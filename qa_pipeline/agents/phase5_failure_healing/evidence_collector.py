from __future__ import annotations

import json
import re
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

from qa_pipeline.core.paths import GENERATED_PLAYWRIGHT_DIR, REPORTS_DIR, REPO_ROOT
from qa_pipeline.core.project_config import load_project_config
from qa_pipeline.core.url_guard import normalize_base_url


@dataclass
class DomCandidate:
    score: int
    tag: str
    text: str
    attrs: dict[str, Any]
    selector_hint: str
    reason: str


@dataclass
class FailureEvidence:
    base_url: str
    failure_text: str
    failed_tests: list[dict[str, Any]]
    missing_target: str
    candidate_locators: list[dict[str, Any]]
    url_leaks: list[str]
    generated_files: dict[str, str]
    artifacts: dict[str, str]
    raw: dict[str, Any]


LOCALHOST_PAT = re.compile(r"(?:https?://)?(?:127\.0\.0\.1|localhost)(?::\d+)?(?:/[\w\-./?=&%]*)?", re.I)


def read_text(path: Path, limit: int = 80_000) -> str:
    if not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="replace")[-limit:]
    except Exception:
        return ""


def read_json(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return None


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT)).replace("\\", "/")
    except Exception:
        return str(path).replace("\\", "/")


