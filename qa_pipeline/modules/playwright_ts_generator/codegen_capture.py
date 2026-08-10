from __future__ import annotations

import html
import json
import os
import re
import shutil
import subprocess
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from qa_pipeline.core.io import read_json, write_json
from qa_pipeline.core.operation_control import (
    begin_operation,
    finish_operation,
    popen_process_group_kwargs,
    register_process,
    terminate_process_tree,
    unregister_process,
)
from qa_pipeline.core.paths import REPO_ROOT, feature_testcase_path
from qa_pipeline.core.runtime_logger import log_event

_LOCK = threading.RLock()
_SESSIONS: dict[str, dict[str, Any]] = {}

_SENSITIVE_WORDS = {
    "password", "passcode", "otp", "one time password", "secret", "token", "ssn", "itin",
    "security code", "cvv", "pin", "date of birth", "dob",
}

_ACTION_METHODS = ("click", "fill", "selectOption", "check", "uncheck", "press", "hover", "dblclick", "setInputFiles")


def _safe(value: str, default: str = "feature") -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_-]+", "_", str(value or "").strip()).strip("_").lower()
    return cleaned or default


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _capture_root(framework_path: str | Path, feature: str) -> Path:
    return Path(framework_path).expanduser().resolve() / ".aiqa-history" / "codegen-captures" / _safe(feature)


def _ensure_gitignore(root: Path) -> None:
    path = root / ".gitignore"
    current = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
    entries = {line.strip() for line in current.splitlines()}
    wanted = [".aiqa-history/codegen-captures/", ".auth/", "playwright/.auth/"]
    missing = [item for item in wanted if item not in entries]
    if missing:
        prefix = "" if not current or current.endswith("\n") else "\n"
        path.write_text(current + prefix + "\n".join(missing) + "\n", encoding="utf-8")


def _resolve_npx() -> str | None:
    names = ["npx.cmd", "npx.exe", "npx"] if os.name == "nt" else ["npx"]
    for name in names:
        resolved = shutil.which(name)
        if resolved:
            return resolved
    return None


def _mask_source(source: str) -> str:
    """Remove recorded secrets while retaining safe test data and locators."""
    def replace_fill(match: re.Match[str]) -> str:
        locator_expr = match.group("locator")
        value = match.group("value")
        context = locator_expr.lower()
        if any(word in context for word in _SENSITIVE_WORDS):
            return f"await {locator_expr}.fill(''); // sensitive value removed by AstraHeal"
        # Email-looking values are often usernames; remove from persisted capture.
        if "@" in value and re.fullmatch(r"[^\s@]+@[^\s@]+", value.strip()):
            return f"await {locator_expr}.fill(''); // username removed by AstraHeal"
        return match.group(0)

    pattern = re.compile(
        r"await\s+(?P<locator>page\.[\s\S]*?)\.fill\(\s*(?P<quote>['\"])(?P<value>[\s\S]*?)(?P=quote)\s*\)\s*;",
        re.MULTILINE,
    )
    return pattern.sub(replace_fill, source)


def _split_statements(source: str) -> list[str]:
    statements: list[str] = []
    buf: list[str] = []
    quote = ""
    escape = False
    depth = 0
    for ch in source:
        buf.append(ch)
        if quote:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == quote:
                quote = ""
            continue
        if ch in {"'", '"', "`"}:
            quote = ch
            continue
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth = max(0, depth - 1)
        elif ch == ";":
            statement = "".join(buf).strip()
            buf = []
            if "await " in statement:
                statements.append(statement)
    tail = "".join(buf).strip()
    if "await " in tail:
        statements.append(tail)
    return statements


def _literal(text: str) -> str:
    text = text.strip()
    match = re.fullmatch(r"(['\"])([\s\S]*?)\1", text)
    if match:
        return bytes(match.group(2), "utf-8").decode("unicode_escape")
    return text


