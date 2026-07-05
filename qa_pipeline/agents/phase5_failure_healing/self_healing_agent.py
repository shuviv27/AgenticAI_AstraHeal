from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from qa_pipeline.agents.phase3_reuse_aware_codegen.dynamic_crawler import crawl_dynamic_page
from qa_pipeline.agents.phase4_review_execution.reviewer import run_review
from qa_pipeline.agents.phase5_failure_healing.evidence_collector import collect_failure_evidence
from qa_pipeline.agents.phase5_failure_healing.root_cause_agent import analyze_failed_scripts_one_by_one
from qa_pipeline.agents.phase5_failure_healing.healing_policy import load_healing_policy, policy_summary_for_prompt
from qa_pipeline.core.paths import GENERATED_PLAYWRIGHT_DIR, QA_CACHE_DIR, REPORTS_DIR, REPO_ROOT, TESTCASES_DIR
from qa_pipeline.core.project_config import load_project_config
from qa_pipeline.core.url_guard import normalize_base_url
from qa_pipeline.core.runtime_logger import log_event
from qa_pipeline.llm.codex_cli import CodexCliProvider
from qa_pipeline.llm.ollama import OllamaProvider



def _log_failed_script_healing_proposals() -> dict[str, Any]:
    """Emit plain-English runtime logs for each failed script RCA proposal."""
    report_path = REPORTS_DIR / "root-cause-failed-scripts-report.json"
    if not report_path.exists():
        return {"ok": False, "message": "No per-script RCA proposal report found yet."}
    try:
        data = json.loads(report_path.read_text(encoding="utf-8", errors="replace"))
    except Exception as exc:
        return {"ok": False, "message": f"Could not read per-script RCA proposal: {type(exc).__name__}: {exc}"}
    script_reports = data.get("script_reports") or []
    total = len(script_reports)
    for idx, row in enumerate(script_reports, 1):
        proposal = row.get("human_fix_proposal") or {}
        log_event(
            "self_healing",
            f"Patch proposal {idx}/{total} for {proposal.get('script') or row.get('spec')}: {proposal.get('likely_problem')} -> {proposal.get('fix_proposal')}",
            status="warning" if row.get("auto_healable") else "info",
            progress=min(15 + int(idx * 35 / max(total, 1)), 60),
            details=proposal,
        )
    return {"ok": True, "proposal_count": total, "report": str(report_path.relative_to(REPO_ROOT))}


FAILED_TESTS_INVENTORY = REPORTS_DIR / "failed-tests.json"
RCA_ATTEMPT_HISTORY = QA_CACHE_DIR / "rca_self_healing_attempts.json"


def _read_failed_inventory() -> dict[str, Any]:
    if not FAILED_TESTS_INVENTORY.exists():
        return {"ok": False, "failed_specs": [], "failed_features": [], "failed_tests": [], "message": "No failed-tests.json inventory found."}
    try:
        data = json.loads(FAILED_TESTS_INVENTORY.read_text(encoding="utf-8", errors="replace"))
        data.setdefault("failed_specs", [])
        data.setdefault("failed_features", [])
        data.setdefault("failed_tests", [])
        data["ok"] = True
        return data
    except Exception as exc:
        return {"ok": False, "failed_specs": [], "failed_features": [], "failed_tests": [], "error": f"{type(exc).__name__}: {exc}"}


def _norm_rel(path_value: str) -> str:
    value = str(path_value or "").replace("\\", "/").strip()
    if value.startswith("generated-playwright/"):
        value = value[len("generated-playwright/"):]
    return value


def _spec_to_feature(spec: str) -> str:
    name = _norm_rel(spec).split("/")[-1]
    if name.endswith(".spec.ts"):
        name = name[:-8]
    return re.sub(r"[^A-Za-z0-9_-]+", "_", name).strip("_").lower() or "feature"


