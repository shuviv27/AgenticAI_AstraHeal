from __future__ import annotations

import json
import uuid
from typing import Any

from fastapi import APIRouter, Form, Query
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse

from qa_pipeline.agentic.code_graph import build_code_graph, query_code_graph
from qa_pipeline.agentic.credential_vault import credential_profile_summary, get_feature_credential_profiles, store_ephemeral_credentials
from qa_pipeline.agentic.events import stream_sse
from qa_pipeline.agentic.functional_walkthrough import load_walkthrough_evidence, walkthrough_html_report_path
from qa_pipeline.agentic.memory import get_framework_memory, get_run, list_runs
from qa_pipeline.agentic.playwright_standard import get_playwright_standards
from qa_pipeline.agentic.runtime import cancel_run, runtime_status, start_run

router = APIRouter(prefix="/api/agentic", tags=["autonomous-multi-agent"])


def _json_object(raw: str) -> dict[str, Any]:
    try:
        value = json.loads(raw or "{}")
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


@router.get("/status")
def agentic_status() -> dict[str, Any]:
    return runtime_status()


@router.get("/playwright-standards")
def agentic_playwright_standards() -> dict[str, Any]:
    """Expose the framework contract before users choose analysis/standardization."""
    return {"ok": True, **get_playwright_standards()}


@router.post("/runs/start")
def agentic_start_run(
    workflow: str = Form("deep_learn"),
    framework_path: str = Form(""),
    provider: str = Form("deterministic"),
    model: str = Form(""),
    base_url: str = Form(""),
    objective: str = Form(""),
    approved: bool = Form(False),
    use_graphify: bool = Form(True),
    run_commands: bool = Form(False),
    project: str = Form("auto"),
    browser: str = Form("chromium"),
    selected_tests: str = Form(""),
    browsers: str = Form("chromium"),
    shard_count: int = Form(2),
    agent_ids: str = Form(""),
    headed: bool = Form(False),
    run_on_agents: bool = Form(True),
    execution_target_mode: str = Form("central_and_workers"),
    central_shared_framework_path: str = Form(""),
    tests_per_shard: int = Form(0),
    run_role: str = Form("first_run"),
    human_instruction: str = Form(""),
    standard_profile: str = Form("astraheal-adaptive-enterprise-v1"),
    approved_files: str = Form(""),
    payload_json: str = Form("{}"),
) -> JSONResponse:
    payload = _json_object(payload_json)
    payload.update({
        "use_graphify": use_graphify,
        "run_commands": run_commands,
        "project": project,
        "browser": browser,
        "selected_tests": selected_tests,
        "browsers": browsers or browser,
        "shard_count": shard_count,
        "agent_ids": agent_ids,
        "headed": headed,
        "run_on_agents": run_on_agents,
        "execution_target_mode": execution_target_mode,
        "central_shared_framework_path": central_shared_framework_path,
        "tests_per_shard": tests_per_shard,
        "run_role": run_role,
        "human_instruction": human_instruction,
        "standard_profile": standard_profile,
    })
    if approved_files:
        payload["approved_files"] = [x.strip().replace("\\", "/") for x in approved_files.replace(";", "\n").splitlines() if x.strip()]
    result = start_run({
        "workflow": workflow,
        "framework_path": framework_path,
        "provider": provider,
        "model": model,
        "base_url": base_url,
        "objective": objective,
        "approved": approved,
        "input_payload": payload,
    })
    result["message"] = "Autonomous multi-agent workflow started. Agent progress is available through the streaming URL."
    return JSONResponse(result)




