from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urljoin

LOCAL_URL_RE = re.compile(r"https?://(?:127\.0\.0\.1|localhost)(?::\d+)?(?:/[^\s'\"]*)?", re.IGNORECASE)


def normalize_base_url(base_url: str | None) -> str:
    value = (base_url or "").strip()
    if not value:
        return ""
    if not re.match(r"^https?://", value, re.IGNORECASE):
        value = "https://" + value
    return value.rstrip("/")


def resolve_app_url(value: str | None, base_url: str | None) -> str:
    base = normalize_base_url(base_url)
    raw = (value or "").strip()
    if not raw:
        return base
    if LOCAL_URL_RE.match(raw):
        return base
    if re.match(r"^https?://", raw, re.IGNORECASE):
        return raw.rstrip("/.,)")
    if raw.startswith("/") and base:
        return urljoin(base + "/", raw.lstrip("/"))
    if base and not raw.startswith("env:"):
        return urljoin(base + "/", raw)
    return raw


def sanitize_testcase_urls(path: Path, base_url: str | None) -> dict:
    """Remove GUI/local URLs from normalized/AI testcase JSON.

    AI providers can accidentally copy the GUI address (127.0.0.1:8080/8088) into a
    testcase. This guardrail replaces those values with the application base URL and
    resolves relative app paths such as /marketplace against that base URL.
    """
    base = normalize_base_url(base_url)
    if not path.exists():
        return {"changed": False, "reason": "file_missing"}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"changed": False, "reason": f"json_read_failed: {exc}"}
    if not isinstance(data, dict):
        return {"changed": False, "reason": "not_object"}

    changed = False
    replaced: list[dict] = []
    if base:
        current = str(data.get("start_url") or "")
        fixed = resolve_app_url(current or base, base)
        if fixed and fixed != current:
            data["start_url"] = fixed
            changed = True
            replaced.append({"level": "root", "from": current, "to": fixed})

    for scenario_index, scenario in enumerate(data.get("scenarios", []) or []):
        if not isinstance(scenario, dict):
            continue
        current = str(scenario.get("start_url") or "")
        fixed = resolve_app_url(current or base, base)
        if base and fixed and fixed != current:
            scenario["start_url"] = fixed
            changed = True
            replaced.append({"scenario": scenario.get("id", scenario_index), "field": "start_url", "from": current, "to": fixed})
        for step_index, step in enumerate(scenario.get("steps", []) or []):
            if not isinstance(step, dict):
                continue
            action = str(step.get("action", "")).lower()
            value = step.get("value")
            if isinstance(value, str):
                new_value = value
                if LOCAL_URL_RE.search(new_value) and base:
                    new_value = LOCAL_URL_RE.sub(base, new_value)
                if action in {"goto", "launch", "open", "navigate"}:
                    new_value = resolve_app_url(new_value, base)
                elif isinstance(new_value, str) and new_value.startswith("/") and base:
                    # For expected navigation, keep relative paths as relative unless the AI
                    # pasted a localhost URL. Relative assertions are more flexible.
                    new_value = new_value
                if new_value != value:
                    step["value"] = new_value
                    changed = True
                    replaced.append({"scenario": scenario.get("id", scenario_index), "step": step_index, "field": "value", "from": value, "to": new_value})
            expected = step.get("expected")
            if isinstance(expected, str) and LOCAL_URL_RE.search(expected) and base:
                fixed_expected = LOCAL_URL_RE.sub(base, expected)
                step["expected"] = fixed_expected
                changed = True
                replaced.append({"scenario": scenario.get("id", scenario_index), "step": step_index, "field": "expected", "from": expected, "to": fixed_expected})

    if changed:
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return {"changed": changed, "base_url": base, "replaced": replaced}
