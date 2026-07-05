from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from qa_pipeline.core.paths import QA_CACHE_DIR, REPORTS_DIR
from qa_pipeline.core.runtime_logger import log_event

MCP_RCA_DIR = REPORTS_DIR / "existing-framework" / "mcp-assisted-rca"
MCP_RCA_JSON = MCP_RCA_DIR / "mcp-assisted-locator-rca.json"
MCP_RCA_HTML = MCP_RCA_DIR / "mcp-assisted-locator-rca.html"
MCP_MEMORY_JSONL = QA_CACHE_DIR / "existing-framework" / "mcp-assisted-memory.jsonl"

_LOCATOR_PATTERNS = [
    r"locator\(([^\n]+?)\)",
    r"getByRole\(([^\n]+?)\)",
    r"getByText\(([^\n]+?)\)",
    r"getByTestId\(([^\n]+?)\)",
    r"getByLabel\(([^\n]+?)\)",
    r"getByPlaceholder\(([^\n]+?)\)",
    r"getByTitle\(([^\n]+?)\)",
    r"getByAltText\(([^\n]+?)\)",
]

_TEXT_PATTERNS = [
    r"name:\s*/([^/]+)/[a-z]*",
    r"name:\s*['\"]([^'\"]+)['\"]",
    r"hasText:\s*['\"]([^'\"]+)['\"]",
    r"text\s*[:=]\s*['\"]([^'\"]+)['\"]",
    r"['\"]([^'\"]{2,80})['\"]",
]


def _html(value: Any) -> str:
    return str(value if value is not None else "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _read(path: Path, limit: int = 200000) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")[:limit]
    except Exception:
        return ""


def _extract_locator_snippets(failure_text: str) -> list[str]:
    snippets: list[str] = []
    for pattern in _LOCATOR_PATTERNS:
        for hit in re.findall(pattern, failure_text or "", flags=re.I | re.S):
            clean = re.sub(r"\s+", " ", hit).strip()
            clean = clean[:220]
            if clean and clean not in snippets:
                snippets.append(clean)
    # Playwright error sometimes says: waiting for getByRole('button', { name: 'Submit' })
    for line in (failure_text or "").splitlines():
        low = line.lower()
        if any(k in low for k in ["waiting for", "locator", "getbyrole", "getbytext", "getbytestid"]):
            line = line.strip()[:260]
            if line and line not in snippets:
                snippets.append(line)
    return snippets[:20]


def _extract_visible_text_candidates(locator_snippets: list[str], failure_text: str) -> list[str]:
    candidates: list[str] = []
    combined = "\n".join(locator_snippets) + "\n" + (failure_text or "")[-5000:]
    for pattern in _TEXT_PATTERNS:
        for hit in re.findall(pattern, combined, flags=re.I | re.S):
            clean = re.sub(r"\s+", " ", str(hit)).strip(" /'\"`)({}[]")[:120]
            if clean and len(clean) >= 2 and clean.lower() not in {"button", "textbox", "link", "div", "span"} and clean not in candidates:
                candidates.append(clean)
    return candidates[:20]


def _find_text_in_files(root: Path, text_candidates: list[str], suffixes: tuple[str, ...]) -> dict[str, list[str]]:
    found: dict[str, list[str]] = {t: [] for t in text_candidates}
    if not text_candidates:
        return found
    ignored = {"node_modules", ".git", "reports", "playwright-report", "test-results", "dist", "build", "coverage"}
    for path in root.rglob("*"):
        if not path.is_file() or any(p in ignored for p in path.parts):
            continue
        if not path.name.lower().endswith(suffixes):
            continue
        txt = _read(path, limit=100000)
        low = txt.lower()
        for cand in text_candidates:
            if cand.lower() in low:
                try:
                    rel = str(path.relative_to(root)).replace("\\", "/")
                except Exception:
                    rel = str(path)
                if rel not in found[cand]:
                    found[cand].append(rel)
    return {k: v[:25] for k, v in found.items()}


