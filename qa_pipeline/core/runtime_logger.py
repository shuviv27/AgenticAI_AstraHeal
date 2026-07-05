from __future__ import annotations

import json
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from qa_pipeline.core.paths import QA_CACHE_DIR, GENERATED_PLAYWRIGHT_DIR

RUNTIME_DIR = QA_CACHE_DIR / "runtime"
RUNTIME_EVENTS = RUNTIME_DIR / "runtime-events.jsonl"
RUNTIME_STATUS = RUNTIME_DIR / "current-status.json"
RUNTIME_SUMMARY = GENERATED_PLAYWRIGHT_DIR / "reports" / "runtime-summary.json"
RUNTIME_MD = GENERATED_PLAYWRIGHT_DIR / "reports" / "runtime-summary.md"
RUNTIME_LIVE_HTML = GENERATED_PLAYWRIGHT_DIR / "reports" / "runtime-live-console.html"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure() -> None:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    RUNTIME_SUMMARY.parent.mkdir(parents=True, exist_ok=True)


def _next_event_id() -> int:
    if not RUNTIME_EVENTS.exists():
        return 1
    try:
        return len(RUNTIME_EVENTS.read_text(encoding="utf-8", errors="replace").splitlines()) + 1
    except Exception:
        return 1


def log_event(stage: str, message: str, *, status: str = "running", progress: int | None = None,
              feature: str = "", source_type: str = "", details: dict[str, Any] | None = None) -> dict[str, Any]:
    """Append an enterprise runtime event.

    The GUI, local live console, Prometheus/Grafana scrape endpoint and reports read this file,
    so long-running generation/execution is explainable instead of looking stuck. Messages are
    intentionally plain-English for debugging by non-developers.
    """
    _ensure()
    if progress is not None:
        try:
            progress = max(0, min(100, int(progress)))
        except Exception:
            progress = None
    event = {
        "id": _next_event_id(),
        "ts": _now(),
        "epoch_ms": int(time.time() * 1000),
        "stage": stage,
        "status": status,
        "progress": progress,
        "feature": feature,
        "source_type": source_type,
        "message": message,
        "details": details or {},
    }
    with RUNTIME_EVENTS.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")
    RUNTIME_STATUS.write_text(json.dumps(event, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    write_runtime_summary()
    return event


def reset_runtime_logs() -> dict[str, Any]:
    _ensure()
    for p in [RUNTIME_EVENTS, RUNTIME_STATUS, RUNTIME_SUMMARY, RUNTIME_MD, RUNTIME_LIVE_HTML]:
        try:
            if p.exists():
                p.unlink()
        except Exception:
            pass
    return log_event("runtime", "Runtime log history was reset by the user.", status="done", progress=0)


def read_events(limit: int = 250) -> list[dict[str, Any]]:
    if not RUNTIME_EVENTS.exists():
        return []
    lines = RUNTIME_EVENTS.read_text(encoding="utf-8", errors="replace").splitlines()[-max(1, limit):]
    events: list[dict[str, Any]] = []
    for line in lines:
        try:
            events.append(json.loads(line))
        except Exception:
            continue
    return events


def current_status() -> dict[str, Any]:
    if RUNTIME_STATUS.exists():
        try:
            return json.loads(RUNTIME_STATUS.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"stage": "not_started", "status": "idle", "progress": 0, "message": "No pipeline action has started yet."}


def write_runtime_summary() -> dict[str, Any]:
    events = read_events(5000)
    by_stage = Counter(e.get("stage", "unknown") for e in events)
    by_status = Counter(e.get("status", "unknown") for e in events)
    errors = [e for e in events if e.get("status") in {"error", "failed"} or "error" in str(e.get("message", "")).lower()]
    slow_or_waiting = [e for e in events if any(w in str(e.get("message", "")).lower() for w in ["sequential", "waiting", "slow", "codex", "batch"])]
    suggestions: list[str] = []
    if errors:
        suggestions.append("Review the latest failed stage first; do not continue to Playwright generation/execution until the active source context is correct.")
    if any("jira" in str(e.get("stage", "")).lower() for e in events):
        suggestions.append("For Jira Epic runs, verify the active source context lists only the child stories/tasks/bugs before generating Playwright.")
    if any("playwright_generation" == e.get("stage") for e in events):
        suggestions.append("Playwright code generation uses a guarded write-lock when multiple features share page/pageObjects files. This is slower but prevents corrupted reusable framework files.")
    if any("app_profile" == e.get("stage") for e in events):
        suggestions.append("For complex apps, provide URL, credentials/storage state, outerHTML/page source, known popups, iframe/shadow DOM notes, and test data to improve locator strategy.")
    summary = {
        "ok": True,
        "current": current_status(),
        "event_count": len(events),
        "by_stage": dict(by_stage),
        "by_status": dict(by_status),
        "recent_errors": errors[-25:],
        "slow_or_waiting_events": slow_or_waiting[-25:],
        "self_learning_suggestions": list(dict.fromkeys(suggestions)),
        "log_file": str(RUNTIME_EVENTS),
        "live_console_file": str(RUNTIME_LIVE_HTML),
        "grafana_url": "http://localhost:3001",
        "prometheus_targets_url": "http://localhost:9090/targets",
        "local_metrics_url": "http://127.0.0.1:8080/metrics",
    }
    _ensure()
    RUNTIME_SUMMARY.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    md = ["# Runtime Log Summary", "", f"Events: {len(events)}", "", "## Current", "", f"- Stage: {summary['current'].get('stage')}", f"- Status: {summary['current'].get('status')}", f"- Message: {summary['current'].get('message')}", "", "## Self-learning suggestions", ""]
    for s in summary["self_learning_suggestions"] or ["No suggestions yet."]:
        md.append(f"- {s}")
    md.extend(["", "## Recent errors", ""])
    for e in errors[-10:]:
        md.append(f"- {e.get('ts')} `{e.get('stage')}`: {e.get('message')}")
    RUNTIME_MD.write_text("\n".join(md) + "\n", encoding="utf-8")
    try:
        write_runtime_live_html()
    except Exception:
        pass
    return summary



def write_runtime_live_html() -> Path:
    """Write a self-refreshing local runtime console under generated-playwright/reports."""
    _ensure()
    events = read_events(250)
    current = current_status()
    rows = []
    for e in events[-150:]:
        rows.append(
            f"<tr><td>{e.get('id','')}</td><td>{e.get('ts','')}</td><td>{e.get('stage','')}</td><td>{e.get('status','')}</td><td>{e.get('progress','')}</td><td>{e.get('feature','')}</td><td>{str(e.get('message','')).replace('<','&lt;').replace('>','&gt;')}</td></tr>"
        )
    html = f"""<!doctype html><html><head><meta charset='utf-8'/><meta http-equiv='refresh' content='3'/>
<title>AI QA Runtime Console</title><style>body{{font-family:Segoe UI,Arial,sans-serif;background:#f8fafc;color:#172033;margin:24px}}.card{{background:white;border:1px solid #e2e8f0;border-radius:16px;padding:16px;margin-bottom:16px}}.bar{{height:16px;background:#e2e8f0;border-radius:999px;overflow:hidden}}.fill{{height:100%;background:#2563eb;width:{int(current.get('progress') or 0)}%}}table{{width:100%;border-collapse:collapse;font-size:12px}}th,td{{border-bottom:1px solid #e2e8f0;padding:8px;text-align:left;vertical-align:top}}th{{background:#eff6ff}}.ok{{color:#16a34a;font-weight:900}}.warn{{color:#d97706;font-weight:900}}.bad{{color:#dc2626;font-weight:900}}code{{background:#0f172a;color:#dbeafe;padding:4px 6px;border-radius:6px}}</style></head>
<body><h1>AI QA Runtime Console</h1><div class='card'><b>Current stage:</b> {current.get('stage')} &nbsp; <b>Status:</b> {current.get('status')} &nbsp; <b>Progress:</b> {current.get('progress') or 0}%<div class='bar'><div class='fill'></div></div><p>{str(current.get('message','')).replace('<','&lt;').replace('>','&gt;')}</p><p>This page auto-refreshes every 3 seconds and works even when Grafana is not logged in.</p></div><div class='card'><h2>Recent runtime events</h2><table><tr><th>#</th><th>Time</th><th>Stage</th><th>Status</th><th>%</th><th>Feature</th><th>Plain-English message</th></tr>{''.join(rows) if rows else '<tr><td colspan=7>No runtime events yet.</td></tr>'}</table></div><p>Raw log: <code>.qa-cache/runtime/runtime-events.jsonl</code></p></body></html>"""
    RUNTIME_LIVE_HTML.write_text(html, encoding="utf-8")
    return RUNTIME_LIVE_HTML

def prometheus_metrics() -> str:
    summary = write_runtime_summary()
    current = summary.get("current", {})
    lines = [
        "# HELP aiqa_runtime_events_total Total runtime events recorded by the AI QA pipeline.",
        "# TYPE aiqa_runtime_events_total counter",
        f"aiqa_runtime_events_total {int(summary.get('event_count', 0))}",
        "# HELP aiqa_runtime_current_progress Current GUI/pipeline progress percentage.",
        "# TYPE aiqa_runtime_current_progress gauge",
        f"aiqa_runtime_current_progress {int(current.get('progress') or 0)}",
        "# HELP aiqa_runtime_recent_errors Number of recent runtime errors captured.",
        "# TYPE aiqa_runtime_recent_errors gauge",
        f"aiqa_runtime_recent_errors {len(summary.get('recent_errors') or [])}",
    ]
    for stage, count in (summary.get("by_stage") or {}).items():
        safe_stage = str(stage).replace('"', '')[:80]
        lines.append(f'aiqa_runtime_stage_events_total{{stage="{safe_stage}"}} {int(count)}')
    for status, count in (summary.get("by_status") or {}).items():
        safe_status = str(status).replace('"', '')[:80]
        lines.append(f'aiqa_runtime_status_events_total{{status="{safe_status}"}} {int(count)}')
    stage = str(current.get("stage", "not_started")).replace('"', '')[:80]
    status = str(current.get("status", "idle")).replace('"', '')[:80]
    lines.append('# HELP aiqa_runtime_current_stage_info Current runtime stage/status as Prometheus labels.')
    lines.append('# TYPE aiqa_runtime_current_stage_info gauge')
    lines.append(f'aiqa_runtime_current_stage_info{{stage="{stage}",status="{status}"}} 1')
    return "\n".join(lines) + "\n"