def _locator_from_expression(expr: str) -> dict[str, Any]:
    expr = expr.strip()
    locator: dict[str, Any] = {"playwright_expression": expr, "verified_by": "playwright_codegen", "confidence": 0.99}
    role = re.search(r"\.getByRole\(\s*(['\"])(?P<role>[^'\"]+)\1\s*,\s*\{[\s\S]*?name\s*:\s*(['\"])(?P<name>[^'\"]+)\3", expr)
    if role:
        locator.update({"strategy": "role", "role": role.group("role"), "value": role.group("name"), "exact": "exact: true" in expr})
        return locator
    for method, strategy in (
        ("getByTestId", "testId"),
        ("getByLabel", "label"),
        ("getByPlaceholder", "placeholder"),
        ("getByText", "text"),
    ):
        match = re.search(rf"\.{method}\(\s*(['\"])(?P<value>[^'\"]+)\1", expr)
        if match:
            locator.update({"strategy": strategy, "value": match.group("value"), "exact": "exact: true" in expr})
            return locator
    match = re.search(r"\.locator\(\s*(['\"])(?P<value>[\s\S]*?)\1\s*\)", expr)
    if match:
        value = match.group("value")
        locator.update({"strategy": "xpath" if value.startswith("//") or value.startswith("xpath=") else "css", "value": value.removeprefix("xpath=")})
        return locator
    # Preserve unsupported expressions in the report, but do not claim they can
    # be converted into a framework locator automatically.
    locator.update({"strategy": "", "value": "", "unsupported_expression": True})
    return locator


def parse_codegen_source(source: str) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    for index, statement in enumerate(_split_statements(source), 1):
        compact = re.sub(r"\s+", " ", statement).strip()
        goto = re.search(r"await\s+page\.goto\(\s*(?P<url>['\"][\s\S]*?['\"])", statement)
        if goto:
            actions.append({"order": index, "action": "goto", "value": _literal(goto.group("url")), "source": compact})
            continue
        expect = re.search(r"await\s+expect\((?P<locator>page\.[\s\S]*?)\)\.(?P<assertion>toBeVisible|toHaveText|toContainText|toHaveValue)\((?P<args>[\s\S]*?)\)\s*;?", statement)
        if expect:
            loc = _locator_from_expression(expect.group("locator"))
            expected = expect.group("args").strip()
            actions.append({
                "order": index,
                "action": "verify",
                "assertion": expect.group("assertion"),
                "expected": _literal(expected) if expected else "",
                "locator": loc,
                "source": compact,
            })
            continue
        action_match = re.search(
            r"await\s+(?P<locator>page\.[\s\S]*?)\.(?P<method>click|fill|selectOption|check|uncheck|press|hover|dblclick|setInputFiles)\((?P<args>[\s\S]*?)\)\s*;?",
            statement,
        )
        if action_match:
            method = action_match.group("method")
            action = {"selectOption": "select", "dblclick": "click"}.get(method, method)
            args = action_match.group("args").strip()
            value = ""
            if method in {"fill", "press", "selectOption"} and args:
                first_arg = args.split(",", 1)[0].strip()
                value = _literal(first_arg)
            loc = _locator_from_expression(action_match.group("locator"))
            actions.append({"order": index, "action": action, "value": value, "locator": loc, "source": compact})
    return actions


def _step_action(step: dict[str, Any]) -> str:
    action = str(step.get("action") or "").lower()
    if action in {"enter", "type"}:
        return "fill"
    if action in {"assert", "expect", "validate"}:
        return "verify"
    if action in {"open", "launch", "navigate"}:
        return "goto"
    return action or "click"


def _tokens(value: str) -> set[str]:
    ignored = {"the", "a", "an", "to", "on", "in", "of", "with", "valid", "button", "field", "click", "enter", "select", "verify"}
    return {token for token in re.findall(r"[a-z0-9]+", value.lower()) if token not in ignored and len(token) > 1}


def _action_label(action: dict[str, Any]) -> str:
    locator = action.get("locator") or {}
    return str(locator.get("value") or action.get("value") or action.get("source") or "")