def _find_locator_in_pom(root: Path, locator_snippets: list[str], text_candidates: list[str]) -> dict[str, Any]:
    suffixes = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs")
    page_object_hits: list[dict[str, Any]] = []
    spec_inline_hits: list[dict[str, Any]] = []
    ignored = {"node_modules", ".git", "reports", "playwright-report", "test-results", "dist", "build", "coverage"}
    keys = [*locator_snippets, *text_candidates]
    keys = [k for k in keys if k]
    for path in root.rglob("*"):
        if not path.is_file() or any(p in ignored for p in path.parts):
            continue
        if not path.name.lower().endswith(suffixes):
            continue
        txt = _read(path, limit=120000)
        low_path = str(path.relative_to(root)).replace("\\", "/").lower()
        matched = []
        for key in keys:
            if key.lower() in txt.lower():
                matched.append(key[:100])
        if matched:
            rel = str(path.relative_to(root)).replace("\\", "/")
            record = {"file": rel, "matched": matched[:8]}
            if any(x in low_path for x in ["pageobject", "page-object", "objects", "locators", "pages/"]):
                page_object_hits.append(record)
            if rel.endswith((".spec.ts", ".test.ts", ".spec.js", ".test.js")):
                spec_inline_hits.append(record)
    return {
        "page_or_page_object_hits": page_object_hits[:30],
        "spec_inline_hits": spec_inline_hits[:30],
        "pom_strategy_observation": "Prefer fixing locator in pageObjects/locator module or reusable page method. Inline spec locator changes require human review unless no POM layer exists.",
    }


def _mcp_tool_plan(locator_snippets: list[str], text_candidates: list[str]) -> list[dict[str, Any]]:
    # This is an auditable plan for the MCP client/AI agent. The backend writes the exact
    # browser-inspection checklist into the RCA report. Codex/Ollama can use this to call
    # Microsoft Playwright MCP when available.
    return [
        {
            "step": 1,
            "name": "Identify failed locator/action",
            "question": "Which locator or Playwright action failed?",
            "evidence": locator_snippets,
            "mcp_usage": "Use Playwright MCP accessibility snapshot around the current page or failed state to compare the target role/name/text with the failed locator.",
        },
        {
            "step": 2,
            "name": "Check locator text on visible GUI",
            "question": "Is the intended button/link/input text visible to the user?",
            "evidence": text_candidates,
            "mcp_usage": "Use MCP browser snapshot / accessibility tree to list visible roles and names. Prefer role+accessible-name over screenshot guessing.",
        },
        {
            "step": 3,
            "name": "Check DOM/accessibility presence",
            "question": "Does the element exist in DOM/accessibility tree?",
            "mcp_usage": "Use MCP snapshot and locator probe to confirm whether the target exists, is hidden, duplicated, or inside iframe/shadow DOM.",
        },
        {
            "step": 4,
            "name": "Check actionability/interactability",
            "question": "If element exists, can it receive click/fill/select action?",
            "mcp_usage": "Use MCP click/hover/fill probes only in diagnostic mode. Detect overlays, disabled state, offscreen location, detached DOM, and permission popups.",
        },
        {
            "step": 5,
            "name": "Map fix to POM/reuse layer",
            "question": "Is the correct locator strategy implemented in pageObjects/pages/util layer?",
            "mcp_usage": "Use observed role/name/testId from MCP plus RAG-indexed framework context. Patch pageObjects first, then page methods/helpers, not raw spec locators.",
        },
    ]



