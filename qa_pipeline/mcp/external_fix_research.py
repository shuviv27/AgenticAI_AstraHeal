from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from qa_pipeline.core.paths import REPORTS_DIR

REPORT_DIR = REPORTS_DIR / "existing-framework" / "external-research"
DEFAULT_CONFIG_NAME = ".astraheal-external-research.json"


def _html(value: Any) -> str:
    return str(value if value is not None else "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _read_json(path: Path, default: Any) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        pass
    return default


def _default_config() -> dict[str, Any]:
    return {
        "enabled": False,
        "mode": "proposal_only",
        "security_note": "External research is disabled by default. Enable only after enterprise security approval because public code/search context can be stale, incompatible, or unsafe.",
        "allowed_sources": ["github_mcp", "stackoverflow_search_mcp", "internal_repos_mcp"],
        "github_mcp": {
            "enabled": False,
            "server_name": "github",
            "recommended_scope": "read-only repository/code search; no write, issue, PR, or secret access for RCA research",
        },
        "stackoverflow_search_mcp": {
            "enabled": False,
            "server_name": "stackoverflow-search",
            "recommended_scope": "read-only search snippets used as advisory context only",
        },
        "decision_rules": [
            "Never copy public code directly into the enterprise framework.",
            "Use external research only to compare patterns and safety tradeoffs.",
            "Prefer official Playwright guidance and the existing framework's own POM conventions.",
            "Any external-inspired change must pass local failed-only rerun and remain inside allowed_files scope.",
        ],
    }


def ensure_external_research_config(framework_path: str | Path = "") -> dict[str, Any]:
    root = Path(framework_path).expanduser().resolve() if framework_path else None
    cfg = _default_config()
    path = None
    if root:
        path = root / DEFAULT_CONFIG_NAME
        if not path.exists():
            try:
                path.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            except Exception:
                pass
        loaded = _read_json(path, {})
        if isinstance(loaded, dict) and loaded:
            cfg.update(loaded)
    env_enabled = os.environ.get("ASTRAHEAL_EXTERNAL_RESEARCH_ENABLED", "").strip().lower()
    if env_enabled in {"1", "true", "yes", "on"}:
        cfg["enabled"] = True
    if os.environ.get("ASTRAHEAL_GITHUB_MCP_ENABLED", "").strip().lower() in {"1", "true", "yes", "on"}:
        cfg.setdefault("github_mcp", {})["enabled"] = True
    cfg["config_path"] = str(path) if path else ""
    return cfg


def collect_external_fix_research(framework_path: str | Path, failed_specs: list[str], failure_text: str = "", classification: str = "") -> dict[str, Any]:
    """Return advisory external-research context for RCA/self-healing prompts.

    This module intentionally does not perform public network calls directly.
    It provides an MCP-ready, enterprise-safe contract. Organizations can wire
    approved MCP search servers to the generated queries/config while this code
    remains offline-safe and deterministic by default.
    """
    root = Path(framework_path).expanduser().resolve() if framework_path else Path.cwd()
    cfg = ensure_external_research_config(root)
    low = (failure_text or "").lower()
    topics: list[str] = []
    if "intercepts pointer events" in low or "not visible" in low or "outside of the viewport" in low:
        topics.append("Playwright locator click intercepted pointer events overlay scrollIntoViewIfNeeded")
    if "locator" in low or "tobevisible" in low or "not found" in low:
        topics.append("Playwright locator not found stable selector Page Object Model getByRole getByTestId")
    if "timeout" in low or "networkidle" in low or "waitforurl" in low:
        topics.append("Playwright timeout navigation wait strategy dynamic website")
    if not topics:
        topics.append("Playwright TypeScript RCA self healing page object model flaky test")
    queries = []
    for spec in failed_specs[:8]:
        base = f"{Path(spec).name} {classification or ''}".strip()
        for topic in topics[:3]:
            queries.append(f"{topic} {base}".strip())
    queries = list(dict.fromkeys(queries))[:12]
    report = {
        "ok": True,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "enabled": bool(cfg.get("enabled")),
        "mode": cfg.get("mode") or "proposal_only",
        "config_path": cfg.get("config_path"),
        "failed_specs": failed_specs[:20],
        "classification": classification,
        "queries": queries,
        "mcp_ready_sources": cfg.get("allowed_sources") or [],
        "github_mcp_enabled": bool((cfg.get("github_mcp") or {}).get("enabled")),
        "stackoverflow_search_mcp_enabled": bool((cfg.get("stackoverflow_search_mcp") or {}).get("enabled")),
        "decision_rules": cfg.get("decision_rules") or [],
        "message": "External MCP research is configured and enabled." if cfg.get("enabled") else "External MCP research is available but disabled by default. Enable after enterprise security approval using .astraheal-external-research.json or ASTRAHEAL_EXTERNAL_RESEARCH_ENABLED=true.",
        "advisory_note": "External GitHub/StackOverflow patterns are advisory only; final patch must follow local framework conventions, allowed_files scope, backup, validation, and failed-only rerun.",
    }
    write_external_research_report(report)
    return report


def write_external_research_report(report: dict[str, Any]) -> Path:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    rows = "".join(f"<li><code>{_html(q)}</code></li>" for q in report.get("queries") or [])
    rules = "".join(f"<li>{_html(x)}</li>" for x in report.get("decision_rules") or [])
    html = f"""<!doctype html><html><head><meta charset='utf-8'/><title>External MCP Fix Research Context</title>
<style>body{{font-family:Segoe UI,Arial,sans-serif;background:#f8fafc;color:#0f172a;margin:24px}}.card{{background:white;border:1px solid #dbe3ef;border-radius:14px;padding:16px;margin:14px 0}}code{{background:#0f172a;color:#dbeafe;padding:3px 6px;border-radius:6px}}pre{{white-space:pre-wrap;background:#0f172a;color:#dbeafe;padding:12px;border-radius:10px}}</style></head><body>
<h1>External MCP Fix Research Context</h1>
<div class='card'><p><b>Status:</b> {_html('enabled' if report.get('enabled') else 'disabled by default')}</p><p>{_html(report.get('message'))}</p><p>{_html(report.get('advisory_note'))}</p></div>
<div class='card'><h2>Generated research queries</h2><ul>{rows or '<li>No queries generated.</li>'}</ul></div>
<div class='card'><h2>Decision rules</h2><ol>{rules or '<li>Use external information as advisory context only.</li>'}</ol></div>
<div class='card'><h2>Raw context</h2><pre>{_html(json.dumps(report, indent=2, ensure_ascii=False))}</pre></div>
</body></html>"""
    out = REPORT_DIR / "external-mcp-fix-research.html"
    out.write_text(html, encoding="utf-8")
    (REPORT_DIR / "external-mcp-fix-research.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return out
