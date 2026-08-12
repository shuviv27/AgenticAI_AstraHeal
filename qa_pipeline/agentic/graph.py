from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from qa_pipeline.agentic.events import publish
from qa_pipeline.agentic.functional_walkthrough import run_functional_walkthrough
from qa_pipeline.agentic.framework_cache import compute_framework_fingerprint
from qa_pipeline.agentic.memory import get_checkpointer, get_framework_memory, put_framework_memory
from qa_pipeline.agentic.observability import configure_langsmith, traceable_agent
from qa_pipeline.agentic.playwright_standard import STANDARD_ID, get_playwright_standards
from qa_pipeline.agentic.provider_gateway import provider_gateway
from qa_pipeline.agentic.rca_guard import enforce_grounded_rca
from qa_pipeline.agentic.state import AstraHealAgentState
from qa_pipeline.core.operation_control import check_cancelled
from qa_pipeline.agentic.tools import (
    apply_grounded_self_healing,
    apply_approved_full_control_framework_fix,
    diagnose_playwright_framework,
    execute_distributed_playwright,
    fix_mcp_build_blockers,
    grounded_existing_framework_rca,
    index_framework_code_graph,
    inspect_existing_framework,
    plan_full_control_framework_fix,
    prepare_playwright_mcp,
)
from qa_pipeline.core.paths import REPORTS_DIR