def _element_level_failure_identification(failure_text: str, locator_snippets: list[str], text_candidates: list[str]) -> dict[str, Any]:
    low = (failure_text or "").lower()
    if any(x in low for x in ["not attached to the dom", "element is not attached", "detached"]):
        failure_type = "locator_detached_from_dom"
        plain = "The test found an element reference, but the page re-rendered or changed before Playwright could scroll/click it. The fix should re-query the locator after the page settles and update the pageObject/page method with a stable live locator."
        next_fix = "Use MCP/codegen/live DOM snapshot to confirm the currently attached element, then patch the object repository or page method. Do not fix with blind sleeps."
    elif any(x in low for x in ["strict mode violation", "resolved to", "more than one element"]):
        failure_type = "locator_ambiguous_multiple_matches"
        plain = "The locator matches more than one element. It needs a more specific role/name/testId or parent-child scope in the pageObject repository."
        next_fix = "Use accessibility snapshot to choose the exact role/name and replace the broad locator in the shared locator/pageObject file."
    elif any(x in low for x in ["waiting for locator", "to be visible", "element(s) not found", "no element", "not found"]):
        failure_type = "locator_missing_or_not_visible"
        plain = "The expected element was not visible or not present in the current page state. It may be a changed locator, route/state issue, auth/data issue, or responsive/mobile viewport difference."
        next_fix = "Check DOM/accessibility presence through MCP. If element exists with changed role/text/testId, update the locator repository; if not, verify navigation/data/environment first."
    elif any(x in low for x in ["intercepts pointer events", "modal", "dialog", "overlay", "cookie", "permission"]):
        failure_type = "element_blocked_by_overlay_or_permission"
        plain = "The target element exists, but a modal, cookie banner, location prompt, or overlay is blocking the action."
        next_fix = "Patch shared blocker-dismissal or page action helper before interacting with the target; avoid force:true unless explicitly approved."
    elif any(x in low for x in ["outside of the viewport", "scrolling into view", "footer", "hamburger"]):
        failure_type = "viewport_or_scroll_actionability"
        plain = "The element is likely present but not reachable in the current viewport or mobile menu state."
        next_fix = "Use viewport-aware helper and scroll/menu handling in the page method, then re-query the locator."
    elif any(x in low for x in ["tohaveurl", "waitforurl", "navigation", "received string"]):
        failure_type = "navigation_or_state_sync"
        plain = "The action did not navigate to the expected state or URL. The issue may be a wrong click target, blocked navigation, or changed product flow."
        next_fix = "Use MCP to verify clicked element and then patch the page navigation helper or expected URL only after product behavior is confirmed."
    else:
        failure_type = "insufficient_element_evidence"
        plain = "The current failed inventory does not contain enough locator/action details for a confident element-level diagnosis."
        next_fix = "Run failed test headed with trace/screenshot/video and then run this MCP check again."
    return {
        "failure_type": failure_type,
        "plain_english": plain,
        "locator_candidates": locator_snippets[:8],
        "visible_text_candidates": text_candidates[:8],
        "recommended_next_fix": next_fix,
    }


def build_mcp_assisted_locator_rca(root: Path, failed_inventory: dict[str, Any], failure_text: str, base_url: str = "") -> dict[str, Any]:
    MCP_RCA_DIR.mkdir(parents=True, exist_ok=True)
    locator_snippets = _extract_locator_snippets(failure_text)
    text_candidates = _extract_visible_text_candidates(locator_snippets, failure_text)
    dom_text_hits = _find_text_in_files(root, text_candidates, (".html", ".htm", ".json", ".txt", ".md"))
    pom_hits = _find_locator_in_pom(root, locator_snippets, text_candidates)
    chains: list[dict[str, Any]] = []
    if locator_snippets:
        category = "locator_or_actionability_failure"
        confidence = 0.86
    else:
        category = "mcp_probe_recommended_insufficient_locator_evidence"
        confidence = 0.42
    for plan in _mcp_tool_plan(locator_snippets, text_candidates):
        chains.append(plan)
    element_identification = _element_level_failure_identification(failure_text, locator_snippets, text_candidates)
    significance = {
        "button_name": "Check failed element with Playwright MCP",
        "purpose": "Diagnose the exact failed element/action using observable browser/accessibility/DOM evidence before any code patch.",
        "what_it_identifies": [
            "the failed locator/action candidate from Playwright error text",
            "whether the intended text/role/testId is visible in the current GUI evidence",
            "whether the element is missing, detached from DOM, hidden, disabled, duplicated, inside iframe/shadow DOM, or blocked by overlay/permission popup",
            "which pageObject/page/helper file should own the smallest safe fix",
        ],
        "what_it_does_not_do": "It does not silently change files. It creates RCA evidence and a safe patch direction for Create safe fix plan / Fix failed tests safely.",
    }
    payload = {
        "ok": True,
        "stage": "mcp_assisted_locator_rca_ready",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "framework_path": str(root),
        "base_url": base_url,
        "category": category,
        "confidence": confidence,
        "significance": significance,
        "element_level_failure_identification": element_identification,
        "failed_specs": failed_inventory.get("failed_specs") or [],
        "failed_tests": failed_inventory.get("failed_tests") or [],
        "failed_locator_or_action_candidates": locator_snippets,
        "visible_text_candidates": text_candidates,
        "dom_or_artifact_text_hits": dom_text_hits,
        "pom_locator_mapping": pom_hits,
        "mcp_auditable_rca_steps": chains,
        "safe_fix_rule": "Use MCP/accessibility snapshot evidence to repair the smallest POM-layer locator/action fix. Do not weaken assertions, skip tests, force click by default, or patch passed scripts.",
        "memory_note": "This MCP-assisted diagnosis is saved so future Codex/Ollama prompts can reuse observed locator, UI text, DOM, and POM mapping evidence.",
    }
    MCP_RCA_JSON.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    _write_html(payload)
    MCP_MEMORY_JSONL.parent.mkdir(parents=True, exist_ok=True)
    with MCP_MEMORY_JSONL.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"type": "mcp_assisted_locator_rca", "created_at": payload["generated_at"], "summary": {"category": category, "confidence": confidence, "failed_specs": payload["failed_specs"], "locators": locator_snippets[:5], "texts": text_candidates[:5]}}, ensure_ascii=False) + "\n")
    log_event("existing_framework_mcp", "MCP-assisted locator/actionability RCA chain saved to project memory.", status="done", progress=100, details={"category": category, "confidence": confidence})
    return payload


