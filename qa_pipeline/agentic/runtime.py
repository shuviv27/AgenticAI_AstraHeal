from __future__ import annotations

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from qa_pipeline.agentic.events import publish
from qa_pipeline.agentic.graph import build_graph, run_fallback
from qa_pipeline.agentic.memory import get_run, initialize_database, list_runs, upsert_run
from qa_pipeline.agentic.observability import configure_langsmith, tracing_context
from qa_pipeline.agentic.state import AstraHealAgentState
from qa_pipeline.core.operation_control import (
    OperationCancelled, begin_operation, bind_operation, check_cancelled,
    finish_operation, request_cancel, reset_operation,
)

_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="astraheal-langgraph")
_LOCK = threading.RLock()
_RUNNING: dict[str, Any] = {}
_CANCELLED: set[str] = set()


def _workflow_label(workflow: str) -> str:
    return {
        "functional_walkthrough": "AI functional browser walkthrough",
        "deep_learn": "Framework analysis",
        "framework_fix": "Framework validation and repair",
        "mcp_prepare": "Playwright MCP preparation",
        "distributed_execute": "Distributed test execution",
        "rca": "Evidence-based failure analysis",
        "self_heal": "Evidence-based self-healing",
        "full_pipeline": "End-to-end QA workflow",
    }.get(str(workflow or ""), "Multi-agent workflow")


def _initial_state(run_id: str, request: dict[str, Any]) -> AstraHealAgentState:
    thread_id = str(request.get("thread_id") or f"framework:{request.get('framework_path') or 'global'}:{run_id}")
    return {
        "run_id": run_id,
        "thread_id": thread_id,
        "workflow": str(request.get("workflow") or "deep_learn"),
        "objective": str(request.get("objective") or "Autonomously complete the selected AstraHeal workflow using guarded deterministic tools."),
        "framework_path": str(request.get("framework_path") or ""),
        "provider": str(request.get("provider") or "deterministic"),
        "model": str(request.get("model") or ""),
        "base_url": str(request.get("base_url") or ""),
        "input_payload": dict(request.get("input_payload") or {}),
        "status": "created",
        "completed_agents": [],
        "step_count": 0,
        "max_steps": int(request.get("max_steps") or 20),
        "messages": [],
        "findings": [],
        "errors": [],
        "approved": bool(request.get("approved", False)),
        "approval_required": False,
        "no_idea_to_fix": False,
    }


def start_run(request: dict[str, Any]) -> dict[str, Any]:
    initialize_database()
    run_id = str(request.get("run_id") or f"agent-{uuid.uuid4().hex[:16]}")
    state = _initial_state(run_id, request)
    upsert_run(run_id, state["thread_id"], state["workflow"], framework_path=state["framework_path"], provider=state["provider"], model=state["model"], status="queued", request=request)
    publish(run_id, "runtime", f"{_workflow_label(state['workflow'])} queued.", status="queued", progress=0, payload={"workflow": state["workflow"], "thread_id": state["thread_id"]})
    begin_operation(
        run_id, label=_workflow_label(state["workflow"]),
        path=f"/api/agentic/runs/{run_id}", method="BACKGROUND",
        expected_seconds=int(request.get("expected_seconds") or 3600),
    )
    future = _EXECUTOR.submit(_execute, state)
    with _LOCK:
        _RUNNING[run_id] = future
    return {"ok": True, "run_id": run_id, "thread_id": state["thread_id"], "workflow": state["workflow"], "status": "queued", "stream_url": f"/api/agentic/runs/{run_id}/events", "status_url": f"/api/agentic/runs/{run_id}"}