AGENT_ORDER: dict[str, list[str]] = {
    "functional_walkthrough": ["functional_walkthrough", "review", "report"],
    "deep_learn": ["framework_discovery", "code_graph", "playwright_gap", "review", "report"],
    "framework_fix": ["framework_discovery", "code_graph", "playwright_gap", "fix", "validation", "review", "report"],
    "mcp_prepare": ["framework_discovery", "playwright_gap", "mcp", "validation", "review", "report"],
    "distributed_execute": ["playwright_gap", "execution", "rca", "review", "report"],
    "rca": ["rca", "review", "report"],
    "self_heal": ["rca", "fix", "validation", "review", "report"],
    "full_pipeline": ["framework_discovery", "code_graph", "playwright_gap", "fix", "validation", "execution", "rca", "review", "report"],
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _invoke(tool_obj: Any, **kwargs: Any) -> Any:
    if hasattr(tool_obj, "invoke"):
        return tool_obj.invoke(kwargs)
    return tool_obj(**kwargs)


def _completed(state: AstraHealAgentState, name: str) -> dict[str, Any]:
    done = list(state.get("completed_agents") or [])
    if name not in done:
        done.append(name)
    return {"completed_agents": done, "step_count": int(state.get("step_count") or 0) + 1}


def _event(state: AstraHealAgentState, agent: str, message: str, progress: int, *, status: str = "running", payload: dict[str, Any] | None = None) -> None:
    publish(str(state.get("run_id") or "unknown"), agent, message, status=status, progress=progress, payload=payload or {})


def supervisor_node(state: AstraHealAgentState) -> dict[str, Any]:
    workflow = str(state.get("workflow") or "deep_learn")
    sequence = AGENT_ORDER.get(workflow, AGENT_ORDER["deep_learn"])
    completed = set(state.get("completed_agents") or [])
    candidates = [name for name in sequence if name not in completed]
    if not candidates:
        return {"next_agent": "end", "routing_reason": "All workflow agents completed.", "status": "completed"}
    selected = candidates[0]
    reason = f"Next required agent in the guarded {workflow} workflow."

    # A framework repair proposal must stop at the human approval boundary.
    # Routing directly to report preserves the proposal in the run result and
    # prevents validation/review nodes from implying that an unapplied repair
    # was executed.
    approval_boundary = bool(state.get("approval_required") and not state.get("approved") and "report" in candidates)
    if approval_boundary:
        selected = "report"
        reason = "Exact framework changes are ready for human review; repository writes are blocked until explicit file approval is supplied."

    # The supervisor may ask the selected LLM to choose among valid next nodes,
    # but deterministic ordering remains the safety fallback and authority.
    provider = str(state.get("provider") or "deterministic")
    if not approval_boundary and provider not in {"", "deterministic", "rules", "none"} and len(candidates) > 1:
        prompt = json.dumps({
            "workflow": workflow,
            "objective": state.get("objective", ""),
            "completed_agents": sorted(completed),
            "allowed_next_agents": candidates,
            "errors": state.get("errors", [])[-5:],
            "gap_summary": (state.get("gap_report") or {}).get("message", ""),
            "instruction": "Choose exactly one allowed_next_agents value. Return JSON {next_agent, reason}. Do not invent another agent.",
        }, ensure_ascii=False)
        decision = provider_gateway.invoke_json(
            prompt,
            system="You are the AstraHeal LangGraph supervisor. Route only among the allowed guarded agents; deterministic validators remain authoritative.",
            provider=provider,
            model=str(state.get("model") or ""),
            repo_root=state.get("framework_path") or None,
            timeout_seconds=60,
        )
        parsed = decision.get("json") or {}
        proposed = str(parsed.get("next_agent") or "")
        if proposed in candidates:
            selected = proposed
            reason = str(parsed.get("reason") or "LLM supervisor selected an allowed next agent.")
    labels = {
        "functional_walkthrough": "AI functional browser walkthrough",
        "framework_discovery": "framework structure analysis",
        "code_graph": "code relationship indexing",
        "playwright_gap": "Playwright configuration health check",
        "mcp": "Playwright MCP preparation",
        "fix": "guarded framework repair",
        "validation": "framework validation",
        "execution": "test execution",
        "rca": "evidence-based failure analysis",
        "review": "independent review",
        "report": "report and memory update",
    }
    _event(
        state,
        "supervisor",
        f"Next step: {labels.get(selected, selected.replace('_', ' '))}.",
        min(95, 3 + int(state.get("step_count") or 0) * 8),
        payload={"next_agent": selected, "workflow": workflow, "technical_reason": reason},
    )
    return {"next_agent": selected, "routing_reason": reason, "status": "running"}


@traceable_agent("AstraHeal Framework Discovery Agent")
def framework_discovery_node(state: AstraHealAgentState) -> dict[str, Any]:
    _event(state, "framework_discovery", "Learning repository structure, tests, fixtures, pages, aliases and framework conventions.", 10)
    result = _invoke(
        inspect_existing_framework,
        framework_path=str(state.get("framework_path") or ""),
        provider="deterministic",
        model=str(state.get("model") or ""),
        base_url=str(state.get("base_url") or ""),
        progress_run_id=str(state.get("run_id") or ""),
    )
    selected_provider = str(state.get("provider") or "deterministic")
    if selected_provider not in {"", "deterministic", "rules", "none"}:
        cache_hit = bool(result.get("cache_hit") or (result.get("cache_reuse") or {}).get("used"))
        prior = get_framework_memory(str(state.get("framework_path") or ""), "framework_inventory") if cache_hit else {}
        prior_value = (prior.get("framework_inventory") or {}).get("value") if isinstance(prior, dict) else None
        same_fp = bool(prior_value and (prior_value.get("cache_reuse") or {}).get("fingerprint") == (result.get("cache_reuse") or {}).get("fingerprint"))
        if same_fp and prior_value.get("autonomous_ai_understanding"):
            result["autonomous_ai_understanding"] = prior_value.get("autonomous_ai_understanding")
            result["ai_provider_used"] = prior_value.get("ai_provider_used") or selected_provider
            result["ai_memory_reused"] = True
            _event(state, "framework_discovery", "Reused the first-pass AI architecture interpretation from durable framework memory; no repeated LLM walkthrough was required.", 23, status="done", payload={"cache_hit": True})
        else:
            _event(state, "framework_discovery", "Repository is new/changed; asking the selected AI provider for a grounded architecture interpretation.", 22)
            ai_prompt = json.dumps({
                "framework_inventory": result,
                "required_output": ["architecture_summary", "project_structure", "reusability_map", "configuration_gaps", "execution_risks", "recommended_next_actions"],
                "rules": ["Return JSON only", "Do not invent files", "Mark unknown facts as unknown", "Use only supplied inventory evidence"],
            }, ensure_ascii=False, default=str)[:45000]
            ai_result = provider_gateway.invoke_json(
                ai_prompt,
                system="You are the AstraHeal framework intelligence agent. Explain only evidence present in the supplied repository inventory.",
                provider=selected_provider,
                model=str(state.get("model") or ""),
                repo_root=state.get("framework_path") or None,
                timeout_seconds=180,
            )
            result["autonomous_ai_understanding"] = ai_result.get("json") if ai_result.get("ok") else {"used": True, "ok": False, "error": ai_result.get("error")}
            result["ai_provider_used"] = selected_provider
    path = str(state.get("framework_path") or "")
    put_framework_memory(path, "framework_inventory", result, confidence=0.95, source="framework_discovery_agent")
    _event(state, "framework_discovery", result.get("message") or "Framework discovery completed.", 24, status="done", payload={"spec_count": result.get("spec_count"), "executable_spec_count": result.get("executable_spec_count")})
    return {"inventory": result, "framework_intelligence": result.get("agentic_framework_understanding") or {}, **_completed(state, "framework_discovery")}


@traceable_agent("AstraHeal Code Graph Agent")
def code_graph_node(state: AstraHealAgentState) -> dict[str, Any]:
    use_graphify = bool((state.get("input_payload") or {}).get("use_graphify", True))
    _event(state, "code_graph", "Indexing code relationships with the built-in graph; Graphify augmentation is optional.", 28)
    result = _invoke(index_framework_code_graph, framework_path=str(state.get("framework_path") or ""), use_graphify=use_graphify)
    put_framework_memory(str(state.get("framework_path") or ""), "code_graph_summary", {k: result.get(k) for k in ("node_count", "edge_count", "file_count", "roles", "unresolved_imports", "graphify")}, confidence=0.92, source="code_graph_agent")
    _event(state, "code_graph", result.get("message") or "Code graph indexing completed.", 40, status="done" if result.get("ok") else "warning", payload={"nodes": result.get("node_count"), "edges": result.get("edge_count"), "graphify_used": (result.get("graphify") or {}).get("used")})
    return {"code_graph": result, **_completed(state, "code_graph")}


@traceable_agent("AstraHeal Playwright Gap Agent")
def playwright_gap_node(state: AstraHealAgentState) -> dict[str, Any]:
    payload = state.get("input_payload") or {}
    workflow = str(state.get("workflow") or "")
    standard_profile = str(payload.get("standard_profile") or STANDARD_ID)
    # The framework-fix workflow is deliberately repair-before-execute. Its
    # gap pass prepares exact human-reviewable package/config changes first;
    # the validation node runs the mandatory npm -> Chromium -> build sequence
    # only after the approved repair has been applied. This avoids RACPAD-size
    # npm/workspace installs being performed twice and avoids knowingly
    # invoking `npm run build` before a missing build contract can be approved.
    run_prerequisite_commands = bool(payload.get("run_commands", False)) and workflow != "framework_fix"
    _event(
        state,
        "playwright_gap",
        "Checking package.json, tsconfig, Playwright config and test discovery; repair proposals are prepared before prerequisite commands."
        if workflow == "framework_fix"
        else "Checking package.json, tsconfig, Playwright config, test discovery and prerequisite commands.",
        44,
    )
    result = _invoke(
        diagnose_playwright_framework,
        framework_path=str(state.get("framework_path") or ""),
        apply_fixes=False,
        run_commands=run_prerequisite_commands,
        reuse_cached_validation=workflow == "deep_learn",
        preserve_command_source_changes=True,
        standard_profile=standard_profile,
        progress_run_id=str(state.get("run_id") or ""),
    )
    put_framework_memory(str(state.get("framework_path") or ""), "playwright_gap_report", result, confidence=0.98, source="playwright_gap_agent")
    analysis = result.get("analysis_after") or result.get("analysis_before") or {}
    requirements = analysis.get("package_requirements") or {}
    _event(
        state,
        "playwright_gap",
        result.get("message") or "Playwright gap diagnosis completed.",
        54,
        status="done" if result.get("ok") else "warning",
        payload={
            "gap_count": analysis.get("gap_count"),
            "critical_gap_count": analysis.get("critical_gap_count"),
            "workspace_aware": bool(requirements.get("workspace_aware")),
            "recommended_build_script": requirements.get("recommended_build_script"),
            "build_strategy": requirements.get("build_strategy"),
            "missing_dev_dependencies": requirements.get("missing_dev_dependencies") or {},
        },
    )
    return {"gap_report": result, **_completed(state, "playwright_gap")}


@traceable_agent("AstraHeal Playwright MCP Agent")
def mcp_node(state: AstraHealAgentState) -> dict[str, Any]:
    payload = state.get("input_payload") or {}
    _event(state, "mcp", "Preparing Playwright MCP readiness evidence.", 58)
    preflight = _invoke(prepare_playwright_mcp, framework_path=str(state.get("framework_path") or ""), project=str(payload.get("project") or "auto"), browser=str(payload.get("browser") or "chromium"))
    result: dict[str, Any] = {"preflight": preflight}
    if preflight.get("action_required") and state.get("approved"):
        _event(state, "mcp", "MCP blockers found; applying approved selected-provider readiness fixes.", 62)
        result["fix"] = _invoke(
            fix_mcp_build_blockers,
            framework_path=str(state.get("framework_path") or ""),
            provider=str(state.get("provider") or "deterministic"),
            model=str(state.get("model") or ""),
            project=str(payload.get("project") or "auto"),
            browser=str(payload.get("browser") or "chromium"),
            human_instruction=str(payload.get("human_instruction") or ""),
        )
    elif preflight.get("action_required"):
        result["approval_required"] = True
        result["message"] = "MCP blockers were identified. Approve safe/full-control repair before files are modified."
    _event(state, "mcp", result.get("message") or preflight.get("message") or "MCP readiness completed.", 68, status="done" if preflight.get("ok") else "warning")
    return {"plan": {**(state.get("plan") or {}), "mcp": result}, **_completed(state, "mcp")}


@traceable_agent("AstraHeal Framework Repair Agent")
def fix_node(state: AstraHealAgentState) -> dict[str, Any]:
    payload = state.get("input_payload") or {}
    workflow = str(state.get("workflow") or "")

    # Framework repair is intentionally a two-run, two-phase contract:
    # (1) prepare exact deterministic + AI diffs without writes;
    # (2) apply only files explicitly approved from that exact proposal.
    if workflow == "framework_fix":
        framework_path = str(state.get("framework_path") or "")
        standard_profile = str(payload.get("standard_profile") or STANDARD_ID)
        if not state.get("approved"):
            gap = state.get("gap_report") or {}
            deterministic = dict(gap.get("change_proposal") or {})
            deterministic_changes = list(deterministic.get("changes") or [])
            ai_proposal: dict[str, Any] = {"ok": True, "changes": [], "proposed_files": [], "message": "No additional AI source patch was requested."}
            selected_provider = str(state.get("provider") or "deterministic")

            # Ask an LLM for an exact replacement plan only when validated
            # blockers remain and a real AI provider was selected. Planning is
            # isolated/read-only; it cannot edit the selected framework.
            if not gap.get("ok") and selected_provider not in {"", "deterministic", "rules", "none", "rule_based"}:
                _event(state, "fix", "Validated blockers remain. Preparing exact AI file replacements for human review; source writes are still blocked.", 61)
                ai_proposal = _invoke(
                    plan_full_control_framework_fix,
                    framework_path=framework_path,
                    provider=selected_provider,
                    model=str(state.get("model") or ""),
                    project=str(payload.get("project") or "auto"),
                    browser=str(payload.get("browser") or "chromium"),
                    human_instruction=str(payload.get("human_instruction") or ""),
                )

            ai_changes = list(ai_proposal.get("changes") or [])
            proposed_files = sorted({
                str(x.get("file") or "").replace("\\", "/")
                for x in deterministic_changes + ai_changes
                if str(x.get("file") or "").strip()
            })
            if not proposed_files and gap.get("ok"):
                message = "Framework validation found no file changes requiring approval."
                _event(state, "fix", message, 68, status="done")
                return {"patch_result": {"ok": True, "changed_files": [], "message": message}, "approval_required": False, **_completed(state, "fix")}

            standard_def = get_playwright_standards()
            selected_standard = next((p for p in (standard_def.get("profiles") or []) if p.get("id") == standard_profile), standard_def)
            approval_payload = {
                "type": "framework_repair_approval",
                "framework_path": framework_path,
                "framework_fingerprint": compute_framework_fingerprint(framework_path).get("fingerprint"),
                "standard_profile": standard_profile,
                "standard": selected_standard,
                "standard_audit": gap.get("standard_audit") or deterministic.get("standard_audit") or {},
                "required_validation_sequence": deterministic.get("required_validation_sequence") or (gap.get("analysis_after") or {}).get("required_commands") or [],
                "deterministic_proposal": deterministic,
                "ai_proposal": ai_proposal,
                "proposed_files": proposed_files,
                "proposed_file_count": len(proposed_files),
                "human_approval_required": True,
                "message": "Review the exact file-by-file diffs below. AstraHeal will apply only files you explicitly approve; all other repository files remain blocked from modification.",
            }
            _event(
                state,
                "fix",
                f"Human approval required for {len(proposed_files)} proposed file(s): {', '.join(proposed_files) if proposed_files else 'no deterministic file; review AI blocker details' }.",
                68,
                status="waiting_for_approval",
                payload={"proposed_files": proposed_files, "standard_profile": standard_profile},
            )
            return {
                "patch_result": {"ok": False, "approval_required": True, "approval_payload": approval_payload, "message": approval_payload["message"]},
                "approval_required": True,
                "approval_payload": approval_payload,
                **_completed(state, "fix"),
            }

        repair_plan = payload.get("framework_repair_plan") or {}
        approved_files_raw = payload.get("approved_files") or []
        if isinstance(approved_files_raw, str):
            approved_files = [x.strip().replace("\\", "/") for x in approved_files_raw.replace(";", "\n").splitlines() if x.strip()]
        else:
            approved_files = [str(x).strip().replace("\\", "/") for x in approved_files_raw if str(x).strip()]
        if not isinstance(repair_plan, dict) or not repair_plan.get("framework_fingerprint"):
            message = "Approved framework repair was rejected because the exact prior proposal was not supplied. Run Validate & fix framework again to create a reviewable plan."
            _event(state, "fix", message, 62, status="waiting_for_approval")
            return {"patch_result": {"ok": False, "approval_required": True, "message": message}, "approval_required": True, **_completed(state, "fix")}
        current_fp = compute_framework_fingerprint(framework_path).get("fingerprint")
        if current_fp != repair_plan.get("framework_fingerprint"):
            message = "Framework contents changed after the proposal was created. The stale approval was rejected; re-analyse so the user can review fresh diffs."
            _event(state, "fix", message, 62, status="waiting_for_approval", payload={"proposal_fingerprint": repair_plan.get("framework_fingerprint"), "current_fingerprint": current_fp})
            return {"patch_result": {"ok": False, "approval_required": True, "stale_proposal": True, "message": message}, "approval_required": True, **_completed(state, "fix")}
        if not approved_files:
            message = "No files were approved. AstraHeal made no repository changes."
            _event(state, "fix", message, 62, status="waiting_for_approval")
            return {"patch_result": {"ok": False, "approval_required": True, "message": message}, "approval_required": True, **_completed(state, "fix")}

        _event(state, "fix", f"Applying only the {len(approved_files)} human-approved file(s): {', '.join(approved_files)}.", 64)
        deterministic_proposal = repair_plan.get("deterministic_proposal") or {}
        deterministic_files = {str(x.get("file") or "").replace("\\", "/") for x in (deterministic_proposal.get("changes") or []) if isinstance(x, dict)}
        safe_approved = [x for x in approved_files if x in deterministic_files]
        if safe_approved:
            safe = _invoke(
                diagnose_playwright_framework,
                framework_path=framework_path,
                apply_fixes=True,
                run_commands=False,
                approved_files="\n".join(safe_approved),
                standard_profile=standard_profile,
                progress_run_id=str(state.get("run_id") or ""),
            )
        else:
            safe = _invoke(
                diagnose_playwright_framework,
                framework_path=framework_path,
                apply_fixes=False,
                run_commands=False,
                standard_profile=standard_profile,
                progress_run_id=str(state.get("run_id") or ""),
            )
        ai_proposal = repair_plan.get("ai_proposal") or {}
        ai_files = {str(x.get("file") or "").replace("\\", "/") for x in (ai_proposal.get("changes") or []) if isinstance(x, dict)}
        ai_approved = [x for x in approved_files if x in ai_files]
        ai_result: dict[str, Any] = {"ok": True, "changed_files": [], "message": "No AI source replacements were approved."}
        if ai_approved:
            ai_result = _invoke(
                apply_approved_full_control_framework_fix,
                framework_path=framework_path,
                proposal_json=json.dumps(ai_proposal, ensure_ascii=False, default=str),
                approved_files="\n".join(ai_approved),
                project=str(payload.get("project") or "auto"),
                browser=str(payload.get("browser") or "chromium"),
            )
        changed = sorted(set((safe.get("safe_fixes") or {}).get("changed_files") or []) | set(ai_result.get("changed_files") or []))
        for rel in changed:
            _event(state, "fix", f"Approved change applied: {rel}", 72, payload={"file": rel})
        result = {
            "ok": True,
            "human_approved_files": approved_files,
            "changed_files": changed,
            "safe_preparation": safe,
            "ai_approved_apply": ai_result,
            "message": f"Applied {len(changed)} approved framework file change(s). Validation will now run the required command sequence.",
        }
        _event(state, "fix", result["message"], 76, status="done")
        return {"patch_result": result, "approval_required": False, **_completed(state, "fix")}

    if not state.get("approved"):
        message = "Human approval is required before repository files are modified."
        _event(state, "fix", message, 62, status="waiting_for_approval")
        return {"patch_result": {"ok": False, "approval_required": True, "message": message}, "approval_required": True, **_completed(state, "fix")}

    _event(state, "fix", "Creating backups and applying safe Playwright configuration fixes.", 62)
    safe = _invoke(diagnose_playwright_framework, framework_path=str(state.get("framework_path") or ""), apply_fixes=True, run_commands=True)
    result: dict[str, Any] = {"safe_preparation": safe, "ok": safe.get("ok", False)}
    if workflow == "full_pipeline" and not safe.get("ok"):
        _event(state, "fix", "Validated blockers remain; invoking the guarded full-control repair agent.", 70)
        result["full_control"] = _invoke(
            full_control_framework_fix,
            framework_path=str(state.get("framework_path") or ""),
            provider=str(state.get("provider") or "deterministic"),
            model=str(state.get("model") or ""),
            project=str(payload.get("project") or "auto"),
            browser=str(payload.get("browser") or "chromium"),
            human_instruction=str(payload.get("human_instruction") or ""),
        )
        result["ok"] = bool((result.get("full_control") or {}).get("ok"))
    elif workflow == "self_heal":
        result["healing"] = _invoke(
            apply_grounded_self_healing,
            framework_path=str(state.get("framework_path") or ""),
            provider=str(state.get("provider") or "deterministic"),
            model=str(state.get("model") or ""),
            base_url=str(state.get("base_url") or ""),
            human_instruction=str(payload.get("human_instruction") or ""),
        )
        result["ok"] = bool((result.get("healing") or {}).get("ok"))
    _event(state, "fix", "Framework repair completed with validation evidence." if result.get("ok") else "Framework repair completed but validated blockers remain.", 76, status="done" if result.get("ok") else "warning")
    return {"patch_result": result, **_completed(state, "fix")}


@traceable_agent("AstraHeal Validation Agent")
def validation_node(state: AstraHealAgentState) -> dict[str, Any]:
    payload = state.get("input_payload") or {}
    approved_files_raw = payload.get("approved_files") or []
    approved_files = approved_files_raw if isinstance(approved_files_raw, str) else "\n".join(str(x) for x in approved_files_raw)
    validation_sequence = (get_playwright_standards().get("required_validation_sequence") or [])
    _event(
        state,
        "validation",
        "Running the approved framework through the required npm registry → npm install → Chromium install → npm run build sequence.",
        78,
        payload={"required_validation_sequence": validation_sequence},
    )
    result = _invoke(
        diagnose_playwright_framework,
        framework_path=str(state.get("framework_path") or ""),
        apply_fixes=False,
        run_commands=True,
        preserve_command_source_changes=True,
        approved_files=approved_files,
        standard_profile=str(payload.get("standard_profile") or STANDARD_ID),
        progress_run_id=str(state.get("run_id") or ""),
    )
    _event(state, "validation", result.get("message") or "Validation completed.", 84, status="done" if result.get("ok") else "warning")
    return {"validation": result, **_completed(state, "validation")}


@traceable_agent("AstraHeal AI Functional Walkthrough Agent")
def functional_walkthrough_node(state: AstraHealAgentState) -> dict[str, Any]:
    payload = state.get("input_payload") or {}
    feature = str(payload.get("feature") or "module2_feature")
    _event(state, "functional_walkthrough", "Opening a supervised adaptive browser. Each testcase line is treated as a goal; the agent may insert verified prerequisite UI actions when the live application flow differs. No Playwright code will be generated in this stage.", 8)

    def publish_step(agent: str, message: str, progress: int, status: str, data: dict[str, Any] | None) -> None:
        _event(state, agent, message, progress, status=status, payload=data or {})

    result = run_functional_walkthrough(
        framework_path=str(state.get("framework_path") or ""),
        feature=feature,
        provider=str(state.get("provider") or "deterministic"),
        model=str(state.get("model") or ""),
        base_url=str(state.get("base_url") or payload.get("base_url") or ""),
        credential_token=str(state.get("run_id") or ""),
        browser_name=str(payload.get("walkthrough_browser") or "chromium"),
        browser_executable=str(payload.get("walkthrough_browser_executable") or ""),
        headed=bool(payload.get("walkthrough_headed", True)),
        supervised=bool(payload.get("walkthrough_supervised", True)),
        allow_mutating_actions=bool(payload.get("walkthrough_allow_mutations", False)),
        allow_cross_origin=bool(payload.get("walkthrough_allow_cross_origin", False)),
        max_scenarios=int(payload.get("walkthrough_max_scenarios") or 20),
        max_steps_per_scenario=int(payload.get("walkthrough_max_steps") or 80),
        confidence_threshold=float(payload.get("walkthrough_confidence_threshold") or 0.72),
        manual_takeover_seconds=int(payload.get("walkthrough_manual_takeover_seconds") or 90),
        action_timeout_seconds=int(payload.get("walkthrough_action_timeout_seconds") or 20),
        max_intermediate_actions=int(payload.get("walkthrough_max_intermediate_actions") or 6),
        capture_screenshots=bool(payload.get("walkthrough_capture_screenshots", False)),
        event_publisher=publish_step,
    )
    put_framework_memory(str(state.get("framework_path") or ""), f"functional_walkthrough:{feature}", result, confidence=0.98 if result.get("ready_for_generation") else 0.5, source="functional_walkthrough_agent")
    _event(state, "functional_walkthrough", result.get("message") or "Functional walkthrough completed.", 88, status="done" if result.get("ready_for_generation") else "warning", payload={"ready_for_generation": result.get("ready_for_generation"), "verified_locator_count": result.get("verified_locator_count")})
    return {"walkthrough": result, **_completed(state, "functional_walkthrough")}


@traceable_agent("AstraHeal Distributed Execution Agent")
def execution_node(state: AstraHealAgentState) -> dict[str, Any]:
    p = state.get("input_payload") or {}
    _event(state, "execution", "Starting central/worker distributed Playwright execution.", 64)
    result = _invoke(
        execute_distributed_playwright,
        framework_path=str(state.get("framework_path") or ""),
        selected_tests=str(p.get("selected_tests") or ""),
        browsers=str(p.get("browsers") or p.get("browser") or "chromium"),
        shard_count=int(p.get("shard_count") or 2),
        agent_ids=str(p.get("agent_ids") or ""),
        headed=bool(p.get("headed", False)),
        run_on_agents=bool(p.get("run_on_agents", True)),
        execution_target_mode=str(p.get("execution_target_mode") or "central_and_workers"),
        central_shared_framework_path=str(p.get("central_shared_framework_path") or ""),
        tests_per_shard=int(p.get("tests_per_shard") or 0),
        run_role=str(p.get("run_role") or "first_run"),
    )
    _event(state, "execution", result.get("message") or "Distributed execution completed.", 82, status="done" if result.get("ok") else "warning", payload={"distributed_run_id": result.get("run_id"), "stage": result.get("stage")})
    return {"execution": result, **_completed(state, "execution")}


@traceable_agent("AstraHeal Evidence RCA Agent")
def rca_node(state: AstraHealAgentState) -> dict[str, Any]:
    execution = state.get("execution") or {}
    walkthrough = state.get("walkthrough") or {}
    if execution and execution.get("ok"):
        result = {"ok": True, "no_failure": True, "no_idea_to_fix": False, "message": "Execution passed; RCA was not required.", "should_patch": False}
    else:
        _event(state, "rca", "Collecting failure evidence and calculating a grounding confidence score.", 86)
        result = _invoke(
            grounded_existing_framework_rca,
            framework_path=str(state.get("framework_path") or ""),
            provider=str(state.get("provider") or "deterministic"),
            model=str(state.get("model") or ""),
            base_url=str(state.get("base_url") or ""),
        )
        result = enforce_grounded_rca(result)
    _event(state, "rca", result.get("message") or ("No idea to fix" if result.get("no_idea_to_fix") else "Grounded RCA completed."), 91, status="warning" if result.get("no_idea_to_fix") else "done", payload={"confidence": result.get("confidence"), "no_idea_to_fix": result.get("no_idea_to_fix")})
    return {"rca": result, "confidence": float(result.get("confidence") or 0), "no_idea_to_fix": bool(result.get("no_idea_to_fix")), **_completed(state, "rca")}


@traceable_agent("AstraHeal Independent Review Agent")
def review_node(state: AstraHealAgentState) -> dict[str, Any]:
    findings: list[dict[str, Any]] = list(state.get("findings") or [])
    gaps = state.get("gap_report") or {}
    validation = state.get("validation") or {}
    execution = state.get("execution") or {}
    walkthrough = state.get("walkthrough") or {}
    rca = state.get("rca") or {}
    if gaps and not gaps.get("ok"):
        findings.append({"severity": "warning", "area": "framework", "message": gaps.get("message", "Framework gaps remain.")})
    if validation and not validation.get("ok"):
        findings.append({"severity": "high", "area": "validation", "message": validation.get("message", "Validation failed.")})
    if walkthrough and not walkthrough.get("ready_for_generation"):
        findings.append({"severity": "high", "area": "functional_walkthrough", "message": walkthrough.get("message", "Functional walkthrough is incomplete; generation should remain blocked.")})
    if execution and not execution.get("ok"):
        findings.append({"severity": "high", "area": "execution", "message": execution.get("message", "Execution failed.")})
    if rca.get("no_idea_to_fix"):
        findings.append({"severity": "warning", "area": "rca", "message": "No idea to fix: evidence threshold was not met, so no patch should be applied."})
    approved = not any(f.get("severity") in {"critical", "high"} for f in findings)
    plan = {**(state.get("plan") or {}), "review": {"approved": approved, "findings": findings, "reviewed_at": _now()}}
    _event(state, "review", "Independent review passed." if approved else "Independent review found unresolved blockers.", 96, status="done" if approved else "warning", payload={"approved": approved, "finding_count": len(findings)})
    return {"findings": findings, "plan": plan, **_completed(state, "review")}


@traceable_agent("AstraHeal Reporting Agent")
def report_node(state: AstraHealAgentState) -> dict[str, Any]:
    root = REPORTS_DIR / "agentic"
    root.mkdir(parents=True, exist_ok=True)
    run_id = str(state.get("run_id") or "unknown")
    output = {
        "ok": not any(f.get("severity") in {"critical", "high"} for f in (state.get("findings") or [])),
        "message": "Exact framework repair proposal is ready for human approval; no proposed source/config change has been applied." if state.get("approval_required") else "Autonomous multi-agent workflow completed.",
        "run_id": run_id,
        "thread_id": state.get("thread_id"),
        "workflow": state.get("workflow"),
        "framework_path": state.get("framework_path"),
        "provider": state.get("provider"),
        "model": state.get("model"),
        "completed_agents": state.get("completed_agents", []),
        "inventory": state.get("inventory", {}),
        "code_graph": state.get("code_graph", {}),
        "gap_report": state.get("gap_report", {}),
        "patch_result": state.get("patch_result", {}),
        "validation": state.get("validation", {}),
        "execution": state.get("execution", {}),
        "walkthrough": state.get("walkthrough", {}),
        "rca": state.get("rca", {}),
        "findings": state.get("findings", []),
        "approval_required": bool(state.get("approval_required")),
        "approval_payload": state.get("approval_payload", {}),
        "langsmith": configure_langsmith(),
        "generated_at": _now(),
    }
    json_path = root / f"{run_id}.json"
    md_path = root / f"{run_id}.md"
    json_path.write_text(json.dumps(output, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    md_path.write_text(
        "# AstraHeal autonomous multi-agent run\n\n"
        f"- Run: `{run_id}`\n- Workflow: `{output['workflow']}`\n- Framework: `{output['framework_path']}`\n"
        f"- Provider: `{output['provider']}`\n- Result: `{'PASS' if output['ok'] else 'REVIEW REQUIRED'}`\n\n"
        "## Agent sequence\n\n" + "\n".join(f"- {a}" for a in output["completed_agents"]) + "\n\n"
        "## Findings\n\n" + ("\n".join(f"- **{f.get('severity','info')}** [{f.get('area','general')}] {f.get('message','')}" for f in output["findings"]) or "- No blocking findings.") + "\n",
        encoding="utf-8",
    )
    output["report_json"] = str(json_path)
    output["report_markdown"] = str(md_path)
    put_framework_memory(str(state.get("framework_path") or ""), "latest_agentic_run", {"run_id": run_id, "workflow": output["workflow"], "ok": output["ok"], "report_json": str(json_path)}, confidence=1.0, source="reporting_agent")
    _event(state, "report", "Workflow report and durable framework memory were saved.", 100, status="done", payload={"ok": output["ok"], "report_json": str(json_path)})
    return {"report": output, "output": output, "status": "completed", **_completed(state, "report")}


NODE_FUNCTIONS: dict[str, Callable[[AstraHealAgentState], dict[str, Any]]] = {
    "supervisor": supervisor_node,
    "functional_walkthrough": functional_walkthrough_node,
    "framework_discovery": framework_discovery_node,
    "code_graph": code_graph_node,
    "playwright_gap": playwright_gap_node,
    "mcp": mcp_node,
    "fix": fix_node,
    "validation": validation_node,
    "execution": execution_node,
    "rca": rca_node,
    "review": review_node,
    "report": report_node,
}


def build_graph() -> Any:
    configure_langsmith()
    try:
        from langgraph.graph import END, START, StateGraph
    except Exception:
        return None
    builder = StateGraph(AstraHealAgentState)
    for name, fn in NODE_FUNCTIONS.items():
        builder.add_node(name, fn)
    builder.add_edge(START, "supervisor")
    for name in NODE_FUNCTIONS:
        if name not in {"supervisor", "report"}:
            builder.add_edge(name, "supervisor")
    builder.add_edge("report", END)
    destinations = {name: name for name in NODE_FUNCTIONS if name != "supervisor"}
    destinations["end"] = END
    builder.add_conditional_edges("supervisor", lambda s: str(s.get("next_agent") or "end"), destinations)
    checkpointer = get_checkpointer()
    return builder.compile(checkpointer=checkpointer) if checkpointer is not None else builder.compile()


def run_fallback(initial_state: AstraHealAgentState, on_update: Callable[[str, dict[str, Any]], None] | None = None) -> dict[str, Any]:
    """Deterministic compatibility runner used only when LangGraph is not installed."""
    state: dict[str, Any] = dict(initial_state)
    sequence = AGENT_ORDER.get(str(state.get("workflow") or "deep_learn"), AGENT_ORDER["deep_learn"])
    for name in sequence:
        check_cancelled()
        update = NODE_FUNCTIONS[name](state)  # type: ignore[arg-type]
        state.update(update)
        if on_update:
            on_update(name, update)
        if state.get("approval_required") and not state.get("approved") and name != "report":
            report_update = report_node(state)  # type: ignore[arg-type]
            state.update(report_update)
            if on_update:
                on_update("report", report_update)
            break
    return state
