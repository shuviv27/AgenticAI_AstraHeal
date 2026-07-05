from __future__ import annotations

from qa_pipeline.agents.phase5_failure_healing.root_cause_agent import analyze_latest_failure


def classify_failure(error_text: str = "", feature: str = "feature", base_url: str = "") -> dict:
    """Backward-compatible failure classifier.

    New implementations should call analyze_latest_failure(), which reads Playwright JSON,
    execution logs, screenshots/traces metadata and dynamic DOM crawl evidence.
    """
    if error_text:
        lower = error_text.lower()
        if "127.0.0.1" in lower or "localhost" in lower:
            return {"category": "wrong_application_url", "auto_healable": True, "confidence": "high", "recommendation": "Apply URL guard and rerun"}
        if "locator" in lower or "tobevisible" in lower:
            return {"category": "locator_or_wait_issue", "auto_healable": True, "confidence": "medium", "recommendation": "Run dynamic DOM crawl and self-healing"}
        if "waitforurl" in lower or "navigation" in lower:
            return {"category": "navigation_or_sync_issue", "auto_healable": True, "confidence": "medium", "recommendation": "Normalize URL and use resilient navigation helper"}
        if "permission" in lower or "geolocation" in lower:
            return {"category": "browser_permission_issue", "auto_healable": True, "confidence": "medium", "recommendation": "Grant browser permissions in context"}
    report = analyze_latest_failure(feature=feature, base_url=base_url)
    return {
        "category": report.get("likely_root_cause", "unknown"),
        "auto_healable": report.get("auto_healable", False),
        "confidence": report.get("confidence", 0),
        "recommendation": (report.get("recommended_fix_plan") or ["Review RCA report"])[0],
    }
