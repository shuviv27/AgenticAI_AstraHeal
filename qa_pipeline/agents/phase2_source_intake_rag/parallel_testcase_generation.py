from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from qa_pipeline.agents.phase2_source_intake_rag.ingest import ingest_source
from qa_pipeline.core.paths import QA_CACHE_DIR, REPO_ROOT
from qa_pipeline.core.text import safe_id
from qa_pipeline.core.url_guard import sanitize_testcase_urls
from qa_pipeline.core.runtime_logger import log_event
from qa_pipeline.parsers.source_parser import normalize_source_to_json


def _feature_from_title(prefix: str, title: str, fallback_index: int) -> str:
    key_match = re.search(r"\b[A-Z][A-Z0-9]+-\d+\b", title or "")
    if key_match:
        return key_match.group(0).lower().replace("-", "_")
    return safe_id(f"{prefix}-{title or fallback_index}")[:80] or f"{prefix}_{fallback_index}"


def generate_one_text_source(text: str, feature: str, source_type: str = "jira_epics", base_url: str = "") -> dict[str, Any]:
    feature = safe_id(feature) or "jira_case"
    log_event("testcase_generation", f"Normalizing testcase source for {feature}", progress=35, feature=feature, source_type=source_type)
    work = QA_CACHE_DIR / "parallel_generation" / feature
    work.mkdir(parents=True, exist_ok=True)
    src = work / f"{feature}.txt"
    src.write_text(text or "", encoding="utf-8")
    normalized = normalize_source_to_json(src, source_type, feature, pasted_text=text, base_url=base_url)
    sanitize_testcase_urls(normalized, base_url)
    testcase = ingest_source(normalized, source_type, feature)
    log_event("testcase_generation", f"Functional testcase JSON/Markdown generated for {feature}", status="done", progress=70, feature=feature, source_type=source_type)
    return {
        "ok": testcase.exists(),
        "feature": feature,
        "source_file": str(src.relative_to(REPO_ROOT)),
        "normalized_file": str(normalized.relative_to(REPO_ROOT)),
        "testcase_file": str(testcase.relative_to(REPO_ROOT)),
    }


def generate_parallel(items: list[dict[str, str]], source_type: str = "jira_epics", base_url: str = "", max_workers: int = 4) -> dict[str, Any]:
    """Generate functional testcase JSON/MD for multiple source blocks concurrently.

    This is intentionally deterministic and file-isolated. AI/Codex can still be used later at the
    Playwright generation step for each feature, but parallel ingestion should not corrupt shared files.
    """
    max_workers = max(1, min(int(max_workers or 1), 8))
    log_event("testcase_generation", f"Starting parallel functional testcase generation for {len(items)} item(s) using {max_workers} worker(s)", progress=10, source_type=source_type, details={"item_count": len(items), "max_workers": max_workers})
    results: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        future_map = {}
        for idx, item in enumerate(items, start=1):
            title = item.get("title") or item.get("key") or f"item-{idx}"
            feature = item.get("feature") or _feature_from_title("jira", title, idx)
            text = item.get("text") or item.get("body") or title
            future_map[pool.submit(generate_one_text_source, text, feature, source_type, base_url)] = feature
        for future in as_completed(future_map):
            feature = future_map[future]
            try:
                results.append(future.result())
            except Exception as exc:
                errors.append({"feature": feature, "error": f"{type(exc).__name__}: {exc}"})
                log_event("testcase_generation", f"Functional testcase generation failed for {feature}: {type(exc).__name__}: {exc}", status="error", progress=60, feature=feature, source_type=source_type)
    summary = {
        "ok": not errors,
        "max_workers": max_workers,
        "generated_count": len([r for r in results if r.get("ok")]),
        "results": sorted(results, key=lambda x: x.get("feature", "")),
        "errors": errors,
        "message": "Parallel testcase generation completed. Use Generate Reusable Playwright per feature or batch generation next.",
    }
    out = QA_CACHE_DIR / "parallel_generation" / "parallel-generation-summary.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    log_event("testcase_generation", f"Parallel testcase generation completed: {summary['generated_count']}/{len(items)} generated", status="done" if summary.get("ok") else "warning", progress=100, source_type=source_type, details=summary)
    return summary
