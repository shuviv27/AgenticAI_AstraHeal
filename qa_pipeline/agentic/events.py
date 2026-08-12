from __future__ import annotations

import asyncio
import json
import threading
from typing import Any, AsyncIterator

from qa_pipeline.agentic.memory import get_run, read_events, record_event
from qa_pipeline.core.runtime_logger import log_event

_CONDITION = threading.Condition()


def publish(run_id: str, agent: str, message: str, *, status: str = "running", progress: int | None = None, event_type: str = "agent_update", payload: dict[str, Any] | None = None) -> dict[str, Any]:
    event = record_event(run_id, agent, event_type, status, message, progress=progress, payload=payload)
    log_event(f"agentic_{agent}", message, status=status, progress=progress, details={"run_id": run_id, **(payload or {})})
    with _CONDITION:
        _CONDITION.notify_all()
    return event


async def stream_sse(run_id: str, after_id: int = 0, heartbeat_seconds: float = 10.0) -> AsyncIterator[str]:
    cursor = max(0, int(after_id or 0))
    idle = 0.0
    while True:
        events = read_events(run_id, after_id=cursor, limit=250)
        if events:
            idle = 0.0
            for event in events:
                cursor = max(cursor, int(event.get("id") or 0))
                yield f"id: {cursor}\nevent: agent_event\ndata: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"
        else:
            await asyncio.sleep(0.5)
            idle += 0.5
        run = get_run(run_id)
        if run.get("status") in {"completed", "failed", "cancelled", "waiting_for_approval"} and not read_events(run_id, after_id=cursor, limit=1):
            yield f"event: run_complete\ndata: {json.dumps(run, ensure_ascii=False, default=str)}\n\n"
            break
        if idle >= heartbeat_seconds:
            idle = 0.0
            yield ": heartbeat\n\n"