@router.post("/walkthrough/start")
def agentic_start_walkthrough(
    framework_path: str = Form(""),
    feature: str = Form("module2_feature"),
    provider: str = Form("deterministic"),
    model: str = Form(""),
    base_url: str = Form(""),
    walkthrough_username: str = Form(""),
    walkthrough_password: str = Form(""),
    walkthrough_browser: str = Form("chromium"),
    walkthrough_browser_executable: str = Form(""),
    walkthrough_headed: bool = Form(True),
    walkthrough_supervised: bool = Form(True),
    walkthrough_allow_mutations: bool = Form(False),
    walkthrough_allow_cross_origin: bool = Form(False),
    walkthrough_max_scenarios: int = Form(20),
    walkthrough_max_steps: int = Form(80),
    walkthrough_confidence_threshold: float = Form(0.72),
    walkthrough_manual_takeover_seconds: int = Form(90),
    walkthrough_action_timeout_seconds: int = Form(20),
    walkthrough_max_intermediate_actions: int = Form(6),
    walkthrough_capture_screenshots: bool = Form(False),
) -> JSONResponse:
    # Credentials are kept only in a process-memory one-time vault. The run
    # request persisted to SQLite contains neither credentials nor a bearer token.
    run_id = f"agent-{uuid.uuid4().hex[:16]}"
    feature_profiles = get_feature_credential_profiles(feature)
    store_ephemeral_credentials(
        walkthrough_username,
        walkthrough_password,
        key=run_id,
        profiles=feature_profiles,
    )
    payload = {
        "feature": feature,
        "walkthrough_browser": walkthrough_browser,
        "walkthrough_browser_executable": walkthrough_browser_executable,
        "walkthrough_headed": walkthrough_headed,
        "walkthrough_supervised": walkthrough_supervised,
        "walkthrough_allow_mutations": walkthrough_allow_mutations,
        "walkthrough_allow_cross_origin": walkthrough_allow_cross_origin,
        "walkthrough_max_scenarios": max(1, min(int(walkthrough_max_scenarios or 20), 100)),
        "walkthrough_max_steps": max(1, min(int(walkthrough_max_steps or 80), 300)),
        "walkthrough_confidence_threshold": max(0.5, min(float(walkthrough_confidence_threshold or 0.72), 0.99)),
        "walkthrough_manual_takeover_seconds": max(5, min(int(walkthrough_manual_takeover_seconds or 90), 600)),
        "walkthrough_action_timeout_seconds": max(3, min(int(walkthrough_action_timeout_seconds or 20), 120)),
        "walkthrough_max_intermediate_actions": max(0, min(int(walkthrough_max_intermediate_actions or 6), 20)),
        "walkthrough_capture_screenshots": walkthrough_capture_screenshots,
    }
    result = start_run({
        "run_id": run_id,
        "workflow": "functional_walkthrough",
        "framework_path": framework_path,
        "provider": provider,
        "model": model,
        "base_url": base_url,
        "objective": "Treat each approved testcase step as an intent, adapt to the live browser flow, insert the minimum verified prerequisite actions, improve unclear steps, capture test data and verify exact locators without generating code.",
        "approved": False,
        "input_payload": payload,
    })
    result["credential_profiles"] = credential_profile_summary(feature)
    result["message"] = (
        "AI functional walkthrough started. Credentials are held only in volatile process memory under the run ID and will be consumed once. "
        f"Detected source credential profiles: {result['credential_profiles'].get('profile_count', 0)}."
    )
    return JSONResponse(result)


@router.get("/walkthrough/report")
def agentic_walkthrough_report(feature: str = Query("module2_feature")) -> JSONResponse:
    report = load_walkthrough_evidence(feature)
    if not report:
        return JSONResponse({"ok": False, "message": "No functional walkthrough report is available for this feature."}, status_code=404)
    return JSONResponse({"ok": True, "report": report})


@router.get("/walkthrough/report/html")
def agentic_walkthrough_html_report(feature: str = Query("module2_feature")) -> HTMLResponse:
    path = walkthrough_html_report_path(feature)
    if not path.exists():
        return HTMLResponse("<h1>No functional walkthrough report is available for this feature.</h1>", status_code=404)
    return HTMLResponse(path.read_text(encoding="utf-8"))


@router.get("/runs")
def agentic_runs(limit: int = Query(50, ge=1, le=500), framework_path: str = Query("")) -> dict[str, Any]:
    return {"ok": True, "runs": list_runs(limit=limit, framework_path=framework_path)}


@router.get("/runs/{run_id}")
def agentic_run_status(run_id: str) -> JSONResponse:
    result = get_run(run_id)
    if not result:
        return JSONResponse({"ok": False, "message": "Autonomous run not found."}, status_code=404)
    return JSONResponse({"ok": True, **result})


@router.get("/runs/{run_id}/events")
async def agentic_run_events(run_id: str, after_id: int = Query(0, ge=0)) -> StreamingResponse:
    return StreamingResponse(stream_sse(run_id, after_id=after_id), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"})


@router.post("/runs/{run_id}/cancel")
def agentic_cancel_run(run_id: str) -> JSONResponse:
    return JSONResponse(cancel_run(run_id))


@router.post("/code-graph/index")
def agentic_code_graph_index(framework_path: str = Form(""), use_graphify: bool = Form(True)) -> JSONResponse:
    return JSONResponse(build_code_graph(framework_path, use_graphify=use_graphify))


@router.post("/code-graph/query")
def agentic_code_graph_query(framework_path: str = Form(""), query: str = Form(""), limit: int = Form(30)) -> JSONResponse:
    return JSONResponse(query_code_graph(framework_path, query, limit=limit))


@router.get("/memory")
def agentic_framework_memory(framework_path: str = Query(""), key: str = Query("")) -> dict[str, Any]:
    return {"ok": True, "framework_path": framework_path, "memory": get_framework_memory(framework_path, key=key)}
