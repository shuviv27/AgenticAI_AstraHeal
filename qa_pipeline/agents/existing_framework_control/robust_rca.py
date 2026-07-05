from __future__ import annotations

import difflib
import hashlib
import json
import os
import re
import shutil
import time
import zipfile
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from qa_pipeline.core.paths import QA_CACHE_DIR, REPORTS_DIR
from qa_pipeline.llm.codex_cli import CodexCliProvider
from qa_pipeline.llm.ollama import OllamaProvider

ROBUST_RCA_DIR = REPORTS_DIR / "existing-framework" / "robust-rca"
ROBUST_EVIDENCE_JSON = ROBUST_RCA_DIR / "multi-signal-evidence.json"
ROBUST_CHAIN_MD = ROBUST_RCA_DIR / "auditable-rca-chain.md"
ROBUST_CHAIN_HTML = ROBUST_RCA_DIR / "auditable-rca-chain.html"
SELECTOR_HEALTH_HTML = REPORTS_DIR / "existing-framework" / "selector-health-report.html"
SELECTOR_HEALTH_JSON = REPORTS_DIR / "existing-framework" / "selector-health-report.json"

ROBUST_CACHE_DIR = QA_CACHE_DIR / "existing-framework" / "robust-rca"
BASELINE_DIR = ROBUST_CACHE_DIR / "baselines"
HISTORY_JSON = ROBUST_CACHE_DIR / "execution-history.json"
FEEDBACK_JSONL = ROBUST_CACHE_DIR / "healing-feedback.jsonl"
SELECTOR_VAULT_JSON = ROBUST_CACHE_DIR / "selector-vault.json"
PATCH_REVIEW_JSON = ROBUST_RCA_DIR / "patch-confidence-review.json"

