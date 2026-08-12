from __future__ import annotations

import hashlib
import html
import json
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

from qa_pipeline.agentic.credential_vault import consume_ephemeral_credentials
from qa_pipeline.agentic.provider_gateway import provider_gateway
from qa_pipeline.core.io import read_json, write_json
from qa_pipeline.core.paths import QA_CACHE_DIR, REPO_ROOT, feature_testcase_path
from qa_pipeline.core.text import safe_id


WALKTHROUGH_ROOT = QA_CACHE_DIR / "functional_walkthrough"
_ALLOWED_ACTIONS = {"goto", "click", "fill", "select", "check", "press", "verify", "wait", "manual", "complete"}
_MUTATING_WORDS = {
    "submit", "save", "create", "delete", "remove", "transfer", "purchase", "pay", "checkout",
    "send", "approve", "reject", "cancel", "update", "insert", "upload", "confirm", "complete",
}
_SECRET_WORDS = {"password", "passcode", "secret", "token", "otp", "pin"}
_PERSONAL_DATA_WORDS = {"social security", "ssn", "itin", "date of birth", "dob", "mobile", "phone", "email", "address", "credit card", "account number"}
_AUTH_WORDS = {"login", "sign in", "username", "email", "password", "authenticate"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_feature(value: str) -> str:
    return re.sub(r"[^a-z0-9_-]+", "_", str(value or "feature").strip().lower()).strip("_") or "feature"


def walkthrough_directory(feature: str) -> Path:
    return WALKTHROUGH_ROOT / _safe_feature(feature)


def walkthrough_report_path(feature: str) -> Path:
    return walkthrough_directory(feature) / "latest.json"


def walkthrough_html_report_path(feature: str) -> Path:
    return walkthrough_directory(feature) / "latest.html"


def walkthrough_enhanced_testcase_path(feature: str) -> Path:
    return feature_testcase_path("module2_uploaded", _safe_feature(feature)).with_name(f"{_safe_feature(feature)}.walkthrough.scenarios.json")


def _write_walkthrough_html(feature: str, report: dict[str, Any]) -> Path:
    path = walkthrough_html_report_path(feature)
    path.parent.mkdir(parents=True, exist_ok=True)
    scenario_rows: list[str] = []
    blocker_rows: list[str] = []
    adaptive_rows: list[str] = []
    for scenario in report.get("scenarios") or []:
        steps = scenario.get("steps") or []
        completed = sum(1 for step in steps if step.get("ok"))
        scenario_rows.append(
            "<tr>"
            f"<td>{html.escape(str(scenario.get('scenario_id') or ''))}</td>"
            f"<td>{html.escape(str(scenario.get('title') or ''))}</td>"
            f"<td>{html.escape(str(scenario.get('credential_role') or 'default').replace('_', ' '))}</td>"
            f"<td>{html.escape(str(scenario.get('status') or ''))}</td>"
            f"<td>{completed}/{len(steps)}</td>"
            f"<td>{int(scenario.get('verified_locator_count') or 0)}</td>"
            f"<td>{int(scenario.get('adaptive_intermediate_action_count') or 0)}</td>"
            "</tr>"
        )
        for step in steps:
            for inserted in step.get("inserted_actions") or []:
                adaptive_rows.append(
                    "<tr>"
                    f"<td>{html.escape(str(scenario.get('scenario_id') or ''))}</td>"
                    f"<td>{html.escape(str(step.get('step_index') or ''))}</td>"
                    f"<td>{html.escape(str(inserted.get('enhanced_step') or inserted.get('target') or ''))}</td>"
                    f"<td><code>{html.escape(str(((inserted.get('locator') or {}).get('playwright_expression') or (inserted.get('locator') or {}).get('value') or '')))}</code></td>"
                    f"<td>{html.escape(str(inserted.get('reason') or ''))}</td>"
                    "</tr>"
                )
            if step.get("ok"):
                continue
            blocker_rows.append(
                "<tr>"
                f"<td>{html.escape(str(scenario.get('scenario_id') or ''))}</td>"
                f"<td>{html.escape(str(step.get('step_index') or ''))}</td>"
                f"<td>{html.escape(str(step.get('original_step') or ''))}</td>"
                f"<td>{html.escape(str(step.get('status') or ''))}</td>"
                f"<td>{html.escape(str(step.get('message') or ''))}</td>"
                "</tr>"
            )
    security = report.get("security") or {}
    path.write_text(
        "<!doctype html><html><head><meta charset='utf-8'><title>AI Functional Walkthrough Report</title>"
        "<style>body{font-family:Segoe UI,Arial;margin:24px;background:#f8fafc;color:#0f172a}.card{background:#fff;border:1px solid #dbe3ef;border-radius:12px;padding:16px;margin:14px 0}table{border-collapse:collapse;width:100%}th,td{padding:8px;border-bottom:1px solid #e2e8f0;text-align:left;vertical-align:top}.ok{color:#166534}.warn{color:#9a3412}code{background:#e2e8f0;padding:2px 5px;border-radius:5px}</style></head><body>"
        f"<h1>AI Functional Walkthrough Report</h1><div class='card'><b>Feature:</b> {html.escape(str(report.get('feature') or feature))}<br/>"
        f"<b>Status:</b> {html.escape(str(report.get('stage') or ''))}<br/><b>Ready for generation:</b> {bool(report.get('ready_for_generation'))}<br/>"
        f"<b>Scenarios:</b> {int(report.get('scenario_count') or len(report.get('scenarios') or []))}<br/><b>Completed scenarios:</b> {int(report.get('completed_scenario_count') or 0)}<br/>"
        f"<b>Verified locators:</b> {int(report.get('verified_locator_count') or 0)}<br/><b>AI-inserted prerequisite actions:</b> {int(report.get('adaptive_intermediate_action_count') or 0)}<br/><b>Message:</b> {html.escape(str(report.get('message') or ''))}</div>"
        "<div class='card'><h2>Scenario progress</h2><table><tr><th>Scenario</th><th>Title</th><th>Credential role</th><th>Status</th><th>Steps completed</th><th>Verified locators</th><th>AI-inserted prerequisites</th></tr>"
        + "".join(scenario_rows)
        + "</table></div><div class='card'><h2>AI-discovered prerequisite actions</h2><table><tr><th>Scenario</th><th>Before source step</th><th>Inserted action</th><th>Verified locator</th><th>Reason</th></tr>"
        + ("".join(adaptive_rows) if adaptive_rows else "<tr><td colspan='5'>No prerequisite actions were inserted.</td></tr>")
        + "</table></div><div class='card'><h2>Unresolved blockers</h2><table><tr><th>Scenario</th><th>Step</th><th>Instruction</th><th>Status</th><th>Reason</th></tr>"
        + ("".join(blocker_rows) if blocker_rows else "<tr><td colspan='5' class='ok'>No unresolved blockers.</td></tr>")
        + "</table></div><div class='card'><h2>Security</h2>"
        f"Credentials persisted: {bool(security.get('credentials_persisted'))}<br/>Credentials sent to AI prompts: {bool(security.get('credentials_in_prompts'))}<br/>Credentials in screenshots: {bool(security.get('credentials_in_screenshots'))}</div>"
        "</body></html>",
        encoding="utf-8",
    )
    return path


def load_walkthrough_evidence(feature: str) -> dict[str, Any]:
    path = walkthrough_report_path(feature)
    if not path.exists():
        return {}
    try:
        data = read_json(path)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _normalise_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _contains_any(text: str, words: set[str]) -> bool:
    low = text.lower()
    return any(word in low for word in words)


def _is_sensitive_step(step: dict[str, Any]) -> bool:
    if bool(step.get("value_sensitive")):
        return True
    return _contains_any(" ".join(str(step.get(k) or "") for k in ("action", "target", "value_env", "description")), _SECRET_WORDS | {"admin user", "valid user", "login id"})


def _is_personal_data_step(step: dict[str, Any]) -> bool:
    return _contains_any(" ".join(str(step.get(k) or "") for k in ("action", "target", "description", "value_env")), _PERSONAL_DATA_WORDS)


def _is_auth_step(step: dict[str, Any]) -> bool:
    return _contains_any(" ".join(str(step.get(k) or "") for k in ("action", "target", "description", "value_env")), _AUTH_WORDS | {"admin user", "store co-worker", "off hour agent", "login id"})


def _is_mutating_step(step: dict[str, Any]) -> bool:
    return _contains_any(" ".join(str(step.get(k) or "") for k in ("action", "target", "description")), _MUTATING_WORDS)


def _step_action(step: dict[str, Any]) -> str:
    raw = str(step.get("action") or "perform").strip().lower()
    if raw in {"open", "launch", "navigate"}:
        return "goto"
    if raw in {"type", "enter"}:
        return "fill"
    if raw in {"assert", "expect", "validate"}:
        return "verify"
    if raw in {"choose"}:
        return "select"
    if raw in _ALLOWED_ACTIONS:
        return raw
    target = str(step.get("target") or "").lower()
    if any(x in target for x in ("enter ", "fill ", "type ")):
        return "fill"
    if any(x in target for x in ("verify", "validate", "should", "displayed", "visible")):
        return "verify"
    if any(x in target for x in ("click", "press", "open", "select")):
        return "click"
    return "manual"


def _credential_role_for_scenario(scenario: dict[str, Any]) -> str:
    explicit = str(scenario.get("credential_profile") or "").strip().lower()
    if explicit:
        return explicit
    corpus = " ".join([str(scenario.get("title") or "")] + [str(x.get("target") or "") for x in scenario.get("steps") or []]).lower()
    if any(token in corpus for token in ("off hour", "off-hour", "oha_chat", "chat only agent")):
        return "off_hour_agent"
    if any(token in corpus for token in ("admin user", "administrator", "developer console")):
        return "admin_user"
    if any(token in corpus for token in ("store co-worker", "store coworker", "henry sms", "ben sms")):
        return "store_coworker"
    return "default"


def _scenario_credentials(scenario: dict[str, Any], credentials: dict[str, Any]) -> dict[str, str]:
    scenario_id = str(scenario.get("id") or "")
    profiles = credentials.get("profiles") if isinstance(credentials.get("profiles"), dict) else {}
    selected = dict(profiles.get(scenario_id) or profiles.get(scenario_id.upper()) or {})
    return {
        "username": str(selected.get("username") or credentials.get("username") or ""),
        "password": str(selected.get("password") or credentials.get("password") or ""),
        "role": str(selected.get("role") or _credential_role_for_scenario(scenario)),
        "profile_id": str(selected.get("profile_id") or scenario_id or "default"),
    }


def _session_key(profile: dict[str, str]) -> str:
    raw = "\0".join((profile.get("username", ""), profile.get("password", ""), profile.get("role", "default")))
    if not raw.strip("\0"):
        return f"anonymous:{profile.get('role') or 'default'}"
    return "credential:" + hashlib.sha256(raw.encode("utf-8", errors="ignore")).hexdigest()[:20]


def _inline_step_value(step: dict[str, Any]) -> str:
    text = _normalise_text(step.get("target") or step.get("description"))
    cleaned = re.sub(r"[*`]+", "", text).strip()
    patterns = [
        r"\b(?:as|with|to)\s+[\"']?([^\"']+?)[\"']?\s*$",
        r"\benter\s+[\"']?([^\"']+?)[\"']?\s*$",
        r"\bprovide(?:\s+the)?(?:\s+contact)?\s+[\"']?([^\"']+?)[\"']?\s*$",
        r"\bis\s+[\"']?([^\"']+?)[\"']?\s*$",
    ]
    for pattern in patterns:
        match = re.search(pattern, cleaned, re.I)
        if not match:
            continue
        candidate = match.group(1).strip(" .")
        low = candidate.lower()
        if low in {"valid username", "valid password", "username", "password", "the field", "the button", "displayed", "visible"}:
            continue
        if len(candidate) <= 160:
            return candidate
    return ""


def _safe_generated_value(step: dict[str, Any]) -> str:
    text = _normalise_text(step.get("target") or step.get("description")).lower()
    if "today" in text and "date" in text:
        return datetime.now().date().isoformat()
    if "future date" in text or ("appointment date" in text and "date" in text):
        return (datetime.now().date() + timedelta(days=1)).isoformat()
    if "time" in text:
        return "10:00 AM"
    if "notes" in text:
        return "AstraHeal functional walkthrough validation"
    return ""


def _step_value(step: dict[str, Any], credentials: dict[str, str]) -> tuple[str, str]:
    text = " ".join(str(step.get(k) or "") for k in ("target", "description", "value_env")).lower()
    if "password" in text or "passcode" in text:
        return credentials.get("password", ""), "password"
    if any(token in text for token in ("username", "email", "login id", "admin user", "valid user")):
        return credentials.get("username", ""), "username"
    env_name = str(step.get("value_env") or "").strip()
    if env_name and os.getenv(env_name):
        return str(os.getenv(env_name) or ""), "environment"
    value = str(step.get("value") or "").strip()
    if value:
        return value, str(step.get("value_source") or "testcase")
    inline = _inline_step_value(step)
    if inline:
        return inline, "test_step"
    generated = _safe_generated_value(step)
    if generated:
        return generated, "safe_runtime_default"
    return "", "missing"


def _stable_css_id(value: str) -> bool:
    value = str(value or "")
    if not value or len(value) > 80:
        return False
    if re.search(r"\d{5,}|[a-f0-9]{12,}", value, flags=re.I):
        return False
    return bool(re.fullmatch(r"[A-Za-z_][\w:.-]*", value))


_VALID_ARIA_ROLES = {
    "alert", "alertdialog", "application", "article", "banner", "blockquote", "button", "caption",
    "cell", "checkbox", "code", "columnheader", "combobox", "complementary", "contentinfo",
    "definition", "deletion", "dialog", "directory", "document", "emphasis", "feed", "figure",
    "form", "generic", "grid", "gridcell", "group", "heading", "img", "insertion", "link", "list",
    "listbox", "listitem", "log", "main", "marquee", "math", "meter", "menu", "menubar",
    "menuitem", "menuitemcheckbox", "menuitemradio", "navigation", "none", "note", "option",
    "paragraph", "presentation", "progressbar", "radio", "radiogroup", "region", "row", "rowgroup",
    "rowheader", "scrollbar", "search", "searchbox", "separator", "slider", "spinbutton", "status",
    "strong", "subscript", "superscript", "switch", "tab", "table", "tablist", "tabpanel", "term",
    "textbox", "time", "timer", "toolbar", "tooltip", "tree", "treegrid", "treeitem",
}


def _css_attr(value: str) -> str:
    return str(value or "").replace("\\", "\\\\").replace('"', '\\"')


def _stable_attr(value: str) -> bool:
    value = str(value or "").strip()
    if not value or len(value) > 100:
        return False
    if re.search(r"\d{6,}|[a-f0-9]{14,}", value, flags=re.I):
        return False
    return bool(re.fullmatch(r"[A-Za-z_][\w:.-]*", value))


def _candidate_key(candidate: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(candidate.get("strategy") or ""),
        str(candidate.get("role") or ""),
        str(candidate.get("value") or ""),
    )


def _control_signature(element: dict[str, Any]) -> str:
    stable = {
        "testid": _normalise_text(element.get("testid")),
        "dom_id": _normalise_text(element.get("dom_id")),
        "name": _normalise_text(element.get("name")),
        "type": _normalise_text(element.get("type")),
        "tag": _normalise_text(element.get("tag")),
        "frame_url": _normalise_text(element.get("frame_url")),
    }
    raw = json.dumps(stable, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8", errors="ignore")).hexdigest()[:20]


def locator_from_element(element: dict[str, Any]) -> dict[str, Any]:
    """Return locator evidence verified against the exact live DOM element.

    Native input buttons often expose their accessible name through the HTML
    ``value`` attribute rather than inner text. Earlier builds did not capture
    that attribute, which produced ``role=button`` with an empty/undefined name.
    Stable id/name selectors are retained as fallbacks so the same submit
    control can be used across multi-stage login pages even when its visible
    label changes between Username and Password stages.
    """
    testid = _normalise_text(element.get("testid"))
    role = _normalise_text(element.get("role")).lower()
    if role not in _VALID_ARIA_ROLES:
        role = ""
    control_value = _normalise_text(element.get("control_value"))
    name = _normalise_text(
        element.get("accessible_name")
        or element.get("aria_label")
        or element.get("label")
        or element.get("placeholder")
        or control_value
        or element.get("text")
    )
    label = _normalise_text(element.get("label"))
    placeholder = _normalise_text(element.get("placeholder"))
    element_id = _normalise_text(element.get("dom_id"))
    element_name = _normalise_text(element.get("name"))
    input_type = _normalise_text(element.get("type")).lower()
    tag = _normalise_text(element.get("tag")).lower()

    candidates: list[dict[str, Any]] = []
    if testid:
        candidates.append({"strategy": "testId", "value": testid, "confidence": 0.99})
    if role and name:
        candidates.append({"strategy": "role", "role": role, "value": name, "exact": True, "confidence": 0.97})
    if label:
        candidates.append({"strategy": "label", "value": label, "exact": True, "confidence": 0.95})
    if placeholder:
        candidates.append({"strategy": "placeholder", "value": placeholder, "exact": True, "confidence": 0.92})
    if _stable_css_id(element_id):
        candidates.append({"strategy": "css", "value": f"#{_css_attr(element_id)}", "confidence": 0.95})
    if _stable_attr(element_name):
        tag_name = tag if tag in {"input", "button", "select", "textarea", "a"} else ""
        selector = f'{tag_name}[name="{_css_attr(element_name)}"]' if tag_name else f'[name="{_css_attr(element_name)}"]'
        candidates.append({"strategy": "css", "value": selector, "confidence": 0.93})
    if control_value and tag == "input" and input_type in {"button", "submit", "reset", "image"}:
        candidates.append({
            "strategy": "css",
            "value": f'input[type="{_css_attr(input_type)}"][value="{_css_attr(control_value)}"]',
            "confidence": 0.91,
        })
    if name and tag in {"a", "button", "summary", "option"}:
        candidates.append({"strategy": "text", "value": name, "exact": True, "confidence": 0.86})
    if not candidates and name:
        candidates.append({"strategy": "text", "value": name, "exact": False, "confidence": 0.65})

    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for candidate in candidates:
        if not candidate.get("strategy") or not str(candidate.get("value") or "").strip():
            continue
        if candidate.get("strategy") == "role" and not candidate.get("role"):
            continue
        key = _candidate_key(candidate)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(candidate)
    candidates = deduped

    if not candidates:
        return {"ok": False, "confidence": 0.0, "reason": "No stable accessible locator attributes were found."}
    primary, *fallbacks = candidates
    return {
        "ok": True,
        "strategy": primary["strategy"],
        "role": primary.get("role", ""),
        "value": primary["value"],
        "exact": bool(primary.get("exact", False)),
        "confidence": float(primary["confidence"]),
        "fallbacks": [{k: v for k, v in item.items() if k != "confidence"} for item in fallbacks[:6]],
        "all_candidates": candidates,
        "playwright_expression": locator_expression(primary),
        "control_signature": _control_signature(element),
        "stable_attributes": {
            "testid": testid,
            "dom_id": element_id,
            "name": element_name,
            "type": input_type,
            "control_value": control_value,
        },
    }


def locator_expression(locator: dict[str, Any]) -> str:
    strategy = str(locator.get("strategy") or "")
    value = json.dumps(str(locator.get("value") or ""), ensure_ascii=False)
    exact = ", exact: true" if locator.get("exact") else ""
    if strategy == "testId":
        return f"page.getByTestId({value})"
    if strategy == "role":
        role = str(locator.get('role') or '').strip()
        if not role or not str(locator.get('value') or '').strip():
            return ''
        return f"page.getByRole({json.dumps(role)}, {{ name: {value}{exact} }})"
    if strategy == "label":
        return f"page.getByLabel({value}, {{ exact: {str(bool(locator.get('exact'))).lower()} }})"
    if strategy == "placeholder":
        return f"page.getByPlaceholder({value}, {{ exact: {str(bool(locator.get('exact'))).lower()} }})"
    if strategy == "text":
        return f"page.getByText({value}, {{ exact: {str(bool(locator.get('exact'))).lower()} }})"
    if strategy == "css":
        return f"page.locator({value})"
    return ""


def _element_search_text(element: dict[str, Any]) -> str:
    return " ".join(_normalise_text(element.get(k)) for k in (
        "text", "accessible_name", "aria_label", "label", "placeholder", "name", "dom_id", "testid", "role", "tag"
    )).lower()


def rank_elements(step: dict[str, Any], elements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    target = _normalise_text(step.get("target") or step.get("description"))
    action = _step_action(step)
    tokens = [x for x in re.findall(r"[a-z0-9]+", target.lower()) if len(x) > 1 and x not in {"the", "a", "an", "on", "in", "to", "of", "and", "with", "click", "enter", "fill", "select", "verify"}]
    ranked: list[dict[str, Any]] = []
    for element in elements:
        hay = _element_search_text(element)
        score = sum(8 for token in tokens if token in hay)
        role = str(element.get("role") or "").lower()
        tag = str(element.get("tag") or "").lower()
        input_type = str(element.get("type") or "").lower()
        if action == "click" and (role in {"button", "link", "tab", "menuitem"} or tag in {"button", "a"}):
            score += 12
        if action == "fill" and (role == "textbox" or tag in {"input", "textarea"}):
            score += 12
        if action == "select" and (role in {"combobox", "option"} or tag == "select"):
            score += 12
        if action == "check" and input_type in {"checkbox", "radio"}:
            score += 12
        locator = locator_from_element(element)
        score += int(float(locator.get("confidence") or 0) * 10)
        if score > 0:
            ranked.append({**element, "match_score": score, "locator": locator})
    return sorted(ranked, key=lambda x: (-int(x.get("match_score") or 0), -float((x.get("locator") or {}).get("confidence") or 0)))


def _enhance_step_text(step: dict[str, Any], action: str, locator: dict[str, Any] | None, page_title: str = "") -> str:
    target = _normalise_text(step.get("target") or step.get("description") or "the target element")
    name = _normalise_text((locator or {}).get("value"))
    location = f' on "{page_title}"' if page_title else ""
    if action == "goto":
        return f"Open the application URL{location}."
    if action == "fill":
        return f"Enter the supplied test data into the {name or target} field{location}."
    if action == "select":
        return f"Select the supplied test data from {name or target}{location}."
    if action == "verify":
        return f"Verify that {name or target} is visible and matches the expected result{location}."
    if action == "click":
        return f"Click {name or target}{location}."
    return target


def _sanitise_element(raw: Any, index: int = 0) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    return {
        "element_id": str(raw.get("element_id") or f"el-{index}"),
        "tag": _normalise_text(raw.get("tag")),
        "role": _normalise_text(raw.get("role")),
        "text": _normalise_text(raw.get("text"))[:240],
        "accessible_name": _normalise_text(raw.get("accessible_name"))[:240],
        "aria_label": _normalise_text(raw.get("aria_label"))[:240],
        "label": _normalise_text(raw.get("label"))[:240],
        "placeholder": _normalise_text(raw.get("placeholder"))[:240],
        "name": _normalise_text(raw.get("name"))[:120],
        "dom_id": _normalise_text(raw.get("dom_id"))[:120],
        "testid": _normalise_text(raw.get("testid"))[:120],
        "type": _normalise_text(raw.get("type"))[:80],
        "control_value": _normalise_text(raw.get("control_value"))[:240],
        "frame_url": _normalise_text(raw.get("frame_url"))[:500],
        "frame_name": _normalise_text(raw.get("frame_name"))[:160],
        "visible": bool(raw.get("visible", True)),
    }


def _deterministic_element_decision(step: dict[str, Any], ranked: list[dict[str, Any]]) -> dict[str, Any]:
    if not ranked:
        return {"ok": False, "action": "manual", "confidence": 0.0, "reason": "No matching visible element was found."}
    best = ranked[0]
    action = _step_action(step)
    target_text = _normalise_text(step.get("target") or step.get("description")).lower()
    hay = _element_search_text(best)
    role = str(best.get("role") or "").lower()
    tag = str(best.get("tag") or "").lower()
    input_type = str(best.get("type") or "").lower()
    locator_confidence = float((best.get("locator") or {}).get("confidence") or 0.0)
    stop = {
        "the", "a", "an", "on", "in", "to", "of", "and", "with", "click", "enter", "fill", "select", "verify",
        "valid", "provided", "store", "co", "worker", "off", "hour", "admin", "user", "field", "button", "option",
    }
    tokens = [token for token in re.findall(r"[a-z0-9]+", target_text) if len(token) > 1 and token not in stop]
    matched = [token for token in tokens if token in hay]
    ratio = len(matched) / max(1, len(tokens))
    role_compatible = (
        action == "click" and (role in {"button", "link", "tab", "menuitem"} or tag in {"button", "a"})
        or action == "fill" and (role == "textbox" or tag in {"input", "textarea"})
        or action == "select" and (role in {"combobox", "option", "listbox"} or tag == "select")
        or action == "check" and (role in {"checkbox", "radio"} or input_type in {"checkbox", "radio"})
        or action == "verify"
    )

    auth_exact = False
    if "password" in target_text or "passcode" in target_text:
        auth_exact = input_type == "password" or "password" in hay or "passcode" in hay
    elif any(token in target_text for token in ("username", "user name", "login id", "admin user", "off hour agent", "store co-worker")):
        auth_exact = role_compatible and any(token in hay for token in ("username", "user name", "email", "login id"))
    elif action == "click" and any(token in target_text for token in ("login", "log in", "sign in")):
        auth_exact = role_compatible and any(token in hay for token in ("login", "log in", "sign in"))

    if auth_exact:
        confidence = 0.97
    elif role_compatible and ratio >= 0.75 and matched:
        confidence = 0.95
    elif role_compatible and len(matched) >= 2:
        confidence = 0.91
    elif role_compatible and len(matched) >= 1 and locator_confidence >= 0.90:
        confidence = 0.86
    elif role_compatible and len(ranked) == 1 and locator_confidence >= 0.90:
        confidence = 0.78
    else:
        score = int(best.get("match_score") or 0)
        confidence = min(0.82, max(0.35, score / 65.0))

    if len(ranked) > 1:
        score = int(best.get("match_score") or 0)
        second_score = int(ranked[1].get("match_score") or 0)
        second_hay = _element_search_text(ranked[1])
        second_matches = sum(1 for token in tokens if token in second_hay)
        if score - second_score < 4 and second_matches >= len(matched) and not auth_exact:
            confidence = min(confidence, 0.68)

    return {
        "ok": True,
        "action": action,
        "element_id": best.get("element_id"),
        "confidence": confidence,
        "reason": "Deterministic accessible-name, label, placeholder, role and action matching selected the strongest live DOM element.",
        "decision_source": "deterministic_dom_fallback",
    }


def _provider_decision(
    *,
    provider: str,
    model: str,
    step: dict[str, Any],
    elements: list[dict[str, Any]],
    page_url: str,
    page_title: str,
    repo_root: str,
) -> dict[str, Any]:
    ranked = rank_elements(step, elements)[:25]
    deterministic = _deterministic_element_decision(step, ranked)
    if provider in {"", "deterministic", "rules", "none"}:
        return deterministic
    # Most ordinary controls can be resolved more accurately and much faster
    # from their live accessible DOM evidence than by spending an LLM call on
    # every spreadsheet row. Reserve the provider for ambiguous targets.
    if deterministic.get("ok") and float(deterministic.get("confidence") or 0) >= 0.90:
        deterministic["decision_source"] = "deterministic_high_confidence"
        deterministic["provider_skipped_reason"] = "Live DOM evidence uniquely matched the testcase goal."
        return deterministic

    prompt = json.dumps({
        "current_url": page_url,
        "page_title": page_title,
        "test_step": {k: step.get(k) for k in ("action", "target", "description", "expected", "value_env", "step_number")},
        "allowed_actions": sorted(_ALLOWED_ACTIONS),
        "visible_elements": [{k: item.get(k) for k in ("element_id", "tag", "role", "text", "accessible_name", "aria_label", "label", "placeholder", "name", "dom_id", "testid", "type", "match_score")} for item in ranked],
        "instruction": "Choose one visible element_id and one allowed action. Do not invent elements. Return JSON with action, element_id, confidence (0..1), reason, enhanced_step. If evidence is insufficient, return action=manual and confidence<0.6.",
    }, ensure_ascii=False)
    result = provider_gateway.invoke_json(
        prompt,
        system="You are the AstraHeal AI Functional Walkthrough Agent. Behave like a careful human tester. Use only the supplied visible DOM evidence and the guided test step. Never invent a locator or claim success without browser evidence.",
        provider=provider,
        model=model,
        repo_root=repo_root,
        timeout_seconds=90,
    )
    parsed = result.get("json") or {}
    action = str(parsed.get("action") or "manual").lower()
    element_id = str(parsed.get("element_id") or "")
    confidence = float(parsed.get("confidence") or 0)
    valid_ids = {str(x.get("element_id")) for x in ranked}
    provider_valid = bool(result.get("ok") and action in _ALLOWED_ACTIONS and element_id in valid_ids and action != "manual")
    if provider_valid:
        return {
            "ok": True,
            "action": action,
            "element_id": element_id,
            "confidence": confidence,
            "reason": str(parsed.get("reason") or "AI selected a verified visible DOM element."),
            "enhanced_step": str(parsed.get("enhanced_step") or ""),
            "provider": provider,
            "decision_source": "ai_provider",
        }
    if deterministic.get("ok"):
        deterministic["reason"] = (
            f"AI provider did not return a usable live element ({result.get('error') or parsed.get('reason') or 'insufficient evidence'}). "
            + str(deterministic.get("reason") or "")
        )
        deterministic["provider_fallback_from"] = provider
        return deterministic
    return {
        "ok": False,
        "action": "manual",
        "element_id": "",
        "confidence": 0.0,
        "reason": str(result.get("error") or parsed.get("reason") or "Neither AI nor deterministic DOM matching found a reliable target."),
        "provider": provider,
    }


_TRANSITION_WORDS = {
    "continue", "next", "proceed", "start", "open", "choose", "select", "allow", "accept",
    "agree", "ok", "got it", "use another", "switch account", "single sign on", "sso",
    "sandbox", "environment", "tenant", "company", "organisation", "organization",
}
_UNSAFE_INTERMEDIATE_WORDS = {
    "delete", "remove", "purchase", "pay", "checkout", "transfer", "approve", "reject",
    "send message", "send sms", "submit order", "place order", "confirm purchase",
}


def _clickable_element(element: dict[str, Any]) -> bool:
    role = str(element.get("role") or "").lower()
    tag = str(element.get("tag") or "").lower()
    return role in {"button", "link", "tab", "menuitem", "option"} or tag in {"button", "a", "summary", "option"}


def _deterministic_transition_decision(
    step: dict[str, Any],
    elements: list[dict[str, Any]],
    used_targets: set[str] | None = None,
) -> dict[str, Any]:
    """Choose a safe intermediate UI action that makes the testcase goal reachable.

    This is deliberately conservative. It favours wizard/identity-provider/consent
    transitions and rejects data-changing controls. The original testcase action is
    never replaced; this decision only inserts a prerequisite action before it.
    """
    used_targets = used_targets or set()
    goal = _normalise_text(step.get("target") or step.get("description")).lower()
    goal_action = _step_action(step)
    auth_goal = _is_auth_step(step)
    password_goal = any(token in goal for token in ("password", "passcode", "secret"))
    candidates: list[tuple[int, dict[str, Any]]] = []
    for element in elements:
        if not _clickable_element(element):
            continue
        hay = _element_search_text(element)
        target_key = f"{element.get('role')}|{element.get('accessible_name')}|{element.get('text')}|{element.get('dom_id')}".lower()
        if target_key in used_targets:
            continue
        if any(word in hay for word in _UNSAFE_INTERMEDIATE_WORDS):
            continue
        score = int(float((locator_from_element(element) or {}).get("confidence") or 0) * 10)
        if any(word in hay for word in _TRANSITION_WORDS):
            score += 20
        if any(word in hay for word in ("cookie", "privacy", "consent")) and any(word in hay for word in ("accept", "agree", "allow", "ok")):
            score += 24
        if auth_goal:
            if any(word in hay for word in ("continue", "next", "sandbox", "sso", "single sign on", "use another", "identity", "tenant")):
                score += 30
            if re.search(r"\b(log\s*in|login|sign\s*in)\s+to\b", hay):
                score += 34
            elif any(word in hay for word in ("log in", "login", "sign in")):
                score += 12
        if password_goal and any(word in hay for word in ("sandbox", "continue", "next", "identity", "tenant", "log in to", "login to", "sign in to")):
            score += 35
        if goal_action in {"fill", "select", "verify"} and any(word in hay for word in ("continue", "next", "open", "choose", "select")):
            score += 12
        if score >= 30:
            candidates.append((score, element))
    if not candidates:
        return {"ok": False, "decision": "manual", "confidence": 0.0, "reason": "No safe intermediate transition was found on the current page."}
    candidates.sort(key=lambda item: (-item[0], -float((locator_from_element(item[1]) or {}).get("confidence") or 0)))
    score, best = candidates[0]
    return {
        "ok": True,
        "decision": "intermediate_action",
        "action": "click",
        "element_id": best.get("element_id"),
        "confidence": min(0.96, max(0.72, score / 80.0)),
        "reason": "A safe wizard, authentication, consent, or navigation control is required before the testcase goal becomes available.",
        "decision_source": "deterministic_adaptive_transition",
    }


def _provider_transition_decision(
    *,
    provider: str,
    model: str,
    step: dict[str, Any],
    elements: list[dict[str, Any]],
    page_url: str,
    page_title: str,
    previous_actions: list[dict[str, Any]],
    repo_root: str,
    used_targets: set[str],
) -> dict[str, Any]:
    deterministic = _deterministic_transition_decision(step, elements, used_targets)
    if provider in {"", "deterministic", "rules", "none"}:
        return deterministic
    # Safe, uniquely ranked wizard/authentication transitions such as
    # “Continue” or “Log In to Sandbox” do not need a remote provider call.
    if deterministic.get("ok") and float(deterministic.get("confidence") or 0) >= 0.90:
        deterministic["provider_skipped_reason"] = "A unique safe prerequisite was proven from the live DOM."
        return deterministic
    clickable = [item for item in elements if _clickable_element(item)][:40]
    prompt = json.dumps({
        "current_url": page_url,
        "page_title": page_title,
        "testcase_goal": {k: step.get(k) for k in ("action", "target", "description", "expected", "step_number")},
        "goal_status": "The direct target for the testcase goal is not currently reachable with sufficient confidence.",
        "previous_inserted_actions": [
            {"action": x.get("action"), "target": ((x.get("locator") or {}).get("value")), "page_url_after": x.get("page_url_after")}
            for x in previous_actions[-5:]
        ],
        "visible_clickable_elements": [
            {k: item.get(k) for k in ("element_id", "tag", "role", "text", "accessible_name", "aria_label", "label", "dom_id", "testid")}
            for item in clickable
        ],
        "instruction": (
            "Decide whether one safe intermediate click is required to make the testcase goal reachable. "
            "Examples include Continue, Next, Log In to Sandbox, choosing an identity provider, opening a wizard section, or accepting a consent banner. "
            "Do not choose delete, purchase, transfer, approval, send, save, or other business-data mutations. "
            "Return JSON: decision='intermediate_action' or 'manual', action='click', element_id, confidence, reason, enhanced_step. "
            "Use only a supplied element_id and do not claim the original testcase goal is complete."
        ),
    }, ensure_ascii=False)
    result = provider_gateway.invoke_json(
        prompt,
        system=(
            "You are the AstraHeal Adaptive Browser Planning Agent. A testcase sentence describes a goal, not necessarily one literal browser action. "
            "Observe the current page and insert only the minimum safe prerequisite action needed to reach that goal. Never invent elements or expose secrets."
        ),
        provider=provider,
        model=model,
        repo_root=repo_root,
        timeout_seconds=90,
    )
    parsed = result.get("json") or {}
    element_id = str(parsed.get("element_id") or "")
    valid_ids = {str(item.get("element_id")) for item in clickable}
    provider_valid = bool(
        result.get("ok")
        and str(parsed.get("decision") or "") == "intermediate_action"
        and str(parsed.get("action") or "click").lower() == "click"
        and element_id in valid_ids
        and float(parsed.get("confidence") or 0) >= 0.60
    )
    if provider_valid:
        selected = next((item for item in clickable if str(item.get("element_id")) == element_id), {})
        hay = _element_search_text(selected)
        if not any(word in hay for word in _UNSAFE_INTERMEDIATE_WORDS):
            return {
                "ok": True,
                "decision": "intermediate_action",
                "action": "click",
                "element_id": element_id,
                "confidence": float(parsed.get("confidence") or 0),
                "reason": str(parsed.get("reason") or "AI selected a safe prerequisite browser action."),
                "enhanced_step": str(parsed.get("enhanced_step") or ""),
                "decision_source": "ai_adaptive_transition",
                "provider": provider,
            }
    if deterministic.get("ok"):
        deterministic["provider_fallback_from"] = provider
        deterministic["reason"] = (
            f"AI did not return a usable safe intermediate action ({result.get('error') or parsed.get('reason') or 'insufficient evidence'}). "
            + str(deterministic.get("reason") or "")
        )
        return deterministic
    return {
        "ok": False,
        "decision": "manual",
        "confidence": 0.0,
        "reason": str(result.get("error") or parsed.get("reason") or deterministic.get("reason") or "No safe adaptive transition was found."),
    }


def _page_state_signature(page: Any, elements: list[dict[str, Any]]) -> str:
    compact = [
        f"{item.get('role')}|{item.get('accessible_name')}|{item.get('text')}|{item.get('dom_id')}"
        for item in elements[:30]
    ]
    raw = "\n".join([str(page.url or ""), str(page.title() or ""), *compact])
    return hashlib.sha256(raw.encode("utf-8", errors="ignore")).hexdigest()[:20]


def _resolve_step_target_adaptively(
    *,
    page: Any,
    step: dict[str, Any],
    provider: str,
    model: str,
    repo_root: str,
    confidence_threshold: float,
    action_timeout_ms: int,
    max_intermediate_actions: int,
    event_publisher: Callable[[str, str, int, str, dict[str, Any] | None], None] | None,
    scenario_id: str,
    step_index: int,
    progress: int,
) -> dict[str, Any]:
    """Resolve a testcase goal, inserting safe prerequisite browser actions when needed."""
    inserted_actions: list[dict[str, Any]] = []
    used_targets: set[str] = set()
    state_visits: dict[str, int] = {}
    last_decision: dict[str, Any] = {}
    last_locator: dict[str, Any] = {"ok": False, "confidence": 0.0}
    current = page
    for attempt in range(max(0, int(max_intermediate_actions)) + 1):
        try:
            current.evaluate(_INTERACTION_LISTENER_SCRIPT)
        except Exception:
            pass
        raw_elements = current.evaluate(_DOM_SNAPSHOT_SCRIPT)
        elements = [_sanitise_element(item, i) for i, item in enumerate(raw_elements if isinstance(raw_elements, list) else [])]
        direct = _provider_decision(
            provider=provider,
            model=model,
            step=step,
            elements=elements,
            page_url=current.url,
            page_title=current.title(),
            repo_root=repo_root,
        )
        selected = next((item for item in elements if str(item.get("element_id")) == str(direct.get("element_id"))), None)
        bundle = locator_from_element(selected or {}) if selected else {"ok": False, "confidence": 0.0}
        locator = _verified_locator_for_element(current, bundle, str((selected or {}).get("element_id") or "")) if selected and bundle.get("ok") else bundle
        confidence = min(float(direct.get("confidence") or 0), float(locator.get("confidence") or 0))
        last_decision, last_locator = direct, locator
        if selected and locator.get("ok") and confidence >= float(confidence_threshold):
            return {
                "ok": True,
                "page": current,
                "decision": direct,
                "selected": selected,
                "locator": locator,
                "confidence": confidence,
                "inserted_actions": inserted_actions,
            }
        if attempt >= int(max_intermediate_actions):
            break
        signature = _page_state_signature(current, elements)
        state_visits[signature] = state_visits.get(signature, 0) + 1
        if state_visits[signature] > 2:
            break
        transition = _provider_transition_decision(
            provider=provider,
            model=model,
            step=step,
            elements=elements,
            page_url=current.url,
            page_title=current.title(),
            previous_actions=inserted_actions,
            repo_root=repo_root,
            used_targets=used_targets,
        )
        if not transition.get("ok"):
            break
        transition_element = next((item for item in elements if str(item.get("element_id")) == str(transition.get("element_id"))), None)
        transition_bundle = locator_from_element(transition_element or {}) if transition_element else {"ok": False}
        transition_locator = _verified_locator_for_element(current, transition_bundle, str((transition_element or {}).get("element_id") or "")) if transition_element and transition_bundle.get("ok") else transition_bundle
        if not transition_element or not transition_locator.get("ok"):
            break
        target_key = f"{transition_element.get('role')}|{transition_element.get('accessible_name')}|{transition_element.get('text')}|{transition_element.get('dom_id')}".lower()
        used_targets.add(target_key)
        before_url, before_title = current.url, current.title()
        current = _execute_action(current, "click", transition_locator, "", "", action_timeout_ms)
        try:
            current.wait_for_timeout(500)
        except Exception:
            pass
        enhanced = str(transition.get("enhanced_step") or "").strip() or f"Click {transition_locator.get('value') or 'the required intermediate control'} before continuing with the testcase goal."
        evidence = {
            "sequence": attempt + 1,
            "action": "click",
            "target": transition_locator.get("value") or _normalise_text((transition_element or {}).get("accessible_name")),
            "enhanced_step": enhanced,
            "ok": True,
            "status": "adaptive_intermediate_verified",
            "confidence": min(float(transition.get("confidence") or 0), float(transition_locator.get("confidence") or 0)),
            "locator": {k: v for k, v in transition_locator.items() if k != "all_candidates"},
            "locator_candidates": transition_locator.get("all_candidates") or [],
            "page_url_before": before_url,
            "page_title_before": before_title,
            "page_url_after": current.url,
            "page_title_after": current.title(),
            "reason": transition.get("reason"),
            "decision_source": transition.get("decision_source") or "adaptive_transition",
        }
        inserted_actions.append(evidence)
        if event_publisher:
            event_publisher(
                "functional_walkthrough",
                f"{scenario_id} step {step_index}: AI inserted prerequisite action — {enhanced}",
                progress,
                "running",
                {"scenario_id": scenario_id, "step_index": step_index, "inserted_action": evidence},
            )
    return {
        "ok": False,
        "page": current,
        "decision": last_decision,
        "locator": last_locator,
        "confidence": min(float(last_decision.get("confidence") or 0), float(last_locator.get("confidence") or 0)),
        "inserted_actions": inserted_actions,
        "reason": last_decision.get("reason") or last_locator.get("reason") or "The testcase goal remained unreachable after adaptive prerequisite actions.",
    }


def _expand_steps_with_inserted_actions(
    enhanced_steps: list[dict[str, Any]],
    step_results: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Persist discovered prerequisite actions as normalised steps for code generation."""
    by_index = {int(item.get("step_index") or 0): item for item in step_results if item.get("step_index")}
    expanded: list[dict[str, Any]] = []
    for index, raw_step in enumerate(enhanced_steps, 1):
        result = by_index.get(index) or {}
        base_number = str(raw_step.get("step_number") or index)
        for insert_index, action in enumerate(result.get("inserted_actions") or [], 1):
            target = str(action.get("target") or ((action.get("locator") or {}).get("value")) or "intermediate control")
            expanded.append({
                "step_number": f"{base_number}.{insert_index}",
                "action": str(action.get("action") or "click"),
                "target": target,
                "description": str(action.get("enhanced_step") or f"Click {target}"),
                "expected": "The application advances to the state required by the next guided action.",
                "generated_by_walkthrough": True,
                "parent_step_number": base_number,
                "walkthrough": action,
            })
        copied = dict(raw_step)
        if result:
            copied["walkthrough"] = result
            if result.get("enhanced_step"):
                copied["target"] = result.get("enhanced_step")
        expanded.append(copied)
    return expanded


_DOM_SNAPSHOT_SCRIPT = r"""
() => {
  const selector = 'button,a,input,textarea,select,option,[role],[aria-label],[data-testid],[data-test-id],[contenteditable="true"],summary';
  const visible = el => {
    const s = getComputedStyle(el); const r = el.getBoundingClientRect();
    return s.visibility !== 'hidden' && s.display !== 'none' && r.width > 1 && r.height > 1;
  };
  const labelFor = el => {
    if (el.labels && el.labels.length) return Array.from(el.labels).map(x => x.innerText || x.textContent || '').join(' ').trim();
    const id = el.id; if (id) { const l = document.querySelector(`label[for="${CSS.escape(id)}"]`); if (l) return (l.innerText || l.textContent || '').trim(); }
    return '';
  };
  const roleFor = el => {
    const explicit = el.getAttribute('role'); if (explicit) return explicit;
    const tag = el.tagName.toLowerCase(); const type = (el.getAttribute('type') || '').toLowerCase();
    if (tag === 'button') return 'button'; if (tag === 'a') return 'link'; if (tag === 'select') return 'combobox';
    if (tag === 'textarea') return 'textbox'; if (tag === 'input' && ['button','submit','reset','image'].includes(type)) return 'button';
    if (tag === 'input' && type === 'checkbox') return 'checkbox'; if (tag === 'input' && type === 'radio') return 'radio';
    if (tag === 'input') return 'textbox'; return '';
  };
  const roots = [document];
  const seenRoots = new Set();
  const elements = [];
  while (roots.length && elements.length < 400) {
    const root = roots.shift();
    if (!root || seenRoots.has(root)) continue;
    seenRoots.add(root);
    for (const el of Array.from(root.querySelectorAll('*'))) {
      if (el.shadowRoot) roots.push(el.shadowRoot);
    }
    for (const el of Array.from(root.querySelectorAll(selector))) {
      if (visible(el) && !elements.includes(el)) elements.push(el);
      if (elements.length >= 400) break;
    }
  }
  return elements.slice(0, 400).map((el, i) => {
    const elementId = `el-${i}`;
    try { el.setAttribute('data-astraheal-walkthrough-id', elementId); } catch (_) {}
    const tag = el.tagName.toLowerCase();
    const type = (el.getAttribute('type') || '').toLowerCase();
    const controlValue = tag === 'input' && ['button','submit','reset','image'].includes(type)
      ? (el.getAttribute('value') || '') : '';
    return {
      element_id: elementId, tag, role: roleFor(el),
      text: (el.innerText || el.textContent || '').trim().slice(0,240),
      accessible_name: (el.getAttribute('aria-label') || labelFor(el) || el.getAttribute('title') || el.getAttribute('placeholder') || controlValue || el.innerText || el.textContent || '').trim().slice(0,240),
      aria_label: (el.getAttribute('aria-label') || '').trim(), label: labelFor(el).slice(0,240),
      placeholder: (el.getAttribute('placeholder') || '').trim(), name: (el.getAttribute('name') || '').trim(),
      dom_id: (el.id || '').trim(), testid: (el.getAttribute('data-testid') || el.getAttribute('data-test-id') || '').trim(),
      type, control_value: controlValue.trim(), frame_url: location.href, frame_name: window.name || '', visible: true
    };
  });
}
"""

_INTERACTION_LISTENER_SCRIPT = r"""
() => {
  if (window.__astrahealListenerInstalled) return;
  window.__astrahealListenerInstalled = true;
  window.__astrahealInteractionSeq = 0;
  const snap = el => {
    const label = el.labels && el.labels.length ? Array.from(el.labels).map(x => x.innerText || x.textContent || '').join(' ').trim() : '';
    const marker = `human-${window.__astrahealInteractionSeq + 1}`;
    try { el.setAttribute('data-astraheal-walkthrough-id', marker); } catch (_) {}
    const tag=(el.tagName||'').toLowerCase(); const type=(el.getAttribute('type')||'').toLowerCase();
    const role=el.getAttribute('role') || (tag==='button' || (tag==='input' && ['button','submit','reset','image'].includes(type)) ? 'button' : tag==='a' ? 'link' : tag==='select' ? 'combobox' : tag==='textarea' || tag==='input' ? 'textbox' : '');
    const controlValue=tag==='input' && ['button','submit','reset','image'].includes(type) ? (el.getAttribute('value')||'') : '';
    return {element_id:marker, tag, role, text:(el.innerText||el.textContent||'').trim().slice(0,240), accessible_name:(el.getAttribute('aria-label')||label||el.getAttribute('title')||el.getAttribute('placeholder')||controlValue||el.innerText||el.textContent||'').trim().slice(0,240), aria_label:el.getAttribute('aria-label')||'', label, placeholder:el.getAttribute('placeholder')||'', name:el.getAttribute('name')||'', dom_id:el.id||'', testid:el.getAttribute('data-testid')||el.getAttribute('data-test-id')||'', type, control_value:controlValue, frame_url:location.href, frame_name:window.name||'', visible:true};
  };
  ['click','input','change'].forEach(type => document.addEventListener(type, ev => {
    const el = ev.target && ev.target.closest ? ev.target.closest('button,a,input,textarea,select,option,[role],[aria-label],[data-testid],[data-test-id],[contenteditable="true"],summary') : ev.target;
    if (!el) return; window.__astrahealInteractionSeq += 1; window.__astrahealLastInteraction = {seq:window.__astrahealInteractionSeq,type,element:snap(el),ts:Date.now()};
  }, true));
}
"""


def _page_locator(page: Any, definition: dict[str, Any]) -> Any:
    strategy = str(definition.get("strategy") or "")
    value = str(definition.get("value") or "")
    exact = bool(definition.get("exact", False))
    if strategy == "testId":
        return page.get_by_test_id(value)
    if strategy == "role":
        role = str(definition.get("role") or "").strip()
        if not role or not value:
            raise ValueError("Role locator requires both a valid role and accessible name.")
        return page.get_by_role(role, name=value, exact=exact)
    if strategy == "label":
        return page.get_by_label(value, exact=exact)
    if strategy == "placeholder":
        return page.get_by_placeholder(value, exact=exact)
    if strategy == "text":
        return page.get_by_text(value, exact=exact)
    if strategy == "css":
        return page.locator(value)
    raise ValueError(f"Unsupported verified locator strategy: {strategy}")


def _verified_locator_for_element(page: Any, locator_bundle: dict[str, Any], element_id: str) -> dict[str, Any]:
    """Select the first candidate that uniquely resolves the exact DOM element.

    The temporary DOM marker is used only during this browser session and is
    never included in the generated locator. Ambiguous candidates are rejected
    instead of being weakened with ``.first``.
    """
    candidates = list(locator_bundle.get("all_candidates") or [])
    if not candidates and locator_bundle.get("strategy"):
        candidates = [{k: locator_bundle.get(k) for k in ("strategy", "role", "value", "exact", "confidence") if locator_bundle.get(k) not in (None, "")}]
    candidates = [
        item for item in candidates
        if str(item.get("strategy") or "").strip()
        and str(item.get("value") or "").strip()
        and (str(item.get("strategy")) != "role" or str(item.get("role") or "").strip() in _VALID_ARIA_ROLES)
        and str(item.get("value") or "").strip().lower() not in {"undefined", "null", "none"}
    ]
    verified: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    for candidate in candidates:
        try:
            target = _page_locator(page, candidate)
            count = int(target.count())
            markers = target.evaluate_all("els => els.map(el => el.getAttribute('data-astraheal-walkthrough-id') || '')") if count else []
            matches_selected = count == 1 and bool(markers) and str(markers[0]) == str(element_id)
            diagnostics.append({"strategy": candidate.get("strategy"), "value": candidate.get("value"), "count": count, "matches_selected": matches_selected})
            if matches_selected:
                verified.append(dict(candidate))
        except Exception as exc:
            diagnostics.append({"strategy": candidate.get("strategy"), "value": candidate.get("value"), "count": -1, "matches_selected": False, "error": f"{type(exc).__name__}: {exc}"})
    if not verified:
        return {"ok": False, "confidence": 0.0, "reason": "No candidate uniquely resolved the exact selected browser element.", "validation": diagnostics}
    primary, *fallbacks = verified
    return {
        "ok": True,
        "strategy": primary.get("strategy"),
        "role": primary.get("role", ""),
        "value": primary.get("value", ""),
        "exact": bool(primary.get("exact", False)),
        "confidence": float(primary.get("confidence") or locator_bundle.get("confidence") or 0.9),
        "fallbacks": [{k: v for k, v in item.items() if k != "confidence"} for item in fallbacks[:3]],
        "all_candidates": candidates,
        "playwright_expression": locator_expression(primary),
        "validation": diagnostics,
        "control_signature": str(locator_bundle.get("control_signature") or ""),
        "stable_attributes": dict(locator_bundle.get("stable_attributes") or {}),
    }


def _read_non_sensitive_element_value(page: Any, locator: dict[str, Any] | None) -> str:
    if not locator:
        return ""
    try:
        target = _page_locator(page, locator)
        tag = str(target.evaluate("el => (el.tagName || '').toLowerCase()") or "")
        if tag in {"input", "textarea", "select"}:
            return _normalise_text(target.input_value())[:500]
        return _normalise_text(target.text_content() or "")[:500]
    except Exception:
        return ""


def _execute_action(page: Any, action: str, locator: dict[str, Any] | None, value: str, expected: str, timeout_ms: int) -> Any:
    context = page.context
    before_pages = list(context.pages)
    if action == "goto":
        page.goto(value, wait_until="domcontentloaded", timeout=timeout_ms)
        return page
    if action == "wait":
        page.wait_for_timeout(max(100, min(int(float(value or 1) * 1000), 30000)))
        return page
    if locator is None:
        raise ValueError("A verified locator is required for this browser action.")
    target = _page_locator(page, locator)
    target.wait_for(state="visible", timeout=timeout_ms)
    if action == "click":
        target.click(timeout=timeout_ms)
    elif action == "fill":
        target.fill(value, timeout=timeout_ms)
    elif action == "select":
        try:
            target.select_option(label=value, timeout=timeout_ms)
        except Exception:
            target.click(timeout=timeout_ms)
            page.get_by_role("option", name=value).click(timeout=timeout_ms)
    elif action == "check":
        target.check(timeout=timeout_ms)
    elif action == "press":
        target.press(value or "Enter", timeout=timeout_ms)
    elif action == "verify":
        target.wait_for(state="visible", timeout=timeout_ms)
        if expected:
            body = _normalise_text(target.text_content(timeout=timeout_ms) or "")
            if expected.lower() not in body.lower():
                raise AssertionError(f"Expected text was not present in the verified element. Expected: {expected!r}; actual: {body[:300]!r}")
    else:
        raise ValueError(f"Unsupported action: {action}")
    page.wait_for_timeout(350)
    new_pages = [candidate for candidate in context.pages if candidate not in before_pages]
    active = new_pages[-1] if new_pages else page
    try:
        active.wait_for_load_state("domcontentloaded", timeout=min(timeout_ms, 15000))
    except Exception:
        pass
    return active


def _visible_count(locator: Any) -> int:
    try:
        return sum(1 for index in range(min(int(locator.count()), 5)) if locator.nth(index).is_visible())
    except Exception:
        return 0


def _looks_authenticated(page: Any) -> bool:
    try:
        url = str(page.url or "").lower()
        title = str(page.title() or "").lower()
        password_visible = _visible_count(page.locator('input[type="password"]')) > 0
        username_visible = _visible_count(page.locator('input[type="email"],input[name*="user" i],input[id*="user" i]')) > 0
        challenge_visible = _visible_count(page.locator('input[name*="verify" i],input[id*="verify" i],input[autocomplete="one-time-code"]')) > 0
        login_words = any(token in f"{url} {title}" for token in ("login", "signin", "sign-in", "verify your identity"))
        return not password_visible and not challenge_visible and not (login_words and username_visible)
    except Exception:
        return False


def _wait_for_authentication_completion(
    page: Any,
    seconds: int,
    publish_event: Callable[[str, str, int, str, dict[str, Any] | None], None] | None,
) -> bool:
    if _looks_authenticated(page):
        return True
    if publish_event:
        publish_event(
            "functional_walkthrough",
            "Authentication needs human completion. Finish MFA/verification in the open browser; AstraHeal will continue automatically after the application home page is reached.",
            52,
            "waiting_for_human",
            {"reason": "mfa_or_identity_verification"},
        )
    deadline = time.time() + max(10, min(int(seconds or 90), 600))
    stable_since = 0.0
    while time.time() < deadline:
        try:
            if _looks_authenticated(page):
                if not stable_since:
                    stable_since = time.time()
                if time.time() - stable_since >= 1.5:
                    return True
            else:
                stable_since = 0.0
        except Exception:
            stable_since = 0.0
        time.sleep(0.5)
    return False


def _non_production_url(url: str) -> bool:
    host = (urlparse(str(url or "")).hostname or "").lower()
    return any(token in host for token in ("localhost", "127.0.0.1", "qa", "test", "sandbox", "staging", "stage", "dev", "uat"))


def _step_memory_key(step: dict[str, Any]) -> str:
    return re.sub(r"[^a-z0-9]+", " ", f"{_step_action(step)} {step.get('target') or step.get('description') or ''}".lower()).strip()


def _wait_for_human_interaction(page: Any, previous_seq: int, seconds: int, publish_event: Callable[[str, str, int, str, dict[str, Any] | None], None] | None, step_label: str) -> dict[str, Any]:
    if publish_event:
        publish_event("functional_walkthrough", f"Human guidance needed: perform '{step_label}' in the open browser within {seconds} seconds. AstraHeal will capture the interacted element but not the entered value.", 55, "waiting_for_human", None)
    deadline = time.time() + max(5, min(seconds, 600))
    while time.time() < deadline:
        try:
            result = page.evaluate("() => window.__astrahealLastInteraction || null")
            if isinstance(result, dict) and int(result.get("seq") or 0) > previous_seq:
                element = _sanitise_element(result.get("element") or {})
                return {"ok": True, "interaction": result.get("type"), "element": element, "locator": locator_from_element(element)}
        except Exception:
            pass
        time.sleep(0.5)
    return {"ok": False, "reason": "No human browser interaction was captured before the supervised timeout."}


def _scenario_start_url(scenario: dict[str, Any], payload: dict[str, Any], base_url: str) -> str:
    for step in scenario.get("steps") or []:
        for value in (step.get("value"), step.get("target"), step.get("description")):
            match = re.search(r"https?://[^\s]+", str(value or ""))
            if match:
                return match.group(0).rstrip(".,;)")
    return str(base_url or payload.get("start_url") or "").strip()


def _same_origin_allowed(current: str, candidate: str, allow_cross_origin: bool) -> bool:
    if allow_cross_origin:
        return True
    a, b = urlparse(current), urlparse(candidate)
    if not a.netloc or not b.netloc:
        return True
    return (a.scheme, a.netloc) == (b.scheme, b.netloc)


def run_functional_walkthrough(
    *,
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
    event_publisher: Callable[[str, str, int, str, dict[str, Any] | None], None] | None = None,
    generation_mode: bool = False,
) -> dict[str, Any]:
    """Walk through normalised functional tests in a real browser without generating code.

    Browser actions are restricted to the guided testcase steps. Credentials are
    consumed from an in-memory one-time token and are never placed in the report,
    SQLite request payload, screenshots, prompts, or generated test data.
    """
    feature = _safe_feature(feature)
    testcase_path = feature_testcase_path("module2_uploaded", feature)
    if not testcase_path.exists():
        return {"ok": False, "stage": "testcases_missing", "message": "Load and normalize the testcase source before starting the AI functional walkthrough."}
    payload = read_json(testcase_path)
    scenarios = list(payload.get("scenarios") or [])[: max(1, min(int(max_scenarios or 20), 100))]
    if not scenarios:
        return {"ok": False, "stage": "no_scenarios", "message": "No normalized testcase scenarios are available for the walkthrough."}
    credentials = consume_ephemeral_credentials(credential_token)
    output_dir = walkthrough_directory(feature)
    output_dir.mkdir(parents=True, exist_ok=True)
    screenshots_dir = output_dir / "screenshots"
    if capture_screenshots:
        screenshots_dir.mkdir(parents=True, exist_ok=True)

    def emit(message: str, progress: int, status: str = "running", payload_data: dict[str, Any] | None = None) -> None:
        if event_publisher:
            event_publisher("functional_walkthrough", message, progress, status, payload_data)

    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        return {
            "ok": False,
            "stage": "python_playwright_missing",
            "message": "The AI Functional Walkthrough Agent requires the Python Playwright package and Chromium. Install project requirements, then run 'python -m playwright install chromium'. No code or framework files were changed.",
            "install_commands": ["pip install -r requirements.txt", "python -m playwright install chromium"],
        }

    emit((f"Preparing browser-grounded generation evidence for {len(scenarios)} testcase scenario(s)." if generation_mode else f"Preparing a no-code browser walkthrough for {len(scenarios)} testcase scenario(s)."), 8)
    scenario_results: list[dict[str, Any]] = []
    enhanced_payload = json.loads(json.dumps(payload, ensure_ascii=False, default=str))
    enhanced_by_id = {str(s.get("id")): s for s in enhanced_payload.get("scenarios") or []}
    current_origin = ""
    browser = None
    completed_steps = 0
    total_steps = sum(min(len(s.get("steps") or []), max_steps_per_scenario) for s in scenarios) or 1
    sessions: dict[str, dict[str, Any]] = {}
    locator_memory: dict[tuple[str, str], dict[str, Any]] = {}
    try:
        with sync_playwright() as pw:
            browser_type = pw.chromium
            launch_args: dict[str, Any] = {"headless": not bool(headed)}
            if browser_name in {"chrome", "msedge"}:
                launch_args["channel"] = browser_name
            if browser_executable:
                launch_args["executable_path"] = str(Path(browser_executable).expanduser())
            browser = browser_type.launch(**launch_args)

            for scenario_index, scenario in enumerate(scenarios, 1):
                scenario_id = str(scenario.get("id") or f"SCENARIO-{scenario_index}")
                title = str(scenario.get("title") or scenario_id)
                scenario_creds = _scenario_credentials(scenario, credentials)
                session_key = _session_key(scenario_creds)
                role = scenario_creds.get("role") or "default"
                session = sessions.get(session_key)
                if session is None:
                    context = browser.new_context(ignore_https_errors=True, viewport={"width": 1440, "height": 900})
                    page = context.new_page()
                    page.set_default_timeout(max(3000, min(int(action_timeout_seconds or 20) * 1000, 120000)))
                    session = {"context": context, "page": page, "authenticated": False, "role": role}
                    sessions[session_key] = session
                    emit(f"Created a secure browser session for credential role '{role.replace('_', ' ')}'.", 9, payload_data={"scenario_id": scenario_id, "credential_role": role})
                page = session["page"]
                if page.is_closed():
                    page = session["context"].new_page()
                    session["page"] = page
                emit(f"Starting browser walkthrough for {scenario_id}: {title}", 10 + int(75 * completed_steps / total_steps), payload_data={"scenario_id": scenario_id, "credential_role": role})
                start_url = _scenario_start_url(scenario, payload, base_url)
                if not start_url:
                    scenario_results.append({"scenario_id": scenario_id, "title": title, "ok": False, "status": "needs_base_url", "message": "No application URL was found in the testcase data or GUI."})
                    continue
                if current_origin and not _same_origin_allowed(current_origin, start_url, allow_cross_origin):
                    scenario_results.append({"scenario_id": scenario_id, "title": title, "ok": False, "status": "cross_origin_blocked", "message": f"Navigation to a different origin was blocked: {start_url}"})
                    continue
                if not current_origin:
                    current_origin = start_url
                page.goto(start_url, wait_until="domcontentloaded", timeout=max(15000, int(action_timeout_seconds or 20) * 1000))
                session["page"] = page
                if _looks_authenticated(page):
                    session["authenticated"] = True
                page.evaluate(_INTERACTION_LISTENER_SCRIPT)
                step_results: list[dict[str, Any]] = []
                scenario_ok = True
                enhanced_scenario = enhanced_by_id.get(scenario_id, {})
                enhanced_steps = enhanced_scenario.get("steps") or []

                for step_index, step in enumerate((scenario.get("steps") or [])[: max(1, min(int(max_steps_per_scenario or 80), 300))], 1):
                    completed_steps += 1
                    action = _step_action(step)
                    step_label = _normalise_text(step.get("target") or step.get("description") or f"Step {step_index}")
                    progress = 10 + int(75 * completed_steps / total_steps)
                    emit(f"{scenario_id} step {step_index}: {step_label}", progress, payload_data={"scenario_id": scenario_id, "step_index": step_index, "action": action})
                    sensitive = _is_sensitive_step(step)
                    mutating = _is_mutating_step(step)
                    value, value_source = _step_value(step, scenario_creds)
                    expected = str(step.get("expected") or "")
                    memory_key = (role, _step_memory_key(step))

                    if action == "goto":
                        destination = value or start_url
                        if not _same_origin_allowed(current_origin, destination, allow_cross_origin):
                            result = {"step_index": step_index, "original_step": step_label, "action": action, "ok": False, "status": "cross_origin_blocked", "message": "Cross-origin navigation was blocked by walkthrough policy."}
                            step_results.append(result); scenario_ok = False; break
                        page = _execute_action(page, "goto", None, destination, expected, int(action_timeout_seconds) * 1000)
                        session["page"] = page
                        session["authenticated"] = bool(session.get("authenticated") or _looks_authenticated(page))
                        result = {"step_index": step_index, "original_step": step_label, "enhanced_step": _enhance_step_text(step, action, None, page.title()), "action": action, "ok": True, "status": "verified", "page_url_after": page.url, "test_data": {"source": "testcase", "sensitive": False, "value": destination}}
                        step_results.append(result)
                        if step_index - 1 < len(enhanced_steps): enhanced_steps[step_index - 1]["walkthrough"] = result
                        continue

                    # Reuse the authenticated browser state and the locator evidence
                    # captured during the first scenario for this credential profile.
                    if session.get("authenticated") and _is_auth_step(step):
                        remembered = locator_memory.get(memory_key) or {}
                        result = {
                            "step_index": step_index,
                            "step_number": step.get("step_number") or str(step_index),
                            "original_step": step_label,
                            "enhanced_step": f"Reuse the authenticated {role.replace('_', ' ')} browser session; this login step does not need to be repeated.",
                            "action": action,
                            "ok": True,
                            "status": "authenticated_session_reused",
                            "confidence": float(remembered.get("confidence") or 0.98),
                            "locator": remembered.get("locator") or {},
                            "locator_candidates": remembered.get("locator_candidates") or [],
                            "page_url_after": page.url,
                            "page_title_after": page.title(),
                            "test_data": {"source": value_source, "sensitive": True, "value": "", "environment_variable": str(step.get("value_env") or "")},
                        }
                        step_results.append(result)
                        if step_index - 1 < len(enhanced_steps):
                            enhanced_steps[step_index - 1]["walkthrough"] = result
                        continue

                    if mutating:
                        if not allow_mutating_actions:
                            result = {"step_index": step_index, "original_step": step_label, "action": action, "ok": False, "status": "mutation_approval_required", "message": "This approved testcase step changes application data. Enable the QA mutation approval option and rerun."}
                            step_results.append(result); scenario_ok = False; break
                        if not _non_production_url(page.url or start_url):
                            result = {"step_index": step_index, "original_step": step_label, "action": action, "ok": False, "status": "production_mutation_blocked", "message": "AstraHeal will not autonomously perform data-changing actions on a URL that is not visibly marked as QA/test/sandbox/staging/dev/UAT."}
                            step_results.append(result); scenario_ok = False; break
                    if action == "fill" and _is_auth_step(step) and not value:
                        result = {"step_index": step_index, "original_step": step_label, "action": action, "ok": False, "status": "credentials_required", "message": f"Credentials for role '{role.replace('_', ' ')}' are missing. Reload the Excel source so its credential rows can be transferred to the volatile vault, or enter temporary credentials in the GUI."}
                        step_results.append(result); scenario_ok = False; break

                    page_url_before = page.url
                    page_title_before = page.title()
                    adaptive = _resolve_step_target_adaptively(
                        page=page,
                        step=step,
                        provider=provider,
                        model=model,
                        repo_root=framework_path or str(REPO_ROOT),
                        confidence_threshold=float(confidence_threshold),
                        action_timeout_ms=int(action_timeout_seconds) * 1000,
                        max_intermediate_actions=int(max_intermediate_actions),
                        event_publisher=event_publisher,
                        scenario_id=scenario_id,
                        step_index=step_index,
                        progress=progress,
                    )
                    page = adaptive.get("page") or page
                    session["page"] = page
                    decision = adaptive.get("decision") or {}
                    selected = adaptive.get("selected")
                    locator = adaptive.get("locator") or {"ok": False, "confidence": 0.0}
                    confidence = float(adaptive.get("confidence") or 0)
                    inserted_actions = list(adaptive.get("inserted_actions") or [])
                    human_guided = False

                    if not selected or not locator.get("ok") or confidence < float(confidence_threshold):
                        if not supervised or not headed:
                            result = {"step_index": step_index, "original_step": step_label, "action": action, "ok": False, "status": "no_verified_locator", "confidence": confidence, "message": adaptive.get("reason") or decision.get("reason") or "No sufficiently confident locator was found from the current DOM.", "locator_validation": locator.get("validation") or [], "inserted_actions": inserted_actions}
                            step_results.append(result); scenario_ok = False; break
                        previous_seq = int(page.evaluate("() => window.__astrahealInteractionSeq || 0") or 0)
                        human = _wait_for_human_interaction(page, previous_seq, manual_takeover_seconds, event_publisher, step_label)
                        if not human.get("ok") or not (human.get("locator") or {}).get("ok"):
                            result = {"step_index": step_index, "original_step": step_label, "action": action, "ok": False, "status": "human_guidance_timeout", "message": human.get("reason") or "No verified human interaction was captured.", "inserted_actions": inserted_actions}
                            step_results.append(result); scenario_ok = False; break
                        selected = human.get("element") or {}
                        locator_bundle = human.get("locator") or {}
                        locator = _verified_locator_for_element(page, locator_bundle, str(selected.get("element_id") or "")) if locator_bundle.get("ok") else locator_bundle
                        if not locator.get("ok"):
                            result = {"step_index": step_index, "original_step": step_label, "action": action, "ok": False, "status": "human_locator_ambiguous", "message": locator.get("reason") or "The human-selected element did not produce a unique reusable locator.", "locator_validation": locator.get("validation") or [], "inserted_actions": inserted_actions}
                            step_results.append(result); scenario_ok = False; break
                        confidence = float(locator.get("confidence") or 0)
                        human_guided = True

                    # When the testcase identifies the field but supplies no usable
                    # value, let the supervised tester enter/select it once. The
                    # value is not captured, while the exact locator is retained.
                    missing_action_value = action in {"fill", "select", "press"} and not value
                    if missing_action_value and not human_guided:
                        if not supervised or not headed:
                            result = {"step_index": step_index, "original_step": step_label, "action": action, "ok": False, "status": "test_data_required", "message": "This step has no executable test value. Supply it in the Excel Test Data column, an environment variable, or supervised browser input."}
                            step_results.append(result); scenario_ok = False; break
                        previous_seq = int(page.evaluate("() => window.__astrahealInteractionSeq || 0") or 0)
                        human = _wait_for_human_interaction(page, previous_seq, manual_takeover_seconds, event_publisher, f"{step_label} (supply the required test data)")
                        if not human.get("ok"):
                            result = {"step_index": step_index, "original_step": step_label, "action": action, "ok": False, "status": "test_data_guidance_timeout", "message": human.get("reason") or "Required test data was not entered."}
                            step_results.append(result); scenario_ok = False; break
                        human_guided = True
                        captured_value = "" if sensitive or _is_personal_data_step(step) else _read_non_sensitive_element_value(page, locator)
                        if captured_value:
                            value = captured_value
                            value_source = "human_supervised_input"
                        else:
                            value_source = "human_input_not_recorded"

                    if not human_guided:
                        page = _execute_action(page, action, locator, value, expected, int(action_timeout_seconds) * 1000)
                        session["page"] = page

                    is_login_submit = action == "click" and any(token in step_label.lower() for token in ("login", "sign in", "log in"))
                    if is_login_submit:
                        if not _wait_for_authentication_completion(page, manual_takeover_seconds, event_publisher):
                            result = {"step_index": step_index, "original_step": step_label, "action": action, "ok": False, "status": "mfa_or_login_timeout", "message": "Login was submitted, but the authenticated application page was not reached before the supervised timeout."}
                            step_results.append(result); scenario_ok = False; break
                        session["authenticated"] = True

                    enhanced_step = str(decision.get("enhanced_step") or "").strip() or _enhance_step_text(step, action, locator, page.title())
                    evidence = {
                        "step_index": step_index,
                        "step_number": step.get("step_number") or str(step_index),
                        "original_step": step_label,
                        "enhanced_step": enhanced_step,
                        "action": action,
                        "ok": True,
                        "status": "human_guided_verified" if human_guided else "verified",
                        "confidence": confidence,
                        "locator": {k: v for k, v in locator.items() if k not in {"all_candidates"}},
                        "locator_candidates": locator.get("all_candidates") or [],
                        "page_url_before": page_url_before,
                        "page_title_before": page_title_before,
                        "page_url_after": page.url,
                        "page_title_after": page.title(),
                        "page_state_before": hashlib.sha256(f"{page_url_before}|{page_title_before}".encode("utf-8", errors="ignore")).hexdigest()[:16],
                        "provider_reason": decision.get("reason"),
                        "decision_source": decision.get("decision_source") or "verified_dom",
                        "inserted_actions": inserted_actions,
                        "adaptive_action_count": len(inserted_actions),
                        "test_data": {
                            "source": value_source,
                            "sensitive": sensitive or value_source in {"username", "password"},
                            "value": "" if sensitive or _is_personal_data_step(step) or value_source in {"username", "password", "human_input_not_recorded"} else value,
                            "environment_variable": str(step.get("value_env") or ""),
                        },
                    }
                    locator_memory[memory_key] = evidence
                    if capture_screenshots and not sensitive and value_source not in {"username", "password"}:
                        shot = screenshots_dir / f"{safe_id(scenario_id)}-step-{step_index}.png"
                        page.screenshot(path=str(shot), full_page=False)
                        evidence["screenshot"] = str(shot.relative_to(REPO_ROOT))
                    step_results.append(evidence)
                    if step_index - 1 < len(enhanced_steps):
                        enhanced_steps[step_index - 1]["target"] = enhanced_step
                        enhanced_steps[step_index - 1]["walkthrough"] = evidence
                        safe_value = str((evidence.get("test_data") or {}).get("value") or "")
                        if safe_value and not bool((evidence.get("test_data") or {}).get("sensitive")):
                            enhanced_steps[step_index - 1]["value"] = safe_value
                            enhanced_steps[step_index - 1]["value_source"] = str((evidence.get("test_data") or {}).get("source") or "functional_walkthrough")

                if enhanced_scenario:
                    enhanced_scenario["steps"] = _expand_steps_with_inserted_actions(enhanced_steps, step_results)

                scenario_results.append({
                    "scenario_id": scenario_id,
                    "title": title,
                    "credential_role": role,
                    "ok": scenario_ok,
                    "status": "completed" if scenario_ok else "stopped_for_review",
                    "start_url": start_url,
                    "final_url": page.url,
                    "steps": step_results,
                    "verified_locator_count": sum(1 for item in step_results if item.get("locator")) + sum(len(item.get("inserted_actions") or []) for item in step_results),
                    "adaptive_intermediate_action_count": sum(len(item.get("inserted_actions") or []) for item in step_results),
                })
                if not scenario_ok:
                    emit((f"Browser grounding is partial for {scenario_id}; source generation will continue with verified and provisional evidence." if generation_mode else f"Walkthrough paused for {scenario_id}. Review the reported step before code generation."), progress, "warning", {"scenario_id": scenario_id})

            for session in sessions.values():
                try:
                    session["context"].close()
                except Exception:
                    pass
            browser.close()
            browser = None
    except Exception as exc:
        if browser is not None:
            try:
                browser.close()
            except Exception:
                pass
        error_text = str(exc)
        browser_missing = (
            "Executable doesn't exist" in error_text
            or "Please run the following command" in error_text and "playwright install" in error_text
            or "browserType.launch" in error_text and "executable" in error_text.lower()
        )
        invalid_custom_executable = bool(browser_executable) and (
            "executable" in error_text.lower() or not Path(browser_executable).expanduser().exists()
        )
        if invalid_custom_executable:
            stage = "custom_browser_executable_invalid"
            message = (
                "The configured custom Chromium/Comet executable could not be launched. "
                "Verify that the path points to an installed Chromium-compatible browser, or select Playwright Chromium. "
                "No framework or test files were changed."
            )
            install_commands: list[str] = []
        elif browser_missing:
            stage = "browser_runtime_missing"
            message = (
                "The Python Playwright package is available, but its Chromium browser runtime is not installed. "
                "Run 'python -m playwright install chromium' on the Central VM, then retry the walkthrough. "
                "No framework or test files were changed."
            )
            install_commands = ["python -m playwright install chromium"]
        else:
            stage = "browser_walkthrough_failed"
            message = f"AI functional walkthrough stopped safely: {type(exc).__name__}: {exc}"
            install_commands = []
        report = {
            "ok": False,
            "ready_for_generation": False,
            "stage": stage,
            "feature": feature,
            "message": message,
            "install_commands": install_commands,
            "technical_error": f"{type(exc).__name__}: {exc}",
            "scenarios": scenario_results,
            "generated_at": _now(),
        }
        write_json(walkthrough_report_path(feature), report)
        html_path = _write_walkthrough_html(feature, report)
        report["report_json"] = str(walkthrough_report_path(feature).relative_to(REPO_ROOT))
        report["report_html"] = str(html_path.relative_to(REPO_ROOT))
        return report

    ready = bool(scenario_results) and all(item.get("ok") for item in scenario_results)
    enhanced_path = walkthrough_enhanced_testcase_path(feature)
    enhanced_payload["walkthrough"] = {
        "completed_at": _now(),
        "provider": provider,
        "model": model,
        "ready_for_generation": ready,
        "report_file": str(walkthrough_report_path(feature).relative_to(REPO_ROOT)),
    }
    write_json(enhanced_path, enhanced_payload)
    report = {
        "ok": ready,
        "ready_for_generation": ready,
        "stage": "functional_walkthrough_completed" if ready else "functional_walkthrough_requires_review",
        "feature": feature,
        "provider": provider,
        "model": model,
        "framework_path": framework_path,
        "source_testcase_file": str(testcase_path.relative_to(REPO_ROOT)),
        "enhanced_testcase_file": str(enhanced_path.relative_to(REPO_ROOT)),
        "scenario_count": len(scenario_results),
        "completed_scenario_count": sum(1 for x in scenario_results if x.get("ok")),
        "verified_locator_count": sum(int(x.get("verified_locator_count") or 0) for x in scenario_results),
        "adaptive_intermediate_action_count": sum(int(x.get("adaptive_intermediate_action_count") or 0) for x in scenario_results),
        "scenarios": scenario_results,
        "adaptive_execution": {
            "goal_driven": True,
            "max_intermediate_actions_per_step": int(max_intermediate_actions),
            "ai_planner_enabled": provider not in {"", "deterministic", "rules", "none"},
            "deterministic_safe_fallback": True,
            "inserted_actions_persisted_for_generation": True,
        },
        "security": {
            "credentials_persisted": False,
            "credentials_in_prompts": False,
            "credentials_in_screenshots": False,
            "cross_origin_navigation_allowed": allow_cross_origin,
            "mutating_actions_approved": allow_mutating_actions,
        },
        "message": (("AI browser grounding completed. Enhanced steps, test-data bindings and verified live locators are ready for Playwright generation." if ready else "AI browser grounding completed partially. Generation will continue with all verified evidence plus safe provisional locator candidates.") if generation_mode else ("AI functional walkthrough completed. Enhanced steps, test-data bindings and verified live locators are ready for Playwright generation." if ready else "AI functional walkthrough completed partially. Review unresolved browser steps before relying on generated locators.")),
        "generated_at": _now(),
    }
    write_json(walkthrough_report_path(feature), report)
    html_path = _write_walkthrough_html(feature, report)
    report["report_json"] = str(walkthrough_report_path(feature).relative_to(REPO_ROOT))
    report["report_html"] = str(html_path.relative_to(REPO_ROOT))
    write_json(walkthrough_report_path(feature), report)
    emit(report["message"], 88, "done" if ready else "warning", {"ready_for_generation": ready, "verified_locator_count": report["verified_locator_count"], "report_html": report["report_html"]})
    return report
