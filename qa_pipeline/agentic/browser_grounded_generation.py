from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from qa_pipeline.agentic.credential_vault import (
    get_feature_credential_profiles,
    store_ephemeral_credentials,
)
from qa_pipeline.agentic.functional_walkthrough import (
    run_functional_walkthrough,
    walkthrough_enhanced_testcase_path,
    walkthrough_report_path,
)
from qa_pipeline.core.io import read_json
from qa_pipeline.core.operation_control import check_cancelled
from qa_pipeline.core.paths import REPO_ROOT
from qa_pipeline.core.runtime_logger import log_event
from qa_pipeline.mcp.playwright_mcp import mcp_status


def _non_production_url(url: str) -> bool:
    value = str(url or "").lower()
    return any(token in value for token in ("localhost", "127.0.0.1", "qa", "test", "sandbox", "staging", "stage", "dev", "uat"))


def _write_codegen_replay(feature: str, framework_path: str, report: dict[str, Any]) -> str:
    """Write a codegen-compatible replay artifact from verified browser evidence.

    This is not represented as Playwright's interactive recorder output. It is a
    deterministic TypeScript replay file assembled from locators that were
    actually validated in the browser. The normal Playwright codegen command is
    still included in the report as an optional human refinement path.
    """
    root = Path(framework_path).expanduser().resolve()
    out_dir = root / ".aiqa-history" / "add-new-tests" / "browser-grounding"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{feature}-verified-replay.ts"
    lines = [
        "import { test, expect } from '@playwright/test';",
        "",
        f"test.describe({json.dumps(feature + ' browser-grounding replay')}, () => {{",
    ]
    for scenario in report.get("scenarios") or []:
        scenario_id = str(scenario.get("scenario_id") or "SCENARIO")
        title = str(scenario.get("title") or scenario_id)
        lines.append(f"  test.skip({json.dumps(scenario_id + ' - ' + title)}, async ({{ page }}) => {{")
        for item in scenario.get("steps") or []:
            if item.get("action") == "goto" and item.get("page_url_after"):
                lines.append(f"    await page.goto({json.dumps(str(item.get('page_url_after')))});")
                continue
            loc = item.get("locator") or {}
            expr = str(loc.get("playwright_expression") or "")
            if not expr:
                strategy = str(loc.get("strategy") or "")
                value = json.dumps(str(loc.get("value") or ""))
                if strategy == "testId": expr = f"page.getByTestId({value})"
                elif strategy == "role":
                    role = str(loc.get('role') or '').strip()
                    if role and str(loc.get('value') or '').strip():
                        expr = f"page.getByRole({json.dumps(role)}, {{ name: {value} }})"
                elif strategy == "label": expr = f"page.getByLabel({value})"
                elif strategy == "placeholder": expr = f"page.getByPlaceholder({value})"
                elif strategy == "text": expr = f"page.getByText({value})"
                elif strategy == "css": expr = f"page.locator({value})"
            if not expr:
                continue
            action = str(item.get("action") or "")
            label = str(item.get("enhanced_step") or item.get("original_step") or "verified browser action")
            lines.append(f"    // {label.replace(chr(10), ' ')}")
            if action == "click": lines.append(f"    await {expr}.click();")
            elif action == "fill": lines.append(f"    await {expr}.fill(''); // value intentionally omitted")
            elif action == "select": lines.append(f"    await {expr}.selectOption({{ label: '' }}); // value intentionally omitted")
            elif action == "verify": lines.append(f"    await expect({expr}).toBeVisible();")
        lines.append("  });")
    lines.extend(["});", ""])
    path.write_text("\n".join(lines), encoding="utf-8")
    return path.relative_to(root).as_posix()