def flatten_failed_tests(results: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not isinstance(results, dict):
        return rows

    def walk_suite(suite: dict[str, Any], parents: list[str]) -> None:
        title = suite.get("title") or ""
        chain = parents + ([title] if title else [])
        for spec in suite.get("specs", []) or []:
            spec_title = spec.get("title") or ""
            for test in spec.get("tests", []) or []:
                for result in test.get("results", []) or []:
                    status = result.get("status") or test.get("status") or spec.get("ok")
                    if status in {"passed", True}:
                        continue
                    errors = result.get("errors") or []
                    error_text = "\n".join(json.dumps(e, ensure_ascii=False) if isinstance(e, dict) else str(e) for e in errors)
                    rows.append({
                        "title": " > ".join([x for x in chain + [spec_title] if x]),
                        "status": status,
                        "duration": result.get("duration", 0),
                        "error_text": error_text,
                        "attachments": result.get("attachments") or [],
                    })
        for child in suite.get("suites", []) or []:
            walk_suite(child, chain)

    for suite in results.get("suites", []) or []:
        walk_suite(suite, [])
    return rows


def combined_failure_text() -> str:
    execution = read_json(REPORTS_DIR / "playwright-mcp-execution.json") or {}
    results = read_json(REPORTS_DIR / "results.json") or {}
    failed_rows = flatten_failed_tests(results)
    parts = [
        json.dumps(execution, indent=2, ensure_ascii=False)[-35_000:] if execution else "",
        json.dumps(failed_rows, indent=2, ensure_ascii=False)[-60_000:] if failed_rows else "",
        read_text(REPORTS_DIR / "quality-review.json", 20_000),
    ]
    return "\n".join(p for p in parts if p)


def extract_missing_target(text: str) -> str:
    patterns = [
        r"getByRole\([^\n]+?name:\s*/([^/]{2,160})/",
        r"getByRole\([^\n]+?name:\s*['\"]([^'\"]{2,160})['\"]",
        r"getByText\([^\n]*?['\"]([^'\"]{2,160})['\"]",
        r"getByLabel\([^\n]*?['\"]([^'\"]{2,160})['\"]",
        r"locator\(['\"]([^'\"]{2,180})['\"]\)",
        r"waiting for (?:locator|expect)\(([^\n]{2,180})\)",
        r"Timeout .*? (?:for|while) ([^\n]{2,180})",
        r"Error:.*?(?:text|locator|element).*?['\"]([^'\"]{2,160})['\"]",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.I | re.S)
        if m:
            value = re.sub(r"\\s\+", " ", m.group(1)).strip()
            value = re.sub(r"[{}()\\]", " ", value).strip()
            return value[:160]
    return ""


def load_dom_elements() -> list[dict[str, Any]]:
    dom = read_json(REPORTS_DIR / "dynamic-dom-map.json")
    if not isinstance(dom, dict):
        return []
    out: list[dict[str, Any]] = []
    for item in dom.get("elements", []) or []:
        if not isinstance(item, dict):
            continue
        attrs = item.get("attrs") or {}
        text = str(item.get("text") or "")
        if text or attrs.get("href") or attrs.get("aria-label") or attrs.get("alt") or attrs.get("title"):
            out.append(item)
    return out


def build_selector_hint(item: dict[str, Any]) -> str:
    tag = str(item.get("tag") or "").lower()
    attrs = item.get("attrs") or {}
    text = str(item.get("text") or "").strip()
    if attrs.get("data-testid"):
        return f"getByTestId('{attrs['data-testid']}')"
    if tag in {"a", "button"} and text:
        role = "link" if tag == "a" else "button"
        return f"getByRole('{role}', {{ name: /{re.escape(text[:60])}/i }})"
    if attrs.get("aria-label"):
        role = "link" if tag == "a" else "button" if tag == "button" else "generic"
        return f"getByRole('{role}', {{ name: /{re.escape(str(attrs['aria-label'])[:60])}/i }})"
    if attrs.get("href"):
        href = str(attrs["href"])
        key = href.strip('/').split('/')[-1] or href
        return f"locator('a[href*=\"{key[:40]}\"]')"
    if text:
        return f"getByText(/{re.escape(text[:60])}/i)"
    return tag or "unknown"


def find_dom_candidates(target: str, limit: int = 8) -> list[dict[str, Any]]:
    if not target:
        return []
    target_norm = re.sub(r"\s+", " ", target).lower().strip()
    words = {w for w in re.findall(r"[a-z0-9]+", target_norm) if len(w) > 2}
    scored: list[DomCandidate] = []
    for item in load_dom_elements():
        attrs = item.get("attrs") or {}
        tag = str(item.get("tag") or "").lower()
        hay_parts = [
            str(item.get("text") or ""), str(attrs.get("aria-label") or ""),
            str(attrs.get("alt") or ""), str(attrs.get("title") or ""), str(attrs.get("href") or ""),
            str(attrs.get("data-testid") or ""), str(attrs.get("id") or ""), str(attrs.get("class") or ""),
        ]
        hay = " ".join(hay_parts).lower()
        score = 0
        reasons = []
        if target_norm and target_norm in hay:
            score += 50; reasons.append("exact/substring match")
        matched_words = [w for w in words if w in hay]
        if matched_words:
            score += len(matched_words) * 8; reasons.append("word overlap: " + ", ".join(matched_words[:5]))
        if tag in {"a", "button", "input", "select", "textarea"}:
            score += 8; reasons.append("actionable element")
        if attrs.get("href"):
            score += 5; reasons.append("has href")
        if attrs.get("data-testid") or attrs.get("aria-label"):
            score += 7; reasons.append("stable attribute")
        if score > 0:
            scored.append(DomCandidate(
                score=score, tag=tag, text=str(item.get("text") or "")[:220], attrs=attrs,
                selector_hint=build_selector_hint(item), reason="; ".join(reasons)
            ))
    scored.sort(key=lambda c: c.score, reverse=True)
    return [asdict(c) for c in scored[:limit]]


def generated_file_map(feature: str) -> dict[str, str]:
    files: dict[str, str] = {}
    for path in [
        GENERATED_PLAYWRIGHT_DIR / "tests" / "generated" / f"{feature}.spec.ts",
        GENERATED_PLAYWRIGHT_DIR / "pages" / f"{feature.capitalize()}Page.ts",
        GENERATED_PLAYWRIGHT_DIR / "pageObjects" / f"{feature.capitalize()}Page.objects.ts",
        GENERATED_PLAYWRIGHT_DIR / "pages" / "AcimaPage.ts",
        GENERATED_PLAYWRIGHT_DIR / "pageObjects" / "AcimaPage.objects.ts",
        GENERATED_PLAYWRIGHT_DIR / "pages" / "BasePage.ts",
        GENERATED_PLAYWRIGHT_DIR / "utils" / "locatorFactory.ts",
    ]:
        if path.exists():
            files[rel(path)] = read_text(path, 25_000)
    return files



def discover_failure_artifacts(limit: int = 40) -> dict[str, list[str]]:
    """Index useful Playwright RCA artifacts without requiring a fixed reporter layout."""
    roots = [REPORTS_DIR, GENERATED_PLAYWRIGHT_DIR / "test-results", GENERATED_PLAYWRIGHT_DIR / "playwright-report", GENERATED_PLAYWRIGHT_DIR / "failures"]
    patterns = {
        "traces": ["*.zip", "*.trace"],
        "videos": ["*.webm", "*.mp4"],
        "screenshots": ["*.png", "*.jpg", "*.jpeg"],
        "har": ["*.har", "network-events.json"],
        "dom_snapshots": ["*dom*.html", "*dom*.json", "*.dom.html", "*.dom.json"],
    }
    indexed: dict[str, list[Path]] = {k: [] for k in patterns}
    ignored = {"node_modules", ".git", "dist", "build"}
    for root in roots:
        if not root.exists():
            continue
        for kind, pats in patterns.items():
            for pat in pats:
                for path in root.rglob(pat):
                    if path.is_file() and not (set(path.parts) & ignored):
                        indexed[kind].append(path)
    return {
        kind: [rel(p) for p in sorted(set(paths), key=lambda x: x.stat().st_mtime if x.exists() else 0, reverse=True)[:limit]]
        for kind, paths in indexed.items()
    }

def collect_failure_evidence(feature: str = "feature", base_url: str = "") -> dict[str, Any]:
    base_url = normalize_base_url(base_url or load_project_config().get("base_url", ""))
    failure_text = combined_failure_text()
    results = read_json(REPORTS_DIR / "results.json") or {}
    failed_tests = flatten_failed_tests(results)
    missing_target = extract_missing_target(failure_text)
    candidates = find_dom_candidates(missing_target)
    url_leaks = sorted(set(LOCALHOST_PAT.findall(failure_text + "\n" + "\n".join(generated_file_map(feature).values()))))
    evidence = FailureEvidence(
        base_url=base_url,
        failure_text=failure_text[-80_000:],
        failed_tests=failed_tests[:25],
        missing_target=missing_target,
        candidate_locators=candidates,
        url_leaks=url_leaks,
        generated_files=generated_file_map(feature),
        artifacts={
            "execution": rel(REPORTS_DIR / "playwright-mcp-execution.json"),
            "playwright_results": rel(REPORTS_DIR / "results.json"),
            "dynamic_dom": rel(REPORTS_DIR / "dynamic-dom-map.json"),
            "full_page_screenshot": rel(REPORTS_DIR / f"{feature}-full-page.png"),
            "quality_review": rel(REPORTS_DIR / "quality-review.json"),
            "artifact_index": discover_failure_artifacts(),
        },
        raw={"results_present": bool(results), "dom_elements": len(load_dom_elements()), "artifact_index_available": discover_failure_artifacts()},
    )
    out = REPORTS_DIR / "failure-evidence.json"
    out.write_text(json.dumps(asdict(evidence), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return asdict(evidence)
