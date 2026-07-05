from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from qa_pipeline.core.paths import QA_CACHE_DIR, REPORTS_DIR, REPO_ROOT, GENERATED_PLAYWRIGHT_DIR
from qa_pipeline.core.commands import resolve_command, run_command
from qa_pipeline.core.url_guard import normalize_base_url


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _latest_page_source(feature: str) -> str:
    candidates = [
        QA_CACHE_DIR / "page_sources" / f"{feature}.html",
        QA_CACHE_DIR / "page_sources" / f"{feature}.txt",
        REPO_ROOT / "samples" / "page_sources" / f"{feature}_home_source.txt",
        REPO_ROOT / "samples" / "page_sources" / f"{feature}.txt",
    ]
    for p in candidates:
        if p.exists():
            return p.read_text(encoding="utf-8", errors="ignore")[:400000]
    return ""


def _classify_app(text: str, dom: dict[str, Any]) -> dict[str, Any]:
    lower = text.lower()
    elements = dom.get("elements", []) if isinstance(dom.get("elements"), list) else []
    attrs_blob = " ".join(" ".join((e.get("attrs") or {}).values()) for e in elements if isinstance(e, dict)).lower()
    findings = {
        "framework_hints": [],
        "automation_risks": [],
        "recommended_inputs": [],
        "locator_strategy": [],
        "healing_strategy": [],
    }
    if "chakra" in lower or "chakra" in attrs_blob:
        findings["framework_hints"].append("Chakra UI / generated CSS classes suspected")
    if "react" in lower or "__next" in lower or "data-react" in lower:
        findings["framework_hints"].append("React/SPA style application")
    if "shadowroot" in lower or any("shadow" in str(e).lower() for e in elements):
        findings["automation_risks"].append("Shadow DOM components detected or suspected")
    if "iframe" in lower or any((e.get("tag") == "iframe") for e in elements if isinstance(e, dict)):
        findings["automation_risks"].append("iFrames detected; generated scripts may need frameLocator")
    if any(x in lower for x in ["recaptcha", "captcha", "cloudflare", "akamai", "datadog", "one trust", "onetrust"]):
        findings["automation_risks"].append("Browser security/analytics/cookie/security layer detected")
    if any(x in lower for x in ["modal", "toast", "dialog", "popover", "drawer", "overlay"]):
        findings["automation_risks"].append("Dynamic overlays/popups may appear")
    findings["recommended_inputs"] = [
        "Application URL and environment name",
        "Login/auth details or saved storageState file when authentication exists",
        "OuterHTML or saved page source for important pages/components",
        "Known popups/permission prompts/cookie banners and expected handling",
        "Shadow DOM/iframe/component library details when known",
        "Stable test IDs or accessibility labels if app team can add them",
        "SRS/Jira Epic/Testcase file with expected business outcomes",
    ]
    findings["context_questions"] = [
        "Does the app require login or SSO? If yes, provide test credentials or storageState.",
        "Are there iframes, shadow DOM widgets, web components, or embedded third-party controls?",
        "Which popups may appear: cookies, location, notifications, feedback, surveys, MFA, captcha?",
        "Which pages should be crawled beyond the landing URL? Provide sitemap/menu journey if known.",
        "Which stable attributes exist: data-testid, data-test, data-qa, aria-label, accessible role/name?",
        "Which flows are business-critical and should be smoke/regression/API/accessibility?",
    ]
    findings["locator_strategy"] = [
        "Prefer getByRole/getByLabel/getByTestId with exact accessible names",
        "Use aria-label/href fallback for link-like visual buttons",
        "Avoid generated CSS classes unless no stable alternative exists",
        "Use frameLocator for iframes and evaluated shadow DOM map for shadow roots",
        "Check visible viewport first; scroll only when the target is not found",
    ]
    findings["healing_strategy"] = [
        "During generation: validate target text against page-source and DOM crawl evidence",
        "During execution: collect trace/screenshot/video/error-context before patching",
        "Patch only pageObjects/pages/utils, never raw locators in spec.ts",
        "Compile, review, and targeted rerun before accepting a healing patch",
        "Store repeated failure signatures in the self-learning matrix",
    ]
    return findings