def _write_html(payload: dict[str, Any]) -> None:
    rows = "".join(
        f"<tr><td>{_html(s.get('step'))}</td><td><b>{_html(s.get('name'))}</b><br/><span>{_html(s.get('question'))}</span></td><td>{_html(s.get('mcp_usage'))}</td></tr>"
        for s in payload.get("mcp_auditable_rca_steps", [])
    )
    html = f"""<!doctype html><html><head><meta charset='utf-8'/><title>MCP Assisted RCA</title>
<style>body{{font-family:Segoe UI,Arial,sans-serif;margin:24px;background:#f8fafc;color:#0f172a}}.card{{background:white;border:1px solid #dbe3ef;border-radius:14px;padding:16px;margin:14px 0}}table{{border-collapse:collapse;width:100%}}td,th{{border-bottom:1px solid #e2e8f0;padding:10px;text-align:left;vertical-align:top}}code,pre{{background:#0f172a;color:#dbeafe;border-radius:10px;padding:12px;white-space:pre-wrap;display:block}}.ok{{color:#16a34a;font-weight:800}}.warn{{color:#b45309;font-weight:800}}</style></head><body>
<h1>Microsoft Playwright MCP Assisted RCA</h1>
<div class='card'><b>Category:</b> <span class='ok'>{_html(payload.get('category'))}</span><br/><b>Confidence:</b> {_html(payload.get('confidence'))}<br/><b>Framework:</b> <code>{_html(payload.get('framework_path'))}</code></div>
<div class='card'><h2>Why this button exists</h2><p>{_html((payload.get('significance') or {}).get('purpose'))}</p><pre>{_html(json.dumps(payload.get('significance'), indent=2, ensure_ascii=False))}</pre></div>
<div class='card'><h2>Element-level failure identified</h2><p><b>{_html((payload.get('element_level_failure_identification') or {}).get('failure_type'))}</b></p><p>{_html((payload.get('element_level_failure_identification') or {}).get('plain_english'))}</p><p><b>Recommended next fix:</b> {_html((payload.get('element_level_failure_identification') or {}).get('recommended_next_fix'))}</p></div>
<div class='card'><h2>Failed locator/action candidates</h2><pre>{_html(json.dumps(payload.get('failed_locator_or_action_candidates'), indent=2, ensure_ascii=False))}</pre></div>
<div class='card'><h2>Visible text candidates</h2><pre>{_html(json.dumps(payload.get('visible_text_candidates'), indent=2, ensure_ascii=False))}</pre></div>
<div class='card'><h2>Auditable RCA Steps</h2><table><tr><th>#</th><th>Check</th><th>How Playwright MCP helps</th></tr>{rows}</table></div>
<div class='card'><h2>POM mapping evidence</h2><pre>{_html(json.dumps(payload.get('pom_locator_mapping'), indent=2, ensure_ascii=False))}</pre></div>
<div class='card'><h2>Safe fix rule</h2><p>{_html(payload.get('safe_fix_rule'))}</p></div>
</body></html>"""
    MCP_RCA_HTML.write_text(html, encoding="utf-8")
