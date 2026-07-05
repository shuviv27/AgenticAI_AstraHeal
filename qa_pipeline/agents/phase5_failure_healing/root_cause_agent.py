from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Any

from qa_pipeline.agents.phase5_failure_healing.evidence_collector import collect_failure_evidence
from qa_pipeline.agents.phase5_failure_healing.healing_policy import load_healing_policy, policy_summary_for_prompt
from qa_pipeline.agents.phase5_failure_healing.enterprise_rca_taxonomy import classify_text
from qa_pipeline.core.paths import QA_CACHE_DIR, REPORTS_DIR, REPO_ROOT
from qa_pipeline.core.project_config import load_project_config
from qa_pipeline.core.url_guard import normalize_base_url
from qa_pipeline.core.runtime_logger import log_event
from qa_pipeline.llm.codex_cli import CodexCliProvider
from qa_pipeline.llm.ollama import OllamaProvider


@dataclass
class FailureSignal:
    kind: str
    confidence: float
    evidence: str
    recommendation: str
    auto_healable: bool


@dataclass
class RootCauseReport:
    ok: bool
    status: str
    feature: str
    base_url: str
    generated_at: str
    failed_tests: list[dict[str, Any]]
    evidence_summary: dict[str, Any]
    signals: list[dict[str, Any]]
    likely_root_cause: str
    confidence: float
    auto_healable: bool
    strict_rules: list[str]
    recommended_fix_plan: list[str]
    artifacts: dict[str, str]
    ai: dict[str, Any]


