from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from qa_pipeline.agentic.code_graph import build_code_graph
from qa_pipeline.agentic.functional_walkthrough import run_functional_walkthrough
from qa_pipeline.agentic.playwright_doctor import diagnose_and_prepare
from qa_pipeline.agentic.rca_guard import enforce_grounded_rca, healing_allowed
from qa_pipeline.agents.existing_framework_control.controller import (
    analyze_existing_failure,
    analyze_existing_framework,
    self_heal_existing_framework,
)
from qa_pipeline.core.distributed_history import run_distributed_plan
from qa_pipeline.mcp.framework_full_control_fix import (
    ai_full_control_fix_framework_issues,
    plan_full_control_framework_fix_issues,
    apply_approved_full_control_plan,
)
from qa_pipeline.mcp.mcp_readiness_preflight import (
    fix_mcp_preflight_build_errors_with_ai,
    run_mcp_readiness_preflight,
)


def _tool(name: str, description: str) -> Callable[[Callable[..., Any]], Any]:
    try:
        from langchain_core.tools import tool
        return tool(name, description=description)
    except Exception:
        def identity(fn: Callable[..., Any]) -> Callable[..., Any]:
            fn.name = name  # type: ignore[attr-defined]
            fn.description = description  # type: ignore[attr-defined]
            return fn
        return identity




@_tool("run_ai_functional_walkthrough", "Treat normalized functional testcase steps as browser goals, adapt to live page transitions, insert verified prerequisite actions, capture test-data bindings and exact locators without generating code.")
def run_ai_functional_walkthrough(
    framework_path: str,
    feature: str,
    provider: str = "deterministic",
    model: str = "",
    base_url: str = "",
    credential_token: str = "",
    browser_name: str = "chromium",
    browser_executable: str = "",
    headed: bool = True,
    supervised: bool = True,
    allow_mutating_actions: bool = False,
    allow_cross_origin: bool = False,
    max_scenarios: int = 20,
    max_steps_per_scenario: int = 80,
    confidence_threshold: float = 0.72,
    manual_takeover_seconds: int = 90,
    action_timeout_seconds: int = 20,
    max_intermediate_actions: int = 6,
    capture_screenshots: bool = False,
) -> dict[str, Any]:
    return run_functional_walkthrough(
        framework_path=framework_path,
        feature=feature,
        provider=provider,
        model=model,
        base_url=base_url,
        credential_token=credential_token,
        browser_name=browser_name,
        browser_executable=browser_executable,
        headed=headed,
        supervised=supervised,
        allow_mutating_actions=allow_mutating_actions,
        allow_cross_origin=allow_cross_origin,
        max_scenarios=max_scenarios,
        max_steps_per_scenario=max_steps_per_scenario,
        confidence_threshold=confidence_threshold,
        manual_takeover_seconds=manual_takeover_seconds,
        action_timeout_seconds=action_timeout_seconds,
        max_intermediate_actions=max_intermediate_actions,
        capture_screenshots=capture_screenshots,
    )


@_tool("inspect_existing_framework", "Inspect an existing Playwright framework without modifying files.")
def inspect_existing_framework(framework_path: str, provider: str = "deterministic", model: str = "", base_url: str = "", progress_run_id: str = "") -> dict[str, Any]:
    return analyze_existing_framework(framework_path, provider=provider, model=model or "llama3", base_url=base_url, reuse_cache=True, progress_run_id=progress_run_id)


@_tool("index_framework_code_graph", "Create a structural code knowledge graph and optionally augment it with Graphify.")
def index_framework_code_graph(framework_path: str, use_graphify: bool = True) -> dict[str, Any]:
    return build_code_graph(framework_path, use_graphify=use_graphify)


@_tool("diagnose_playwright_framework", "Find Playwright package/config/build gaps and optionally apply safe fixes and run validation commands.")
def diagnose_playwright_framework(
    framework_path: str,
    apply_fixes: bool = False,
    run_commands: bool = True,
    reuse_cached_validation: bool = False,
    preserve_command_source_changes: bool = False,
    approved_files: str = "",
    standard_profile: str = "astraheal-adaptive-enterprise-v1",
    progress_run_id: str = "",
) -> dict[str, Any]:
    files = [x.strip().replace("\\", "/") for x in approved_files.replace(";", "\n").splitlines() if x.strip()]
    progress = None
    if progress_run_id:
        def progress(stage: str, pct: int, message: str, details: dict[str, Any] | None = None) -> None:
            try:
                from qa_pipeline.agentic.events import publish
                publish(progress_run_id, "playwright_gap", message, status="running", progress=max(1, min(99, pct)), payload=details or {})
            except Exception:
                pass
    return diagnose_and_prepare(
        framework_path,
        apply_fixes=apply_fixes,
        run_commands=run_commands,
        progress=progress,
        reuse_cached_validation=reuse_cached_validation,
        preserve_command_source_changes=preserve_command_source_changes,
        approved_files=files or None,
        standard_profile=standard_profile,
    )