DATA_SUFFIXES = {
    ".json", ".yaml", ".yml", ".csv", ".tsv", ".txt", ".sql", ".env",
}
CODE_SUFFIXES = {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"}
IGNORED_DIR_PARTS = {"node_modules", ".git", "dist", "build", "coverage"}


def _ensure() -> None:
    ROBUST_RCA_DIR.mkdir(parents=True, exist_ok=True)
    ROBUST_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    BASELINE_DIR.mkdir(parents=True, exist_ok=True)


def _rel(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")
    except Exception:
        return str(path).replace("\\", "/")


def _ignored(path: Path, root: Path) -> bool:
    try:
        parts = set(path.relative_to(root).parts)
    except Exception:
        parts = set(path.parts)
    return bool(parts & IGNORED_DIR_PARTS)


def _read(path: Path, limit: int = 2_000_000) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")[:limit]
    except Exception:
        return ""


def _json_read(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return default


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="ignore")).hexdigest()


def _hash_file(path: Path) -> dict[str, Any]:
    text = _read(path)
    return {"sha256": _hash_text(text), "bytes": len(text.encode("utf-8", errors="ignore"))}


def _walk_recent(root: Path, patterns: list[str], limit: int = 80) -> list[Path]:
    found: list[Path] = []
    for pattern in patterns:
        for path in root.rglob(pattern):
            if path.is_file() and not _ignored(path, root):
                found.append(path)
    found = sorted(set(found), key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True)
    return found[:limit]


def _artifact_index(root: Path) -> dict[str, Any]:
    failures_dirs = [p for p in (root / "failures").glob("run-*") if p.is_dir()] if (root / "failures").exists() else []
    failures_dirs = sorted(failures_dirs, key=lambda p: p.stat().st_mtime, reverse=True)[:10]
    trace_files = _walk_recent(root, ["*.zip", "*.trace"], limit=40)
    har_files = _walk_recent(root, ["*.har"], limit=40)
    dom_files = _walk_recent(root, ["*.dom.html", "*.dom.json", "dom-*.html", "dom-*.json", "*dom-snapshot*.html", "*dom-snapshot*.json"], limit=80)
    screenshots = _walk_recent(root, ["*.png", "*.jpg", "*.jpeg"], limit=40)
    return {
        "failure_run_dirs": [_rel(p, root) for p in failures_dirs],
        "trace_files": [_rel(p, root) for p in trace_files],
        "har_files": [_rel(p, root) for p in har_files],
        "dom_snapshot_files": [_rel(p, root) for p in dom_files],
        "screenshots": [_rel(p, root) for p in screenshots],
    }


def _tag_counter_from_html(text: str) -> Counter[str]:
    tags = re.findall(r"<\s*([a-zA-Z0-9:-]+)(?:\s|>|/)", text or "")
    return Counter(t.lower() for t in tags)


def _attrs_from_html(text: str) -> Counter[str]:
    attrs = re.findall(r"\s(data-[\w:-]+|aria-[\w:-]+|role|id|class|name|placeholder|href)=", text or "", flags=re.I)
    return Counter(a.lower() for a in attrs)


def _compare_latest_pair(files: list[Path], root: Path, label: str) -> dict[str, Any]:
    if len(files) < 2:
        return {"available": bool(files), "signal": label, "changed": False, "confidence": 0.25 if files else 0.0, "note": "Need at least two snapshots to compute diff.", "files_seen": [_rel(p, root) for p in files[:2]]}
    latest, previous = files[0], files[1]
    a = _read(previous)
    b = _read(latest)
    changed = _hash_text(a) != _hash_text(b)
    tag_delta = {}
    attr_delta = {}
    if changed:
        tags_a, tags_b = _tag_counter_from_html(a), _tag_counter_from_html(b)
        attrs_a, attrs_b = _attrs_from_html(a), _attrs_from_html(b)
        tag_delta = {k: tags_b[k] - tags_a[k] for k in sorted(set(tags_a) | set(tags_b)) if tags_b[k] != tags_a[k]}
        attr_delta = {k: attrs_b[k] - attrs_a[k] for k in sorted(set(attrs_a) | set(attrs_b)) if attrs_b[k] != attrs_a[k]}
    ratio = 0.0
    if a or b:
        ratio = 1 - difflib.SequenceMatcher(None, a[:200_000], b[:200_000]).ratio()
    return {
        "available": True,
        "signal": label,
        "changed": changed,
        "confidence": min(0.95, 0.45 + ratio) if changed else 0.55,
        "latest": _rel(latest, root),
        "previous": _rel(previous, root),
        "change_ratio": round(ratio, 4),
        "tag_delta_top": dict(list(sorted(tag_delta.items(), key=lambda x: abs(x[1]), reverse=True))[:20]),
        "attribute_delta_top": dict(list(sorted(attr_delta.items(), key=lambda x: abs(x[1]), reverse=True))[:20]),
    }


def _schema_shape(value: Any, depth: int = 0) -> Any:
    if depth > 4:
        return "..."
    if isinstance(value, dict):
        return {k: _schema_shape(v, depth + 1) for k, v in sorted(value.items())[:80]}
    if isinstance(value, list):
        return [_schema_shape(value[0], depth + 1)] if value else []
    return type(value).__name__


def _read_har_summary(path: Path) -> dict[str, Any]:
    data = _json_read(path, {})
    entries = (((data or {}).get("log") or {}).get("entries") or []) if isinstance(data, dict) else []
    urls: dict[str, dict[str, Any]] = {}
    statuses = Counter()
    schema_shapes: dict[str, Any] = {}
    for e in entries[:500]:
        req = e.get("request") or {}
        res = e.get("response") or {}
        url = str(req.get("url") or "")
        short = re.sub(r"[?#].*$", "", url)[-140:]
        status = int(res.get("status") or 0)
        statuses[str(status)] += 1
        urls[short] = {"method": req.get("method"), "status": status, "mimeType": (res.get("content") or {}).get("mimeType")}
        text = (res.get("content") or {}).get("text") or ""
        if text and "json" in str((res.get("content") or {}).get("mimeType") or "").lower():
            try:
                schema_shapes[short] = _schema_shape(json.loads(text))
            except Exception:
                pass
    return {"entry_count": len(entries), "statuses": dict(statuses), "responses": urls, "schemas": schema_shapes}


def _har_diff_signal(root: Path) -> dict[str, Any]:
    files = _walk_recent(root, ["*.har"], limit=5)
    if len(files) < 2:
        return {"available": bool(files), "signal": "network_har_diff", "changed": False, "confidence": 0.20 if files else 0.0, "note": "Need current and previous HAR. TestTelemetry can capture this automatically."}
    latest, previous = files[0], files[1]
    a = _read_har_summary(previous)
    b = _read_har_summary(latest)
    changed_status = a.get("statuses") != b.get("statuses")
    schema_keys_a = set((a.get("schemas") or {}).keys())
    schema_keys_b = set((b.get("schemas") or {}).keys())
    schema_changed = schema_keys_a != schema_keys_b or any((a.get("schemas") or {}).get(k) != (b.get("schemas") or {}).get(k) for k in schema_keys_a & schema_keys_b)
    changed = changed_status or schema_changed
    return {
        "available": True,
        "signal": "network_har_diff",
        "changed": changed,
        "confidence": 0.88 if changed else 0.55,
        "latest": _rel(latest, root),
        "previous": _rel(previous, root),
        "status_delta": {"previous": a.get("statuses"), "latest": b.get("statuses")},
        "schema_changed": schema_changed,
        "added_schema_urls": sorted(schema_keys_b - schema_keys_a)[:30],
        "removed_schema_urls": sorted(schema_keys_a - schema_keys_b)[:30],
    }


def _fixture_files(root: Path) -> list[Path]:
    candidates: list[Path] = []
    keywords = ("fixture", "fixtures", "testdata", "test-data", "seed", "seeds", "data", "mock", "mocks")
    for path in root.rglob("*"):
        if not path.is_file() or _ignored(path, root):
            continue
        low = str(path).lower()
        if path.suffix.lower() in DATA_SUFFIXES and any(k in low for k in keywords):
            candidates.append(path)
    return sorted(candidates, key=lambda p: _rel(p, root))[:1000]


def _current_fixture_snapshot(root: Path) -> dict[str, Any]:
    return { _rel(p, root): _hash_file(p) for p in _fixture_files(root) }


def _fixture_seed_diff_signal(root: Path) -> dict[str, Any]:
    current = _current_fixture_snapshot(root)
    baseline_path = BASELINE_DIR / "last-passed-fixtures.json"
    previous = _json_read(baseline_path, {})
    if not previous:
        return {"available": bool(current), "signal": "fixture_seed_diff", "changed": False, "confidence": 0.20 if current else 0.0, "note": "No passed-run fixture baseline yet. It will be created after a passing run.", "fixture_count": len(current)}
    changed = [rel for rel, meta in current.items() if previous.get(rel, {}).get("sha256") != meta.get("sha256")]
    removed = [rel for rel in previous.keys() if rel not in current]
    added = [rel for rel in current.keys() if rel not in previous]
    has_change = bool(changed or removed or added)
    return {
        "available": True,
        "signal": "fixture_seed_diff",
        "changed": has_change,
        "confidence": 0.82 if has_change else 0.55,
        "changed_files": changed[:50],
        "added_files": added[:50],
        "removed_files": removed[:50],
        "fixture_count": len(current),
    }


def _trace_replay_signal(root: Path, failure_text: str) -> dict[str, Any]:
    trace_files = _walk_recent(root, ["*.zip", "*.trace"], limit=20)
    low = (failure_text or "").lower()
    timing_words = ["timeout", "waiting for", "locator", "element is not", "not visible", "detached", "navigation", "load state", "networkidle", "intercepts pointer events"]
    timing_score = sum(1 for w in timing_words if w in low)
    trace_has_actions = False
    action_markers: list[str] = []
    for trace in trace_files[:3]:
        if trace.suffix == ".zip":
            try:
                with zipfile.ZipFile(trace) as zf:
                    names = zf.namelist()
                    action_markers.extend([n for n in names if "trace" in n.lower() or "network" in n.lower()][:10])
                    trace_has_actions = bool(action_markers)
            except Exception:
                pass
    return {
        "available": bool(trace_files),
        "signal": "playwright_trace_replay",
        "changed": timing_score > 0,
        "confidence": min(0.9, 0.35 + (timing_score * 0.09)) if timing_score else (0.25 if trace_files else 0.0),
        "trace_files": [_rel(p, root) for p in trace_files[:10]],
        "action_timing_indicators": timing_score,
        "trace_action_markers_seen": trace_has_actions,
        "note": "Trace artifacts are indexed for RCA; open the trace from the report for visual replay when confidence is low.",
    }


def _history() -> list[dict[str, Any]]:
    data = _json_read(HISTORY_JSON, [])
    return data if isinstance(data, list) else []


def record_execution_history(root: Path, inventory: dict[str, Any], execution: dict[str, Any] | None = None) -> dict[str, Any]:
    _ensure()
    history = _history()
    record = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "framework_path": str(root),
        "ok": bool((execution or {}).get("ok", inventory.get("failed_count", 1) == 0)),
        "all_specs": inventory.get("all_specs") or [],
        "failed_specs": inventory.get("failed_specs") or [],
        "passed_specs": inventory.get("passed_specs") or [],
    }
    history.append(record)
    history = history[-200:]
    _write_json(HISTORY_JSON, history)
    if not record["failed_specs"] and record["all_specs"]:
        _write_json(BASELINE_DIR / "last-passed-fixtures.json", _current_fixture_snapshot(root))
        # Copy latest DOM and HAR as baseline metadata if available.
        latest_dom = _walk_recent(root, ["*.dom.html", "*.dom.json", "dom-*.html", "dom-*.json", "*dom-snapshot*.html", "*dom-snapshot*.json"], limit=10)
        latest_har = _walk_recent(root, ["*.har"], limit=10)
        _write_json(BASELINE_DIR / "last-passed-artifacts.json", {"dom": [_rel(p, root) for p in latest_dom], "har": [_rel(p, root) for p in latest_har], "timestamp": record["timestamp"]})
    return {"history_count": len(history), "baseline_updated": not record["failed_specs"] and bool(record["all_specs"])}


