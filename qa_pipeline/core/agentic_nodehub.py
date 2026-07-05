from __future__ import annotations

import json
import math
import re
import html
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any

from qa_pipeline.core.paths import QA_CACHE_DIR, REPORTS_DIR
from qa_pipeline.core.runtime_logger import log_event
from qa_pipeline.core.vdi_agent_control import list_agents, create_agent_job
from qa_pipeline.core.distributed_history import append_execution_history
from qa_pipeline.core.central_workspace import resolve_worker_framework_root, with_unique_artifact_env, wrap_command_for_worker_path

AGENTIC_ROOT = QA_CACHE_DIR / "agentic-nodehub-runs"
CENTRAL_REPORT_DIR = REPORTS_DIR / "existing-framework"
MASTER_AGENT_ID = "__MASTER_VM__"
_STATE_LOCK = threading.RLock()
_RCA_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="agentic-rca-heal")



def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _now_id() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _write(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _safe_read(path: Path, default: Any) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        pass
    return default


def _framework_history_dir(framework_path: str) -> Path:
    return Path(framework_path).expanduser().resolve() / ".aiqa-history"


def _framework_reports_dir(framework_path: str) -> Path:
    return _framework_history_dir(framework_path) / "reports"


def _framework_run_dir(framework_path: str, run_id: str) -> Path:
    return _framework_history_dir(framework_path) / "agentic-nodehub-runs" / run_id


def _central_run_dir(run_id: str) -> Path:
    return AGENTIC_ROOT / run_id


def _parse_list(text: str) -> list[str]:
    return [x.strip() for x in re.split(r"[,\n;]+", text or "") if x.strip()]


def _parse_bool(value: Any, default: bool = True) -> bool:
    if value is None or value == "":
        return default
    return str(value).strip().lower() not in {"0", "false", "no", "off", "disabled"}


def _parse_allocation(text: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for item in re.split(r"[,\n;]+", text or ""):
        item = item.strip()
        if not item or "=" not in item:
            continue
        k, v = item.split("=", 1)
        k = k.strip()
        try:
            n = int(str(v).strip())
        except Exception:
            continue
        if k and n > 0:
            out[k] = n
    return out


def _h(value: Any) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def _enforce_central_ai_controls(
    centralize_reports_and_ai_memory: bool,
    ai_heavy_lifting_mode: str,
    worker_ai_role: str,
    codex_patch_location: str,
) -> tuple[bool, str, str, str, list[str]]:
    """Keep all expensive/patching AI work on the Central VM.

    Worker VMs/VDIs are intentionally lightweight: they execute Playwright and
    return stdout/stderr/artifact hints.  Codex/OpenAI/DeepSeek/Ollama patching,
    RAG, report consolidation and AI memory remain on the Central VM to avoid
    spreading secrets, provider auth and patch authority across VDI machines.
    """
    warnings: list[str] = []
    if not centralize_reports_and_ai_memory:
        warnings.append("centralize_reports_and_ai_memory was requested as false, but VM/VDI node-hub forces Central VM as the source of truth for reports and AI memory.")
    if str(ai_heavy_lifting_mode or "").strip() not in {"", "central_brain_worker_evidence"}:
        warnings.append("AI heavy-lifting mode was normalized to central_brain_worker_evidence.")
    if str(worker_ai_role or "").strip() not in {"", "browser_mcp_evidence_only"}:
        warnings.append("Worker AI role was normalized to browser_mcp_evidence_only. Workers do not apply AI patches.")
    if str(codex_patch_location or "").strip() not in {"", "central_only"}:
        warnings.append("Codex patch location was normalized to central_only.")
    return True, "central_brain_worker_evidence", "browser_mcp_evidence_only", "central_only", warnings


def _build_execution_sequence(state: dict[str, Any]) -> list[dict[str, Any]]:
    plan = state.get("plan") or {}
    per_worker = state.get("per_worker") or {}
    sequence: list[dict[str, Any]] = []
    order = 1
    for wid, worker in per_worker.items():
        assigned = list(worker.get("assigned_tests") or [])
        primary_results = list(worker.get("primary_results") or [])
        final_results = list(worker.get("final_rerun_results") or [])
        for idx, test in enumerate(assigned, start=1):
            attempts = [r for r in primary_results if r.get("test") == test]
            final = next((r for r in final_results if r.get("test") == test), None)
            if final:
                status = final.get("status") or "failed"
            elif attempts:
                status = attempts[-1].get("status") or "unknown"
            elif worker.get("phase") == "done" or idx < int(worker.get("next_index") or 0):
                status = "unknown"
            elif idx == int(worker.get("next_index") or 0) + 1 and worker.get("status") == "running":
                status = "queued_or_running"
            else:
                status = "pending"
            sequence.append({
                "order": order,
                "worker_id": wid,
                "worker_name": worker.get("worker_name") or wid,
                "worker_phase": worker.get("phase"),
                "test": test,
                "status": status,
                "primary_attempts": len(attempts),
                "final_rerun_status": final.get("status") if final else "",
                "rca_status": next((e.get("status") for e in (state.get("parallel_rca_events") or []) if e.get("test") == test and e.get("worker_id") == wid), ""),
                "human_intervention": any(h.get("test") == test and h.get("worker_id") == wid for h in (state.get("human_intervention_needed") or [])),
            })
            order += 1
    return sequence


def _progress_summary(state: dict[str, Any]) -> dict[str, Any]:
    sequence = state.get("execution_sequence") or _build_execution_sequence(state)
    total = len(sequence)
    completed_statuses = {"passed", "failed"}
    completed = len([x for x in sequence if x.get("status") in completed_statuses or x.get("final_rerun_status")])
    passed = len([x for x in sequence if x.get("status") == "passed" or x.get("final_rerun_status") == "passed"])
    failed = len([x for x in sequence if x.get("status") == "failed" and x.get("final_rerun_status") != "passed"])
    pending = max(0, total - completed)
    workers = list((state.get("per_worker") or {}).values())
    done_workers = len([w for w in workers if w.get("phase") == "done" or w.get("status") == "done"])
    percent = int((completed / total) * 100) if total else 0
    return {
        "total_tests": total,
        "completed_tests": completed,
        "passed_tests": passed,
        "failed_or_human_intervention_tests": failed,
        "pending_tests": pending,
        "worker_count": len(workers),
        "done_workers": done_workers,
        "progress_percent": percent,
        "single_consolidated_report": True,
        "central_ai_heavy_lifting_only": True,
    }


def _read_selected_tests(framework_path: str, selected_tests: str) -> tuple[Path, list[str]]:
    from qa_pipeline.core.distributed_history import _read_selected_tests as read_existing
    return read_existing(framework_path, selected_tests)


def _build_command(root: Path, tests: list[str], browser: str, headed: bool) -> str:
    from qa_pipeline.core.distributed_history import _build_command as build_existing
    return build_existing(root, tests, browser, headed)


def _match_worker(worker: dict[str, Any], key: str) -> bool:
    key_l = str(key or "").strip().lower()
    return key_l in {
        str(worker.get("agent_id") or "").lower(),
        str(worker.get("agent_name") or "").lower(),
        str(worker.get("hostname") or "").lower(),
        str(worker.get("ip_address") or "").lower(),
        str(worker.get("host") or "").lower(),
        str(worker.get("host_ip") or "").lower(),
    }


def _normalize_execution_target_mode(mode: str, include_master: bool = True) -> str:
    m = str(mode or "").strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "central": "central_only",
        "central_vm": "central_only",
        "local": "central_only",
        "local_only": "central_only",
        "master_only": "central_only",
        "worker": "workers_only",
        "workers": "workers_only",
        "worker_only": "workers_only",
        "remote_only": "workers_only",
        "all": "central_and_workers",
        "hybrid": "central_and_workers",
        "central_workers": "central_and_workers",
        "central_plus_workers": "central_and_workers",
        "central_and_worker": "central_and_workers",
    }
    m = aliases.get(m, m)
    if m not in {"central_only", "workers_only", "central_and_workers"}:
        m = "central_and_workers" if include_master else "workers_only"
    return m


def _master_worker(master_name: str) -> dict[str, Any]:
    return {
        "agent_id": MASTER_AGENT_ID,
        "agent_name": master_name or "Central-VM-Worker",
        "status": "online",
        "is_master_worker": True,
        "hostname": "central-control-plane",
        "host": "127.0.0.1",
        "ip_address": "127.0.0.1",
        "execution_location": "central_vm",
    }


def _workers(include_master: bool, master_name: str, agent_ids: str, execution_target_mode: str = "central_and_workers") -> list[dict[str, Any]]:
    mode = _normalize_execution_target_mode(execution_target_mode, include_master)
    requested = _parse_list(agent_ids)
    online = list_agents().get("agents") or []
    online = [a for a in online if a.get("status") == "online"]
    if requested:
        ordered = []
        for req in requested:
            if req.strip().lower() in {"master", "local", "central", "central-vm", "vm-1", MASTER_AGENT_ID.lower(), (master_name or "").lower()}:
                continue
            for a in online:
                if _match_worker(a, req) and a not in ordered:
                    ordered.append(a)
        online = ordered

    result: list[dict[str, Any]] = []
    if mode in {"central_only", "central_and_workers"}:
        result.append(_master_worker(master_name))
    if mode in {"workers_only", "central_and_workers"}:
        result.extend(online)

    # Central-only is intentionally valid even when no worker agents are online.
    # Workers-only should not silently fall back to central VM because that hides
    # worker setup/network problems. Return an empty worker list so the caller can
    # surface a clear configuration warning.
    if not result and mode != "workers_only":
        result.append(_master_worker(master_name or "Central-VM-Worker"))
    return result


def _assign_tests(tests: list[str], workers: list[dict[str, Any]], allocation_text: str, shard_count: int) -> list[dict[str, Any]]:
    if not workers:
        return []
    counts = _parse_allocation(allocation_text)
    browser_default = "chromium"
    assigned: list[dict[str, Any]] = []
    cursor = 0
    used_workers: list[dict[str, Any]] = []
    for key, count in counts.items():
        worker = next((w for w in workers if _match_worker(w, key)), None)
        if not worker:
            continue
        chunk = tests[cursor:cursor + count]
        cursor += len(chunk)
        used_workers.append(worker)
        assigned.append({**worker, "assigned_tests": chunk, "requested_count": count, "test_count": len(chunk), "browser": browser_default})
    remaining = tests[cursor:]
    if remaining:
        target_workers = [w for w in workers if w not in used_workers] or workers
        if counts:
            # Spread unallocated tests evenly across the selected workers after explicit counts.
            per = math.ceil(len(remaining) / max(1, len(target_workers)))
            chunks = [remaining[i:i+per] for i in range(0, len(remaining), per)]
        else:
            count = max(1, int(shard_count or len(target_workers) or 1))
            if len(target_workers) >= count:
                target_workers = target_workers[:count]
            per = math.ceil(len(remaining) / max(1, len(target_workers)))
            chunks = [remaining[i:i+per] for i in range(0, len(remaining), per)]
        for i, chunk in enumerate(chunks):
            worker = target_workers[i % len(target_workers)]
            existing = next((a for a in assigned if a.get("agent_id") == worker.get("agent_id")), None)
            if existing:
                existing.setdefault("assigned_tests", []).extend(chunk)
                existing["test_count"] = len(existing.get("assigned_tests") or [])
            else:
                assigned.append({**worker, "assigned_tests": chunk, "requested_count": len(chunk), "test_count": len(chunk), "browser": browser_default})
    return [a for a in assigned if a.get("assigned_tests")]


def create_agentic_nodehub_plan(
    framework_path: str,
    selected_tests: str = "",
    browsers: str = "chromium",
    shard_count: int = 5,
    agent_ids: str = "",
    include_master_worker: bool = True,
    master_worker_name: str = "Central-VM-Worker",
    worker_test_allocation: str = "",
    execution_target_mode: str = "central_and_workers",
    immediate_rerun_attempts: int = 1,
    auto_apply_fixes: bool = True,
    ai_provider: str = "codex",
    policy_mode: str = "approved_with_backup",
    worker_workspace_mode: str = "central_shared_workspace",
    central_shared_framework_path: str = "",
    centralize_reports_and_ai_memory: bool = True,
    ai_heavy_lifting_mode: str = "central_brain_worker_evidence",
    worker_ai_role: str = "browser_mcp_evidence_only",
    codex_patch_location: str = "central_only",
) -> dict[str, Any]:
    centralize_reports_and_ai_memory, ai_heavy_lifting_mode, worker_ai_role, codex_patch_location, central_control_warnings = _enforce_central_ai_controls(
        centralize_reports_and_ai_memory, ai_heavy_lifting_mode, worker_ai_role, codex_patch_location
    )
    root, tests = _read_selected_tests(framework_path, selected_tests)
    browser_list = _parse_list(browsers) or ["chromium"]
    execution_target_mode = _normalize_execution_target_mode(execution_target_mode, include_master_worker)
    workers = _workers(include_master_worker, master_worker_name, agent_ids, execution_target_mode)
    shards = _assign_tests(tests, workers, worker_test_allocation, shard_count)
    for idx, shard in enumerate(shards):
        shard["worker_id"] = shard.get("agent_id")
        shard["worker_name"] = shard.get("agent_name")
        shard["browser"] = browser_list[idx % len(browser_list)]
        shard["shard_id"] = f"worker-{idx+1:02d}-{re.sub(r'[^A-Za-z0-9_-]+','-', str(shard.get('agent_name') or 'worker'))[:36]}"
    plan = {
        "ok": bool(tests and shards),
        "stage": "agentic_nodehub_plan_created",
        "generated_at": _now(),
        "framework_path": str(root),
        "total_tests": len(tests),
        "worker_count": len(shards),
        "execution_target_mode": execution_target_mode,
        "include_master_worker": execution_target_mode in {"central_only", "central_and_workers"},
        "master_worker_id": MASTER_AGENT_ID if execution_target_mode in {"central_only", "central_and_workers"} else "",
        "browsers": browser_list,
        "immediate_rerun_attempts": min(1, max(0, int(immediate_rerun_attempts or 0))),
        "auto_apply_fixes": bool(auto_apply_fixes),
        "ai_provider": ai_provider or "codex",
        "policy_mode": policy_mode or "approved_with_backup",
        "worker_workspace_mode": worker_workspace_mode or "central_shared_workspace",
        "central_shared_framework_path": central_shared_framework_path or "",
        "centralize_reports_and_ai_memory": True,
        "single_consolidated_execution_report": True,
        "central_ai_heavy_lifting_only": True,
        "worker_ai_disabled": True,
        "ai_heavy_lifting_mode": ai_heavy_lifting_mode,
        "worker_ai_role": worker_ai_role,
        "codex_patch_location": codex_patch_location,
        "central_control_enforcement_warnings": central_control_warnings,
        "heavy_lifting_balance": {
            "central_vm": ["framework RAG", "AUT/webscraping coordination", "new script generation", "reuse-law validation", "RCA", "self-healing", "source patching with backup/rollback"],
            "worker_vm": ["browser execution", "Playwright MCP/DOM evidence collection where AUT is reachable", "artifact upload to central VM"],
            "rule": "Workers execute and collect evidence only; the Central VM is always source-of-truth for code changes, RCA, self-healing, reports and AI memory."
        },
        "source_of_truth": "central_vm_framework_and_ai_memory",
        "worker_execution_note": "Workers execute browsers/tests from a central shared framework path or their configured workspace, but RCA/self-healing/reports are controlled from the Central VM source-of-truth framework.",
        "worker_test_allocation_raw": worker_test_allocation,
        "available_workers": workers,
        "shards": shards,
        "message": (f"Agentic node-hub plan created: {len(tests)} test(s) assigned across {len(shards)} worker(s). Execution target mode: {execution_target_mode}." if shards else f"No execution workers resolved for mode {execution_target_mode}. Start worker agents or choose Central VM only / Central VM + workers."),
    }
    _write(_framework_reports_dir(str(root)) / "agentic-nodehub-plan.json", plan)
    _write(CENTRAL_REPORT_DIR / "agentic-nodehub-plan.json", plan)
    log_event("agentic_nodehub", plan["message"], status="ok" if plan["ok"] else "warning", progress=100, details={"workers": len(shards), "tests": len(tests)})
    return plan


def _empty_state(run_id: str, plan: dict[str, Any]) -> dict[str, Any]:
    per_worker = {}
    for shard in plan.get("shards") or []:
        per_worker[shard["worker_id"]] = {
            "worker_id": shard["worker_id"],
            "worker_name": shard.get("worker_name"),
            "shard_id": shard.get("shard_id"),
            "browser": shard.get("browser"),
            "assigned_tests": shard.get("assigned_tests") or [],
            "next_index": 0,
            "phase": "primary",
            "primary_results": [],
            "failed_after_retries": [],
            "final_rerun_results": [],
            "status": "queued",
        }
    return {
        "ok": True,
        "run_id": run_id,
        "stage": "agentic_nodehub_run_started",
        "generated_at": _now(),
        "framework_path": plan.get("framework_path"),
        "plan": plan,
        "per_worker": per_worker,
        "events": [],
        "parallel_rca_events": [],
        "self_healing_events": [],
        "execution_sequence": [],
        "gui_progress": {},
        "central_ai_heavy_lifting_only": True,
        "single_consolidated_execution_report": True,
        "message": "Agentic node-hub run started. Each worker runs one test at a time, reruns failures once immediately, compares first/retry failure type, starts RCA/self-healing in parallel after stable same-type failure, continues with next assigned tests, then final-reruns failed tests after its allocation finishes.",
    }


def _save_state(state: dict[str, Any]) -> None:
    # Multiple execution workers can now continue while RCA/self-healing is running
    # in a separate thread. Keep state/report writes serialized so JSON reports do
    # not get partially overwritten by concurrent updates.
    with _STATE_LOCK:
        state["execution_sequence"] = _build_execution_sequence(state)
        state["gui_progress"] = _progress_summary(state)
        run_id = state.get("run_id") or "latest"
        framework_path = state.get("framework_path") or ""
        for p in [_central_run_dir(run_id) / "run-state.json", _framework_run_dir(framework_path, run_id) / "run-state.json"]:
            try:
                _write(p, state)
            except Exception as exc:
                state.setdefault("warnings", []).append(f"state write failed at {p}: {type(exc).__name__}: {exc}")
        try:
            _write(CENTRAL_REPORT_DIR / "active-agentic-nodehub-run.json", state)
            _write(_framework_reports_dir(framework_path) / "active-agentic-nodehub-run.json", state)
        except Exception:
            pass
        write_agentic_nodehub_report(state)


def _load_state(framework_path: str, run_id: str) -> dict[str, Any]:
    candidates = []
    if run_id:
        candidates.append(_central_run_dir(run_id) / "run-state.json")
        if framework_path:
            candidates.append(_framework_run_dir(framework_path, run_id) / "run-state.json")
    if framework_path:
        candidates.append(_framework_reports_dir(framework_path) / "active-agentic-nodehub-run.json")
    candidates.append(CENTRAL_REPORT_DIR / "active-agentic-nodehub-run.json")
    for p in candidates:
        data = _safe_read(p, {})
        if data:
            return data
    return {}


def _status_from_result(result: dict[str, Any]) -> str:
    if result.get("ok") is True:
        return "passed"
    return "failed"


def _failure_type_signature(text: str) -> dict[str, Any]:
    low = (text or "").lower()
    if any(x in low for x in ["strict mode violation", "locator", "getbyrole", "getbytext", "tobevisible", "waiting for", "not found"]):
        kind = "locator_or_dom_change"
    elif any(x in low for x in ["intercepts pointer events", "not enabled", "not visible", "outside of the viewport", "detached", "click timeout"]):
        kind = "interactability_overlay_or_viewport"
    elif any(x in low for x in ["waitforurl", "tohaveurl", "navigation", "networkidle", "timeout"]):
        kind = "navigation_or_timeout"
    elif any(x in low for x in ["401", "403", "500", "net::", "econn", "ssl", "certificate", "vpn", "proxy"]):
        kind = "environment_network_auth_or_data"
    elif any(x in low for x in ["expected", "received", "expect", "assert"]):
        kind = "assertion_or_product_behavior_drift"
    else:
        kind = "unknown_failure_type"
    m = re.search(r"(?:getByRole|getByText|getByTestId|getByLabel|locator)\([^\n\r]{0,180}", text or "", flags=re.I)
    component = (m.group(0) if m else "")[:180]
    return {"kind": kind, "component_hint": component, "signature": (kind + "::" + re.sub(r"[^a-z0-9]+", "-", component.lower()).strip("-")[:80]) if component else kind}


def _compare_first_retry_failure_types(attempt_results: list[dict[str, Any]]) -> dict[str, Any]:
    failed = [a for a in attempt_results or [] if a.get("status") == "failed"]
    if len(failed) < 2:
        return {"available": False, "message": "One retry comparison requires first failure and retry failure evidence."}
    first_text = json.dumps(failed[0], ensure_ascii=False)
    retry_text = json.dumps(failed[1], ensure_ascii=False)
    first = _failure_type_signature(first_text)
    retry = _failure_type_signature(retry_text)
    same = first.get("kind") == retry.get("kind") or first.get("signature") == retry.get("signature")
    return {"available": True, "same_failure_type": same, "first_failure": first, "retry_failure": retry, "decision": "same_component_or_failure_type_fix_candidate" if same else "possibly_flaky_or_state_dependent_collect_more_evidence"}


def _append_event(state: dict[str, Any], event: dict[str, Any]) -> None:
    state.setdefault("events", []).append({"time": _now(), **event})


def _run_one_test_local(root: Path, test_path: str, browser: str, headed: bool) -> dict[str, Any]:
    from qa_pipeline.agents.existing_framework_control.controller import execute_existing_framework
    return execute_existing_framework(
        framework_path=str(root),
        project=browser or "auto",
        headed=headed,
        targets=test_path,
        execution_mode="agentic_nodehub_single_test",
        shards=1,
        use_mcp_assist=True,
    )


def _rca_and_heal(framework_path: str, test_path: str, provider: str, policy_mode: str, auto_apply: bool, base_url: str = "") -> dict[str, Any]:
    from qa_pipeline.agents.existing_framework_control.controller import analyze_existing_failure, self_heal_existing_framework
    rca = analyze_existing_failure(framework_path=framework_path, provider="deterministic", base_url=base_url)
    healing = {"skipped": True, "message": "Auto self-healing disabled for this agentic run."}
    if auto_apply:
        healing = self_heal_existing_framework(framework_path=framework_path, provider=provider or "codex", base_url=base_url, apply_patch=True, policy_mode=policy_mode or "approved_with_backup", human_approval_decision="approve", human_approval_instruction=f"Agentic node-hub auto-approval for stable failed test {test_path}. Apply minimal fix with backup and rollback.", human_approval_safe_files="")
    return {"generated_at": _now(), "test": test_path, "rca": rca, "self_healing": healing, "auto_apply": bool(auto_apply)}


def _start_parallel_rca_and_heal(
    state: dict[str, Any],
    framework_path: str,
    test_path: str,
    worker_id: str,
    provider: str,
    policy_mode: str,
    auto_apply: bool,
    base_url: str = "",
) -> dict[str, Any]:
    """Start RCA/self-healing without blocking the worker's next test.

    The worker continues executing its assigned scripts. Source patching remains
    centralized on the Central VM through the existing self-healing controller,
    while report/state writes are serialized by _STATE_LOCK.
    """
    worker = (state.get("per_worker") or {}).get(worker_id, {})
    event = {
        "generated_at": _now(),
        "status": "running",
        "parallel": True,
        "test": test_path,
        "worker_id": worker_id,
        "worker_name": worker.get("worker_name"),
        "message": "RCA/self-healing started in parallel; execution worker can continue with next assigned test.",
    }
    with _STATE_LOCK:
        state.setdefault("parallel_rca_events", []).append(event)
    _save_state(state)

    def _task() -> None:
        try:
            completed = _rca_and_heal(framework_path, test_path, provider, policy_mode, auto_apply, base_url=base_url)
            completed.update({
                "status": "completed",
                "parallel": True,
                "worker_id": worker_id,
                "worker_name": worker.get("worker_name"),
                "completed_at": _now(),
            })
            with _STATE_LOCK:
                event.update(completed)
                if completed.get("self_healing"):
                    state.setdefault("self_healing_events", []).append({"test": test_path, "worker_id": worker_id, "self_healing": completed.get("self_healing")})
            append_execution_history(framework_path, {"type": "agentic_nodehub_parallel_rca_self_heal", "run_id": state.get("run_id"), "worker_id": worker_id, "test": test_path, "rca_event": completed}, mirror_to_framework=True)
            log_event("agentic_nodehub", f"Parallel RCA/self-healing completed for {test_path}", status="warning", progress=100, details={"worker_id": worker_id, "test": test_path})
        except Exception as exc:
            with _STATE_LOCK:
                event.update({"status": "failed", "completed_at": _now(), "error": f"{type(exc).__name__}: {exc}"})
                state.setdefault("warnings", []).append(f"Parallel RCA/self-healing failed for {test_path}: {type(exc).__name__}: {exc}")
            log_event("agentic_nodehub", f"Parallel RCA/self-healing failed for {test_path}: {type(exc).__name__}: {exc}", status="warning", progress=100)
        finally:
            _save_state(state)

    _RCA_EXECUTOR.submit(_task)
    return event


def _run_master_worker(state: dict[str, Any], worker_id: str, headed: bool, base_url: str) -> dict[str, Any]:
    root = Path(state["framework_path"])
    plan = state.get("plan") or {}
    worker = state["per_worker"][worker_id]
    attempts = int(plan.get("immediate_rerun_attempts") or 0)
    provider = plan.get("ai_provider") or "codex"
    policy_mode = plan.get("policy_mode") or "approved_with_backup"
    auto_apply = bool(plan.get("auto_apply_fixes"))
    worker["status"] = "running"
    for test in list(worker.get("assigned_tests") or []):
        attempt_results = []
        passed = False
        for attempt in range(attempts + 1):
            result = _run_one_test_local(root, test, worker.get("browser") or "auto", headed)
            status = _status_from_result(result)
            attempt_results.append({"attempt": attempt + 1, "status": status, "ok": result.get("ok"), "message": result.get("message"), "html_report": result.get("html_report")})
            _append_event(state, {"worker_id": worker_id, "worker_name": worker.get("worker_name"), "phase": "primary", "test": test, "attempt": attempt + 1, "status": status})
            _save_state(state)
            if status == "passed":
                passed = True
                break
        failure_comparison = _compare_first_retry_failure_types(attempt_results)
        worker.setdefault("primary_results", []).append({"test": test, "status": "passed" if passed else "failed", "attempts": attempt_results, "first_retry_failure_comparison": failure_comparison})
        if not passed:
            worker.setdefault("failed_after_retries", []).append(test)
            _append_event(state, {"worker_id": worker_id, "worker_name": worker.get("worker_name"), "phase": "failure_type_comparison", "test": test, "status": "same_type" if failure_comparison.get("same_failure_type") else "needs_review", "details": failure_comparison})
            _start_parallel_rca_and_heal(state, str(root), test, worker_id, provider, policy_mode, auto_apply, base_url=base_url)
            _save_state(state)
    # After this worker's allocation finishes, automatically rerun failed tests once.
    worker["phase"] = "final_rerun"
    for test in list(worker.get("failed_after_retries") or []):
        result = _run_one_test_local(root, test, worker.get("browser") or "auto", headed)
        status = _status_from_result(result)
        worker.setdefault("final_rerun_results", []).append({"test": test, "status": status, "ok": result.get("ok"), "message": result.get("message")})
        _append_event(state, {"worker_id": worker_id, "worker_name": worker.get("worker_name"), "phase": "final_rerun_after_fix", "test": test, "status": status})
        if status == "failed":
            state.setdefault("human_intervention_needed", []).append({"test": test, "worker_id": worker_id, "reason": "Still failing after one immediate retry, RCA/self-healing and final rerun."})
        _save_state(state)
    worker["phase"] = "done"
    worker["status"] = "done"
    _save_state(state)
    return worker


def _schedule_remote_test(state: dict[str, Any], worker_id: str, test_path: str, phase: str = "primary", attempt: int = 0) -> dict[str, Any]:
    # IMPORTANT: framework_path below is always the Central VM source-of-truth path.
    # Remote workers may run from a Central SMB/UNC share or a mapped workspace, but
    # RCA/self-healing/history remains centralized against this central framework.
    root = Path(state["framework_path"])
    plan = state.get("plan") or {}
    worker = state["per_worker"][worker_id]
    base_command = _build_command(root, [test_path], worker.get("browser") or "auto", headed=bool(plan.get("headed", True)))
    command = with_unique_artifact_env(base_command, run_id=str(state.get("run_id") or "run"), worker_id=worker_id, phase=phase, attempt=attempt, test_path=test_path)
    worker_visible_root, workspace_note = resolve_worker_framework_root(
        central_framework_path=str(root),
        worker=worker,
        mode=str(plan.get("worker_workspace_mode") or "central_shared_workspace"),
        central_shared_framework_path=str(plan.get("central_shared_framework_path") or ""),
    )
    command, job_working_dir = wrap_command_for_worker_path(command, worker_visible_root, fallback_working_dir=str(worker.get("workspace_root") or "C:\\"))
    metadata = {
        "agentic_nodehub": True,
        "framework_path": str(root),
        "central_framework_path": str(root),
        "worker_visible_framework_root": worker_visible_root,
        "worker_workspace_mode": plan.get("worker_workspace_mode"),
        "workspace_note": workspace_note,
        "centralized_reports_and_ai_memory": True,
        "single_consolidated_execution_report": True,
        "central_ai_heavy_lifting_only": True,
        "worker_ai_disabled": True,
        "ai_heavy_lifting_mode": plan.get("ai_heavy_lifting_mode") or "central_brain_worker_evidence",
        "worker_ai_role": plan.get("worker_ai_role") or "browser_mcp_evidence_only",
        "codex_patch_location": plan.get("codex_patch_location") or "central_only",
        "mcp_evidence_expected": str(plan.get("worker_ai_role") or "").lower() in {"browser_mcp_evidence_only", "browser_execution_plus_mcp_evidence", "mcp_evidence"},
        "run_id": state.get("run_id"),
        "worker_id": worker_id,
        "worker_name": worker.get("worker_name"),
        "test_path": test_path,
        "phase": phase,
        "attempt": attempt,
    }
    job = create_agent_job(worker_id, command=command, working_dir=job_working_dir, job_type="agentic_nodehub_test", created_by="agentic_nodehub", metadata=metadata, timeout_seconds=7200)
    _append_event(state, {"worker_id": worker_id, "worker_name": worker.get("worker_name"), "phase": phase, "test": test_path, "attempt": attempt + 1, "status": "queued", "job_id": job.get("job_id"), "worker_visible_framework_root": worker_visible_root, "workspace_note": workspace_note})
    worker["status"] = "running"
    worker["worker_visible_framework_root"] = worker_visible_root
    worker["workspace_note"] = workspace_note
    _save_state(state)
    return job


def _schedule_next_remote(state: dict[str, Any], worker_id: str) -> None:
    worker = state["per_worker"][worker_id]
    if worker.get("phase") == "primary":
        idx = int(worker.get("next_index") or 0)
        tests = worker.get("assigned_tests") or []
        if idx < len(tests):
            worker["next_index"] = idx + 1
            _schedule_remote_test(state, worker_id, tests[idx], phase="primary", attempt=0)
            return
        worker["phase"] = "final_rerun"
        worker["final_rerun_queue"] = list(worker.get("failed_after_retries") or [])
        worker["final_rerun_index"] = 0
    if worker.get("phase") == "final_rerun":
        idx = int(worker.get("final_rerun_index") or 0)
        tests = worker.get("final_rerun_queue") or []
        if idx < len(tests):
            worker["final_rerun_index"] = idx + 1
            _schedule_remote_test(state, worker_id, tests[idx], phase="final_rerun", attempt=0)
            return
        worker["phase"] = "done"
        worker["status"] = "done"
        _save_state(state)


def handle_agentic_nodehub_test_completion(job: dict[str, Any]) -> dict[str, Any]:
    meta = job.get("metadata") or {}
    framework_path = meta.get("framework_path") or job.get("working_dir") or ""
    run_id = meta.get("run_id") or ""
    worker_id = meta.get("worker_id") or job.get("agent_id") or ""
    test_path = meta.get("test_path") or ""
    phase = meta.get("phase") or "primary"
    attempt = int(meta.get("attempt") or 0)
    state = _load_state(framework_path, run_id)
    if not state:
        return {"ok": False, "message": "Agentic node-hub run state was not found."}
    worker = (state.get("per_worker") or {}).get(worker_id)
    if not worker:
        return {"ok": False, "message": f"Worker {worker_id} not found in run state."}
    status = "passed" if int(job.get("return_code") or 1) == 0 else "failed"
    result = {"test": test_path, "phase": phase, "attempt": attempt + 1, "status": status, "job_id": job.get("job_id"), "stdout_tail": job.get("stdout_tail"), "stderr_tail": job.get("stderr_tail")}
    _append_event(state, {"worker_id": worker_id, "worker_name": worker.get("worker_name"), "phase": phase, "test": test_path, "attempt": attempt + 1, "status": status, "job_id": job.get("job_id")})
    plan = state.get("plan") or {}
    max_attempts = int(plan.get("immediate_rerun_attempts") or 0)
    if phase == "primary":
        if status == "failed" and attempt < max_attempts:
            worker.setdefault("primary_results", []).append(result)
            _save_state(state)
            _schedule_remote_test(state, worker_id, test_path, phase="primary", attempt=attempt + 1)
            return {"ok": True, "message": f"Immediate rerun queued for {test_path} on {worker.get('worker_name')}."}
        final_status = "passed" if status == "passed" else "failed"
        previous_attempts = [r for r in (worker.get("primary_results") or []) if r.get("test") == test_path]
        comparison = _compare_first_retry_failure_types([*previous_attempts, result])
        result["first_retry_failure_comparison"] = comparison
        worker.setdefault("primary_results", []).append(result)
        if final_status == "failed":
            worker.setdefault("failed_after_retries", []).append(test_path)
            _append_event(state, {"worker_id": worker_id, "worker_name": worker.get("worker_name"), "phase": "failure_type_comparison", "test": test_path, "status": "same_type" if comparison.get("same_failure_type") else "needs_review", "details": comparison})
            _start_parallel_rca_and_heal(state, framework_path, test_path, worker_id, plan.get("ai_provider") or "codex", plan.get("policy_mode") or "approved_with_backup", bool(plan.get("auto_apply_fixes")), base_url=plan.get("base_url") or "")
        _save_state(state)
        # Schedule the next test immediately; RCA/self-healing continues in the
        # Central VM control plane and updates the same run report when complete.
        _schedule_next_remote(state, worker_id)
    else:
        worker.setdefault("final_rerun_results", []).append(result)
        if status == "failed":
            state.setdefault("human_intervention_needed", []).append({"test": test_path, "worker_id": worker_id, "reason": "Still failing after final rerun on remote worker."})
        _save_state(state)
        _schedule_next_remote(state, worker_id)
    _refresh_overall_stage(state)
    _save_state(state)
    return {"ok": True, "run_id": run_id, "status": status, "message": f"Agentic node-hub completion handled for {test_path}."}


def _refresh_overall_stage(state: dict[str, Any]) -> None:
    workers = list((state.get("per_worker") or {}).values())
    done = [w for w in workers if w.get("phase") == "done" or w.get("status") == "done"]
    total = len(workers)
    if total and len(done) >= total:
        state["stage"] = "agentic_nodehub_run_completed"
        state["ok"] = not bool(state.get("human_intervention_needed"))
        state["message"] = f"Agentic node-hub run completed: {len(done)}/{total} workers done. Human intervention needed: {len(state.get('human_intervention_needed') or [])}."
    else:
        state["stage"] = "agentic_nodehub_run_in_progress"
        state["message"] = f"Agentic node-hub run in progress: {len(done)}/{total} workers done. Parallel RCA events: {len(state.get('parallel_rca_events') or [])}."


def run_agentic_nodehub(
    framework_path: str,
    selected_tests: str = "",
    browsers: str = "chromium",
    shard_count: int = 5,
    agent_ids: str = "",
    include_master_worker: bool = True,
    master_worker_name: str = "Central-VM-Worker",
    worker_test_allocation: str = "",
    execution_target_mode: str = "central_and_workers",
    immediate_rerun_attempts: int = 1,
    auto_apply_fixes: bool = True,
    ai_provider: str = "codex",
    policy_mode: str = "approved_with_backup",
    headed: bool = True,
    run_on_agents: bool = True,
    base_url: str = "",
    worker_workspace_mode: str = "central_shared_workspace",
    central_shared_framework_path: str = "",
    centralize_reports_and_ai_memory: bool = True,
    ai_heavy_lifting_mode: str = "central_brain_worker_evidence",
    worker_ai_role: str = "browser_mcp_evidence_only",
    codex_patch_location: str = "central_only",
) -> dict[str, Any]:
    plan = create_agentic_nodehub_plan(
        framework_path, selected_tests, browsers, shard_count, agent_ids,
        include_master_worker, master_worker_name, worker_test_allocation,
        execution_target_mode, immediate_rerun_attempts, auto_apply_fixes,
        ai_provider, policy_mode, worker_workspace_mode, central_shared_framework_path,
        centralize_reports_and_ai_memory, ai_heavy_lifting_mode, worker_ai_role,
        codex_patch_location,
    )
    plan["headed"] = bool(headed)
    plan["base_url"] = base_url or ""
    run_id = "agentic-run-" + _now_id()
    state = _empty_state(run_id, plan)
    _save_state(state)
    master_ids = [w for w in (state.get("per_worker") or {}) if w == MASTER_AGENT_ID or state["per_worker"][w].get("is_master_worker")]
    remote_ids = [w for w in (state.get("per_worker") or {}) if w not in master_ids]

    # Queue remote workers first so VM-2/VM-3/VDIs can start while VM-1 master
    # worker is also executing locally. This preserves node-hub parallelism.
    if run_on_agents and remote_ids:
        for wid in remote_ids:
            _schedule_next_remote(state, wid)
    # Start master VM worker locally. It is a real worker and can execute its own
    # allocated tests while remote agents are polling/running their first jobs.
    if master_ids:
        with ThreadPoolExecutor(max_workers=len(master_ids)) as pool:
            futures = [pool.submit(_run_master_worker, state, wid, headed, base_url) for wid in master_ids]
            for fut in as_completed(futures):
                try:
                    fut.result()
                except Exception as exc:
                    state.setdefault("warnings", []).append(f"Master worker failed: {type(exc).__name__}: {exc}")
    if remote_ids and not run_on_agents:
        # If no remote agent execution is requested, run remote allocations locally as fallback.
        with ThreadPoolExecutor(max_workers=max(1, len(remote_ids))) as pool:
            futures = [pool.submit(_run_master_worker, state, wid, headed, base_url) for wid in remote_ids]
            for fut in as_completed(futures):
                try:
                    fut.result()
                except Exception as exc:
                    state.setdefault("warnings", []).append(f"Local fallback worker failed: {type(exc).__name__}: {exc}")
    _refresh_overall_stage(state)
    _save_state(state)
    append_execution_history(str(plan.get("framework_path") or framework_path), {"type": "agentic_nodehub_run", **state, "framework_html_report": str(_framework_reports_dir(str(plan.get('framework_path'))) / "agentic-nodehub-report.html")}, mirror_to_framework=True)
    log_event("agentic_nodehub", state.get("message", "Agentic node-hub run state updated."), status="running" if remote_ids and run_on_agents else ("done" if state.get("ok") else "warning"), progress=100, details={"run_id": run_id})
    framework_url_path = str(plan.get("framework_path") or framework_path).replace("\\", "/")
    return {**state, "html_report_url": "/api/module2/framework-artifact/agentic-nodehub-report?framework_path=" + framework_url_path, "framework_html_report": str(_framework_reports_dir(str(plan.get("framework_path"))) / "agentic-nodehub-report.html")}


def get_agentic_nodehub_status(framework_path: str = "", run_id: str = "") -> dict[str, Any]:
    state = _load_state(framework_path, run_id)
    if not state:
        return {"ok": False, "message": "No active agentic node-hub run state found yet."}
    _refresh_overall_stage(state)
    _save_state(state)
    framework_url_path = str(state.get("framework_path") or framework_path).replace("\\", "/")
    return {**state, "html_report_url": "/api/module2/framework-artifact/agentic-nodehub-report?framework_path=" + framework_url_path}


def write_agentic_nodehub_report(state: dict[str, Any]) -> dict[str, str]:
    framework_path = str(state.get("framework_path") or "")
    plan = state.get("plan") or {}
    sequence = state.get("execution_sequence") or _build_execution_sequence(state)
    progress = state.get("gui_progress") or _progress_summary({**state, "execution_sequence": sequence})

    worker_rows = []
    for wid, worker in (state.get("per_worker") or {}).items():
        assigned = worker.get("assigned_tests") or []
        primary = worker.get("primary_results") or []
        rerun = worker.get("final_rerun_results") or []
        worker_rows.append(
            "<tr>"
            f"<td>{_h(worker.get('worker_name') or wid)}</td>"
            f"<td>{_h(worker.get('phase'))}</td>"
            f"<td>{_h(worker.get('status'))}</td>"
            f"<td>{len(assigned)}</td>"
            f"<td>{len([r for r in primary if r.get('status')=='passed'])}</td>"
            f"<td>{len([r for r in primary if r.get('status')=='failed'])}</td>"
            f"<td>{len(rerun)}</td>"
            f"<td><pre>{_h(json.dumps(worker, indent=2, ensure_ascii=False)[:5000])}</pre></td>"
            "</tr>"
        )

    sequence_rows = []
    for item in sequence:
        sequence_rows.append(
            "<tr>"
            f"<td>{_h(item.get('order'))}</td>"
            f"<td>{_h(item.get('worker_name'))}</td>"
            f"<td>{_h(item.get('worker_phase'))}</td>"
            f"<td><code>{_h(item.get('test'))}</code></td>"
            f"<td>{_h(item.get('status'))}</td>"
            f"<td>{_h(item.get('primary_attempts'))}</td>"
            f"<td>{_h(item.get('final_rerun_status'))}</td>"
            f"<td>{_h(item.get('rca_status'))}</td>"
            f"<td>{'Yes' if item.get('human_intervention') else 'No'}</td>"
            "</tr>"
        )

    events = ''.join(
        f"<li><b>{_h(e.get('time'))}</b> [{_h(e.get('worker_name') or e.get('worker_id'))}] {_h(e.get('phase'))} — <code>{_h(e.get('test'))}</code> — {_h(e.get('status'))}</li>"
        for e in (state.get("events") or [])[-150:]
    )
    rca_events = state.get('parallel_rca_events') or []
    heal_events = state.get('self_healing_events') or []
    central_warnings = plan.get('central_control_enforcement_warnings') or []
    warning_html = ''.join(f"<li>{_h(w)}</li>" for w in central_warnings)
    html_doc = f"""<!doctype html><html><head><meta charset='utf-8'/><title>Single Consolidated Agentic Node-Hub Execution Report</title>
<style>
body{{font-family:Segoe UI,Arial,sans-serif;background:#f8fafc;color:#0f172a;margin:24px}}
table{{width:100%;border-collapse:collapse;background:white;margin-top:10px}}td,th{{border:1px solid #cbd5e1;padding:8px;vertical-align:top}}th{{background:#1e293b;color:white}}
pre{{white-space:pre-wrap;max-height:260px;overflow:auto;background:#0f172a;color:#d1fae5;padding:8px;border-radius:6px}}
.card{{background:white;border:1px solid #cbd5e1;border-radius:12px;padding:16px;margin:14px 0}}
.good{{background:#ecfdf5;border-color:#86efac}}.warn{{background:#fff7ed;border-color:#fdba74}}.grid{{display:grid;grid-template-columns:repeat(4,minmax(150px,1fr));gap:12px}}.metric{{font-size:26px;font-weight:700}}
code{{background:#eef2ff;padding:1px 4px;border-radius:4px}}
</style></head><body>
<h1>Single Consolidated Agentic Node-Hub Execution Report</h1>
<div class='card good'><b>Centralized architecture confirmed:</b> Central VM is the controller, source-of-truth framework, AI memory owner, RCA/self-healing owner and patch authority. Worker VMs/VDIs execute Playwright browser commands and return evidence only. Codex/OpenAI/DeepSeek/Ollama keys and source patching are not required on workers.</div>
<div class='grid'>
  <div class='card'><div class='metric'>{_h(progress.get('total_tests'))}</div>Total tests</div>
  <div class='card'><div class='metric'>{_h(progress.get('completed_tests'))}</div>Completed</div>
  <div class='card'><div class='metric'>{_h(progress.get('passed_tests'))}</div>Passed / recovered</div>
  <div class='card'><div class='metric'>{_h(progress.get('failed_or_human_intervention_tests'))}</div>Needs attention</div>
</div>
<div class='card'><b>Run:</b> {_h(state.get('run_id'))}<br/><b>Stage:</b> {_h(state.get('stage'))}<br/><b>Progress:</b> {_h(progress.get('progress_percent'))}%<br/><b>Central source-of-truth framework:</b> {_h(framework_path)}<br/><b>Worker workspace mode:</b> {_h(plan.get('worker_workspace_mode'))}<br/><b>Central shared path visible to workers:</b> {_h(plan.get('central_shared_framework_path') or 'not configured')}<br/><b>AI heavy lifting mode:</b> {_h(plan.get('ai_heavy_lifting_mode') or 'central_brain_worker_evidence')}<br/><b>Worker AI role:</b> {_h(plan.get('worker_ai_role') or 'browser_mcp_evidence_only')}<br/><b>Codex patch location:</b> {_h(plan.get('codex_patch_location') or 'central_only')}<br/><b>Single consolidated report:</b> Yes<br/><b>Message:</b> {_h(state.get('message'))}</div>
<div class='card warn'><h2>Central AI control guard</h2><ul>{warning_html or '<li>No override was requested. Central-only AI heavy lifting is enforced.</li>'}</ul><p>Workers may collect Playwright/MCP/browser evidence, but they do not run provider-based patching and do not update source files directly.</p></div>
<div class='card'><h2>Execution sequence and completion status</h2><table><thead><tr><th>#</th><th>Worker</th><th>Worker phase</th><th>Test script</th><th>Status</th><th>Primary attempts</th><th>Final rerun</th><th>RCA/self-heal</th><th>Human intervention</th></tr></thead><tbody>{''.join(sequence_rows) or '<tr><td colspan="9">No execution sequence available yet. Refresh status while workers are running.</td></tr>'}</tbody></table></div>
<div class='card'><h2>Worker summary</h2><table><thead><tr><th>Worker</th><th>Phase</th><th>Status</th><th>Assigned</th><th>Passed attempts</th><th>Failed attempts</th><th>Final reruns</th><th>Details</th></tr></thead><tbody>{''.join(worker_rows) or '<tr><td colspan="8">No workers in run state.</td></tr>'}</tbody></table></div>
<div class='card'><h2>Recent execution events</h2><ul>{events or '<li>No events yet.</li>'}</ul></div>
<div class='card'><h2>Parallel RCA / Self-healing events</h2><pre>{_h(json.dumps({'parallel_rca_events': rca_events, 'self_healing_events': heal_events, 'human_intervention_needed': state.get('human_intervention_needed') or []}, indent=2, ensure_ascii=False)[:24000])}</pre></div>
</body></html>"""
    central = CENTRAL_REPORT_DIR / "agentic-nodehub-report.html"
    central.parent.mkdir(parents=True, exist_ok=True)
    central.write_text(html_doc, encoding="utf-8")
    _write(CENTRAL_REPORT_DIR / "agentic-nodehub-report.json", {**state, "execution_sequence": sequence, "gui_progress": progress})
    # Alias names make it clear to business users that there is one combined report.
    (CENTRAL_REPORT_DIR / "single-consolidated-agentic-nodehub-report.html").write_text(html_doc, encoding="utf-8")
    _write(CENTRAL_REPORT_DIR / "single-consolidated-agentic-nodehub-report.json", {**state, "execution_sequence": sequence, "gui_progress": progress})
    out = {"central_html_report": str(central), "central_single_consolidated_report": str(CENTRAL_REPORT_DIR / "single-consolidated-agentic-nodehub-report.html")}
    try:
        local = _framework_reports_dir(framework_path)
        local.mkdir(parents=True, exist_ok=True)
        (local / "agentic-nodehub-report.html").write_text(html_doc, encoding="utf-8")
        (local / "single-consolidated-agentic-nodehub-report.html").write_text(html_doc, encoding="utf-8")
        _write(local / "agentic-nodehub-report.json", {**state, "execution_sequence": sequence, "gui_progress": progress})
        _write(local / "single-consolidated-agentic-nodehub-report.json", {**state, "execution_sequence": sequence, "gui_progress": progress})
        out["framework_html_report"] = str(local / "agentic-nodehub-report.html")
        out["framework_json_report"] = str(local / "agentic-nodehub-report.json")
        out["framework_single_consolidated_report"] = str(local / "single-consolidated-agentic-nodehub-report.html")
    except Exception as exc:
        out["framework_report_warning"] = f"{type(exc).__name__}: {exc}"
    return out