def _signals_from_evidence(evidence: dict[str, Any]) -> list[FailureSignal]:
    text = (evidence.get("failure_text") or "").lower()
    taxonomy = classify_text(evidence.get("failure_text") or "")
    signals: list[FailureSignal] = []
    if taxonomy.get("category") != "UNKNOWN":
        signals.append(FailureSignal(
            str(taxonomy.get("category")), float(taxonomy.get("confidence") or 0.5),
            "Enterprise taxonomy matched this failure category from evidence text.",
            str(taxonomy.get("healing") or "Use category-driven healing."),
            bool(taxonomy.get("auto_healable")),
        ))

    if evidence.get("url_leaks"):
        signals.append(FailureSignal(
            "wrong_application_url", 0.98,
            f"Found localhost/GUI URL leakage: {evidence.get('url_leaks')}",
            "Replace localhost/127.0.0.1 URLs with saved project BASE_URL in testcases/specs/pages and enforce URL guard before execution.", True
        ))

    if "strict mode violation" in text:
        signals.append(FailureSignal(
            "strict_locator_ambiguity", 0.90,
            "Playwright strict mode indicates locator matched multiple elements.",
            "Patch pageObjects with a more specific fallback/primary locator from live DOM, then rerun static review and headed execution.", True
        ))

    if any(x in text for x in ["not attached to the dom", "element is not attached", "element is detached", "locator.scrollintoviewifneeded"]):
        signals.append(FailureSignal(
            "locator_detached_from_dom", 0.93,
            "Playwright reported that the element/locator became detached from the DOM during scroll/action. This usually means the page re-rendered, the locator was captured too early, or the selector points to a transient duplicate node.",
            "Use Playwright MCP/codegen/live DOM evidence to regenerate a stable locator in the pageObject. Re-query the locator immediately before action, wait for DOM stability, handle re-render overlays, then retry through BasePage safe action helpers. Do not keep stale Locator/ElementHandle references.", True
        ))

    if any(x in text for x in ["getbyrole", "getbytext", "getbylabel", "locator", "tobevisible", "waiting for", "could not find visible text", "not visible", "should be visible"]):
        score = 0.90 if evidence.get("candidate_locators") else 0.82
        recommendation = "Use full-page DOM crawl candidates plus Playwright MCP/codegen evidence to strengthen pageObjects locator fallbacks. Keep spec clean and reuse page methods."
        if "navigation" in text or "current url" in text and any(x in text for x in ["marketplace", "find-a-store", "shop"]):
            recommendation = "Verify whether the generated step clicked the correct header/nav control. Use human-like header-scoped click and menu/page-option verification; do not replace the click with direct page.goto navigation."
        signals.append(FailureSignal(
            "locator_not_found_or_unstable", score,
            f"Locator/visibility failure detected. Missing target: {evidence.get('missing_target') or 'not extracted'}. DOM candidates: {len(evidence.get('candidate_locators') or [])}.",
            recommendation, True
        ))

    if any(x in text for x in ["intercepts pointer events", "element is outside of the viewport", "not visible", "not enabled", "click timeout", "element is detached", "not attached to the dom", "element is not attached"]):
        signals.append(FailureSignal(
            "clickability_scroll_or_overlay_issue", 0.88,
            "Failure suggests overlay, offscreen element, detached element, or clickability issue.",
            "Apply BasePage heal-aware click/verify helpers: dismiss overlays, full-page scroll, scrollIntoView, re-query locator after DOM re-render, stable retry, then click.", True
        ))

    if any(x in text for x in ["waitforurl", "tohaveurl", "navigation", "timeout", "networkidle"]):
        signals.append(FailureSignal(
            "navigation_or_sync_issue", 0.80,
            "Failure mentions navigation, URL expectation, waiting, or timeout.",
            "Use resilient navigation helpers, relative URL assertions, waitForPageReady, and same-tab/new-tab handling.", True
        ))

    if any(x in text for x in ["permission", "geolocation", "notification", "allow location", "browser context"]):
        signals.append(FailureSignal(
            "browser_permission_issue", 0.86,
            "Failure mentions browser permission, geolocation, or notification prompt.",
            "Grant permissions in Playwright context and use browser launch flags that suppress permission UI.", True
        ))

    if any(x in text for x in ["net::err", "err_timed_out", "econnrefused", "dns", "ssl"]):
        signals.append(FailureSignal(
            "environment_or_network_issue", 0.72,
            "Failure contains network/environment error.",
            "Do not patch tests first. Verify base URL, VPN/proxy, DNS, SSL and app availability. Then rerun.", False
        ))

    if not signals:
        signals.append(FailureSignal(
            "unknown_or_insufficient_artifacts", 0.35,
            "No deterministic failure pattern found. Execution artifacts may be missing or test may not have run.",
            "Run headed execution with trace/video/screenshots, then run RCA again.", False
        ))
    signals.sort(key=lambda s: s.confidence, reverse=True)
    return signals


def _ai_rca(provider: str, model: str, feature: str, base_url: str, evidence: dict[str, Any], signals: list[FailureSignal]) -> dict[str, Any]:
    if provider not in {"codex", "ollama"}:
        return {"used": False, "provider": provider, "message": "Deterministic RCA used. Select Codex or Ollama to add AI reasoning."}
    prompt = f"""
You are a senior Playwright RCA agent. Return JSON only with keys:
root_cause, confidence, auto_healable, exact_file_to_patch, patch_scope, validation_steps, risk.

Strict rules:
- Never suggest raw locators in generated spec files.
- Prefer patching pageObjects first, then reusable page methods/BasePage helpers.
- Use full-page DOM evidence and candidate locators before changing anything.
- If the error says "Element is not attached to the DOM" or locator.scrollIntoViewIfNeeded failed, treat it as stale/detached locator evidence: re-query the locator immediately before action, use Playwright MCP/codegen/live DOM to generate a stable selector, and patch the pageObject/page helper instead of the spec.
- If issue is environment/network/authentication, do not patch test code.
- For dynamic web apps consider overlays, scroll, viewport, permission popups, clickability, same/new tab navigation, and sync.

Enterprise healing policy:
{policy_summary_for_prompt()}

Feature: {feature}
Base URL: {base_url}
Deterministic signals: {json.dumps([asdict(s) for s in signals], ensure_ascii=False)}
Evidence JSON:
{json.dumps(evidence, indent=2, ensure_ascii=False)[-16000:]}
""".strip()
    try:
        if provider == "codex":
            result = CodexCliProvider(REPO_ROOT).run(prompt)
            return {"used": True, "provider": "codex", "ok": result.ok, "message": (result.stdout if result.ok else result.stderr)[-8000:]}
        result = OllamaProvider(model=model).chat(prompt)
        return {"used": True, "provider": "ollama", "ok": result.ok, "message": (result.text if result.ok else result.error)[-8000:]}
    except Exception as exc:
        return {"used": True, "provider": provider, "ok": False, "message": f"AI RCA failed safely: {type(exc).__name__}: {exc}"}




