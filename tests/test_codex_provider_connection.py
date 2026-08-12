from __future__ import annotations

import asyncio
import json
from pathlib import Path

from starlette.requests import Request

import qa_pipeline.gui.app as gui_app


def _payload(response) -> dict:
    return json.loads(response.body.decode("utf-8"))


def test_codex_login_missing_cli_returns_json(monkeypatch) -> None:
    monkeypatch.setattr(gui_app, "resolve_command", lambda name: None)

    response = asyncio.run(gui_app.api_llm_codex_login(mode="device", cwd=""))
    data = _payload(response)

    assert response.status_code == 200
    assert data["ok"] is False
    assert data["error_type"] == "CodexCliNotFound"
    assert "codex --version" in data["commands"]["version"]


def test_codex_login_uses_defined_safe_cwd_and_returns_json(monkeypatch, tmp_path: Path) -> None:
    seen: dict = {}

    monkeypatch.setattr(gui_app, "resolve_command", lambda name: "C:/Tools/codex.exe")

    def fake_launch(*, codex_path: str, device_auth: bool, cwd: Path) -> dict:
        seen.update(codex_path=codex_path, device_auth=device_auth, cwd=cwd)
        return {
            "ok": True,
            "launched_terminal": True,
            "pid": 1234,
            "mode": "test",
            "command": "codex logout & codex login --device-auth",
        }

    monkeypatch.setattr(gui_app, "_launch_fresh_codex_login_terminal", fake_launch)

    response = asyncio.run(gui_app.api_llm_codex_login(mode="device", cwd=str(tmp_path)))
    data = _payload(response)

    assert response.status_code == 200
    assert data["ok"] is True
    assert data["launched_terminal"] is True
    assert seen["cwd"] == tmp_path.resolve()
    assert seen["device_auth"] is True
    assert data["status_url"] == "/api/llm/codex/status"


def test_codex_login_launch_failure_still_returns_valid_json(monkeypatch) -> None:
    monkeypatch.setattr(gui_app, "resolve_command", lambda name: "codex")
    monkeypatch.setattr(
        gui_app,
        "_launch_fresh_codex_login_terminal",
        lambda **kwargs: {
            "ok": False,
            "launched_terminal": False,
            "error": "terminal blocked by policy",
            "manual_command": "codex logout & codex login --device-auth",
        },
    )

    response = asyncio.run(gui_app.api_llm_codex_login(mode="device", cwd="Z:/missing/path"))
    data = _payload(response)

    assert response.status_code == 200
    assert data["ok"] is False
    assert data["launch"]["error"] == "terminal blocked by policy"
    assert "manually" in data["message"].lower()


def test_api_exception_handler_returns_json() -> None:
    request = Request({"type": "http", "method": "POST", "path": "/api/example", "headers": [], "query_string": b"", "server": ("test", 80), "client": ("test", 123)})
    response = asyncio.run(gui_app.astraheal_unhandled_exception_handler(request, NameError("cwd is not defined")))
    data = _payload(response)

    assert response.status_code == 500
    assert data["ok"] is False
    assert data["error_type"] == "NameError"
    assert "cwd" in data["error"]


def test_gui_uses_safe_json_response_parser() -> None:
    html = (Path(gui_app.STATIC_DIR) / "index.html").read_text(encoding="utf-8")
    assert "async function readApiResponse(response)" in html
    assert "const d=await readApiResponse(r);" in html
    assert "async function codexDeviceLogin()" in html