@_tool("prepare_playwright_mcp", "Run Playwright MCP readiness checks and return exact blockers.")
def prepare_playwright_mcp(framework_path: str, project: str = "auto", browser: str = "chromium") -> dict[str, Any]:
    return run_mcp_readiness_preflight(framework_path, project=project, browser=browser, run_build=True, run_test_list=True, check_browser=True)


@_tool("fix_mcp_build_blockers", "Apply selected-provider and safe deterministic fixes for MCP build blockers.")
def fix_mcp_build_blockers(framework_path: str, provider: str = "deterministic", model: str = "", project: str = "auto", browser: str = "chromium", human_instruction: str = "") -> dict[str, Any]:
    return fix_mcp_preflight_build_errors_with_ai(framework_path, provider=provider, model=model, project=project, browser=browser, human_instruction=human_instruction)


@_tool("full_control_framework_fix", "Run the existing backup-first full-control framework repair workflow.")
def full_control_framework_fix(framework_path: str, provider: str = "deterministic", model: str = "", project: str = "auto", browser: str = "chromium", human_instruction: str = "") -> dict[str, Any]:
    return ai_full_control_fix_framework_issues(framework_path, provider=provider, model=model, project=project, browser=browser, human_instruction=human_instruction)


@_tool("plan_full_control_framework_fix", "Prepare exact AI framework patch diffs for human approval without changing source files.")
def plan_full_control_framework_fix(framework_path: str, provider: str = "codex", model: str = "", project: str = "auto", browser: str = "chromium", human_instruction: str = "") -> dict[str, Any]:
    return plan_full_control_framework_fix_issues(framework_path, provider=provider, model=model, project=project, browser=browser, human_instruction=human_instruction)


@_tool("apply_approved_full_control_framework_fix", "Apply only a previously generated exact AI patch proposal within the human-approved file list.")
def apply_approved_full_control_framework_fix(framework_path: str, proposal_json: str, approved_files: str, project: str = "auto", browser: str = "chromium") -> dict[str, Any]:
    try:
        proposal = json.loads(proposal_json or "{}")
    except Exception:
        proposal = {}
    files = [x.strip().replace("\\", "/") for x in approved_files.replace(";", "\n").splitlines() if x.strip()]
    return apply_approved_full_control_plan(framework_path, proposal, files, project=project, browser=browser)


@_tool("execute_distributed_playwright", "Run a central/worker distributed Playwright execution plan.")
def execute_distributed_playwright(framework_path: str, selected_tests: str = "", browsers: str = "chromium", shard_count: int = 2, agent_ids: str = "", headed: bool = False, run_on_agents: bool = True, execution_target_mode: str = "central_and_workers", central_shared_framework_path: str = "", tests_per_shard: int = 0, run_role: str = "first_run") -> dict[str, Any]:
    return run_distributed_plan(
        framework_path=framework_path,
        selected_tests=selected_tests,
        browsers=browsers,
        shard_count=shard_count,
        agent_ids=agent_ids,
        headed=headed,
        run_on_agents=run_on_agents,
        execution_target_mode=execution_target_mode,
        central_shared_framework_path=central_shared_framework_path,
        tests_per_shard=tests_per_shard,
        run_role=run_role,
    )


@_tool("grounded_existing_framework_rca", "Analyse the latest existing-framework failure and refuse a fix when evidence is insufficient.")
def grounded_existing_framework_rca(framework_path: str, provider: str = "deterministic", model: str = "", base_url: str = "") -> dict[str, Any]:
    raw = analyze_existing_failure(framework_path, provider=provider, model=model or "llama3", base_url=base_url)
    return enforce_grounded_rca(raw)


@_tool("apply_grounded_self_healing", "Apply a backup-first self-healing patch only when the RCA evidence gate allows it.")
def apply_grounded_self_healing(framework_path: str, provider: str = "deterministic", model: str = "", base_url: str = "", policy_mode: str = "approved_with_backup", human_instruction: str = "") -> dict[str, Any]:
    raw = analyze_existing_failure(framework_path, provider=provider, model=model or "llama3", base_url=base_url)
    allowed, guarded = healing_allowed(raw)
    if not allowed:
        return {"ok": False, "stage": "healing_refused_insufficient_evidence", "rca": guarded, "message": guarded.get("message", "No idea to fix")}
    result = self_heal_existing_framework(
        framework_path=framework_path,
        provider=provider,
        model=model or "llama3",
        base_url=base_url,
        apply_patch=True,
        policy_mode=policy_mode,
        human_approval_decision="approve",
        human_approval_instruction=human_instruction,
    )
    return {"ok": bool(result.get("ok")), "rca": guarded, "healing": result, "message": result.get("message", "Grounded self-healing completed.")}


ALL_TOOLS = [
    run_ai_functional_walkthrough,
    inspect_existing_framework,
    index_framework_code_graph,
    diagnose_playwright_framework,
    prepare_playwright_mcp,
    fix_mcp_build_blockers,
    full_control_framework_fix,
    plan_full_control_framework_fix,
    apply_approved_full_control_framework_fix,
    execute_distributed_playwright,
    grounded_existing_framework_rca,
    apply_grounded_self_healing,
]