FAILED_TESTS_INVENTORY = REPORTS_DIR / "failed-tests.json"
RCA_ATTEMPT_HISTORY = QA_CACHE_DIR / "rca_self_healing_attempts.json"
MAX_RCA_ATTEMPTS_PER_FAILURE = 3


def _read_attempt_history() -> dict[str, Any]:
    if not RCA_ATTEMPT_HISTORY.exists():
        return {}
    try:
        return json.loads(RCA_ATTEMPT_HISTORY.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return {}


def _failure_fingerprint(spec: str, failed_tests: list[dict[str, Any]]) -> str:
    rows = _failure_tests_for_spec(failed_tests, spec, _feature_from_spec(spec)) if failed_tests else []
    raw = json.dumps({"spec": _normalise_spec_path(spec), "rows": rows}, ensure_ascii=False, sort_keys=True)[:4000]
    return hashlib.sha1(raw.encode("utf-8", errors="ignore")).hexdigest()[:16]


def _attempt_info(spec: str, failed_tests: list[dict[str, Any]]) -> dict[str, Any]:
    history = _read_attempt_history()
    fp = _failure_fingerprint(spec, failed_tests)
    record = history.get(fp) or {}
    attempts = int(record.get("attempts") or 0)
    return {
        "fingerprint": fp,
        "attempts": attempts,
        "max_attempts": MAX_RCA_ATTEMPTS_PER_FAILURE,
        "blocked": attempts >= MAX_RCA_ATTEMPTS_PER_FAILURE,
        "message": ("Maximum RCA/self-healing attempts reached for this same failure. Human intervention is required." if attempts >= MAX_RCA_ATTEMPTS_PER_FAILURE else "RCA/self-healing attempt budget available."),
        "history": record,
    }


def _read_failed_inventory() -> dict[str, Any]:
    if not FAILED_TESTS_INVENTORY.exists():
        return {"ok": False, "failed_specs": [], "failed_features": [], "failed_tests": [], "message": "No failed-tests.json inventory found."}
    try:
        data = json.loads(FAILED_TESTS_INVENTORY.read_text(encoding="utf-8", errors="replace"))
        data.setdefault("ok", True)
        data.setdefault("failed_specs", [])
        data.setdefault("failed_features", [])
        data.setdefault("failed_tests", [])
        return data
    except Exception as exc:
        return {"ok": False, "failed_specs": [], "failed_features": [], "failed_tests": [], "error": f"{type(exc).__name__}: {exc}"}


def _normalise_spec_path(value: str) -> str:
    value = str(value or "").replace("\\", "/").strip()
    if value.startswith("generated-playwright/"):
        value = value[len("generated-playwright/"):]
    return value


def _feature_from_spec(spec: str) -> str:
    name = _normalise_spec_path(spec).split("/")[-1]
    if name.endswith(".spec.ts"):
        name = name[:-8]
    return re.sub(r"[^A-Za-z0-9_-]+", "_", name).strip("_").lower() or "feature"


def _current_url_from_text(text: str) -> str:
    match = re.search(r"Current URL:\s*(\S+)", text or "", re.I)
    return match.group(1).strip().strip('\"`),;') if match else ""


def _failure_tests_for_spec(failed_tests: list[dict[str, Any]], spec: str, feature: str) -> list[dict[str, Any]]:
    norm = _normalise_spec_path(spec).lower()
    feat = feature.lower()
    rows: list[dict[str, Any]] = []
    for row in failed_tests or []:
        blob = json.dumps(row, ensure_ascii=False).lower()
        if norm and norm in blob:
            rows.append(row)
        elif feat and feat in blob:
            rows.append(row)
    return rows or (failed_tests[:1] if failed_tests else [])


def _human_fix_proposal(feature: str, spec: str, evidence: dict[str, Any], signals: list[FailureSignal]) -> dict[str, Any]:
    top = signals[0] if signals else FailureSignal("unknown", 0.0, "No signal", "Run headed with trace/video and analyze again.", False)
    failure_text = evidence.get("failure_text") or ""
    current_url = _current_url_from_text(failure_text)
    missing_target = evidence.get("missing_target") or ""
    patch_files = [
        f"generated-playwright/pageObjects/*Page.objects.ts for the real application page touched by {spec}",
        f"generated-playwright/pages/*Page.ts for reusable page method behavior",
        "generated-playwright/pages/BasePage.ts only for generic reusable browser/action handling",
    ]
    diagnosis_steps = [
        "Confirm the failed spec and test title from failed-tests.json / Playwright JSON.",
        "Open trace/screenshot/error-context to identify the exact failed action.",
        "Map spec -> page method -> pageObject locator before proposing any source change.",
    ]
    if top.kind == "environment_or_network_issue":
        patch_files = ["No code patch first. Verify VPN/proxy/base URL/test data and rerun."]
        diagnosis_steps += ["Check base URL/VPN/proxy/API availability before patching code."]
    elif top.kind == "browser_permission_issue":
        patch_files = ["generated-playwright/pages/BasePage.ts reusable permission helper", "Affected page method only if it currently treats permission text as visible text"]
        diagnosis_steps += ["Grant/suppress browser permission at context/config level, then verify blocker disappeared."]
    elif top.kind == "locator_detached_from_dom":
        patch_files = ["Affected real PageObjects file with stable locator regenerated from MCP/codegen/live DOM", "Affected Page method to re-query locator immediately before action", "BasePage safe action helper only if multiple workflows share the detached action"]
        diagnosis_steps += [
            "Check whether the locator is present in current DOM after the page settles.",
            "Use Playwright MCP/codegen or live DOM crawl to regenerate a stable selector for the current rendered node.",
            "Avoid stale ElementHandle/locator references; re-query immediately before scroll/click/expect.",
            "Add DOM-stability/overlay-dismiss guard in page method/BasePage, not raw waits in the spec.",
        ]
    elif top.kind in {"clickability_scroll_or_overlay_issue", "navigation_or_sync_issue"}:
        patch_files = ["Affected real Page class reusable method", "BasePage strong click / human navigation helper", "PageObjects only if locator is ambiguous"]
        diagnosis_steps += ["Check overlay/cookie/location/chat/modal blockers, viewport size, scroll position, and same-tab/new-tab navigation behavior."]
    elif top.kind == "locator_not_found_or_unstable":
        patch_files = ["Affected real PageObjects file first", "Affected real Page class method only if assertion/action is semantically wrong"]
        diagnosis_steps += ["Use MCP/codegen/live DOM candidates to update pageObject fallback locators before touching page methods."]
    return {
        "script": spec,
        "feature": feature,
        "likely_problem": top.kind,
        "confidence": top.confidence,
        "human_explanation": top.evidence,
        "current_url_seen": current_url,
        "failed_target_or_action": missing_target,
        "fix_proposal": top.recommendation,
        "diagnosis_steps": diagnosis_steps,
        "files_to_patch_in_order": patch_files,
        "guardrails": [
            "Do not add raw locators inside generated spec files.",
            "Do not rerun already-passed specs during RCA validation.",
            "Patch PageObjects/Page/BasePage only when evidence proves the change.",
            "For detached DOM locators, use MCP/codegen/live DOM evidence and re-query the locator before action instead of adding hard waits.",
            "After patch, rerun this failed spec only, then update the consolidated report.",
        ],
    }


def _render_failed_scripts_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Root Cause Analysis — Failed Scripts One-by-One",
        "",
        f"- Generated at: `{payload.get('generated_at')}`",
        f"- Base URL: `{payload.get('base_url')}`",
        f"- Failed scripts analyzed: **{payload.get('failed_script_count', 0)}**",
        "",
        "This report intentionally analyzes only failed scripts from the previous Playwright run. Already-passed scripts are preserved and are not part of RCA patch validation.",
        "",
    ]
    for idx, item in enumerate(payload.get("script_reports", []), 1):
        proposal = item.get("human_fix_proposal") or {}
        lines.extend([
            f"## {idx}. `{proposal.get('script') or item.get('spec')}`",
            "",
            f"- Feature: `{proposal.get('feature') or item.get('feature')}`",
            f"- Likely problem: **{proposal.get('likely_problem')}**",
            f"- Confidence: **{proposal.get('confidence')}**",
            f"- Current URL seen: `{proposal.get('current_url_seen') or 'not captured'}`",
            f"- Failed target/action: `{proposal.get('failed_target_or_action') or 'not extracted'}`",
            "",
            "### Human explanation",
            proposal.get("human_explanation") or "No explanation available.",
            "",
            "### Proposed fix",
            proposal.get("fix_proposal") or "No fix proposal available.",
            "",
            "### Diagnosis steps",
        ])
        for d in proposal.get("diagnosis_steps") or []:
            lines.append(f"- {d}")
        lines.extend([
            "",
            "### Patch files/order",
        ])
        for f in proposal.get("files_to_patch_in_order") or []:
            lines.append(f"- {f}")
        lines.extend(["", "### Guardrails"])
        for g in proposal.get("guardrails") or []:
            lines.append(f"- {g}")
        lines.extend(["", "### Signals"])
        for sig in item.get("signals", []):
            lines.append(f"- **{sig.get('kind')}** ({sig.get('confidence')}): {sig.get('recommendation')}")
        lines.append("")
    return "\n".join(lines) + "\n"