def profile_application(feature: str, base_url: str = "", use_mcp: bool = True) -> dict[str, Any]:
    feature = re.sub(r"[^a-zA-Z0-9_-]+", "_", feature or "feature").strip("_").lower() or "feature"
    base_url = normalize_base_url(base_url)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    dom_path = REPORTS_DIR / "dynamic-dom-map.json"
    dom = _read_json(dom_path) if dom_path.exists() else {}
    page_source = _latest_page_source(feature)
    if base_url and resolve_command("npm") and not dom:
        script = GENERATED_PLAYWRIGHT_DIR / "scripts" / "crawlDynamicPage.ts"
        if script.exists():
            run_command(["npm", "--prefix", str(GENERATED_PLAYWRIGHT_DIR), "run", "crawl:dynamic", "--", "--url", base_url, "--feature", feature], cwd=REPO_ROOT, timeout=240, extra_env={"BASE_URL": base_url})
            dom = _read_json(dom_path) if dom_path.exists() else {}
    findings = _classify_app(page_source, dom)
    profile = {
        "ok": True,
        "feature": feature,
        "base_url": base_url,
        "generated_at": __import__('datetime').datetime.utcnow().isoformat() + "Z",
        "dom_summary": dom.get("summary", {}),
        "dom_url": dom.get("url"),
        "dom_title": dom.get("title"),
        "page_source_available": bool(page_source),
        "mcp_enabled": bool(use_mcp),
        "findings": findings,
        "context_awareness_model": {
            "goal": "Build an app-specific context pack before testcase and Playwright generation.",
            "inputs_used": ["URL", "live DOM crawl", "page source/outerHTML", "Jira/SRS/PDF/testcase source", "failure history", "MCP browser snapshot"],
            "when_to_ask_user": "Ask for credentials, outerHTML, screenshots, known popups, iframe/shadow DOM details, and business flow data when confidence is low.",
            "ai_browser_note": "The system uses Playwright/MCP-style browser inspection and deterministic crawling as the controlled alternative to a general AI browser. LLMs assist, but guardrails decide what code is written.",
        },
        "generation_contract": {
            "spec_rule": "spec.ts calls page methods only",
            "page_rule": "page methods call pageObjects/BasePage helpers",
            "object_rule": "locators live in pageObjects only",
            "self_heal_rule": "patch pageObjects/pages/utils only, validate with tsc/review/rerun",
            "scroll_rule": "do not scroll by default; scroll only after visible viewport/action-target search fails",
        },
    }
    out = REPORTS_DIR / "app-intelligence-profile.json"
    out.write_text(json.dumps(profile, indent=2, ensure_ascii=False)+"\n", encoding="utf-8")
    md = REPORTS_DIR / "app-intelligence-profile.md"
    framework_lines = [f"- {x}" for x in findings['framework_hints']] or ["- None detected"]
    risk_lines = [f"- {x}" for x in findings['automation_risks']] or ["- None detected"]
    md_lines = [
        f"# App Intelligence Profile — {feature}", "",
        f"URL: `{base_url}`", f"DOM title: `{profile.get('dom_title')}`", "",
        "## Framework hints", *framework_lines, "",
        "## Automation risks", *risk_lines, "",
        "## Recommended user inputs", *[f"- {x}" for x in findings['recommended_inputs']], "",
        "## Questions to ask when context is missing", *[f"- {x}" for x in findings.get('context_questions', [])], "",
        "## Locator strategy", *[f"- {x}" for x in findings['locator_strategy']], "",
        "## Self-healing strategy", *[f"- {x}" for x in findings['healing_strategy']], "",
    ]
    md.write_text("\n".join(md_lines)+"\n", encoding="utf-8")
    profile["profile_file"] = str(out.relative_to(REPO_ROOT))
    profile["markdown_file"] = str(md.relative_to(REPO_ROOT))
    return profile