def _flakiness_signal(root: Path, failed_specs: list[str]) -> dict[str, Any]:
    history = [h for h in _history() if h.get("framework_path") == str(root)]
    spec_stats: dict[str, dict[str, int]] = defaultdict(lambda: {"runs": 0, "failures": 0, "passes": 0})
    for h in history[-60:]:
        failed = set(str(x) for x in h.get("failed_specs") or [])
        all_specs = set(str(x) for x in h.get("all_specs") or []) | failed
        passed = set(str(x) for x in h.get("passed_specs") or [])
        all_specs |= passed
        for spec in all_specs:
            spec_stats[spec]["runs"] += 1
            if spec in failed:
                spec_stats[spec]["failures"] += 1
            elif spec in passed or spec not in failed:
                spec_stats[spec]["passes"] += 1
    details = []
    for spec in failed_specs:
        s = spec_stats.get(spec, {"runs": 0, "failures": 0, "passes": 0})
        runs = max(1, s["runs"])
        details.append({"spec": spec, **s, "failure_rate": round(s["failures"] / runs, 3)})
    intermittent = [d for d in details if d["runs"] >= 3 and 0 < d["failure_rate"] < 0.8]
    consistent = [d for d in details if d["runs"] >= 3 and d["failure_rate"] >= 0.8]
    return {
        "available": bool(history),
        "signal": "cross_run_flakiness_frequency",
        "changed": bool(intermittent or consistent),
        "confidence": 0.86 if intermittent else (0.76 if consistent else (0.30 if history else 0.0)),
        "history_runs_seen": len(history),
        "failed_spec_stats": details,
        "intermittent_flake_candidates": intermittent,
        "consistent_regression_candidates": consistent,
    }