def _build_failed_scope(root_cause: dict[str, Any]) -> dict[str, Any]:
    inventory = root_cause.get("failed_inventory") or _read_failed_inventory()
    failed_specs = [_norm_rel(s) for s in (inventory.get("failed_specs") or []) if _norm_rel(s)]
    allowed: set[str] = set()
    spec_import_pages: dict[str, list[str]] = {}
    for spec in failed_specs:
        allowed.add(spec)
        spec_path = GENERATED_PLAYWRIGHT_DIR / spec
        pages: list[str] = []
        if spec_path.exists():
            text = _read(spec_path)
            for m in re.finditer(r"from ['\"]\.\./(?:\.\./)?pages/([^'\"]+)['\"]", text):
                rel = f"pages/{m.group(1)}"
                if not rel.endswith(".ts"):
                    rel += ".ts"
                pages.append(rel)
                allowed.add(rel)
            # Also catch direct strings like new HomePage or imports with aliases.
            for m in re.finditer(r"import\s+\{?\s*([A-Za-z0-9_]+Page)\s*\}?\s+from ['\"]([^'\"]*pages/[^'\"]+)['\"]", text):
                rel = f"pages/{Path(m.group(2)).name}"
                if not rel.endswith(".ts"):
                    rel += ".ts"
                pages.append(rel)
                allowed.add(rel)
        spec_import_pages[spec] = sorted(dict.fromkeys(pages))

    # Include pageObjects imported by failed pages.
    for rel in list(allowed):
        if not rel.startswith("pages/") or rel.endswith("BasePage.ts"):
            continue
        page_path = GENERATED_PLAYWRIGHT_DIR / rel
        if page_path.exists():
            page_text = _read(page_path)
            for m in re.finditer(r"from ['\"]\.\./pageObjects/([^'\"]+)['\"]", page_text):
                obj_rel = f"pageObjects/{m.group(1)}"
                if not obj_rel.endswith(".ts"):
                    obj_rel += ".ts"
                allowed.add(obj_rel)

    # Allow generic helpers only when RCA proposes auto-healable script-level patches.
    allowed.add("pages/BasePage.ts")
    allowed.add("utils/locatorFactory.ts")
    return {
        "ok": bool(failed_specs),
        "failed_specs": failed_specs,
        "failed_features": [_spec_to_feature(s) for s in failed_specs],
        "allowed_files": sorted(allowed),
        "spec_import_pages": spec_import_pages,
        "message": "Patch scope is restricted to files used by failed specs plus shared BasePage/locatorFactory helpers." if failed_specs else "No failed specs were available for scoped patching.",
    }


def _allowed(path: Path, allowed_files: set[str] | None) -> bool:
    if allowed_files is None:
        return True
    rel = _rel(path)
    return rel in allowed_files


