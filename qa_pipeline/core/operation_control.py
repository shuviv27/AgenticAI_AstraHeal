from __future__ import annotations

import contextlib
import contextvars
import os
import signal
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Iterator


_CURRENT_OPERATION_ID: contextvars.ContextVar[str] = contextvars.ContextVar(
    "astraheal_current_operation_id", default=""
)
_LOCK = threading.RLock()


class OperationCancelled(RuntimeError):
    """Raised when a user requests cancellation of the current operation."""


@dataclass
class OperationRecord:
    operation_id: str
    label: str = "Backend operation"
    path: str = ""
    method: str = ""
    expected_seconds: int = 1800
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    cancelled_at: float | None = None
    status: str = "running"
    message: str = "Operation is running."
    cancel_event: threading.Event = field(default_factory=threading.Event, repr=False)
    processes: dict[int, subprocess.Popen[Any]] = field(default_factory=dict, repr=False)

    def as_dict(self) -> dict[str, Any]:
        now = self.finished_at or time.time()
        return {
            "operation_id": self.operation_id,
            "label": self.label,
            "path": self.path,
            "method": self.method,
            "expected_seconds": self.expected_seconds,
            "elapsed_seconds": round(max(0.0, now - self.started_at), 2),
            "started_at_epoch_ms": int(self.started_at * 1000),
            "finished_at_epoch_ms": int(self.finished_at * 1000) if self.finished_at else None,
            "cancelled_at_epoch_ms": int(self.cancelled_at * 1000) if self.cancelled_at else None,
            "status": self.status,
            "message": self.message,
            "cancel_requested": self.cancel_event.is_set(),
            "active_process_count": len(self.processes),
            "process_ids": sorted(self.processes),
        }


_OPERATIONS: dict[str, OperationRecord] = {}
_MAX_RETAINED = 250


def new_operation_id(prefix: str = "op") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:16]}"


def _prune_locked() -> None:
    if len(_OPERATIONS) <= _MAX_RETAINED:
        return
    completed = sorted(
        (record for record in _OPERATIONS.values() if record.status not in {"running", "cancelling"}),
        key=lambda record: record.finished_at or record.started_at,
    )
    for record in completed[: max(0, len(_OPERATIONS) - _MAX_RETAINED)]:
        _OPERATIONS.pop(record.operation_id, None)


def begin_operation(
    operation_id: str | None = None,
    *,
    label: str = "Backend operation",
    path: str = "",
    method: str = "",
    expected_seconds: int = 1800,
) -> OperationRecord:
    operation_id = str(operation_id or new_operation_id()).strip()
    with _LOCK:
        existing = _OPERATIONS.get(operation_id)
        if existing and existing.status in {"running", "cancelling"}:
            if label:
                existing.label = label
            if path:
                existing.path = path
            if method:
                existing.method = method
            if expected_seconds > 0:
                existing.expected_seconds = expected_seconds
            return existing
        record = OperationRecord(
            operation_id=operation_id,
            label=label or "Backend operation",
            path=path,
            method=method,
            expected_seconds=max(1, int(expected_seconds or 1800)),
        )
        _OPERATIONS[operation_id] = record
        _prune_locked()
        return record


def bind_operation(operation_id: str) -> contextvars.Token[str]:
    return _CURRENT_OPERATION_ID.set(str(operation_id or ""))


def reset_operation(token: contextvars.Token[str]) -> None:
    _CURRENT_OPERATION_ID.reset(token)


@contextlib.contextmanager
def operation_scope(
    operation_id: str | None = None,
    *,
    label: str = "Backend operation",
    path: str = "",
    method: str = "",
    expected_seconds: int = 1800,
    finish_on_exit: bool = True,
) -> Iterator[OperationRecord]:
    record = begin_operation(
        operation_id,
        label=label,
        path=path,
        method=method,
        expected_seconds=expected_seconds,
    )
    token = bind_operation(record.operation_id)
    try:
        check_cancelled(record.operation_id)
        yield record
        if finish_on_exit:
            finish_operation(record.operation_id, "completed", "Operation completed.")
    except OperationCancelled:
        finish_operation(record.operation_id, "cancelled", "Operation aborted by user.")
        raise
    except Exception:
        if finish_on_exit:
            finish_operation(record.operation_id, "failed", "Operation failed before completion.")
        raise
    finally:
        reset_operation(token)


