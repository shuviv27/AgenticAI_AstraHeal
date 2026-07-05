from __future__ import annotations


def score_requirement_scenarios(testcase_json: dict) -> dict:
    scenarios = testcase_json.get("scenarios", []) if isinstance(testcase_json, dict) else []
    missing_url = [s.get("id") or s.get("title") for s in scenarios if not s.get("start_url")]
    score = 100
    if not scenarios:
        score -= 50
    if missing_url:
        score -= min(30, len(missing_url) * 3)
    return {"quality_score": max(score, 0), "scenario_count": len(scenarios), "missing_start_url": missing_url, "recommendation": "ingest" if score >= 70 else "warn"}