def _extract_assertion_pairs(text: str) -> list[dict[str, str]]:
    pairs: list[dict[str, str]] = []
    patterns = [
        r"Expected\s*(?:string|value|text)?\s*[:=]?\s*['\"]?([^\n'\"]{1,200})['\"]?\s*(?:Received|Actual)\s*[:=]?\s*['\"]?([^\n'\"]{1,200})",
        r"expect\([^\)]*\)\.(?:toHaveText|toContainText|toHaveURL|toHaveValue)[\s\S]{0,300}?Expected[^\n:]*:\s*([^\n]+)\n\s*(?:Received|Actual)[^\n:]*:\s*([^\n]+)",
        r"expected\s+([^\n]{1,180})\s+to\s+(?:equal|contain|match)\s+([^\n]{1,180})",
    ]
    for pat in patterns:
        for m in re.finditer(pat, text or "", flags=re.I):
            before = re.sub(r"\s+", " ", m.group(1)).strip(" ' \"`")
            after = re.sub(r"\s+", " ", m.group(2)).strip(" ' \"`")
            if before and after and before != after:
                pairs.append({"expected": before[:220], "received": after[:220]})
    return pairs[:10]


def _token_similarity(a: str, b: str) -> float:
    tokens_a = set(re.findall(r"[a-z0-9]+", (a or "").lower()))
    tokens_b = set(re.findall(r"[a-z0-9]+", (b or "").lower()))
    if not tokens_a or not tokens_b:
        return 0.0
    return len(tokens_a & tokens_b) / len(tokens_a | tokens_b)


def _contains_behavioral_marker(value: str) -> bool:
    return bool(re.search(r"\b(price|amount|total|balance|apr|rate|error|approved|declined|eligible|ineligible|failed|success|cancel|order|payment|policy|permission|security|role|status|id|count|quantity)\b|\d", value or "", flags=re.I))


def _assertion_drift_signal(failure_text: str, threshold: float = 0.30) -> dict[str, Any]:
    pairs = _extract_assertion_pairs(failure_text)
    if not pairs:
        return {"available": False, "signal": "assertion_drift_classifier", "changed": False, "confidence": 0.0, "auto_heal_assertion_allowed": False, "note": "No clear expected/received assertion pair found."}
    decisions = []
    blocked = False
    for p in pairs:
        sim = _token_similarity(p["expected"], p["received"])
        behavioral = _contains_behavioral_marker(p["expected"] + " " + p["received"])
        allow = sim >= threshold and not behavioral
        blocked = blocked or not allow
        decisions.append({**p, "semantic_similarity": round(sim, 3), "behavioral_marker_seen": behavioral, "auto_heal_allowed": allow})
    min_sim = min(d["semantic_similarity"] for d in decisions)
    return {
        "available": True,
        "signal": "assertion_drift_classifier",
        "changed": True,
        "confidence": 0.90,
        "threshold": threshold,
        "auto_heal_assertion_allowed": not blocked,
        "human_review_required": blocked,
        "minimum_similarity": min_sim,
        "decisions": decisions,
        "note": "Assertion patching is blocked when semantic similarity is below threshold or the change looks behavioral/business-critical.",
    }


def collect_multi_signal_evidence(root: Path, failed_specs: list[str], failure_text: str) -> dict[str, Any]:
    _ensure()
    dom_files = _walk_recent(root, ["*.dom.html", "*.dom.json", "dom-*.html", "dom-*.json", "*dom-snapshot*.html", "*dom-snapshot*.json"], limit=10)
    evidence = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "framework_path": str(root),
        "failed_specs": failed_specs,
        "artifact_index": _artifact_index(root),
        "signals": {
            "dom_snapshot_diff": _compare_latest_pair(dom_files, root, "dom_snapshot_diff"),
            "playwright_trace_replay": _trace_replay_signal(root, failure_text),
            "network_har_diff": _har_diff_signal(root),
            "fixture_seed_diff": _fixture_seed_diff_signal(root),
            "cross_run_flakiness_frequency": _flakiness_signal(root, failed_specs),
            "assertion_drift_classifier": _assertion_drift_signal(failure_text, threshold=0.30),
        },
    }
    _write_json(ROBUST_EVIDENCE_JSON, evidence)
    return evidence