def _read_attempt_history() -> dict[str, Any]:
    if not RCA_ATTEMPT_HISTORY.exists():
        return {}
    try:
        return json.loads(RCA_ATTEMPT_HISTORY.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return {}


def _record_healing_attempts(root_cause: dict[str, Any], applied: bool) -> dict[str, Any]:
    history = _read_attempt_history()
    updated: list[dict[str, Any]] = []
    for row in root_cause.get("script_reports") or []:
        proposal = row.get("human_fix_proposal") or {}
        attempt = proposal.get("attempt_control") or {}
        fp = attempt.get("fingerprint")
        if not fp:
            continue
        record = history.get(fp) or {"spec": row.get("spec"), "attempts": 0, "events": []}
        if applied:
            record["attempts"] = int(record.get("attempts") or 0) + 1
            record.setdefault("events", []).append({"event": "self_healing_patch_applied", "spec": row.get("spec"), "at": datetime.now().isoformat(timespec="seconds")})
        history[fp] = record
        updated.append({"fingerprint": fp, "spec": row.get("spec"), "attempts": record.get("attempts")})
    RCA_ATTEMPT_HISTORY.parent.mkdir(parents=True, exist_ok=True)
    RCA_ATTEMPT_HISTORY.write_text(json.dumps(history, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return {"ok": True, "updated": updated, "history_path": str(RCA_ATTEMPT_HISTORY.relative_to(REPO_ROOT))}

LOCALHOST_PAT = re.compile(r"https?://(?:127\.0\.0\.1|localhost)(?::\d+)?(?:/[\w\-./?=&%]*)?", re.I)


@dataclass
class PatchAction:
    action: str
    status: str
    file: str
    details: str


@dataclass
class HealingReport:
    ok: bool
    status: str
    feature: str
    base_url: str
    applied: bool
    generated_at: str
    root_cause: dict[str, Any]
    evidence: dict[str, Any]
    patches: list[dict[str, Any]]
    validation: dict[str, Any]
    ai: dict[str, Any]
    strict_rules: list[str]
    next_steps: list[str]


def _rel(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT)).replace("\\", "/")
    except Exception:
        return str(path).replace("\\", "/")


def _backup(path: Path) -> Path:
    backup_dir = REPORTS_DIR / "healing-backups" / datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_dir.mkdir(parents=True, exist_ok=True)
    dest = backup_dir / path.relative_to(REPO_ROOT)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, dest)
    return dest


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""


def _write(path: Path, text: str, apply_patch: bool) -> bool:
    if not apply_patch:
        return False
    _backup(path)
    path.write_text(text, encoding="utf-8")
    return True


def _replace_localhost_urls(base_url: str, apply_patch: bool, allowed_files: set[str] | None = None) -> list[PatchAction]:
    actions: list[PatchAction] = []
    if not base_url:
        return actions
    roots = [GENERATED_PLAYWRIGHT_DIR / "tests" / "generated", GENERATED_PLAYWRIGHT_DIR / "pages", GENERATED_PLAYWRIGHT_DIR / "pageObjects", TESTCASES_DIR]
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in {".ts", ".json"}:
                continue
            if not _allowed(path, allowed_files):
                continue
            text = _read(path)
            if not LOCALHOST_PAT.search(text):
                continue
            updated = LOCALHOST_PAT.sub(base_url, text)
            if updated != text:
                _write(path, updated, apply_patch)
                actions.append(PatchAction("url_guard", "applied" if apply_patch else "proposed", _rel(path), f"Replace localhost/127 URLs with {base_url}"))
    return actions


def _ensure_locator_factory_fallbacks(apply_patch: bool) -> PatchAction:
    path = GENERATED_PLAYWRIGHT_DIR / "utils" / "locatorFactory.ts"
    if not path.exists():
        return PatchAction("locator_factory_fallbacks", "skipped", _rel(path), "locatorFactory.ts not found")
    text = _read(path)
    if "fallbacks?: LocatorDefinition[]" in text and "resolveLocatorBase" in text and "relaxedRegex" in text:
        return PatchAction("locator_factory_fallbacks", "already_present", _rel(path), "Fallback locator union support is already present")
    updated = r"""import type { Locator, Page } from '@playwright/test';

export type LocatorDefinition =
  | { strategy: 'testId'; value: string; description?: string; fallbacks?: LocatorDefinition[] }
  | { strategy: 'role'; role: Parameters<Page['getByRole']>[0]; value: string; description?: string; fallbacks?: LocatorDefinition[] }
  | { strategy: 'label'; value: string; description?: string; fallbacks?: LocatorDefinition[] }
  | { strategy: 'text'; value: string; description?: string; fallbacks?: LocatorDefinition[] }
  | { strategy: 'css'; value: string; description?: string; fallbacks?: LocatorDefinition[] }
  | { strategy: 'xpath'; value: string; description?: string; fallbacks?: LocatorDefinition[] };

export function resolveLocator(page: Page, locator: LocatorDefinition): Locator {
  let resolved = resolveLocatorBase(page, locator);
  for (const fallback of locator.fallbacks ?? []) {
    resolved = resolved.or(resolveLocatorBase(page, fallback));
  }
  return resolved.first();
}

function resolveLocatorBase(page: Page, locator: LocatorDefinition): Locator {
  switch (locator.strategy) {
    case 'testId': return page.getByTestId(locator.value);
    case 'role': return page.getByRole(locator.role, { name: relaxedRegex(locator.value) });
    case 'label': return page.getByLabel(relaxedRegex(locator.value));
    case 'text': return page.getByText(relaxedRegex(locator.value));
    case 'css': return page.locator(locator.value);
    case 'xpath': return page.locator(`xpath=${locator.value}`);
    default: throw new Error(`Unsupported locator strategy: ${(locator as LocatorDefinition).strategy}`);
  }
}

function relaxedRegex(value: string): RegExp {
  const clean = String(value || '').replace(/[\u2010-\u2015]/g, '-').replace(/\s+/g, ' ').trim();
  const escaped = escapeRegExp(clean).replace(/\\ /g, '\\s+');
  return new RegExp(escaped, 'i');
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}
"""
    _write(path, updated, apply_patch)
    return PatchAction("locator_factory_fallbacks", "applied" if apply_patch else "proposed", _rel(path), "Add safe fallback locator support without changing specs")


def _ensure_base_page_resilience(apply_patch: bool) -> list[PatchAction]:
    path = GENERATED_PLAYWRIGHT_DIR / "pages" / "BasePage.ts"
    if not path.exists():
        return [PatchAction("base_page_resilience", "skipped", _rel(path), "BasePage.ts not found")]
    text = _read(path)
    updated = text
    additions = """
  async waitForStableDom(): Promise<void> {
    // Never use networkidle for production marketing/SPA pages.
    // Analytics, telemetry, fonts, and service workers may keep network active.
    await this.page.waitForLoadState('domcontentloaded', { timeout: 30000 }).catch(() => undefined);
    await this.page.locator('body').waitFor({ state: 'visible', timeout: 15000 }).catch(() => undefined);
    await this.page.evaluate(async () => {
      await new Promise<void>((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve())));
    }).catch(() => undefined);
  }

  async healAwareClick(locator: Locator, description = 'target element'): Promise<void> {
    await this.dismissCommonOverlays();
    await this.autoScrollFullPage().catch(() => undefined);
    await locator.first().scrollIntoViewIfNeeded().catch(() => undefined);
    await this.waitForStableDom().catch(() => undefined);
    if (!(await locator.first().isVisible({ timeout: 7000 }).catch(() => false))) {
      throw new Error(`Self-healing hint: ${description} was not visible after overlay handling and full-page scroll.`);
    }
    await this.safeClick(locator.first());
  }

  async healAwareVerifyVisible(locator: Locator, description = 'target element'): Promise<void> {
    await this.dismissCommonOverlays();
    await this.autoScrollFullPage().catch(() => undefined);
    await locator.first().scrollIntoViewIfNeeded().catch(() => undefined);
    await this.waitForStableDom().catch(() => undefined);
    await expect(locator.first(), `${description} should be visible after overlay handling and full-page scroll`).toBeVisible({ timeout: 15000 });
  }

  async smartFindByTextOrHref(target: string): Promise<Locator> {
    const text = String(target || '').trim();
    await this.dismissCommonOverlays();
    await this.autoScrollFullPage().catch(() => undefined);
    const escaped = escapeRegExp(text).replace(/\\ /g, '\\s+');
    const byRoleLink = this.page.getByRole('link', { name: new RegExp(escaped, 'i') });
    if (await byRoleLink.first().isVisible({ timeout: 1200 }).catch(() => false)) return byRoleLink.first();
    const byRoleButton = this.page.getByRole('button', { name: new RegExp(escaped, 'i') });
    if (await byRoleButton.first().isVisible({ timeout: 1200 }).catch(() => false)) return byRoleButton.first();
    const byText = this.page.getByText(new RegExp(escaped, 'i'));
    if (await byText.first().isVisible({ timeout: 1200 }).catch(() => false)) return byText.first();
    const hrefKey = text.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
    if (hrefKey) {
      const byHref = this.page.locator(`a[href*="${hrefKey}"]`);
      if (await byHref.first().isVisible({ timeout: 1200 }).catch(() => false)) return byHref.first();
    }
    throw new Error(`Self-healing hint: unable to find target by text/href: ${target}`);
  }

  async smartClickByTextOrHref(target: string, expectedUrlPart = ''): Promise<void> {
    const locator = await this.smartFindByTextOrHref(target);
    if (expectedUrlPart) await this.clickAndVerifyMaybeNewTab(locator, expectedUrlPart);
    else await this.healAwareClick(locator, target);
  }

"""
    if "async smartFindByTextOrHref" not in updated:
        insert_before = "  async verifyResponsiveLayoutSmoke(): Promise<void> {"
        if insert_before in updated:
            updated = updated.replace(insert_before, additions + insert_before)
        else:
            updated = updated.replace("}\n\nfunction escapeRegExp", additions + "}\n\nfunction escapeRegExp")
    if updated != text:
        _write(path, updated, apply_patch)
        return [PatchAction("base_page_resilience", "applied" if apply_patch else "proposed", _rel(path), "Add smart DOM stabilization, scroll, overlay, and text/href discovery helpers")]
    return [PatchAction("base_page_resilience", "already_present", _rel(path), "BasePage already has advanced resilience helpers")]


def _candidate_to_fallback(candidate: dict[str, Any]) -> str:
    attrs = candidate.get("attrs") or {}
    tag = str(candidate.get("tag") or "").lower()
    text = str(candidate.get("text") or "").strip().replace("'", "\\'")[:120]
    if attrs.get("data-testid"):
        return "{ strategy: 'testId', value: '" + str(attrs["data-testid"]).replace("'", "\\'") + "' }"
    if tag in {"a", "button"} and text:
        role = "link" if tag == "a" else "button"
        return "{ strategy: 'role', role: '" + role + "', value: '" + text + "' }"
    if attrs.get("aria-label"):
        role = "link" if tag == "a" else "button" if tag == "button" else "link"
        val = str(attrs["aria-label"]).replace("'", "\\'")[:120]
        return "{ strategy: 'role', role: '" + role + "', value: '" + val + "' }"
    if attrs.get("href"):
        href = str(attrs["href"]).replace("'", "\\'")
        key = href.strip('/').split('/')[-1] or href
        key = key[:80]
        return "{ strategy: 'css', value: 'a[href*=\"" + key.replace('"', '\\"') + "\"]' }"
    if text:
        return "{ strategy: 'text', value: '" + text + "' }"
    return ""


def _strengthen_pageobjects_with_dom_candidate(evidence: dict[str, Any], apply_patch: bool, allowed_files: set[str] | None = None) -> list[PatchAction]:
    actions: list[PatchAction] = []
    target = evidence.get("missing_target") or ""
    candidates = evidence.get("candidate_locators") or []
    if not target or not candidates:
        return [PatchAction("dom_locator_patch", "skipped", "generated-playwright/pageObjects", "No missing target with DOM candidate found")]
    best = candidates[0]
    fallback = _candidate_to_fallback(best)
    if not fallback:
        return [PatchAction("dom_locator_patch", "skipped", "generated-playwright/pageObjects", "DOM candidate could not be converted to a safe fallback")]
    target_words = [w for w in re.findall(r"[A-Za-z0-9]+", target.lower()) if len(w) > 2]
    patched = False
    for path in (GENERATED_PLAYWRIGHT_DIR / "pageObjects").glob("*Page.objects.ts"):
        if not _allowed(path, allowed_files):
            continue
        text = _read(path)
        updated = text
        # Find object entries with value/description overlapping the failed target. Add fallbacks only when not present.
        def repl(match: re.Match) -> str:
            nonlocal patched
            entry = match.group(0)
            low = entry.lower()
            if "fallbacks" in low:
                return entry
            if not any(w in low for w in target_words):
                return entry
            patched = True
            return entry[:-2] + f", fallbacks: [{fallback}] }}"
        updated = re.sub(r"\{\s*strategy:\s*'[^']+'[^\n]+?\s*\}", repl, updated)
        if updated != text:
            _write(path, updated, apply_patch)
            actions.append(PatchAction("dom_locator_patch", "applied" if apply_patch else "proposed", _rel(path), f"Add fallback from live DOM for target '{target}': {fallback}"))
    if not patched:
        detail = f"Top candidate for '{target}' is {json.dumps(best, ensure_ascii=False)[:700]}. No matching existing pageObject key found, so proposal only."
        actions.append(PatchAction("dom_locator_patch", "proposal_only", "generated-playwright/reports/failure-evidence.json", detail))
    return actions


def _upgrade_page_methods_to_heal_aware(apply_patch: bool, allowed_files: set[str] | None = None) -> list[PatchAction]:
    actions: list[PatchAction] = []
    pages_dir = GENERATED_PLAYWRIGHT_DIR / "pages"
    if not pages_dir.exists():
        return actions
    for path in pages_dir.glob("*Page.ts"):
        if path.name == "BasePage.ts":
            continue
        if not _allowed(path, allowed_files):
            continue
        text = _read(path)
        updated = re.sub(
            r"await expect\(this\.getLocator\(([^)]+)\)\)\.toBeVisible\(\);",
            r"await this.healAwareVerifyVisible(this.getLocator(\1), '\1');",
            text,
        )
        updated = re.sub(
            r"await this\.safeClick\(this\.getLocator\(([^)]+)\)\);",
            r"await this.healAwareClick(this.getLocator(\1), '\1');",
            updated,
        )
        if updated != text:
            _write(path, updated, apply_patch)
            actions.append(PatchAction("heal_aware_page_methods", "applied" if apply_patch else "proposed", _rel(path), "Replace brittle visible/click calls with heal-aware reusable BasePage helpers"))
    if not actions:
        actions.append(PatchAction("heal_aware_page_methods", "already_present", "generated-playwright/pages", "No brittle page method calls found or already upgraded"))
    return actions


def _ai_patch_guidance(provider: str, model: str, root_cause: dict[str, Any], evidence: dict[str, Any], apply_patch: bool) -> dict[str, Any]:
    if provider not in {"codex", "ollama"}:
        return {"used": False, "provider": provider, "message": "Deterministic self-healing rules were used. Select Codex/Ollama for AI patch guidance."}
    prompt = f"""
You are a strict Playwright self-healing patch reviewer. Return JSON only with keys:
safe_to_patch, confidence, files_allowed, files_blocked, validation_steps, notes.

Strict rules:
- Never add raw locators to generated spec files.
- Prefer pageObjects fallback locator patch first.
- If Playwright reports "Element is not attached to the DOM" or locator.scrollIntoViewIfNeeded failed, regenerate a stable selector using MCP/codegen/live DOM evidence, re-query the locator immediately before action, and patch pageObject/page helper instead of adding waits to specs.
- Use BasePage reusable helpers for scroll, overlays, clickability, permissions and sync.
- Do not patch code for network/env/auth/data issues.
- Patch must be small, reversible, backed up, and validated by static review plus headed rerun.

Enterprise healing policy:
{policy_summary_for_prompt()}

Apply patch requested: {apply_patch}
Root cause:
{json.dumps(root_cause, indent=2, ensure_ascii=False)[-10000:]}
Evidence:
{json.dumps(evidence, indent=2, ensure_ascii=False)[-12000:]}
""".strip()
    try:
        if provider == "codex":
            result = CodexCliProvider(REPO_ROOT).run(prompt)
            return {"used": True, "provider": "codex", "ok": result.ok, "message": (result.stdout if result.ok else result.stderr)[-8000:]}
        result = OllamaProvider(model=model).chat(prompt)
        return {"used": True, "provider": "ollama", "ok": result.ok, "message": (result.text if result.ok else result.error)[-8000:]}
    except Exception as exc:
        return {"used": True, "provider": provider, "ok": False, "message": f"AI patch guidance failed safely: {type(exc).__name__}: {exc}"}


def run_self_healing(feature: str = "feature", provider: str = "deterministic", model: str = "llama3", base_url: str = "", apply_patch: bool = False) -> dict[str, Any]:
    base_url = normalize_base_url(base_url or load_project_config().get("base_url", ""))
    policy = load_healing_policy()

    # Strict enhancement: self-healing must be driven by the failed-script inventory,
    # never by the active batch/all scripts. This prevents passed tests from being
    # patched, reanalyzed, or rerun accidentally.
    root_cause = analyze_failed_scripts_one_by_one(feature=feature, provider=provider, model=model, base_url=base_url)
    failed_scope = _build_failed_scope(root_cause)

    strict_rules = [
        "RCA/self-healing is failed-script scoped only; already-passed scripts are not analyzed, patched, or rerun.",
        "Patch only files imported/used by failed specs plus shared BasePage/locatorFactory helpers when the failure requires generic click/locator resilience.",
        "Never add raw locators to generated spec files.",
        "If the same failed resource reaches the maximum RCA/self-healing attempts, stop and ask for user intervention.",
        "If locator is missing or detached from DOM, crawl/inspect the page with Playwright MCP/codegen/live DOM evidence and update pageObjects fallback locators.",
        "If locator is visible but not interactable, use reusable safe click strategy: overlay dismiss, scroll into view, re-query after re-render, coordinate fallback, or JS click only inside BasePage/page method guardrails.",
        f"Honor self-healing policy {policy.get('version')}: max attempts {policy.get('maxHealingAttempts')}, auto-apply confidence {policy.get('minAutoApplyConfidence')}.",
        "Blocked anti-patterns include waitForTimeout, explicit/default waits above 30000ms, broad force:true, raw spec locators, assertion weakening, and passed-script edits.",
    ]

    if not root_cause.get("ok") or not failed_scope.get("ok"):
        msg = root_cause.get("message") or failed_scope.get("message") or "Self-healing blocked because no exact failed script scope was available."
        log_event("self_healing", msg, status="error", progress=100, details={"root_cause": root_cause, "failed_scope": failed_scope})
        out_report = HealingReport(
            ok=False,
            status="blocked_no_failed_scope",
            feature=feature,
            base_url=base_url,
            applied=False,
            generated_at=datetime.now().isoformat(timespec="seconds"),
            root_cause=root_cause,
            evidence={"failed_scope": failed_scope},
            patches=[],
            validation={"ok": False, "message": "Review blocked RCA report and rerun execution with JSON reporting if needed."},
            ai={"used": False, "message": msg},
            strict_rules=strict_rules,
            next_steps=[msg, "Run a headed execution once more to generate exact failed-tests.json, then run RCA again."],
        )
        (REPORTS_DIR / "self-healing-report.json").write_text(json.dumps(asdict(out_report), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        (REPORTS_DIR / "self-healing-report.md").write_text(_render_markdown(asdict(out_report)), encoding="utf-8")
        return asdict(out_report)

    blocked_attempts = []
    for row in root_cause.get("script_reports") or []:
        proposal = row.get("human_fix_proposal") or {}
        attempt = proposal.get("attempt_control") or {}
        if attempt.get("blocked"):
            blocked_attempts.append({"spec": row.get("spec"), "attempt": attempt})
    if blocked_attempts and apply_patch:
        msg = "Self-healing blocked: maximum RCA/self-healing attempts reached for one or more failed scripts. Human intervention is required."
        log_event("self_healing", msg, status="error", progress=100, details={"blocked_attempts": blocked_attempts})
        out_report = HealingReport(
            ok=False,
            status="blocked_max_attempts_reached",
            feature=feature,
            base_url=base_url,
            applied=False,
            generated_at=datetime.now().isoformat(timespec="seconds"),
            root_cause=root_cause,
            evidence={"failed_scope": failed_scope, "blocked_attempts": blocked_attempts},
            patches=[asdict(PatchAction("attempt_guard", "blocked", str(b.get("spec")), "Maximum RCA/self-healing attempts reached; ask user for updated data/page source/manual review.")) for b in blocked_attempts],
            validation={"ok": False, "message": msg},
            ai={"used": False, "message": msg},
            strict_rules=strict_rules,
            next_steps=[
                "Review the failed script and native Playwright trace manually.",
                "Provide updated page source/screenshot/test data or allow App Intelligence crawl.",
                "After manual input, clear/retry RCA attempt history if appropriate.",
            ],
        )
        (REPORTS_DIR / "self-healing-report.json").write_text(json.dumps(asdict(out_report), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        (REPORTS_DIR / "self-healing-report.md").write_text(_render_markdown(asdict(out_report)), encoding="utf-8")
        return asdict(out_report)

    allowed_files = set(failed_scope.get("allowed_files") or [])
    per_script_proposals = _log_failed_script_healing_proposals()
    crawl = {"ok": False, "message": "Skipped: no base_url"}
    if base_url:
        try:
            # Crawl once to refresh locator candidates. The patch still remains failed-file scoped.
            crawl = crawl_dynamic_page(base_url=base_url, feature=(failed_scope.get("failed_features") or [feature])[0], headed=False)
        except Exception as exc:
            crawl = {"ok": False, "message": f"Dynamic crawl failed safely: {type(exc).__name__}: {exc}"}

    patches: list[PatchAction] = []
    top_kind = ""
    script_reports = root_cause.get("script_reports") or []
    if script_reports and script_reports[0].get("signals"):
        top_kind = str(script_reports[0]["signals"][0].get("kind") or "")
    if top_kind == "environment_or_network_issue" and apply_patch:
        patches.append(PatchAction("safe_block", "blocked", "N/A", "Environment/network issue detected; code patch intentionally blocked."))
    else:
        # Collect evidence per failed feature and patch only scoped files.
        for failed_feature in failed_scope.get("failed_features") or [feature]:
            evidence = collect_failure_evidence(feature=failed_feature, base_url=base_url)
            patches.extend(_replace_localhost_urls(base_url, apply_patch=apply_patch, allowed_files=allowed_files))
            patches.append(_ensure_locator_factory_fallbacks(apply_patch=apply_patch))
            patches.extend(_ensure_base_page_resilience(apply_patch=apply_patch))
            patches.extend(_strengthen_pageobjects_with_dom_candidate(evidence, apply_patch=apply_patch, allowed_files=allowed_files))
            patches.extend(_upgrade_page_methods_to_heal_aware(apply_patch=apply_patch, allowed_files=allowed_files))
            break

    ai = _ai_patch_guidance(provider, model, root_cause, {"failed_scope": failed_scope, "crawl": crawl}, apply_patch)
    validation = run_review(skip_npm=True)
    attempts = _record_healing_attempts(root_cause, applied=bool(apply_patch and not any(p.status == "blocked" for p in patches)))
    status = "patch_applied" if apply_patch else "proposal_created"
    if any(p.status == "blocked" for p in patches):
        status = "blocked_by_guardrail"
    out_report = HealingReport(
        ok=True,
        status=status,
        feature=feature,
        base_url=base_url,
        applied=apply_patch and status != "blocked_by_guardrail",
        generated_at=datetime.now().isoformat(timespec="seconds"),
        root_cause=root_cause,
        evidence={
            "failed_scope": failed_scope,
            "crawl": crawl,
            "per_script_proposals": per_script_proposals,
            "attempt_history_update": attempts,
            "note": "Patch proposal/application was restricted to failed scripts and their imported Page Objects/Page classes.",
        },
        patches=[asdict(p) for p in patches],
        validation=validation,
        ai=ai,
        strict_rules=strict_rules,
        next_steps=[
            "Review root-cause-failed-scripts-report.md and self-healing-report.md.",
            "Run RCA & Self-Healing -> Re-run Failed Only; do not run full regression unless explicitly required.",
            "Open failed-only consolidated report to see original failed -> passed after patch status while preserving originally passed scripts.",
            "If the same script fails repeatedly beyond the attempt limit, provide updated page source/screenshot or inspect manually.",
        ],
    )
    out = REPORTS_DIR / "self-healing-report.json"
    out.write_text(json.dumps(asdict(out_report), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    md = REPORTS_DIR / "self-healing-report.md"
    md.write_text(_render_markdown(asdict(out_report)), encoding="utf-8")
    return asdict(out_report)


def propose_healing_action(failure: dict) -> dict:
    return {"status": "proposal_only", "auto_apply": False, "failure": failure, "message": "Use run_self_healing(..., apply_patch=False) for a guarded patch plan, then apply only after review."}


def _render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Self-Healing Report",
        "",
        f"- Feature: `{report.get('feature')}`",
        f"- Base URL: `{report.get('base_url')}`",
        f"- Status: **{report.get('status')}**",
        f"- Applied: **{report.get('applied')}**",
        "",
        "## Evidence",
        "```json",
        json.dumps(report.get("evidence", {}), indent=2, ensure_ascii=False)[:6000],
        "```",
        "",
        "## Patch actions",
    ]
    for p in report.get("patches", []):
        lines.append(f"- **{p.get('action')}** / {p.get('status')} / `{p.get('file')}`: {p.get('details')}")
    lines.extend(["", "## Strict rules"])
    for r in report.get("strict_rules", []):
        lines.append(f"- {r}")
    lines.extend(["", "## Next steps"])
    for n in report.get("next_steps", []):
        lines.append(f"- {n}")
    return "\n".join(lines) + "\n"