def current_operation_id() -> str:
    return str(_CURRENT_OPERATION_ID.get() or "")


def get_operation(operation_id: str) -> dict[str, Any] | None:
    with _LOCK:
        record = _OPERATIONS.get(str(operation_id or ""))
        return record.as_dict() if record else None


def active_operations() -> list[dict[str, Any]]:
    with _LOCK:
        return [
            record.as_dict()
            for record in sorted(_OPERATIONS.values(), key=lambda item: item.started_at, reverse=True)
            if record.status in {"running", "cancelling"}
        ]


def finish_operation(operation_id: str, status: str = "completed", message: str = "") -> dict[str, Any] | None:
    with _LOCK:
        record = _OPERATIONS.get(str(operation_id or ""))
        if not record:
            return None
        if record.cancel_event.is_set() and status == "completed":
            status = "cancelled"
            message = message or "Operation aborted by user."
        record.status = status
        record.message = message or record.message
        record.finished_at = time.time()
        return record.as_dict()


def cancellation_requested(operation_id: str | None = None) -> bool:
    operation_id = str(operation_id or current_operation_id() or "")
    if not operation_id:
        return False
    with _LOCK:
        record = _OPERATIONS.get(operation_id)
        return bool(record and record.cancel_event.is_set())


def check_cancelled(operation_id: str | None = None) -> None:
    if cancellation_requested(operation_id):
        raise OperationCancelled("Operation aborted by user")


def terminate_process_tree(proc: subprocess.Popen[Any], grace_seconds: float = 2.0) -> None:
    if proc.poll() is not None:
        return
    try:
        if os.name == "nt":
            # /T terminates children such as node -> browser -> renderer.
            subprocess.run(
                ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=max(3, int(grace_seconds) + 2),
                check=False,
            )
        else:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            except Exception:
                proc.terminate()
            try:
                proc.wait(timeout=grace_seconds)
            except Exception:
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                except Exception:
                    proc.kill()
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def register_process(proc: subprocess.Popen[Any], operation_id: str | None = None) -> None:
    operation_id = str(operation_id or current_operation_id() or "")
    if not operation_id:
        return
    with _LOCK:
        record = _OPERATIONS.get(operation_id)
        if not record:
            record = begin_operation(operation_id, label="Background process")
        record.processes[int(proc.pid)] = proc
        cancelled = record.cancel_event.is_set()
    if cancelled:
        terminate_process_tree(proc)
        raise OperationCancelled("Operation aborted by user")


def unregister_process(proc: subprocess.Popen[Any], operation_id: str | None = None) -> None:
    operation_id = str(operation_id or current_operation_id() or "")
    if not operation_id:
        return
    with _LOCK:
        record = _OPERATIONS.get(operation_id)
        if record:
            record.processes.pop(int(proc.pid), None)


def request_cancel(operation_id: str) -> dict[str, Any]:
    operation_id = str(operation_id or "").strip()
    with _LOCK:
        record = _OPERATIONS.get(operation_id)
        if not record:
            return {"ok": False, "message": "Operation not found.", "operation_id": operation_id}
        if record.status not in {"running", "cancelling"}:
            return {
                "ok": True,
                "operation_id": operation_id,
                "status": record.status,
                "message": "Operation has already finished.",
            }
        record.cancel_event.set()
        record.cancelled_at = time.time()
        record.status = "cancelling"
        record.message = "Cancellation requested. Stopping owned subprocesses and waiting for a safe boundary."
        processes = list(record.processes.values())
    for proc in processes:
        terminate_process_tree(proc)
    remote_jobs: dict[str, Any] = {"cancelled_job_count": 0, "cancelled_job_ids": []}
    try:
        from qa_pipeline.core.vdi_agent_control import cancel_jobs_for_operation
        remote_jobs = cancel_jobs_for_operation(operation_id)
    except Exception:
        pass
    return {
        "ok": True,
        "operation_id": operation_id,
        "status": "cancelling",
        "terminated_process_count": len(processes),
        "cancelled_worker_job_count": int(remote_jobs.get("cancelled_job_count") or 0),
        "cancelled_worker_job_ids": list(remote_jobs.get("cancelled_job_ids") or []),
        "message": record.message,
    }


def popen_process_group_kwargs() -> dict[str, Any]:
    if os.name == "nt":
        return {"creationflags": getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)}
    return {"start_new_session": True}