def _error_text_classification(failure_text: str) -> dict[str, Any]:
    low = (failure_text or "").lower()
    scores = Counter()
    if any(x in low for x in ["strict mode violation", "locator resolved", "getbyrole", "getbytestid", "waiting for locator", "to be visible"]):
        scores["selector_or_dom_drift"] += 3
    if any(x in low for x in ["intercepts pointer events", "not enabled", "not visible", "outside of the viewport", "detached", "click timeout"]):
        scores["actionability_or_overlay"] += 3
    if any(x in low for x in ["waitforurl", "tohaveurl", "navigation", "networkidle", "load state"]):
        scores["sync_or_navigation_timing"] += 2
    if any(x in low for x in ["net::err", "econnrefused", "dns", "ssl", "proxy", "vpn", "timeout exceeded while connecting"]):
        scores["environment_or_network"] += 3
    if any(x in low for x in ["expect", "expected", "received", "tohavetext", "tocontaintext", "tohaveurl", "toequal"]):
        scores["assertion_drift_or_regression"] += 2
    if not scores:
        return {"class": "unknown_or_insufficient_evidence", "score": 1}
    label, score = scores.most_common(1)[0]
    return {"class": label, "score": score, "all_scores": dict(scores)}


def classify_healing_strategy(evidence: dict[str, Any], failure_text: str) -> dict[str, Any]:
    signals = evidence.get("signals") or {}
    error_class = _error_text_classification(failure_text)
    dom = signals.get("dom_snapshot_diff") or {}
    trace = signals.get("playwright_trace_replay") or {}
    har = signals.get("network_har_diff") or {}
    fixture = signals.get("fixture_seed_diff") or {}
    flaky = signals.get("cross_run_flakiness_frequency") or {}
    assertion = signals.get("assertion_drift_classifier") or {}

    chain: list[dict[str, Any]] = []
    def add(step: str, decision: str, confidence: float, evidence_keys: list[str], auto_patch: bool, strategy: str) -> None:
        chain.append({
            "step": step,
            "decision": decision,
            "confidence": round(confidence, 3),
            "evidence_keys": evidence_keys,
            "auto_patch_candidate": auto_patch,
            "healing_strategy": strategy,
        })

    if har.get("changed") and har.get("confidence", 0) >= 0.80:
        add("Chain 3 - Network/API HAR classifier", "API response/status/schema changed; treat as app/API regression or contract drift before code patching.", har.get("confidence", 0.0), ["network_har_diff"], False, "Block UI locator/assertion patch. Raise PR comment with HAR before/after and validate API contract/test data.")
    if fixture.get("changed") and fixture.get("confidence", 0) >= 0.75:
        add("Chain 4 - Fixture/seed classifier", "Fixture/seed/data changed between passing and failing run.", fixture.get("confidence", 0.0), ["fixture_seed_diff"], False, "Block code patch until fixture/data seed is reconciled or approved.")
    if assertion.get("available") and assertion.get("human_review_required"):
        add("Chain 5 - Assertion drift classifier", "Assertion value drift is below semantic threshold or behavioral; human review required.", assertion.get("confidence", 0.0), ["assertion_drift_classifier"], False, "Do not auto-update assertion. Create PR comment with expected/received and similarity score.")
    if flaky.get("intermittent_flake_candidates"):
        add("Chain 6 - Cross-run flakiness classifier", "Failure is intermittent across historical runs.", flaky.get("confidence", 0.0), ["cross_run_flakiness_frequency", "playwright_trace_replay"], True, "Patch wait/actionability helpers, SmartLocator fallback, overlay handling; avoid business assertion changes.")
    if dom.get("changed") and error_class.get("class") in {"selector_or_dom_drift", "actionability_or_overlay"}:
        add("Chain 1 - DOM snapshot diff classifier", "Markup or selector surface changed and failure text points to locator/actionability.", max(dom.get("confidence", 0.0), 0.82), ["dom_snapshot_diff", "failure_text"], True, "Patch pageObjects/locator vault first; use SmartLocator secondary/tertiary fallback; then page methods.")
    if trace.get("changed") and error_class.get("class") in {"sync_or_navigation_timing", "actionability_or_overlay", "selector_or_dom_drift"}:
        add("Chain 2 - Trace timing classifier", "Trace/failure text indicates action fired too early/late or target not actionable.", max(trace.get("confidence", 0.0), 0.78), ["playwright_trace_replay", "failure_text"], True, "Patch reusable waits, waitForStableDom, safeClick, overlay dismissal, and navigation expectations.")

    if not chain:
        cls = error_class.get("class", "unknown_or_insufficient_evidence")
        auto_patch = cls not in {"environment_or_network", "assertion_drift_or_regression", "unknown_or_insufficient_evidence"}
        add("Fallback - Error text with evidence availability check", f"Primary multi-signal artifacts were incomplete; fallback class is {cls}.", 0.45 if auto_patch else 0.30, ["failure_text", "artifact_index"], auto_patch, "Run with TestTelemetry enabled, collect trace/HAR/DOM, then patch only if evidence confirms locator/timing issue.")

    blockers = [c for c in chain if not c["auto_patch_candidate"]]
    patch_candidates = [c for c in chain if c["auto_patch_candidate"]]
    selected = blockers[0] if blockers else max(patch_candidates, key=lambda c: c["confidence"])
    result = {
        "selected_chain": selected,
        "all_chain_decisions": chain,
        "auto_heal_allowed": bool(selected["auto_patch_candidate"] and selected["confidence"] >= 0.70),
        "confidence": selected["confidence"],
        "human_approval_required": bool(not selected["auto_patch_candidate"] or selected["confidence"] < 0.70),
        "error_text_classification": error_class,
        "confidence_gate": {"minimum_for_patch_proposal": 0.70, "minimum_for_auto_apply_after_diff_review": 0.80},
    }
    _write_rca_chain_docs(evidence, result)
    return result


