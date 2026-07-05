from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from qa_pipeline.core.paths import QA_CACHE_DIR, GENERATED_PLAYWRIGHT_DIR

AI_MEMORY_DIR = QA_CACHE_DIR / "ai-memory"
ACTION_HISTORY_JSONL = AI_MEMORY_DIR / "action-history.jsonl"
ACTION_MEMORY_JSON = AI_MEMORY_DIR / "action-memory-summary.json"
ACTION_HISTORY_HTML = GENERATED_PLAYWRIGHT_DIR / "reports" / "ai-action-history.html"

SENSITIVE_KEYS = {"password", "token", "secret", "api_key", "apikey", "authorization", "cookie"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure() -> None:
    AI_MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    ACTION_HISTORY_HTML.parent.mkdir(parents=True, exist_ok=True)


def _sanitize(value: Any, limit: int = 4000) -> Any:
    if isinstance(value, dict):
        clean = {}
        for k, v in value.items():
            if any(s in str(k).lower() for s in SENSITIVE_KEYS):
                clean[k] = "***redacted***"
            else:
                clean[k] = _sanitize(v, limit=limit)
        return clean
    if isinstance(value, list):
        return [_sanitize(v, limit=limit) for v in value[:50]]
    text = str(value if value is not None else "")
    return text[:limit]


def record_action(action: str, status: str = "done", message: str = "", details: dict[str, Any] | None = None) -> dict[str, Any]:
    """Persist GUI/backend action history for AI memory and audit.

    This is not hidden chain-of-thought. It stores observable actions, evidence pointers,
    RCA/self-healing outcomes, and human-readable messages so future Codex/Ollama prompts
    can retrieve historical knowledge safely.
    """
    _ensure()
    event = {
        "ts": _now(),
        "epoch_ms": int(time.time() * 1000),
        "action": action,
        "status": status,
        "message": message,
        "details": _sanitize(details or {}),
    }
    with ACTION_HISTORY_JSONL.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")
    write_action_memory_summary()
    return event


def read_action_history(limit: int = 200) -> list[dict[str, Any]]:
    if not ACTION_HISTORY_JSONL.exists():
        return []
    lines = ACTION_HISTORY_JSONL.read_text(encoding="utf-8", errors="replace").splitlines()[-max(1, limit):]
    rows = []
    for line in lines:
        try:
            rows.append(json.loads(line))
        except Exception:
            continue
    return rows


def write_action_memory_summary() -> dict[str, Any]:
    _ensure()
    rows = read_action_history(2000)
    by_action: dict[str, int] = {}
    by_status: dict[str, int] = {}
    important = []
    for r in rows:
        by_action[r.get("action", "unknown")] = by_action.get(r.get("action", "unknown"), 0) + 1
        by_status[r.get("status", "unknown")] = by_status.get(r.get("status", "unknown"), 0) + 1
        msg = str(r.get("message", "")).lower()
        if any(k in msg for k in ["rca", "self-heal", "healing", "failed", "codex", "patch", "headed", "framework"]):
            important.append(r)
    summary = {
        "ok": True,
        "history_count": len(rows),
        "by_action": by_action,
        "by_status": by_status,
        "last_50_important_events": important[-50:],
        "jsonl": str(ACTION_HISTORY_JSONL),
        "html": str(ACTION_HISTORY_HTML),
        "note": "Use this memory as historical observable context for RCA/self-healing prompts; do not treat it as hidden reasoning.",
    }
    ACTION_MEMORY_JSON.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    write_action_history_html(rows[-250:])
    return summary


def write_action_history_html(rows: list[dict[str, Any]] | None = None) -> Path:
    _ensure()
    rows = rows if rows is not None else read_action_history(250)
    def h(x: Any) -> str:
        return str(x if x is not None else "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    trs = []
    for r in rows[-250:]:
        trs.append(f"<tr><td>{h(r.get('ts'))}</td><td>{h(r.get('action'))}</td><td>{h(r.get('status'))}</td><td>{h(r.get('message'))}</td></tr>")
    html = f"""<!doctype html><html><head><meta charset='utf-8'/><title>AI Action History Memory</title>
<style>body{{font-family:Segoe UI,Arial,sans-serif;background:#f8fafc;color:#0f172a;margin:24px}}.card{{background:white;border:1px solid #dbe3ef;border-radius:14px;padding:16px;margin-bottom:16px}}table{{width:100%;border-collapse:collapse}}td,th{{border-bottom:1px solid #e2e8f0;padding:8px;text-align:left;vertical-align:top}}th{{background:#eff6ff}}code{{background:#0f172a;color:#dbeafe;padding:3px 6px;border-radius:6px}}</style></head><body>
<h1>AI Action History Memory</h1><div class='card'><p>This report stores observable GUI/backend actions, RCA/self-healing outputs, Codex login actions, execution mode, and patch history. It is used as enterprise AI memory for future RCA and self-healing context.</p><p>Raw memory: <code>.qa-cache/ai-memory/action-history.jsonl</code></p></div><div class='card'><table><tr><th>Time</th><th>Action</th><th>Status</th><th>Message</th></tr>{''.join(trs) if trs else '<tr><td colspan=4>No action history yet.</td></tr>'}</table></div></body></html>"""
    ACTION_HISTORY_HTML.write_text(html, encoding="utf-8")
    return ACTION_HISTORY_HTML
