from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from qa_pipeline.core.paths import GENERATED_PLAYWRIGHT_DIR, REPORTS_DIR, REPO_ROOT

MATRIX_PATH = REPORTS_DIR / "self-learning-failure-matrix.json"
MD_PATH = REPORTS_DIR / "self-learning-failure-matrix.md"


def _norm(value: str) -> str:
    value = re.sub(r"C:\\[^\n\r\s]+", "<path>", value or "")
    value = re.sub(r"/[^\n\r\s]+", "<path>", value)
    value = re.sub(r"\d+", "#", value)
    return value.strip()[:3000]


def _signature(error: str, test_name: str = "") -> str:
    body = _norm(error) + "\n" + _norm(test_name)
    return hashlib.sha256(body.encode("utf-8", errors="ignore")).hexdigest()[:16]


def record_failure(error: str, test_name: str = "", category: str = "unknown", evidence: dict[str, Any] | None = None) -> dict[str, Any]:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    data = {"signatures": {}, "summary": {}}
    if MATRIX_PATH.exists():
        try: data = json.loads(MATRIX_PATH.read_text(encoding="utf-8"))
        except Exception: pass
    sig = _signature(error, test_name)
    rec = data.setdefault("signatures", {}).setdefault(sig, {"count": 0, "test_names": [], "categories": [], "last_error": "", "recommended_guardrails": []})
    rec["count"] += 1
    if test_name and test_name not in rec["test_names"]: rec["test_names"].append(test_name)
    if category and category not in rec["categories"]: rec["categories"].append(category)
    rec["last_error"] = _norm(error)
    if evidence: rec["last_evidence"] = evidence
    rec["recommended_guardrails"] = _guardrails_for(rec["last_error"], rec["categories"])
    counts = Counter()
    for r in data.get("signatures", {}).values():
        for c in r.get("categories", ["unknown"]): counts[c] += r.get("count", 1)
    data["summary"] = {"total_signatures": len(data.get("signatures", {})), "category_counts": dict(counts)}
    MATRIX_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False)+"\n", encoding="utf-8")
    _write_md(data)
    return {"ok": True, "signature": sig, "matrix_file": str(MATRIX_PATH.relative_to(REPO_ROOT)), "markdown_file": str(MD_PATH.relative_to(REPO_ROOT)), "record": rec}


def _guardrails_for(error: str, categories: list[str]) -> list[str]:
    e = (error or "").lower()
    out = []
    if "strict mode violation" in e:
        out.append("Add disambiguation rule: prefer exact role/name + container/section scoping.")
    if "location permission handled" in e or "browser permission handled" in e or "permission popup handled" in e:
        out.append("Treat permission-handling phrases as browser actions, not visible text assertions; use handle_location_permission and ZIP/geolocation fallback.")
    if "testcase1page" in e or "scrum" in e and "pageobject" in e or "duplicate locator" in e or "duplicate method" in e:
        out.append("Do not create testcase/story-specific Page Objects. Resolve steps to real application pages such as HomePage, FindStorePage, LoginPage, CheckoutPage and reuse existing page methods/locators.")
    if "could not find visible text" in e or "not visible" in e:
        out.append("Validate generated assertions against DOM/page-source evidence before script creation.")
    if "timeout" in e:
        out.append("Replace generic waits with assertion-driven readiness and targeted navigation/action waits.")
    if "networkidle" in e:
        out.append("Never use networkidle as readiness for production SPA/analytics-heavy pages.")
    if "locator" in e or "selector" in e:
        out.append("Patch locator in pageObjects only; rerun tsc/review/targeted test before accepting.")
    if not out:
        out.append("Route to RCA with trace/screenshot/video/error context; require confidence before auto-heal.")
    return out


def _write_md(data: dict[str, Any]) -> None:
    lines = ["# Self-Learning Failure Matrix", "", "This file records repeated failure signatures so the generator/RCA/self-healer can improve guardrails over time.", ""]
    lines.append("## Summary")
    for k,v in (data.get("summary") or {}).items(): lines.append(f"- **{k}**: `{v}`")
    lines += ["", "## Signatures", ""]
    for sig, rec in sorted((data.get("signatures") or {}).items(), key=lambda kv: kv[1].get('count',0), reverse=True):
        lines.append(f"### {sig} — count {rec.get('count')}")
        lines.append(f"- Tests: {', '.join(rec.get('test_names', [])) or 'n/a'}")
        lines.append(f"- Categories: {', '.join(rec.get('categories', [])) or 'unknown'}")
        lines.append("- Guardrails:")
        for g in rec.get("recommended_guardrails", []): lines.append(f"  - {g}")
        lines.append("")
    MD_PATH.write_text("\n".join(lines)+"\n", encoding="utf-8")


def summarize_failure_learning() -> dict[str, Any]:
    if not MATRIX_PATH.exists():
        return {"ok": True, "summary": {"total_signatures": 0}, "message": "No failures recorded yet.", "matrix_file": str(MATRIX_PATH.relative_to(REPO_ROOT))}
    data = json.loads(MATRIX_PATH.read_text(encoding="utf-8"))
    return {"ok": True, "summary": data.get("summary", {}), "signatures": data.get("signatures", {}), "matrix_file": str(MATRIX_PATH.relative_to(REPO_ROOT)), "markdown_file": str(MD_PATH.relative_to(REPO_ROOT))}