def _write_rca_chain_docs(evidence: dict[str, Any], strategy: dict[str, Any]) -> None:
    rows = []
    for c in strategy.get("all_chain_decisions") or []:
        rows.append(f"| {c.get('step')} | {c.get('decision')} | {c.get('confidence')} | {'Yes' if c.get('auto_patch_candidate') else 'No'} | {c.get('healing_strategy')} |")
    md = "\n".join([
        "# Auditable Existing-Framework RCA Chain",
        "",
        "This file records evidence-based RCA decisions. It is intentionally an auditable summary, not hidden model chain-of-thought.",
        "",
        f"- Generated: `{evidence.get('generated_at')}`",
        f"- Framework: `{evidence.get('framework_path')}`",
        f"- Failed specs: `{', '.join(evidence.get('failed_specs') or [])}`",
        "",
        "## Selected decision",
        "```json",
        json.dumps(strategy.get("selected_chain"), indent=2, ensure_ascii=False),
        "```",
        "",
        "## Chain matrix",
        "| Chain | Decision | Confidence | Auto patch? | Strategy |",
        "|---|---:|---:|---:|---|".replace("---:", "---"),
        *rows,
        "",
        "## Evidence index",
        "```json",
        json.dumps(evidence.get("artifact_index"), indent=2, ensure_ascii=False),
        "```",
    ]) + "\n"
    ROBUST_CHAIN_MD.write_text(md, encoding="utf-8")
    html_rows = "".join([f"<tr><td>{_h(c.get('step'))}</td><td>{_h(c.get('decision'))}</td><td>{c.get('confidence')}</td><td>{'Yes' if c.get('auto_patch_candidate') else 'No'}</td><td>{_h(c.get('healing_strategy'))}</td></tr>" for c in strategy.get("all_chain_decisions") or []])
    ROBUST_CHAIN_HTML.write_text(f"""<!doctype html><html><head><meta charset='utf-8'><title>Auditable RCA Chain</title><style>body{{font-family:Segoe UI,Arial,sans-serif;margin:24px;background:#f8fafc;color:#0f172a}}.card{{background:white;border:1px solid #dbe3ef;border-radius:14px;padding:16px;margin:14px 0}}table{{border-collapse:collapse;width:100%}}td,th{{border-bottom:1px solid #e2e8f0;padding:8px;text-align:left;vertical-align:top}}code,pre{{background:#0f172a;color:#dbeafe;border-radius:10px;padding:12px;white-space:pre-wrap}}</style></head><body><h1>Auditable Existing-Framework RCA Chain</h1><div class='card'><p>This report is an evidence summary, not hidden model reasoning.</p><b>Framework:</b> <code>{_h(evidence.get('framework_path'))}</code></div><div class='card'><h2>Selected Decision</h2><pre>{_h(json.dumps(strategy.get('selected_chain'), indent=2, ensure_ascii=False))}</pre></div><div class='card'><h2>Chain Matrix</h2><table><tr><th>Chain</th><th>Decision</th><th>Confidence</th><th>Auto Patch?</th><th>Strategy</th></tr>{html_rows}</table></div><div class='card'><h2>Evidence Index</h2><pre>{_h(json.dumps(evidence.get('artifact_index'), indent=2, ensure_ascii=False))}</pre></div></body></html>""", encoding="utf-8")


def build_robust_rca(root: Path, failed_specs: list[str], failure_text: str) -> dict[str, Any]:
    evidence = collect_multi_signal_evidence(root, failed_specs, failure_text)
    strategy = classify_healing_strategy(evidence, failure_text)
    payload = {"evidence": evidence, "strategy": strategy, "reports": {"evidence_json": str(ROBUST_EVIDENCE_JSON), "chain_markdown": str(ROBUST_CHAIN_MD), "chain_html": str(ROBUST_CHAIN_HTML)}}
    return payload


