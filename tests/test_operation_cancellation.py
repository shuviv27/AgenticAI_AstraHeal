from __future__ import annotations

import sys
import threading
import time
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from qa_pipeline.core.commands import run_command
from qa_pipeline.core.operation_control import (
    OperationCancelled,
    active_operations,
    begin_operation,
    finish_operation,
    get_operation,
    operation_scope,
    request_cancel,
)
from qa_pipeline.core import vdi_agent_control
from qa_pipeline.gui.app import app


def test_managed_command_is_terminated_when_operation_is_cancelled() -> None:
    operation_id = f"test-cancel-command-{uuid.uuid4().hex}"

    def cancel_later() -> None:
        deadline = time.time() + 5
        while time.time() < deadline:
            state = get_operation(operation_id) or {}
            if state.get("status") == "running" and int(state.get("active_process_count") or 0) > 0:
                request_cancel(operation_id)
                return
            time.sleep(0.02)
        request_cancel(operation_id)

    canceller = threading.Thread(target=cancel_later, daemon=True)
    canceller.start()
    started = time.time()
    with pytest.raises(OperationCancelled):
        with operation_scope(operation_id, label="Long test command"):
            run_command([sys.executable, "-c", "import time; time.sleep(30)"], timeout=60)
    assert time.time() - started < 8
    status = get_operation(operation_id)
    assert status
    assert status["status"] == "cancelled"
    assert status["cancel_requested"] is True


def test_operation_registry_exposes_active_and_completed_state() -> None:
    operation_id = "test-operation-registry"
    begin_operation(operation_id, label="Registry test", expected_seconds=60)
    assert any(item["operation_id"] == operation_id for item in active_operations())
    finish_operation(operation_id, "completed", "Done")
    status = get_operation(operation_id)
    assert status
    assert status["status"] == "completed"
    assert status["active_process_count"] == 0


def test_operation_api_routes_return_json() -> None:
    client = TestClient(app)
    operation_id = "test-api-operation"
    begin_operation(operation_id, label="API test")
    status = client.get(f"/api/operations/{operation_id}")
    assert status.status_code == 200
    assert status.json()["operation_id"] == operation_id
    cancelled = client.post(f"/api/operations/{operation_id}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelling"


def test_worker_job_can_be_cancelled_from_central_vm(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(vdi_agent_control, "AGENT_DIR", tmp_path / "runner-agents")
    monkeypatch.setattr(vdi_agent_control, "TOKEN_DIR", tmp_path / "runner-agents" / "tokens")
    monkeypatch.setattr(vdi_agent_control, "AGENTS_DIR", tmp_path / "runner-agents" / "agents")
    monkeypatch.setattr(vdi_agent_control, "JOBS_DIR", tmp_path / "runner-agents" / "jobs")
    monkeypatch.setattr(vdi_agent_control, "PACKAGES_DIR", tmp_path / "runner-agents" / "packages")

    job = vdi_agent_control.create_agent_job(
        "worker-1",
        command="echo test",
        metadata={"operation_id": "parent-operation"},
    )
    result = vdi_agent_control.cancel_jobs_for_operation("parent-operation")
    assert result["cancelled_job_count"] == 1
    status = vdi_agent_control.get_agent_job_status(job["job_id"])
    assert status["cancel_requested"] is True
    assert status["status"] == "cancelled"


def test_gui_contains_abort_control_and_operation_headers() -> None:
    html = (Path(__file__).parents[1] / "qa_pipeline" / "gui" / "static" / "index.html").read_text(encoding="utf-8")
    assert "Stop current operation" in html
    assert "X-AstraHeal-Operation-Id" in html
    assert "/api/operations/" in html
    assert "Expected limit" in html
