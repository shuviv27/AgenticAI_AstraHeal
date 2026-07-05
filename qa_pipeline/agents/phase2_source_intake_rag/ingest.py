from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from qa_pipeline.core.io import read_json, write_json
from qa_pipeline.core.paths import feature_testcase_path, ensure_dirs
from qa_pipeline.core.schemas import TestScenario, TestStep
from qa_pipeline.core.text import safe_id


def _normalise_step(raw: dict, default_page: str) -> TestStep:
    return TestStep(
        action=raw.get("action", "verify"),
        target=raw.get("target", raw.get("name", "page")),
        value=raw.get("value"),
        page=raw.get("page", default_page),
        expected=raw.get("expected"),
    )


def write_functional_testcases_markdown(json_path: Path, payload: dict) -> Path:
    """Write a user-readable step-by-step Markdown view next to testcase JSON."""
    md_path = json_path.with_name(json_path.name.replace('.scenarios.json', '.scenarios.md')) if json_path.name.endswith('.scenarios.json') else json_path.with_suffix('.md')
    scenarios = payload.get('scenarios', []) or []
    lines: list[str] = [
        f"# Functional Testcases — {payload.get('feature', json_path.stem)}",
        "",
        "This file is generated before Playwright automation. It is written in simple business language so QA/business users can review the expected test flow.",
        "",
        f"- Source type: `{payload.get('source_type', '')}`",
        f"- Source: `{payload.get('source', payload.get('source_ref', ''))}`",
        f"- Total scenarios: **{len(scenarios)}**",
        "",
    ]
    for idx, s in enumerate(scenarios, 1):
        lines.extend([
            f"## {idx}. {s.get('title', s.get('id', 'Scenario'))}",
            "",
            f"- Scenario ID: `{s.get('id', '')}`",
            f"- Priority: `{s.get('priority', 'medium')}`",
            f"- Start URL: `{s.get('start_url') or 'Use project BASE_URL'}`",
            f"- Expected result: {s.get('expected_result', '')}",
            "",
            "### Step-by-step actions",
            "",
        ])
        steps = s.get('steps', []) or []
        if not steps:
            lines.append("No steps generated yet.")
        for step_index, step in enumerate(steps, 1):
            action = str(step.get('action', 'verify')).replace('_', ' ')
            target = step.get('target') or 'page'
            value = step.get('value') or step.get('expected') or ''
            if value:
                lines.append(f"{step_index}. **{action.title()}** `{target}` with/expecting `{value}`")
            else:
                lines.append(f"{step_index}. **{action.title()}** `{target}`")
        lines.append("")
    md_path.write_text("\n".join(lines).rstrip() + "\n", encoding='utf-8')
    return md_path


def ingest_source(source: Path, source_type: str, feature: str) -> Path:
    """Convert source-specific input into normalized functional testcase JSON.

    For Jira/Confluence/Test Management tools this function expects already-exported JSON.
    For PDF/SRS in this starter build, place extracted text/JSON into samples or plug in the parser adapter.
    """
    ensure_dirs()
    raw = read_json(source)
    page = raw.get("page") or raw.get("feature") or feature
    scenarios: list[TestScenario] = []

    for index, item in enumerate(raw.get("scenarios", []), start=1):
        scenario_id = item.get("id") or f"{source_type.upper()}-{safe_id(feature)}-{index:03d}"
        steps = [_normalise_step(s, page) for s in item.get("steps", [])]
        scenarios.append(TestScenario(
            id=scenario_id,
            title=item.get("title", f"{feature} scenario {index}"),
            feature=feature,
            page=item.get("page", page),
            source_type=source_type,
            source_ref=raw.get("source_ref", source.name),
            priority=item.get("priority", raw.get("priority", "medium")),
            tags=item.get("tags", raw.get("tags", [feature])),
            preconditions=item.get("preconditions", []),
            steps=steps,
            expected_result=item.get("expected_result", "Expected result should be verified"),
            start_url=item.get("start_url") or raw.get("start_url"),
        ))

    out = feature_testcase_path(source_type, feature)
    payload = {
        "id": str(uuid4()),
        "feature": feature,
        "source_type": source_type,
        "source": str(source),
        "scenarios": [s.to_dict() for s in scenarios],
    }
    write_json(out, payload)
    write_functional_testcases_markdown(out, payload)
    return out
