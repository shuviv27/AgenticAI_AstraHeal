from __future__ import annotations


def build_coverage_map(testcase_json: dict) -> dict:
    scenarios = testcase_json.get("scenarios", []) if isinstance(testcase_json, dict) else []
    tags: dict[str, int] = {}
    for scenario in scenarios:
        for tag in scenario.get("tags", []):
            tags[tag] = tags.get(tag, 0) + 1
    return {"scenario_count": len(scenarios), "coverage_by_tag": tags, "status": "designed"}