def _score(step: dict[str, Any], action: dict[str, Any]) -> float:
    step_action = _step_action(step)
    action_name = str(action.get("action") or "")
    action_score = 1.0 if step_action == action_name else (0.75 if {step_action, action_name} <= {"click", "check", "hover"} else 0.0)
    step_text = " ".join(str(step.get(key) or "") for key in ("target", "description", "expected"))
    left, right = _tokens(step_text), _tokens(_action_label(action))
    lexical = len(left & right) / max(1, len(left | right))
    if step_action == "goto" and action_name == "goto":
        lexical = 1.0
    return 0.58 * action_score + 0.42 * lexical


def _action_to_step(action: dict[str, Any], *, generated: bool = False) -> dict[str, Any]:
    locator = dict(action.get("locator") or {})
    label = _action_label(action) or str(action.get("action") or "browser action")
    action_name = str(action.get("action") or "click")
    descriptions = {
        "goto": f"Navigate to {action.get('value') or label}",
        "fill": f"Enter value in {label}",
        "click": f"Click {label}",
        "select": f"Select value in {label}",
        "verify": f"Verify {label}",
        "press": f"Press key on {label}",
        "check": f"Check {label}",
        "uncheck": f"Uncheck {label}",
    }
    value = str(action.get("value") or "")
    sensitive = any(word in label.lower() for word in _SENSITIVE_WORDS)
    return {
        "action": action_name,
        "target": label,
        "description": descriptions.get(action_name, f"Perform {action_name} on {label}"),
        "value": "" if sensitive else value,
        "value_sensitive": sensitive,
        "expected": str(action.get("expected") or ""),
        "generated_by_codegen": generated,
        "walkthrough": {
            "status": "codegen_verified",
            "source": "playwright_codegen",
            "locator": locator,
            "test_data": {
                "source": "playwright_codegen",
                "sensitive": sensitive,
                "value": "" if sensitive else value,
                "environment_variable": "",
            },
        },
    }


def align_actions_to_scenario(scenario: dict[str, Any], actions: list[dict[str, Any]]) -> dict[str, Any]:
    source_steps = [dict(step) for step in (scenario.get("steps") or [])]
    result_steps: list[dict[str, Any]] = []
    cursor = 0
    matched = 0
    inserted = 0
    for source_step in source_steps:
        best_index = -1
        best_score = 0.0
        for idx in range(cursor, min(len(actions), cursor + 8)):
            score = _score(source_step, actions[idx])
            if score > best_score:
                best_index, best_score = idx, score
        if best_index >= 0 and best_score >= 0.56:
            for extra in actions[cursor:best_index]:
                if extra.get("locator", {}).get("strategy") or extra.get("action") == "goto":
                    result_steps.append(_action_to_step(extra, generated=True))
                    inserted += 1
            matched_action = actions[best_index]
            enriched = dict(source_step)
            verified = _action_to_step(matched_action)
            enriched["walkthrough"] = verified["walkthrough"]
            if not str(enriched.get("value") or "").strip() and verified.get("value") and not verified.get("value_sensitive"):
                enriched["value"] = verified["value"]
            result_steps.append(enriched)
            cursor = best_index + 1
            matched += 1
        else:
            result_steps.append(source_step)
    for extra in actions[cursor:]:
        if extra.get("locator", {}).get("strategy") or extra.get("action") == "goto":
            result_steps.append(_action_to_step(extra, generated=True))
            inserted += 1
    output = dict(scenario)
    output["steps"] = result_steps
    output["codegen_capture"] = {
        "matched_source_steps": matched,
        "inserted_codegen_steps": inserted,
        "captured_action_count": len(actions),
    }
    return output


def _scenario_payload(feature: str) -> dict[str, Any]:
    path = feature_testcase_path("module2_uploaded", feature)
    if not path.exists():
        return {"scenarios": []}
    data = read_json(path)
    return data if isinstance(data, dict) else {"scenarios": []}