def diff_against_backup(root: Path, backup_root: Path | str, allowed_files: list[str]) -> dict[str, Any]:
    backup_path = Path(backup_root)
    files: dict[str, Any] = {}
    combined: list[str] = []
    for rel in allowed_files:
        before_path = backup_path / rel
        after_path = root / rel
        if not before_path.exists() or not after_path.exists():
            continue
        before = _read(before_path)
        after = _read(after_path)
        if before == after:
            continue
        diff = "".join(difflib.unified_diff(before.splitlines(True), after.splitlines(True), fromfile=f"before/{rel}", tofile=f"after/{rel}", n=4))
        files[rel] = {"changed": True, "diff": diff[-20_000:]}
        combined.append(diff)
    return {"changed_files": list(files.keys()), "file_diffs": files, "combined_diff": "\n".join(combined)[-60_000:]}


def restore_backup(root: Path, backup_root: Path | str, files: list[str]) -> dict[str, Any]:
    restored = []
    backup_path = Path(backup_root)
    for rel in files:
        src = backup_path / rel
        dest = root / rel
        if src.exists():
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
            restored.append(rel)
    return {"restored_files": restored, "count": len(restored)}


def _parse_score(text: str) -> float | None:
    matches = re.findall(r"(?:confidence|score)\D{0,20}([01](?:\.\d+)?)", text or "", flags=re.I)
    values = []
    for m in matches:
        try:
            v = float(m)
            if 0 <= v <= 1:
                values.append(v)
        except Exception:
            pass
    return max(values) if values else None


def review_patch_confidence(root: Path, provider: str, model: str, rca_payload: dict[str, Any], diff_payload: dict[str, Any]) -> dict[str, Any]:
    _ensure()
    changed_files = diff_payload.get("changed_files") or []
    if not changed_files:
        review = {"ok": False, "confidence": 0.0, "human_approval_required": True, "message": "No patch diff detected. Auto-apply is blocked."}
        _write_json(PATCH_REVIEW_JSON, review)
        return review
    provider = (provider or "deterministic").strip().lower()
    selected = (((rca_payload.get("robust_multi_signal_rca") or {}).get("strategy") or {}).get("selected_chain") or {})
    deterministic_score = min(0.92, max(0.0, float(selected.get("confidence") or 0.0)) + 0.05)
    message = "Deterministic diff review: patch is within allowed files and RCA confidence was used as proxy."
    ai_raw = ""
    if provider in {"codex", "ollama"}:
        prompt = f"""
You are the second-stage patch confidence reviewer for a Playwright self-healing system.
Return JSON only with keys: confidence, approve_auto_apply, reasons, risks.

Rules:
- Approve only if the diff is minimal and restricted to failed specs/imported page/pageObject/helper files.
- Reject assertion updates unless assertion_drift_classifier explicitly allowed them.
- Reject broad rewrites, deleting assertions, adding sleeps, or changing unrelated specs.
- Confidence must be 0.0 to 1.0. Auto apply requires >= 0.80.

RCA selected chain:
{json.dumps(selected, indent=2, ensure_ascii=False)}

Assertion drift gate:
{json.dumps((((rca_payload.get('robust_multi_signal_rca') or {}).get('evidence') or {}).get('signals') or {}).get('assertion_drift_classifier'), indent=2, ensure_ascii=False)}

Changed files:
{json.dumps(changed_files, indent=2, ensure_ascii=False)}

Diff:
{diff_payload.get('combined_diff', '')[-50000:]}
""".strip()
        try:
            if provider == "codex":
                res = CodexCliProvider(root, timeout_seconds=240).run(prompt)
                ai_raw = (res.stdout if res.ok else res.stderr)[-12000:]
            else:
                res = OllamaProvider(model=model).chat(prompt)
                ai_raw = (res.text if res.ok else res.error)[-12000:]
            parsed_score = _parse_score(ai_raw)
            if parsed_score is not None:
                deterministic_score = parsed_score
                message = ai_raw
        except Exception as exc:
            ai_raw = f"{type(exc).__name__}: {exc}"
            deterministic_score = min(deterministic_score, 0.79)
            message = "AI confidence review failed safely; human approval required. " + ai_raw
    confidence = round(float(deterministic_score), 3)
    review = {
        "ok": True,
        "provider": provider,
        "confidence": confidence,
        "auto_apply_threshold": 0.80,
        "human_approval_required": confidence < 0.80,
        "approve_auto_apply": confidence >= 0.80,
        "changed_files": changed_files,
        "message": message[-12000:],
        "ai_raw": ai_raw[-12000:],
    }
    _write_json(PATCH_REVIEW_JSON, review)
    return review


def append_feedback(root: Path, rca: dict[str, Any], patch_review: dict[str, Any], diff_payload: dict[str, Any], accepted: bool, source: str = "auto") -> dict[str, Any]:
    _ensure()
    record = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "framework_path": str(root),
        "accepted": bool(accepted),
        "source": source,
        "confidence": patch_review.get("confidence"),
        "failed_specs": rca.get("failed_specs") or [],
        "selected_chain": (((rca.get("robust_multi_signal_rca") or {}).get("strategy") or {}).get("selected_chain") or {}),
        "changed_files": diff_payload.get("changed_files") or [],
        "summary_hash": _hash_text(json.dumps({"rca": rca.get("signals"), "diff": diff_payload.get("combined_diff", "")[:20000]}, ensure_ascii=False)),
    }
    FEEDBACK_JSONL.parent.mkdir(parents=True, exist_ok=True)
    with FEEDBACK_JSONL.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    vault = _json_read(SELECTOR_VAULT_JSON, {"entries": []})
    entries = vault.get("entries") if isinstance(vault, dict) else []
    if not isinstance(entries, list):
        entries = []
    if accepted:
        entries.append(record)
        entries = entries[-500:]
    _write_json(SELECTOR_VAULT_JSON, {"updated_at": datetime.now().isoformat(timespec="seconds"), "entries": entries})
    return {"feedback_jsonl": str(FEEDBACK_JSONL), "selector_vault_json": str(SELECTOR_VAULT_JSON), "vault_entries": len(entries)}