def _execute(initial: AstraHealAgentState) -> None:
    run_id = str(initial["run_id"])
    final: dict[str, Any] = {}
    operation_token = bind_operation(run_id)
    try:
        check_cancelled(run_id)
        upsert_run(run_id, initial["thread_id"], initial["workflow"], framework_path=initial["framework_path"], provider=initial["provider"], model=initial["model"], status="running")
        workflow_label = _workflow_label(str(initial.get("workflow") or ""))
        publish(run_id, "runtime", f"{workflow_label} started.", status="running", progress=1, payload={"langsmith": configure_langsmith()})
        with tracing_context(run_id=run_id, workflow=initial["workflow"], framework_path=initial["framework_path"]):
            graph = build_graph()
            if graph is None:
                publish(run_id, "runtime", "LangGraph dependency is unavailable; guarded compatibility runner is active. Install project dependencies for durable graph checkpoints.", status="warning", progress=2)
                final = run_fallback(initial)
            else:
                config = {"configurable": {"thread_id": initial["thread_id"]}, "metadata": {"run_id": run_id, "workflow": initial["workflow"], "framework_path": initial["framework_path"]}, "run_name": f"AstraHeal:{initial['workflow']}"}
                latest: dict[str, Any] = dict(initial)
                for update in graph.stream(initial, config=config, stream_mode="updates"):
                    check_cancelled(run_id)
                    if run_id in _CANCELLED:
                        raise OperationCancelled("Run cancelled by user")
                    if isinstance(update, dict):
                        for node_name, node_update in update.items():
                            if isinstance(node_update, dict):
                                latest.update(node_update)
                            # Node functions already publish meaningful user-facing milestones.
                            # Keep raw LangGraph transitions in LangSmith/checkpoints instead of
                            # duplicating technical messages in the GUI stream.
                final = latest
        result = final.get("output") or final.get("report") or final
        # An approval gate can be raised both on the initial proposal and when
        # an approved proposal is stale/invalid. Preserve that state instead of
        # incorrectly reporting completion merely because approved=True was sent.
        status = "waiting_for_approval" if final.get("approval_required") else "completed"
        upsert_run(run_id, initial["thread_id"], initial["workflow"], framework_path=initial["framework_path"], provider=initial["provider"], model=initial["model"], status=status, result=result)
        publish(run_id, "runtime", "Workflow completed." if status == "completed" else "Analysis completed and is waiting for approval before repository modification.", status=status, progress=100, payload={"ok": result.get("ok") if isinstance(result, dict) else True})
        finish_operation(run_id, status, "Workflow completed." if status == "completed" else "Workflow is waiting for approval.")
    except Exception as exc:
        cancelled = run_id in _CANCELLED or isinstance(exc, OperationCancelled)
        status = "cancelled" if cancelled else "failed"
        message = "Workflow cancelled." if cancelled else f"{locals().get('workflow_label', 'Workflow')} stopped before completion. Technical reason: {type(exc).__name__}: {exc}"
        upsert_run(run_id, initial["thread_id"], initial["workflow"], framework_path=initial["framework_path"], provider=initial["provider"], model=initial["model"], status=status, result=final, error=message)
        publish(run_id, "runtime", message, status=status, progress=100)
        finish_operation(run_id, status, message)
    finally:
        reset_operation(operation_token)
        with _LOCK:
            _RUNNING.pop(run_id, None)
            _CANCELLED.discard(run_id)


def cancel_run(run_id: str) -> dict[str, Any]:
    run = get_run(run_id)
    if not run:
        return {"ok": False, "message": "Run not found."}
    with _LOCK:
        _CANCELLED.add(run_id)
        future = _RUNNING.get(run_id)
        cancelled_before_start = bool(future and future.cancel())
    operation_result = request_cancel(run_id)
    if cancelled_before_start:
        upsert_run(
            run_id, str(run.get("thread_id") or ""), str(run.get("workflow") or ""),
            framework_path=str(run.get("framework_path") or ""),
            provider=str(run.get("provider") or ""), model=str(run.get("model") or ""),
            status="cancelled", error="Workflow cancelled before execution started.",
        )
        finish_operation(run_id, "cancelled", "Workflow cancelled before execution started.")
        with _LOCK:
            _RUNNING.pop(run_id, None)
        publish(run_id, "runtime", "Workflow cancelled before execution started.", status="cancelled", progress=100)
        return {"ok": True, "run_id": run_id, "status": "cancelled", "message": "Workflow cancelled before execution started."}
    publish(run_id, "runtime", "Cancellation requested. Active commands and browser processes are being stopped at the nearest safe boundary.", status="cancelling", progress=98)
    return {"ok": True, "run_id": run_id, "status": "cancelling", **{k: v for k, v in operation_result.items() if k not in {"ok", "operation_id", "status"}}}


def runtime_status() -> dict[str, Any]:
    try:
        import langgraph  # noqa: F401
        langgraph_available = True
    except Exception:
        langgraph_available = False
    try:
        import langchain  # noqa: F401
        langchain_available = True
    except Exception:
        langchain_available = False
    return {"ok": True, "langgraph_available": langgraph_available, "langchain_available": langchain_available, "langsmith": configure_langsmith(), "memory_database": str(initialize_database()), "running_count": len(_RUNNING), "recent_runs": list_runs(20)}