def _write_capture_reports(session: dict[str, Any], actions: list[dict[str, Any]], enhanced: dict[str, Any]) -> dict[str, str]:
    session_dir = Path(session["session_dir"])
    json_path = session_dir / "capture.json"
    html_path = session_dir / "capture-report.html"
    latest_dir = session_dir.parent
    payload = {
        "ok": bool(actions),
        "session_id": session["session_id"],
        "feature": session["feature"],
        "scenario_id": session.get("scenario_id", ""),
        "framework_path": session["framework_path"],
        "created_at": session["created_at"],
        "completed_at": _now(),
        "recorded_action_count": len(actions),
        "actions": actions,
        "enhanced_testcase_file": str(session_dir / "enhanced.scenarios.json"),
        "sanitized_recording_file": str(session_dir / "recorded.sanitized.spec.ts"),
        "raw_recording_deleted": True,
        "message": "Playwright Codegen capture imported and mapped to the functional testcase." if actions else "No supported Playwright Codegen actions were found in the recording.",
    }
    write_json(json_path, payload)
    write_json(session_dir / "enhanced.scenarios.json", enhanced)
    write_json(latest_dir / "latest.json", payload)
    write_json(latest_dir / "latest-enhanced.scenarios.json", enhanced)
    rows = "".join(
        "<tr>"
        f"<td>{int(item.get('order') or 0)}</td>"
        f"<td>{html.escape(str(item.get('action') or ''))}</td>"
        f"<td>{html.escape(str((item.get('locator') or {}).get('strategy') or ''))}</td>"
        f"<td><code>{html.escape(str((item.get('locator') or {}).get('playwright_expression') or (item.get('locator') or {}).get('value') or ''))}</code></td>"
        f"<td>{html.escape(str(item.get('value') or ''))}</td>"
        "</tr>"
        for item in actions
    )
    html_path.write_text(
        "<!doctype html><html><head><meta charset='utf-8'><title>Playwright Codegen Capture</title>"
        "<style>body{font-family:Segoe UI,Arial;margin:24px;background:#f8fafc;color:#0f172a}.card{background:#fff;border:1px solid #dbe3ef;border-radius:12px;padding:16px;margin:14px 0}table{border-collapse:collapse;width:100%}th,td{padding:8px;border-bottom:1px solid #e2e8f0;text-align:left;vertical-align:top}code{white-space:pre-wrap}</style></head><body>"
        f"<h1>Playwright Codegen Capture</h1><div class='card'><b>Feature:</b> {html.escape(session['feature'])}<br/><b>Scenario:</b> {html.escape(session.get('scenario_id') or 'automatic mapping')}<br/><b>Actions:</b> {len(actions)}<br/><b>Raw credentials retained:</b> No</div>"
        f"<div class='card'><h2>Captured actions and locators</h2><table><tr><th>#</th><th>Action</th><th>Strategy</th><th>Playwright locator</th><th>Non-secret value</th></tr>{rows or '<tr><td colspan=5>No supported actions found.</td></tr>'}</table></div>"
        "<div class='card'><h2>How generation uses this</h2><p>Existing page methods and locators are reused first. Exact Codegen locators are used for missing elements. Unmatched Codegen actions are inserted as verified intermediate steps in the correct order.</p></div></body></html>",
        encoding="utf-8",
    )
    shutil.copy2(html_path, latest_dir / "latest-report.html")
    return {"json": str(json_path), "html": str(html_path)}