def ground_testcases_for_generation(
    *,
    framework_path: str,
    feature: str,
    provider: str,
    model: str,
    base_url: str,
    browser_name: str = "chromium",
    browser_executable: str = "",
    headed: bool = True,
    allow_mutating_actions: bool | None = None,
    max_scenarios: int = 50,
    max_steps_per_scenario: int = 150,
    max_intermediate_actions: int = 8,
    manual_takeover_seconds: int = 120,
    action_timeout_seconds: int = 25,
) -> dict[str, Any]:
    """Run live browser grounding as the first phase of code generation.

    Failure or partial completion never prevents source generation. Verified
    steps and AI-discovered prerequisite actions are retained and merged into
    the generated Playwright design; unresolved steps fall back to framework
    reuse and provisional SmartLocator candidates.
    """
    check_cancelled()
    root = Path(framework_path).expanduser().resolve()
    profiles = get_feature_credential_profiles(feature)
    token = store_ephemeral_credentials(profiles=profiles, ttl_seconds=1800)
    mutation_allowed = _non_production_url(base_url) if allow_mutating_actions is None else bool(allow_mutating_actions)
    log_event(
        "browser_grounded_generation",
        "Starting AI browser grounding before Playwright source generation.",
        progress=8,
        feature=feature,
        details={"provider": provider, "credential_profile_count": len(profiles)},
    )
    try:
        mcp = mcp_status(headless=not headed, probe_server=False)
    except Exception as exc:
        mcp = {"mcp_probe_ok": False, "error": f"{type(exc).__name__}: {exc}"}
    try:
        report = run_functional_walkthrough(
            framework_path=str(root),
            feature=feature,
            provider=provider,
            model=model,
            base_url=base_url,
            credential_token=token,
            browser_name=browser_name,
            browser_executable=browser_executable,
            headed=headed,
            supervised=headed,
            allow_mutating_actions=mutation_allowed,
            allow_cross_origin=False,
            max_scenarios=max_scenarios,
            max_steps_per_scenario=max_steps_per_scenario,
            confidence_threshold=0.72,
            manual_takeover_seconds=manual_takeover_seconds,
            action_timeout_seconds=action_timeout_seconds,
            max_intermediate_actions=max_intermediate_actions,
            capture_screenshots=False,
            generation_mode=True,
            event_publisher=lambda agent, message, progress, status, payload: log_event(
                "browser_grounded_generation",
                message,
                status=status,
                progress=progress,
                feature=feature,
                details=payload or {},
            ),
        )
    except Exception as exc:
        report = {
            "ok": False,
            "ready_for_generation": False,
            "stage": "browser_grounding_exception",
            "message": f"Browser grounding was unavailable, so generation will continue with existing framework reuse and provisional locator candidates: {type(exc).__name__}: {exc}",
            "scenarios": [],
        }
    check_cancelled()
    enhanced = walkthrough_enhanced_testcase_path(feature)
    replay = ""
    if report.get("scenarios"):
        try:
            replay = _write_codegen_replay(feature, str(root), report)
        except Exception:
            replay = ""
    result = {
        "attempted": True,
        "ok": bool(report.get("ok")),
        "partial": not bool(report.get("ok")) and bool(report.get("scenarios")),
        "generation_may_continue": True,
        "provider": provider,
        "model": model,
        "credential_profile_count": len(profiles),
        "credentials_persisted": False,
        "mcp": mcp,
        "walkthrough": report,
        "enhanced_testcase_file": str(enhanced.relative_to(REPO_ROOT)) if enhanced.exists() else "",
        "walkthrough_report_file": str(walkthrough_report_path(feature).relative_to(REPO_ROOT)) if walkthrough_report_path(feature).exists() else "",
        "verified_replay_file": replay,
        "playwright_codegen_command": f"npx playwright codegen --target=playwright-test {json.dumps(base_url)}" if base_url else "npx playwright codegen --target=playwright-test",
        "message": (
            "Browser grounding completed and verified evidence will be used for page methods, locators and adaptive prerequisite actions."
            if report.get("ok")
            else "Browser grounding completed partially or was unavailable. Generation will continue and use every verified item that was collected."
        ),
    }
    log_event(
        "browser_grounded_generation",
        result["message"],
        status="done" if report.get("ok") else "warning",
        progress=42,
        feature=feature,
        details={"verified_locator_count": report.get("verified_locator_count", 0), "generation_may_continue": True},
    )
    return result


def _scenario_start_url(scenario: dict[str, Any]) -> str:
    for step in scenario.get("steps") or []:
        if str(step.get("action") or "").lower() == "goto":
            return str(step.get("value") or step.get("url") or "").strip().rstrip("/").lower()
    return ""


