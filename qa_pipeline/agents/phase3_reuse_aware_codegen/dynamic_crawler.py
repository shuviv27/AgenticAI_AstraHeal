from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from qa_pipeline.core.commands import resolve_command, run_command
from qa_pipeline.core.paths import GENERATED_PLAYWRIGHT_DIR, REPORTS_DIR, REPO_ROOT
from qa_pipeline.core.url_guard import normalize_base_url


def crawl_dynamic_page(base_url: str = "", feature: str = "feature", headed: bool = False) -> dict[str, Any]:
    """Run a Playwright DOM crawler before generation.

    The crawler explores the complete initial page, auto-scrolls to trigger lazy-loaded
    sections, accepts browser permissions, captures a full-page screenshot, and writes a
    DOM map that AI/codegen can use for difficult dynamic components.
    """
    base = normalize_base_url(base_url)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    if not base:
        return {"ok": False, "skipped": True, "reason": "base_url_missing"}
    if resolve_command("npm") is None:
        return {"ok": False, "skipped": True, "reason": "npm_not_found"}
    script = GENERATED_PLAYWRIGHT_DIR / "scripts" / "crawlDynamicPage.ts"
    if not script.exists():
        return {"ok": False, "skipped": True, "reason": f"crawler_missing: {script}"}
    args = [
        "npm", "--prefix", str(GENERATED_PLAYWRIGHT_DIR), "run", "crawl:dynamic", "--",
        "--url", base,
        "--feature", feature,
    ]
    if headed:
        args.append("--headed")
    proc = run_command(args, cwd=REPO_ROOT, timeout=240, extra_env={"BASE_URL": base})
    report_path = REPORTS_DIR / "dynamic-dom-map.json"
    payload: dict[str, Any] = {
        "ok": proc.ok,
        "command": proc.command,
        "returncode": proc.returncode,
        "stdout": proc.stdout[-4000:],
        "stderr": proc.stderr[-4000:],
        "error": proc.error,
        "dom_map": str(report_path.relative_to(REPO_ROOT)) if report_path.exists() else "",
    }
    if report_path.exists():
        try:
            data = json.loads(report_path.read_text(encoding="utf-8"))
            payload["summary"] = data.get("summary", {})
        except Exception:
            pass
    return payload