def _build_enhanced_payload(framework_path: str, feature: str, scenario_id: str, actions: list[dict[str, Any]]) -> dict[str, Any]:
    original = _scenario_payload(feature)
    scenarios = [dict(item) for item in (original.get("scenarios") or [])]
    if not scenarios:
        return {**original, "scenarios": []}

    # Codegen is commonly recorded one testcase at a time. Preserve earlier
    # imported scenario evidence so TC_02 capture does not erase TC_01.
    previous_path = _capture_root(framework_path, feature) / "latest-enhanced.scenarios.json"
    previous_by_id: dict[str, dict[str, Any]] = {}
    if previous_path.exists():
        try:
            previous = read_json(previous_path)
            previous_by_id = {
                str(item.get("id") or "").lower(): dict(item)
                for item in (previous.get("scenarios") or [])
                if isinstance(item, dict) and str(item.get("id") or "").strip()
            }
        except Exception:
            previous_by_id = {}
    scenarios = [previous_by_id.get(str(item.get("id") or "").lower(), item) for item in scenarios]

    selected_index = 0
    if scenario_id:
        for idx, scenario in enumerate(scenarios):
            if str(scenario.get("id") or "").lower() == scenario_id.lower():
                selected_index = idx
                break
    else:
        selected_index = next(
            (idx for idx, scenario in enumerate(scenarios) if not scenario.get("codegen_capture")),
            0,
        )
    scenarios[selected_index] = align_actions_to_scenario(scenarios[selected_index], actions)
    captured_ids = [
        str(item.get("id") or "")
        for item in scenarios
        if isinstance(item.get("codegen_capture"), dict)
    ]
    return {
        **original,
        "scenarios": scenarios,
        "codegen_capture": {
            "feature": feature,
            "scenario_id": str(scenarios[selected_index].get("id") or scenario_id),
            "recorded_action_count": len(actions),
            "captured_scenario_ids": captured_ids,
            "captured_scenario_count": len(captured_ids),
            "generated_at": _now(),
        },
    }


def _finalize_session(session_id: str, *, terminate: bool = False) -> dict[str, Any]:
    with _LOCK:
        session = _SESSIONS.get(session_id)
        if not session:
            return {"ok": False, "message": "Codegen session not found.", "session_id": session_id}
        if session.get("status") in {"completed", "completed_without_actions"}:
            return session_status(session_id)
        if session.get("_finalizing"):
            return session_status(session_id)
        session["_finalizing"] = True
    proc: subprocess.Popen[Any] | None = session.get("process")
    if terminate and proc and proc.poll() is None:
        terminate_process_tree(proc)
    if proc and proc.poll() is None:
        return {"ok": True, "running": True, "session_id": session_id, "message": "Codegen is still running. Close the recorder or click Stop & import."}
    if proc:
        unregister_process(proc, session_id)
    handle = session.get("output_handle")
    if handle:
        try:
            handle.close()
        except Exception:
            pass
    raw_path = Path(session["raw_file"])
    source = raw_path.read_text(encoding="utf-8", errors="replace") if raw_path.exists() else ""
    sanitized = _mask_source(source)
    sanitized_path = Path(session["session_dir"]) / "recorded.sanitized.spec.ts"
    sanitized_path.write_text(sanitized, encoding="utf-8")
    try:
        raw_path.unlink(missing_ok=True)
    except Exception:
        pass
    actions = parse_codegen_source(sanitized)
    enhanced = _build_enhanced_payload(session["framework_path"], session["feature"], session.get("scenario_id", ""), actions)
    report_paths = _write_capture_reports(session, actions, enhanced)
    session.update({"status": "completed" if actions else "completed_without_actions", "completed_at": _now(), "actions": actions, "enhanced": enhanced, "report_paths": report_paths, "_finalizing": False})
    finish_operation(session_id, "completed" if actions else "failed", "Codegen capture imported." if actions else "Codegen capture contained no supported actions.")
    log_event("playwright_codegen", session.get("message") or "Playwright Codegen capture imported.", status="done" if actions else "warning", progress=100, feature=session["feature"], details={"session_id": session_id, "action_count": len(actions)})
    return session_status(session_id)


def _monitor(session_id: str) -> None:
    with _LOCK:
        session = _SESSIONS.get(session_id)
    if not session:
        return
    proc = session.get("process")
    if not proc:
        return
    try:
        proc.wait()
    finally:
        _finalize_session(session_id)