def _goal_key(step: dict[str, Any]) -> str:
    raw = " ".join(str(step.get(key) or "") for key in ("action", "target", "description"))
    words = [word for word in re.findall(r"[a-z0-9]+", raw.lower()) if word not in {"valid", "the", "a", "an", "enter", "fill", "click"}]
    if "password" in words or "passcode" in words:
        return "fill:password"
    if "username" in words or "user" in words and "name" in words:
        return "fill:username"
    return ":".join(words[:8])


def load_grounded_payload(feature: str, original: dict[str, Any]) -> dict[str, Any]:
    """Merge verified adaptive browser steps into the testcase payload.

    Original testcase steps remain the source of truth. AI-inserted prerequisite
    actions are included only when backed by a verified live locator. A verified
    authentication prerequisite discovered once is also propagated to scenarios
    that start on the same application and have the same parent goal, because
    every generated Playwright test opens its own isolated page/context.
    """
    path = walkthrough_enhanced_testcase_path(feature)
    if not path.exists():
        return original
    try:
        enhanced = read_json(path)
    except Exception:
        return original
    merged = json.loads(json.dumps(original, ensure_ascii=False, default=str))
    enhanced_by_id = {str(item.get("id") or ""): item for item in enhanced.get("scenarios") or []}
    original_by_id = {str(item.get("id") or ""): item for item in original.get("scenarios") or []}

    # Library of browser-proven prerequisites. The key is deliberately scoped
    # to the application URL and the parent business goal to avoid transplanting
    # a transition between unrelated applications or unrelated steps.
    prerequisite_library: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for sid, source in enhanced_by_id.items():
        original_scenario = original_by_id.get(sid) or {}
        original_steps = {str(item.get("step_number") or index): item for index, item in enumerate(original_scenario.get("steps") or [], 1)}
        start_url = _scenario_start_url(original_scenario)
        for item in source.get("steps") or []:
            walkthrough = item.get("walkthrough") or {}
            locator = walkthrough.get("locator") or {}
            if not (
                item.get("generated_by_walkthrough")
                and str(walkthrough.get("status") or "") == "adaptive_intermediate_verified"
                and locator.get("strategy")
                and locator.get("value")
            ):
                continue
            parent_number = str(item.get("parent_step_number") or "")
            parent = original_steps.get(parent_number) or {}
            key = (start_url, _goal_key(parent))
            if key[0] and key[1]:
                prerequisite_library.setdefault(key, []).append(item)

    for scenario in merged.get("scenarios") or []:
        sid = str(scenario.get("id") or "")
        source = enhanced_by_id.get(sid)
        start_url = _scenario_start_url(scenario)
        source_steps = list((source or {}).get("steps") or [])
        by_parent: dict[str, list[dict[str, Any]]] = {}
        direct_by_number: dict[str, dict[str, Any]] = {}
        direct_position = 0
        for item in source_steps:
            if item.get("generated_by_walkthrough"):
                walkthrough = item.get("walkthrough") or {}
                locator = walkthrough.get("locator") or {}
                if str(walkthrough.get("status") or "") == "adaptive_intermediate_verified" and locator.get("strategy") and locator.get("value"):
                    raw_number = str(item.get("step_number") or "")
                    inferred_parent = raw_number.split(".", 1)[0] if "." in raw_number else ""
                    parent_number = str(item.get("parent_step_number") or inferred_parent)
                    by_parent.setdefault(parent_number, []).append(item)
            else:
                direct_position += 1
                direct_by_number[str(item.get("step_number") or direct_position)] = item

        candidate_steps: list[dict[str, Any]] = []
        for index, original_step in enumerate(scenario.get("steps") or [], 1):
            number = str(original_step.get("step_number") or index)
            inserts = list(by_parent.get(number) or [])
            if not inserts:
                inserts = list(prerequisite_library.get((start_url, _goal_key(original_step))) or [])
            seen = set()
            for item in inserts:
                marker = json.dumps((item.get("walkthrough") or {}).get("locator") or {}, sort_keys=True, default=str)
                if marker not in seen:
                    candidate_steps.append(json.loads(json.dumps(item, default=str)))
                    seen.add(marker)
            candidate_steps.append(direct_by_number.get(number) or original_step)
        if candidate_steps:
            scenario["steps"] = candidate_steps
            scenario["browser_grounded"] = bool(source)
    return merged