def analyze_failed_scripts_one_by_one(feature: str = "feature", provider: str = "deterministic", model: str = "llama3", base_url: str = "") -> dict[str, Any]:
    """Analyze failed scripts individually and produce a human-readable patch proposal.

    This is the RCA entry point used by the GUI. It reads the failed-test inventory
    from the latest execution, logs progress script-by-script, and writes both JSON
    and Markdown reports that a human can review before self-healing is applied.
    """
    base_url = normalize_base_url(base_url or load_project_config().get("base_url", ""))
    inventory = _read_failed_inventory()
    failed_specs = [_normalise_spec_path(s) for s in (inventory.get("failed_specs") or []) if _normalise_spec_path(s)]
    if not failed_specs:
        msg = "RCA blocked: no exact failed script inventory is available. The system will not analyze all scripts or guess failures. Re-run execution with Playwright JSON reporting enabled, then run RCA again."
        log_event("root_cause_analysis", msg, status="error", progress=100, details=inventory)
        payload = {
            "ok": False,
            "status": "blocked_no_failed_inventory",
            "mode": "failed_scripts_only_enforced",
            "feature": feature,
            "base_url": base_url,
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "failed_inventory": inventory,
            "failed_script_count": 0,
            "message": msg,
            "strict_rules": [
                "RCA must analyze failed scripts only.",
                "Already-passed scripts must not be part of RCA or self-healing validation.",
                "If the exact failed spec cannot be identified, block RCA and request a rerun with JSON reporting instead of assuming all scripts failed.",
            ],
            "artifacts": {
                "failed_inventory": "generated-playwright/reports/failed-tests.json"
            },
        }
        (REPORTS_DIR / "root-cause-failed-scripts-report.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        (REPORTS_DIR / "root-cause-report.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return payload

    script_reports: list[dict[str, Any]] = []
    total = len(failed_specs)
    log_event("root_cause_analysis", f"RCA started for {total} failed script(s). Already-passed scripts will not be analyzed or rerun.", progress=5, details={"failed_specs": failed_specs})
    for index, spec in enumerate(failed_specs, 1):
        script_feature = _feature_from_spec(spec)
        progress = int(10 + (index - 1) * 70 / max(total, 1))
        log_event("root_cause_analysis", f"Analyzing failed script {index}/{total}: {spec}", progress=progress, details={"spec": spec, "feature": script_feature})
        evidence = collect_failure_evidence(feature=script_feature, base_url=base_url)
        if inventory.get("failed_tests"):
            evidence["failed_tests_for_script"] = _failure_tests_for_spec(inventory.get("failed_tests") or [], spec, script_feature)
        signals = _signals_from_evidence(evidence)
        proposal = _human_fix_proposal(script_feature, spec, evidence, signals)
        attempt = _attempt_info(spec, inventory.get("failed_tests") or [])
        proposal["attempt_control"] = attempt
        if attempt.get("blocked"):
            signals = [FailureSignal("max_rca_attempts_reached", 1.0, attempt.get("message", "Max attempts reached"), "Stop automatic patching for this failure and ask the user for manual input, updated page source, credentials/test data, or permission to inspect live DOM.", False)] + signals
            proposal["fix_proposal"] = attempt.get("message")
            proposal["auto_patch_blocked"] = True
        log_event(
            "root_cause_analysis",
            f"Fix proposal for {spec}: {proposal.get('likely_problem')} -> {proposal.get('fix_proposal')}",
            status="warning" if signals and signals[0].auto_healable else "info",
            progress=min(progress + 5, 90),
            details=proposal,
        )
        script_reports.append({
            "spec": spec,
            "feature": script_feature,
            "evidence_summary": {
                "missing_target": evidence.get("missing_target"),
                "candidate_count": len(evidence.get("candidate_locators") or []),
                "current_url_seen": proposal.get("current_url_seen"),
                "failed_tests_for_script": evidence.get("failed_tests_for_script") or [],
            },
            "signals": [asdict(s) for s in signals],
            "human_fix_proposal": proposal,
            "auto_healable": bool(signals and signals[0].auto_healable and signals[0].confidence >= 0.75),
        })

    auto_healable_count = sum(1 for r in script_reports if r.get("auto_healable"))
    payload = {
        "ok": True,
        "status": "completed",
        "mode": "failed_scripts_one_by_one",
        "feature": feature,
        "base_url": base_url,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "failed_inventory": inventory,
        "failed_script_count": total,
        "auto_healable_count": auto_healable_count,
        "script_reports": script_reports,
        "strict_rules": [
            "Analyze failed scripts only; do not include already-passed scripts in RCA validation.",
            "Patch pageObjects/pages/utils only; never add raw locators to specs.",
            "Human-like browser actions must be used for navigation/menu/dropdown interactions; do not replace clicks with direct page.goto routes.",
            "After patch, rerun failed scripts only and update the consolidated report.",
        ],
        "artifacts": {
            "json": "generated-playwright/reports/root-cause-failed-scripts-report.json",
            "markdown": "generated-playwright/reports/root-cause-failed-scripts-report.md",
            "failed_inventory": "generated-playwright/reports/failed-tests.json",
        },
    }
    (REPORTS_DIR / "root-cause-failed-scripts-report.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (REPORTS_DIR / "root-cause-failed-scripts-report.md").write_text(_render_failed_scripts_markdown(payload), encoding="utf-8")
    # Keep the legacy report path populated so existing report tabs still work.
    (REPORTS_DIR / "root-cause-report.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (REPORTS_DIR / "root-cause-report.md").write_text(_render_failed_scripts_markdown(payload), encoding="utf-8")
    log_event("root_cause_analysis", f"RCA completed for {total} failed script(s). Human-readable proposals are ready.", status="done", progress=100, details={"report": payload["artifacts"]})
    return payload


def analyze_latest_failure(feature: str = "feature", provider: str = "deterministic", model: str = "llama3", base_url: str = "") -> dict[str, Any]:
    base_url = normalize_base_url(base_url or load_project_config().get("base_url", ""))
    evidence = collect_failure_evidence(feature=feature, base_url=base_url)
    policy = load_healing_policy()
    signals = _signals_from_evidence(evidence)
    top = signals[0]
    strict_rules = [
        "Never patch generated specs with raw locators.",
        "Patch pageObjects first; patch page methods/BasePage only for reusable behavior.",
        "Run dynamic crawl before locator repair.",
        "Apply only high-confidence single-purpose patches automatically.",
        "Back up every changed file before patching.",
        "Run static review and headed rerun after patching.",
        "Do not patch code for environment/network/auth/data-unavailable failures.",
        f"Honor policy gate version {policy.get('version')} with max {policy.get('maxHealingAttempts')} attempts and auto-apply threshold {policy.get('minAutoApplyConfidence')}.",
        "Do not add waitForTimeout, test.skip/fixme/only, force:true, or assertion weakening.",
    ]
    fix_plan = []
    if evidence.get("missing_target"):
        fix_plan.append(f"Investigate target from failure: {evidence['missing_target']}")
    if evidence.get("candidate_locators"):
        fix_plan.append("Use top DOM candidate from generated-playwright/reports/failure-evidence.json to strengthen locator fallback.")
    fix_plan.extend([s.recommendation for s in signals])
    ai = _ai_rca(provider, model, feature, base_url, evidence, signals)
    report = RootCauseReport(
        ok=True,
        status="completed",
        feature=feature,
        base_url=base_url,
        generated_at=datetime.now().isoformat(timespec="seconds"),
        failed_tests=evidence.get("failed_tests", [])[:25],
        evidence_summary={
            "missing_target": evidence.get("missing_target"),
            "candidate_count": len(evidence.get("candidate_locators") or []),
            "url_leaks": evidence.get("url_leaks") or [],
            "dom_elements": (evidence.get("raw") or {}).get("dom_elements", 0),
            "taxonomy": classify_text(evidence.get("failure_text") or ""),
            "policy_version": policy.get("version"),
        },
        signals=[asdict(s) for s in signals],
        likely_root_cause=top.kind,
        confidence=top.confidence,
        auto_healable=top.auto_healable and top.confidence >= 0.75,
        strict_rules=strict_rules,
        recommended_fix_plan=fix_plan,
        artifacts=evidence.get("artifacts", {}),
        ai=ai,
    )
    out = REPORTS_DIR / "root-cause-report.json"
    out.write_text(json.dumps(asdict(report), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    md = REPORTS_DIR / "root-cause-report.md"
    md.write_text(_render_markdown(asdict(report)), encoding="utf-8")
    return asdict(report)


def _render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Root Cause Analysis Report",
        "",
        f"- Feature: `{report.get('feature')}`",
        f"- Base URL: `{report.get('base_url')}`",
        f"- Likely root cause: **{report.get('likely_root_cause')}**",
        f"- Confidence: **{report.get('confidence')}**",
        f"- Auto-healable: **{report.get('auto_healable')}**",
        "",
        "## Evidence summary",
        "```json",
        json.dumps(report.get("evidence_summary", {}), indent=2, ensure_ascii=False),
        "```",
        "",
        "## Signals",
    ]
    for s in report.get("signals", []):
        lines.append(f"- **{s.get('kind')}** ({s.get('confidence')}): {s.get('evidence')} → {s.get('recommendation')}")
    lines.extend(["", "## Strict rules"])
    for r in report.get("strict_rules", []):
        lines.append(f"- {r}")
    lines.extend(["", "## Recommended fix plan"])
    for step in report.get("recommended_fix_plan", []):
        lines.append(f"- {step}")
    lines.extend(["", "## AI narrative", "", "```json", str(report.get("ai", {}))[-6000:], "```", ""])
    return "\n".join(lines)