def start_codegen_capture(
    *, framework_path: str, feature: str, base_url: str = "", scenario_id: str = "", browser: str = "chromium",
) -> dict[str, Any]:
    root = Path(framework_path).expanduser().resolve()
    if not root.exists():
        return {"ok": False, "message": f"Framework path does not exist: {root}"}
    npx = _resolve_npx()
    if not npx:
        return {"ok": False, "message": "npx was not found. Install Node.js and the framework dependencies first."}
    _ensure_gitignore(root)
    feature = _safe(feature)
    session_id = f"codegen-{uuid.uuid4().hex[:16]}"
    session_dir = _capture_root(root, feature) / session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    raw_file = session_dir / "recorded.raw.spec.ts"
    stdout_file = session_dir / "codegen-console.log"
    cmd = [npx, "playwright", "codegen", "--target=playwright-test", f"--browser={browser or 'chromium'}", f"--output={raw_file}"]
    if base_url.strip():
        cmd.append(base_url.strip())
    begin_operation(session_id, label=f"Playwright Codegen capture for {feature}", path="/api/module2/playwright/codegen/start", method="BACKGROUND", expected_seconds=7200)
    out_handle = stdout_file.open("w", encoding="utf-8", errors="replace")
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(root),
            stdin=subprocess.DEVNULL,
            stdout=out_handle,
            stderr=subprocess.STDOUT,
            text=True,
            **popen_process_group_kwargs(),
        )
        register_process(proc, session_id)
    except Exception as exc:
        out_handle.close()
        finish_operation(session_id, "failed", str(exc))
        return {"ok": False, "message": f"Could not start Playwright Codegen: {type(exc).__name__}: {exc}"}
    session = {
        "ok": True,
        "session_id": session_id,
        "feature": feature,
        "scenario_id": str(scenario_id or "").strip(),
        "framework_path": str(root),
        "base_url": base_url,
        "browser": browser,
        "created_at": _now(),
        "status": "running",
        "pid": proc.pid,
        "process": proc,
        "output_handle": out_handle,
        "session_dir": str(session_dir),
        "raw_file": str(raw_file),
        "console_file": str(stdout_file),
        "message": "Playwright Codegen is running. Walk through the selected testcase manually, add assertions where useful, then close the recorder or click Stop & import capture.",
    }
    with _LOCK:
        _SESSIONS[session_id] = session
    threading.Thread(target=_monitor, args=(session_id,), daemon=True).start()
    log_event("playwright_codegen", session["message"], status="running", progress=10, feature=feature, details={"session_id": session_id, "scenario_id": scenario_id, "pid": proc.pid})
    return session_status(session_id)


def session_status(session_id: str) -> dict[str, Any]:
    with _LOCK:
        session = _SESSIONS.get(session_id)
    if not session:
        return {"ok": False, "message": "Codegen session not found.", "session_id": session_id}
    proc = session.get("process")
    running = bool(proc and proc.poll() is None)
    return {
        "ok": True,
        "session_id": session_id,
        "feature": session["feature"],
        "scenario_id": session.get("scenario_id", ""),
        "framework_path": session["framework_path"],
        "status": "running" if running else session.get("status", "completed"),
        "running": running,
        "pid": session.get("pid"),
        "created_at": session.get("created_at"),
        "completed_at": session.get("completed_at"),
        "recorded_action_count": len(session.get("actions") or []),
        "report_paths": session.get("report_paths") or {},
        "message": session.get("message") or "",
    }


def stop_and_import_codegen_capture(session_id: str) -> dict[str, Any]:
    return _finalize_session(session_id, terminate=True)


def latest_codegen_capture(framework_path: str, feature: str) -> dict[str, Any]:
    path = _capture_root(framework_path, feature) / "latest.json"
    if not path.exists():
        return {"ok": False, "message": "No Playwright Codegen capture has been imported for this feature."}
    data = read_json(path)
    return data if isinstance(data, dict) else {"ok": False, "message": "Latest Codegen capture is invalid."}


def load_codegen_enhanced_payload(framework_path: str, feature: str, original: dict[str, Any]) -> dict[str, Any]:
    path = _capture_root(framework_path, feature) / "latest-enhanced.scenarios.json"
    if not path.exists():
        return original
    try:
        data = read_json(path)
        return data if isinstance(data, dict) and data.get("scenarios") else original
    except Exception:
        return original


def latest_codegen_report_path(framework_path: str, feature: str) -> Path:
    return _capture_root(framework_path, feature) / "latest-report.html"
