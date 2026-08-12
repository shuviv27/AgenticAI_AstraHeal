"""AstraHeal autonomous LangChain/LangGraph multi-agent subsystem.

Runtime entry points are imported lazily so lower-level framework intelligence
modules can reuse agentic cache/standards utilities without creating a
controller -> agentic package -> graph -> tools -> controller import cycle.
"""

from __future__ import annotations

from typing import Any


def start_run(request: dict[str, Any]) -> dict[str, Any]:
    from .runtime import start_run as _start_run
    return _start_run(request)


def cancel_run(run_id: str) -> dict[str, Any]:
    from .runtime import cancel_run as _cancel_run
    return _cancel_run(run_id)


def runtime_status() -> dict[str, Any]:
    from .runtime import runtime_status as _runtime_status
    return _runtime_status()


__all__ = ["start_run", "cancel_run", "runtime_status"]