def _h(value: Any) -> str:
    return str(value if value is not None else "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def generate_selector_health_report(root: Path | None = None) -> dict[str, Any]:
    _ensure()
    history = _history()
    feedback_records = []
    if FEEDBACK_JSONL.exists():
        for line in FEEDBACK_JSONL.read_text(encoding="utf-8", errors="replace").splitlines()[-500:]:
            try:
                feedback_records.append(json.loads(line))
            except Exception:
                pass
    by_spec: dict[str, dict[str, Any]] = defaultdict(lambda: {"runs": 0, "failures": 0, "heals": 0})
    for h in history[-100:]:
        if root and h.get("framework_path") != str(root):
            continue
        all_specs = set(h.get("all_specs") or []) | set(h.get("failed_specs") or []) | set(h.get("passed_specs") or [])
        failed = set(h.get("failed_specs") or [])
        for spec in all_specs:
            by_spec[spec]["runs"] += 1
            if spec in failed:
                by_spec[spec]["failures"] += 1
    for f in feedback_records:
        if root and f.get("framework_path") != str(root):
            continue
        for spec in f.get("failed_specs") or []:
            by_spec[spec]["heals"] += 1
    components = []
    for spec, stats in by_spec.items():
        runs = max(1, stats["runs"])
        failure_rate = stats["failures"] / runs
        heal_rate = stats["heals"] / runs
        stability = max(0.0, 1.0 - failure_rate - min(0.4, heal_rate / 2))
        components.append({"component_or_spec": spec, **stats, "failure_rate": round(failure_rate, 3), "heal_rate": round(heal_rate, 3), "stability_score": round(stability, 3)})
    components = sorted(components, key=lambda x: (x["stability_score"], -x["heals"]))
    summary = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "framework_path": str(root) if root else "all",
        "history_runs_seen": len(history),
        "feedback_records_seen": len(feedback_records),
        "component_scores": components,
        "shortlist_for_testability_improvement": [c for c in components if c["stability_score"] < 0.80 or c["heals"] >= 2][:20],
        "trend": {
            "last_10_runs_failed_specs": [len(h.get("failed_specs") or []) for h in history[-10:]],
            "last_10_heal_confidences": [r.get("confidence") for r in feedback_records[-10:]],
        },
    }
    _write_json(SELECTOR_HEALTH_JSON, summary)
    rows = "".join([f"<tr><td>{_h(c['component_or_spec'])}</td><td>{c['runs']}</td><td>{c['failures']}</td><td>{c['heals']}</td><td>{c['stability_score']}</td></tr>" for c in components[:200]])
    shortlist = "".join([f"<li><code>{_h(c['component_or_spec'])}</code> — stability {c['stability_score']}, heals {c['heals']}, failures {c['failures']}</li>" for c in summary["shortlist_for_testability_improvement"]]) or "<li>No unstable components detected yet.</li>"
    SELECTOR_HEALTH_HTML.write_text(f"""<!doctype html><html><head><meta charset='utf-8'><title>Selector Health Report</title><style>body{{font-family:Segoe UI,Arial,sans-serif;margin:24px;background:#f8fafc;color:#0f172a}}.card{{background:white;border:1px solid #dbe3ef;border-radius:14px;padding:16px;margin:14px 0}}table{{border-collapse:collapse;width:100%}}td,th{{border-bottom:1px solid #e2e8f0;padding:8px;text-align:left}}code{{background:#0f172a;color:#dbeafe;padding:3px 6px;border-radius:6px}}</style></head><body><h1>Nightly Selector Health Report</h1><div class='card'><b>Framework:</b> <code>{_h(summary['framework_path'])}</code><p>Runs seen: {summary['history_runs_seen']} | Feedback records: {summary['feedback_records_seen']}</p></div><div class='card'><h2>Shortlist for Dev Testability Improvements</h2><ul>{shortlist}</ul></div><div class='card'><h2>Component Stability Scores</h2><table><tr><th>Component/Spec</th><th>Runs</th><th>Failures</th><th>Heals</th><th>Stability</th></tr>{rows}</table></div></body></html>""", encoding="utf-8")
    return {"ok": True, "report_json": str(SELECTOR_HEALTH_JSON), "report_html": str(SELECTOR_HEALTH_HTML), "url": "/artifacts/reports/existing-framework/selector-health-report.html", **summary}
