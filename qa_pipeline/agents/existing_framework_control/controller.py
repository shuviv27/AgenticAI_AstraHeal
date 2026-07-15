from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
import platform
import urllib.parse
from collections import Counter
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from qa_pipeline.core.commands import resolve_command, run_command
from qa_pipeline.core.paths import QA_CACHE_DIR, GENERATED_PLAYWRIGHT_DIR, REPORTS_DIR, REPO_ROOT
from qa_pipeline.core.runtime_logger import log_event
from qa_pipeline.core.url_guard import normalize_base_url
from qa_pipeline.core.tsconfig_alias import load_jsonc, runtime_env_for_tsconfig_aliases, tsconfig_alias_summary
from qa_pipeline.llm.codex_cli import CodexCliProvider
from qa_pipeline.llm.ollama import OllamaProvider
from qa_pipeline.llm.openai_compatible import OpenAICompatibleProvider
from qa_pipeline.agents.phase5_failure_healing.healing_policy import load_healing_policy, policy_summary_for_prompt, validate_patch_diff
from qa_pipeline.agents.existing_framework_control.robust_rca import (
    append_feedback,
    build_robust_rca,
    diff_against_backup,
    generate_selector_health_report as generate_robust_selector_health_report,
    record_execution_history,
    restore_backup,
    review_patch_confidence,
)
from qa_pipeline.agents.existing_framework_control.framework_intelligence import (
    build_framework_intelligence_v2,
    query_framework_context,
    plain_english_failure_report,
)
from qa_pipeline.agents.existing_framework_control.mcp_locator_rca import build_mcp_assisted_locator_rca
from qa_pipeline.agents.existing_framework_control.deep_framework_agents import build_deep_framework_understanding, load_deep_framework_memory
from qa_pipeline.mcp.playwright_mcp import mcp_status, write_playwright_mcp_configs
from qa_pipeline.core.human_intervention import create_human_intervention_request, read_human_intervention_memory, save_human_intervention_update
from qa_pipeline.mcp.external_fix_research import collect_external_fix_research, ensure_external_research_config
from qa_pipeline.agents.existing_framework_control.structure_discovery import (
    EXECUTABLE_SPEC_SUFFIXES as STRUCTURE_EXECUTABLE_SPEC_SUFFIXES,
    build_structure_profile,
    classify_spec_candidate,
    discover_configured_test_dirs,
    executable_spec_paths,
)

EXISTING_CACHE_DIR = QA_CACHE_DIR / "existing-framework"
EXISTING_REPORTS_DIR = REPORTS_DIR / "existing-framework"
EXISTING_HTML_DIR = EXISTING_REPORTS_DIR / "html"
EXISTING_RESULTS_JSON = EXISTING_REPORTS_DIR / "results.json"
EXISTING_INVENTORY_JSON = EXISTING_REPORTS_DIR / "failed-tests.json"
EXISTING_INTELLIGENCE_JSON = EXISTING_REPORTS_DIR / "framework-intelligence.json"
EXISTING_INTELLIGENCE_MD = EXISTING_REPORTS_DIR / "framework-intelligence.md"
EXISTING_ALIGNMENT_HTML = EXISTING_REPORTS_DIR / "playwright-framework-alignment.html"
EXISTING_ALIGNMENT_JSON = EXISTING_REPORTS_DIR / "playwright-framework-alignment.json"
EXISTING_RCA_JSON = EXISTING_REPORTS_DIR / "root-cause-report.json"
EXISTING_SELF_HEAL_JSON = EXISTING_REPORTS_DIR / "self-healing-report.json"
EXISTING_PLAIN_FAILURE_JSON = EXISTING_REPORTS_DIR / "plain-english-failure-report.json"
EXISTING_PLAIN_FAILURE_HTML = EXISTING_REPORTS_DIR / "plain-english-failure-report.html"
EXISTING_PENDING_JSON = EXISTING_CACHE_DIR / "failed-only-pending.json"
EXISTING_COMMON_CAUSE_MEMORY_JSON = EXISTING_CACHE_DIR / "common-cause-memory.json"
EXISTING_COMMON_CAUSE_MEMORY_HTML = EXISTING_REPORTS_DIR / "common-cause-memory.html"
EXISTING_BACKUP_DIR = EXISTING_CACHE_DIR / "backups"
EXISTING_OBJECT_REPO_LOCATOR_AUDIT_JSON = EXISTING_REPORTS_DIR / "object-repository-locator-audit.json"
EXISTING_OBJECT_REPO_LOCATOR_AUDIT_HTML = EXISTING_REPORTS_DIR / "object-repository-locator-audit.html"
EXISTING_FIRST_RUN_BASELINE_JSON = EXISTING_REPORTS_DIR / "first-run-baseline-inventory.json"
EXISTING_RERUN_LEDGER_JSON = EXISTING_REPORTS_DIR / "failed-only-rerun-ledger.json"
EXISTING_FAILED_ONLY_LATEST_REPORT_HTML = EXISTING_REPORTS_DIR / "failed-only-latest-playwright-report.html"
EXISTING_LATEST_PLAYWRIGHT_ROUTER_HTML = EXISTING_REPORTS_DIR / "latest-playwright-report.html"

IGNORED_DIRS = {"node_modules", ".git", "reports", "playwright-report", "test-results", "dist", "build", ".next", "coverage", ".codex-backups", ".aiqa-history", "%appdata%", "%AppData%", ".npm", "npm-cache"}


def _astraheal_max_wait_ms() -> int:
    """Central guardrail for browser idle/default waits during AstraHeal runs.

    The enterprise default is capped at 30 seconds so a hidden/blocked locator
    does not keep the browser idle for minutes.  Teams may lower it with
    ASTRAHEAL_MAX_EXPLICIT_WAIT_MS or ASTRAHEAL_MAX_TEST_TIMEOUT_MS, but values
    above 30000 are intentionally capped.
    """
    raw = os.environ.get("ASTRAHEAL_MAX_EXPLICIT_WAIT_MS") or os.environ.get("ASTRAHEAL_MAX_TEST_TIMEOUT_MS") or "30000"
    try:
        value = int(float(str(raw).strip()))
    except Exception:
        value = 30000
    return max(5000, min(value, 30000))

def _append_playwright_timeout_arg(cmd: list[str]) -> list[str]:
    """Append AstraHeal Playwright runtime guards when safe.

    This keeps execution fast and predictable: max test timeout is capped at
    30 seconds and retries are clamped to one unless the user's custom command
    explicitly supplies a different value.
    """
    lowered = [str(c).lower() for c in cmd]
    if not ("playwright" in lowered and "test" in lowered):
        return cmd
    out = [*cmd]
    if not any(c == "--timeout" or c.startswith("--timeout=") for c in lowered):
        out.append(f"--timeout={_astraheal_max_wait_ms()}")
    if not any(c == "--retries" or c.startswith("--retries=") for c in lowered):
        out.append("--retries=1")
    return out
EXECUTABLE_SPEC_SUFFIXES = STRUCTURE_EXECUTABLE_SPEC_SUFFIXES
FEATURE_SUFFIXES = (".feature",)
# Broad suffix list is retained for manual/legacy Cucumber workflows, failed-output
# parsing and framework scoring. GUI discovery and normal Playwright execution now
# use EXECUTABLE_SPEC_SUFFIXES from recursively proven Playwright test locations, not only root
# tests/**. This supports enterprise layouts such as src/test/specs/** while
# still excluding backups, generated reports, node_modules and history folders.
SPEC_SUFFIXES = (*EXECUTABLE_SPEC_SUFFIXES, *FEATURE_SUFFIXES)
TS_SUFFIXES = {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"}

IGNORED_EXECUTION_PARTS = {"node_modules", ".git", "reports", "playwright-report", "test-results", "dist", "build", ".next", "coverage", ".codex-backups", ".aiqa-history", ".qa-cache", "generated-playwright"}
DEFAULT_EXECUTABLE_TEST_ROOTS = (
    "tests",
    "src/test/specs",
    "src/test",
    "src/tests",
    "test/specs",
    "test",
    "specs",
    "e2e",
    "integration",
)


def _ensure_dirs() -> None:
    EXISTING_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    EXISTING_REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    EXISTING_HTML_DIR.mkdir(parents=True, exist_ok=True)


def existing_framework_artifact_locations(framework_path: str = "") -> dict[str, Any]:
    """Return absolute local storage paths for reports, RCA, healing and logs.

    Browser URLs are useful while the GUI is running, but users also need to
    know where artifacts live on the Windows/local VM filesystem.  This report
    deliberately distinguishes AstraHeal's central retained copy from the
    client framework's native Playwright output folder.
    """
    _ensure_dirs()
    root: Path | None = None
    raw = str(framework_path or "").strip().strip('"').strip("'")
    if raw:
        try:
            root = _resolve_framework_path(raw)
        except Exception:
            try:
                root = Path(raw).expanduser().resolve()
            except Exception:
                root = None

    def item(path: Path, purpose: str) -> dict[str, Any]:
        return {
            "path": str(path.resolve()),
            "exists": path.exists(),
            "purpose": purpose,
        }

    central = {
        "latest_playwright_router": item(EXISTING_LATEST_PLAYWRIGHT_ROUTER_HTML, "Stage-aware link to the latest first-run or failed-only Playwright report."),
        "native_playwright_copy": item(EXISTING_HTML_DIR / "index.html", "Central retained copy of the latest native Playwright HTML report."),
        "combined_first_run_rerun": item(EXISTING_REPORTS_DIR / "consolidated-report.html", "Combined first-run and failed-only rerun ledger."),
        "plain_english_rca_html": item(EXISTING_PLAIN_FAILURE_HTML, "Explainable test-by-test Plain English RCA report."),
        "plain_english_rca_json": item(EXISTING_PLAIN_FAILURE_JSON, "Structured Plain English RCA data."),
        "root_cause_html": item(EXISTING_REPORTS_DIR / "root-cause-report.html", "Detailed RCA evidence and auditable checklist."),
        "root_cause_json": item(EXISTING_RCA_JSON, "Structured root-cause analysis."),
        "self_healing_html": item(EXISTING_REPORTS_DIR / "self-healing-report.html", "Safe-fix proposal/apply result, impacted files, backup and rollback details."),
        "self_healing_json": item(EXISTING_SELF_HEAL_JSON, "Structured self-healing result."),
        "failed_inventory": item(EXISTING_INVENTORY_JSON, "Latest failed specs and failed test cases used by RCA and failed-only rerun."),
        "execution_report": item(EXISTING_REPORTS_DIR / "execution-report.json", "Latest execution command, exit code and artifact evidence."),
        "report_manifest": item(EXISTING_REPORTS_DIR / "report-manifest.json", "Stage-aware report links and latest report pointers."),
        "common_cause_memory": item(EXISTING_COMMON_CAUSE_MEMORY_JSON, "Recurring shared failure signatures."),
        "runtime_events": item(QA_CACHE_DIR / "runtime" / "runtime-events.jsonl", "Append-only runtime progress and diagnostic events."),
        "runtime_status": item(QA_CACHE_DIR / "runtime" / "current-status.json", "Latest runtime stage/status."),
        "ai_action_history": item(QA_CACHE_DIR / "ai-memory" / "action-history.jsonl", "Observable AI action and patch history."),
        "human_intervention_memory": item(QA_CACHE_DIR / "existing-framework" / "human-intervention" / "human-intervention-memory.jsonl", "Human approval, guidance and approved-file memory."),
        "backup_root": item(EXISTING_BACKUP_DIR, "Timestamped backups created before approved self-healing changes."),
    }

    framework_native: list[dict[str, Any]] = []
    if root is not None:
        for path, purpose in [
            (root / "playwright-report" / "index.html", "Playwright default native HTML location when the framework does not override outputFolder."),
            (root / "reports" / "existing-framework" / "html" / "index.html", "AstraHeal-compatible native HTML location inside the selected framework."),
            (root / "reports" / "html-report" / "index.html", "Alternative framework HTML reporter location."),
            (root / "test-results", "Native Playwright traces, screenshots, videos and attachments."),
            (root / "reports" / "existing-framework" / "test-results", "AstraHeal-compatible test-results location inside the framework."),
            (root / "reports" / "existing-framework" / "execution-console.log", "Exact streamed Playwright command output for the latest local/sequential execution."),
        ]:
            framework_native.append(item(path, purpose))

    return {
        "ok": True,
        "astraheal_install_root": str(REPO_ROOT.resolve()),
        "selected_framework_root": str(root) if root is not None else "",
        "central_report_root": str(EXISTING_REPORTS_DIR.resolve()),
        "central_cache_root": str(QA_CACHE_DIR.resolve()),
        "existing_framework_cache_root": str(EXISTING_CACHE_DIR.resolve()),
        "central_artifacts": central,
        "framework_native_candidates": framework_native,
        "explanation": {
            "playwright": "Playwright first writes its native report under the selected framework. AstraHeal then copies/retains the latest report under generated-playwright/reports/existing-framework so GUI links remain stable.",
            "rca_self_healing": "RCA and self-healing reports are retained centrally under generated-playwright/reports/existing-framework; supporting memory, runtime logs and backups are under .qa-cache.",
        },
    }


def _safe_str(value: Any, limit: int = 12000) -> str:
    text = str(value if value is not None else "")
    return text[-limit:]


def _rel_to(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")
    except Exception:
        return str(path).replace("\\", "/")


def _has_playwright_config(path: Path) -> bool:
    return any((path / name).exists() for name in [
        "playwright.config.ts", "playwright.config.js", "playwright.config.mjs", "playwright.config.cjs",
        "playwright.config.mts", "playwright.config.cts",
    ])


def _quick_spec_count(path: Path, limit: int = 80) -> int:
    count = 0
    for spec in path.rglob("*"):
        if count >= limit:
            break
        if not spec.is_file():
            continue
        parts = {p.lower() for p in spec.parts}
        if parts.intersection({"node_modules", ".git", "playwright-report", "test-results", "dist", "build"}):
            continue
        if spec.name.lower().endswith(SPEC_SUFFIXES):
            count += 1
    return count


def _score_framework_root(path: Path) -> int:
    score = 0
    if (path / "package.json").exists():
        score += 40
    if _has_playwright_config(path):
        score += 70
    if (path / "tests").exists():
        score += 25
    if (path / "features").exists():
        score += 25
    if (path / "cucumber.js").exists() or (path / "cucumber.mjs").exists() or (path / "cucumber.cjs").exists():
        score += 70
    if (path / "src" / "step-definitions").exists() or (path / "step-definitions").exists():
        score += 18
    if (path / "pages").exists():
        score += 12
    if (path / "pageObjects").exists() or (path / "pageobjects").exists() or (path / "page-objects").exists():
        score += 12
    score += min(60, _quick_spec_count(path, limit=60) * 3)
    return score


def _auto_select_framework_root(path: Path) -> Path:
    """Return the best Playwright framework root under the user-provided folder.

    Users often paste a parent repo folder instead of the exact Playwright framework
    root.  This helper keeps the GUI simple: the AI scans the provided folder and
    picks the nearest folder that has package.json/playwright.config/tests specs.
    """
    candidates = [path]
    max_depth = 8
    base_parts = len(path.parts)
    for child in path.rglob("*"):
        if not child.is_dir():
            continue
        rel_parts = len(child.parts) - base_parts
        if rel_parts > max_depth:
            continue
        if any(part.lower() in {"node_modules", ".git", "dist", "build", "playwright-report", "test-results", "coverage", "log", "logs", "tmp"} for part in child.parts):
            continue
        # Enterprise repos often keep the Playwright framework several folders
        # below the selected parent.  Treat package/config/tests/spec evidence as
        # candidate roots, but final scoring still prefers package+config roots
        # over a raw tests folder.
        if (child / "package.json").exists() or _has_playwright_config(child) or (child / "tests").exists() or _quick_spec_count(child, limit=10) > 0:
            candidates.append(child)
    ranked = sorted((( _score_framework_root(c), c) for c in candidates), key=lambda x: (x[0], -len(x[1].parts)), reverse=True)
    best_score, best = ranked[0]
    # Keep original folder if no meaningful Playwright evidence was found.
    return best if best_score >= 45 else path


def _resolve_framework_path(framework_path: str) -> Path:
    raw = (framework_path or "").strip().strip('"').strip("'")
    if not raw:
        raise ValueError("Framework path is required. Paste the root folder of the existing Playwright TypeScript framework.")
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = (REPO_ROOT / path).resolve()
    else:
        path = path.resolve()
    if not path.exists() or not path.is_dir():
        raise ValueError(f"Framework path does not exist or is not a directory: {path}")
    selected = _auto_select_framework_root(path)
    if selected != path:
        log_event("existing_framework", "AI auto-detected the actual Playwright framework root under the provided folder.", status="warning", progress=10, details={"provided_path": str(path), "selected_framework_root": str(selected)})
    return selected


def _path_under_test_area(parts: tuple[str, ...] | list[str]) -> bool:
    rel = "/".join(str(p).lower() for p in parts if str(p))
    return (
        rel.startswith("tests/")
        or rel.startswith("src/test/")
        or rel.startswith("src/tests/")
        or rel.startswith("test/")
        or rel.startswith("specs/")
        or rel.startswith("e2e/")
        or "/src/test/" in ("/" + rel + "/")
        or "/tests/" in ("/" + rel + "/")
    )


def _is_ignored(path: Path, root: Path) -> bool:
    try:
        parts = path.relative_to(root).parts
    except Exception:
        parts = path.parts
    parts_low = [str(p).lower() for p in parts]
    under_test_area = _path_under_test_area(parts_low)
    for p in parts_low:
        if p in IGNORED_DIRS:
            # A business module can legitimately be named reports, e.g.
            # src/test/specs/reports/reporting.spec.ts. Do not treat that as a
            # generated reports folder when it is inside the executable test tree.
            if p == "reports" and under_test_area:
                continue
            return True
    return False


def _find_files(root: Path, suffixes: tuple[str, ...] | set[str], limit: int = 5000) -> list[Path]:
    """Fast recursive file search that prunes ignored enterprise folders.

    Path.rglob() still walks inside ignored directories before filtering them.
    That is slow for real Playwright repos with node_modules, reports, test-results
    or generated cache folders.  os.walk lets us prune those directories before
    descent, keeping Deep Learn and Find Scripts responsive.
    """
    files: list[Path] = []
    root = Path(root)
    for current, dirs, names in os.walk(root):
        base = Path(current)
        kept_dirs = []
        for d in dirs:
            dlow = d.lower()
            rel_parts = []
            try:
                rel_parts = list((base / d).relative_to(root).parts)
            except Exception:
                rel_parts = [d]
            if dlow in IGNORED_DIRS and not (dlow == "reports" and _path_under_test_area(rel_parts)):
                continue
            kept_dirs.append(d)
        dirs[:] = kept_dirs
        for name0 in names:
            if len(files) >= limit:
                break
            path = base / name0
            if not path.is_file() or _is_ignored(path, root):
                continue
            name = path.name.lower()
            if isinstance(suffixes, tuple):
                if name.endswith(suffixes):
                    files.append(path)
            elif path.suffix.lower() in suffixes:
                files.append(path)
        if len(files) >= limit:
            break
    return sorted(files, key=lambda p: _rel_to(p, root))


def _strip_playwright_line_selector(target: Any) -> str:
    """Return only the spec-file part from a Playwright CLI target.

    The GUI can now pass either a spec file, for example
    ``tests/ui/login.spec.ts``, or an individual test selector, for example
    ``tests/ui/login.spec.ts:42``.  Discovery and safety checks must validate
    the underlying spec path without losing the exact selector used by the CLI.
    """
    text = str(target or "").replace("\\", "/").strip().strip('"\'`').lstrip("/")
    return re.sub(r"(\.(?:specs|spec|test)\.(?:ts|tsx|js|jsx|mjs|cjs))(?::\d+){1,2}$", r"\1", text, flags=re.I)


def _is_playwright_line_selector(target: Any) -> bool:
    return bool(re.search(r"\.(?:specs|spec|test)\.(?:ts|tsx|js|jsx|mjs|cjs):\d+(?::\d+)?$", str(target or "").replace("\\", "/"), flags=re.I))


def _clean_rel_for_execution(rel_path: Any) -> str:
    return _strip_playwright_line_selector(rel_path).replace("\\", "/").strip().strip("'\"").lstrip("/")


def _has_blocked_execution_part(rel_path: str) -> bool:
    parts = [p.lower() for p in str(rel_path or "").replace("\\", "/").split("/") if p]
    under_test_area = _path_under_test_area(parts)
    for p in parts:
        if p in IGNORED_EXECUTION_PARTS:
            if p == "reports" and under_test_area:
                continue
            return True
    return False


def _looks_like_enterprise_test_root(rel_path: str) -> bool:
    """Return true for recognized executable Playwright test areas.

    Root ``tests/**`` remains supported, and enterprise nested structures such as
    ``src/test/specs/**`` are now first-class.  The function deliberately avoids
    accepting backup/history/report folders even if they contain a nested tests
    directory.
    """
    rel = str(rel_path or "").replace("\\", "/").strip().strip("/").lower()
    if not rel:
        return False
    for prefix in DEFAULT_EXECUTABLE_TEST_ROOTS:
        prefix = prefix.strip("/").lower()
        if rel == prefix or rel.startswith(prefix + "/"):
            return True
    wrapped = "/" + rel + "/"
    # Monorepo/package support: packages/app/src/test/specs/foo.spec.ts,
    # apps/web/tests/foo.spec.ts, etc.  Backups/reports are already blocked.
    enterprise_markers = ("/src/test/specs/", "/src/test/", "/tests/", "/test/specs/", "/specs/", "/e2e/")
    return any(marker in wrapped for marker in enterprise_markers)


def _is_tests_folder_executable_spec(rel_path: str, root: Path | None = None) -> bool:
    """True for executable Playwright spec/test targets discovered safely.

    Legacy root ``tests/**`` and nested ``src/test/specs/**`` paths remain
    first-class. When ``root`` is provided, unusual enterprise locations are
    also accepted only when Playwright configuration or executable test content
    proves that the file is runnable.
    """
    rel = _clean_rel_for_execution(rel_path)
    low = rel.lower()
    if not low.endswith(EXECUTABLE_SPEC_SUFFIXES):
        return False
    if _has_blocked_execution_part(low):
        return False
    if _looks_like_enterprise_test_root(low):
        return True
    if root is not None:
        try:
            return bool(classify_spec_candidate(Path(root).resolve(), rel).get("accepted"))
        except Exception:
            return False
    return False


def _configured_playwright_test_dirs(root: Path) -> list[str]:
    """Discover configured Playwright test roots plus compatible defaults.

    The structure scanner understands literal ``testDir`` values, path.join /
    path.resolve expressions and simple variables used by enterprise configs.
    """
    candidates = [*discover_configured_test_dirs(root), *DEFAULT_EXECUTABLE_TEST_ROOTS]
    seen: set[str] = set()
    out: list[str] = []
    for c in candidates:
        c = str(c or "").replace("\\", "/").strip().strip("/")
        if not c or _has_blocked_execution_part(c):
            continue
        key = c.lower()
        if key not in seen:
            out.append(c)
            seen.add(key)
    return out


def _discover_executable_test_roots(root: Path, rel_specs: list[str] | None = None) -> list[str]:
    rel_specs = rel_specs or []
    try:
        profiled_roots = list(build_structure_profile(root, limit=5000).get("discovered_test_roots") or [])
    except Exception:
        profiled_roots = []
    roots = [*_configured_playwright_test_dirs(root), *profiled_roots]
    # If no configured/common root exists, add the highest approved parent folder
    # from discovered specs so unusual monorepos are still explainable.
    existing_common = [r for r in roots if (root / r).exists()]
    if not existing_common:
        for spec in rel_specs:
            spec = _clean_rel_for_execution(spec)
            parts = spec.split("/")[:-1]
            for idx in range(len(parts), 0, -1):
                cand = "/".join(parts[:idx])
                if cand and _looks_like_enterprise_test_root(cand + "/x.spec.ts"):
                    roots.append(cand)
                    break
    seen: set[str] = set()
    out: list[str] = []
    for r in roots:
        key = r.lower().strip("/")
        if key and key not in seen and (root / r).exists():
            out.append(r.strip("/")); seen.add(key)
    return out


def _find_executable_tests_under_tests(root: Path, limit: int = 5000) -> list[Path]:
    """Recursively find executable Playwright specs in any proven test layout."""
    return executable_spec_paths(Path(root).resolve(), limit=limit)


def _load_package_json(root: Path) -> dict[str, Any]:
    path = root / "package.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception as exc:
        return {"_error": f"{type(exc).__name__}: {exc}"}


def _detect_package_manager(root: Path) -> str:
    if (root / "pnpm-lock.yaml").exists():
        return "pnpm"
    if (root / "yarn.lock").exists():
        return "yarn"
    return "npm"


def _playwright_config_files(root: Path) -> list[str]:
    names = [
        "playwright.config.ts",
        "playwright.config.js",
        "playwright.config.mjs",
        "playwright.config.cjs",
        "playwright.config.mts",
        "playwright.config.cts",
    ]
    return [_rel_to(root / name, root) for name in names if (root / name).exists()]


def _likely_dirs(root: Path) -> dict[str, list[str]]:
    """Return structure-aware component folders from the recursive profile."""
    try:
        profile = build_structure_profile(Path(root).resolve(), limit=5000)
        model = profile.get("component_directory_model") or {}
        return {
            "spec_dirs": list(model.get("spec_dirs") or profile.get("discovered_test_roots") or [])[:200],
            "page_dirs": list(model.get("page_dirs") or [])[:200],
            "page_object_dirs": list(model.get("page_object_dirs") or [])[:200],
            "config_dirs": list(model.get("config_dirs") or [])[:200],
            "api_dirs": list(model.get("api_dirs") or [])[:200],
            "ui_base_dirs": list(model.get("ui_base_dirs") or [])[:200],
            "fixture_dirs": list(model.get("fixture_dirs") or [])[:200],
            "test_data_dirs": list(model.get("test_data_dirs") or [])[:200],
            "utility_dirs": list(model.get("utility_dirs") or [])[:200],
            "reporter_dirs": list(model.get("reporter_dirs") or [])[:200],
        }
    except Exception:
        # Safe compatibility fallback. Deep discovery errors must never block
        # the existing deterministic framework workflow.
        return {
            "spec_dirs": [], "page_dirs": [], "page_object_dirs": [],
            "config_dirs": [], "api_dirs": [], "ui_base_dirs": [],
            "fixture_dirs": [], "test_data_dirs": [], "utility_dirs": [],
            "reporter_dirs": [],
        }


def _read(path: Path, limit: int = 200000) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")[:limit]
    except Exception:
        return ""


def _strip_js_ts_comments_for_scan(text: str) -> str:
    """Mask comments while preserving line numbers for test-title discovery."""
    if not text:
        return ""
    def block_repl(match: re.Match[str]) -> str:
        return "".join("\n" if ch == "\n" else " " for ch in match.group(0))
    text = re.sub(r"/\*.*?\*/", block_repl, text, flags=re.S)
    text = re.sub(r"//[^\n\r]*", lambda m: " " * len(m.group(0)), text)
    return text


def _line_number_for_offset(text: str, offset: int) -> int:
    return max(1, text.count("\n", 0, max(0, offset)) + 1)


def _discover_test_cases_in_spec(root: Path, rel_spec: str) -> dict[str, Any]:
    """Statically discover Playwright test cases inside one spec file.

    This intentionally does not launch the AUT or call npm.  It supports the
    most common Playwright styles: test('title'), test.only(...), test.skip(...),
    test.fixme(...), and it(...) aliases.  Hooks, test.describe and test.step
    are excluded so the count shown in the GUI is close to Playwright's real
    executable test-case count without slowing discovery.
    """
    spec = str(rel_spec or "").replace("\\", "/").strip()
    path = root / _strip_playwright_line_selector(spec)
    raw = _read(path, limit=1_000_000)
    masked = _strip_js_ts_comments_for_scan(raw)
    tests: list[dict[str, Any]] = []
    # Prefix prevents matching ``mytest(...)``.  Modifier validation below
    # rejects describe/hooks/step while allowing only/skip/fixme/fail/slow.
    pattern = re.compile(r'''(?<![\w$])(?P<api>test|it)(?P<mods>(?:\.[A-Za-z_$][\w$]*)*)\s*\(\s*(?P<q>['"`])(?P<title>(?:\\.|(?!(?P=q)).)*?)(?P=q)''', re.S)
    allowed_mods = {"", "only", "skip", "fixme", "fail", "slow"}
    blocked_mods = {"describe", "step", "beforeeach", "aftereach", "beforeall", "afterall", "use", "extend", "info"}
    seen_lines: set[int] = set()

    def add_case(start_offset: int, title_raw: str, kind: str = "test_case") -> None:
        title = re.sub(r"\s+", " ", (title_raw or "").replace("\\`", "`").replace("\\'", "'").replace('\\"', '"')).strip()
        line = _line_number_for_offset(masked, start_offset)
        if line in seen_lines:
            return
        seen_lines.add(line)
        target = f"{spec}:{line}"
        tests.append({
            "id": f"{spec}::{line}::{title}",
            "spec": spec,
            "target": target,
            "line": line,
            "title": title or f"Test at line {line}",
            "ordinal": len(tests) + 1,
            "kind": kind,
        })

    for match in pattern.finditer(masked):
        mods = [m for m in str(match.group("mods") or "").strip(".").split(".") if m]
        low_mods = [m.lower() for m in mods]
        if any(m in blocked_mods for m in low_mods):
            continue
        if any(m not in allowed_mods for m in low_mods):
            continue
        add_case(match.start(), match.group("title") or "", "test_case")

    # Enterprise/custom wrapper support. Many mature frameworks wrap Playwright
    # test with helpers such as testDetails({...})("case title", async ...).
    # These are still executable Playwright tests, so show them in the hierarchy
    # and allow line-selector execution.
    wrapper_pattern = re.compile(r"""(?<![\w$])(?P<api>testDetails|testCase|createTest|uiTest|scenario)\s*\((?:[^()]|\([^()]*\))*\)\s*\(\s*(?P<q>['"`])(?P<title>(?:\\.|(?!(?P=q)).)*?)(?P=q)""", re.S)
    for match in wrapper_pattern.finditer(masked):
        add_case(match.start(), match.group("title") or "", "custom_wrapper:" + str(match.group("api") or "wrapper"))

    return {
        "spec": spec,
        "test_case_count": len(tests),
        "tests": tests,
        "discovery_method": "static_playwright_test_call_scan",
    }


def _build_test_case_inventory(root: Path, rel_specs: list[str]) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    total = 0
    for spec in rel_specs:
        if not _is_tests_folder_executable_spec(spec, root=root):
            continue
        item = _discover_test_cases_in_spec(root, spec)
        items.append(item)
        total += int(item.get("test_case_count") or 0)
    return {
        "specs": items,
        "total_spec_count": len(items),
        "total_test_case_count": total,
        "counting_method": "static_playwright_test_call_scan",
        "message": "Static Playwright test-call discovery used for fast GUI hierarchy. Playwright execution remains the source of truth for final pass/fail results.",
    }


def _extract_import_paths(text: str) -> list[str]:
    imports: list[str] = []
    patterns = [
        r"import\s+(?:type\s+)?(?:[^;]*?)\s+from\s+['\"]([^'\"]+)['\"]",
        r"import\s*\(\s*['\"]([^'\"]+)['\"]\s*\)",
        r"require\s*\(\s*['\"]([^'\"]+)['\"]\s*\)",
    ]
    for pat in patterns:
        imports.extend(re.findall(pat, text, flags=re.M))
    return imports


def _candidate_files_for_import_or_path(root: Path, raw_value: str, base_file: Path | None = None) -> list[Path]:
    """Return safe candidate files inside root for relative, absolute, alias, or Windows-style paths.

    This is intentionally conservative but broader than the earlier resolver.
    Real enterprise frameworks often use aliases such as @pages/LoginPage,
    src/pages/LoginPage, tests/specs/Login.specs.ts, or absolute Windows paths
    in reports.  If we cannot resolve these, self-healing has no allowed files
    and correctly blocks.  This helper keeps the guardrail but resolves the
    common valid cases.
    """
    value = (raw_value or "").strip().strip('"\'`').replace("\\", "/")
    if not value:
        return []

    candidates: list[Path] = []
    alias_summary = tsconfig_alias_summary(root)
    base_url = str(alias_summary.get("base_url") or ".").replace("\\", "/").strip().strip("/") or "."
    try:
        ts_base_root = (root / base_url).resolve() if base_url != "." else root.resolve()
    except Exception:
        ts_base_root = root.resolve()

    def add_base(path_like: str | Path) -> None:
        s = str(path_like).replace("\\", "/")
        if not s:
            return
        bases = [Path(s)]
        # Pathlib on Linux does not treat C:/... as absolute, but on Windows it does.
        # Keep both direct and root-relative variants; below we only accept files under root.
        if base_file is not None and (s.startswith("./") or s.startswith("../") or raw_value.startswith(".")):
            bases.append((base_file.parent / s))
        bases.append(root / s)
        if ts_base_root != root.resolve() and not Path(s).is_absolute():
            bases.append(ts_base_root / s)
        for base in bases:
            candidates.append(base)
            # Imports like @pages/foo.page have a semantic suffix (.page) but
            # still need .ts/.js materialization. Treat only real code suffixes
            # as complete file extensions.
            if base.suffix.lower() in {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".json"}:
                continue
            for suffix in [".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"]:
                candidates.append(Path(str(base) + suffix))
            for index in ["index.ts", "index.tsx", "index.js", "index.jsx"]:
                candidates.append(base / index)

    # Direct value, relative imports, and normalized dotless forms.
    add_base(value)
    add_base(value.lstrip("./"))

    # If an absolute path or terminal output contains the project path, convert it to relative.
    root_norm = str(root.resolve()).replace("\\", "/").lower()
    low = value.lower()
    if root_norm and root_norm in low:
        idx = low.index(root_norm) + len(root_norm)
        rel = value[idx:].lstrip("/")
        add_base(rel)

    # Trim noisy prefixes back to common framework roots.
    for marker in ["/tests/", "tests/", "/specs/", "specs/", "/e2e/", "e2e/", "/src/", "src/", "/pages/", "pages/", "/pageobjects/", "pageobjects/", "/pageObjects/", "pageObjects/", "/utils/", "utils/"]:
        low_value = value.lower()
        marker_low = marker.lower()
        if marker_low in low_value:
            idx = low_value.index(marker_low)
            rel = value[idx:].lstrip("/")
            if rel.startswith("specs/") and (root / "tests" / rel).exists():
                add_base("tests/" + rel)
            add_base(rel)

    # Common TS path aliases and enterprise folder conventions.
    alias_variants: list[str] = []
    if value.startswith("@/"):
        alias_variants.append(value[2:])
    if value.startswith("~/"):
        alias_variants.append(value[2:])
    m = re.match(r"^@([^/]+)/(.+)$", value)
    if m:
        alias = m.group(1).lower()
        rest = m.group(2)
        alias_map = {
            "pages": ["pages", "src/pages", "app/pages", "lib/pages"],
            "pageobjects": ["pageObjects", "pageobjects", "page-objects", "src/pageObjects", "src/pageobjects", "src/page-objects"],
            "objects": ["pageObjects", "pageobjects", "objects", "src/pageObjects", "src/objects"],
            "utils": ["utils", "src/utils", "test-utils", "tests/utils"],
            "helpers": ["helpers", "src/helpers", "utils", "src/utils"],
            "fixtures": ["fixtures", "tests/fixtures", "src/fixtures", "src/test/resources/fixtures"],
            "config": ["config", "src/config", "src/main/config", "tests/config", "src/test/config"],
            "api": ["api", "src/api", "src/main/api"],
            "base": ["base", "src/base", "src/main/ui_base", "src/ui_base"],
            "dataloader": ["data-loader", "dataLoader", "src/test/resources/data-loader", "tests/data-loader"],
            "testdata": ["testData", "test-data", "src/test/resources/testData", "tests/testData"],
            "reporters": ["reporters", "src/test/resources/reporters", "tests/reporters"],
            "components": ["components", "src/components"],
            "pom": ["pages", "pageObjects", "src/pages", "src/pageObjects"],
        }
        for prefix in alias_map.get(alias, [alias, f"src/{alias}"]):
            alias_variants.append(f"{prefix}/{rest}")
    for prefix in ["pages/", "pageObjects/", "pageobjects/", "page-objects/", "utils/", "helpers/", "fixtures/"]:
        if value.startswith(prefix):
            alias_variants.extend([value, "src/" + value, "tests/" + value])
    for variant in alias_variants:
        add_base(variant)

    # tsconfig/jsconfig path aliases such as @config/* => src/main/config/*.
    # JSONC comments/trailing commas are supported because enterprise tsconfig
    # files commonly contain comments.
    for key, mapped_values in (alias_summary.get("paths") or {}).items():
        key_regex = "^" + re.escape(str(key)).replace("\\*", "(.+)") + "$"
        match = re.match(key_regex, value)
        if not match:
            continue
        wildcard = match.group(1) if match.groups() else ""
        for mapped in mapped_values if isinstance(mapped_values, list) else [mapped_values]:
            mapped_str = str(mapped).replace("*", wildcard)
            add_base(mapped_str)

    resolved: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        try:
            cand = candidate.expanduser().resolve()
            cand.relative_to(root.resolve())
        except Exception:
            continue
        if cand.exists() and cand.is_file() and not _is_ignored(cand, root):
            key = str(cand).lower()
            if key not in seen:
                resolved.append(cand)
                seen.add(key)

    # Last resort: same basename anywhere under the framework root.
    # This is useful when the report stores only the filename or a partial path.
    base_name = Path(value).name
    if base_name and (base_name.lower().endswith(SPEC_SUFFIXES) or Path(base_name).suffix.lower() in TS_SUFFIXES):
        for p in root.rglob(base_name):
            if p.is_file() and not _is_ignored(p, root):
                key = str(p.resolve()).lower()
                if key not in seen:
                    resolved.append(p.resolve())
                    seen.add(key)
                    if len(resolved) >= 20:
                        break
    return resolved


def _resolve_existing_file(root: Path, raw_value: str, base_file: Path | None = None) -> Path | None:
    candidates = _candidate_files_for_import_or_path(root, raw_value, base_file=base_file)
    return candidates[0] if candidates else None


def _resolve_import(base_file: Path, imp: str, root: Path) -> Path | None:
    return _resolve_existing_file(root, imp, base_file=base_file)


def _import_graph_for_specs(root: Path, spec_files: list[Path]) -> dict[str, Any]:
    graph: dict[str, Any] = {}
    for spec in spec_files[:300]:
        text = _read(spec, limit=50000)
        imports = _extract_import_paths(text)
        resolved = []
        for imp in imports:
            found = _resolve_import(spec, imp, root)
            if found:
                resolved.append(_rel_to(found, root))
        graph[_rel_to(spec, root)] = sorted(dict.fromkeys(resolved))
    return graph



def _tsconfig_alias_import_audit(root: Path, code_files: list[Path], limit: int = 1200) -> dict[str, Any]:
    """Audit TypeScript path aliases and unresolved internal alias imports.

    This specifically catches failures like "Cannot find module '@config/environment'"
    before RCA mislabels them as locator/DOM problems.
    """
    summary = tsconfig_alias_summary(root)
    alias_imports: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    resolved_count = 0
    alias_keys = list((summary.get("paths") or {}).keys())

    def is_internal_alias(value: str) -> bool:
        if not value or not value.startswith(("@", "~", "#")):
            return False
        if value.startswith(("@playwright/", "@types/", "@babel/", "@jest/", "@testing-library/", "@cucumber/")):
            return False
        if alias_keys:
            for key in alias_keys:
                regex = "^" + re.escape(str(key)).replace("\\*", "(.+)") + "$"
                if re.match(regex, value):
                    return True
        # Keep common enterprise aliases even when tsconfig parse failed/missing.
        return bool(re.match(r"^@(pages|pageobjects|objects|fixtures|config|api|base|dataloader|testdata|reporters|utils|helpers|components|pom)(/|$)", value, flags=re.I))

    for file in code_files[:limit]:
        if not file.exists() or file.suffix.lower() not in TS_SUFFIXES:
            continue
        rel = _rel_to(file, root)
        for imp in _extract_import_paths(_read(file, limit=120000)):
            if not is_internal_alias(str(imp)):
                continue
            found = _resolve_import(file, str(imp), root)
            rec = {"file": rel, "import": str(imp), "resolved": _rel_to(found, root) if found else ""}
            alias_imports.append(rec)
            if found:
                resolved_count += 1
            else:
                unresolved.append(rec)
            if len(alias_imports) >= 300:
                break
        if len(alias_imports) >= 300:
            break
    runtime_required = bool(alias_imports and summary.get("alias_count"))
    return {
        "ok": True,
        "tsconfig": summary,
        "runtime_alias_resolver_recommended": runtime_required,
        "alias_import_count_sampled": len(alias_imports),
        "resolved_alias_import_count_sampled": resolved_count,
        "unresolved_alias_import_count_sampled": len(unresolved),
        "sample_alias_imports": alias_imports[:80],
        "unresolved_alias_imports": unresolved[:80],
        "message": (
            "TypeScript path aliases detected. AstraHeal will preload a runtime alias resolver for Playwright execution and RCA scope resolution."
            if runtime_required else
            "No internal TypeScript path alias runtime resolver requirement was detected from sampled files."
        ),
    }


def _inline_locator_findings(root: Path, spec_files: list[Path]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    locator_re = re.compile(r"\bpage\s*\.\s*(locator|getByRole|getByText|getByTestId|getByLabel|getByPlaceholder|getByAltText|getByTitle)\s*\(")
    for spec in spec_files[:500]:
        text = _read(spec, limit=100000)
        count = len(locator_re.findall(text))
        if count:
            findings.append({"spec": _rel_to(spec, root), "inline_locator_calls": count})
    return findings[:80]


def _pom_score(dirs: dict[str, list[str]], inline_findings: list[dict[str, Any]], spec_count: int) -> dict[str, Any]:
    score = 100
    if not dirs.get("page_dirs"):
        score -= 25
    if not dirs.get("page_object_dirs"):
        score -= 25
    if spec_count and inline_findings:
        affected = len(inline_findings)
        score -= min(35, int((affected / max(spec_count, 1)) * 35) + 5)
    score = max(0, score)
    return {
        "score": score,
        "grade": "strong" if score >= 80 else ("moderate" if score >= 55 else "needs_refactor"),
        "rule": "Specs should call reusable page methods; page methods should use pageObjects/locator modules. RCA patches should prefer pageObjects/pages/helpers over specs.",
    }


def _playwright_alignment_plan(root: Path, inventory: dict[str, Any], package_json: dict[str, Any], dirs: dict[str, list[str]], inline: list[dict[str, Any]], spec_files: list[Path]) -> dict[str, Any]:
    """Create a human-readable Playwright alignment strategy without risky rewrites.

    Understanding mode should not silently rewrite an enterprise framework.  This
    function detects alignment gaps and turns them into safe, actionable guardrails
    for RCA/self-healing.  Actual code changes still go through the existing
    approved-with-backup / rollback flow.
    """
    issues: list[dict[str, Any]] = []
    actions: list[dict[str, Any]] = []
    spec_rel = [_rel_to(p, root) for p in spec_files]
    specs_suffix_count = len([s for s in spec_rel if s.lower().endswith(".specs.ts") or s.lower().endswith(".specs.js")])
    config_text = "\n".join(_read(p, limit=60000) for p in _playwright_config_files(root))
    has_pw_config = bool(_playwright_config_files(root))
    has_test_match_for_specs = bool(re.search(r"\.specs\.", config_text, flags=re.I)) if config_text else False
    deps = {}
    if isinstance(package_json, dict):
        deps.update(package_json.get("dependencies") or {})
        deps.update(package_json.get("devDependencies") or {})
    scripts = (package_json.get("scripts") or {}) if isinstance(package_json, dict) else {}

    def issue(severity: str, title: str, detail: str, safe_fix: str) -> None:
        issues.append({"severity": severity, "title": title, "detail": detail, "safe_fix": safe_fix})

    if not (root / "package.json").exists():
        issue("blocker", "package.json missing at resolved framework root", "Playwright execution needs package.json and npm scripts/dependencies from the actual framework root.", "Use the auto-detected root or create package.json via approved framework setup before execution.")
    if "@playwright/test" not in deps and "playwright" not in deps:
        issue("high", "Playwright dependency not detected", "@playwright/test or playwright was not found in dependencies/devDependencies.", "Run npm install for the existing framework or add @playwright/test with approval.")
    if not has_pw_config:
        issue("high", "Playwright config not detected", "No playwright.config.ts/js/mjs/cjs file was found at the framework root.", "Create a minimal Playwright config with reports/traces/screenshots through approved self-healing.")
    if specs_suffix_count and has_pw_config and not has_test_match_for_specs:
        issue("medium", ".specs.* files may not be matched by default config", f"Detected {specs_suffix_count} .specs.* files. Default Playwright testMatch often does not include .specs.* unless configured.", "Add testMatch for **/*.specs.ts/js or rename files through a reviewed change.")
    executable_spec_files = [p for p in spec_files if p.name.lower().endswith(EXECUTABLE_SPEC_SUFFIXES) and _is_tests_folder_executable_spec(_rel_to(p, root), root=root)]
    executable_roots = _discover_executable_test_roots(root, [_rel_to(p, root) for p in executable_spec_files])
    if not executable_roots:
        issue("medium", "Playwright executable test location not proven", "AstraHeal recursively checks configured testDir, nested enterprise roots such as src/test/specs/**, monorepo test folders, and executable Playwright content. No runnable location was proven.", "Use the correct framework root, confirm Playwright testDir/testMatch, or place executable tests in the intended framework test location.")
    if not executable_spec_files:
        issue("blocker", "No executable Playwright spec/test files found", "Recursive discovery checked configured testDir, conventional and nested test folders, and executable Playwright test content.", "Use Deep Learn/AI full-control fix to identify the actual test layout or repair Playwright testDir/testMatch/import configuration.")
    if not dirs.get("page_dirs"):
        issue("medium", "Page class folder not detected", "Specs may be interacting directly with the page instead of calling reusable page methods.", "Create/use pages/<PageName>.ts and move business actions there during approved fixes.")
    if not dirs.get("page_object_dirs"):
        issue("medium", "PageObject/locator folder not detected", "Locator definitions may be mixed with page methods or specs.", "Create/use pageObjects/<PageName>.objects.ts and keep locators separate from test specs.")
    if inline:
        issue("medium", "Inline locators inside specs", f"Detected inline page.locator/getBy* calls in {len(inline)} spec file(s).", "RCA/self-healing should prefer pageObjects/pages/helper files; edit specs only when unavoidable.")
    if has_pw_config and not re.search(r"trace\s*:", config_text, flags=re.I):
        issue("low", "Trace collection not visible in Playwright config", "RCA is stronger with trace/video/screenshot evidence.", "Enable trace: 'on-first-retry', screenshot/video on failure through approved config update.")

    if not issues:
        actions.append({"priority": 1, "area": "framework", "action": "No structural alignment change required.", "why": "The framework has Playwright project evidence and reusable structure is acceptable.", "how_to_apply": "Continue normal execution and failed-only RCA/self-healing."})
    else:
        for idx, item in enumerate(issues, start=1):
            actions.append({"priority": idx, "area": "playwright_alignment", "action": item["safe_fix"], "why": item["detail"], "severity": item["severity"], "how_to_apply": "Use Fix failed tests safely / AI full-control framework fix so backup, approval, validation and rollback remain active."})

    strategy = {
        "for_humans": [
            "Understand mode detects Playwright alignment gaps and writes this report; it does not silently rewrite your enterprise framework.",
            "Fix mode uses this alignment memory plus failed-test evidence to patch only approved files with backup and rollback.",
            "RCA remains failed-only: passed scripts and unrelated files are not patched.",
        ],
        "rca_self_healing_order": [
            "1. Confirm exact failed test and retry history.",
            "2. Read Playwright console, JSON/html report, trace/video/screenshot paths and worker evidence.",
            "3. Map failed spec -> imported page -> pageObject/locator/helper/test data using the framework memory.",
            "4. Classify root cause: locator/DOM, not-interactable, timing, popup/permission, network/cert, data/fixture, assertion/product drift, or framework config.",
            "5. Patch smallest approved file first: pageObjects -> page methods/BasePage/helpers -> fixture/test data -> spec only if unavoidable.",
            "6. Rerun failed-only; rollback automatically if validation fails under strict policy.",
        ],
        "central_vm_rule": "In VM/VDI mode, RCA, source patching, AI memory and consolidated reports stay on the Central VM. Workers execute browsers and return evidence only.",
    }
    plan = {
        "ok": True,
        "stage": "playwright_framework_alignment_checked",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "framework_path": str(root),
        "aligned": not any(i.get("severity") in {"blocker", "high"} for i in issues),
        "issue_count": len(issues),
        "issues": issues,
        "recommended_actions": actions,
        "human_understandable_strategy": strategy,
        "report_url": "/artifacts/reports/existing-framework/playwright-framework-alignment.html",
    }
    _write_alignment_report(plan)
    return plan


def _write_alignment_report(plan: dict[str, Any]) -> None:
    def esc(v: Any) -> str:
        return str(v if v is not None else "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    rows = []
    for i in plan.get("issues") or []:
        rows.append(f"<tr><td>{esc(i.get('severity'))}</td><td>{esc(i.get('title'))}</td><td>{esc(i.get('detail'))}</td><td>{esc(i.get('safe_fix'))}</td></tr>")
    actions = ''.join(f"<li><b>{esc(a.get('severity') or 'info')}</b> — {esc(a.get('action'))}<br/><span>{esc(a.get('why'))}</span></li>" for a in (plan.get("recommended_actions") or []))
    strategy = plan.get("human_understandable_strategy") or {}
    order = ''.join(f"<li>{esc(x)}</li>" for x in (strategy.get("rca_self_healing_order") or []))
    html = f"""<!doctype html><html><head><meta charset='utf-8'/><title>Playwright Framework Alignment & RCA Strategy</title>
<style>body{{font-family:Segoe UI,Arial,sans-serif;background:#f8fafc;color:#0f172a;margin:24px}}table{{width:100%;border-collapse:collapse;background:white}}td,th{{border:1px solid #cbd5e1;padding:8px;vertical-align:top}}th{{background:#1e293b;color:white}}.card{{background:white;border:1px solid #cbd5e1;border-radius:12px;padding:16px;margin:14px 0}}.good{{background:#ecfdf5}}.warn{{background:#fff7ed}}</style></head><body>
<h1>Playwright Framework Alignment & RCA Strategy</h1>
<div class='card {'good' if plan.get('aligned') else 'warn'}'><b>Framework:</b> {esc(plan.get('framework_path'))}<br/><b>Aligned:</b> {esc(plan.get('aligned'))}<br/><b>Issue count:</b> {esc(plan.get('issue_count'))}</div>
<div class='card'><h2>Human-readable rule</h2><p>Understanding mode is safe and report-first. Actual source alignment changes are made only through approved self-healing/full-control fix with backup, validation and rollback.</p><p><b>Central VM rule:</b> {esc(strategy.get('central_vm_rule'))}</p></div>
<div class='card'><h2>Detected alignment gaps</h2><table><thead><tr><th>Severity</th><th>Gap</th><th>Why it matters</th><th>Safe alignment action</th></tr></thead><tbody>{''.join(rows) or '<tr><td colspan="4">No critical alignment gaps found.</td></tr>'}</tbody></table></div>
<div class='card'><h2>Recommended actions</h2><ol>{actions}</ol></div>
<div class='card'><h2>Robust RCA + Self-healing sequence</h2><ol>{order}</ol></div>
</body></html>"""
    EXISTING_ALIGNMENT_HTML.write_text(html, encoding="utf-8")
    EXISTING_ALIGNMENT_JSON.write_text(json.dumps(plan, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _ai_framework_understanding(root: Path, provider: str, model: str, inventory: dict[str, Any]) -> dict[str, Any]:
    provider = (provider or "deterministic").strip().lower()
    if provider not in {"codex", "ollama"}:
        return {"used": False, "provider": provider, "message": "Deterministic static framework understanding used. Select Codex/Ollama for extra narrative guidance."}
    prompt = f"""
You are an enterprise Playwright framework understanding agent.
Return JSON only with keys: architecture_summary, pom_contract, execution_command_recommendation, rca_scope_rules, self_healing_patch_order, risks.

Analyze the following static inventory of an existing Playwright framework. Do not modify files.
Focus on preserving the user's existing framework and bypassing testcase generation.

Strict rules:
- Use existing tests/specs only; do not generate new functional testcases.
- Preserve Page Object Model: spec -> page class/method -> pageObjects/locator definitions.
- RCA/self-healing must only target failed specs and files imported by those failed specs.
- Never patch already-passed specs during failed-only RCA validation.
- Prefer stable Playwright locators: getByRole/getByTestId/getByLabel, then CSS/XPath only when justified.

Inventory:
{json.dumps(inventory, indent=2, ensure_ascii=False)[:26000]}
""".strip()
    try:
        if provider == "codex":
            result = CodexCliProvider(root, timeout_seconds=300).run(prompt)
            return {"used": True, "provider": "codex", "ok": result.ok, "message": (result.stdout if result.ok else result.stderr)[-10000:]}
        result = OllamaProvider(model=model).chat(prompt)
        return {"used": True, "provider": "ollama", "ok": result.ok, "message": (result.text if result.ok else result.error)[-10000:]}
    except Exception as exc:
        return {"used": True, "provider": provider, "ok": False, "message": f"AI framework understanding failed safely: {type(exc).__name__}: {exc}"}


def analyze_existing_framework(framework_path: str, provider: str = "deterministic", model: str = "llama3", base_url: str = "") -> dict[str, Any]:
    _ensure_dirs()
    root = _resolve_framework_path(framework_path)
    log_event("existing_framework", f"Analyzing existing Playwright framework: {root}", progress=8, details={"framework_path": str(root)})
    package_json = _load_package_json(root)
    structure_profile = build_structure_profile(root, limit=5000)
    spec_files = _find_files(root, SPEC_SUFFIXES, limit=5000)
    executable_rel_specs = list(structure_profile.get("executable_specs") or [])
    executable_spec_files = [root / rel for rel in executable_rel_specs]
    executable_test_roots = list(structure_profile.get("discovered_test_roots") or _discover_executable_test_roots(root, executable_rel_specs))
    ts_files = _find_files(root, TS_SUFFIXES, limit=5000)
    dirs = _likely_dirs(root)
    inline = _inline_locator_findings(root, spec_files)
    scripts = package_json.get("scripts", {}) if isinstance(package_json, dict) else {}
    playwright_scripts = {k: v for k, v in scripts.items() if "playwright" in str(v).lower() or "e2e" in k.lower() or "test" == k.lower()}
    import_graph = _import_graph_for_specs(root, spec_files)
    path_alias_audit = _tsconfig_alias_import_audit(root, ts_files)
    inventory: dict[str, Any] = {
        "ok": True,
        "stage": "existing_framework_understood",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "framework_path": str(root),
        "base_url": normalize_base_url(base_url),
        "package_manager": _detect_package_manager(root),
        "has_package_json": (root / "package.json").exists(),
        "playwright_config_files": _playwright_config_files(root),
        "playwright_scripts": playwright_scripts,
        "total_code_files_seen": len(ts_files),
        "spec_count": len(spec_files),
        "executable_spec_count": len(executable_spec_files),
        "executable_test_roots": executable_test_roots,
        "structure_discovery": structure_profile,
        "sample_specs": [_rel_to(p, root) for p in spec_files[:60]],
        "sample_executable_specs": executable_rel_specs[:80],
        "directory_model": dirs,
        "spec_import_graph_sample": import_graph,
        "tsconfig_path_alias_audit": path_alias_audit,
        "inline_locator_findings_in_specs": inline,
        "pom_compliance": _pom_score(dirs, inline, len(spec_files)),
        "execution_recommendation": {
            "default_command": "npx --no-install playwright test <targets> --project=<browser> --workers=1 --reporter=line,json,html",
            "bypass_testcase_generation": True,
            "target_scope": "existing framework specs discovered from the provided folder",
        },
        "strict_rules": [
            "Bypass Requirement/Input/Testcase/Generated Playwright phases for this mode.",
            "Do not copy or overwrite the user's framework into generated-playwright.",
            "Execute the framework in-place from the provided folder.",
            "RCA and self-healing must use failed-tests inventory only.",
            "Patch failed specs and their imported page/pageObject/helper files only.",
            "Treat Cannot find module / MODULE_NOT_FOUND for @aliases as a TypeScript path-alias/runtime configuration issue, not a locator/DOM failure.",
            "Prefer PageObjects first, then page methods/BasePage/helpers; avoid raw locator fixes inside specs.",
            "Robust RCA uses five signals before patching: DOM diff, trace timing, HAR diff, fixture/seed diff, and cross-run flakiness frequency.",
            "Assertion updates are blocked unless the assertion drift classifier marks the change as cosmetic and above semantic threshold.",
        ],
    }
    try:
        inventory["object_repository_locator_audit"] = audit_object_repository_locators(root, base_url=normalize_base_url(base_url))
        inventory["object_repository_locator_audit_url"] = "/artifacts/reports/existing-framework/object-repository-locator-audit.html"
    except Exception as exc:
        inventory["object_repository_locator_audit"] = {"ok": False, "error": f"{type(exc).__name__}: {exc}", "message": "Object repository locator audit failed safely; base framework learning continued."}
    try:
        inventory["playwright_alignment"] = _playwright_alignment_plan(root, inventory, package_json if isinstance(package_json, dict) else {}, dirs, inline, spec_files)
    except Exception as exc:
        inventory["playwright_alignment"] = {"ok": False, "error": f"{type(exc).__name__}: {exc}", "message": "Playwright alignment check failed safely; base understanding is still available."}
    # Agentic deep understanding is deterministic and always runs before AI/Codex/Ollama.
    # It maps folder roles, spec->page->pageObject dependencies, locator strategy, AUT hints,
    # and saves reusable project memory for RCA/self-healing.
    try:
        inventory["agentic_framework_understanding"] = build_deep_framework_understanding(root, inventory, base_url=normalize_base_url(base_url))
        inventory["agentic_framework_understanding_url"] = "/artifacts/reports/existing-framework/agentic-framework-understanding.html"
    except Exception as exc:
        inventory["agentic_framework_understanding"] = {"ok": False, "error": f"{type(exc).__name__}: {exc}", "message": "Agentic framework understanding failed safely; base analysis is still available."}
    inventory["ai_understanding"] = _ai_framework_understanding(root, provider, model, inventory)
    try:
        inventory["framework_intelligence_v2"] = build_framework_intelligence_v2(root, inventory, base_url=normalize_base_url(base_url))
    except Exception as exc:
        inventory["framework_intelligence_v2"] = {"ok": False, "error": f"{type(exc).__name__}: {exc}", "message": "Framework intelligence v2 failed safely; base analysis is still available."}
    EXISTING_INTELLIGENCE_JSON.write_text(json.dumps(inventory, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    EXISTING_INTELLIGENCE_MD.write_text(_render_framework_markdown(inventory), encoding="utf-8")
    log_event("existing_framework", "Existing framework understanding completed. GUI can now execute existing specs without generating new testcases.", status="done", progress=100, details={"spec_count": len(spec_files), "executable_spec_count": len(executable_spec_files), "executable_test_roots": executable_test_roots, "pom_score": inventory["pom_compliance"]["score"]})
    return inventory


def _render_framework_markdown(inventory: dict[str, Any]) -> str:
    lines = [
        "# Existing Playwright Framework Intelligence",
        "",
        f"- Framework path: `{inventory.get('framework_path')}`",
        f"- Generated at: `{inventory.get('generated_at')}`",
        f"- Spec count: **{inventory.get('spec_count')}**",
        f"- POM grade: **{inventory.get('pom_compliance', {}).get('grade')}** ({inventory.get('pom_compliance', {}).get('score')}/100)",
        "",
        "## Important mode decision",
        "This mode bypasses requirement parsing, functional testcase generation, and generated Playwright script generation. It executes the provided framework in-place and uses failed-only RCA/self-healing when failures occur.",
        "",
        "## Discovered scripts",
        "```json",
        json.dumps(inventory.get("playwright_scripts", {}), indent=2, ensure_ascii=False),
        "```",
        "",
        "## Directory model",
        "```json",
        json.dumps(inventory.get("directory_model", {}), indent=2, ensure_ascii=False),
        "```",
        "",
        "## Strict rules",
    ]
    for rule in inventory.get("strict_rules", []):
        lines.append(f"- {rule}")
    v2 = inventory.get("framework_intelligence_v2") or {}
    if v2.get("ok"):
        lines.extend(["", "## Framework Intelligence V2", "- HTML: `generated-playwright/reports/existing-framework/framework-intelligence-v2.html`", f"- RAG chunks indexed: **{v2.get('rag_index', {}).get('chunk_count', 0)}**", "- Coverage: architecture, technology stack, trigger flows, normal flows, backend/API/DB hints, test data validation, VDI/VM/VPN hints."])
    alignment = inventory.get("playwright_alignment") or {}
    if alignment:
        lines.extend(["", "## Playwright Framework Alignment", f"- Aligned for execution: **{alignment.get('aligned')}**", f"- Issue count: **{alignment.get('issue_count', 0)}**", "- HTML: `generated-playwright/reports/existing-framework/playwright-framework-alignment.html`"])
        for item in (alignment.get("issues") or [])[:12]:
            lines.append(f"  - **{item.get('severity')}**: {item.get('title')} — {item.get('safe_fix')}")
    audit = inventory.get("object_repository_locator_audit") or {}
    if audit:
        s = audit.get("summary") or {}
        lines.extend(["", "## Object repository locator audit", f"- Locator definitions found: **{s.get('total_locators', 0)}**", f"- Object/page/locator files scanned: **{s.get('object_repo_file_count', 0)}**", f"- Static/snapshot matched: **{s.get('static_verified_count', 0)}**", f"- Need live Playwright MCP/page-state verification: **{s.get('needs_live_mcp_count', 0)}**", "- HTML: `generated-playwright/reports/existing-framework/object-repository-locator-audit.html`"])
    if inventory.get("inline_locator_findings_in_specs"):
        lines.extend(["", "## Inline locator warnings", "Some specs appear to call locators directly. Self-healing will still prefer moving fixes into page/pageObject/helper layers."])
    return "\n".join(lines) + "\n"


def _playwright_bin_exists(root: Path) -> bool:
    for rel in ["node_modules/@playwright/test", "node_modules/.bin/playwright", "node_modules/.bin/playwright.cmd"]:
        if (root / rel).exists():
            return True
    return False


def _ensure_runtime(root: Path, auto_install: bool = True) -> dict[str, Any]:
    status: dict[str, Any] = {
        "ok": False,
        "framework_path": str(root),
        "npm_available": bool(resolve_command("npm")),
        "npx_available": bool(resolve_command("npx")),
        "installed_before": _playwright_bin_exists(root),
        "steps": [],
    }
    if not (root / "package.json").exists():
        status["error"] = "package.json not found at the framework root. Please pass the Playwright project root folder."
        return status
    if not status["npm_available"] or not status["npx_available"]:
        status["error"] = "npm/npx not available. Install Node.js LTS and reopen the terminal/GUI."
        return status
    if not _playwright_bin_exists(root):
        if not auto_install:
            status["error"] = "Playwright dependencies missing. Run npm install in the existing framework folder."
            return status
        log_event("existing_framework", "Existing framework dependencies missing. Running npm install in the provided framework folder.", progress=18, details={"framework_path": str(root)})
        install = run_command(["npm", "install", "--registry=https://registry.npmjs.org/"], cwd=root, timeout=1200)
        status["steps"].append({"name": "npm_install", "ok": install.ok, "returncode": install.returncode, "stdout": install.stdout[-3000:], "stderr": install.stderr[-3000:], "error": install.error})
        if not install.ok:
            status["error"] = "npm install failed in the existing framework folder."
            return status
    version = run_command(["npx", "--no-install", "playwright", "--version"], cwd=root, timeout=60)
    status["steps"].append({"name": "playwright_version", "ok": version.ok, "stdout": version.stdout[-1000:], "stderr": version.stderr[-1000:], "error": version.error})
    if not version.ok:
        status["error"] = "Playwright CLI unavailable in the existing framework. Run npm install and retry."
        return status
    status["ok"] = True
    status["installed_after"] = _playwright_bin_exists(root)
    return status


def _parse_target_patterns(targets: str) -> list[str]:
    raw = (targets or "").strip()
    if not raw:
        return []
    return [x.strip().strip('"').strip("'") for x in re.split(r"[,\n]+", raw) if x.strip()]


def _ensure_headed_args(cmd: list[str]) -> list[str]:
    """Append Playwright headed flags to common custom test commands.

    Module 2 is intentionally optimized for visual debugging of existing
    frameworks. Some teams use custom commands such as `npx playwright test`,
    `npm test`, `npm run test:e2e`, `pnpm test`, or `yarn test`. The default
    command path already adds `--headed`; this helper protects custom-command
    paths so they do not silently fall back to headless execution.
    """
    lowered = [c.lower() for c in cmd]
    joined = " ".join(lowered)
    if "--headed" in lowered or "--ui" in lowered or "--debug" in lowered:
        return cmd
    # Direct Playwright command: npx playwright test ...
    if "playwright" in lowered and "test" in lowered:
        return [*cmd, "--headed"]
    # Package-manager test script. Forward headed to the underlying script.
    # npm/yarn/pnpm use `--` to forward arguments safely to scripts.
    if cmd and lowered[0] in {"npm", "pnpm", "yarn"} and ("test" in joined or "e2e" in joined or "playwright" in joined):
        if "--" in cmd:
            return [*cmd, "--headed"]
        return [*cmd, "--", "--headed"]
    return cmd


def _discover_playwright_test_targets(root: Path) -> dict[str, Any]:
    """Discover executable Playwright test scripts for default GUI execution.

    The normal Run & Fix workflow discovers TypeScript/JavaScript Playwright
    spec/test files from recursively proven test locations. Root tests/** remains supported,
    and nested enterprise layouts such as src/test/specs/** are now supported.
    Feature files are requirements/BDD assets and are skipped here.
    """
    structure_profile = build_structure_profile(root, limit=5000)
    rel_specs = list(structure_profile.get("executable_specs") or [])
    spec_files = [root / rel for rel in rel_specs]
    executable_roots = list(structure_profile.get("discovered_test_roots") or _discover_executable_test_roots(root, rel_specs))
    test_root_label = ", ".join(executable_roots[:8]) if executable_roots else "recursively proven Playwright test locations"
    skipped_feature_files = [_rel_to(p, root) for p in _find_files(root, FEATURE_SUFFIXES, limit=5000)]
    skipped_outside_tests = [str(x.get("path") or "") for x in (structure_profile.get("rejected_spec_candidates") or []) if x.get("path")]
    all_named_specs = [s for s in rel_specs if re.search(r"(^|/)ALL.*\.(spec|specs|test)\.(ts|tsx|js|jsx|mjs|cjs)$", s, flags=re.I)]
    plural_specs = [s for s in rel_specs if re.search(r"\.specs\.(ts|tsx|js|jsx|mjs|cjs)$", s, flags=re.I)]

    if not rel_specs:
        return {
            "ok": False,
            "strategy": "no_executable_tests_found_by_recursive_structure_scan",
            "test_root": test_root_label,
            "executable_test_roots": executable_roots,
            "targets": [],
            "spec_count": 0,
            "total_discovered_spec_count": 0,
            "selected_specs": [],
            "sample_specs": [],
            "all_named_specs": [],
            "plural_specs": [],
            "skipped_feature_files": skipped_feature_files[:500],
            "skipped_outside_tests_folder": skipped_outside_tests[:500],
            "structure_discovery": structure_profile,
            "message": "No executable Playwright spec/test files were proven by recursive scan. AstraHeal checked Playwright testDir configuration, conventional/nested test folders, and executable Playwright test content. Feature files remain excluded from this workflow.",
        }

    # Prefer explicit paths whenever practical. This avoids missing non-standard
    # .specs.ts files in frameworks whose Playwright config still uses defaults.
    if len(rel_specs) <= 250:
        return {
            "ok": True,
            "strategy": "explicit_discovered_playwright_specs",
            "test_root": test_root_label,
            "executable_test_roots": executable_roots,
            "targets": rel_specs,
            "spec_count": len(rel_specs),
            "total_discovered_spec_count": len(rel_specs),
            "selected_specs": rel_specs[:1000],
            "sample_specs": rel_specs[:120],
            "all_named_specs": all_named_specs[:200],
            "plural_specs": plural_specs[:200],
            "skipped_feature_files": skipped_feature_files[:500],
            "skipped_outside_tests_folder": skipped_outside_tests[:500],
            "structure_discovery": structure_profile,
            "message": f"Executing every executable Playwright spec/test file found under {test_root_label} explicitly. Feature files are skipped by design.",
        }

    def dir_has_specs(rel_dir: str) -> tuple[bool, list[str]]:
        p = root / rel_dir
        prefix = rel_dir.lower().rstrip("/") + "/"
        matches = [s for s in rel_specs if s.lower().startswith(prefix)]
        return p.exists() and p.is_dir() and bool(matches), matches

    for rel_dir in [*executable_roots, "tests/specs", "tests/e2e", "tests/integration", "tests", "src/test/specs"]:
        ok, matches = dir_has_specs(rel_dir)
        if ok:
            msg = f"Large suite detected. Executing folder '{rel_dir}' to avoid Windows command length limits. Selected executable specs are shown in preview."
            if any(s in plural_specs for s in matches):
                msg += " This folder contains .specs.ts files; ensure your playwright.config testMatch supports them, or run selected files explicitly in smaller batches."
            return {
                "ok": True,
                "strategy": "large_suite_discovered_test_root_scope",
                "test_root": rel_dir,
                "targets": [rel_dir],
                "spec_count": len(matches),
                "total_discovered_spec_count": len(rel_specs),
                "selected_specs": matches[:1000],
                "sample_specs": matches[:120],
                "all_named_specs": [s for s in all_named_specs if s in matches][:200],
                "plural_specs": [s for s in plural_specs if s in matches][:200],
                "skipped_feature_files": skipped_feature_files[:500],
                "skipped_outside_tests_folder": skipped_outside_tests[:500],
                "structure_discovery": structure_profile,
                "message": msg,
            }

    return {
        "ok": True,
        "strategy": "large_suite_explicit_discovered_specs",
        "test_root": test_root_label,
        "executable_test_roots": executable_roots,
        "targets": rel_specs[:250],
        "spec_count": len(rel_specs),
        "total_discovered_spec_count": len(rel_specs),
        "selected_specs": rel_specs[:1000],
        "sample_specs": rel_specs[:120],
        "all_named_specs": all_named_specs[:200],
        "plural_specs": plural_specs[:200],
        "skipped_feature_files": skipped_feature_files[:500],
        "skipped_outside_tests_folder": skipped_outside_tests[:500],
        "structure_discovery": structure_profile,
        "message": f"Large Playwright suite detected under {test_root_label}. Preview shows all executable tests; default run scope is capped to explicit files to avoid command-length problems. Use module/include filters for exact batches.",
    }


def preview_existing_framework_tests(framework_path: str) -> dict[str, Any]:
    """Return exactly what the GUI will execute before running Playwright."""
    _ensure_dirs()
    root = _resolve_framework_path(framework_path)
    structure_profile = build_structure_profile(root, limit=5000)
    intelligence = {
        "ok": bool(structure_profile.get("executable_specs")),
        "stage": "lightweight_recursive_structure_discovery",
        "framework_path": str(root),
        "structure_discovery": structure_profile,
        "message": "Find Scripts uses deterministic recursive discovery only. Full AI/RAG learning runs from Deep learn this framework with AI or AI full-control framework fix.",
    }
    discovered_scope = _discover_playwright_test_targets(root)
    log_event(
        "module2_existing_framework",
        f"Test discovery completed. Selected {discovered_scope.get('spec_count', 0)} spec file(s) from {discovered_scope.get('test_root') or 'discovered scope'} before execution.",
        status="ok" if discovered_scope.get("ok") else "warning",
        progress=100,
        details={"framework_path": str(root), "discovered_scope": discovered_scope},
    )
    return {
        "ok": bool(discovered_scope.get("ok")),
        "stage": "existing_framework_test_discovery_completed",
        "framework_path": str(root),
        "framework_intelligence": intelligence,
        "selected_execution_scope": discovered_scope,
        "message": "These are the existing Playwright tests selected for execution. Review this list, then click Run all selected existing tests.",
    }



def _split_filter_terms(value: str) -> list[str]:
    """Split GUI include/exclude filters into simple lowercase tokens."""
    return [x.strip().lower().replace("\\", "/") for x in re.split(r"[,\n;]+", value or "") if x.strip()]


def _apply_test_selection_filters(rel_specs: list[str], module_folder: str = "", include_text: str = "", exclude_text: str = "") -> dict[str, Any]:
    """Filter discovered specs for the GUI selectable-test workflow.

    This is deliberately path-based and deterministic.  AI/RAG finds and
    explains the framework, but the user remains in control of which scripts are
    executed or skipped.
    """
    folder = (module_folder or "").strip().strip('"').strip("'").replace("\\", "/").strip("/").lower()
    include_terms = _split_filter_terms(include_text)
    exclude_terms = _split_filter_terms(exclude_text)
    selected: list[str] = []
    skipped: list[dict[str, str]] = []

    for spec in rel_specs:
        low = spec.lower().replace("\\", "/")
        reason = ""
        if folder and not (low == folder or low.startswith(folder + "/") or ("/" + folder + "/") in ("/" + low)):
            reason = f"outside selected folder/filter '{module_folder}'"
        elif include_terms and not any(term in low for term in include_terms):
            reason = "does not match include filter"
        elif exclude_terms and any(term in low for term in exclude_terms):
            reason = "matched exclude filter"
        if reason:
            skipped.append({"spec": spec, "reason": reason})
        else:
            selected.append(spec)

    return {
        "selected_specs": selected,
        "skipped_specs": skipped,
        "selected_count": len(selected),
        "skipped_count": len(skipped),
        "module_folder_filter": module_folder,
        "include_filters": include_terms,
        "exclude_filters": exclude_terms,
    }


def preview_existing_framework_tests_for_selection(
    framework_path: str,
    module_folder: str = "",
    include_text: str = "",
    exclude_text: str = "",
) -> dict[str, Any]:
    """Return a user-selectable list of specs with include/exclude filters.

    The previous preview only summarized the discovered scope.  This version is
    designed for non-technical users: it shows every discovered spec, lets the
    GUI render checkboxes, and preserves the selection into project memory so the
    exact execution choice is auditable.
    """
    _ensure_dirs()
    root = _resolve_framework_path(framework_path)
    structure_profile = build_structure_profile(root, limit=5000)
    intelligence = {
        "ok": bool(structure_profile.get("executable_specs")),
        "stage": "lightweight_recursive_structure_discovery",
        "framework_path": str(root),
        "structure_discovery": structure_profile,
        "message": "Find Scripts uses deterministic recursive discovery only. Full AI/RAG learning runs from Deep learn this framework with AI or AI full-control framework fix.",
    }
    discovered_scope = _discover_playwright_test_targets(root)
    all_specs = list(discovered_scope.get("selected_specs") or discovered_scope.get("targets") or [])
    # If the selected scope is folder based, use a fresh full file scan so the GUI
    # can still show individual checkboxes.
    if not all_specs or all(s and not str(s).lower().endswith(EXECUTABLE_SPEC_SUFFIXES) for s in all_specs):
        all_specs = [_rel_to(p, root) for p in _find_executable_tests_under_tests(root, limit=5000)]
    all_specs = sorted(dict.fromkeys(
        str(s).replace("\\", "/") for s in all_specs
        if str(s).strip() and _is_tests_folder_executable_spec(str(s), root=root)
    ))
    filtered = _apply_test_selection_filters(all_specs, module_folder=module_folder, include_text=include_text, exclude_text=exclude_text)
    test_case_inventory = _build_test_case_inventory(root, filtered["selected_specs"])
    selection = {
        "ok": bool(all_specs),
        "stage": "existing_framework_selectable_test_discovery_completed",
        "framework_path": str(root),
        "total_discovered_spec_count": len(all_specs),
        "all_specs": all_specs,
        "selected_specs": filtered["selected_specs"],
        "skipped_specs": filtered["skipped_specs"],
        "selected_count": filtered["selected_count"],
        "skipped_count": filtered["skipped_count"],
        "total_test_case_count": test_case_inventory.get("total_test_case_count", 0),
        "selected_test_case_count": test_case_inventory.get("total_test_case_count", 0),
        "test_case_inventory": test_case_inventory,
        "filters": {
            "module_folder": module_folder,
            "include_text": include_text,
            "exclude_text": exclude_text,
            "include_terms": filtered["include_filters"],
            "exclude_terms": filtered["exclude_filters"],
        },
        "selected_execution_scope": {
            **discovered_scope,
            "strategy": "user_selectable_existing_specs",
            "targets": filtered["selected_specs"],
            "selected_specs": filtered["selected_specs"],
            "spec_count": filtered["selected_count"],
            "test_case_count": test_case_inventory.get("total_test_case_count", 0),
            "total_test_case_count": test_case_inventory.get("total_test_case_count", 0),
            "test_case_inventory": test_case_inventory,
            "sample_specs": filtered["selected_specs"][:120],
            "message": "User can expand each spec, see contained Playwright test cases, and select either whole specs or individual test cases before execution.",
        },
        "framework_intelligence": intelligence,
        "message": "Test selection is ready. Only executable Playwright spec/test files proven by recursive configuration, path, or code evidence are shown. Select the scripts you want to run, then click Run chosen tests.",
    }
    sel_path = EXISTING_CACHE_DIR / "latest-user-test-selection.json"
    sel_path.write_text(json.dumps(selection, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    log_event(
        "module2_existing_framework",
        f"Selectable test discovery completed: {filtered['selected_count']} spec file(s), {test_case_inventory.get('total_test_case_count', 0)} test case(s) selected, {filtered['skipped_count']} skipped.",
        status="ok" if filtered["selected_count"] else "warning",
        progress=100,
        details={"framework_path": str(root), "filters": selection["filters"], "selected_count": filtered["selected_count"]},
    )
    return selection


def execute_selected_existing_framework_tests(
    framework_path: str,
    selected_tests: str,
    project: str = "auto",
    headed: bool = True,
    base_url: str = "",
    execution_mode: str = "sequential",
    test_command: str = "",
    use_mcp_assist: bool = True,
) -> dict[str, Any]:
    """Run only user-selected existing specs from the external framework."""
    root = _resolve_framework_path(framework_path)
    chosen = _parse_target_patterns(selected_tests)
    chosen = sorted(dict.fromkeys(str(s).replace("\\", "/") for s in chosen if str(s).strip()))
    if not chosen:
        payload = {
            "ok": False,
            "stage": "existing_framework_selected_run_blocked_no_tests",
            "framework_path": str(root),
            "message": "No test scripts were selected. Click 'Find scripts in framework', tick one or more scripts, then click 'Run chosen tests'.",
        }
        log_event("existing_framework_selected_run", payload["message"], status="error", progress=100, details=payload)
        return payload
    invalid = [s for s in chosen if not (root / _strip_playwright_line_selector(s)).exists()]
    non_executable_or_outside_tests = [s for s in chosen if not _is_tests_folder_executable_spec(s, root=root)]
    if invalid or non_executable_or_outside_tests:
        payload = {
            "ok": False,
            "stage": "existing_framework_selected_run_blocked_invalid_tests",
            "framework_path": str(root),
            "invalid_tests": invalid,
            "non_executable_or_outside_tests_folder": non_executable_or_outside_tests,
            "selected_tests": chosen,
            "message": "Some selected items do not exist or were not proven as executable Playwright spec/test files by the recursive structure scan. Refresh the test list; feature files are intentionally skipped.",
        }
        log_event("existing_framework_selected_run", payload["message"], status="error", progress=100, details=payload)
        return payload
    selection_record = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "framework_path": str(root),
        "selected_tests": chosen,
        "selected_count": len(chosen),
        "selected_spec_count": len(sorted(dict.fromkeys(_strip_playwright_line_selector(x) for x in chosen))),
        "selected_test_case_selector_count": len([x for x in chosen if _is_playwright_line_selector(x)]),
        "mode": "headed" if headed else "headless",
        "project": _normalize_project(project) or "auto/all",
        "message": "User-selected existing Playwright scripts were executed. Unselected scripts were intentionally skipped.",
    }
    (EXISTING_CACHE_DIR / "last-executed-user-selection.json").write_text(json.dumps(selection_record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    log_event("existing_framework_selected_run", f"Running {len(chosen)} user-selected existing Playwright target(s).", status="running", progress=12, details=selection_record)
    result = execute_existing_framework(
        framework_path=str(root),
        project=project,
        headed=headed,
        base_url=base_url,
        execution_mode=execution_mode,
        shards=1,
        targets="\n".join(chosen),
        test_command=test_command,
        auto_install=True,
        use_mcp_assist=use_mcp_assist,
    )
    try:
        from qa_pipeline.core.distributed_history import append_execution_history
        append_execution_history(str(root), {
            "type": "selected_test_execution",
            "stage": "existing_framework_user_selected_tests_completed",
            "ok": bool(result.get("ok")),
            "selected_tests": chosen,
            "selected_count": len(chosen),
            "execution": {k: result.get(k) for k in ["ok", "returncode", "failed_count", "stage", "message"]},
        }, mirror_to_framework=True)
    except Exception as exc:
        log_event("framework_history", f"Could not write selected execution history: {type(exc).__name__}: {exc}", status="warning", progress=100)
    return {
        "ok": bool(result.get("ok")),
        "stage": "existing_framework_user_selected_tests_completed",
        "selection": selection_record,
        "existing_framework_execution": result,
        "playwright_html_report_url": result.get("playwright_html_report_url") or "/artifacts/reports/existing-framework/html/index.html",
        "message": f"Executed {len(chosen)} chosen existing Playwright target(s). Unselected scripts/test cases were not executed.",
    }

def _normalize_project(project: str) -> str:
    value = (project or "").strip()
    if value.lower() in {"", "auto", "all", "detect", "default", "none"}:
        return ""
    return value



def _is_cucumber_framework(root: Path) -> bool:
    return any((root / name).exists() for name in ["cucumber.js", "cucumber.mjs", "cucumber.cjs"]) or (root / "features").exists() and ((root / "src" / "step-definitions").exists() or (root / "step-definitions").exists())

def _is_feature_target(targets: list[str]) -> bool:
    return bool(targets) and all(str(t).lower().endswith(".feature") for t in targets)

def _build_command(root: Path, project: str, headed: bool, targets: list[str], test_command: str = "") -> list[str]:
    project = _normalize_project(project)
    if test_command.strip():
        import shlex
        cmd = shlex.split(test_command.strip())
        if "{targets}" in cmd:
            idx = cmd.index("{targets}")
            cmd = cmd[:idx] + targets + cmd[idx + 1:]
        if headed:
            cmd = _ensure_headed_args(cmd)
        return _append_playwright_timeout_arg(cmd)
    if _is_feature_target(targets) or (_is_cucumber_framework(root) and any(str(t).lower().endswith(".feature") for t in targets)):
        args = ["npx", "--no-install", "cucumber-js", *targets, "--format", "progress-bar", "--format", "json:reports/cucumber-json/cucumber-aiqa.json", "--format", "html:reports/html-report/cucumber-report.html"]
        return args
    args = ["npx", "--no-install", "playwright", "test", *targets]
    if project:
        args.append(f"--project={project}")
    args.extend(["--workers=1", "--reporter=line,json,html", f"--timeout={_astraheal_max_wait_ms()}", "--retries=1"])
    if headed:
        args.append("--headed")
    return args



def _resolve_first_arg(args: list[str]) -> tuple[list[str], str | None]:
    """Resolve npm/npx/playwright wrappers safely, especially on Windows."""
    if not args:
        return args, "empty command"
    resolved = resolve_command(args[0])
    if not resolved:
        return args, f"command not found: {args[0]}"
    return [resolved, *args[1:]], None


def _alias_runtime_env_summary(env: dict[str, str]) -> dict[str, Any]:
    register = str((env or {}).get("ASTRAHEAL_TSCONFIG_ALIAS_REGISTER") or "").strip()
    node_options = str((env or {}).get("NODE_OPTIONS") or "").strip()
    return {
        "enabled": bool(register and register in node_options),
        "register_file": register,
        "node_options_preload_present": bool(register and register in node_options),
        "framework_root": str((env or {}).get("ASTRAHEAL_FRAMEWORK_ROOT") or ""),
        "purpose": "Preload dependency-free tsconfig path alias resolver for Playwright/Node runtime.",
    }


def _launcher_env_lines(env: dict[str, str], windows: bool) -> str:
    keys = ["NODE_OPTIONS", "ASTRAHEAL_FRAMEWORK_ROOT", "ASTRAHEAL_TSCONFIG_ALIAS_REGISTER"]
    lines: list[str] = []
    for key in keys:
        value = str((env or {}).get(key) or "").strip()
        if not value:
            continue
        if windows:
            # SET syntax intentionally keeps spaces in NODE_OPTIONS and works in cmd.exe.
            lines.append(f"set \"{key}={value}\"")
        else:
            import shlex as _shlex
            lines.append(f"export {key}={_shlex.quote(value)}")
    if not lines:
        return ""
    return ("\r\n" if windows else "\n").join(lines) + ("\r\n" if windows else "\n")


def _is_module_resolution_failure(text: str) -> bool:
    low = (text or "").lower()
    return any(x in low for x in [
        "cannot find module", "module_not_found", "err_module_not_found", "require stack",
        "tsconfig-paths", "path alias", "path aliases", "failed to resolve import",
        "cannot resolve module", "could not resolve module",
    ])


def _extract_missing_module_name(text: str) -> str:
    raw = text or ""
    patterns = [
        r"Cannot find module ['\"]([^'\"]+)['\"]",
        r"Error: Cannot find module ['\"]([^'\"]+)['\"]",
        r"ERR_MODULE_NOT_FOUND[^\n]*['\"]([^'\"]+)['\"]",
        r"Cannot resolve module ['\"]([^'\"]+)['\"]",
    ]
    for pat in patterns:
        m = re.search(pat, raw, flags=re.I)
        if m:
            return m.group(1)[:180]
    return ""


def _write_execution_launcher(root: Path, args: list[str], env: dict[str, str], title: str) -> Path:
    """Write a debuggable launcher script beside the external framework reports."""
    run_dir = root / "reports" / "existing-framework"
    run_dir.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        script = run_dir / "RUN_EXISTING_PLAYWRIGHT_HEADED.cmd"
        cmdline = subprocess.list2cmdline(args)
        env_lines = _launcher_env_lines(env, windows=True)
        script.write_text(
            "@echo off\r\n"
            "setlocal enableextensions\r\n"
            f"echo [{title}] Starting at %DATE% %TIME%\r\n"
            f"echo Framework folder: {root}\r\n"
            "echo.\r\n"
            "echo Node/NPM/NPX locations:\r\n"
            "where node\r\n"
            "where npm\r\n"
            "where npx\r\n"
            "echo.\r\n"
            f"cd /d {subprocess.list2cmdline([str(root)])}\r\n"
            f"{env_lines}"
            f"echo Command: {cmdline}\r\n"
            f"{cmdline}\r\n"
            "set EXITCODE=%ERRORLEVEL%\r\n"
            "echo.\r\n"
            "echo Playwright command exited with code %EXITCODE%\r\n"
            "exit /b %EXITCODE%\r\n",
            encoding="utf-8",
        )
    else:
        import shlex
        script = run_dir / "run_existing_playwright_headed.sh"
        cmdline = " ".join(shlex.quote(x) for x in args)
        env_lines = _launcher_env_lines(env, windows=False)
        script.write_text(
            "#!/usr/bin/env bash\nset -o pipefail\n"
            f"echo '[{title}] Starting'\n"
            f"echo 'Framework folder: {root}'\n"
            "command -v node || true\ncommand -v npm || true\ncommand -v npx || true\n"
            f"cd {shlex.quote(str(root))}\n"
            f"{env_lines}"
            f"echo 'Command: {cmdline}'\n"
            f"{cmdline}\n"
            "code=$?\necho \"Playwright command exited with code $code\"\nexit $code\n",
            encoding="utf-8",
        )
        script.chmod(0o755)
    return script


def _write_execution_log(root: Path, execution: dict[str, Any]) -> Path:
    log_path = root / "reports" / "existing-framework" / "execution-console.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    text = [
        f"Command: {execution.get('command')}",
        f"CWD: {execution.get('cwd')}",
        f"Return code: {execution.get('returncode')}",
        f"Duration seconds: {execution.get('duration_seconds')}",
        "",
        "===== STDOUT/STDERR =====",
        str(execution.get("stdout", "")),
        "",
        "===== STDERR/ERROR =====",
        str(execution.get("stderr", "")),
        str(execution.get("error", "")),
    ]
    log_path.write_text("\n".join(text), encoding="utf-8", errors="replace")
    return log_path


def _run_streaming(args: list[str], root: Path, env: dict[str, str], title: str, start_pct: int = 30, end_pct: int = 92) -> dict[str, Any]:
    """Run Playwright for an external framework and stream combined output.

    This fixes the previous silent-failure pattern where stdout was read but
    stderr was only read after process completion. If Playwright failed early on
    stderr, the GUI could show generic progress without a useful failure report.
    """
    started = time.time()
    output_lines: list[str] = []
    final_args, resolution_error = _resolve_first_arg(args)
    command_display = " ".join(args)
    resolved_command_display = " ".join(final_args)
    launcher = _write_execution_launcher(root, final_args if not resolution_error else args, env, title)
    if resolution_error:
        execution = {
            "ok": False,
            "returncode": None,
            "command": command_display,
            "resolved_command": resolved_command_display,
            "launcher_script": str(launcher),
            "cwd": str(root),
            "stdout": "",
            "stderr": resolution_error,
            "error": resolution_error,
            "duration_seconds": round(time.time() - started, 2),
        }
        _write_execution_log(root, execution)
        log_event("existing_framework", f"{title} could not start: {resolution_error}", status="error", progress=end_pct, details=execution)
        return execution
    try:
        log_event("existing_framework", f"{title}: starting real Playwright process.", progress=start_pct, details={"command": command_display, "resolved_command": resolved_command_display, "cwd": str(root), "launcher_script": str(launcher)})
        # On Windows run the generated .cmd through cmd.exe so npx.cmd/npm.cmd
        # wrappers execute exactly like they do from the user's terminal.
        if os.name == "nt":
            popen_args = ["cmd.exe", "/d", "/s", "/c", str(launcher)]
        else:
            popen_args = [str(launcher)]
        proc = subprocess.Popen(
            popen_args,
            cwd=str(root),
            env=env,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=1,
        )
        assert proc.stdout is not None
        last_log = 0.0
        for line in proc.stdout:
            line = line.rstrip("\n")
            output_lines.append(line)
            now = time.time()
            if now - last_log > 0.6:
                pct = min(end_pct, start_pct + int((now - started) % max(end_pct - start_pct, 1)))
                log_event("existing_framework", f"{title}: {line[-260:]}", progress=pct, details={"command": command_display, "launcher_script": str(launcher)})
                last_log = now
        returncode = proc.wait()
        duration = round(time.time() - started, 2)
        combined = "\n".join(output_lines)
        ok = returncode == 0
        execution = {
            "ok": ok,
            "returncode": returncode,
            "command": command_display,
            "resolved_command": resolved_command_display,
            "launcher_script": str(launcher),
            "cwd": str(root),
            "stdout": combined[-30000:],
            "stderr": "",
            "duration_seconds": duration,
        }
        _write_execution_log(root, execution)
        log_event("existing_framework", f"{title} {'passed' if ok else 'completed with issue'} in {duration}s.", status="done" if ok else "warning", progress=end_pct, details={"returncode": returncode, "launcher_script": str(launcher)})
        return execution
    except Exception as exc:
        execution = {
            "ok": False,
            "returncode": None,
            "command": command_display,
            "resolved_command": resolved_command_display,
            "launcher_script": str(launcher),
            "cwd": str(root),
            "stdout": "\n".join(output_lines)[-30000:],
            "stderr": f"{type(exc).__name__}: {exc}",
            "error": f"{type(exc).__name__}: {exc}",
            "duration_seconds": round(time.time() - started, 2),
        }
        _write_execution_log(root, execution)
        log_event("existing_framework", f"{title} failed to start or stream: {type(exc).__name__}: {exc}", status="error", progress=end_pct, details=execution)
        return execution


def _playwright_execution_evidence(root: Path, execution: dict[str, Any]) -> dict[str, Any]:
    """Check whether Playwright actually ran tests and produced artifacts."""
    text = (str(execution.get("stdout", "")) + "\n" + str(execution.get("stderr", "")) + "\n" + str(execution.get("error", ""))).lower()
    html_exists = (root / "reports" / "existing-framework" / "html" / "index.html").exists() or (root / "playwright-report" / "index.html").exists()
    json_exists = (root / "reports" / "existing-framework" / "results.json").exists() or (root / "reports" / "results.json").exists()
    test_results_exists = (root / "reports" / "existing-framework" / "test-results").exists() or (root / "test-results").exists()
    no_tests = "no tests found" in text or "did not expect test()" in text
    started_markers = [
        "running ",
        "passed",
        "failed",
        "timed out",
        "test-results",
        "playwright report",
        "browser",
        "chromium",
        "firefox",
        "webkit",
        "cucumber",
        "scenario",
        "features/",
    ]
    has_text_evidence = any(m in text for m in started_markers)
    return {
        "html_report_found": html_exists,
        "json_report_found": json_exists,
        "test_results_folder_found": test_results_exists,
        "stdout_or_stderr_has_playwright_markers": has_text_evidence,
        "no_tests_found_message": no_tests,
        "likely_process_started": bool(has_text_evidence or html_exists or json_exists or test_results_exists),
    }


def _persist_execution_report(report: dict[str, Any]) -> None:
    _ensure_dirs()
    (EXISTING_REPORTS_DIR / "execution-report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _copy_external_artifacts(root: Path) -> dict[str, Any]:
    copied: dict[str, Any] = {"html_copied": False, "json_copied": False, "sources": []}
    # Copy our forced output paths first. The source can equal the destination when
    # the built-in generated-playwright folder is used as a smoke-test existing framework.
    html_candidates = [root / "reports" / "existing-framework" / "html", root / "playwright-report", root / "reports" / "html-report"]
    json_candidates = [root / "reports" / "existing-framework" / "results.json", root / "reports" / "results.json", root / "reports" / "cucumber-json" / "cucumber-aiqa.json", root / "reports" / "cucumber-json" / "cucumber.json"]
    html_source = next((src for src in html_candidates if (src / "index.html").exists()), None)
    if html_source:
        if html_source.resolve() == EXISTING_HTML_DIR.resolve():
            copied["html_copied"] = True
            copied["sources"].append(str(html_source))
        else:
            if EXISTING_HTML_DIR.exists():
                shutil.rmtree(EXISTING_HTML_DIR, ignore_errors=True)
            shutil.copytree(html_source, EXISTING_HTML_DIR, dirs_exist_ok=True)
            copied["html_copied"] = True
            copied["sources"].append(str(html_source))
    for src in json_candidates:
        if src.exists():
            EXISTING_RESULTS_JSON.parent.mkdir(parents=True, exist_ok=True)
            if src.resolve() != EXISTING_RESULTS_JSON.resolve():
                shutil.copy2(src, EXISTING_RESULTS_JSON)
            copied["json_copied"] = True
            copied["sources"].append(str(src))
            break
    if not copied["html_copied"]:
        _write_fallback_html("Existing framework Playwright report", {"message": "Native HTML report was not found after execution.", "sources_checked": [str(s) for s in html_candidates]})
    return copied


def _write_fallback_html(title: str, details: dict[str, Any]) -> None:
    EXISTING_HTML_DIR.mkdir(parents=True, exist_ok=True)
    body = json.dumps(details, indent=2, ensure_ascii=False)
    (EXISTING_HTML_DIR / "index.html").write_text(f"""<!doctype html><html><head><meta charset='utf-8'/><title>{title}</title>
<style>body{{font-family:Arial,sans-serif;margin:24px;background:#f8fafc;color:#111827}}.card{{background:white;border:1px solid #dbe3ef;border-radius:14px;padding:16px;margin:14px 0}}pre{{white-space:pre-wrap;background:#111827;color:#d1fae5;padding:14px;border-radius:10px}}</style></head><body>
<h1>{title}</h1><div class='card'><p>The AI QA Pipeline generated this fallback page because the existing framework did not produce a native HTML report in the expected location.</p></div><div class='card'><h2>Details</h2><pre>{body}</pre></div></body></html>""", encoding="utf-8")


def _framework_playwright_report_url(root: Path | str) -> str:
    encoded = urllib.parse.quote(str(root).replace('\\', '/'), safe='')
    return f"/api/module2/framework-artifact/playwright-report?framework_path={encoded}"


def _mark_playwright_report_in_progress(root: Path, title: str, details: dict[str, Any] | None = None) -> None:
    payload = {
        "message": "A fresh Playwright execution has started. Reopen the report after completion to see the latest native/landing report.",
        "framework_path": str(root),
        "started_at": datetime.now().isoformat(timespec="seconds"),
        **(details or {}),
    }
    _write_fallback_html(title, payload)


def _normalize_existing_spec_path(value: Any, root: Path | None = None) -> str:
    """Return a stable project-relative spec path for reporting/comparison.

    Playwright JSON can report files relative to the configured testDir.  For
    example, with ``testDir: './src/test/specs'`` it may report
    ``account/foo.spec.ts`` while the GUI selection uses
    ``src/test/specs/account/foo.spec.ts``.  This function maps such paths back
    to the real project-relative path so first-run, rerun, RCA and combined
    reports do not split the same test into duplicate rows.
    """
    v = str(value or "").replace("\\", "/").strip().strip('"\'`')
    if not v:
        return ""
    # Remove line/column suffixes only when they appear after a spec filename.
    v = re.sub(r"(\.(?:specs|spec|test)\.(?:ts|tsx|js|jsx|mjs|cjs))(?::\d+){1,2}$", r"\1", v, flags=re.I)
    relative_resolved = False
    try:
        if root and Path(v).is_absolute():
            v = str(Path(v).resolve().relative_to(root.resolve())).replace("\\", "/")
            relative_resolved = True
    except Exception:
        relative_resolved = False
    low = v.lower()
    # Trim any absolute prefix before common project test roots only when we did
    # not already make the path project-relative.  This avoids converting
    # src/test/specs/foo.spec.ts into test/specs/foo.spec.ts.
    if not relative_resolved:
        for marker in ["/src/test/specs/", "/src/test/", "/tests/", "/test/specs/", "/specs/", "/e2e/"]:
            idx = low.find(marker)
            if idx >= 0:
                v = v[idx + 1:]
                break
    v = re.sub(r"^\./+", "", v).replace("//", "/").strip("/")
    if root and v and not _is_tests_folder_executable_spec(v, root=root):
        try:
            for test_dir in _configured_playwright_test_dirs(root):
                candidate = test_dir.strip("/") + "/" + v
                if (root / candidate).exists() and _is_tests_folder_executable_spec(candidate, root=root):
                    v = candidate
                    break
        except Exception:
            pass
    return v


def _spec_compare_key(value: Any) -> str:
    v = _normalize_existing_spec_path(value).lower().strip("/")
    for prefix in ["tests/", "src/test/specs/", "src/test/", "src/tests/", "test/specs/", "test/", "specs/", "e2e/", "integration/"]:
        if v.startswith(prefix):
            return v[len(prefix):]
    return v

def _test_title_text(parts: list[Any] | tuple[Any, ...] | None, title: Any = "") -> str:
    values = [str(x).strip() for x in (parts or []) if str(x).strip()]
    t = str(title or "").strip()
    if t and (not values or values[-1] != t):
        values.append(t)
    return " › ".join(values).strip(" ›")


def _test_case_id(spec: Any, title: Any = "", project: Any = "") -> str:
    title_key = re.sub(r"\s+", " ", str(title or "").strip()).lower()
    project_key = str(project or "").strip().lower()
    # Do not include line/column because self-healing patches can move code.
    return "::".join([_spec_compare_key(spec), project_key, title_key]).strip(":")


def _case_record(spec: Any, title: Any = "", status: str = "unknown", project: Any = "", errors: Any = None, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    display_spec = _normalize_existing_spec_path(spec)
    rec = {
        "id": _test_case_id(display_spec, title, project),
        "spec": display_spec,
        "title": str(title or "").strip(),
        "projectName": project,
        "status": str(status or "unknown").lower(),
        "errors": errors or [],
    }
    if extra:
        rec.update(extra)
    return rec


def _inventory_test_cases(inventory: dict[str, Any], root: Path | None = None) -> list[dict[str, Any]]:
    """Return all test-case records, falling back to spec records for legacy inventories."""
    records: list[dict[str, Any]] = []
    for item in inventory.get("all_test_cases") or inventory.get("test_cases") or []:
        if isinstance(item, dict):
            spec = _normalize_existing_spec_path(item.get("spec") or item.get("file"), root=root)
            title = item.get("title") or item.get("name") or ""
            project = item.get("projectName") or item.get("project") or ""
            status = item.get("status") or "unknown"
            if spec:
                records.append(_case_record(spec, title, status, project, item.get("errors") or [], {k: v for k, v in item.items() if k not in {"id", "spec", "file", "title", "name", "status", "project", "projectName", "errors"}}))
    if records:
        return records
    failed = {_spec_compare_key(s) for s in inventory.get("failed_specs") or []}
    passed = {_spec_compare_key(s) for s in inventory.get("passed_specs") or []}
    all_specs = list(inventory.get("all_specs") or inventory.get("target_args") or [])
    if not all_specs:
        all_specs = list(inventory.get("failed_specs") or []) + list(inventory.get("passed_specs") or [])
    seen: set[str] = set()
    for spec in all_specs:
        display = _normalize_existing_spec_path(spec, root=root)
        key = _spec_compare_key(display)
        if not key or key in seen:
            continue
        seen.add(key)
        status = "failed" if key in failed else ("passed" if key in passed or failed else "unknown")
        records.append(_case_record(display, "", status, "", [], {"granularity": "spec_file_fallback"}))
    return records


def _dedupe_case_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for rec in records or []:
        spec = _normalize_existing_spec_path(rec.get("spec") or rec.get("file"))
        if not spec:
            continue
        title = rec.get("title") or rec.get("name") or ""
        project = rec.get("projectName") or rec.get("project") or ""
        key = rec.get("id") or _test_case_id(spec, title, project)
        normalized = {**rec, "id": key, "spec": spec, "title": str(title or "").strip(), "projectName": project, "status": str(rec.get("status") or "unknown").lower()}
        if key not in merged:
            merged[key] = normalized
            order.append(key)
            continue
        old = merged[key]
        # Failed status has priority; otherwise keep the richer title/errors.
        if normalized.get("status") in {"failed", "timedout", "interrupted"}:
            old.update(normalized)
        elif old.get("status") not in {"failed", "timedout", "interrupted"}:
            if len(json.dumps(normalized, ensure_ascii=False)) > len(json.dumps(old, ensure_ascii=False)):
                old.update(normalized)
    return [merged[k] for k in order]


def _walk_playwright_json(data: Any, root: Path | None = None) -> dict[str, Any]:
    all_specs: set[str] = set()
    failed_specs: set[str] = set()
    passed_specs: set[str] = set()
    failed_tests: list[dict[str, Any]] = []
    all_test_cases: list[dict[str, Any]] = []
    spec_statuses: dict[str, str] = {}
    test_statuses: dict[str, str] = {}

    def norm_file(value: str) -> str:
        return _normalize_existing_spec_path(value, root=root)

    def final_status_for_test(test: dict[str, Any]) -> tuple[str, list[Any]]:
        results = [r for r in (test.get("results") or []) if isinstance(r, dict)]
        if results:
            status = str(results[-1].get("status") or "unknown").lower()
            errors: list[Any] = []
            for result in results:
                if str(result.get("status") or "").lower() in {"failed", "timedout", "interrupted"}:
                    errors.extend(result.get("errors") or ([result.get("error")] if result.get("error") else []))
            return status, errors
        status = str(test.get("status") or test.get("outcome") or "unknown").lower()
        return status, []

    def visit_suite(suite: dict[str, Any], inherited_file: str = "", inherited_titles: list[str] | None = None) -> None:
        inherited_titles = list(inherited_titles or [])
        file = norm_file(suite.get("file") or inherited_file or "")
        suite_title = str(suite.get("title") or "").strip()
        # Prefer Playwright's titlePath when available; it usually gives clean hierarchy.
        title_path = [str(x).strip() for x in (suite.get("titlePath") or inherited_titles) if str(x).strip()]
        if suite_title and (not title_path or title_path[-1] != suite_title):
            title_path.append(suite_title)
        for spec in suite.get("specs") or []:
            if not isinstance(spec, dict):
                continue
            spec_file = norm_file(spec.get("file") or file)
            if spec_file:
                all_specs.add(spec_file)
            title = _test_title_text(title_path, spec.get("title", ""))
            spec_failed = False
            spec_has_pass = False
            for test in spec.get("tests") or []:
                if not isinstance(test, dict):
                    continue
                project = test.get("projectName") or test.get("projectId") or ""
                status, errors = final_status_for_test(test)
                extra = {
                    "line": spec.get("line"),
                    "column": spec.get("column"),
                    "expectedStatus": test.get("expectedStatus"),
                    "outcome": test.get("outcome"),
                    "attempt_count": len(test.get("results") or []),
                }
                rec = _case_record(spec_file, title, status, project, errors, extra)
                all_test_cases.append(rec)
                test_statuses[rec["id"]] = status
                if status in {"failed", "timedout", "interrupted"}:
                    spec_failed = True
                    failed_tests.append(rec)
                elif status in {"passed", "skipped", "expected", "flaky"}:
                    spec_has_pass = True
            if spec_file:
                if spec_failed:
                    failed_specs.add(spec_file)
                    spec_statuses[spec_file] = "failed"
                elif spec_has_pass or spec.get("tests"):
                    passed_specs.add(spec_file)
                    spec_statuses.setdefault(spec_file, "passed")
        for child in suite.get("suites") or []:
            if isinstance(child, dict):
                visit_suite(child, file, title_path)

    if isinstance(data, dict):
        for suite in data.get("suites") or []:
            if isinstance(suite, dict):
                visit_suite(suite)
    all_test_cases = _dedupe_case_records(all_test_cases)
    failed_test_cases = [r for r in all_test_cases if str(r.get("status") or "").lower() in {"failed", "timedout", "interrupted"}]
    passed_test_cases = [r for r in all_test_cases if r.get("id") not in {x.get("id") for x in failed_test_cases} and str(r.get("status") or "").lower() in {"passed", "skipped", "expected", "flaky"}]
    return {
        "all_specs": sorted(all_specs),
        "failed_specs": sorted(failed_specs),
        "passed_specs": sorted(passed_specs - failed_specs),
        "failed_tests": failed_test_cases,
        "all_test_cases": all_test_cases,
        "failed_test_cases": failed_test_cases,
        "passed_test_cases": passed_test_cases,
        "test_case_count": len(all_test_cases),
        "failed_test_case_count": len(failed_test_cases),
        "passed_test_case_count": len(passed_test_cases),
        "spec_statuses": spec_statuses,
        "test_statuses": test_statuses,
    }

def _extract_failed_specs_from_stdout(text: str, root: Path) -> list[str]:
    """Extract failed spec files from Playwright console output.

    Important enterprise fix: migrated suites sometimes use `.specs.ts`
    instead of `.spec.ts`.  The previous regex missed `.specs.ts`, so
    the browser could execute and fail correctly while RCA/self-healing saw
    an empty failed inventory.
    """
    found: set[str] = set()
    normalized = (text or "").replace("\\", "/")
    patterns = [
        r"((?:[A-Za-z]:)?/?[\w ._@()\-/]+?\.(?:specs|spec|test)\.(?:ts|tsx|js|jsx|mjs|cjs))(?::\d+)?",
        r"›\s*((?:tests|specs|e2e|src)/[^\n:]+?\.(?:specs|spec|test)\.(?:ts|tsx|js|jsx|mjs|cjs))(?::\d+)?",
    ]
    ignored_prefixes = {"node_modules", "playwright-report", "test-results", "reports"}
    for pattern in patterns:
        for m in re.finditer(pattern, normalized, flags=re.I):
            value = m.group(1).strip().strip('"\'`')
            # Trim terminal line prefixes and absolute paths back to project-relative paths.
            value = re.sub(r"^.*?(?=(?:tests|specs|e2e|src)/)", "", value)
            value = value.replace("//", "/")
            if not value or any(part.lower() in ignored_prefixes for part in Path(value).parts):
                continue
            if value.lower().endswith(SPEC_SUFFIXES):
                value = _normalize_existing_spec_path(value, root=root)
                if value and _is_tests_folder_executable_spec(value, root=root):
                    found.add(value)
    # As another fallback, scan generated test-results folders; Playwright often
    # creates folders whose names include the spec filename when a test fails.
    for base in [root / "test-results", root / "reports" / "existing-framework" / "test-results"]:
        if not base.exists():
            continue
        for path in base.rglob("*"):
            name = str(path).replace("\\", "/")
            for m in re.finditer(r"((?:tests|specs|e2e|src)/[^\s]+?\.(?:specs|spec|test)\.(?:ts|tsx|js|jsx|mjs|cjs))", name, flags=re.I):
                value = m.group(1)
                value = _normalize_existing_spec_path(value, root=root)
                if value and _is_tests_folder_executable_spec(value, root=root):
                    found.add(value)
    return sorted(found)


def _write_failed_inventory(root: Path, execution: dict[str, Any], targets: list[str], source: str) -> dict[str, Any]:
    parsed = {"all_specs": [], "failed_specs": [], "passed_specs": [], "failed_tests": [], "spec_statuses": {}}
    if EXISTING_RESULTS_JSON.exists():
        try:
            data = json.loads(EXISTING_RESULTS_JSON.read_text(encoding="utf-8", errors="replace"))
            parsed = _walk_playwright_json(data, root=root)
        except Exception as exc:
            parsed["json_parse_error"] = f"{type(exc).__name__}: {exc}"

    failed_specs = parsed.get("failed_specs") or []
    extraction_note = ""
    stdout_text = str(execution.get("stdout", "")) + "\n" + str(execution.get("stderr", "")) + "\n" + str(execution.get("error", ""))

    if not failed_specs and not execution.get("ok"):
        failed_specs = _extract_failed_specs_from_stdout(stdout_text, root)
        if failed_specs:
            extraction_note = "Failed specs were extracted from Playwright console output because JSON reporter output was unavailable or incomplete."

    # Safe fallback: if Playwright returned non-zero and exactly one/few explicit
    # targets were executed, keep the RCA pipeline unblocked by treating those
    # targets as failed. This is safer than silently blocking Explain/Fix/Rerun.
    # For large full-suite runs we avoid marking every spec failed unless there
    # is no other evidence and the target set is small enough to be reviewable.
    if not failed_specs and not execution.get("ok"):
        explicit_targets = [_strip_playwright_line_selector(t) for t in (targets or []) if _is_tests_folder_executable_spec(str(t), root=root)]
        if 1 <= len(explicit_targets) <= 50:
            failed_specs = explicit_targets
            extraction_note = (
                "Playwright failed but JSON/console parsing did not identify exact failed specs. "
                "Because this run used explicit spec targets, those selected specs were carried into RCA/self-healing inventory. Review before auto-fix."
            )
        else:
            extraction_note = (
                "Execution failed but no exact failed spec could be extracted. "
                "RCA report will explain the execution/startup failure; auto-fix remains blocked until a failed spec is identified."
            )

    failed_specs = sorted(dict.fromkeys(_normalize_existing_spec_path(s, root=root) for s in failed_specs if str(s).strip()))
    failed_specs = [s for s in failed_specs if s]
    all_specs = sorted(dict.fromkeys([*(_normalize_existing_spec_path(s, root=root) for s in (parsed.get("all_specs") or [])), *(_normalize_existing_spec_path(s, root=root) for s in (targets or [])), *failed_specs]))
    passed_specs = [_normalize_existing_spec_path(s, root=root) for s in (parsed.get("passed_specs") or []) if _normalize_existing_spec_path(s, root=root)]
    if not passed_specs:
        passed_specs = [s for s in all_specs if _spec_compare_key(s) not in {_spec_compare_key(x) for x in failed_specs}]
    failed_tests = parsed.get("failed_tests") or []
    all_test_cases = _dedupe_case_records(parsed.get("all_test_cases") or [])
    failed_test_cases = _dedupe_case_records(parsed.get("failed_test_cases") or failed_tests or [])
    passed_test_cases = _dedupe_case_records(parsed.get("passed_test_cases") or [])
    if failed_specs and not failed_tests:
        failed_tests = [_case_record(s, "Failure detected from Playwright console/output inventory", "failed", "", [{"message": stdout_text[-6000:]}], {"granularity": "spec_file_fallback"}) for s in failed_specs[:50]]
        failed_test_cases = _dedupe_case_records(failed_tests)
    if not all_test_cases:
        # Legacy/no-JSON fallback: combined report will clearly state spec-file granularity.
        fallback_cases = []
        failed_keys = {_spec_compare_key(s) for s in failed_specs}
        for s in all_specs:
            status = "failed" if _spec_compare_key(s) in failed_keys else "passed"
            fallback_cases.append(_case_record(s, "", status, "", [], {"granularity": "spec_file_fallback"}))
        all_test_cases = _dedupe_case_records(fallback_cases)
    if not failed_test_cases:
        failed_keys = {_spec_compare_key(s) for s in failed_specs}
        failed_test_cases = [r for r in all_test_cases if _spec_compare_key(r.get("spec")) in failed_keys or str(r.get("status") or "").lower() in {"failed", "timedout", "interrupted"}]
    if not passed_test_cases:
        failed_ids = {r.get("id") for r in failed_test_cases}
        passed_test_cases = [r for r in all_test_cases if r.get("id") not in failed_ids and str(r.get("status") or "").lower() not in {"failed", "timedout", "interrupted"}]

    inventory = {
        "ok": True,
        "source": source,
        "framework_path": str(root),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "target_args": [_normalize_existing_spec_path(t, root=root) for t in targets],
        "all_specs": all_specs,
        "passed_specs": sorted(dict.fromkeys(passed_specs), key=_spec_compare_key),
        "failed_specs": failed_specs,
        "failed_count": len(set(_spec_compare_key(s) for s in failed_specs)),
        "failed_tests": failed_test_cases,
        "all_test_cases": all_test_cases,
        "passed_test_cases": passed_test_cases,
        "failed_test_cases": failed_test_cases,
        "test_case_count": len(all_test_cases),
        "passed_test_case_count": len(passed_test_cases),
        "failed_test_case_count": len(failed_test_cases),
        "inventory_granularity": "test_case" if any(r.get("granularity") != "spec_file_fallback" for r in all_test_cases) else "spec_file_fallback",
        "spec_statuses": parsed.get("spec_statuses") or {s: ("failed" if _spec_compare_key(s) in {_spec_compare_key(x) for x in failed_specs} else "passed") for s in all_specs},
        "test_statuses": parsed.get("test_statuses") or {r.get("id"): r.get("status") for r in all_test_cases if r.get("id")},
        "results_json": "generated-playwright/reports/existing-framework/results.json" if EXISTING_RESULTS_JSON.exists() else "not_available",
        "native_html_report": "generated-playwright/reports/existing-framework/html/index.html",
        "execution_console_log": str(root / "reports" / "existing-framework" / "execution-console.log"),
        "extraction_note": extraction_note,
        "note": "Existing-framework RCA/self-healing uses failed_specs only. Reports use test-case level counts when Playwright JSON is available; otherwise they clearly fall back to spec-file granularity.",
    }
    EXISTING_INVENTORY_JSON.write_text(json.dumps(inventory, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return inventory


def execute_existing_framework(
    framework_path: str,
    project: str = "chromium",
    headed: bool = True,
    base_url: str = "",
    execution_mode: str = "sequential",
    shards: int = 1,
    targets: str = "",
    test_command: str = "",
    auto_install: bool = True,
    use_mcp_assist: bool = True,
    run_role: str = "first_run",
) -> dict[str, Any]:
    _ensure_dirs()
    root = _resolve_framework_path(framework_path)
    # Understanding is cheap/static and ensures the latest folder location is persisted.
    intelligence = analyze_existing_framework(str(root), provider="deterministic", base_url=base_url)
    mcp_readiness = {"enabled": False}
    if use_mcp_assist:
        try:
            log_event("existing_framework_mcp", "Preparing Microsoft Playwright MCP assist in visible-browser mode.", progress=12, details={"framework_path": str(root)})
            write_playwright_mcp_configs(headless=False)
            mcp_readiness = mcp_status(headless=False)
        except Exception as exc:
            mcp_readiness = {"enabled": True, "ok": False, "error": f"{type(exc).__name__}: {exc}", "message": "MCP assist failed safely; deterministic Playwright execution will continue."}
    runtime = _ensure_runtime(root, auto_install=auto_install)
    if not runtime.get("ok"):
        _write_fallback_html("Existing framework runtime preflight failed", runtime)
        report = {"ok": False, "stage": "existing_framework_runtime_preflight_failed", "runtime_preflight": runtime, "framework_intelligence": intelligence, "framework_path": str(root), "error": runtime.get("error"), "message": runtime.get("error") or "Runtime preflight failed before Playwright could start."}
        _persist_execution_report(report)
        log_event("existing_framework", report["message"], status="error", progress=100, details=report)
        return report
    # Clean previous forced report paths inside the external repo and inside pipeline artifacts.
    for p in [root / "reports" / "existing-framework", EXISTING_HTML_DIR]:
        if p.exists():
            shutil.rmtree(p, ignore_errors=True)
    (root / "reports" / "existing-framework" / "html").mkdir(parents=True, exist_ok=True)
    _mark_playwright_report_in_progress(root, "Existing framework execution in progress", {"mode": execution_mode, "project": project, "headed": headed})
    target_args = _parse_target_patterns(targets)
    discovered_scope = _discover_playwright_test_targets(root)
    if not target_args and not test_command.strip():
        target_args = list(discovered_scope.get("targets") or [])
    effective_base_url = normalize_base_url(base_url)
    env = {
        **os.environ.copy(),
        "PLAYWRIGHT_HTML_OPEN": "never",
        "PLAYWRIGHT_HTML_OUTPUT_DIR": "reports/existing-framework/html",
        "PLAYWRIGHT_JSON_OUTPUT_NAME": "reports/existing-framework/results.json",
        "PW_WORKERS": "1",
        "CI": "false" if headed else os.environ.get("CI", ""),
        "HEADED": "true" if headed else "false",
        "HEADLESS": "false" if headed else "true",
        "PW_HEADLESS": "false" if headed else "true",
        "PLAYWRIGHT_HEADLESS": "false" if headed else "true",
        "PLAYWRIGHT_MCP_ENABLED": "true" if use_mcp_assist else "false",
        "PLAYWRIGHT_MCP_HEADLESS": "false" if headed else "true",
        "HEADLESS": "false" if headed else "true",
        "BROWSER": _normalize_project(project) or os.environ.get("BROWSER", "chromium"),
        "ASTRAHEAL_MAX_EXPLICIT_WAIT_MS": str(_astraheal_max_wait_ms()),
        "ASTRAHEAL_MAX_TEST_TIMEOUT_MS": str(_astraheal_max_wait_ms()),
    }
    if effective_base_url:
        env["BASE_URL"] = effective_base_url
        env["TEST_BASE_URL"] = effective_base_url
    alias_env = runtime_env_for_tsconfig_aliases(root, output_dir=root / "reports" / "existing-framework", base_env=env)
    if alias_env:
        env.update(alias_env)
        log_event(
            "existing_framework",
            "TypeScript path-alias runtime resolver prepared for Playwright execution.",
            progress=26,
            details=_alias_runtime_env_summary(env),
        )
    args = _build_command(root, project, headed, target_args, test_command=test_command)
    mode = (execution_mode or "sequential").strip().lower()
    if mode == "distributed" and not test_command.strip():
        # Existing-framework mode intentionally avoids silently running only one shard.
        # True distributed orchestration can be added later, but the safe default is
        # to execute the complete selected scope in one Playwright process.
        log_event("existing_framework", "Distributed was requested for existing-framework mode; running the complete selected scope sequentially to avoid partial shard execution.", status="warning", progress=27, details={"requested_shards": shards})
        mode = "sequential_safe_fallback"
    if not target_args and not test_command.strip():
        msg = "No executable Playwright spec/test files were discovered. AstraHeal recursively checked Playwright testDir, nested test folders such as tests/** and src/test/specs/**, monorepo paths, and executable Playwright code evidence. Feature files under features/** are intentionally skipped in the Run & Fix workflow."
        details = {"message": msg, "framework_path": str(root), "discovered_scope": discovered_scope}
        _write_fallback_html("Existing framework spec discovery failed", details)
        report = {"ok": False, "stage": "existing_framework_no_specs_found", "framework_path": str(root), "discovered_test_scope": discovered_scope, "error": msg, "message": msg}
        _persist_execution_report(report)
        log_event("existing_framework", msg, status="error", progress=100, details=details)
        return report
    log_event("existing_framework", "Executing existing Playwright framework in-place with discovered spec scope. Requirement/testcase/codegen phases are bypassed.", progress=28, details={"framework_path": str(root), "targets": target_args, "headed": headed, "project": _normalize_project(project) or "auto/all", "discovery_strategy": discovered_scope.get("strategy"), "max_wait_ms": _astraheal_max_wait_ms(), "tsconfig_path_alias_runtime": _alias_runtime_env_summary(env), "timeout_policy": "Default Playwright test/action/navigation waits are capped at 30000ms by AstraHeal where the runner/config is under AstraHeal control."})
    result = _run_streaming(args, root, env, "Existing framework execution", 32, 92)
    evidence = _playwright_execution_evidence(root, result)
    # If Playwright exits without any sign of test execution/report creation, mark
    # it as a real failure instead of presenting a misleading completed progress bar.
    if evidence.get("no_tests_found_message") or not evidence.get("likely_process_started"):
        result["ok"] = False
        result["execution_start_validation_error"] = (
            "Playwright process did not produce clear test-start/report evidence. "
            "Open the generated launcher script and execution-console.log under the external framework's reports/existing-framework folder for exact command output."
        )
    artifacts = _copy_external_artifacts(root)
    inventory = _write_failed_inventory(root, result, target_args, source="existing_framework_execution")
    first_run_stage_report: Path | None = None
    if str(run_role or "first_run") == "first_run":
        try:
            first_run_stage_report = _write_sequential_first_run_playwright_report(root, inventory, result)
            _write_latest_playwright_router(
                "Latest Playwright report: first sequential/local run",
                "<p>The latest execution stage is the original first run. Open the first-run report for exact passed/failed test-case details and the native Playwright HTML snapshot.</p>",
                [("Open exact first-run Playwright report", "/artifacts/reports/existing-framework/first-run-playwright-report.html"), ("Open native first-run HTML snapshot", "/artifacts/reports/existing-framework/first-run-native-html/index.html"), ("Open combined first-run + rerun report", "/artifacts/reports/existing-framework/consolidated-report.html")],
            )
        except Exception as exc:
            log_event("existing_framework_report", f"Sequential first-run report snapshot warning: {type(exc).__name__}: {exc}", status="warning", progress=100)
    robust_history = record_execution_history(root, inventory, result)
    report = {
        "ok": bool(result.get("ok")),
        "stage": "existing_framework_execution_completed",
        "mode": "headed" if headed else "headless",
        "execution_mode": mode,
        "framework_path": str(root),
        "project": _normalize_project(project) or "auto/all",
        "base_url": effective_base_url,
        "targets": target_args,
        "discovered_test_scope": discovered_scope,
        "runtime_preflight": runtime,
        "mcp_assist": mcp_readiness,
        "framework_intelligence": intelligence,
        "execution": result,
        "tsconfig_path_alias_runtime": _alias_runtime_env_summary(env),
        "timeout_policy": {"max_wait_ms": _astraheal_max_wait_ms(), "cli_timeout_applied": True, "note": "AstraHeal default runner passes --timeout=max_wait_ms. Generated scripts/config also cap action/navigation waits to 30000ms or less."},
        "execution_start_evidence": evidence,
        "artifact_normalization": artifacts,
        "failed_test_inventory": inventory,
        "robust_rca_history": robust_history,
        "playwright_html_report_url": (f"/artifacts/reports/existing-framework/{first_run_stage_report.name}" if first_run_stage_report else "/artifacts/reports/existing-framework/latest-playwright-report.html"),
        "message": "Existing framework execution completed in-place. If failures exist, run Existing Framework RCA/Self-Healing; failed-only scope is already recorded.",
        "run_role": run_role,
    }
    if str(run_role or "first_run") == "first_run":
        try:
            _record_first_run_baseline(root, inventory, execution_report=report)
        except Exception as exc:
            report["first_run_baseline_warning"] = f"{type(exc).__name__}: {exc}"
    (EXISTING_REPORTS_DIR / "execution-report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    log_event("existing_framework", "Existing framework execution finished and failed-only inventory was recorded.", status="done" if result.get("ok") else "warning", progress=100, details={"ok": result.get("ok"), "failed_count": inventory.get("failed_count")})
    return report


def read_existing_failed_inventory() -> dict[str, Any]:
    if not EXISTING_INVENTORY_JSON.exists():
        return {"ok": False, "error": "No existing-framework failed inventory found. Execute the existing framework first.", "path": str(EXISTING_INVENTORY_JSON)}
    try:
        data = json.loads(EXISTING_INVENTORY_JSON.read_text(encoding="utf-8", errors="replace"))
        data["ok"] = True
        return data
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}", "path": str(EXISTING_INVENTORY_JSON)}


def _read_last_execution_inventory() -> dict[str, Any]:
    """Recover failed-test inventory from the latest execution report.

    This protects the agentic handoff when failed-tests.json is accidentally
    overwritten, missing, or stale.  The GUI must not silently skip failed-only
    rerun after a first run clearly produced failures.
    """
    report_path = EXISTING_REPORTS_DIR / "execution-report.json"
    if not report_path.exists():
        return {"ok": False, "error": "execution-report.json not found"}
    try:
        report = json.loads(report_path.read_text(encoding="utf-8", errors="replace"))
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    inv = report.get("failed_test_inventory") or {}
    if inv.get("failed_specs"):
        inv["ok"] = True
        inv["source"] = str(inv.get("source") or "execution-report.json fallback")
        inv["recovered_from_execution_report"] = True
        return inv
    return {"ok": False, "error": "No failed_specs in latest execution report", "execution_report_stage": report.get("stage")}


def _read_last_self_heal_failed_specs() -> dict[str, Any]:
    report_path = EXISTING_SELF_HEAL_JSON
    if not report_path.exists():
        return {"ok": False, "error": "self-healing-report.json not found"}
    try:
        report = json.loads(report_path.read_text(encoding="utf-8", errors="replace"))
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    rca = report.get("root_cause") or {}
    specs = [str(s).replace("\\", "/") for s in (rca.get("failed_specs") or []) if str(s).strip()]
    if not specs:
        return {"ok": False, "error": "No failed_specs in self-healing report"}
    return {
        "ok": True,
        "source": "self-healing-report.json fallback",
        "framework_path": report.get("framework_path") or rca.get("framework_path"),
        "failed_specs": specs,
        "failed_count": len(set(specs)),
        "all_specs": rca.get("failed_inventory", {}).get("all_specs") or specs,
        "passed_specs": rca.get("failed_inventory", {}).get("passed_specs") or [],
        "failed_tests": rca.get("failed_inventory", {}).get("failed_tests") or [],
        "recovered_from_self_healing_report": True,
    }


def _best_failed_inventory_for_followup() -> dict[str, Any]:
    # If a failed-only rerun has already happened, the current scope must come
    # from the latest rerun iteration, not from stale first-run/self-heal files.
    # This preserves the exact iteration flow: original run -> rerun 1 remaining
    # failures -> rerun 2 remaining failures -> manual review.
    remaining_from_ledger = _latest_failed_only_remaining_inventory()
    if remaining_from_ledger.get("ledger_iteration_count"):
        try:
            EXISTING_INVENTORY_JSON.write_text(json.dumps(remaining_from_ledger, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        except Exception:
            pass
        return remaining_from_ledger

    primary = read_existing_failed_inventory()
    if primary.get("ok") and primary.get("failed_specs"):
        return primary
    recovered = _read_last_execution_inventory()
    if recovered.get("ok") and recovered.get("failed_specs"):
        EXISTING_INVENTORY_JSON.write_text(json.dumps(recovered, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return recovered
    recovered2 = _read_last_self_heal_failed_specs()
    if recovered2.get("ok") and recovered2.get("failed_specs"):
        EXISTING_INVENTORY_JSON.write_text(json.dumps(recovered2, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return recovered2
    # preserve the original error but attach fallbacks for transparent debugging
    primary.setdefault("fallback_execution_inventory", recovered)
    primary.setdefault("fallback_self_heal_inventory", recovered2)
    return primary


def _tokenize_for_scope(value: str) -> list[str]:
    tokens = re.split(r"[^a-zA-Z0-9]+", (value or "").lower())
    stop = {"test", "tests", "spec", "specs", "e2e", "all", "page", "object", "objects", "ts", "tsx", "js", "jsx", "src"}
    return [t for t in tokens if len(t) >= 3 and t not in stop]


def _heuristic_related_files(root: Path, resolved_specs: list[Path], failed_specs: list[str], limit: int = 80) -> list[Path]:
    """Find likely page/pageObject/helper files when imports are missing or alias-heavy.

    This is a controlled fallback.  It does not open the entire repo to Codex; it
    only adds files from conventional framework layers and only if they match
    feature tokens from the failed spec names/paths.
    """
    tokens: set[str] = set()
    for spec in failed_specs:
        tokens.update(_tokenize_for_scope(spec))
    for spec in resolved_specs:
        tokens.update(_tokenize_for_scope(spec.stem))
        tokens.update(_tokenize_for_scope(str(spec.parent.relative_to(root)) if spec.exists() else ""))
    if not tokens:
        return []
    conventional_dirs = [
        "pages", "pageObjects", "pageobjects", "page-objects",
        "src/pages", "src/pageObjects", "src/pageobjects", "src/page-objects",
        "utils", "src/utils", "helpers", "src/helpers",
        "fixtures", "tests/fixtures", "components", "src/components",
    ]
    hits: list[Path] = []
    seen: set[str] = set()
    for folder in conventional_dirs:
        base = root / folder
        if not base.exists() or not base.is_dir():
            continue
        for path in base.rglob("*"):
            if len(hits) >= limit:
                break
            if not path.is_file() or _is_ignored(path, root) or path.suffix.lower() not in TS_SUFFIXES:
                continue
            rel = _rel_to(path, root).lower()
            name_tokens = set(_tokenize_for_scope(path.stem))
            # Prefer filename/path token matches.  Content scanning is used only
            # for smaller files to avoid broad, slow scans in enterprise repos.
            match = bool(tokens.intersection(name_tokens)) or any(t in rel for t in tokens)
            if not match and path.stat().st_size < 120000:
                content = _read(path, limit=120000).lower()
                match = any(t in content for t in tokens)
            if match:
                key = str(path.resolve()).lower()
                if key not in seen:
                    hits.append(path.resolve())
                    seen.add(key)
        if len(hits) >= limit:
            break
    return hits


def _scope_from_failed_specs(root: Path, failed_specs: list[str]) -> dict[str, Any]:
    scoped: set[Path] = set()
    queue: list[Path] = []
    resolution_details: list[dict[str, Any]] = []
    provenance: dict[str, set[str]] = {}

    def add(path: Path, reason: str, *, enqueue: bool = False) -> None:
        try:
            resolved = path.resolve()
        except Exception:
            return
        if not resolved.exists() or not resolved.is_file() or _is_ignored(resolved, root):
            return
        scoped.add(resolved)
        rel = _rel_to(resolved, root)
        provenance.setdefault(rel, set()).add(reason)
        if enqueue and resolved not in queue:
            queue.append(resolved)

    for spec in failed_specs:
        resolved_candidates = _candidate_files_for_import_or_path(root, spec)
        spec_candidates = [p for p in resolved_candidates if p.name.lower().endswith(SPEC_SUFFIXES)] or resolved_candidates
        if spec_candidates:
            chosen = spec_candidates[0].resolve()
            add(chosen, "failed_spec", enqueue=True)
            resolution_details.append({"input": spec, "resolved": _rel_to(chosen, root), "candidate_count": len(spec_candidates)})
        else:
            resolution_details.append({"input": spec, "resolved": None, "candidate_count": 0, "warning": "Spec path could not be resolved under framework root."})

    # Walk local/alias imports up to five levels. This is the primary,
    # explainable write scope: failed spec -> page -> locator/object -> helper.
    seen: set[Path] = set()
    depth = 0
    while queue and depth < 5:
        next_queue: list[Path] = []
        for file in queue:
            if file in seen:
                continue
            seen.add(file)
            text = _read(file, limit=120000)
            for imp in _extract_import_paths(text):
                found = _resolve_import(file, imp, root)
                if found and found.suffix.lower() in TS_SUFFIXES:
                    found = found.resolve()
                    was_new = found not in scoped
                    add(found, f"imported_dependency_level_{depth + 1}")
                    if was_new:
                        next_queue.append(found)
        queue = next_queue
        depth += 1

    # Config files are candidates only when they exist. They stay visible in the
    # approval scope because module-resolution/runtime failures may require them.
    for name in [
        "playwright.config.ts", "playwright.config.js", "playwright.config.mjs", "playwright.config.cjs",
        "tsconfig.json", "jsconfig.json", "package.json", "package-lock.json", "pnpm-lock.yaml", "yarn.lock",
    ]:
        p = root / name
        if p.is_file() and not _is_ignored(p, root):
            add(p, "runtime_or_configuration_candidate")

    # Shared helper files are included only when actually present. Their reason is
    # shown separately so the user can remove them from the approval textarea.
    for pattern in [
        "**/BasePage.ts", "**/base.page.ts", "**/basePage.ts", "**/BasePage.js",
        "**/locatorFactory.ts", "**/locators.ts", "**/SmartLocator.ts",
        "**/safeActions.ts", "**/actions.ts", "**/fixtures/*.ts",
    ]:
        for p in root.glob(pattern):
            if p.is_file() and not _is_ignored(p, root):
                add(p, "shared_framework_helper_candidate")

    heuristic_hits = _heuristic_related_files(root, [p for p in scoped if p.name.lower().endswith(SPEC_SUFFIXES)], failed_specs)
    for p in heuristic_hits:
        add(p, "token_matched_fallback_candidate")

    rel = sorted(_rel_to(p, root) for p in scoped if p.exists())
    scope_mode = "import_graph"
    if heuristic_hits:
        scope_mode = "import_graph_plus_token_matched_fallback"
    if not rel and failed_specs:
        scope_mode = "blocked_unresolved_failed_specs"

    groups = {
        "failed_spec_files": sorted(k for k, reasons in provenance.items() if "failed_spec" in reasons),
        "imported_dependency_files": sorted(k for k, reasons in provenance.items() if any(r.startswith("imported_dependency_level_") for r in reasons)),
        "runtime_config_candidates": sorted(k for k, reasons in provenance.items() if "runtime_or_configuration_candidate" in reasons),
        "shared_helper_candidates": sorted(k for k, reasons in provenance.items() if "shared_framework_helper_candidate" in reasons),
        "heuristic_fallback_candidates": sorted(k for k, reasons in provenance.items() if "token_matched_fallback_candidate" in reasons),
    }
    recommended = sorted(dict.fromkeys([*groups["imported_dependency_files"], *groups["shared_helper_candidates"], *groups["runtime_config_candidates"], *groups["failed_spec_files"]]))

    return {
        "ok": bool(rel),
        "framework_path": str(root),
        "failed_specs": failed_specs,
        "allowed_files": rel,
        "recommended_patch_files": recommended,
        "scope_groups": groups,
        "file_reasons": {k: sorted(v) for k, v in sorted(provenance.items())},
        "resolution_details": resolution_details,
        "scope_mode": scope_mode,
        "heuristic_related_files": groups["heuristic_fallback_candidates"],
        "message": (
            "Write approval is restricted to failed specs, their resolved import graph, existing runtime/config files, and clearly identified shared helper candidates. Whole-workspace expansion is not automatic."
            if rel else
            "No scoped files could be resolved from failed specs. Confirm failed spec paths are under the selected framework root."
        ),
    }


def _html_attr(value: Any) -> str:
    return _html(value).replace("'", "&#39;")


_LOCATOR_PATTERNS: list[tuple[str, str]] = [
    ("getByTestId", r"\.(?:getByTestId)\s*\(\s*(['\"`])([^'\"`]{1,180})\1"),
    ("getByRole", r"\.(?:getByRole)\s*\(\s*(['\"`])([^'\"`]{1,80})\1(?:\s*,\s*\{[^)]*?name\s*:\s*(?:/([^/]{1,120})/[a-z]*|(['\"`])([^'\"`]{1,160})\4))?"),
    ("getByLabel", r"\.(?:getByLabel)\s*\(\s*(['\"`])([^'\"`]{1,180})\1"),
    ("getByPlaceholder", r"\.(?:getByPlaceholder)\s*\(\s*(['\"`])([^'\"`]{1,180})\1"),
    ("getByText", r"\.(?:getByText)\s*\(\s*(?:/([^/]{1,160})/[a-z]*|(['\"`])([^'\"`]{1,180})\2)"),
    ("locator", r"\.(?:locator)\s*\(\s*(['\"`])([^'\"`]{1,260})\1"),
]


def _looks_like_object_repository_file(rel: str) -> bool:
    low = (rel or "").lower().replace("\\", "/")
    return any(x in low for x in [
        "pageobject", "page-object", "pageobjects", "/objects/", "/locators/", "/selectors/",
        "/pages/", "basepage", "safeaction", "smartlocator",
    ]) and low.endswith(tuple(TS_SUFFIXES))


def _locator_risk(strategy: str, value: str) -> str:
    low = (value or "").lower()
    if strategy in {"getByTestId", "getByRole", "getByLabel", "getByPlaceholder"}:
        return "low"
    if strategy == "getByText":
        return "medium"
    if strategy == "locator" and ("xpath" in low or low.startswith("//") or "nth-child" in low or ":nth" in low or "text=" in low):
        return "high"
    if strategy == "locator" and re.search(r"[#.\[]", value or ""):
        return "medium"
    return "medium"


def _locator_human_selector(strategy: str, value: str, role: str = "", name: str = "") -> str:
    if strategy == "getByRole":
        return f"role={role or value}, name={name}" if name else f"role={role or value}"
    return f"{strategy}={value}"


def _extract_locator_records_from_file(path: Path, root: Path) -> list[dict[str, Any]]:
    text = _read(path, limit=220000)
    rel = _rel_to(path, root)
    records: list[dict[str, Any]] = []
    for strategy, pattern in _LOCATOR_PATTERNS:
        for m in re.finditer(pattern, text, flags=re.I | re.S):
            groups = list(m.groups())
            value = ""
            role = ""
            name = ""
            if strategy == "getByRole":
                role = groups[1] or ""
                name = (groups[2] or groups[4] or "").strip()
                value = name or role
            elif strategy == "getByText":
                value = (groups[0] or groups[2] or "").strip()
            else:
                value = (groups[1] if len(groups) > 1 else "").strip()
            if not value or any(x in value for x in ["${", "`+"]):
                dynamic = True
            else:
                dynamic = False
            line = text[:m.start()].count("\n") + 1
            records.append({
                "file": rel,
                "line": line,
                "strategy": strategy,
                "value": value[:220],
                "role": role[:80],
                "name": name[:160],
                "human_selector": _locator_human_selector(strategy, value, role=role, name=name),
                "risk": _locator_risk(strategy, value),
                "dynamic": dynamic,
                "source_snippet": re.sub(r"\s+", " ", text[max(0, m.start()-120):min(len(text), m.end()+120)]).strip()[:420],
            })
    return records


def _static_dom_evidence_files(root: Path, limit: int = 450) -> list[Path]:
    suffixes = {".html", ".htm", ".json", ".md", ".txt"}
    out: list[Path] = []
    for path in root.rglob("*"):
        if len(out) >= limit:
            break
        if not path.is_file():
            continue
        try:
            parts = {p.lower() for p in path.relative_to(root).parts}
        except Exception:
            parts = {p.lower() for p in path.parts}
        if parts.intersection({"node_modules", ".git", "dist", "build", ".next", "%appdata%", "%AppData%", ".npm", "npm-cache"}):
            continue
        if path.suffix.lower() in suffixes or path.name.lower() in {"error-context.md", "dom-snapshot.html", "aria-snapshot.yml"}:
            out.append(path)
    return out


def _static_dom_locator_status(root: Path, rec: dict[str, Any], evidence_texts: list[tuple[str, str]]) -> dict[str, Any]:
    strategy = str(rec.get("strategy") or "")
    value = str(rec.get("value") or "").strip()
    if not value:
        return {"status": "dynamic_or_empty_locator", "confidence": 0.0, "evidence_files": [], "note": "Locator value is dynamic/empty; live MCP/browser inspection is required."}
    search_terms: list[str] = []
    if strategy == "getByTestId":
        search_terms = [f'data-testid="{value}"', f"data-testid='{value}'", value]
    elif strategy == "getByRole":
        search_terms = [str(rec.get("name") or value), f'role="{rec.get("role") or value}"', f"role='{rec.get('role') or value}'"]
    elif strategy in {"getByText", "getByLabel", "getByPlaceholder"}:
        search_terms = [value]
    elif strategy == "locator":
        clean = value.strip()
        # For CSS id/class/attribute selectors, search for useful literal fragments only.
        bits = re.findall(r"[A-Za-z0-9_-]{3,}", clean)
        search_terms = bits[:5] or [clean]
    hits: list[str] = []
    for rel, text in evidence_texts:
        low = text.lower()
        if any(term and term.lower() in low for term in search_terms):
            hits.append(rel)
            if len(hits) >= 5:
                break
    if hits:
        return {"status": "verified_in_static_dom_or_snapshot_artifact", "confidence": 0.62, "evidence_files": hits, "note": "Matched local DOM/snapshot/artifact text. Live page-state verification is still recommended before patching."}
    return {"status": "not_found_in_static_artifacts_needs_live_playwright_mcp", "confidence": 0.28, "evidence_files": [], "note": "Not found in static artifacts. This is not a final failure because the element may appear only after navigation/login/scroll/modal state. Use Check failed element with Playwright MCP for exact live DOM/actionability evidence."}


def _write_object_repository_locator_audit_html(payload: dict[str, Any]) -> None:
    rows = []
    for rec in (payload.get("locators") or [])[:500]:
        rows.append(
            "<tr>"
            f"<td><code>{_html(rec.get('file'))}:{_html(rec.get('line'))}</code></td>"
            f"<td>{_html(rec.get('human_selector'))}</td>"
            f"<td>{_html(rec.get('risk'))}</td>"
            f"<td>{_html((rec.get('dom_verification') or {}).get('status'))}</td>"
            f"<td>{_html((rec.get('dom_verification') or {}).get('note'))}</td>"
            "</tr>"
        )
    summary = payload.get("summary") or {}
    html = f"""<!doctype html><html><head><meta charset='utf-8'/><title>Object Repository Locator Audit</title>
<style>body{{font-family:Segoe UI,Arial,sans-serif;background:#f8fafc;color:#0f172a;margin:24px}}.card{{background:white;border:1px solid #dbe3ef;border-radius:14px;padding:16px;margin:14px 0}}table{{width:100%;border-collapse:collapse;background:white}}td,th{{border:1px solid #cbd5e1;padding:8px;vertical-align:top}}th{{background:#1e293b;color:white}}code{{background:#0f172a;color:#dbeafe;padding:3px 6px;border-radius:6px}}.warn{{color:#b45309;font-weight:800}}.ok{{color:#16a34a;font-weight:800}}</style></head><body>
<h1>Object Repository Locator Audit</h1>
<div class='card'><p><b>Framework:</b> <code>{_html(payload.get('framework_path'))}</code></p><p><b>Total object-repository locators:</b> {_html(summary.get('total_locators'))} &nbsp; <b>Files scanned:</b> {_html(summary.get('object_repo_file_count'))}</p><p><b>Static/snapshot verified:</b> <span class='ok'>{_html(summary.get('static_verified_count'))}</span> &nbsp; <b>Need live MCP/page-state verification:</b> <span class='warn'>{_html(summary.get('needs_live_mcp_count'))}</span> &nbsp; <b>High-risk:</b> <span class='warn'>{_html(summary.get('high_risk_count'))}</span></p><p>{_html(payload.get('human_summary'))}</p></div>
<div class='card'><h2>How to read this audit</h2><p>This is a concise human-style object repository review. During framework learning AstraHeal reads locator files and page methods, checks locator style, and searches local DOM/snapshot/artifact evidence. A locator that is not found in static artifacts is not automatically wrong because many elements require login, route navigation, scroll, modal state, iframe, or mobile viewport. For an actual failed element, use <b>Check failed element with Playwright MCP</b> to inspect the live failed page state and generate the replacement locator.</p></div>
<div class='card'><h2>Locator matrix</h2><table><thead><tr><th>File:line</th><th>Locator</th><th>Risk</th><th>DOM/snapshot status</th><th>Action</th></tr></thead><tbody>{''.join(rows) or '<tr><td colspan="5">No object repository locators found.</td></tr>'}</tbody></table></div>
</body></html>"""
    EXISTING_OBJECT_REPO_LOCATOR_AUDIT_HTML.write_text(html, encoding="utf-8")


def audit_object_repository_locators(root: Path, base_url: str = "") -> dict[str, Any]:
    """Concise object repository locator audit used by Deep Learn.

    The audit is intentionally read-only. It checks locator definitions in pageObjects,
    pages and locator repositories, then performs best-effort static DOM/snapshot
    matching. Live page-state proof is left to MCP locator RCA so Deep Learn does
    not click through every business workflow or create false negatives.
    """
    root = Path(root).resolve()
    EXISTING_REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    log_event("module2_existing_framework", "Object repository audit: scanning pageObjects/pages/locator repository for locator definitions.", progress=62, details={"framework_path": str(root)})
    files = [p for p in _find_files(root, TS_SUFFIXES, limit=3500) if _looks_like_object_repository_file(_rel_to(p, root))]
    records: list[dict[str, Any]] = []
    for file in files:
        records.extend(_extract_locator_records_from_file(file, root))
    evidence_texts: list[tuple[str, str]] = []
    for path in _static_dom_evidence_files(root):
        txt = _read(path, limit=120000)
        if txt:
            evidence_texts.append((_rel_to(path, root), txt[:120000]))
    for rec in records:
        rec["dom_verification"] = _static_dom_locator_status(root, rec, evidence_texts)
    static_verified = sum(1 for r in records if (r.get("dom_verification") or {}).get("status") == "verified_in_static_dom_or_snapshot_artifact")
    needs_live = sum(1 for r in records if "needs_live" in str((r.get("dom_verification") or {}).get("status")))
    high_risk = sum(1 for r in records if r.get("risk") == "high")
    by_file = Counter(r.get("file") for r in records)
    by_strategy = Counter(r.get("strategy") for r in records)
    summary = {
        "total_locators": len(records),
        "object_repo_file_count": len(files),
        "static_verified_count": static_verified,
        "needs_live_mcp_count": needs_live,
        "high_risk_count": high_risk,
        "counts_by_strategy": dict(by_strategy),
        "top_locator_files": [{"file": f, "locator_count": c} for f, c in by_file.most_common(20)],
    }
    payload = {
        "ok": True,
        "stage": "object_repository_locator_audit_completed",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "framework_path": str(root),
        "base_url": normalize_base_url(base_url),
        "summary": summary,
        "locators": records[:1200],
        "object_repo_files": [_rel_to(p, root) for p in files[:300]],
        "report_url": "/artifacts/reports/existing-framework/object-repository-locator-audit.html",
        "human_summary": f"Scanned {len(files)} object/page/locator file(s), found {len(records)} locator definition(s), statically matched {static_verified}, and marked {needs_live} for live Playwright MCP verification when the related workflow fails.",
        "live_mcp_note": "Use Check failed element with Playwright MCP after a real failure. It inspects the failed page state and identifies whether the element is missing, detached, hidden, blocked by overlay, inside iframe/shadow DOM, or needs a new locator in the pageObject repository.",
    }
    EXISTING_OBJECT_REPO_LOCATOR_AUDIT_JSON.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    _write_object_repository_locator_audit_html(payload)
    log_event("module2_existing_framework", payload["human_summary"], status="done", progress=68, details={"summary": summary, "report_url": payload.get("report_url")})
    return payload


def _failure_text(inventory: dict[str, Any]) -> str:
    parts = [json.dumps(inventory.get("failed_tests", []), indent=2, ensure_ascii=False)[:12000]]
    execution_report = EXISTING_REPORTS_DIR / "execution-report.json"
    if execution_report.exists():
        try:
            data = json.loads(execution_report.read_text(encoding="utf-8", errors="replace"))
            parts.append(str(data.get("execution", {}).get("stdout", ""))[-6000:])
            parts.append(str(data.get("execution", {}).get("stderr", ""))[-6000:])
        except Exception:
            pass
    return "\n".join(parts)[-22000:]


def _build_auditable_rca_reasoning_checklist(root: Path, failed_specs: list[str], failure_text: str, scope: dict[str, Any] | None = None, mcp_locator_rca: dict[str, Any] | None = None) -> dict[str, Any]:
    """Create a visible RCA checklist without exposing hidden model chain-of-thought."""
    low = (failure_text or "").lower()
    mcp_locator_rca = mcp_locator_rca or {}
    scope = scope or {}

    def state(keys: list[str], positive: str, neutral: str = "Needs evidence") -> str:
        return positive if any(k in low for k in keys) else neutral

    module_name = _extract_missing_module_name(failure_text)
    checklist = [
        {"order": 1, "check": "Confirm failure belongs to selected failed specs only", "status": "done" if failed_specs else "blocked", "observable_evidence": failed_specs[:20], "fix_decision": "RCA/self-healing scope is restricted to failed specs and imported files only."},
        {"order": 2, "check": "Check Playwright/Node module resolution and TypeScript path aliases", "status": "module_resolution_failure_found" if _is_module_resolution_failure(failure_text) else "No module-resolution evidence", "observable_evidence": {"missing_module": module_name, "tsconfig_alias_runtime_needed": module_name.startswith("@") if module_name else False}, "fix_decision": "If present, fix tsconfig paths/package/Playwright runtime preload first. Do not run DOM locator MCP as the primary RCA for Cannot find module errors."},
        {"order": 3, "check": "Check whether failed locator or expected element exists in DOM/accessibility snapshot", "status": state(["locator", "getby", "tobevisible", "element(s) not found", "waiting for locator", "waiting for"], "locator_or_dom_evidence_found"), "observable_evidence": (mcp_locator_rca.get("failed_locator_or_action_candidates") or [])[:10], "fix_decision": "If absent, update pageObject locator or treat as product/data/environment issue before patching assertions."},
        {"order": 4, "check": "Validate locator strategy/address correctness", "status": state(["strict mode violation", "resolved to", "nth(", "aria-label", "xpath", "filter({ hastext"], "locator_strategy_needs_review"), "observable_evidence": "Look for strict-mode ambiguity, brittle nth selectors, stale text, role/name mismatch, data-testid changes, iframe/shadow DOM.", "fix_decision": "Prefer stable getByRole/getByTestId/getByLabel in pageObjects; keep framework style."},
        {"order": 5, "check": "Check interactability: visible, enabled, stable, not detached", "status": state(["not attached to the dom", "element is not attached", "not visible", "not enabled", "detached", "stable", "timeout", "locator.click"], "actionability_needs_review"), "observable_evidence": "Playwright actionability logs, trace, screenshot, video, error-context.md.", "fix_decision": "If locator is detached/not attached to DOM, use Playwright MCP/codegen/live DOM snapshot to generate a current locator, then patch pageObject or page method to re-query after DOM settles. Do not add blind waitForTimeout."},
        {"order": 6, "check": "Check viewport/page-size/scroll issue", "status": state(["outside of the viewport", "scrolling into view", "done scrolling", "footer", "mobile", "hamburger"], "viewport_or_scroll_signal_found"), "observable_evidence": "Element may exist lower on page, behind footer/header, or in mobile drawer based on screen size.", "fix_decision": "Use scrollIntoViewIfNeeded, viewport-aware helper, responsive locator, or mobile-specific page method."},
        {"order": 7, "check": "Check overlay, popup, permission dialog, modal interception", "status": state(["intercepts pointer events", "chakra-modal", "popup", "permission", "cookie", "geolocation", "modal", "dialog"], "overlay_or_popup_signal_found"), "observable_evidence": "Pointer-event interception logs, modal/header/body identifiers, screenshots/videos.", "fix_decision": "Dismiss/handle overlay in shared helper before click; avoid force:true by default."},
        {"order": 8, "check": "Check navigation/state synchronization", "status": state(["tohaveurl", "waitforurl", "navigation", "networkidle", "domcontentloaded", "received string"], "navigation_or_state_signal_found"), "observable_evidence": "URL mismatch, repeated same URL, skipped navigation, timeout waiting for state.", "fix_decision": "Patch page navigation helper with deterministic state/URL waits; avoid blind sleeps."},
        {"order": 9, "check": "Check test data, auth/session, API/backend, VPN/proxy/environment", "status": state(["login", "auth", "401", "403", "500", "econn", "net::", "ssl", "certificate", "vpn", "timed_out"], "environment_or_data_signal_found"), "observable_evidence": "Network/API errors, login not visible, account feature not available, blocked endpoints, timeout.", "fix_decision": "Do not fake pass. Validate environment/data first; patch only if framework wait/login helper is unstable."},
        {"order": 10, "check": "Check assertion/product behavior drift", "status": state(["expect(", "expected", "received", "assert", "should be visible"], "assertion_or_behavior_signal_found"), "observable_evidence": "Expected vs received mismatch and screenshots.", "fix_decision": "Only update assertions after confirming product behavior changed and human/business review allows it."},
        {"order": 11, "check": "Select safest self-healing patch location", "status": "done", "observable_evidence": scope.get("allowed_files", [])[:30], "fix_decision": "Patch config/package/runtime alias setup for module-resolution failures; patch locator/pageObjects only for browser DOM failures."},
    ]
    return {"ok": True, "generated_at": datetime.now().isoformat(timespec="seconds"), "name": "Auditable RCA reasoning checklist", "privacy_note": "This is a human-readable checklist of observable evidence and decisions, not hidden chain-of-thought.", "failed_specs": failed_specs, "checks": checklist, "summary": "RCA first checks Playwright/Node module resolution and tsconfig aliases, then locator existence, locator strategy, interactability, viewport/scroll, overlays/popups, navigation, environment/data, and assertion drift before recommending a patch."}


def _write_existing_rca_html(payload: dict[str, Any]) -> Path:
    EXISTING_REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    checklist = ((payload.get("auditable_rca_reasoning_checklist") or {}).get("checks") or [])
    check_rows = []
    for c in checklist:
        check_rows.append(f"<tr><td>{_html(c.get('order'))}</td><td>{_html(c.get('check'))}</td><td>{_html(c.get('status'))}</td><td><pre>{_html(json.dumps(c.get('observable_evidence'), indent=2, ensure_ascii=False)[:3000])}</pre></td><td>{_html(c.get('fix_decision'))}</td></tr>")
    signal_rows = ''.join(f"<li><b>{_html(sig.get('kind'))}</b> ({_html(sig.get('confidence'))}) — {_html(sig.get('recommendation'))}</li>" for sig in (payload.get("signals") or []))
    ext = payload.get("external_research_context") or {}
    ext_queries = ''.join(f"<li><code>{_html(q)}</code></li>" for q in (ext.get('queries') or [])[:12])
    common = payload.get("common_cause_analysis") or {}
    common_rows = []
    for g in (common.get("groups") or [])[:20]:
        common_rows.append(f"<tr><td>{_html(g.get('component'))}</td><td>{_html(g.get('failure_kind'))}</td><td>{_html(g.get('impacted_count'))}</td><td><pre>{_html(json.dumps(g.get('impacted_specs') or [], indent=2, ensure_ascii=False)[:2500])}</pre></td><td>{_html(g.get('recommended_fix_priority'))}</td><td>{_html(g.get('why'))}</td></tr>")
    fix_plan = ''.join('<li>'+_html(x)+'</li>' for x in (payload.get('recommended_fix_plan') or []))
    case_rows = []
    for rec in ((payload.get('plain_english_failure_report') or {}).get('test_case_outcomes') or []):
        cls = 'ok' if rec.get('status') == 'passed' else ('bad' if rec.get('status') == 'failed' else 'warn')
        case_rows.append(f"<tr><td><code>{_html(rec.get('spec'))}</code></td><td>{_html(rec.get('line'))}</td><td>{_html(rec.get('test'))}</td><td class='{cls}'>{_html(rec.get('status'))}</td><td>{_html(rec.get('plain_english_reason'))}</td><td>{_html(rec.get('suggested_fix_area'))}</td></tr>")
    html = f"""<!doctype html><html><head><meta charset='utf-8'/><title>Existing Framework RCA Report</title>
<style>body{{font-family:Segoe UI,Arial,sans-serif;background:#f8fafc;color:#0f172a;margin:24px}}.card{{background:white;border:1px solid #dbe3ef;border-radius:14px;padding:16px;margin:14px 0}}table{{width:100%;border-collapse:collapse;background:#fff}}td,th{{border:1px solid #cbd5e1;padding:8px;vertical-align:top}}th{{background:#1e293b;color:white}}pre{{white-space:pre-wrap;background:#0f172a;color:#dbeafe;padding:10px;border-radius:8px;max-height:260px;overflow:auto}}code{{background:#0f172a;color:#dbeafe;padding:3px 6px;border-radius:6px}}.ok{{color:#16a34a;font-weight:800}}.bad{{color:#dc2626;font-weight:800}}.warn{{color:#b45309;font-weight:800}}</style></head><body>
<h1>Existing Framework RCA Report</h1>
<div class='card'><p><b>Status:</b> {_html(payload.get('stage'))}</p><p><b>Framework:</b> {_html(payload.get('framework_path'))}</p><p><b>Failed specs:</b> {_html(payload.get('failed_script_count'))}</p><p>{_html((payload.get('auditable_rca_reasoning_checklist') or {}).get('privacy_note'))}</p></div>
<div class='card'><h2>Auditable RCA reasoning checklist</h2><table><thead><tr><th>#</th><th>Check</th><th>Status</th><th>Observable evidence</th><th>Fix decision</th></tr></thead><tbody>{''.join(check_rows) or '<tr><td colspan="5">No checklist generated.</td></tr>'}</tbody></table></div>
<div class='card'><h2>Exact test-by-test RCA</h2><p>This is the management-friendly view: each spec/test shows pass/fail and the reason. Passed tests are listed as passed; failed tests show the suspected root cause and safest patch area.</p><table><thead><tr><th>Spec</th><th>Line</th><th>Test</th><th>Status</th><th>Plain English reason</th><th>Safe fix area</th></tr></thead><tbody>{''.join(case_rows) or '<tr><td colspan="6">No test-case level evidence found. Open the native Playwright shard report.</td></tr>'}</tbody></table></div>
<div class='card'><h2>Common-cause analysis across failed workflows</h2><p>{_html(common.get('message'))}</p><p><b>Multi-workflow common cause found:</b> {_html(common.get('has_multi_workflow_common_cause'))}</p><table><thead><tr><th>Shared component/action</th><th>Failure kind</th><th>Impacted count</th><th>Impacted specs</th><th>Fix priority</th><th>Why</th></tr></thead><tbody>{''.join(common_rows) or '<tr><td colspan="6">No common-cause groups found.</td></tr>'}</tbody></table><p><a href='/artifacts/reports/existing-framework/common-cause-memory.html' target='_blank'>Open common-cause memory/cache</a></p></div>
<div class='card'><h2>Deterministic signals</h2><ul>{signal_rows or '<li>No deterministic signals found.</li>'}</ul></div>
<div class='card'><h2>External MCP research context</h2><p>{_html(ext.get('message'))}</p><p><b>Mode:</b> {_html(ext.get('mode'))} | <b>Enabled:</b> {_html(ext.get('enabled'))}</p><ul>{ext_queries or '<li>No external queries generated.</li>'}</ul></div>
<div class='card'><h2>Recommended fix plan</h2><ol>{fix_plan}</ol></div>
<div class='card'><h2>Raw RCA JSON</h2><pre>{_html(json.dumps(payload, indent=2, ensure_ascii=False)[:70000])}</pre></div>
</body></html>"""
    out = EXISTING_REPORTS_DIR / "root-cause-report.html"
    out.write_text(html, encoding="utf-8")
    return out


def analyze_existing_failure(framework_path: str = "", provider: str = "deterministic", model: str = "llama3", base_url: str = "") -> dict[str, Any]:
    _ensure_dirs()
    inventory = _best_failed_inventory_for_followup()
    root = _resolve_framework_path(framework_path or inventory.get("framework_path", "")) if (framework_path or inventory.get("framework_path")) else None
    if not inventory.get("ok") or not root:
        payload = {"ok": False, "stage": "existing_framework_rca_blocked", "message": inventory.get("error") or "Run existing framework execution first.", "failed_inventory": inventory}
        EXISTING_RCA_JSON.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return payload
    raw_failed_specs = [str(s).replace("\\", "/") for s in (inventory.get("failed_specs") or []) if str(s).strip()]
    failed_specs = [s for s in raw_failed_specs if _is_tests_folder_executable_spec(s, root=root)]
    if not failed_specs:
        payload = {"ok": True, "stage": "existing_framework_rca_no_failures", "message": "No failed specs were found. RCA/self-healing is not required.", "failed_inventory": inventory}
        EXISTING_RCA_JSON.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return payload
    scope = _scope_from_failed_specs(root, failed_specs)
    failure_text = _failure_text(inventory)
    deterministic_signals = _deterministic_signals(failure_text)
    robust_multi_signal_rca = build_robust_rca(root, failed_specs, failure_text)
    try:
        mcp_locator_rca = build_mcp_assisted_locator_rca(root, inventory, failure_text, base_url=normalize_base_url(base_url))
    except Exception as exc:
        mcp_locator_rca = {"ok": False, "error": f"{type(exc).__name__}: {exc}", "message": "MCP-assisted locator RCA failed safely; continuing with standard RCA."}
    rag_query = " ".join([*failed_specs, failure_text[-4000:], "locator page object api db fixture test data vpn vdi"])[-12000:]
    try:
        rag_context = query_framework_context(rag_query, top_k=12, framework_path=root)
    except Exception as exc:
        rag_context = {"ok": False, "error": f"{type(exc).__name__}: {exc}", "message": "RAG context retrieval failed safely."}
    auditable_checklist = _build_auditable_rca_reasoning_checklist(root, failed_specs, failure_text, scope=scope, mcp_locator_rca=mcp_locator_rca)
    common_cause_analysis = _build_common_cause_analysis(root, inventory, failure_text, failed_specs)
    external_research_context = collect_external_fix_research(root, failed_specs, failure_text=failure_text, classification=(deterministic_signals[0].get("kind") if deterministic_signals else ""))
    ai = _ai_rca_existing(root, provider, model, inventory, scope, failure_text, base_url, rag_context=rag_context, external_research_context=external_research_context, auditable_checklist=auditable_checklist, common_cause_analysis=common_cause_analysis)
    payload = {
        "ok": True,
        "stage": "existing_framework_root_cause_completed",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "framework_path": str(root),
        "base_url": normalize_base_url(base_url),
        "failed_inventory": inventory,
        "failed_script_count": len(failed_specs),
        "failed_specs": failed_specs,
        "scope": scope,
        "signals": deterministic_signals,
        "robust_multi_signal_rca": robust_multi_signal_rca,
        "mcp_assisted_locator_rca": mcp_locator_rca,
        "mcp_assisted_locator_rca_url": "/artifacts/reports/existing-framework/mcp-assisted-rca/mcp-assisted-locator-rca.html",
        "auditable_rca_reasoning_checklist": auditable_checklist,
        "common_cause_analysis": common_cause_analysis,
        "common_cause_memory_report_url": "/artifacts/reports/existing-framework/common-cause-memory.html",
        "root_cause_report_url": "/artifacts/reports/existing-framework/root-cause-report.html",
        "external_research_context": external_research_context,
        "external_research_report_url": "/artifacts/reports/existing-framework/external-research/external-mcp-fix-research.html",
        "rag_context_for_failed_scope": rag_context,
        "agentic_framework_memory": load_deep_framework_memory(),
        "ai": ai,
        "recommended_fix_plan": [
            "Review allowed_files and failure evidence.",
            "Patch pageObjects/locator modules first when locator is missing or unstable.",
            "Patch reusable page methods/BasePage/helpers when interaction, overlay, scroll, wait, or navigation is unstable.",
            "Avoid raw locator fixes inside specs unless the framework has no reusable layer for that screen.",
            "After patch, rerun failed specs only from this inventory.",
            "Use multi-signal RCA before patching: DOM snapshot diff, trace replay/timing, HAR diff, fixture/seed diff, and cross-run flakiness frequency.",
            "Run assertion drift classifier before updating any assertion; semantic similarity below 0.30 or behavioral/numeric changes must require human review.",
            "Run second-stage patch confidence review; below 0.80 must require human approval and must not leave an auto-applied patch active.",
        ],
        "strict_rules": [
            "Existing framework mode never generates new functional testcases.",
            "RCA analyzes failed_specs only.",
            "Self-healing may patch only scope.allowed_files.",
            "Already-passed specs are preserved and not rerun during failed-only validation.",
            "Second-stage confidence gate blocks auto-apply below 0.80.",
        ],
    }
    try:
        exact_plain = _build_exact_plain_english_failure_report(inventory, root=root)
        generic_plain = plain_english_failure_report(payload, failure_text=failure_text)
        payload["plain_english_failure_report"] = {**generic_plain, **exact_plain, "generic_summary": generic_plain}
        _write_exact_plain_failure_report(payload["plain_english_failure_report"])
        payload["plain_english_failure_report_url"] = "/artifacts/reports/existing-framework/plain-english-failure-report.html"
    except Exception as exc:
        payload["plain_english_failure_report"] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    try:
        limit_state = _failed_only_iteration_limit_state(root)
        payload["failed_only_iteration_state"] = limit_state
        payload["manual_review_required"] = bool(limit_state.get("blocked"))
        payload["gui_summary"] = _gui_summary_for_rca_payload(payload)
    except Exception as exc:
        payload["gui_summary_warning"] = f"{type(exc).__name__}: {exc}"
    EXISTING_RCA_JSON.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    try:
        _write_existing_rca_html(payload)
    except Exception as exc:
        payload["root_cause_html_warning"] = f"{type(exc).__name__}: {exc}"
        EXISTING_RCA_JSON.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    log_event("existing_framework", f"Existing framework RCA completed for {len(failed_specs)} failed spec(s).", status="done", progress=100, details={"failed_specs": failed_specs, "root_cause_report_url": payload.get("root_cause_report_url")})
    return payload



def _recommended_files_for_failure_category(scope: dict[str, Any], category: str, max_files: int = 12) -> list[str]:
    groups = scope.get("scope_groups") or {}
    failed = list(groups.get("failed_spec_files") or [])
    imported = list(groups.get("imported_dependency_files") or [])
    config = list(groups.get("runtime_config_candidates") or [])
    shared = list(groups.get("shared_helper_candidates") or [])
    heuristic = list(groups.get("heuristic_fallback_candidates") or [])
    if category == "typescript_module_resolution":
        ordered = [*config, *imported, *failed]
    elif category in {"ambiguous_locator", "overlay_or_blocker", "detached_or_rerendered_element", "locator_missing_or_wrong_page_state"}:
        ordered = [*imported, *shared, *heuristic, *failed]
    elif category == "navigation_or_redirect":
        ordered = [*imported, *config, *shared, *failed]
    elif category in {"authentication_or_authorization", "browser_or_runtime_crash", "assertion_or_product_behavior_mismatch", "timeout_or_unfinished_state", "unknown_or_insufficient_evidence"}:
        ordered = []
    else:
        ordered = [*imported, *shared, *failed]
    return list(dict.fromkeys(ordered))[:max(0, int(max_files or 0))]


def _explain_failed_case(rec: dict[str, Any], root: Path | None = None) -> dict[str, Any]:
    """Create evidence-based, category-specific RCA and safe-fix guidance."""
    error_text = "\n".join(str(x) for x in (rec.get("errors") or []))
    if not error_text:
        error_text = json.dumps(rec, ensure_ascii=False)
    low = error_text.lower()
    reason = _failure_reason_from_case(rec)
    category = "unknown_or_insufficient_evidence"
    confidence = 0.35
    layer = "trace/screenshot/manual review"
    action = "Collect trace, screenshot, video and DOM evidence before changing framework code."
    validation = "Rerun the exact failed test with trace, screenshot and video enabled; do not patch until the same failure is reproducible."
    evidence: list[str] = []
    safety = "manual_review_required"

    def has(*terms: str) -> bool:
        return any(t in low for t in terms)

    if _is_module_resolution_failure(error_text):
        category, confidence, layer = "typescript_module_resolution", 0.97, "playwright.config / tsconfig / package runtime bootstrap"
        action = "Correct the alias/runtime resolver or import path. Do not edit locators because the browser step was never reached."
        validation = "Run Playwright --list first, then rerun the failed spec and confirm the module loads before browser actions start."
        evidence.append("Node/Playwright reported an unresolved module, path alias, or require/import stack.")
        safety = "safe_with_config_scope_and_backup"
    elif has("strict mode violation", "resolved to ") and has("locator"):
        category, confidence, layer = "ambiguous_locator", 0.92, "page object / locator repository"
        action = "Replace the ambiguous selector with a unique role/test-id/label locator in the reusable page object; avoid nth() unless business order is stable."
        validation = "Use MCP/codegen or locator inspector to prove the selector resolves to exactly one intended element, then rerun the failed test."
        evidence.append("Playwright strict mode indicates that one locator matched multiple elements.")
        safety = "safe_after_live_dom_verification"
    elif has("intercepts pointer events", "receives pointer events", "another element would receive"):
        category, confidence, layer = "overlay_or_blocker", 0.93, "shared BasePage/blocker handler or page method"
        action = "Identify the blocking modal, cookie banner, spinner or overlay and handle it in a reusable page/blocker method before the click."
        validation = "Capture screenshot/trace at the failed click, verify the blocker disappears, and rerun without force-click or hard waits."
        evidence.append("The error states that another element intercepted the pointer event.")
        safety = "safe_after_overlay_identity_is_proven"
    elif has("not attached to the dom", "element is detached", "detached from"):
        category, confidence, layer = "detached_or_rerendered_element", 0.90, "page method / locator re-query logic"
        action = "Re-query the locator after the UI rerender and wait for the business state, not a fixed delay. Keep the locator in the reusable page layer."
        validation = "Use trace DOM snapshots to confirm rerender timing, then rerun the failed test repeatedly to check stability."
        evidence.append("Playwright reported that the previously resolved element was detached or replaced.")
        safety = "safe_after_trace_timing_review"
    elif has("waiting for locator", "element(s) not found", "to be visible", "locator("):
        category, confidence, layer = "locator_missing_or_wrong_page_state", 0.82, "page object / locator repository or navigation method"
        action = "First prove the current page/state and live DOM. If the element exists with a changed attribute, update the reusable locator; if navigation/state is wrong, fix the page flow instead."
        validation = "Open trace/screenshot, verify URL and DOM, test the candidate locator with MCP/codegen, then rerun only the failed test."
        evidence.append("The failure contains locator visibility/availability waiting evidence.")
        safety = "requires_live_dom_or_trace_evidence"
    elif has("tohaveurl", "url did not match", "navigation", "page.goto"):
        category, confidence, layer = "navigation_or_redirect", 0.82, "navigation/page workflow or environment URL configuration"
        action = "Compare expected and actual URL/redirect chain. Fix reusable navigation or environment configuration; change the assertion only when the product requirement changed."
        validation = "Record redirect/network trace and confirm final URL and authentication state before rerun."
        evidence.append("The failed assertion/action relates to URL, redirect or navigation state.")
        safety = "manual_requirement_check_before_assertion_change"
    elif has("expect(", "expected", "received", "toequal", "tocontain", "tohavetext"):
        category, confidence, layer = "assertion_or_product_behavior_mismatch", 0.72, "requirement/test data/AUT verification before test code"
        action = "Compare expected value with requirement and actual AUT data. Update test data or reusable assertion only after confirming the intended product behavior."
        validation = "Capture actual value and requirement reference, then rerun with controlled test data."
        evidence.append("Playwright assertion output shows expected-versus-received mismatch.")
        safety = "human_review_required_before_assertion_change"
    elif has("timeout", "timed out"):
        category, confidence, layer = "timeout_or_unfinished_state", 0.62, "workflow synchronization, navigation, network or locator layer"
        action = "Use trace timing to identify the exact unfinished action. Add a condition-based wait in the reusable flow only when the expected state is proven; do not add waitForTimeout."
        validation = "Review the final trace action, network and screenshot, then rerun with the same 30-second guard."
        evidence.append("The test/action exceeded its timeout without enough evidence to assume a locator-only problem.")
        safety = "manual_trace_review_required"
    elif has("browser has been closed", "target page, context or browser has been closed", "browser disconnected"):
        category, confidence, layer = "browser_or_runtime_crash", 0.88, "runner/browser infrastructure or fixture lifecycle"
        action = "Inspect browser launch, fixture teardown, worker memory and crash logs. Do not modify page locators for a closed browser/context."
        validation = "Run one worker with browser logs and verify fixture lifecycle before rerunning failed tests."
        evidence.append("Playwright reported a closed/disconnected browser, page or context.")
        safety = "infrastructure_review_required"
    elif has("401", "403", "unauthorized", "forbidden"):
        category, confidence, layer = "authentication_or_authorization", 0.90, "environment/session/credential fixture"
        action = "Validate credentials, role, session state, VPN and auth fixture. Do not self-heal selectors until authorization is restored."
        validation = "Confirm login/session setup independently, then rerun the failed test without code changes."
        evidence.append("Failure evidence indicates an authorization/session problem.")
        safety = "do_not_auto_patch"

    recommended_files: list[str] = []
    spec = str(rec.get("spec") or "")
    if root is not None and spec:
        try:
            scoped = _scope_from_failed_specs(root, [spec])
            recommended_files = _recommended_files_for_failure_category(scoped, category, max_files=8)
        except Exception:
            recommended_files = []

    return {
        "failure_category": category,
        "confidence": confidence,
        "plain_english_reason": reason,
        "observed_evidence": evidence or ["The available result does not contain a decisive error signature; trace/screenshot review is required."],
        "likely_fix_layer": layer,
        "suggested_fix_area": action,
        "recommended_files": recommended_files,
        "validation_steps": validation,
        "self_healing_safety": safety,
    }


def _build_exact_plain_english_failure_report(inventory: dict[str, Any], root: Path | None = None) -> dict[str, Any]:
    cases = _dedupe_case_records(_inventory_test_cases(inventory or {}, root=root))
    outcomes = []
    failed = 0
    passed = 0
    category_counts: Counter[str] = Counter()
    for rec in cases:
        status_raw = str(rec.get("status") or "unknown").lower()
        is_bad = status_raw in {"failed", "timedout", "interrupted"}
        if is_bad:
            failed += 1
            explanation = _explain_failed_case(rec, root=root)
            category_counts[explanation["failure_category"]] += 1
        elif status_raw in {"passed", "skipped", "expected", "flaky"}:
            passed += 1
            explanation = {
                "failure_category": "not_applicable",
                "confidence": 1.0,
                "plain_english_reason": "passed",
                "observed_evidence": ["Playwright reported the test as passed/expected/flaky/skipped in the latest inventory."],
                "likely_fix_layer": "No fix required",
                "suggested_fix_area": "No fix required",
                "recommended_files": [],
                "validation_steps": "No failed-test validation is required for this test.",
                "self_healing_safety": "not_applicable",
            }
        else:
            explanation = {
                "failure_category": "unknown_status",
                "confidence": 0.2,
                "plain_english_reason": f"Playwright status is {status_raw}; the result is not safely classified as passed or failed.",
                "observed_evidence": ["The latest result contains an unrecognized or incomplete status."],
                "likely_fix_layer": "report/inventory review",
                "suggested_fix_area": "Regenerate the Playwright JSON/HTML report before changing code.",
                "recommended_files": [],
                "validation_steps": "Run the exact test again with JSON and HTML reporters enabled.",
                "self_healing_safety": "do_not_auto_patch",
            }
        outcomes.append({
            "spec": rec.get("spec"),
            "line": rec.get("line"),
            "test": rec.get("title") or "(whole spec fallback)",
            "status": "failed" if is_bad else ("passed" if status_raw in {"passed", "skipped", "expected", "flaky"} else status_raw),
            **explanation,
            "errors": rec.get("errors") or [],
        })
    return {
        "ok": True,
        "source": "AstraHeal exact Playwright inventory plus deterministic error classification",
        "summary": f"{len(cases)} test case(s) analysed: {passed} passed, {failed} failed.",
        "total_test_cases": len(cases),
        "passed_test_cases": passed,
        "failed_test_cases": failed,
        "failure_category_counts": dict(category_counts),
        "framework_path": str(root) if root is not None else "",
        "local_storage_locations": existing_framework_artifact_locations(str(root) if root is not None else ""),
        "test_case_outcomes": outcomes,
        "message": "Each failed test now shows the observed evidence, failure category/confidence, likely fix layer, recommended files, safe action, validation steps and self-healing safety decision."
    }


def _write_exact_plain_failure_report(report: dict[str, Any]) -> None:
    try:
        EXISTING_PLAIN_FAILURE_JSON.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        rows = []
        for rec in report.get("test_case_outcomes") or []:
            cls = "bad" if rec.get("status") == "failed" else ("ok" if rec.get("status") == "passed" else "warn")
            evidence = "<br/>".join(_html(x) for x in (rec.get("observed_evidence") or []))
            files = "<br/>".join(f"<code>{_html(x)}</code>" for x in (rec.get("recommended_files") or [])) or "Evidence first; no file safely selected yet."
            conf = f"{float(rec.get('confidence') or 0):.0%}"
            rows.append(f"<tr><td><code>{_html(rec.get('spec'))}</code><br/>line {_html(rec.get('line'))}</td><td>{_html(rec.get('test'))}</td><td class='{cls}'>{_html(rec.get('status'))}</td><td><b>{_html(rec.get('failure_category'))}</b><br/>Confidence: {_html(conf)}</td><td>{evidence}</td><td>{_html(rec.get('plain_english_reason'))}</td><td><b>Layer:</b> {_html(rec.get('likely_fix_layer'))}<br/><br/>{_html(rec.get('suggested_fix_area'))}<br/><br/><b>Files:</b><br/>{files}</td><td>{_html(rec.get('validation_steps'))}<br/><br/><b>Self-healing:</b> {_html(rec.get('self_healing_safety'))}</td></tr>")
        html = f"""<!doctype html><html><head><meta charset='utf-8'><title>Plain English RCA</title>
<style>body{{font-family:Segoe UI,Arial,sans-serif;margin:24px;background:#f8fafc;color:#0f172a}}.card{{background:white;border:1px solid #dbe3ef;border-radius:14px;padding:16px;margin:14px 0}}.warn{{color:#b45309;font-weight:800}}.ok{{color:#16a34a;font-weight:800}}.bad{{color:#dc2626;font-weight:800}}table{{width:100%;border-collapse:collapse;background:white;font-size:13px}}th,td{{border:1px solid #cbd5e1;padding:8px;vertical-align:top}}th{{background:#1e293b;color:white;position:sticky;top:0}}code{{background:#0f172a;color:#dbeafe;padding:2px 6px;border-radius:6px;display:inline-block;margin:2px 0}}.scroll{{overflow:auto;max-height:75vh}}</style></head><body>
<h1>Plain English RCA Report</h1><section class='card'><h2>Summary</h2><p>{_html(report.get('summary'))}</p><p>{_html(report.get('message'))}</p><p><b>Failure categories:</b> {_html(json.dumps(report.get('failure_category_counts') or {}, ensure_ascii=False))}</p></section>
<section class='card'><h2>Where this report and supporting logs are stored locally</h2><p><b>Central report root:</b> <code>{_html(((report.get('local_storage_locations') or {}).get('central_report_root')))}</code></p><p><b>Central cache/log root:</b> <code>{_html(((report.get('local_storage_locations') or {}).get('central_cache_root')))}</code></p><p><b>Selected framework:</b> <code>{_html(((report.get('local_storage_locations') or {}).get('selected_framework_root')))}</code></p><p>Use <b>Logs, Reports and AI Memory → Show local report/log folders</b> in the GUI for every exact file and whether it currently exists.</p></section>
<section class='card'><h2>Test-by-test explainable RCA</h2><p>This report separates evidence from inference. A locator is not recommended unless the error/trace indicates a DOM problem; environment, module, browser and assertion failures receive different fix layers.</p><div class='scroll'><table><thead><tr><th>Spec / line</th><th>Test</th><th>Status</th><th>Category / confidence</th><th>Observed evidence</th><th>Plain-English cause</th><th>Safest fix and likely files</th><th>Validation / auto-heal decision</th></tr></thead><tbody>{''.join(rows) or '<tr><td colspan="8">No test-case level evidence found. Open the native Playwright report.</td></tr>'}</tbody></table></div></section>
</body></html>"""
        EXISTING_PLAIN_FAILURE_HTML.write_text(html, encoding="utf-8")
    except Exception:
        pass


def _deterministic_signals(text: str) -> list[dict[str, Any]]:
    low = (text or "").lower()
    signals: list[dict[str, Any]] = []
    def add(kind: str, confidence: float, recommendation: str) -> None:
        signals.append({"kind": kind, "confidence": confidence, "recommendation": recommendation})
    if _is_module_resolution_failure(text):
        missing = _extract_missing_module_name(text)
        target = f" for {missing}" if missing else ""
        add(
            "typescript_path_alias_or_module_resolution",
            0.96,
            f"Fix Playwright/Node module resolution{target}: parse tsconfig/jsconfig path aliases and preload a runtime resolver or approved framework bootstrap. Do not change DOM locators for this failure.",
        )
    if any(x in low for x in ["element is not attached to the dom", "not attached to the dom", "detached from dom", "detached"]):
        add("locator_detached_from_dom", 0.91, "Do not reuse stale locator/ElementHandle. Re-query the locator after page settles, use MCP/codegen to verify the live replacement locator, and patch pageObject/page method helper rather than adding blind waits.")
    if any(x in low for x in ["strict mode violation", "locator resolved to", "locator(", "getbyrole", "getbytext", "tobevisible", "waiting for"]):
        add("locator_not_found_or_ambiguous", 0.88, "Update pageObjects/locator definitions using stable Playwright locators and add fallbacks where needed.")
    if any(x in low for x in ["element(s) not found"]):
        add("locator_not_found_or_ambiguous", 0.86, "Update pageObjects/locator definitions using stable Playwright locators and add fallbacks where needed.")
    if any(x in low for x in ["intercepts pointer events", "not enabled", "not visible", "outside of the viewport", "detached", "click timeout"]):
        add("clickability_overlay_or_viewport", 0.84, "Patch reusable page method/BasePage to dismiss overlays, scroll into view, wait for stable DOM, then click safely.")
    if any(x in low for x in ["waitforurl", "tohaveurl", "navigation", "timeout", "networkidle"]):
        add("navigation_or_sync", 0.78, "Use resilient navigation waits and relative URL assertions in page methods/helper layer.")
    if any(x in low for x in ["net::err", "dns", "econnrefused", "err_timed_out", "ssl"]):
        add("environment_or_network", 0.72, "Verify VPN, proxy, base URL, DNS, SSL, and test data before patching framework code.")
    if not signals:
        add("unknown_or_insufficient_evidence", 0.35, "Run headed with traces/screenshots/video enabled and rerun RCA.")
    return sorted(signals, key=lambda x: x["confidence"], reverse=True)


def _failure_kind_from_text(text: str) -> str:
    low = (text or "").lower()
    if _is_module_resolution_failure(text):
        return "typescript_path_alias_or_module_resolution"
    if any(x in low for x in ["strict mode violation", "resolved to", "locator", "getbyrole", "getbytext", "getbytestid", "waiting for", "tobevisible", "element(s) not found"]):
        return "locator_or_dom_change"
    if any(x in low for x in ["intercepts pointer events", "not enabled", "not visible", "outside of the viewport", "detached", "click timeout", "locator.click"]):
        return "interactability_overlay_or_viewport"
    if any(x in low for x in ["waitforurl", "tohaveurl", "navigation", "networkidle", "domcontentloaded", "timeout"]):
        return "navigation_or_synchronization"
    if any(x in low for x in ["401", "403", "500", "net::err", "econn", "ssl", "certificate", "vpn", "proxy", "dns"]):
        return "environment_network_auth_or_data"
    if any(x in low for x in ["expect(", "expected", "received", "assert"]):
        return "assertion_or_product_behavior_drift"
    return "unknown_or_framework_failure"


def _extract_component_hint(text: str) -> dict[str, Any]:
    """Extract a compact component/locator/action hint for common-cause grouping.

    This deliberately uses observable failure text only. It is not hidden model
    reasoning; it creates an auditable grouping key such as button:Continue or
    role:button:name=Checkout so one shared broken component can be fixed first.
    """
    raw = text or ""
    compact = " ".join(raw.split())
    candidates: list[tuple[str, str]] = []
    patterns = [
        ("testid", r"getByTestId\((['\"])(.*?)\1\)"),
        ("label", r"getByLabel\((['\"])(.*?)\1"),
        ("placeholder", r"getByPlaceholder\((['\"])(.*?)\1"),
        ("text", r"getByText\((['\"])(.*?)\1"),
        ("role_name", r"getByRole\((['\"])(.*?)\1\s*,\s*\{[^}]*name\s*:\s*(['\"])(.*?)\3"),
        ("locator", r"locator\((['\"])(.*?)\1"),
        ("button", r"(?:button|Button)\s*['\"]([^'\"]{2,80})['\"]"),
        ("css_id", r"#[A-Za-z0-9_-]{2,80}"),
        ("css_class", r"\.[A-Za-z0-9_-]{3,80}"),
    ]
    for kind, pattern in patterns:
        for m in re.finditer(pattern, compact, flags=re.I):
            if kind == "role_name":
                value = f"role:{m.group(2)} name:{m.group(4)}"
            elif kind in {"css_id", "css_class"}:
                value = m.group(0)
            else:
                value = m.group(2) if len(m.groups()) >= 2 else m.group(1)
            value = re.sub(r"\s+", " ", str(value or "")).strip()[:120]
            if value:
                candidates.append((kind, value))
        if candidates:
            break
    action = "click" if re.search(r"\bclick\b|locator\.click", compact, flags=re.I) else "verify" if re.search(r"expect|tobevisible|assert|should", compact, flags=re.I) else "flow"
    if candidates:
        kind, value = candidates[0]
    else:
        # Fall back to visible page/workflow tokens from the spec path/error.
        m = re.search(r"(?:tests|pages|pageObjects|src)[/\\]([^\s:]+?)(?:\.spec|\.test|\.ts|\.js|[/\\])", raw, flags=re.I)
        kind, value = ("workflow", m.group(1).replace("/", "-").replace("\\", "-")) if m else ("component", "unknown")
    normalized = re.sub(r"[^a-z0-9]+", "-", f"{kind}-{value}".lower()).strip("-")[:100] or "unknown-component"
    return {"kind": kind, "value": value, "action": action, "normalized": normalized}


def _failure_records_from_inventory(inventory: dict[str, Any], failure_text: str, failed_specs: list[str]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    raw_failed = inventory.get("failed_tests") or []
    for item in raw_failed if isinstance(raw_failed, list) else []:
        if not isinstance(item, dict):
            continue
        spec = str(item.get("spec") or item.get("file") or item.get("testFile") or item.get("test_file") or item.get("path") or "").replace("\\", "/")
        title = str(item.get("title") or item.get("test") or item.get("name") or item.get("fullTitle") or "")
        error = str(item.get("error") or item.get("message") or item.get("failure") or item.get("stdout") or item.get("stderr") or "")
        combined = "\n".join(x for x in [spec, title, error, json.dumps(item, ensure_ascii=False)[:4000]] if x)
        if not spec:
            for fs in failed_specs:
                if fs and fs in combined:
                    spec = fs
                    break
        component = _extract_component_hint(combined)
        records.append({"spec": spec or "unknown", "title": title, "failure_kind": _failure_kind_from_text(combined), "component": component, "signature": f"{_failure_kind_from_text(combined)}::{component.get('normalized')}", "evidence_excerpt": combined[-2500:]})
    if not records:
        chunks = re.split(r"(?=\n\s*(?:Error:|TimeoutError:|\d+\)|\[\w+\].*?›))", failure_text or "")
        for fs in failed_specs:
            related = [c for c in chunks if fs in c]
            text = "\n".join(related)[-5000:] if related else (failure_text or "")[-5000:]
            component = _extract_component_hint(text + "\n" + fs)
            records.append({"spec": fs, "title": "", "failure_kind": _failure_kind_from_text(text), "component": component, "signature": f"{_failure_kind_from_text(text)}::{component.get('normalized')}", "evidence_excerpt": text[-2500:]})
    return records


def _load_common_cause_memory(root: Path | None = None, limit: int = 50) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    paths = [EXISTING_COMMON_CAUSE_MEMORY_JSON]
    if root:
        paths.append(root / ".aiqa-history" / "common-cause-memory.json")
    for path in paths:
        try:
            data = json.loads(path.read_text(encoding="utf-8", errors="replace")) if path.exists() else {}
            records.extend(data.get("records") or [])
        except Exception:
            continue
    dedup: dict[str, dict[str, Any]] = {}
    for rec in records:
        key = str(rec.get("memory_key") or rec.get("signature") or json.dumps(rec, sort_keys=True, ensure_ascii=False)[:200])
        dedup[key] = rec
    ordered = sorted(dedup.values(), key=lambda x: str(x.get("updated_at") or x.get("generated_at") or ""), reverse=True)[:limit]
    return {"ok": True, "count": len(ordered), "records": ordered}


def _write_common_cause_memory_html(memory: dict[str, Any]) -> None:
    EXISTING_REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    rows = []
    for rec in memory.get("records") or []:
        rows.append(
            f"<tr><td>{_html(rec.get('updated_at') or rec.get('generated_at'))}</td><td>{_html(rec.get('component'))}</td><td>{_html(rec.get('failure_kind'))}</td><td>{_html(rec.get('impacted_count'))}</td><td><pre>{_html(json.dumps(rec.get('impacted_specs') or [], indent=2, ensure_ascii=False)[:3000])}</pre></td><td>{_html(rec.get('recommended_fix_priority'))}</td></tr>"
        )
    EXISTING_COMMON_CAUSE_MEMORY_HTML.write_text(f"""<!doctype html><html><head><meta charset='utf-8'/><title>Common Cause RCA Memory</title>
<style>body{{font-family:Segoe UI,Arial,sans-serif;background:#f8fafc;color:#0f172a;margin:24px}}table{{width:100%;border-collapse:collapse;background:white}}td,th{{border:1px solid #cbd5e1;padding:8px;vertical-align:top}}th{{background:#1e293b;color:white}}pre{{white-space:pre-wrap;background:#0f172a;color:#dbeafe;padding:8px;border-radius:8px}}</style></head><body>
<h1>Common Cause RCA Memory</h1><p>This cache stores recurring failed component/failure signatures so future RCA and self-healing can prioritize shared causes before individual test edits.</p><table><thead><tr><th>Updated</th><th>Component</th><th>Failure kind</th><th>Impacted specs</th><th>Specs</th><th>Fix priority</th></tr></thead><tbody>{''.join(rows) or '<tr><td colspan="6">No common-cause memory yet.</td></tr>'}</tbody></table></body></html>""", encoding="utf-8")


def _persist_common_cause_memory(root: Path, analysis: dict[str, Any], source: str = "rca") -> dict[str, Any]:
    memory = _load_common_cause_memory(root, limit=200)
    existing = {str(r.get("memory_key") or r.get("signature") or ""): r for r in memory.get("records") or []}
    for group in analysis.get("groups") or []:
        key = str(group.get("memory_key") or group.get("signature") or "")
        if not key:
            continue
        prev = existing.get(key, {})
        impacted = sorted(set([*(prev.get("impacted_specs") or []), *(group.get("impacted_specs") or [])]))
        existing[key] = {
            **prev,
            "memory_key": key,
            "signature": group.get("signature"),
            "component": group.get("component"),
            "failure_kind": group.get("failure_kind"),
            "impacted_specs": impacted,
            "impacted_count": len(impacted),
            "last_source": source,
            "recommended_fix_priority": group.get("recommended_fix_priority"),
            "first_seen_at": prev.get("first_seen_at") or analysis.get("generated_at"),
            "updated_at": datetime.now().isoformat(timespec="seconds"),
            "latest_evidence_excerpt": group.get("evidence_excerpt"),
        }
    records = sorted(existing.values(), key=lambda x: str(x.get("updated_at") or ""), reverse=True)[:200]
    payload = {"ok": True, "generated_at": datetime.now().isoformat(timespec="seconds"), "framework_path": str(root), "records": records, "count": len(records)}
    EXISTING_COMMON_CAUSE_MEMORY_JSON.parent.mkdir(parents=True, exist_ok=True)
    EXISTING_COMMON_CAUSE_MEMORY_JSON.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    try:
        local = root / ".aiqa-history"
        local.mkdir(parents=True, exist_ok=True)
        (local / "common-cause-memory.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    except Exception as exc:
        payload["local_memory_warning"] = f"{type(exc).__name__}: {exc}"
    _write_common_cause_memory_html(payload)
    return {"ok": True, "count": len(records), "memory_report_url": "/artifacts/reports/existing-framework/common-cause-memory.html"}


def _build_common_cause_analysis(root: Path, inventory: dict[str, Any], failure_text: str, failed_specs: list[str]) -> dict[str, Any]:
    records = _failure_records_from_inventory(inventory, failure_text, failed_specs)
    groups_by_signature: dict[str, dict[str, Any]] = {}
    for rec in records:
        sig = str(rec.get("signature") or "unknown")
        grp = groups_by_signature.setdefault(sig, {
            "signature": sig,
            "memory_key": sig,
            "failure_kind": rec.get("failure_kind"),
            "component": (rec.get("component") or {}).get("value") or (rec.get("component") or {}).get("normalized"),
            "component_kind": (rec.get("component") or {}).get("kind"),
            "action": (rec.get("component") or {}).get("action"),
            "impacted_specs": [],
            "impacted_titles": [],
            "evidence_excerpt": rec.get("evidence_excerpt") or "",
        })
        if rec.get("spec") and rec.get("spec") not in grp["impacted_specs"]:
            grp["impacted_specs"].append(rec.get("spec"))
        if rec.get("title") and rec.get("title") not in grp["impacted_titles"]:
            grp["impacted_titles"].append(rec.get("title"))
    groups = []
    for grp in groups_by_signature.values():
        impacted_count = len(grp.get("impacted_specs") or [])
        grp["impacted_count"] = impacted_count
        if impacted_count > 1:
            grp["recommended_fix_priority"] = "fix_shared_component_first"
            grp["why"] = "Multiple failed workflows share the same failure signature/component. Patch the shared locator/page method/helper before editing individual specs."
        else:
            grp["recommended_fix_priority"] = "fix_single_workflow_after_shared_components"
            grp["why"] = "Single failed workflow/signature. Still patch reusable page/pageObject/helper layer first."
        groups.append(grp)
    groups = sorted(groups, key=lambda g: (int(g.get("impacted_count") or 0), str(g.get("failure_kind") or "")), reverse=True)
    memory = _load_common_cause_memory(root, limit=30)
    analysis = {
        "ok": True,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "framework_path": str(root),
        "failed_specs": failed_specs,
        "records": records[:80],
        "groups": groups[:50],
        "primary_common_cause": groups[0] if groups else {},
        "has_multi_workflow_common_cause": any(int(g.get("impacted_count") or 0) > 1 for g in groups),
        "historical_memory_used": memory,
        "report_url": "/artifacts/reports/existing-framework/common-cause-memory.html",
        "message": "Common-cause analysis grouped failed workflows by observable failure kind and component/locator/action signature. Shared components are prioritized before individual test edits.",
    }
    analysis["memory_store"] = _persist_common_cause_memory(root, analysis, source="rca")
    return analysis


def _ai_rca_existing(root: Path, provider: str, model: str, inventory: dict[str, Any], scope: dict[str, Any], failure_text: str, base_url: str, rag_context: dict[str, Any] | None = None, external_research_context: dict[str, Any] | None = None, auditable_checklist: dict[str, Any] | None = None, common_cause_analysis: dict[str, Any] | None = None) -> dict[str, Any]:
    provider = (provider or "deterministic").lower().strip()
    if provider not in {"codex", "ollama"}:
        return {"used": False, "provider": provider, "message": "Deterministic RCA signals used. Select Codex/Ollama for extra failure reasoning."}
    rag_context = rag_context or {}
    external_research_context = external_research_context or {}
    auditable_checklist = auditable_checklist or {}
    common_cause_analysis = common_cause_analysis or {}
    prompt = f"""
You are a senior Playwright RCA agent for an existing user-owned Playwright TypeScript framework.
Return JSON only with keys: root_cause, confidence, auto_healable, patch_order, exact_files_to_patch, validation_steps, risk, plain_english_summary, evidence_chain_summary.
Do not modify files. Do not reveal hidden chain-of-thought. Provide an auditable evidence_chain_summary made only of observable facts, classifications, and decisions.

Reasoning workflow to follow internally:
1. Understand architecture and triggering flow from framework intelligence/RAG.
2. Use Microsoft Playwright MCP-style observable checks when available: failed locator/action -> visible GUI text/accessibility role -> DOM/accessibility presence -> actionability/interactability -> POM locator strategy.
3. Check failure evidence: error, trace, DOM, HAR/network, fixtures/test data, cross-run history.
4. Classify whether the issue is locator, interaction, popup, permission, API/DB/data/env, assertion drift, iframe/shadow DOM, or product defect.
5. Decide whether self-healing is safe.
6. Recommend the smallest allowed patch and validation steps.

Strict rules:
- Requirement/testcase/codegen phases are bypassed. Existing specs are the source of truth.
- Analyze failed specs only: {json.dumps(inventory.get('failed_specs', []), ensure_ascii=False)}
- Patch scope must be restricted to allowed files only: {json.dumps(scope.get('allowed_files', []), ensure_ascii=False)}
- Preserve POM/reuse: spec -> page method -> pageObjects/locator definitions.
- Do not patch unrelated specs or already-passed specs.
- If issue is environment/network/auth/data, do not recommend code changes first.

Base URL: {normalize_base_url(base_url)}
Failed inventory:
{json.dumps(inventory, indent=2, ensure_ascii=False)[:14000]}

Failure text:
{failure_text[-12000:]}

RAG context for failed scope:
{json.dumps(rag_context.get('hits', [])[:10], indent=2, ensure_ascii=False)[:6000]}

Auditable RCA checklist to follow and summarize:
{json.dumps(auditable_checklist.get('checks', [])[:20], indent=2, ensure_ascii=False)[:16000]}

Common-cause analysis to prioritize before individual fixes:
{json.dumps({k: common_cause_analysis.get(k) for k in ['has_multi_workflow_common_cause','primary_common_cause','groups','historical_memory_used']}, indent=2, ensure_ascii=False)[:9000]}

Optional external MCP research context. Use as advisory only; never copy public code blindly:
{json.dumps(external_research_context, indent=2, ensure_ascii=False)[:6000]}
""".strip()
    try:
        if provider == "codex":
            result = CodexCliProvider(root, timeout_seconds=300).run(prompt)
            return {"used": True, "provider": "codex", "ok": result.ok, "message": (result.stdout if result.ok else result.stderr)[-10000:]}
        result = OllamaProvider(model=model).chat(prompt)
        return {"used": True, "provider": "ollama", "ok": result.ok, "message": (result.text if result.ok else result.error)[-10000:]}
    except Exception as exc:
        return {"used": True, "provider": provider, "ok": False, "message": f"AI RCA failed safely: {type(exc).__name__}: {exc}"}


def _backup_scope(root: Path, allowed_files: list[str]) -> dict[str, Any]:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_root = EXISTING_BACKUP_DIR / timestamp
    copied: list[str] = []
    for rel in allowed_files:
        src = (root / rel).resolve()
        if not src.exists() or not src.is_file():
            continue
        dest = backup_root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        copied.append(rel)
    return {"backup_root": str(backup_root), "copied_files": copied, "count": len(copied)}


def _scoped_file_excerpts(root: Path, allowed_files: list[str], max_total: int = 36000) -> dict[str, str]:
    excerpts: dict[str, str] = {}
    used = 0
    for rel in allowed_files[:25]:
        path = root / rel
        text = _read(path, limit=14000)
        if not text:
            continue
        remaining = max_total - used
        if remaining <= 0:
            break
        chunk = text[: min(len(text), remaining)]
        excerpts[rel] = chunk
        used += len(chunk)
    return excerpts




def _prioritize_patch_files_for_ai(allowed_files: list[str], rca: dict[str, Any], max_files: int = 220) -> list[str]:
    """Keep AI patch prompts small and fast while preserving safe scope.

    Large enterprise frameworks can produce hundreds of approved files after the
    user gives local/VM approval. Passing all of them to Codex makes the UI look
    stuck. This function orders likely shared-component files first and caps the
    prompt list; policy validation still checks the real changed files.
    """
    allowed = [str(x).replace("\\", "/") for x in allowed_files or []]
    common = rca.get("common_cause_analysis") or {}
    groups = common.get("groups") or []
    keywords: set[str] = set()
    for spec in rca.get("failed_specs") or []:
        for part in re.split(r"[^A-Za-z0-9]+", str(spec)):
            if len(part) >= 4:
                keywords.add(part.lower())
    for group in groups[:5]:
        for value in [group.get("component"), group.get("failure_kind"), group.get("component_kind"), group.get("action")]:
            for part in re.split(r"[^A-Za-z0-9]+", str(value or "")):
                if len(part) >= 3:
                    keywords.add(part.lower())
    priority_dirs = ["pageobjects/", "page-objects/", "pages/", "src/pages/", "locators/", "selectors/", "utils/", "helpers/", "support/", "fixtures/", "tests/"]
    def score(rel: str) -> tuple[int, str]:
        low = rel.lower()
        val = 0
        for idx, prefix in enumerate(priority_dirs):
            if prefix in low:
                val += max(1, 80 - idx * 5)
        if any(k and k in low for k in keywords):
            val += 90
        if low.endswith(("basepage.ts", "base.page.ts", "safeactions.ts", "locatorfactory.ts", "smartlocator.ts")):
            val += 60
        if low.startswith("tests/"):
            val += 15
        return (-val, rel)
    ordered = sorted(dict.fromkeys(allowed), key=score)
    return ordered[:max(1, int(max_files or 220))]

def _deterministic_existing_fix_plan(rca: dict[str, Any], failure_text: str, allowed_files: list[str]) -> dict[str, Any]:
    """Always create a human-readable fix plan even when Codex/Ollama is not connected.

    This prevents the GUI from appearing to do nothing after Explain/Create Fix
    when enterprise auth blocks AI patching.  It is proposal-only and safe.
    """
    signals = rca.get("signals") or []
    mcp = rca.get("mcp_assisted_locator_rca") or {}
    failed_specs = rca.get("failed_specs") or []
    primary = signals[0].get("kind") if signals else "unknown_or_insufficient_evidence"
    common = rca.get("common_cause_analysis") or {}
    primary_common = common.get("primary_common_cause") or {}
    plan: list[str] = []
    if common.get("has_multi_workflow_common_cause") and primary_common:
        plan.extend([
            f"Prioritize shared component first: {primary_common.get('component')} ({primary_common.get('failure_kind')}) impacts {primary_common.get('impacted_count')} failed spec(s).",
            "Patch the common pageObject/page method/BasePage/helper used by these workflows before editing individual test specs.",
            "After common component fix, rerun only the failed inventory to confirm multiple workflows recover together.",
        ])
    if primary == "typescript_path_alias_or_module_resolution":
        missing = _extract_missing_module_name(failure_text)
        plan.extend([
            f"Treat this as Playwright/Node module resolution, not a browser locator issue. Missing module: {missing or 'not extracted from log'}.",
            "Read tsconfig.json/jsconfig.json with JSONC support and verify baseUrl/paths include the missing alias target, for example @config/* -> src/main/config/*.",
            "Ensure Playwright execution preloads a path-alias runtime resolver through NODE_OPTIONS or an approved Playwright config/bootstrap. Prefer a dependency-free generated resolver when enterprise installs are restricted; alternatively add tsconfig-paths/register if package approval exists.",
            "Include package.json, tsconfig/jsconfig, playwright.config.*, the failed spec, fixture, and alias target files in the human-approved patch scope.",
            "Rerun only the failed spec after the alias resolver is active; do not modify pageObjects/locators unless a second browser-step failure appears after the import error is fixed.",
        ])
    elif primary == "locator_not_found_or_ambiguous" or mcp.get("failed_locator_or_action_candidates"):
        plan.extend([
            "Open the failed spec and identify the page method being called.",
            "Find the matching locator in pageObjects/locator module or page class.",
            "Compare failed locator text/role/testId with MCP/accessibility candidates and Playwright error output.",
            "Update locator in POM layer using stable getByRole/getByTestId/getByLabel first; avoid raw XPath unless framework already uses it consistently.",
            "Do not edit passed specs or weaken assertions.",
        ])
    elif primary == "clickability_overlay_or_viewport":
        plan.extend([
            "Patch reusable page method/BasePage helper, not the spec.",
            "Wait for element to be visible, enabled and stable; scroll into view; handle/dismiss overlay or permission dialog if present.",
            "Retry the action once through a safe helper; do not add blind waitForTimeout, waits above 30000ms, or force:true by default.",
        ])
    elif primary == "navigation_or_sync":
        plan.extend([
            "Patch reusable navigation/wait helper or page method.",
            "Use deterministic URL/state/network assertion relevant to the business flow.",
            "Avoid networkidle as the only wait for dynamic applications.",
        ])
    elif primary == "environment_or_network":
        plan.extend([
            "Do not auto-patch framework code first.",
            "Verify VPN/proxy/base URL/auth/test data/certificates from the same machine where browser runs.",
            "Rerun after environment is stable, then re-run RCA if the same code-level failure remains.",
        ])
    else:
        plan.extend([
            "Review execution-console.log and Playwright HTML report for the exact failing step.",
            "Use MCP locator RCA to extract failed locator/action candidates.",
            "Patch only files listed in the allowed file scope after evidence is available.",
        ])
    return {
        "ok": True,
        "provider": "deterministic",
        "auto_patch_available": False,
        "primary_failure_kind": primary,
        "failed_specs": failed_specs,
        "allowed_files": allowed_files,
        "plan": plan,
        "message": "Safe fix plan generated. Codex/Ollama is needed to auto-apply the patch; otherwise apply this plan manually and then click Run failed tests again.",
        "common_cause_priority": primary_common,
        "evidence_summary": {
            "signals": signals[:5],
            "mcp_locator_candidates": mcp.get("failed_locator_or_action_candidates") or [],
            "mcp_text_candidates": mcp.get("visible_text_candidates") or [],
            "failure_excerpt": failure_text[-3000:],
        },
    }


def _write_self_healing_html(payload: dict[str, Any]) -> Path:
    EXISTING_REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    framework_for_locations = str(payload.get("framework_path") or ((payload.get("root_cause") or {}).get("framework_path") or ""))
    artifact_locations = existing_framework_artifact_locations(framework_for_locations)
    plan = payload.get("deterministic_fix_plan") or {}
    changed = (payload.get("patch_diff") or {}).get("changed_files") or []
    rca = payload.get("root_cause") or {}
    rows = []
    for i, step in enumerate(plan.get("plan") or [], 1):
        rows.append(f"<li>{_html(step)}</li>")
    case_fix_rows = []
    for rec in (((rca.get('plain_english_failure_report') or {}).get('test_case_outcomes')) or []):
        if str(rec.get('status') or '').lower() == 'failed':
            evidence = "<br/>".join(_html(x) for x in (rec.get('observed_evidence') or []))
            recommended = "<br/>".join(f"<code>{_html(x)}</code>" for x in (rec.get('recommended_files') or [])) or "No file selected until evidence is confirmed."
            confidence = f"{float(rec.get('confidence') or 0):.0%}"
            case_fix_rows.append(f"<tr><td><code>{_html(rec.get('spec'))}</code><br/>line {_html(rec.get('line'))}</td><td>{_html(rec.get('test'))}</td><td><b>{_html(rec.get('failure_category'))}</b><br/>{_html(confidence)}</td><td>{evidence}</td><td>{_html(rec.get('plain_english_reason'))}</td><td><b>{_html(rec.get('likely_fix_layer'))}</b><br/>{_html(rec.get('suggested_fix_area'))}<br/><br/>{recommended}</td><td>{_html(rec.get('validation_steps'))}<br/><br/><b>{_html(rec.get('self_healing_safety'))}</b></td></tr>")
    files = []
    for f in (payload.get("scope") or {}).get("allowed_files") or []:
        files.append(f"<li><code>{_html(f)}</code></li>")
    changed_rows = []
    for f in changed:
        changed_rows.append(f"<li><code>{_html(f)}</code></li>")
    checklist_rows = []
    for c in (payload.get("auditable_rca_reasoning_checklist") or (rca.get("auditable_rca_reasoning_checklist") or {})).get("checks", []):
        checklist_rows.append(f"<tr><td>{_html(c.get('order'))}</td><td>{_html(c.get('check'))}</td><td>{_html(c.get('status'))}</td><td>{_html(c.get('fix_decision'))}</td></tr>")
    ext = payload.get("external_research_context") or (rca.get("external_research_context") or {})
    ext_queries = ''.join(f"<li><code>{_html(q)}</code></li>" for q in (ext.get('queries') or [])[:12])
    common = payload.get("common_cause_analysis") or (rca.get("common_cause_analysis") or {})
    gate = payload.get("multi_signal_gate_status") or rca.get("multi_signal_gate_status") or {}
    gate_class = "ok" if gate.get("final_patch_allowed") else ("warn" if gate else "warn")
    common_rows = []
    for g in (common.get("groups") or [])[:20]:
        common_rows.append(f"<tr><td>{_html(g.get('component'))}</td><td>{_html(g.get('failure_kind'))}</td><td>{_html(g.get('impacted_count'))}</td><td><pre>{_html(json.dumps(g.get('impacted_specs') or [], indent=2, ensure_ascii=False)[:2500])}</pre></td><td>{_html(g.get('recommended_fix_priority'))}</td></tr>")
    html = f"""<!doctype html><html><head><meta charset='utf-8'/><title>Existing Framework Self-Healing Report</title>
<style>body{{font-family:Segoe UI,Arial,sans-serif;margin:24px;background:#f8fafc;color:#0f172a}}.card{{background:white;border:1px solid #dbe3ef;border-radius:14px;padding:16px;margin:14px 0}}.ok{{color:#16a34a;font-weight:800}}.bad{{color:#dc2626;font-weight:800}}.warn{{color:#b45309;font-weight:800}}code{{background:#0f172a;color:#dbeafe;padding:3px 6px;border-radius:6px}}pre{{white-space:pre-wrap;background:#0f172a;color:#dbeafe;border-radius:10px;padding:14px}}</style></head><body>
<h1>Existing Framework Self-Healing Report</h1>
<div class='card'><b>Status:</b> <span class='{ 'ok' if payload.get('applied') else 'warn' }'>{_html(payload.get('stage'))}</span><p>{_html(payload.get('message'))}</p></div>
<div class='card'><h2>Local storage locations</h2><p><b>Central reports:</b> <code>{_html(artifact_locations.get('central_report_root'))}</code></p><p><b>RCA/self-healing cache, logs and backups:</b> <code>{_html(artifact_locations.get('central_cache_root'))}</code></p><p><b>Selected Playwright framework:</b> <code>{_html(artifact_locations.get('selected_framework_root'))}</code></p><p>Playwright's native report is normally under the selected framework's <code>playwright-report/index.html</code>; AstraHeal retains a stable copy under the central reports folder.</p></div>
<div class='card'><h2>Human approval and multi-signal RCA gate</h2><p class='{gate_class}'>{_html(gate.get('user_message') or 'No separate gate status was recorded for this proposal/apply step.')}</p><pre>{_html(json.dumps(gate, indent=2, ensure_ascii=False)[:12000])}</pre></div>
<div class='card'><h2>Codex apply diagnostics</h2><p>This section explains whether Codex was missing, unauthenticated, failed, or executed successfully but returned no file diff. Human approval is not treated as missing when the popup was approved.</p><pre>{_html(json.dumps({'codex_apply_diagnostics': payload.get('codex_apply_diagnostics'), 'codex_attempts': payload.get('codex_attempts'), 'deterministic_fallback_patch': payload.get('deterministic_fallback_patch'), 'ai_message': (payload.get('ai') or {}).get('message')}, indent=2, ensure_ascii=False)[:24000])}</pre></div>
<div class='card'><h2>Failed specs in scope</h2><pre>{_html(json.dumps(rca.get('failed_specs') or [], indent=2, ensure_ascii=False))}</pre></div>
<div class='card'><h2>Specific failed tests and evidence-based safe fix</h2><p>Each row separates observed evidence from the inferred cause, identifies the correct framework layer, lists likely files, and states whether self-healing is safe. Locator changes are not recommended for module, environment, browser, authentication or unverified assertion failures.</p><table style="width:100%;border-collapse:collapse"><thead><tr><th>Spec / line</th><th>Failed test</th><th>Category / confidence</th><th>Observed evidence</th><th>Plain-English cause</th><th>Fix layer / likely files</th><th>Validation / healing safety</th></tr></thead><tbody>{''.join(case_fix_rows) if case_fix_rows else '<tr><td colspan="7">No failed test-case level evidence found. Use native shard report/trace before patching.</td></tr>'}</tbody></table></div>
<div class='card'><h2>Safe fix plan</h2><ol>{''.join(rows) if rows else '<li>No deterministic plan was generated.</li>'}</ol></div>
<div class='card'><h2>Common-cause fix priority</h2><p>When several workflows fail because of the same component, the shared component is fixed first before individual test edits.</p><table style="width:100%;border-collapse:collapse"><thead><tr><th>Shared component/action</th><th>Failure kind</th><th>Impacted count</th><th>Impacted specs</th><th>Fix priority</th></tr></thead><tbody>{''.join(common_rows) if common_rows else '<tr><td colspan="5">No common-cause group available.</td></tr>'}</tbody></table><p><a href='/artifacts/reports/existing-framework/common-cause-memory.html' target='_blank'>Open common-cause memory/cache</a></p></div>
<div class='card'><h2>Auditable RCA reasoning checklist used for patching</h2><table style="width:100%;border-collapse:collapse"><thead><tr><th>#</th><th>Check</th><th>Status</th><th>Fix decision</th></tr></thead><tbody>{''.join(checklist_rows) if checklist_rows else '<tr><td colspan="4">No checklist available.</td></tr>'}</tbody></table><p>This is an observable RCA checklist, not hidden chain-of-thought.</p></div>
<div class='card'><h2>External MCP research context</h2><p>{_html(ext.get('message'))}</p><ul>{ext_queries or '<li>No external research queries available or feature disabled.</li>'}</ul></div>
<div class='card'><h2>Approved write boundary (not files changed)</h2><p>These files are the maximum boundary AI was allowed to modify. They are not all changed. The exact changed/impacted files appear in the next section. Whole-workspace write expansion is disabled unless explicitly granted.</p><ul>{''.join(files) if files else '<li>No allowed files resolved. Patch blocked.</li>'}</ul></div>
<div class='card'><h2>Files changed / impacted</h2><ul>{''.join(changed_rows) if changed_rows else '<li>No files were changed by this step.</li>'}</ul></div>
<div class='card'><h2>Patch review and rollback</h2><p><b>Applied:</b> {_html(payload.get('applied'))} &nbsp; <b>Human review required:</b> {_html(payload.get('human_approval_required'))}</p><p><b>Backup root:</b> <code>{_html((payload.get('backup') or {}).get('backup_root'))}</code></p><p>If failed-only validation is not good, use the GUI button <b>Rollback last AI fix</b> or restore the listed changed files from the backup root.</p><pre>{_html(json.dumps({'patch_confidence_review': payload.get('patch_confidence_review'), 'policy_validation': payload.get('policy_validation'), 'confidence_restore': payload.get('confidence_restore')}, indent=2, ensure_ascii=False)[:24000])}</pre></div>
<div class='card'><h2>Raw details</h2><pre>{_html(json.dumps(payload, indent=2, ensure_ascii=False)[:70000])}</pre></div>
</body></html>"""
    out = EXISTING_REPORTS_DIR / "self-healing-report.html"
    out.write_text(html, encoding="utf-8")
    return out


def _patch_changed_files(root: Path, backup: dict[str, Any], allowed_files: list[str]) -> dict[str, Any]:
    backup_root = str(backup.get("backup_root") or "")
    if not backup_root:
        return {"changed_files": [], "combined_diff": "", "skipped": True, "reason": "No backup root available for diff."}
    return diff_against_backup(root, backup_root, allowed_files)





def _codex_apply_runtime_diagnostics(root: Path) -> dict[str, Any]:
    """Return a small, user-facing Codex readiness snapshot for patch apply.

    This separates three situations that previously looked identical on the GUI:
    1. Codex is missing/not authenticated.
    2. Codex executed but returned an error.
    3. Codex executed successfully but chose not to edit any file.
    """
    diag: dict[str, Any] = {
        "checked_at": datetime.now().isoformat(timespec="seconds"),
        "workspace": str(root),
        "codex_found": False,
        "login_status_checked": False,
        "login_ok": None,
        "login_exit_code": None,
        "login_stdout_tail": "",
        "login_stderr_tail": "",
        "message": "Codex readiness was not checked yet.",
    }
    try:
        provider = CodexCliProvider(root, timeout_seconds=30)
        diag["codex_found"] = bool(provider.is_available())
        if not diag["codex_found"]:
            diag["message"] = "Codex CLI executable was not found on PATH for the GUI backend process."
            return diag
        status = provider.login_status()
        diag.update({
            "login_status_checked": True,
            "login_ok": bool(status.ok),
            "login_exit_code": status.exit_code,
            "login_stdout_tail": _safe_str(status.stdout, 4000),
            "login_stderr_tail": _safe_str(status.stderr, 4000),
        })
        if status.ok:
            diag["message"] = "Codex CLI is available to the GUI backend. If no files change, it is a no-diff/patch-decision issue, not a login issue."
        else:
            diag["message"] = "Codex CLI was found but login/status check did not confirm an authenticated backend session."
        return diag
    except Exception as exc:
        diag["message"] = f"Codex readiness check failed safely: {type(exc).__name__}: {exc}"
        return diag


def _summarize_codex_attempt(name: str, result: Any) -> dict[str, Any]:
    return {
        "attempt": name,
        "ok": bool(getattr(result, "ok", False)),
        "exit_code": getattr(result, "exit_code", None),
        "stdout_tail": _safe_str(getattr(result, "stdout", ""), 8000),
        "stderr_tail": _safe_str(getattr(result, "stderr", ""), 8000),
    }


def _codex_attempt_timed_out(ai: dict[str, Any] | None, attempts: list[dict[str, Any]] | None) -> bool:
    text = json.dumps({"ai": ai or {}, "attempts": attempts or []}, ensure_ascii=False).lower()
    return "timed out" in text or "timeout" in text or "exit_code\": 124" in text or "exit_code': 124" in text


def _approved_apply_mode(policy_mode: str, approval_decision: str) -> bool:
    approved_decisions = {"approve", "approved", "approve_with_guidance", "approve_with_backup_and_validate"}
    approved_modes = {"approved_with_backup", "local_approved", "vm_vdi_approved", "apply_and_validate"}
    return (approval_decision or "").strip().lower() in approved_decisions and (policy_mode or "approved_with_backup").strip().lower() in approved_modes


def _build_focused_codex_retry_prompt(
    root: Path,
    rca: dict[str, Any],
    failure_text: str,
    allowed_files: list[str],
    prompt_allowed_files: list[str],
    excerpts: dict[str, str],
    deterministic_fix_plan: dict[str, Any],
    runtime_human_approval: dict[str, Any],
    policy_mode: str,
) -> str:
    failed_cases = [x for x in (((rca.get("plain_english_failure_report") or {}).get("test_case_outcomes")) or []) if str(x.get("status") or "").lower() == "failed"]
    concise_cases = [
        {
            "spec": x.get("spec"),
            "line": x.get("line"),
            "test": x.get("test"),
            "reason": x.get("plain_english_reason"),
            "fix_area": x.get("suggested_fix_area"),
        }
        for x in failed_cases[:50]
    ]
    return f"""
AstraHeal approved patch retry: the first Codex attempt returned without changing framework files.
This is an explicit human-approved apply step in policy mode: {policy_mode}.

You are running inside the selected Playwright framework workspace:
{root}

Important instruction: DO NOT return only an explanation or plan. Make the smallest safe edit to one or more allowed framework files if a code-level fix is supported by the evidence. Preserve POM layering: spec -> page method -> pageObject/locator repository/helper. Do not add test.skip/test.fixme/test.only. Do not add waits above 30000ms.

Failed tests requiring a concrete fix:
{json.dumps(concise_cases, indent=2, ensure_ascii=False)[:16000]}

Safe deterministic plan to implement:
{json.dumps((deterministic_fix_plan or {}).get('plan') or [], indent=2, ensure_ascii=False)[:6000]}

Allowed patch files, prioritized:
{json.dumps(prompt_allowed_files[:80], indent=2, ensure_ascii=False)[:16000]}

Runtime human approval:
{json.dumps(runtime_human_approval, indent=2, ensure_ascii=False)[:6000]}

Failure evidence:
{failure_text[-12000:]}

Focused file excerpts:
{json.dumps(excerpts, indent=2, ensure_ascii=False)[:28000]}

If the locator is missing/not found:
- verify whether the locator belongs in pageObjects/locator repository or a page method;
- replace/add a stable role/testId/label/text locator compatible with the framework style;
- do not weaken assertions or bypass the test.

If the element is detached/unstable/intercepted:
- patch reusable BasePage/page method helper to re-query after page settles, scroll, handle blockers, and click/assert safely;
- avoid blind sleeps and force:true by default.

Return a concise summary of files changed after editing.
""".strip()


def _candidate_deterministic_patch_files(root: Path, allowed_files: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    keywords = ("base-page", "basepage", "mobile-base", "page", "helper", "action", "click", "locator")
    for rel in allowed_files or []:
        norm = str(rel or "").replace("\\", "/").lstrip("./")
        low = norm.lower()
        if not norm or norm in seen:
            continue
        if not (low.endswith(tuple(TS_SUFFIXES)) and any(k in low for k in keywords)):
            continue
        if (root / norm).exists() and (root / norm).is_file():
            seen.add(norm)
            ordered.append(norm)
    # Common enterprise Playwright locations are included only when they exist;
    # policy validation still audits the actual changed file.
    for norm in [
        "pages/base-page.ts", "pages/BasePage.ts", "src/pages/base-page.ts", "src/pages/BasePage.ts",
        "pages/mobile/mobile-base-page.ts", "src/pages/mobile/mobile-base-page.ts",
        "utils/base-page.ts", "helpers/base-page.ts", "support/base-page.ts",
    ]:
        if norm not in seen and (root / norm).exists() and (root / norm).is_file():
            seen.add(norm)
            ordered.append(norm)
    return ordered[:20]


def _try_deterministic_self_heal_patch(root: Path, rca: dict[str, Any], failure_text: str, allowed_files: list[str]) -> dict[str, Any]:
    """Apply a very small deterministic fallback patch when Codex produced no diff.

    This is intentionally conservative.  It only touches common BasePage/action
    helper patterns already present in the user's framework.  It does not change
    assertions, skip tests, or invent product behavior.  The patch remains under
    backup/policy validation and must be validated by failed-only rerun.
    """
    low = (failure_text or "").lower()
    if _is_module_resolution_failure(failure_text):
        return {
            "attempted": False,
            "changed_files": [],
            "message": "Deterministic fallback skipped source edits because this is a module/path-alias runtime failure. AstraHeal preloads a generated tsconfig alias resolver during execution; any permanent framework-source change should be human-approved through Codex/package/config review.",
            "recommended_layer": "playwright.config.ts / tsconfig.json / package.json / runtime bootstrap",
        }
    if not any(k in low for k in ["locator", "tobevisible", "element(s) not found", "not attached", "detached", "intercepts pointer events", "locator.click", "scrollintoviewifneeded"]):
        return {"attempted": False, "changed_files": [], "message": "Deterministic fallback skipped because the failure evidence was not locator/actionability related."}
    changed: list[str] = []
    details: list[dict[str, Any]] = []
    marker = "AstraHeal deterministic self-healing fallback"
    for rel in _candidate_deterministic_patch_files(root, allowed_files):
        path = root / rel
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        if marker in text:
            continue
        new = text
        local_changes: list[str] = []
        # Most common BasePage assertVisible pattern seen in enterprise POMs.
        patterns = [
            "await expect(locator, message).toBeVisible();",
            "await expect(locator).toBeVisible();",
        ]
        replacement_with_message = """try {
      await locator.scrollIntoViewIfNeeded({ timeout: 5000 });
    } catch {
      // AstraHeal deterministic self-healing fallback: element may be detached or below viewport; final expect keeps accurate failure evidence.
    }
    await expect(locator, message).toBeVisible({ timeout: 10000 });"""
        replacement_no_message = """try {
      await locator.scrollIntoViewIfNeeded({ timeout: 5000 });
    } catch {
      // AstraHeal deterministic self-healing fallback: element may be detached or below viewport; final expect keeps accurate failure evidence.
    }
    await expect(locator).toBeVisible({ timeout: 10000 });"""
        if patterns[0] in new:
            new = new.replace(patterns[0], replacement_with_message, 1)
            local_changes.append("assertVisible scroll/actionability guard")
        elif patterns[1] in new:
            new = new.replace(patterns[1], replacement_no_message, 1)
            local_changes.append("toBeVisible scroll/actionability guard")
        click_patterns = [
            "await locator.click({ timeout: 15_000 });",
            "await locator.click({ timeout: 15000 });",
            "await locator.click();",
        ]
        click_replacement = """await locator.scrollIntoViewIfNeeded({ timeout: 5000 }).catch(() => {});
      // AstraHeal deterministic self-healing fallback: re-use Playwright Locator laziness, then click with bounded timeout.
      await locator.click({ timeout: 10000 });"""
        for pat in click_patterns:
            if pat in new and "deterministic self-healing fallback: re-use Playwright Locator" not in new:
                new = new.replace(pat, click_replacement, 1)
                local_changes.append("bounded scroll-before-click guard")
                break
        tap_patterns = [
            "await locator.tap({ timeout: 15_000 });",
            "await locator.tap({ timeout: 15000 });",
        ]
        tap_replacement = """await locator.scrollIntoViewIfNeeded({ timeout: 5000 }).catch(() => {});
      // AstraHeal deterministic self-healing fallback: tap after bounded scroll/actionability check.
      await locator.tap({ timeout: 10000 });"""
        for pat in tap_patterns:
            if pat in new and "deterministic self-healing fallback: tap after" not in new:
                new = new.replace(pat, tap_replacement, 1)
                local_changes.append("bounded scroll-before-tap guard")
                break
        if new != text:
            try:
                path.write_text(new, encoding="utf-8")
                changed.append(rel)
                details.append({"file": rel, "changes": local_changes})
            except Exception as exc:
                details.append({"file": rel, "error": f"{type(exc).__name__}: {exc}"})
    return {
        "attempted": True,
        "changed_files": changed,
        "details": details,
        "message": (
            f"Deterministic fallback changed {len(changed)} helper file(s). Validate by rerunning failed tests."
            if changed else
            "Deterministic fallback ran but found no safe known BasePage/action helper pattern to patch."
        ),
    }


def _no_change_self_heal_message(ai: dict[str, Any], codex_diag: dict[str, Any], codex_attempts: list[dict[str, Any]], deterministic_fallback: dict[str, Any], provider: str) -> str:
    provider = (provider or "").lower()
    if provider != "codex":
        return "No framework files were changed because the selected provider is proposal-only for direct patching. Select Codex CLI for approved file changes, or apply the generated plan manually."
    if codex_diag and not codex_diag.get("codex_found"):
        return "No framework files were changed because the GUI backend cannot find Codex CLI on PATH. This is a backend environment issue, not a human approval issue."
    if codex_diag and codex_diag.get("login_status_checked") and codex_diag.get("login_ok") is False:
        return "No framework files were changed because the GUI backend could not confirm an authenticated Codex CLI session. Fresh login must be completed in the same Windows/VM user context that runs AstraHeal GUI."
    any_attempt_ok = any(bool(a.get("ok")) for a in codex_attempts or [])
    if any_attempt_ok:
        fb_msg = (deterministic_fallback or {}).get("message") or "No deterministic fallback was applied."
        return "Codex CLI executed after human approval, but no file diff was produced. AstraHeal retried with a smaller focused patch prompt and checked deterministic fallback. " + fb_msg + " Open the self-healing report to see Codex stdout/stderr and exact failed tests. Failed-only rerun scope is preserved."
    if codex_attempts:
        if _codex_attempt_timed_out(ai, codex_attempts):
            fb_msg = (deterministic_fallback or {}).get("message") or "Deterministic fallback did not apply a safe patch."
            return (
                "No framework files were changed because Codex CLI timed out before producing a patch. "
                "Codex login can still be valid; timeout usually means the repo/prompt was too large, the VM/VDI was slow, or Codex/network reasoning exceeded the backend limit. "
                + fb_msg
                + " To avoid this, AstraHeal now uses a smaller patch prompt by default. You can also set ASTRAHEAL_CODEX_PATCH_TIMEOUT_SECONDS=420 for large repos, or grant exact pageObject/helper files in Human Update memory."
            )
        last = codex_attempts[-1]
        tail = (last.get("stderr_tail") or last.get("stdout_tail") or "")[-500:]
        return "No framework files were changed because Codex patch execution did not complete successfully. " + (tail or "Check Codex diagnostics in the self-healing report.")
    return "No framework files were changed. AstraHeal preserved failed-only rerun scope and recorded diagnostics in the self-healing report."

def _workspace_approved_patch_files(root: Path, seed_files: list[str] | None = None, max_files: int = 700) -> list[str]:
    """Return a broad but bounded patch scope for user-approved local/VM workspaces.

    This is used when the user explicitly selects an apply-and-validate mode. It
    lets Codex patch non-standard Playwright frameworks where specs/pages/objects
    are not connected by simple imports, while still excluding generated reports,
    node_modules, caches and other unsafe folders.
    """
    root = root.resolve()
    seen: set[str] = set()
    ordered: list[str] = []

    def add_file(path: Path) -> None:
        try:
            resolved = path.resolve()
            if not resolved.exists() or not resolved.is_file() or _is_ignored(resolved, root):
                return
            if not str(resolved).lower().startswith(str(root).lower()):
                return
            rel = _rel_to(resolved, root)
            if rel in seen:
                return
            if resolved.suffix.lower() in TS_SUFFIXES or resolved.name.lower() in {
                "playwright.config.ts", "playwright.config.js", "playwright.config.mjs",
                "package.json", "tsconfig.json",
            }:
                seen.add(rel)
                ordered.append(rel)
        except Exception:
            return

    for rel in seed_files or []:
        add_file(root / rel)

    preferred_roots = [
        "tests", "test", "specs", "e2e", "src", "pages", "pageObjects",
        "page-objects", "objects", "locators", "selectors", "utils", "helpers",
        "support", "fixtures", "testData", "test-data", "data", "config",
    ]
    for folder in preferred_roots:
        base = root / folder
        if not base.exists() or not base.is_dir():
            continue
        for child in base.rglob("*"):
            if len(ordered) >= max_files:
                return ordered
            add_file(child)

    # Add important root-level config files at the end.
    for name in ["playwright.config.ts", "playwright.config.js", "playwright.config.mjs", "package.json", "tsconfig.json"]:
        if len(ordered) >= max_files:
            break
        add_file(root / name)
    return ordered

def _resolve_runtime_approved_files(root: Path, values: str, max_files: int = 200) -> list[str]:
    """Resolve only the files/folders explicitly submitted in this popup."""
    approved: list[str] = []
    seen: set[str] = set()
    for raw_value in re.split(r"[\r\n,;]+", str(values or "")):
        raw = raw_value.strip().strip('"').strip("'").replace("\\", "/")
        if not raw:
            continue
        try:
            candidate = Path(raw)
            resolved = candidate.resolve() if candidate.is_absolute() else (root / raw.lstrip("./")).resolve()
            if not str(resolved).lower().startswith(str(root.resolve()).lower()) or not resolved.exists() or _is_ignored(resolved, root):
                continue
            files = [resolved] if resolved.is_file() else [p.resolve() for p in resolved.rglob("*") if p.is_file() and not _is_ignored(p, root)]
            for file in files:
                if len(approved) >= max_files:
                    return approved
                if file.suffix.lower() not in TS_SUFFIXES and file.name.lower() not in {
                    "playwright.config.ts", "playwright.config.js", "playwright.config.mjs", "playwright.config.cjs",
                    "package.json", "package-lock.json", "pnpm-lock.yaml", "yarn.lock", "tsconfig.json", "jsconfig.json",
                }:
                    continue
                rel = _rel_to(file, root)
                if rel not in seen:
                    seen.add(rel)
                    approved.append(rel)
        except Exception:
            continue
    return approved


def _human_approved_patch_files(root: Path, human_memory: dict[str, Any] | None = None) -> list[str]:
    """Return human-approved files that may extend the safe patch scope.

    This does not grant full-repo access.  It only adds files the user explicitly
    listed under "Files human approves as safe for AI to patch" and only when
    those files exist under the selected framework root.
    """
    human_memory = human_memory or read_human_intervention_memory(limit=50)
    records = list(human_memory.get("records") or [])
    latest = human_memory.get("latest_update") or {}
    if latest:
        records.append(latest)
    approved: list[str] = []
    seen: set[str] = set()
    for rec in records:
        if str(rec.get("decision") or "").lower() not in {"approved_to_patch", "reviewed", "manual_fix_done"}:
            continue
        candidates = list(rec.get("safe_files_confirmed_by_human") or [])
        # If the user selected approved_to_patch and filled affected_files, treat
        # those as additional safe files.  This is the "folder/file access" grant.
        if str(rec.get("decision") or "").lower() == "approved_to_patch":
            candidates.extend(rec.get("affected_files") or [])
        for value in candidates:
            raw = str(value or "").strip().strip('"').strip("'").replace("\\", "/")
            if not raw:
                continue
            p = Path(raw)
            try:
                if p.is_absolute():
                    resolved = p.resolve()
                    if not str(resolved).lower().startswith(str(root.resolve()).lower()):
                        continue
                    rel = _rel_to(resolved, root)
                else:
                    rel = raw.lstrip("./")
                    resolved = (root / rel).resolve()
                if not resolved.exists() or _is_ignored(resolved, root):
                    continue
                candidate_files: list[Path] = []
                if resolved.is_dir():
                    # Folder access grant: include TS/JS files under this folder,
                    # capped to prevent accidental whole-repo patching.
                    for child in resolved.rglob("*"):
                        if len(candidate_files) >= 80:
                            break
                        if child.is_file() and not _is_ignored(child, root) and child.suffix.lower() in TS_SUFFIXES:
                            candidate_files.append(child.resolve())
                elif resolved.is_file():
                    candidate_files = [resolved]
                for candidate in candidate_files:
                    if candidate.suffix.lower() not in TS_SUFFIXES and candidate.name.lower() not in {"playwright.config.ts", "playwright.config.js", "package.json"}:
                        continue
                    rel = _rel_to(candidate, root)
                    if rel not in seen:
                        approved.append(rel)
                        seen.add(rel)
            except Exception:
                continue
    return approved


def _effective_policy_for_apply_mode(policy: dict[str, Any], allowed_files: list[str], policy_mode: str = "approved_with_backup") -> dict[str, Any]:
    """Return the policy used for the current AI patch attempt.

    Strict enterprise mode keeps all deterministic blocks.  Local/VM approved
    mode is designed for user-owned workspaces where the user explicitly wants
    the AI patch to be kept for validation instead of repeatedly rolling back.
    It still blocks destructive test-disabling changes, keeps a backup, records
    changed files, and exposes rollback.
    """
    mode = (policy_mode or "approved_with_backup").strip().lower()
    effective = dict(policy or {})
    effective["applyMode"] = mode
    effective["version"] = f"{effective.get('version', 'enterprise-policy')}+{mode}"
    if mode in {"approved_with_backup", "local_approved", "vm_vdi_approved", "apply_and_validate"}:
        parent_prefixes: set[str] = set()
        for rel in allowed_files or []:
            norm = str(rel or "").replace("\\", "/").lstrip("./")
            if not norm:
                continue
            parts = norm.split("/")
            if len(parts) > 1:
                parent_prefixes.add("/".join(parts[:-1]) + "/")
        common_framework_prefixes = {
            "src/", "tests/", "test/", "specs/", "e2e/", "playwright/",
            "pages/", "page/", "pageObjects/", "page-objects/", "objects/",
            "locators/", "selectors/", "utils/", "helpers/", "support/",
            "fixtures/", "testData/", "test-data/", "data/", "config/",
        }
        effective["allowedPaths"] = sorted(set(effective.get("allowedPaths") or []) | parent_prefixes | common_framework_prefixes)
        # In approved mode, do not rollback for pragmatic fixes such as spec-level
        # locator additions, force:true, or waitForTimeout. They remain visible in
        # the self-healing report and can be rolled back by the user.
        effective["blockedPatterns"] = [r"test\.skip\s*\(", r"test\.fixme\s*\(", r"\.only\s*\("]
        effective["allowForceClick"] = True
        effective["allowSpecLocatorAddition"] = True
        effective["allowAssertionChange"] = True
        effective["humanApprovalBecomesWarning"] = True
    return effective


def _severe_policy_violations(policy_validation: dict[str, Any], policy_mode: str = "approved_with_backup") -> list[dict[str, Any]]:
    """Violations that are unsafe enough to auto-rollback.

    In strict enterprise mode, legacy severe violations still rollback. In
    approved local/VM mode, only destructive test-disabling patterns rollback;
    other issues are warnings because the user validates by rerunning failed
    tests and can use Rollback last AI fix.
    """
    mode = (policy_mode or "approved_with_backup").strip().lower()
    violations = policy_validation.get("violations") or []
    if mode == "strict_enterprise":
        severe_types = {"OUT_OF_FAILED_SCOPE", "DISALLOWED_PATH", "BLOCKED_PATTERN", "RAW_LOCATOR_IN_SPEC", "FORCE_CLICK_DEFAULT"}
        return [v for v in violations if str(v.get("type") or "") in severe_types]

    severe: list[dict[str, Any]] = []
    for v in violations:
        typ = str(v.get("type") or "")
        pat = str(v.get("pattern") or "")
        # Destructive test-disabling edits are still blocked in every mode.
        if typ == "BLOCKED_PATTERN" and any(token in pat for token in ["test\\.skip", "test\\.fixme", "\\.only"]):
            severe.append(v)
    return severe


def _approval_decision_is_positive(decision: str) -> bool:
    return (decision or "").strip().lower() in {"approve", "approved", "approve_with_guidance", "approve_with_backup_and_validate", "yes"}


def _multi_signal_gate_status(rca: dict[str, Any], policy_mode: str, approval_decision: str = "", allowed_files: list[str] | None = None) -> dict[str, Any]:
    """Return auditable gate status for AI patch apply.

    The multi-signal RCA gate is an evidence quality gate, not a second hidden
    approval prompt.  In approved local/VM modes, an explicit runtime popup
    approval allows AstraHeal to try a minimal Codex patch with backup and
    rollback even when the evidence confidence is below the automatic threshold.
    Strict enterprise mode remains gated.  Destructive edits are still blocked
    later by policy validation/rollback.
    """
    robust_strategy = rca.get("robust_multi_signal_rca") or {}
    strategy = robust_strategy.get("strategy") if isinstance(robust_strategy, dict) else {}
    selected = (strategy or {}).get("selected_chain") or {}
    original_auto_allowed = bool((strategy or {}).get("auto_heal_allowed", False)) if robust_strategy else True
    confidence = float((strategy or {}).get("confidence") or selected.get("confidence") or 0.0) if robust_strategy else 1.0
    mode = (policy_mode or "approved_with_backup").strip().lower()
    positive_approval = _approval_decision_is_positive(approval_decision)
    approved_modes = {"approved_with_backup", "local_approved", "vm_vdi_approved", "apply_and_validate"}
    has_scope = bool(allowed_files)
    override_allowed = bool(robust_strategy and positive_approval and mode in approved_modes and has_scope)
    final_allowed = bool(original_auto_allowed or override_allowed or not robust_strategy)
    status = {
        "has_multi_signal_rca": bool(robust_strategy),
        "policy_mode": mode,
        "selected_chain": selected,
        "confidence": confidence,
        "original_auto_heal_allowed": original_auto_allowed,
        "runtime_human_approval_received": positive_approval,
        "runtime_approval_override_allowed": override_allowed,
        "final_patch_allowed": final_allowed,
        "blocked_reason": "" if final_allowed else "Multi-signal RCA confidence gate blocked auto-apply and no runtime approval override was available.",
        "user_message": (
            "Human approval popup was received. AstraHeal will proceed with a minimal AI patch attempt using backup, policy validation and rollback."
            if override_allowed and not original_auto_allowed else
            "Multi-signal RCA gate allowed automatic self-healing."
            if original_auto_allowed else
            "Multi-signal RCA gate blocked patching. Approve the runtime popup in approved local/VM mode or provide safe files/human guidance."
        ),
    }
    try:
        if robust_strategy and isinstance(strategy, dict):
            strategy["original_auto_heal_allowed"] = original_auto_allowed
            strategy["runtime_human_approval_received"] = positive_approval
            strategy["runtime_approval_override_allowed"] = override_allowed
            strategy["final_patch_allowed"] = final_allowed
            strategy["human_approval_override_note"] = status["user_message"]
    except Exception:
        pass
    return status




def create_runtime_patch_approval_request(
    framework_path: str = "",
    provider: str = "codex",
    model: str = "llama3",
    base_url: str = "",
    policy_mode: str = "approved_with_backup",
) -> dict[str, Any]:
    """Build a human-readable runtime approval request before applying an AI patch.

    The frontend renders this as a popup.  This function does not change files.
    It summarizes the failed-test scope, allowed files, likely risks, and best
    practice recommendation so the user can Approve, Deny, or add guidance.
    """
    _ensure_dirs()
    provider = (provider or "codex").strip().lower()
    policy_mode = (policy_mode or "approved_with_backup").strip().lower()
    rca = analyze_existing_failure(framework_path=framework_path, provider="deterministic", model=model, base_url=base_url)
    root = _resolve_framework_path(framework_path or rca.get("framework_path", ""))
    scope = rca.get("scope") or {}
    allowed_files = list(scope.get("allowed_files") or [])
    human_memory = read_human_intervention_memory(limit=50)
    human_approved_files = _human_approved_patch_files(root, human_memory)
    # Broad workspace files are calculated only as a transparent, read/context
    # fallback. They are NOT silently added to the write approval boundary.
    # A folder/file enters write scope only when the user explicitly lists it.
    workspace_context_candidates: list[str] = []
    if policy_mode in {"approved_with_backup", "local_approved", "vm_vdi_approved", "apply_and_validate"}:
        workspace_context_candidates = _workspace_approved_patch_files(root, allowed_files, max_files=700)
    # Previous human approvals remain visible as memory/context, but they do not
    # silently expand this new runtime write boundary. The current popup is the
    # source of truth for the current patch attempt.
    effective_allowed = sorted(set(allowed_files))
    failed_categories = [str(x.get("failure_category") or "") for x in ((rca.get("plain_english_failure_report") or {}).get("test_case_outcomes") or []) if str(x.get("status") or "").lower() == "failed"]
    primary_category = next((x for x in failed_categories if x and x != "unknown_or_insufficient_evidence"), failed_categories[0] if failed_categories else "")
    recommended_files = _recommended_files_for_failure_category(scope, primary_category, max_files=20)
    if not recommended_files and primary_category not in {"authentication_or_authorization", "browser_or_runtime_crash", "assertion_or_product_behavior_mismatch", "timeout_or_unfinished_state", "unknown_or_insufficient_evidence"}:
        recommended_files = _prioritize_patch_files_for_ai(scope.get("recommended_patch_files") or effective_allowed, rca, max_files=20)
    failure_text = _failure_text(rca.get("failed_inventory") or {})
    deterministic_fix_plan = _deterministic_existing_fix_plan(rca, failure_text, effective_allowed)
    failed_case_outcomes = [x for x in ((rca.get("plain_english_failure_report") or {}).get("test_case_outcomes") or []) if str(x.get("status") or "").lower() == "failed"]

    risks: list[str] = []
    if not effective_allowed:
        risks.append("No safe patch files are resolved yet. AI needs file/folder approval or better framework learning before changing files.")
    if policy_mode == "strict_enterprise":
        risks.append("Strict enterprise mode may rollback changes that touch spec files, assertions, force-clicks or wait logic. Use approval if you want apply-and-validate behavior.")
    if provider not in {"codex", "ollama"}:
        risks.append("Automatic patching needs Codex/Ollama. Rule-based mode can propose a plan but cannot modify files.")
    signals = rca.get("signals") or []
    for sig in signals[:5]:
        cat = str(sig.get("category") or sig.get("type") or "")
        if cat and cat not in risks:
            risks.append(f"Failure signal detected: {cat}")
    if not risks:
        risks.append("No destructive risk detected before patch. The AI will still create backup, record changed files, and allow rollback.")

    questions = [
        "Do you approve AI to apply a minimal fix in the listed safe files/folders?",
        "Should the fix follow POM/reusability rules first instead of editing the spec directly?",
        "Are there any files/folders that AI is explicitly allowed to modify for this fix?",
        "Is this actually an environment/test-data/AUT behavior issue rather than a framework code issue?",
    ]
    best_practices = [
        "Prefer pageObjects/locator files first, then page methods, then helpers/fixtures/test data, and spec only when unavoidable.",
        "Do not hide failures using test.skip/test.fixme/test.only.",
        "Keep the patch small, run failed-only validation, and rollback if validation fails.",
        "Save human guidance to project memory so future RCA/self-healing can reuse it.",
    ]
    request_id = f"RTA-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    payload = {
        "ok": True,
        "approval_required": True,
        "request_id": request_id,
        "stage": "runtime_patch_approval_request",
        "framework_path": str(root),
        "provider": provider,
        "policy_mode": policy_mode,
        "failed_specs": rca.get("failed_specs") or [],
        "failed_count": len(rca.get("failed_specs") or []),
        "failed_test_cases": failed_case_outcomes[:200],
        "failed_test_case_count": len(failed_case_outcomes),
        "gui_summary": "\n".join(["Runtime approval request - failed tests in scope", *[f"{x.get('spec')} -> {x.get('test')} failed - reason: {x.get('plain_english_reason')}" for x in failed_case_outcomes[:80]]]),
        "allowed_files": effective_allowed[:300],
        "allowed_files_count": len(effective_allowed),
        "recommended_patch_files": recommended_files,
        "recommended_patch_files_count": len(recommended_files),
        "primary_failure_category": primary_category,
        "scope_groups": scope.get("scope_groups") or {},
        "file_reasons": scope.get("file_reasons") or {},
        "allowed_files_explanation": "These are the maximum files AI may write after approval, not files that will definitely change. Actual changed files are reported separately after the patch.",
        "workspace_context_candidates_count": len(workspace_context_candidates),
        "workspace_context_explanation": "Additional framework files may be read/searched for context, but they are not writable unless you explicitly add their file/folder paths in the approval box.",
        "human_approved_files": human_approved_files,
        "workspace_scope_enabled": False,
        "risks": risks,
        "questions": questions,
        "best_practices": best_practices,
        "recommended_decision": "approve_with_backup_and_validate" if effective_allowed else "provide_safe_files_or_guidance_first",
        "deterministic_fix_plan": deterministic_fix_plan,
        "root_cause": {
            "failed_specs": rca.get("failed_specs") or [],
            "signals": rca.get("signals") or [],
            "plain_english_failure_report": rca.get("plain_english_failure_report") or {},
            "common_cause_analysis": rca.get("common_cause_analysis") or {},
        },
        "message": "Runtime approval is ready. Review the per-test RCA, recommended minimal files and maximum write boundary, then approve, deny, or provide guidance.",
    }
    out = EXISTING_REPORTS_DIR / "runtime-approval-request.json"
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    log_event("human_approval", "Runtime approval request prepared for AI patch.", status="warning", progress=100, details={"request_id": request_id, "failed_count": payload["failed_count"], "allowed_files_count": len(effective_allowed)})
    return payload

def rollback_last_existing_fix() -> dict[str, Any]:
    """Restore the last AI patch from the stored backup, if available."""
    _ensure_dirs()
    if not EXISTING_SELF_HEAL_JSON.exists():
        payload = {"ok": False, "stage": "rollback_blocked_no_report", "message": "No self-healing report found. Nothing to rollback."}
        log_event("existing_framework_self_healing", payload["message"], status="warning", progress=100, details=payload)
        return payload
    try:
        report = json.loads(EXISTING_SELF_HEAL_JSON.read_text(encoding="utf-8", errors="replace"))
    except Exception as exc:
        payload = {"ok": False, "stage": "rollback_report_read_failed", "message": f"Could not read self-healing report: {type(exc).__name__}: {exc}"}
        log_event("existing_framework_self_healing", payload["message"], status="error", progress=100, details=payload)
        return payload
    root = _resolve_framework_path(report.get("framework_path") or ((report.get("root_cause") or {}).get("framework_path") or ""))
    backup = report.get("backup") or {}
    changed = report.get("changed_files") or ((report.get("patch_diff") or {}).get("changed_files") or [])
    if not changed:
        payload = {"ok": False, "stage": "rollback_blocked_no_changed_files", "message": "No changed files are listed in the last self-healing report."}
        log_event("existing_framework_self_healing", payload["message"], status="warning", progress=100, details=payload)
        return payload
    restored = restore_backup(root, backup.get("backup_root", ""), changed)
    payload = {
        "ok": bool(restored.get("count")),
        "stage": "existing_framework_last_fix_rollback_completed" if restored.get("count") else "existing_framework_last_fix_rollback_noop",
        "framework_path": str(root),
        "restored_files": restored.get("restored_files") or [],
        "backup_root": backup.get("backup_root"),
        "message": f"Rollback completed. Restored {restored.get('count', 0)} file(s)." if restored.get("count") else "Rollback did not restore any files; backup files may be missing.",
        "source_self_healing_report": str(EXISTING_SELF_HEAL_JSON),
    }
    (EXISTING_REPORTS_DIR / "rollback-report.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    log_event("existing_framework_self_healing", payload["message"], status="done" if payload["ok"] else "warning", progress=100, details=payload)
    return payload


def self_heal_existing_framework(framework_path: str = "", provider: str = "codex", model: str = "llama3", base_url: str = "", apply_patch: bool = False, policy_mode: str = "approved_with_backup", human_approval_decision: str = "", human_approval_instruction: str = "", human_approval_safe_files: str = "", human_approval_request_id: str = "") -> dict[str, Any]:
    _ensure_dirs()
    provider = (provider or "codex").lower().strip()
    action_label = "apply guarded fix" if apply_patch else "create safe fix plan"
    log_event("existing_framework_self_healing", f"Starting {action_label} for failed existing-framework specs.", status="running", progress=8, details={"provider": provider, "apply_patch": apply_patch, "policy_mode": policy_mode})

    rca = analyze_existing_failure(framework_path=framework_path, provider=provider if not apply_patch else "deterministic", model=model, base_url=base_url)
    if not rca.get("ok") or not rca.get("failed_specs"):
        payload = {"ok": False, "stage": "existing_framework_self_healing_blocked", "applied": False, "root_cause": rca, "message": rca.get("message", "No failed existing-framework scope available.")}
        EXISTING_SELF_HEAL_JSON.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        _write_self_healing_html(payload)
        log_event("existing_framework_self_healing", payload["message"], status="error", progress=100, details=payload)
        return payload

    root = _resolve_framework_path(framework_path or rca.get("framework_path", ""))
    limit_state = _failed_only_iteration_limit_state(root)
    if limit_state.get("blocked"):
        payload = _manual_review_limit_payload(root, rca.get("failed_inventory") or {}, "existing_framework_self_healing_blocked_after_two_iterations")
        payload.update({
            "applied": False,
            "root_cause": rca,
            "scope": rca.get("scope") or {},
            "self_healing_report_url": "/artifacts/reports/existing-framework/self-healing-report.html",
        })
        EXISTING_SELF_HEAL_JSON.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        _write_self_healing_html(payload)
        log_event("existing_framework_self_healing", payload["message"], status="warning", progress=100, details=payload)
        return payload
    approval_decision = (human_approval_decision or "").strip().lower()
    approval_instruction = (human_approval_instruction or "").strip()
    approval_safe_files = (human_approval_safe_files or "").strip()
    if apply_patch and approval_decision in {"deny", "denied", "reject", "rejected", "cancel"}:
        payload = {
            "ok": False,
            "stage": "existing_framework_self_healing_denied_by_human",
            "applied": False,
            "framework_path": str(root),
            "human_approval_decision": approval_decision,
            "human_approval_instruction": approval_instruction,
            "message": "AI patch was cancelled by human decision. No files were changed.",
            "root_cause": rca,
        }
        EXISTING_SELF_HEAL_JSON.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        _write_self_healing_html(payload)
        log_event("existing_framework_self_healing", payload["message"], status="warning", progress=100, details=payload)
        return payload
    scope = rca.get("scope") or {}
    human_intervention_memory = read_human_intervention_memory(limit=50)
    allowed_files = list(scope.get("allowed_files") or [])
    human_approved_files = _human_approved_patch_files(root, human_intervention_memory)
    # Historical approvals are context only. They never silently expand the
    # current patch boundary; the current Runtime AI Fix Approval textarea is
    # authoritative for this attempt.
    if human_approved_files:
        scope = {**scope, "historical_human_approved_files_context_only": human_approved_files}
        rca["scope"] = scope
    approved_modes = {"approved_with_backup", "local_approved", "vm_vdi_approved", "apply_and_validate"}
    broad_scope_opt_in = str(os.environ.get("ASTRAHEAL_ALLOW_BROAD_WORKSPACE_PATCH_SCOPE") or "").strip().lower() in {"1", "true", "yes", "on"}
    if apply_patch and broad_scope_opt_in and (policy_mode or "approved_with_backup").strip().lower() in approved_modes:
        workspace_files = _workspace_approved_patch_files(root, allowed_files, max_files=700)
        if workspace_files:
            original_count = len(allowed_files)
            allowed_files = sorted(set([*allowed_files, *workspace_files]))
            scope = {**scope, "allowed_files": allowed_files, "workspace_approved_patch_scope": {"enabled": True, "explicit_environment_opt_in": True, "original_failed_scope_count": original_count, "expanded_scope_count": len(allowed_files), "max_files": 700}, "scope_mode": (scope.get("scope_mode") or "import_graph") + "+explicit_broad_workspace_opt_in"}
            rca["scope"] = scope
    else:
        scope = {**scope, "workspace_approved_patch_scope": {"enabled": False, "reason": "Broad workspace write access is disabled by default. Add exact files/folders in Runtime AI Fix Approval to extend scope."}}
        rca["scope"] = scope

    # Runtime popup approval can grant additional safe files/folders and adds
    # human guidance to AI memory for this patch attempt. This supports the
    # runtime Approve/Deny/Provide Input workflow without weakening enterprise
    # rollback and audit behavior.
    runtime_human_approval = {"decision": approval_decision, "instruction": approval_instruction, "safe_files": approval_safe_files, "request_id": human_approval_request_id}
    if apply_patch and approval_decision in {"approve", "approved", "approve_with_guidance", "approve_with_backup_and_validate"}:
        try:
            approved_update = save_human_intervention_update(
                framework_path=str(root),
                intervention_type="framework_code",
                decision="approved_to_patch",
                summary=f"Runtime popup approval for AI fix {human_approval_request_id or ''}".strip(),
                details=approval_instruction or "User approved AI patch at runtime popup. Apply minimal safe fix with backup and rerun validation.",
                affected_files=approval_safe_files,
                safe_files=approval_safe_files,
                rerun_instruction="After patch, run failed tests again in the selected headed/headless mode.",
            )
            refreshed_human_memory = read_human_intervention_memory(limit=50)
            runtime_approved_files = _resolve_runtime_approved_files(root, approval_safe_files)
            # Exact current-popup restriction: deleting every path means no write
            # permission and blocks patching; adding a folder/file grants only it.
            allowed_files = sorted(set(runtime_approved_files))
            scope = {**scope, "allowed_files": allowed_files, "runtime_popup_approved_files": runtime_approved_files, "runtime_popup_scope_is_authoritative": True, "scope_mode": "runtime_popup_exact_write_boundary"}
            rca["scope"] = scope
            human_intervention_memory = refreshed_human_memory
            runtime_human_approval["saved_update"] = approved_update
        except Exception as exc:
            runtime_human_approval["save_warning"] = f"Could not persist runtime approval memory: {type(exc).__name__}: {exc}"

    failure_text = _failure_text(rca.get("failed_inventory") or {})
    deterministic_fix_plan = _deterministic_existing_fix_plan(rca, failure_text, allowed_files)
    auditable_checklist = rca.get("auditable_rca_reasoning_checklist") or _build_auditable_rca_reasoning_checklist(root, rca.get("failed_specs") or [], failure_text, scope=scope, mcp_locator_rca=rca.get("mcp_assisted_locator_rca") or {})
    common_cause_analysis = rca.get("common_cause_analysis") or _build_common_cause_analysis(root, rca.get("failed_inventory") or {}, failure_text, rca.get("failed_specs") or [])
    external_research_context = rca.get("external_research_context") or collect_external_fix_research(root, rca.get("failed_specs") or [], failure_text=failure_text, classification=deterministic_fix_plan.get("primary_failure_kind") or "")

    if not allowed_files:
        payload = {
            "ok": False,
            "stage": "existing_framework_self_healing_blocked_no_scope",
            "applied": False,
            "root_cause": rca,
            "scope": scope,
            "deterministic_fix_plan": deterministic_fix_plan,
            "message": "No allowed files resolved from failed specs. Automatic patching is blocked. Check the failed spec paths and import structure.",
        }
        payload["human_intervention_request"] = create_human_intervention_request(str(root), payload["message"], source="blocked_no_safe_patch_scope")
        EXISTING_SELF_HEAL_JSON.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        _write_self_healing_html(payload)
        log_event("existing_framework_self_healing", payload["message"], status="error", progress=100, details=payload)
        return payload

    multi_signal_gate = _multi_signal_gate_status(rca, policy_mode, approval_decision, allowed_files)
    rca["multi_signal_gate_status"] = multi_signal_gate
    if apply_patch and not multi_signal_gate.get("final_patch_allowed"):
        selected_chain = multi_signal_gate.get("selected_chain") or {}
        payload = {
            "ok": False,
            "stage": "existing_framework_self_healing_blocked_by_multi_signal_gate",
            "applied": False,
            "root_cause": rca,
            "scope": scope,
            "deterministic_fix_plan": deterministic_fix_plan,
            "multi_signal_gate_status": multi_signal_gate,
            "message": (
                "Auto-healing is blocked by the multi-signal RCA gate because runtime approval was not available for this apply attempt "
                "or Strict Enterprise mode is active. Use Approved local/VM mode, approve the runtime popup, and keep backup/rollback validation enabled. "
                f"Selected RCA chain: {selected_chain.get('step') or 'unknown'} - {selected_chain.get('decision') or multi_signal_gate.get('blocked_reason')}"
            ),
        }
        payload["human_intervention_request"] = create_human_intervention_request(str(root), payload["message"], source="multi_signal_gate")
        EXISTING_SELF_HEAL_JSON.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        _write_self_healing_html(payload)
        log_event("existing_framework_self_healing", payload["message"], status="warning", progress=100, details=payload)
        _write_existing_pending(rca)
        return payload
    if apply_patch and multi_signal_gate.get("runtime_approval_override_allowed"):
        log_event(
            "existing_framework_self_healing",
            "Runtime human approval overrode the low-confidence multi-signal gate; applying minimal patch with backup and rollback guardrails.",
            status="running",
            progress=24,
            details=multi_signal_gate,
        )

    base_policy = load_healing_policy()
    policy = _effective_policy_for_apply_mode(base_policy, allowed_files, policy_mode)
    backup = _backup_scope(root, allowed_files) if apply_patch else {"count": 0, "message": "Proposal mode; no backup needed because no files are changed."}
    log_event("existing_framework_self_healing", "Patch scope prepared and backup created." if apply_patch else "Patch scope prepared for proposal only.", status="running", progress=30, details={"allowed_files": allowed_files, "backup": backup})

    try:
        rag_context = query_framework_context(" ".join([*rca.get("failed_specs", []), failure_text[-3000:]]), top_k=int(os.environ.get("ASTRAHEAL_RAG_PATCH_TOP_K", "5") or 5), framework_path=root)
    except Exception as exc:
        rag_context = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    deep_framework_memory = load_deep_framework_memory()
    # Reuse the same human memory loaded at the start of the healing cycle so
    # approved safe files and user clarifications remain consistent.
    prompt_allowed_files = _prioritize_patch_files_for_ai(allowed_files, rca, max_files=int(os.environ.get("ASTRAHEAL_AI_PATCH_PROMPT_FILE_LIMIT", "60") or 60))
    prompt_scope_note = {"total_allowed_files": len(allowed_files), "prompt_file_limit": len(prompt_allowed_files), "message": "AI prompt is focused on highest-probability shared component files first to avoid long/stuck patch waits. Policy validation still audits actual changed files."}
    excerpts = _scoped_file_excerpts(root, prompt_allowed_files, max_total=int(os.environ.get("ASTRAHEAL_AI_PATCH_EXCERPT_CHARS", "12000") or 12000))
    strict_rules = [
        "Patch only allowed files from the current approved scope. In approved local/VM mode this can include the selected framework workspace files listed below.",
        "Do not modify passed specs or unrelated pages/pageObjects.",
        "Do not add test.skip, test.only, test.fixme, blind waitForTimeout, force:true by default, or any explicit/default wait above 30000ms.",
        "Preserve framework style and POM layering: spec -> page method -> pageObjects/locator definitions.",
        "If evidence indicates environment/data/product defect, do not fake pass the test.",
        "After patch, rerun failed specs only.",
    ]

    ai: dict[str, Any]
    codex_apply_diagnostics: dict[str, Any] = _codex_apply_runtime_diagnostics(root) if apply_patch and provider == "codex" else {}
    codex_attempts: list[dict[str, Any]] = []
    deterministic_fallback_patch: dict[str, Any] = {"attempted": False, "changed_files": [], "message": "Not needed."}
    if provider == "codex":
        mode_line = "Apply the minimal patch now inside this workspace." if apply_patch else "Do not modify files. Produce a patch proposal only."
        prompt = f"""
You are fixing an existing user-owned Playwright TypeScript framework. {mode_line}
If this is an apply step, actually edit the selected workspace files; do not return only a plan. After editing, return concise plain English plus changed files summary. Do not reveal hidden chain-of-thought.

AI fix permission mode: {policy_mode}
Strict guardrails:
{json.dumps(strict_rules, indent=2, ensure_ascii=False)}

Allowed files shown to AI first, prioritized for speed:
{json.dumps(prompt_allowed_files, indent=2, ensure_ascii=False)}

Prompt scope optimization:
{json.dumps(prompt_scope_note, indent=2, ensure_ascii=False)}

Failed specs only:
{json.dumps(rca.get('failed_specs', []), indent=2, ensure_ascii=False)}

Base URL:
{normalize_base_url(base_url)}

RCA summary:
{json.dumps({k: rca.get(k) for k in ['signals','recommended_fix_plan','failed_script_count','robust_multi_signal_rca','mcp_assisted_locator_rca','auditable_rca_reasoning_checklist','common_cause_analysis','external_research_context']}, indent=2, ensure_ascii=False)[:9000]}

Auditable RCA reasoning checklist to apply before patching:
{json.dumps(auditable_checklist.get('checks', []), indent=2, ensure_ascii=False)[:9000]}

Common-cause analysis to fix shared broken components before individual specs:
{json.dumps({k: common_cause_analysis.get(k) for k in ['has_multi_workflow_common_cause','primary_common_cause','groups','historical_memory_used']}, indent=2, ensure_ascii=False)[:9000]}

External MCP research context, advisory only:
{json.dumps(external_research_context, indent=2, ensure_ascii=False)[:6000]}

Failure evidence:
{failure_text[-8000:]}

Scoped file excerpts:
{json.dumps(excerpts, indent=2, ensure_ascii=False)[:12000]}

RAG context from indexed framework chunks:
{json.dumps(rag_context.get('hits', [])[:8], indent=2, ensure_ascii=False)[:6000]}

Agentic multi-agent framework memory:
{json.dumps(deep_framework_memory, indent=2, ensure_ascii=False)[:6000]}

Human intervention memory / user clarifications:
{json.dumps(human_intervention_memory, indent=2, ensure_ascii=False)[:6000]}

Runtime popup approval for this patch attempt:
{json.dumps(runtime_human_approval, indent=2, ensure_ascii=False)[:8000]}

Multi-signal RCA gate status for this patch attempt:
{json.dumps(multi_signal_gate if 'multi_signal_gate' in locals() else {}, indent=2, ensure_ascii=False)[:8000]}

Implementation guidance:
- When locator is missing/ambiguous, update locator/pageObject definition with robust getByRole/getByTestId/getByLabel fallback where the framework style supports it.
- When element is visible but not interactable, patch page method/helper to dismiss overlays, scroll into view, wait for stable DOM, retry, and then click.
- When navigation is flaky, patch reusable wait/navigation helper rather than sleeping blindly.
- Keep existing framework naming and style.
""".strip()
        try:
            codex_timeout = max(90, int(os.environ.get("ASTRAHEAL_CODEX_PATCH_TIMEOUT_SECONDS", "180") or 180))
            log_event("existing_framework_self_healing", "Codex patch execution started with optimized common-cause prompt scope.", status="running", progress=45, details={"timeout_seconds": codex_timeout, "total_allowed_files": len(allowed_files), "prompt_allowed_files": len(prompt_allowed_files), "common_cause": common_cause_analysis.get("primary_common_cause")})
            result = CodexCliProvider(root, timeout_seconds=codex_timeout).run(prompt)
            codex_attempts.append(_summarize_codex_attempt("primary", result))
            ai = {"used": True, "provider": "codex", "ok": result.ok, "message": (result.stdout if result.ok else result.stderr)[-16000:], "timeout_seconds": codex_timeout, "prompt_scope_note": prompt_scope_note, "codex_attempts": codex_attempts}
        except Exception as exc:
            ai = {"used": True, "provider": "codex", "ok": False, "message": f"Codex self-healing failed safely: {type(exc).__name__}: {exc}"}
        if not apply_patch and not ai.get("ok"):
            ai["fallback_plan"] = deterministic_fix_plan
            ai["ok"] = True
            ai["message"] = (str(ai.get("message", "")) + "\n\nFallback deterministic fix plan created because Codex proposal could not run. No files changed.")[-16000:]
    elif provider == "ollama":
        prompt = f"Return JSON patch guidance only. Do not modify files. Failed specs: {rca.get('failed_specs')}. Allowed files: {allowed_files}. Failure: {failure_text[-8000:]}"
        result = OllamaProvider(model=model).chat(prompt)
        ai = {"used": True, "provider": "ollama", "ok": result.ok, "message": (result.text if result.ok else result.error)[-12000:]}
    elif provider in {"openai", "deepseek", "perplexity"}:
        prompt = f"""Create an enterprise Playwright self-healing patch proposal. Do not claim that files were changed.
Provider: {provider}
Note: Perplexity is treated as an OpenAI-compatible reasoning provider for web-grounded RCA/fix proposal guidance; direct writes still require Codex/manual approval.
Failed specs: {rca.get('failed_specs')}
Allowed files: {allowed_files}
RCA summary: {json.dumps({k: rca.get(k) for k in ['signals','recommended_fix_plan','robust_multi_signal_rca']}, ensure_ascii=False)[:6000]}
Failure evidence: {failure_text[-9000:]}
Return: likely root cause, exact files to modify, minimal code-level approach, and validation command."""
        result = OpenAICompatibleProvider(provider=provider, model=model).chat(prompt)
        ai = {"used": True, "provider": provider, "ok": result.ok if not apply_patch else False, "message": (result.text if result.ok else result.error)[-14000:], "api_provider_note": "OpenAI/DeepSeek/Perplexity are used for RCA/fix proposal guidance in this build. Direct file writes are still applied through Codex CLI or manual human-approved patching to preserve local workspace auditability."}
        if apply_patch:
            ai["fallback_plan"] = deterministic_fix_plan
    else:
        ai = {
            "used": False,
            "provider": provider,
            "ok": not apply_patch,
            "message": "Deterministic plan only. No files can be changed unless Codex CLI is selected for direct file patching, or an API provider is used for proposal guidance and then applied through the approved patch workflow.",
            "fallback_plan": deterministic_fix_plan,
        }

    patch_diff = {"changed_files": [], "combined_diff": "", "skipped": True}
    patch_confidence_review = {"skipped": True, "message": "Proposal mode or no patch application."}
    policy_validation = {"skipped": True, "message": "Proposal mode or no patch application."}
    confidence_restore = {"skipped": True}

    # Human approval means AstraHeal may attempt a bounded deterministic repair if
    # Codex is connected but the CLI process times out.  A Codex timeout is not an
    # authentication problem: it usually means the CLI spent too long reasoning over
    # repo context on a slow VM/VDI or restricted network.  Do not leave the user with
    # a generic login/human-review message in that case.
    if apply_patch and provider == "codex" and not ai.get("ok") and _approved_apply_mode(policy_mode, approval_decision):
        if _codex_attempt_timed_out(ai, codex_attempts):
            log_event(
                "existing_framework_self_healing",
                "Codex patch attempt timed out; running bounded deterministic locator/actionability fallback instead of requesting another human approval.",
                status="running",
                progress=68,
                details={"codex_attempts": codex_attempts, "failure_kind": deterministic_fix_plan.get("primary_failure_kind")},
            )
            deterministic_fallback_patch = _try_deterministic_self_heal_patch(root, rca, failure_text, allowed_files)
            patch_diff = _patch_changed_files(root, backup, allowed_files)
            if patch_diff.get("changed_files"):
                ai["ok"] = True
                ai["codex_timeout_recovered_by_deterministic_fallback"] = True
                ai["message"] = (
                    str(ai.get("message", ""))
                    + "\n\nCodex CLI was connected but timed out before producing a patch. "
                    + "AstraHeal applied a bounded deterministic locator/actionability fallback under the same human approval, backup, policy validation, and rollback controls. "
                    + (deterministic_fallback_patch.get("message") or "")
                )[-16000:]
            else:
                ai["message"] = (
                    str(ai.get("message", ""))
                    + "\n\nCodex CLI was connected but timed out. AstraHeal checked deterministic fallback, but no safe known locator/actionability helper pattern matched the approved files. "
                    + "This is not a fresh-login issue. Reduce patch scope, grant the exact pageObject/helper files, or raise ASTRAHEAL_CODEX_PATCH_TIMEOUT_SECONDS for very large repos."
                )[-16000:]

    if apply_patch and provider == "codex" and ai.get("ok"):
        patch_diff = _patch_changed_files(root, backup, allowed_files)
        if not patch_diff.get("changed_files"):
            positive_runtime_approval = approval_decision in {"approve", "approved", "approve_with_guidance", "approve_with_backup_and_validate"}
            if positive_runtime_approval:
                try:
                    log_event("existing_framework_self_healing", "Codex returned without a diff; running focused second patch attempt before reporting no-change.", status="running", progress=62, details={"allowed_files": len(allowed_files), "prompt_allowed_files": len(prompt_allowed_files)})
                    retry_prompt = _build_focused_codex_retry_prompt(root, rca, failure_text, allowed_files, prompt_allowed_files, excerpts, deterministic_fix_plan, runtime_human_approval, policy_mode)
                    retry_result = CodexCliProvider(root, timeout_seconds=codex_timeout if 'codex_timeout' in locals() else 300).run(retry_prompt)
                    codex_attempts.append(_summarize_codex_attempt("focused_retry_after_no_diff", retry_result))
                    ai["codex_attempts"] = codex_attempts
                    ai["focused_retry_ok"] = bool(retry_result.ok)
                    ai["message"] = (str(ai.get("message", "")) + "\n\nFocused retry output:\n" + (retry_result.stdout if retry_result.ok else retry_result.stderr))[-16000:]
                    patch_diff = _patch_changed_files(root, backup, allowed_files)
                except Exception as exc:
                    codex_attempts.append({"attempt": "focused_retry_after_no_diff", "ok": False, "error": f"{type(exc).__name__}: {exc}"})
                    ai["codex_attempts"] = codex_attempts
                    ai["message"] = (str(ai.get("message", "")) + f"\n\nFocused retry failed safely: {type(exc).__name__}: {exc}")[-16000:]
            if not patch_diff.get("changed_files") and positive_runtime_approval and (policy_mode or "approved_with_backup").strip().lower() in {"approved_with_backup", "local_approved", "vm_vdi_approved", "apply_and_validate"}:
                log_event("existing_framework_self_healing", "Codex still produced no diff; checking deterministic locator/actionability fallback patch.", status="running", progress=70, details={"failure_kind": deterministic_fix_plan.get("primary_failure_kind")})
                deterministic_fallback_patch = _try_deterministic_self_heal_patch(root, rca, failure_text, allowed_files)
                if deterministic_fallback_patch.get("changed_files"):
                    ai["ok"] = True
                    ai["deterministic_fallback_applied"] = True
                    ai["message"] = (str(ai.get("message", "")) + "\n\n" + deterministic_fallback_patch.get("message", "Deterministic fallback patch applied."))[-16000:]
                    patch_diff = _patch_changed_files(root, backup, allowed_files)
            if not patch_diff.get("changed_files"):
                ai["ok"] = False
                ai["message"] = (str(ai.get("message", "")) + "\n\n" + _no_change_self_heal_message(ai, codex_apply_diagnostics, codex_attempts, deterministic_fallback_patch, provider))[-16000:]
                patch_confidence_review = {"approve_auto_apply": False, "human_approval_required": True, "message": "No files changed after primary Codex attempt, focused retry, and deterministic fallback check.", "codex_attempts": codex_attempts, "codex_apply_diagnostics": codex_apply_diagnostics, "deterministic_fallback_patch": deterministic_fallback_patch}
                policy_validation = {"ok": False, "human_approval_required": True, "message": "No patch diff detected after approved apply pipeline.", "codex_apply_diagnostics": codex_apply_diagnostics}
            else:
                patch_confidence_review = review_patch_confidence(root, provider, model, rca, patch_diff)
                policy_validation = validate_patch_diff(patch_diff, scoped_allowed_files=allowed_files, policy=policy)
                policy_validation["apply_mode"] = policy_mode
                policy_validation["effective_policy"] = {"version": policy.get("version"), "allowedPaths": policy.get("allowedPaths"), "blockedPatterns": policy.get("blockedPatterns"), "allowForceClick": policy.get("allowForceClick"), "allowSpecLocatorAddition": policy.get("allowSpecLocatorAddition"), "allowAssertionChange": policy.get("allowAssertionChange")}
                rollback_policy_mode = "apply_and_validate" if approval_decision in {"approve", "approved", "approve_with_guidance", "approve_with_backup_and_validate"} else policy_mode
                severe_policy_violations = _severe_policy_violations(policy_validation, rollback_policy_mode)
                patch_confidence_review["policy_validation"] = policy_validation
                patch_confidence_review["severe_policy_violations"] = severe_policy_violations
                patch_confidence_review["codex_attempts"] = codex_attempts
                patch_confidence_review["codex_apply_diagnostics"] = codex_apply_diagnostics
                patch_confidence_review["deterministic_fallback_patch"] = deterministic_fallback_patch
                if severe_policy_violations:
                    confidence_restore = restore_backup(root, backup.get("backup_root", ""), patch_diff.get("changed_files") or allowed_files)
                    ai["ok"] = False
                    ai["message"] = (str(ai.get("message", "")) + "\n\nPatch was rolled back because severe blocked patterns or out-of-scope files were detected. Use human approval fields to grant safe files, then run Fix again.")[-16000:]
                else:
                    ai["ok"] = True
                    if patch_confidence_review.get("human_approval_required") or policy_validation.get("human_approval_required"):
                        ai["message"] = (str(ai.get("message", "")) + "\n\nPatch was kept for user validation. Confidence/policy review raised warnings, but no severe rollback condition was detected. Review changed_files, run failed tests again, or use rollback if needed.")[-16000:]
        else:
            patch_confidence_review = review_patch_confidence(root, provider, model, rca, patch_diff)
            policy_validation = validate_patch_diff(patch_diff, scoped_allowed_files=allowed_files, policy=policy)
            policy_validation["apply_mode"] = policy_mode
            policy_validation["effective_policy"] = {"version": policy.get("version"), "allowedPaths": policy.get("allowedPaths"), "blockedPatterns": policy.get("blockedPatterns"), "allowForceClick": policy.get("allowForceClick"), "allowSpecLocatorAddition": policy.get("allowSpecLocatorAddition"), "allowAssertionChange": policy.get("allowAssertionChange")}
            rollback_policy_mode = "apply_and_validate" if approval_decision in {"approve", "approved", "approve_with_guidance", "approve_with_backup_and_validate"} else policy_mode
            severe_policy_violations = _severe_policy_violations(policy_validation, rollback_policy_mode)
            patch_confidence_review["policy_validation"] = policy_validation
            patch_confidence_review["severe_policy_violations"] = severe_policy_violations
            # Enterprise behavior changed in this build: low confidence or
            # review warnings do NOT automatically undo a real patch.  The
            # patch stays in the framework with backup/rollback available, and
            # the user validates by running failed tests again.  Only severe,
            # deterministic policy violations are auto-rolled back.
            if severe_policy_violations:
                confidence_restore = restore_backup(root, backup.get("backup_root", ""), patch_diff.get("changed_files") or allowed_files)
                ai["ok"] = False
                ai["message"] = (str(ai.get("message", "")) + "\n\nPatch was rolled back because severe blocked patterns or out-of-scope files were detected. Use human approval fields to grant safe files, then run Fix again.")[-16000:]
            else:
                ai["ok"] = True
                if patch_confidence_review.get("human_approval_required") or policy_validation.get("human_approval_required"):
                    ai["message"] = (str(ai.get("message", "")) + "\n\nPatch was kept for user validation. Confidence/policy review raised warnings, but no severe rollback condition was detected. Review changed_files, run failed tests again, or use rollback if needed.")[-16000:]

    validation = _validate_existing_after_patch(root) if apply_patch and provider == "codex" and ai.get("ok") and patch_diff.get("changed_files") else {"ok": True, "skipped": True, "message": "No active patch validation executed because this is proposal mode, no-op, or destructive rollback occurred."}
    accepted_for_feedback = bool(apply_patch and provider == "codex" and ai.get("ok") and patch_diff.get("changed_files") and not _severe_policy_violations(policy_validation or {}, policy_mode))
    feedback_store = append_feedback(root, rca, patch_confidence_review, patch_diff, accepted=accepted_for_feedback, source="user_validate_with_rollback") if apply_patch and provider == "codex" and patch_diff.get("changed_files") else {"skipped": True}

    # Always preserve the failed-only rerun scope after proposal/apply so the user
    # can validate the same failed specs.  This fixes the broken handoff where
    # Run Failed Tests Again could skip immediately after a no-op patch.
    pending = _write_existing_pending(rca)

    if apply_patch:
        severe_rollback = bool((confidence_restore or {}).get("restored_files"))
        if patch_diff.get("changed_files") and ai.get("ok") and not severe_rollback:
            if patch_confidence_review.get("human_approval_required") or policy_validation.get("human_approval_required"):
                stage = "existing_framework_self_healing_patch_applied_needs_validation"
                ok = True
                message = "AI patch was applied and kept for validation. Review changed_files and policy warnings, then click Run failed tests again. Use Rollback last AI fix if validation fails."
                human_approval_required = True
            else:
                stage = "existing_framework_self_healing_patch_applied"
                ok = True
                message = "Safe patch was applied. Now click Run failed tests again for validation."
                human_approval_required = False
        elif patch_diff.get("changed_files") and severe_rollback:
            stage = "existing_framework_self_healing_patch_rolled_back_severe_policy"
            ok = False
            message = "A patch was attempted but rolled back because destructive test-disabling patterns were detected. For normal locator/helper/spec changes, use Approved local/VM mode so the patch is kept for validation with rollback available."
            human_approval_required = True
        else:
            stage = "existing_framework_self_healing_no_files_changed_after_approved_pipeline"
            ok = False
            message = _no_change_self_heal_message(ai, codex_apply_diagnostics if 'codex_apply_diagnostics' in locals() else {}, codex_attempts if 'codex_attempts' in locals() else [], deterministic_fallback_patch if 'deterministic_fallback_patch' in locals() else {}, provider)
            human_approval_required = True
    else:
        stage = "existing_framework_self_healing_proposal_created"
        ok = bool(ai.get("ok", True))
        message = "Safe fix plan created. No files were changed. Review the plan, then use Fix failed tests safely with Codex connected or apply manually."
        human_approval_required = False

    payload = {
        "ok": ok,
        "stage": stage,
        "applied": accepted_for_feedback,
        "changed_files": patch_diff.get("changed_files") or [],
        "human_approval_required": human_approval_required,
        "framework_path": str(root),
        "policy_mode": policy_mode,
        "root_cause": rca,
        "scope": scope,
        "rag_context_for_patch": rag_context,
        "agentic_framework_memory": deep_framework_memory,
        "human_intervention_memory": human_intervention_memory,
        "runtime_human_approval": runtime_human_approval,
        "codex_apply_diagnostics": codex_apply_diagnostics if 'codex_apply_diagnostics' in locals() else {},
        "codex_attempts": codex_attempts if 'codex_attempts' in locals() else [],
        "deterministic_fallback_patch": deterministic_fallback_patch if 'deterministic_fallback_patch' in locals() else {},
        "multi_signal_gate_status": multi_signal_gate if 'multi_signal_gate' in locals() else {},
        "deterministic_fix_plan": deterministic_fix_plan,
        "auditable_rca_reasoning_checklist": auditable_checklist,
        "common_cause_analysis": common_cause_analysis,
        "common_cause_memory_report_url": "/artifacts/reports/existing-framework/common-cause-memory.html",
        "external_research_context": external_research_context,
        "external_research_report_url": "/artifacts/reports/existing-framework/external-research/external-mcp-fix-research.html",
        "prompt_scope_note": prompt_scope_note if 'prompt_scope_note' in locals() else {},
        "backup": backup,
        "patch_diff": patch_diff,
        "patch_confidence_review": patch_confidence_review,
        "policy_validation": policy_validation,
        "confidence_restore": confidence_restore,
        "feedback_store": feedback_store,
        "validation": validation,
        "ai": ai,
        "strict_rules": strict_rules,
        "failed_only_pending": pending,
        "self_healing_report_url": "/artifacts/reports/existing-framework/self-healing-report.html",
        "auditable_rca_chain_url": "/artifacts/reports/existing-framework/robust-rca/auditable-rca-chain.html",
        "selector_health_report_url": "/artifacts/reports/existing-framework/selector-health-report.html",
        "message": message,
        "next_steps": [
            "Review self-healing report and exact changed_files.",
            "If changed_files is empty, no patch was applied; connect Codex or grant safe files through human update memory.",
            "If changed_files is not empty, run Failed Tests Again to validate the patch.",
            "Use Strict Enterprise mode for shared/client-controlled branches; use Approved local/VM mode for your own local/VM workspace with backup and rollback.",
            "If validation is bad, click Rollback last AI fix or restore from the backup directory shown in this report.",
            "Open consolidated report after rerun.",
        ],
    }
    try:
        payload["failed_only_iteration_state"] = _failed_only_iteration_limit_state(root)
        payload["gui_summary"] = _gui_summary_for_self_heal_payload(payload)
    except Exception as exc:
        payload["gui_summary_warning"] = f"{type(exc).__name__}: {exc}"
    if human_approval_required:
        payload["human_intervention_request"] = create_human_intervention_request(str(root), message, source=stage)
    EXISTING_SELF_HEAL_JSON.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    _write_self_healing_html(payload)
    log_event("existing_framework_self_healing", message, status="done" if ok else "warning", progress=100, details={"applied": payload.get("applied"), "changed_files": payload.get("changed_files"), "framework_path": str(root)})
    return payload

def _validate_existing_after_patch(root: Path) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    if (root / "tsconfig.json").exists() and _playwright_bin_exists(root):
        tsc = run_command(["npx", "--no-install", "tsc", "--noEmit"], cwd=root, timeout=180)
        checks.append({"name": "tsc_no_emit", "ok": tsc.ok, "stdout": tsc.stdout[-3000:], "stderr": tsc.stderr[-3000:], "error": tsc.error})
    else:
        checks.append({"name": "tsc_no_emit", "ok": True, "skipped": True, "message": "tsconfig.json or local node_modules not available."})
    return {"ok": all(c.get("ok") for c in checks), "checks": checks}


def _write_existing_pending(rca: dict[str, Any]) -> dict[str, Any]:
    failed_cases = [x for x in ((rca.get("plain_english_failure_report") or {}).get("test_case_outcomes") or []) if str(x.get("status") or "").lower() == "failed"]
    data = {
        "active": True,
        "framework_path": rca.get("framework_path"),
        "failed_specs": rca.get("failed_specs") or [],
        "failed_test_cases": failed_cases[:300],
        "failed_test_case_count": len(failed_cases),
        "failed_only_iteration_state": _failed_only_iteration_limit_state(Path(rca.get("framework_path")).expanduser().resolve() if rca.get("framework_path") else None),
        "created_at_epoch_ms": int(time.time() * 1000),
        "message": "After existing-framework self-healing, rerun failed tests only unless the user explicitly starts a full regression.",
    }
    EXISTING_PENDING_JSON.parent.mkdir(parents=True, exist_ok=True)
    EXISTING_PENDING_JSON.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return data


def clear_existing_pending() -> None:
    try:
        EXISTING_PENDING_JSON.unlink(missing_ok=True)
    except Exception:
        pass


def execute_existing_failed_only(framework_path: str = "", project: str = "chromium", headed: bool = True, base_url: str = "", execution_mode: str = "sequential", shards: int = 1, test_command: str = "", use_mcp_assist: bool = True) -> dict[str, Any]:
    _ensure_dirs()
    log_event("existing_framework_failed_only", "Reading failed-test inventory for failed-only rerun.", status="running", progress=5)
    inventory = _best_failed_inventory_for_followup()
    if not inventory.get("ok"):
        payload = {"ok": False, "stage": "existing_framework_failed_only_blocked_no_inventory", "message": inventory.get("error") or "No failed-test inventory is available. Run all selected existing tests first.", "failed_inventory": inventory}
        (EXISTING_REPORTS_DIR / "failed-only-rerun-report.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        log_event("existing_framework_failed_only", payload["message"], status="error", progress=100, details=payload)
        return payload

    root = _resolve_framework_path(framework_path or inventory.get("framework_path", ""))
    failed_targets = _failed_rerun_targets_from_inventory(inventory, root=root)
    failed_specs = sorted(dict.fromkeys(_strip_playwright_line_selector(t) for t in failed_targets if _is_tests_folder_executable_spec(t, root=root)), key=_spec_compare_key)
    if not failed_targets:
        recovered = _read_last_execution_inventory()
        if recovered.get("ok") and (recovered.get("failed_specs") or recovered.get("failed_test_cases")):
            inventory = recovered
            failed_targets = _failed_rerun_targets_from_inventory(inventory, root=root)
            failed_specs = sorted(dict.fromkeys(_strip_playwright_line_selector(t) for t in failed_targets if _is_tests_folder_executable_spec(t, root=root)), key=_spec_compare_key)
    if not failed_targets:
        payload = {"ok": False, "skipped": True, "stage": "existing_framework_failed_only_blocked_no_failed_targets", "message": "No valid failed test targets found for rerun. Open failed-tests.json and execution-report.json; the previous run may not have captured failed test cases/specs or paths were outside the recursively proven Playwright execution scope.", "failed_inventory": inventory}
        (EXISTING_REPORTS_DIR / "failed-only-rerun-report.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        log_event("existing_framework_failed_only", payload["message"], status="error", progress=100, details=payload)
        return payload

    limit_state = _failed_only_iteration_limit_state(root)
    if limit_state.get("blocked"):
        payload = _manual_review_limit_payload(root, inventory, "existing_framework_failed_only_blocked_after_two_iterations")
        payload["failed_targets_blocked"] = failed_targets
        (EXISTING_REPORTS_DIR / "failed-only-rerun-report.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        log_event("existing_framework_failed_only", payload["message"], status="warning", progress=100, details=payload)
        return payload

    archived = _archive_existing_html("full-run-before-existing-framework-failed-only")
    exact_note = "exact failed test-case selector(s)" if any(_is_playwright_line_selector(t) for t in failed_targets) else "failed spec file target(s)"
    log_event("existing_framework_failed_only", f"Launching visible failed-only Playwright rerun for {len(failed_targets)} {exact_note}.", progress=20, status="running", details={"failed_targets": failed_targets, "failed_specs": failed_specs, "headed": headed, "framework_path": str(root)})

    # Avoid accidental full-suite reruns. Custom commands are allowed only when
    # they explicitly contain {targets}; otherwise the safe default runner is used.
    effective_test_command = test_command if (test_command and "{targets}" in test_command) else ""
    if test_command and not effective_test_command:
        log_event("existing_framework_failed_only", "Ignoring custom command for failed-only rerun because it does not contain {targets}; using safe Playwright spec-target runner.", status="warning", progress=24, details={"custom_command": test_command})

    rerun_scope_verification = {
        "verified_failed_only": True,
        "failed_target_count": len(failed_targets),
        "failed_targets": failed_targets,
        "failed_spec_count": len(failed_specs),
        "failed_specs": failed_specs,
        "source_inventory": inventory.get("source") or inventory.get("stage") or "failed-tests.json",
        "custom_command_policy": "Custom command is ignored unless it contains {targets}; safe default runner passes failed specs as explicit Playwright targets.",
        "full_suite_protection": "No empty target list is allowed for this endpoint. Only failed specs from the latest failed inventory are submitted to execute_existing_framework().",
        "max_wait_ms": _astraheal_max_wait_ms(),
    }
    result = execute_existing_framework(str(root), project=project, headed=headed, base_url=base_url, execution_mode=execution_mode, shards=shards, targets="\n".join(failed_targets), test_command=effective_test_command, use_mcp_assist=use_mcp_assist, run_role="failed_only_rerun")
    result["rerun_scope_verification"] = rerun_scope_verification
    rerun_inventory = read_existing_failed_inventory()
    baseline_inventory = _read_first_run_baseline(inventory)
    iteration = _append_failed_only_rerun_iteration(root, inventory, rerun_inventory, result, archived, failed_targets)
    latest_iteration_report = _write_failed_only_iteration_playwright_report(root, iteration, baseline_inventory)
    # Persist any report snapshot metadata added while rendering the iteration report.
    try:
        ledger_now = _read_rerun_ledger()
        for idx, item in enumerate(ledger_now.get("iterations") or []):
            if int(item.get("iteration") or -1) == int(iteration.get("iteration") or -2):
                ledger_now["iterations"][idx] = {**item, **iteration}
                break
        EXISTING_RERUN_LEDGER_JSON.write_text(json.dumps(ledger_now, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    except Exception as exc:
        result["rerun_ledger_snapshot_warning"] = f"{type(exc).__name__}: {exc}"
    consolidated = _write_existing_consolidated_report(baseline_inventory, rerun_inventory, result, archived)
    clear_existing_pending()
    payload = {
        "ok": bool(result.get("ok")),
        "stage": "existing_framework_failed_only_rerun_completed",
        "scope": "failed_specs_only",
        "rerun_scope_verification": rerun_scope_verification,
        "rerun_iteration": iteration,
        "timeout_policy": {"max_wait_ms": _astraheal_max_wait_ms(), "default_explicit_wait_cap_seconds": 30},
        "original_failed_inventory": inventory,
        "rerun_failed_inventory": rerun_inventory,
        "rerun": result,
        "archived_full_report": archived,
        "playwright_html_report_url": f"/artifacts/reports/existing-framework/{latest_iteration_report.name}",
        "existing_framework_consolidated_report_url": "/artifacts/reports/existing-framework/consolidated-report.html",
        "message": "Failed-only rerun executed the previously failed specs using the same real Playwright runner." if result.get("ok") else "Failed-only rerun executed but failures remain or startup failed. Open execution-console.log and consolidated report.",
    }
    try:
        rem = _latest_failed_only_remaining_inventory()
        remaining_lines = []
        for rec in _inventory_failed_case_records(rem, root=root)[:80]:
            remaining_lines.append(f"{rec.get('spec')} -> {rec.get('title') or '(whole spec fallback)'} still failed - reason: {_failure_reason_from_case(rec)}")
        payload["gui_summary"] = "\n".join([
            f"Failed-only rerun iteration {iteration.get('iteration')} completed.",
            f"Submitted failed target(s): {iteration.get('submitted_target_count')}",
            f"Reported passed after rerun: {iteration.get('passed_after_rerun')}",
            f"Remaining failed after rerun: {iteration.get('failed_after_rerun')}",
            "",
            "Remaining failed tests:" if remaining_lines else "No remaining failed tests found in latest rerun inventory.",
            *remaining_lines,
        ])
    except Exception as exc:
        payload["gui_summary_warning"] = f"{type(exc).__name__}: {exc}"
    (EXISTING_REPORTS_DIR / "failed-only-rerun-report.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    log_event("existing_framework_failed_only", payload["message"], status="done" if result.get("ok") else "warning", progress=100, details={"ok": result.get("ok"), "failed_specs": failed_specs})
    return payload

def _archive_existing_html(label: str) -> dict[str, Any]:
    """Best-effort archive of the previous Playwright HTML report.

    Playwright HTML report assets under ``html/data`` can be deleted or rewritten
    while a failed-only rerun is being prepared. On Windows this made
    ``shutil.copytree`` raise ``shutil.Error`` and returned HTTP 500 before the
    failed specs were rerun. Archiving must never block RCA/self-healing/rerun,
    so copy files one-by-one and skip assets that disappear mid-copy.
    """
    src = EXISTING_HTML_DIR
    if not (src / "index.html").exists():
        return {"ok": False, "reason": "No existing-framework HTML report found to archive."}
    dest = EXISTING_REPORTS_DIR / label
    skipped: list[str] = []
    copied = 0
    try:
        if dest.exists():
            shutil.rmtree(dest, ignore_errors=True)
        dest.mkdir(parents=True, exist_ok=True)
        for path in src.rglob("*"):
            rel = path.relative_to(src)
            target = dest / rel
            try:
                if path.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, target)
                copied += 1
            except FileNotFoundError:
                skipped.append(str(rel).replace("\\", "/"))
            except OSError as exc:
                rel_text = str(rel).replace("\\", "/")
                skipped.append(f"{rel_text}: {exc}")
        if not (dest / "index.html").exists():
            # Keep a small fallback report so the consolidated report has a link
            # even when the original report was volatile/corrupted.
            (dest / "index.html").write_text("<html><body><h1>Archived Playwright report unavailable</h1><p>The previous HTML report was being modified or had missing assets while the failed-only rerun started. The rerun was not blocked.</p></body></html>", encoding="utf-8")
        status = "done" if not skipped else "warning"
        log_event("existing_framework_failed_only", "Archived previous HTML report for failed-only comparison." if not skipped else "Archived previous HTML report with some missing volatile assets skipped.", status=status, progress=12, details={"copied_files": copied, "skipped_assets": skipped[:20], "skipped_count": len(skipped)})
        return {"ok": True, "target": str(dest.relative_to(GENERATED_PLAYWRIGHT_DIR)), "url": f"/artifacts/reports/existing-framework/{label}/index.html", "copied_files": copied, "skipped_assets": skipped[:50], "skipped_count": len(skipped)}
    except Exception as exc:
        # Never allow archive failure to crash failed-only rerun.
        log_event("existing_framework_failed_only", f"Previous HTML report archive skipped: {exc}", status="warning", progress=12, details={"error": str(exc)})
        return {"ok": False, "reason": "Previous HTML report archive failed but failed-only rerun was allowed to continue.", "error": str(exc)}


def _html(value: Any) -> str:
    return str(value if value is not None else "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")




def _read_json_or(path: Path, default: Any) -> Any:
    try:
        if path.exists() and path.is_file():
            return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return default
    return default


def _inventory_failed_case_records(inventory: dict[str, Any], root: Path | None = None) -> list[dict[str, Any]]:
    records = _dedupe_case_records(_inventory_test_cases(inventory or {}, root=root))
    return [r for r in records if str(r.get("status") or "").lower() in {"failed", "timedout", "interrupted"}]


def _failed_rerun_targets_from_inventory(inventory: dict[str, Any], root: Path | None = None) -> list[str]:
    """Prefer exact failed test-case selectors for rerun; fall back to spec files.

    This prevents iteration-2 validation from rerunning every test in the failed
    spec.  Example: if only 8 test cases remain failed, the rerun submits those
    8 selectors such as tests/ui/payment.spec.ts:35, not the whole spec file
    containing 42 tests.
    """
    targets: list[str] = []
    seen: set[str] = set()
    for rec in _inventory_failed_case_records(inventory or {}, root=root):
        spec = _normalize_existing_spec_path(rec.get("spec"), root=root)
        line = rec.get("line") or rec.get("testLine") or rec.get("location", {}).get("line") if isinstance(rec.get("location"), dict) else rec.get("line")
        if not spec or not _is_tests_folder_executable_spec(spec, root=root):
            continue
        selector = spec
        try:
            if line and int(line) > 0:
                selector = f"{spec}:{int(line)}"
        except Exception:
            selector = spec
        key = selector.lower()
        if key not in seen:
            targets.append(selector)
            seen.add(key)
    if targets:
        return targets
    for spec in inventory.get("failed_specs") or []:
        spec = _normalize_existing_spec_path(spec, root=root)
        if spec and _is_tests_folder_executable_spec(spec, root=root) and spec.lower() not in seen:
            targets.append(spec)
            seen.add(spec.lower())
    return targets


def _write_first_run_only_combined_placeholder(root: Path, inventory: dict[str, Any]) -> None:
    cases = _dedupe_case_records(_inventory_test_cases(inventory or {}, root=root))
    failed = [c for c in cases if _is_failed_status(c.get("status"))]
    passed = [c for c in cases if c.get("id") not in {x.get("id") for x in failed} and not _is_failed_status(c.get("status"))]
    rows = []
    for c in cases:
        st = str(c.get("status") or "unknown").lower()
        cls = "bad" if _is_failed_status(st) else "ok"
        rows.append(f"<tr><td><code>{_html(c.get('spec'))}</code></td><td>{_html(c.get('title') or '(whole spec fallback)')}</td><td class='{cls}'>{_html(st)}</td><td>{_html('RCA/fix/rerun pending' if _is_failed_status(st) else 'Not rerun by design')}</td></tr>")
    summary = {"first_run_total": len(cases), "first_run_passed": len(passed), "first_run_failed": len(failed), "rerun_iteration_count": 0, "message": "First run baseline is saved. No failed-only rerun has been executed yet."}
    (EXISTING_REPORTS_DIR / "consolidated-report.json").write_text(json.dumps({"ok": True, "type": "first_run_only_combined_placeholder", "summary": summary, "baseline_first_run_inventory": inventory}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    html = f"""<!doctype html><html><head><meta charset='utf-8'/><title>Combined Existing Framework Report</title><style>body{{font-family:Segoe UI,Arial,sans-serif;background:#f8fafc;color:#0f172a;margin:24px}}.card{{background:white;border:1px solid #dbe3ef;border-radius:14px;padding:16px;margin:14px 0}}table{{width:100%;border-collapse:collapse;background:white}}th,td{{border:1px solid #cbd5e1;padding:8px;vertical-align:top}}th{{background:#1e293b;color:white}}code{{background:#0f172a;color:#dbeafe;padding:2px 6px;border-radius:6px}}.ok{{color:#16a34a;font-weight:800}}.bad{{color:#dc2626;font-weight:800}}</style></head><body><h1>Combined First-Run + Rerun Report</h1><div class='card'><p><b>First-run total:</b> {len(cases)} &nbsp; <b>Passed:</b> <span class='ok'>{len(passed)}</span> &nbsp; <b>Failed:</b> <span class='bad'>{len(failed)}</span></p><p>No failed-only rerun iteration has been executed yet. After RCA/fix, click <b>Run failed tests again</b> or <b>Run failed tests distributed</b>; this same report will append Rerun 1 and Rerun 2 columns.</p><p><a target='_blank' href='/artifacts/reports/existing-framework/first-run-playwright-report.html'>Open first-run Playwright report</a></p></div><div class='card'><h2>First-run ledger</h2><table><thead><tr><th>Spec</th><th>Test</th><th>First run</th><th>Rerun status</th></tr></thead><tbody>{''.join(rows) or '<tr><td colspan="4">No test case inventory available.</td></tr>'}</tbody></table></div></body></html>"""
    (EXISTING_REPORTS_DIR / "consolidated-report.html").write_text(html, encoding="utf-8")
    _update_report_manifest(combined_report_url="/artifacts/reports/existing-framework/consolidated-report.html", combined_summary=summary)


def _record_first_run_baseline(root: Path, inventory: dict[str, Any], execution_report: dict[str, Any] | None = None, distributed_summary: dict[str, Any] | None = None) -> dict[str, Any]:
    baseline = {
        "ok": True,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "framework_path": str(root),
        "source_inventory": inventory,
        "execution_report": execution_report or {},
        "distributed_summary": distributed_summary or {},
        "message": "Baseline first-run inventory preserved. Later failed-only rerun iterations must compare back to this first run, not overwrite it.",
    }
    EXISTING_FIRST_RUN_BASELINE_JSON.parent.mkdir(parents=True, exist_ok=True)
    EXISTING_FIRST_RUN_BASELINE_JSON.write_text(json.dumps(baseline, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    # A new first run starts a new validation story; old rerun iterations would corrupt the next matrix.
    EXISTING_RERUN_LEDGER_JSON.write_text(json.dumps({"ok": True, "framework_path": str(root), "iterations": [], "reset_at": baseline["created_at"]}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    try:
        _write_first_run_only_combined_placeholder(root, inventory)
    except Exception as exc:
        baseline["combined_placeholder_warning"] = f"{type(exc).__name__}: {exc}"
    return baseline


def _read_first_run_baseline(fallback_inventory: dict[str, Any] | None = None) -> dict[str, Any]:
    baseline = _read_json_or(EXISTING_FIRST_RUN_BASELINE_JSON, {})
    inv = baseline.get("source_inventory") if isinstance(baseline, dict) else None
    if isinstance(inv, dict) and inv.get("ok"):
        return inv
    return fallback_inventory or {}


def _read_rerun_ledger() -> dict[str, Any]:
    ledger = _read_json_or(EXISTING_RERUN_LEDGER_JSON, {})
    if not isinstance(ledger, dict):
        ledger = {}
    ledger.setdefault("ok", True)
    ledger.setdefault("iterations", [])
    return ledger


def _is_failed_status(value: Any) -> bool:
    return str(value or "").lower() in {"failed", "timedout", "interrupted"}


def _latest_failed_only_remaining_inventory() -> dict[str, Any]:
    """Return the current remaining-failed inventory after the latest rerun iteration.

    This is the source-of-truth for iteration-2 RCA/fix/rerun.  Without this,
    the GUI can accidentally fall back to stale spec-level inventory and rerun
    the whole failed spec file, creating reports like 42/42 when only 8 exact
    failed test cases should have been submitted.
    """
    ledger = _read_rerun_ledger()
    iterations = [x for x in (ledger.get("iterations") or []) if isinstance(x, dict)]
    if not iterations:
        return {"ok": False, "error": "No failed-only rerun iterations recorded yet."}
    latest = iterations[-1]
    framework = latest.get("framework_path") or ledger.get("framework_path") or ""
    root: Path | None = None
    if framework:
        try:
            root = Path(framework).expanduser().resolve()
        except Exception:
            root = None
    inv = latest.get("rerun_inventory") or {}
    cases = _dedupe_case_records(_inventory_test_cases(inv, root=root))
    failed_cases = [r for r in cases if _is_failed_status(r.get("status"))]
    passed_cases = [r for r in cases if r.get("id") not in {x.get("id") for x in failed_cases} and not _is_failed_status(r.get("status"))]
    if cases or failed_cases:
        failed_specs = sorted({_normalize_existing_spec_path(r.get("spec"), root=root) for r in failed_cases if r.get("spec")}, key=_spec_compare_key)
        all_specs = sorted({_normalize_existing_spec_path(r.get("spec"), root=root) for r in cases if r.get("spec")}, key=_spec_compare_key)
        passed_specs = sorted({_normalize_existing_spec_path(r.get("spec"), root=root) for r in passed_cases if r.get("spec")}, key=_spec_compare_key)
        return {
            "ok": True,
            "source": f"failed-only-rerun-ledger iteration {latest.get('iteration')}",
            "framework_path": framework,
            "iteration": latest.get("iteration"),
            "ledger_iteration_count": len(iterations),
            "all_specs": all_specs,
            "passed_specs": passed_specs,
            "failed_specs": failed_specs,
            "all_test_cases": cases,
            "passed_test_cases": passed_cases,
            "failed_test_cases": failed_cases,
            "failed_tests": failed_cases,
            "test_case_count": len(cases),
            "passed_test_case_count": len(passed_cases),
            "failed_test_case_count": len(failed_cases),
            "failed_count": len(failed_specs),
            "message": "Remaining failed tests were resolved from the latest failed-only rerun iteration ledger.",
        }
    # Legacy fallback: preserve remaining failed spec files if the rerun did not
    # produce JSON case records.  This is less precise, so reports will say so.
    legacy_specs = [_normalize_existing_spec_path(s, root=root) for s in (inv.get("failed_specs") or [])]
    legacy_specs = [s for s in legacy_specs if s and _is_tests_folder_executable_spec(s, root=root)]
    return {
        "ok": bool(legacy_specs),
        "source": f"failed-only-rerun-ledger iteration {latest.get('iteration')} spec fallback",
        "framework_path": framework,
        "iteration": latest.get("iteration"),
        "ledger_iteration_count": len(iterations),
        "failed_specs": sorted(set(legacy_specs), key=_spec_compare_key),
        "failed_count": len(set(legacy_specs)),
        "all_specs": sorted(set(legacy_specs), key=_spec_compare_key),
        "passed_specs": [],
        "message": "Latest rerun did not expose exact test-case JSON. AstraHeal fell back to failed spec files; rerun scope may be wider than exact failed tests.",
    }


def _failed_only_iteration_limit_state(root: Path | None = None) -> dict[str, Any]:
    ledger = _read_rerun_ledger()
    iterations = [x for x in (ledger.get("iterations") or []) if isinstance(x, dict)]
    remaining = _latest_failed_only_remaining_inventory() if iterations else {"ok": False, "failed_test_case_count": 0, "failed_specs": []}
    remaining_tests = int(remaining.get("failed_test_case_count") or 0)
    remaining_specs = len(remaining.get("failed_specs") or [])
    blocked = len(iterations) >= 2 and (remaining_tests > 0 or remaining_specs > 0)
    return {
        "ok": True,
        "max_failed_only_fix_iterations": 2,
        "completed_failed_only_iterations": len(iterations),
        "remaining_failed_test_cases": remaining_tests,
        "remaining_failed_specs": remaining_specs,
        "blocked": blocked,
        "manual_review_required": blocked,
        "remaining_inventory": remaining,
        "message": (
            "AstraHeal has already completed 2 RCA/self-healing/rerun iterations after the original run. Remaining failures must be reviewed manually."
            if blocked else
            f"Failed-only iteration limit check passed: {len(iterations)}/2 iteration(s) used."
        ),
    }


def _manual_review_limit_payload(root: Path | None, inventory: dict[str, Any], stage: str) -> dict[str, Any]:
    limit = _failed_only_iteration_limit_state(root)
    remaining = limit.get("remaining_inventory") or inventory or {}
    cases = _dedupe_case_records(_inventory_failed_case_records(remaining, root=root))
    if not cases:
        cases = _dedupe_case_records(_inventory_failed_case_records(inventory or {}, root=root))
    lines = []
    for rec in cases[:80]:
        lines.append(f"{rec.get('spec')} -> {rec.get('title') or '(whole spec fallback)'} -> failed - reason: {_failure_reason_from_case(rec)}")
    payload = {
        "ok": False,
        "stage": stage,
        "manual_review_required": True,
        "iteration_limit": limit,
        "framework_path": str(root or ""),
        "remaining_failed_tests": cases,
        "gui_summary": "Manual review required after 2 failed-only AI fix iterations.\n" + "\n".join(lines),
        "message": limit.get("message") or "Manual review required after two failed-only AI fix iterations.",
    }
    try:
        out = EXISTING_REPORTS_DIR / "manual-review-required-after-two-iterations.html"
        rows = ''.join(f"<tr><td><code>{_html(r.get('spec'))}</code></td><td>{_html(r.get('line'))}</td><td>{_html(r.get('title') or '(whole spec fallback)')}</td><td>{_html(_failure_reason_from_case(r))}</td></tr>" for r in cases)
        out.write_text(f"""<!doctype html><html><head><meta charset='utf-8'><title>Manual Review Required</title>
<style>body{{font-family:Segoe UI,Arial,sans-serif;margin:24px;background:#f8fafc;color:#0f172a}}.card{{background:white;border:1px solid #dbe3ef;border-radius:14px;padding:16px;margin:14px 0}}table{{width:100%;border-collapse:collapse}}th,td{{border:1px solid #cbd5e1;padding:8px;vertical-align:top}}th{{background:#1e293b;color:white}}code{{background:#0f172a;color:#dbeafe;padding:2px 6px;border-radius:6px}}</style></head><body>
<h1>Manual Review Required</h1><div class='card'><p>{_html(payload['message'])}</p><p>AstraHeal executed the original run and up to two failed-only RCA/self-healing validation iterations. To avoid unsafe repeated patching, remaining failures are now for manual investigation.</p></div>
<div class='card'><h2>Remaining failed tests</h2><table><thead><tr><th>Spec</th><th>Line</th><th>Test</th><th>Reason</th></tr></thead><tbody>{rows or '<tr><td colspan="4">No case-level remaining failure records found.</td></tr>'}</tbody></table></div></body></html>""", encoding='utf-8')
        payload["manual_review_report_url"] = "/artifacts/reports/existing-framework/manual-review-required-after-two-iterations.html"
    except Exception as exc:
        payload["manual_review_report_warning"] = f"{type(exc).__name__}: {exc}"
    return payload


def _failed_case_gui_lines_from_rca(rca: dict[str, Any], *, include_passed: bool = True, limit: int = 120) -> list[str]:
    report = (rca.get("plain_english_failure_report") or {}) if isinstance(rca, dict) else {}
    outcomes = [x for x in (report.get("test_case_outcomes") or []) if isinstance(x, dict)]
    lines: list[str] = []
    for rec in outcomes[:limit]:
        status = str(rec.get("status") or "unknown").lower()
        if status == "passed":
            if include_passed:
                lines.append(f"{rec.get('spec')} -> {rec.get('test') or '(whole spec fallback)'} passed")
        elif status == "failed":
            lines.append(f"{rec.get('spec')} -> {rec.get('test') or '(whole spec fallback)'} failed - reason: {rec.get('plain_english_reason') or 'see Playwright report'}")
        else:
            lines.append(f"{rec.get('spec')} -> {rec.get('test') or '(whole spec fallback)'} {status}")
    return lines


def _gui_summary_for_rca_payload(payload: dict[str, Any]) -> str:
    lines = _failed_case_gui_lines_from_rca(payload, include_passed=True, limit=160)
    if not lines:
        failed = payload.get("failed_specs") or []
        lines = [f"{s} -> failed - reason: see native Playwright report/trace" for s in failed]
    header = [
        "Explain failed tests - test-level RCA",
        f"Failed spec count: {len(payload.get('failed_specs') or [])}",
        f"Plain English report: {payload.get('plain_english_failure_report_url') or '/artifacts/reports/existing-framework/plain-english-failure-report.html'}",
    ]
    limit = _failed_only_iteration_limit_state(Path(payload.get('framework_path')).expanduser().resolve() if payload.get('framework_path') else None)
    if limit.get("completed_failed_only_iterations"):
        header.append(f"Failed-only fix iteration: {limit.get('completed_failed_only_iterations')}/2 completed")
    if limit.get("blocked"):
        header.append("Manual review required: 2 failed-only fix iterations are already completed.")
    return "\n".join(header + [""] + lines[:160])


def _gui_summary_for_self_heal_payload(payload: dict[str, Any]) -> str:
    rca = payload.get("root_cause") or {}
    failed_lines = _failed_case_gui_lines_from_rca(rca, include_passed=False, limit=120)
    plan = (payload.get("deterministic_fix_plan") or {}).get("plan") or []
    changed = payload.get("changed_files") or (payload.get("patch_diff") or {}).get("changed_files") or []
    gate = payload.get("multi_signal_gate_status") or rca.get("multi_signal_gate_status") or {}
    out = [
        "Safe fix / self-healing details",
        f"Stage: {payload.get('stage')}",
        f"Message: {payload.get('message')}",
        f"Human approval / RCA gate: {gate.get('user_message', 'not recorded')}",
        f"Patch allowed after approval: {gate.get('final_patch_allowed', 'not applicable')}",
        "",
        "Failed tests in scope:",
        *(failed_lines or ["No test-level failed case evidence found. Open native Playwright report/trace."]),
        "",
        "Safe fix plan:",
    ]
    if plan:
        out.extend(f"{i}. {step}" for i, step in enumerate(plan[:40], 1))
    else:
        out.append("No deterministic plan generated.")
    out.extend(["", "Files changed / expected patch location:"])
    if changed:
        out.extend(f"- {x}" for x in changed[:80])
    else:
        allowed = (payload.get("scope") or {}).get("allowed_files") or []
        out.extend(f"- {x}" for x in allowed[:40]) if allowed else out.append("No files changed yet. Proposal/approval step only or patch provider not connected.")
    diag = payload.get("codex_apply_diagnostics") or {}
    attempts = payload.get("codex_attempts") or []
    fallback = payload.get("deterministic_fallback_patch") or {}
    if diag or attempts or fallback.get("attempted"):
        out.extend(["", "Codex / patch apply diagnostics:"])
        if diag:
            out.append(f"- Codex found by backend: {diag.get('codex_found')}")
            out.append(f"- Codex login/status OK: {diag.get('login_ok')}")
            out.append(f"- Diagnostic: {diag.get('message')}")
        if attempts:
            for a in attempts[:4]:
                out.append(f"- Attempt {a.get('attempt')}: ok={a.get('ok')} exit_code={a.get('exit_code')}")
        if fallback.get("attempted"):
            out.append(f"- Deterministic fallback: {fallback.get('message')}")
        if not changed:
            out.append("- Meaning: approval was received, but no framework diff was produced. This is now diagnosed separately from human approval; failed-only rerun scope is preserved.")
    return "\n".join(out)


def _append_failed_only_rerun_iteration(root: Path, source_inventory: dict[str, Any], rerun_inventory: dict[str, Any], execution: dict[str, Any], archived: dict[str, Any], submitted_targets: list[str]) -> dict[str, Any]:
    ledger = _read_rerun_ledger()
    iterations = [x for x in (ledger.get("iterations") or []) if isinstance(x, dict)]
    iteration_no = len(iterations) + 1
    failed_after = _inventory_failed_case_records(rerun_inventory, root=root)
    iteration = {
        "iteration": iteration_no,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "framework_path": str(root),
        "submitted_target_count": len(submitted_targets),
        "submitted_targets": submitted_targets,
        "source_failed_count_before_rerun": len(_inventory_failed_case_records(source_inventory, root=root)) or int(source_inventory.get("failed_test_case_count") or source_inventory.get("failed_count") or 0),
        "passed_after_rerun": int(rerun_inventory.get("passed_test_case_count") or 0),
        "failed_after_rerun": len(failed_after) or int(rerun_inventory.get("failed_test_case_count") or rerun_inventory.get("failed_count") or 0),
        "rerun_inventory": rerun_inventory,
        "execution": execution,
        "archived_previous_html_report": archived,
        "native_html_report_url": "/artifacts/reports/existing-framework/html/index.html",
    }
    iterations.append(iteration)
    new_ledger = {"ok": True, "framework_path": str(root), "updated_at": iteration["created_at"], "iterations": iterations}
    EXISTING_RERUN_LEDGER_JSON.write_text(json.dumps(new_ledger, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return iteration


def _case_line_key_from_record(rec: dict[str, Any]) -> tuple[str, str]:
    spec = _spec_compare_key(rec.get("spec"))
    line = str(rec.get("line") or "").strip()
    return spec, line


def _write_latest_playwright_router(title: str, body_html: str, links: list[tuple[str, str]] | None = None) -> None:
    links_html = "".join(f"<li><a target='_blank' href='{_html(url)}'>{_html(text)}</a></li>" for text, url in (links or []))
    html = f"""<!doctype html><html><head><meta charset='utf-8'/><title>{_html(title)}</title>
<style>body{{font-family:Segoe UI,Arial,sans-serif;background:#f8fafc;color:#0f172a;margin:24px}}.card{{background:white;border:1px solid #dbe3ef;border-radius:14px;padding:16px;margin:14px 0}}a{{font-weight:700}}code{{background:#0f172a;color:#dbeafe;padding:3px 6px;border-radius:6px}}pre{{white-space:pre-wrap;background:#0f172a;color:#dbeafe;border-radius:10px;padding:12px;max-height:460px;overflow:auto}}</style></head><body>
<h1>{_html(title)}</h1><div class='card'>{body_html}</div><div class='card'><h2>Report links</h2><ul>{links_html or '<li>No links available.</li>'}</ul></div></body></html>"""
    EXISTING_LATEST_PLAYWRIGHT_ROUTER_HTML.write_text(html, encoding="utf-8")
    _update_report_manifest(latest_playwright_report_url="/artifacts/reports/existing-framework/latest-playwright-report.html", latest_playwright_title=title, latest_playwright_links=[{"label": t, "url": u} for t, u in (links or [])])


def _report_manifest_path() -> Path:
    return EXISTING_REPORTS_DIR / "report-link-manifest.json"


def _read_report_manifest() -> dict[str, Any]:
    try:
        if _report_manifest_path().exists():
            data = json.loads(_report_manifest_path().read_text(encoding="utf-8", errors="replace"))
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {"ok": True, "updated_at": "", "reports": {}}


def _update_report_manifest(**entries: Any) -> dict[str, Any]:
    manifest = _read_report_manifest()
    reports = manifest.setdefault("reports", {})
    for key, value in entries.items():
        if value is not None:
            reports[key] = value
    manifest["ok"] = True
    manifest["updated_at"] = datetime.now().isoformat(timespec="seconds")
    manifest["message"] = "AstraHeal Logs & Reports links are stage-aware. Open Playwright Report uses latest-playwright-report.html; Open combined report uses consolidated-report.html only."
    _report_manifest_path().write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return manifest


def _snapshot_html_report(snapshot_name: str) -> dict[str, Any]:
    """Copy current central native HTML report to a stable per-stage folder.

    This prevents a later failed-only rerun from overwriting an older iteration's
    native Playwright HTML.  If no native HTML is available, the caller still
    gets a useful diagnostic instead of a stale link.
    """
    src = EXISTING_HTML_DIR
    dst = EXISTING_REPORTS_DIR / snapshot_name
    try:
        if dst.exists():
            shutil.rmtree(dst, ignore_errors=True)
        if src.exists() and (src / "index.html").exists():
            shutil.copytree(src, dst, dirs_exist_ok=True)
            return {"ok": True, "path": str(dst / "index.html"), "url": f"/artifacts/reports/existing-framework/{snapshot_name}/index.html"}
        dst.mkdir(parents=True, exist_ok=True)
        (dst / "index.html").write_text("""<!doctype html><html><head><meta charset='utf-8'/><title>No native Playwright HTML snapshot</title></head><body><h1>No native Playwright HTML snapshot was available for this stage</h1><p>Open the stage index report and execution JSON for details.</p></body></html>""", encoding="utf-8")
        return {"ok": False, "path": str(dst / "index.html"), "url": f"/artifacts/reports/existing-framework/{snapshot_name}/index.html", "message": "Native Playwright HTML was not available for snapshot."}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}", "url": f"/artifacts/reports/existing-framework/{snapshot_name}/index.html"}


def _write_sequential_first_run_playwright_report(root: Path, inventory: dict[str, Any], execution: dict[str, Any]) -> Path:
    snapshot = _snapshot_html_report("first-run-native-html")
    cases = _dedupe_case_records(_inventory_test_cases(inventory or {}, root=root))
    failed = [c for c in cases if _is_failed_status(c.get("status"))]
    passed = [c for c in cases if c.get("id") not in {x.get("id") for x in failed} and not _is_failed_status(c.get("status"))]
    rows = []
    for c in cases:
        st = str(c.get("status") or "unknown").lower()
        cls = "bad" if _is_failed_status(st) else "ok"
        rows.append(f"<tr><td><code>{_html(c.get('spec'))}</code></td><td>{_html(c.get('line') or '')}</td><td>{_html(c.get('title') or '(whole spec fallback)')}</td><td class='{cls}'>{_html(st)}</td><td>{_html(_failure_reason_from_case(c) if _is_failed_status(st) else 'passed')}</td></tr>")
    html = f"""<!doctype html><html><head><meta charset='utf-8'/><title>Exact First Run Playwright Report</title>
<style>body{{font-family:Segoe UI,Arial,sans-serif;background:#f8fafc;color:#0f172a;margin:24px}}.card{{background:white;border:1px solid #dbe3ef;border-radius:14px;padding:16px;margin:14px 0}}table{{width:100%;border-collapse:collapse;background:white}}th,td{{border:1px solid #cbd5e1;padding:8px;vertical-align:top}}th{{background:#1e293b;color:white}}code{{background:#0f172a;color:#dbeafe;padding:2px 6px;border-radius:6px}}.ok{{color:#16a34a;font-weight:800}}.bad{{color:#dc2626;font-weight:800}}pre{{white-space:pre-wrap;background:#0f172a;color:#dbeafe;padding:10px;border-radius:8px;max-height:360px;overflow:auto}}</style></head><body>
<h1>Exact First Run Playwright Report</h1><div class='card'><p><b>Playwright reported/runnable tests:</b> {len(cases)} &nbsp; <b>Passed:</b> <span class='ok'>{len(passed)}</span> &nbsp; <b>Failed:</b> <span class='bad'>{len(failed)}</span></p><p><a target='_blank' href='{_html(snapshot.get('url'))}'>Open native Playwright HTML snapshot for first run</a></p></div>
<div class='card'><h2>Test-by-test first-run ledger</h2><table><thead><tr><th>Spec</th><th>Line</th><th>Test title</th><th>Status</th><th>Plain English reason</th></tr></thead><tbody>{''.join(rows) or '<tr><td colspan="5">No test-case records were available. Open native Playwright HTML.</td></tr>'}</tbody></table></div>
<div class='card'><h2>Raw inventory</h2><pre>{_html(json.dumps(inventory, indent=2, ensure_ascii=False)[:80000])}</pre></div></body></html>"""
    out = EXISTING_REPORTS_DIR / "first-run-playwright-report.html"
    out.write_text(html, encoding="utf-8")
    _update_report_manifest(first_run_report_url="/artifacts/reports/existing-framework/first-run-playwright-report.html", first_run_native_html_url=snapshot.get("url"), first_run_summary={"reported": len(cases), "passed": len(passed), "failed": len(failed)})
    return out


def _failure_reason_from_case(rec: dict[str, Any]) -> str:
    text = json.dumps(rec.get("errors") or rec, ensure_ascii=False)[-6000:]
    low = text.lower()
    if _is_module_resolution_failure(text):
        missing = _extract_missing_module_name(text)
        return f"Playwright/Node could not resolve module import or TypeScript path alias{(' ' + missing) if missing else ''}; the test did not reach the browser/DOM step"
    if "element(s) not found" in low or "waiting for locator" in low or "to be visible" in low and "not found" in low:
        return "locator is missing, hidden, or not available in DOM for this page state"
    if "not attached to the dom" in low or "detached" in low:
        return "locator became detached from DOM; re-query element after page settles and verify with MCP/codegen"
    if "intercepts pointer events" in low or "receives pointer events" in low:
        return "element is blocked by overlay/modal/cookie/location popup or another component"
    if "timeout" in low or "test timeout" in low:
        return "test timed out; likely slow AUT, navigation/state wait, or blocked locator/action"
    if "tohaveurl" in low or "url did not match" in low or "navigation" in low and "expected" in low:
        return "navigation or redirect did not reach the expected URL/page state"
    if any(x in low for x in ["expect(", "expected:", "received:", "tohavetext", "tocontaintext", "toequal"]):
        return "actual application value or state did not match the expected assertion; confirm requirement and test data before changing the test"
    if "payment type not found" in low:
        return "expected payment option/test data is not available in the current environment"
    return "failure requires trace/screenshot review; see native Playwright shard report"

def _write_failed_only_iteration_playwright_report(root: Path, iteration: dict[str, Any], baseline_inventory: dict[str, Any]) -> Path:
    inv = iteration.get("rerun_inventory") or {}
    iteration_no = int(iteration.get("iteration") or 1)
    native_snapshot = _snapshot_html_report(f"failed-only-rerun-iteration-{iteration_no}-html")
    iteration["native_html_snapshot"] = native_snapshot
    cases = _dedupe_case_records(_inventory_test_cases(inv, root=root))
    failed = [c for c in cases if str(c.get("status") or "").lower() in {"failed", "timedout", "interrupted"}]
    passed = [c for c in cases if c.get("id") not in {x.get("id") for x in failed} and str(c.get("status") or "").lower() not in {"failed", "timedout", "interrupted"}]
    rows = []
    for c in cases:
        st = str(c.get("status") or "unknown").lower()
        cls = "bad" if st in {"failed","timedout","interrupted"} else "ok"
        rows.append(f"<tr><td><code>{_html(c.get('spec'))}</code></td><td>{_html(c.get('line'))}</td><td>{_html(c.get('title') or '(whole spec fallback)')}</td><td class='{cls}'>{_html(st)}</td><td>{_html(_failure_reason_from_case(c) if cls=='bad' else 'passed')}</td></tr>")
    html = f"""<!doctype html><html><head><meta charset='utf-8'/><title>Failed-only Rerun Iteration {iteration.get('iteration')} Playwright Report Index</title>
<style>body{{font-family:Segoe UI,Arial,sans-serif;background:#f8fafc;color:#0f172a;margin:24px}}.card{{background:white;border:1px solid #dbe3ef;border-radius:14px;padding:16px;margin:14px 0}}table{{width:100%;border-collapse:collapse;background:white}}th,td{{border:1px solid #cbd5e1;padding:8px;vertical-align:top}}th{{background:#1e293b;color:white}}code{{background:#0f172a;color:#dbeafe;padding:2px 6px;border-radius:6px}}.ok{{color:#16a34a;font-weight:800}}.bad{{color:#dc2626;font-weight:800}}pre{{white-space:pre-wrap;background:#0f172a;color:#dbeafe;padding:10px;border-radius:8px;max-height:360px;overflow:auto}}</style></head><body>
<h1>Failed-only Rerun Iteration {iteration.get('iteration')} Playwright Report Index</h1>
<div class='card'><p><b>Submitted failed target count:</b> {iteration.get('submitted_target_count')} &nbsp; <b>Reported tests:</b> {len(cases)} &nbsp; <b>Passed:</b> <span class='ok'>{len(passed)}</span> &nbsp; <b>Still failed:</b> <span class='bad'>{len(failed)}</span></p><p>This is the exact failed-only rerun iteration report. It should contain only the failed targets submitted for this iteration, not the original full suite.</p></div>
<div class='card'><h2>Native Playwright HTML</h2><p><a target='_blank' href='{_html(native_snapshot.get('url'))}'>Open native Playwright HTML snapshot generated by this failed-only rerun</a></p><p class='small'>Snapshot is preserved per iteration, so rerun-2 does not overwrite rerun-1 report evidence.</p></div>
<div class='card'><h2>Submitted targets</h2><pre>{_html(json.dumps(iteration.get('submitted_targets') or [], indent=2, ensure_ascii=False))}</pre></div>
<div class='card'><h2>Rerun test-by-test ledger</h2><table><thead><tr><th>Spec</th><th>Line</th><th>Test</th><th>Status</th><th>Reason</th></tr></thead><tbody>{''.join(rows) or '<tr><td colspan="5">No rerun case records found. Open native Playwright HTML.</td></tr>'}</tbody></table></div>
</body></html>"""
    out = EXISTING_REPORTS_DIR / f"failed-only-rerun-iteration-{int(iteration.get('iteration') or 1)}-playwright-report.html"
    out.write_text(html, encoding="utf-8")
    EXISTING_FAILED_ONLY_LATEST_REPORT_HTML.write_text(html, encoding="utf-8")
    _write_latest_playwright_router(
        f"Latest Playwright report: failed-only rerun iteration {iteration.get('iteration')}",
        f"<p>Latest execution stage is failed-only rerun iteration <b>{iteration.get('iteration')}</b>.</p><p>Submitted <b>{iteration.get('submitted_target_count')}</b> failed target(s); Playwright reported <b>{len(cases)}</b> test case(s), with <b>{len(passed)}</b> passed and <b>{len(failed)}</b> still failed.</p>",
        [("Open failed-only iteration report", f"/artifacts/reports/existing-framework/{out.name}"), ("Open native Playwright HTML snapshot for this rerun", native_snapshot.get('url') or "/artifacts/reports/existing-framework/html/index.html"), ("Open combined first-run + all reruns report", "/artifacts/reports/existing-framework/consolidated-report.html")]
    )
    _update_report_manifest(latest_failed_only_report_url=f"/artifacts/reports/existing-framework/{out.name}", latest_failed_only_native_html_url=native_snapshot.get('url'), latest_failed_only_iteration=iteration.get('iteration'), latest_failed_only_summary={"submitted": iteration.get('submitted_target_count'), "reported": len(cases), "passed": len(passed), "failed": len(failed)})
    return out

def _write_existing_consolidated_report(original: dict[str, Any], rerun: dict[str, Any], execution: dict[str, Any], archive: dict[str, Any]) -> Path:
    """Create a durable first-run + multi-iteration failed-only report.

    The baseline first run must never be overwritten by failed-only reruns.  Each
    failed-only click appends a separate iteration so a sequence like 120 -> 12
    failed -> 8 remaining -> 0 remaining is reported accurately instead of
    replacing the story with the latest rerun's 42 reported spec-level cases.
    """
    framework = original.get("framework_path") or (execution.get("framework_path") if isinstance(execution, dict) else "") or ""
    root = Path(framework).expanduser().resolve() if framework else None
    baseline_inventory = _read_first_run_baseline(original)
    original_cases = _dedupe_case_records(_inventory_test_cases(baseline_inventory or original, root=root))
    original_failed = [r for r in original_cases if str(r.get("status") or "").lower() in {"failed", "timedout", "interrupted"}]
    original_passed = [r for r in original_cases if r.get("id") not in {x.get("id") for x in original_failed} and str(r.get("status") or "").lower() not in {"failed", "timedout", "interrupted"}]
    ledger = _read_rerun_ledger()
    iterations = [x for x in (ledger.get("iterations") or []) if isinstance(x, dict)]
    if not iterations and rerun:
        iterations = [{"iteration": 1, "rerun_inventory": rerun, "execution": execution, "archived_previous_html_report": archive, "submitted_targets": execution.get("rerun_scope_verification", {}).get("failed_targets") or execution.get("rerun_scope_verification", {}).get("failed_specs") or [], "submitted_target_count": len(execution.get("rerun_scope_verification", {}).get("failed_targets") or execution.get("rerun_scope_verification", {}).get("failed_specs") or [])}]

    def failed_status(rec: dict[str, Any]) -> bool:
        return str(rec.get("status") or "").lower() in {"failed", "timedout", "interrupted"}

    def iteration_cases(it: dict[str, Any]) -> list[dict[str, Any]]:
        return _dedupe_case_records(_inventory_test_cases(it.get("rerun_inventory") or {}, root=root))

    iter_case_lists = [iteration_cases(it) for it in iterations]
    iter_maps: list[dict[str, dict[str, Any]]] = []
    iter_line_maps: list[dict[tuple[str, str], dict[str, Any]]] = []
    iter_spec_title_maps: list[dict[tuple[str, str], dict[str, Any]]] = []
    for cases in iter_case_lists:
        by_id = {c.get("id"): c for c in cases if c.get("id")}
        by_line = {_case_line_key_from_record(c): c for c in cases if _case_line_key_from_record(c)[0] and _case_line_key_from_record(c)[1]}
        by_spec_title = {(_spec_compare_key(c.get("spec")), re.sub(r"\s+", " ", str(c.get("title") or "").strip()).lower()): c for c in cases if c.get("spec")}
        iter_maps.append(by_id)
        iter_line_maps.append(by_line)
        iter_spec_title_maps.append(by_spec_title)

    def find_in_iteration(rec: dict[str, Any], idx: int) -> dict[str, Any] | None:
        rid = rec.get("id")
        if rid and rid in iter_maps[idx]:
            return iter_maps[idx][rid]
        lk = _case_line_key_from_record(rec)
        if lk[0] and lk[1] and lk in iter_line_maps[idx]:
            return iter_line_maps[idx][lk]
        tk = (_spec_compare_key(rec.get("spec")), re.sub(r"\s+", " ", str(rec.get("title") or "").strip()).lower())
        return iter_spec_title_maps[idx].get(tk)

    header_iter = ''.join(f"<th>Rerun {int(it.get('iteration') or i+1)}</th>" for i, it in enumerate(iterations))
    rows: list[str] = []
    recovered_final = 0
    still_failing_final = 0
    final_unresolved = 0
    matched_iter_ids: list[set[str]] = [set() for _ in iterations]

    for row_no, rec in enumerate(original_cases, 1):
        first_failed = failed_status(rec)
        first_cls = "bad" if first_failed else "ok"
        first_text = "Failed in first run" if first_failed else "Passed in first run"
        cells = []
        latest_status = "failed" if first_failed else "passed"
        latest_record: dict[str, Any] | None = rec
        if first_failed:
            for idx, it in enumerate(iterations):
                rr = find_in_iteration(rec, idx)
                if rr and rr.get("id"):
                    matched_iter_ids[idx].add(rr.get("id"))
                if rr:
                    if failed_status(rr):
                        reason = _failure_reason_from_case(rr)
                        cells.append(f"<td class='bad'>Still failed<br/><span class='small'>{_html(reason)}</span></td>")
                        latest_status = "failed"
                        latest_record = rr
                    else:
                        cells.append("<td class='ok'>Passed / recovered</td>")
                        latest_status = "passed"
                        latest_record = rr
                else:
                    cells.append("<td class='warn'>Not submitted / no evidence in this iteration</td>")
            if latest_status == "passed":
                final_text = "Recovered after failed-only rerun"
                final_cls = "ok"
                recovered_final += 1
            elif iterations:
                final_text = "Still failing after latest rerun"
                final_cls = "bad"
                still_failing_final += 1
            else:
                final_text = "RCA/fix/rerun pending"
                final_cls = "warn"
                final_unresolved += 1
        else:
            cells = ["<td class='muted'>Not rerun by design</td>" for _ in iterations]
            final_text = "Passed"
            final_cls = "ok"
        line = rec.get("line") or ""
        title = rec.get("title") or "(whole spec fallback)"
        rows.append(f"<tr><td>{row_no}</td><td><code>{_html(rec.get('spec'))}</code><br/><span class='small'>line { _html(line) }</span></td><td>{_html(title)}</td><td class='{first_cls}'>{first_text}</td>{''.join(cells)}<td class='{final_cls}'>{_html(final_text)}</td></tr>")

    # Scope warnings: rerun should submit only remaining failed targets.  Show if reported cases exceed submitted target count.
    scope_rows = []
    unexpected_extra = 0
    for idx, (it, cases) in enumerate(zip(iterations, iter_case_lists), 1):
        submitted = int(it.get("submitted_target_count") or len(it.get("submitted_targets") or []))
        reported = len(cases)
        failed_after = len([c for c in cases if failed_status(c)])
        passed_after = reported - failed_after
        scope_status = "ok"
        scope_note = "Scope looks correct."
        if submitted and reported > submitted and any(_is_playwright_line_selector(t) for t in (it.get("submitted_targets") or [])):
            scope_status = "warn"
            scope_note = "Playwright reported more tests than submitted line selectors. A selector may point at a describe block/hook or Playwright config may have expanded scope. Open the iteration native report."
        scope_rows.append(f"<tr><td>{idx}</td><td>{submitted}</td><td>{reported}</td><td class='ok'>{passed_after}</td><td class='bad'>{failed_after}</td><td class='{scope_status}'>{_html(scope_note)}</td></tr>")
        for c in cases:
            if c.get("id") not in matched_iter_ids[idx-1]:
                # Extra evidence is allowed when Playwright expands a spec; count it visibly.
                if _spec_compare_key(c.get("spec")) not in {_spec_compare_key(x.get("spec")) for x in original_failed}:
                    unexpected_extra += 1

    latest_remaining = 0
    if iterations:
        latest_cases = iter_case_lists[-1]
        latest_remaining = len([c for c in latest_cases if failed_status(c)])
    else:
        latest_remaining = len(original_failed)

    summary = {
        "report_granularity": "test_case" if any(r.get("granularity") != "spec_file_fallback" for r in original_cases) else "spec_file_fallback",
        "first_run_total": len(original_cases),
        "first_run_passed": len(original_passed),
        "first_run_failed": len(original_failed),
        "rerun_iteration_count": len(iterations),
        "recovered_after_all_reruns": recovered_final,
        "still_failing_after_latest_rerun": latest_remaining if iterations else len(original_failed),
        "unexpected_extra_rerun_tests": unexpected_extra,
        "message": "Baseline first run is preserved separately from every failed-only rerun iteration.",
    }
    combined_json = {
        "ok": True,
        "type": "existing_framework_combined_first_run_and_failed_only_rerun_iterations",
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "framework_path": framework,
        "summary": summary,
        "baseline_first_run_inventory": baseline_inventory or original,
        "rerun_ledger": {**ledger, "iterations": iterations},
        "latest_failed_only_inventory": rerun,
        "latest_failed_only_execution": execution,
        "combined_html_report_url": "/artifacts/reports/existing-framework/consolidated-report.html",
        "first_run_exact_report_url": "/artifacts/reports/existing-framework/first-run-playwright-report.html",
        "latest_failed_only_report_url": "/artifacts/reports/existing-framework/failed-only-latest-playwright-report.html",
    }
    (EXISTING_REPORTS_DIR / "consolidated-report.json").write_text(json.dumps(combined_json, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    iter_links = ''.join(f"<li><a target='_blank' href='/artifacts/reports/existing-framework/failed-only-rerun-iteration-{int(it.get('iteration') or i+1)}-playwright-report.html'>Open failed-only rerun iteration {int(it.get('iteration') or i+1)} Playwright report</a></li>" for i, it in enumerate(iterations))
    html = f"""<!doctype html><html><head><meta charset='utf-8'/><title>Combined Existing Framework Report</title>
<style>body{{font-family:Segoe UI,Arial,sans-serif;margin:24px;background:#f8fafc;color:#0f172a}}.card{{background:white;border:1px solid #dbe3ef;border-radius:14px;padding:16px;margin:14px 0}}.ok{{color:#16a34a;font-weight:800}}.bad{{color:#dc2626;font-weight:800}}.warn{{color:#b45309;font-weight:800}}.muted{{color:#64748b;font-weight:700}}.small{{font-size:12px;color:#475569}}table{{border-collapse:collapse;width:100%}}td,th{{border:1px solid #e2e8f0;padding:8px;text-align:left;vertical-align:top}}th{{background:#1e293b;color:white}}code{{background:#0f172a;color:#dbeafe;padding:3px 6px;border-radius:6px}}pre{{white-space:pre-wrap;background:#0f172a;color:#dbeafe;border-radius:10px;padding:14px;max-height:500px;overflow:auto}}.metric{{display:inline-block;background:#eef2ff;border:1px solid #c7d2fe;border-radius:12px;padding:10px;margin:5px}}</style></head><body>
<h1>Combined Existing Framework Report</h1>
<div class='card'><b>Framework:</b> <code>{_html(framework)}</code><p>This report preserves the original first run and every failed-only rerun iteration. A second or third click on Run failed tests again no longer overwrites the first-run baseline.</p></div>
<div class='card'><h2>Summary</h2><span class='metric'>First-run total: <b>{summary['first_run_total']}</b></span><span class='metric'>First-run passed: <b>{summary['first_run_passed']}</b></span><span class='metric'>First-run failed: <b>{summary['first_run_failed']}</b></span><span class='metric'>Rerun iterations: <b>{summary['rerun_iteration_count']}</b></span><span class='metric'>Recovered after reruns: <b>{summary['recovered_after_all_reruns']}</b></span><span class='metric'>Still failing after latest: <b>{summary['still_failing_after_latest_rerun']}</b></span><span class='metric'>Unexpected extra rerun tests: <b>{summary['unexpected_extra_rerun_tests']}</b></span></div>
<div class='card'><h2>Report links</h2><ul><li><a target='_blank' href='/artifacts/reports/existing-framework/first-run-playwright-report.html'>Open exact first-run Playwright shard report</a></li>{iter_links}<li><a target='_blank' href='/artifacts/reports/existing-framework/failed-only-latest-playwright-report.html'>Open latest failed-only rerun Playwright report</a></li><li><a target='_blank' href='/artifacts/reports/existing-framework/consolidated-report.json'>Open combined JSON</a></li></ul></div>
<div class='card'><h2>Failed-only rerun scope audit</h2><table><thead><tr><th>Iteration</th><th>Submitted failed targets</th><th>Playwright reported tests</th><th>Passed</th><th>Failed</th><th>Scope note</th></tr></thead><tbody>{''.join(scope_rows) or '<tr><td colspan="6">No failed-only rerun has been executed yet.</td></tr>'}</tbody></table></div>
<div class='card'><h2>Complete first-run + rerun matrix</h2><table><thead><tr><th>#</th><th>Spec</th><th>Test</th><th>First run</th>{header_iter}<th>Final status</th></tr></thead><tbody>{''.join(rows) if rows else '<tr><td colspan="6">No test-case inventory available.</td></tr>'}</tbody></table></div>
<div class='card'><h2>Raw combined evidence</h2><pre>{_html(json.dumps(combined_json, indent=2, ensure_ascii=False)[:120000])}</pre></div>
</body></html>"""
    out = EXISTING_REPORTS_DIR / "consolidated-report.html"
    out.write_text(html, encoding="utf-8")
    _update_report_manifest(combined_report_url="/artifacts/reports/existing-framework/consolidated-report.html", combined_summary=summary)
    log_event("existing_framework_report", "Combined first-run + failed-only rerun iteration report generated.", status="done", progress=100, details={"summary": summary, "url": "/artifacts/reports/existing-framework/consolidated-report.html"})
    return out


def generate_existing_selector_health_report(framework_path: str = "") -> dict[str, Any]:
    root = _resolve_framework_path(framework_path) if framework_path else None
    return generate_robust_selector_health_report(root)


def install_existing_framework_robust_harness(framework_path: str) -> dict[str, Any]:
    """Install optional SmartLocator/TestTelemetry helper files into an existing Playwright TS framework.

    This is intentionally additive: it creates support files and a documentation note,
    but it does not rewrite specs automatically. Users can import the fixture gradually.
    """
    root = _resolve_framework_path(framework_path)
    support_dir = root / "qa-ai-support"
    support_dir.mkdir(parents=True, exist_ok=True)
    files: dict[str, str] = {}
    smart_locator = r"""
import type { Locator, Page } from '@playwright/test';

export type SmartLocatorCandidate =
  | { strategy: 'testId'; value: string; description?: string }
  | { strategy: 'role'; role: Parameters<Page['getByRole']>[0]; value: string; description?: string }
  | { strategy: 'label'; value: string; description?: string }
  | { strategy: 'placeholder'; value: string; description?: string }
  | { strategy: 'text'; value: string; description?: string }
  | { strategy: 'css'; value: string; description?: string }
  | { strategy: 'xpath'; value: string; description?: string };

export class SmartLocator {
  constructor(private readonly page: Page, private readonly candidates: SmartLocatorCandidate[], private readonly name = 'smart target') {}

  locator(): Locator {
    let loc = this.resolve(this.candidates[0]);
    for (const candidate of this.candidates.slice(1)) loc = loc.or(this.resolve(candidate));
    return loc.first();
  }

  async click(options: { timeout?: number } = {}): Promise<void> {
    const target = await this.firstReachable(options.timeout ?? 10_000);
    await target.click({ timeout: options.timeout ?? 10_000 }).catch(async err => {
      await this.page.locator('[role="dialog"], [class*="modal" i], [class*="overlay" i]').evaluateAll(nodes => nodes.forEach(n => (n as HTMLElement).style.pointerEvents = 'none')).catch(() => undefined);
      await target.scrollIntoViewIfNeeded().catch(() => undefined);
      await target.click({ timeout: options.timeout ?? 10_000 }).catch(() => { throw err; });
    });
  }

  async firstReachable(timeout = 10_000): Promise<Locator> {
    const deadline = Date.now() + timeout;
    for (const candidate of this.candidates) {
      const loc = this.resolve(candidate).first();
      const remaining = Math.max(500, deadline - Date.now());
      if (await loc.isVisible({ timeout: Math.min(1500, remaining) }).catch(() => false)) {
        await loc.scrollIntoViewIfNeeded().catch(() => undefined);
        return loc;
      }
    }
    throw new Error(`SmartLocator failed for ${this.name}. Tried candidates: ${JSON.stringify(this.candidates)}`);
  }

  private resolve(candidate: SmartLocatorCandidate): Locator {
    switch (candidate.strategy) {
      case 'testId': return this.page.getByTestId(candidate.value);
      case 'role': return this.page.getByRole(candidate.role, { name: relaxed(candidate.value) });
      case 'label': return this.page.getByLabel(relaxed(candidate.value));
      case 'placeholder': return this.page.getByPlaceholder(relaxed(candidate.value));
      case 'text': return this.page.getByText(relaxed(candidate.value));
      case 'css': return this.page.locator(candidate.value);
      case 'xpath': return this.page.locator(`xpath=${candidate.value}`);
    }
  }
}

function relaxed(value: string): RegExp {
  return new RegExp(String(value).replace(/[.*+?^${}()|[\]\\]/g, '\\$&').replace(/\s+/g, '\\s+'), 'i');
}
"""
    telemetry = """
import { test as base } from '@playwright/test';
import fs from 'node:fs/promises';
import path from 'node:path';

export const test = base.extend({
  page: async ({ page }, use, testInfo) => {
    const titlePath = typeof (testInfo as any).titlePath === 'function' ? (testInfo as any).titlePath() : ((testInfo as any).titlePath || [testInfo.title]);
    const safeTitle = titlePath.join(' › ').replace(/[^a-z0-9._-]+/gi, '-').slice(0, 120);
    const runId = process.env.QA_AI_RUN_ID || new Date().toISOString().replace(/[:.]/g, '-');
    const bundleDir = path.join(process.cwd(), 'failures', `run-${runId}`, safeTitle);
    await page.context().tracing.start({ screenshots: true, snapshots: true, sources: true }).catch(() => undefined);
    await use(page);
    if (testInfo.status !== testInfo.expectedStatus) {
      await fs.mkdir(bundleDir, { recursive: true });
      await page.screenshot({ path: path.join(bundleDir, 'failure.png'), fullPage: true }).catch(() => undefined);
      await fs.writeFile(path.join(bundleDir, 'dom-snapshot.html'), await page.content().catch(() => ''), 'utf8').catch(() => undefined);
      await fs.writeFile(path.join(bundleDir, 'url.txt'), page.url(), 'utf8').catch(() => undefined);
      await page.context().tracing.stop({ path: path.join(bundleDir, 'trace.zip') }).catch(() => undefined);
      await testInfo.attach('qa-ai-failure-bundle', { body: bundleDir, contentType: 'text/plain' }).catch(() => undefined);
    } else {
      await page.context().tracing.stop().catch(() => undefined);
    }
  },
});

export { expect } from '@playwright/test';
"""

    browser_guard = """
import type { BrowserContext, Page } from '@playwright/test';

export async function grantDefaultBrowserPermissions(context: BrowserContext, origin?: string): Promise<void> {
  const permissions = ['geolocation', 'notifications', 'clipboard-read', 'clipboard-write'];
  await context.grantPermissions(permissions as any, origin ? { origin } : undefined).catch(() => undefined);
}

export async function installBrowserBlockerAutoHandlers(page: Page, origin?: string): Promise<void> {
  await grantDefaultBrowserPermissions(page.context(), origin || new URL(page.url() || 'http://localhost').origin).catch(() => undefined);
  page.on('dialog', async dialog => {
    await dialog.accept().catch(async () => dialog.dismiss().catch(() => undefined));
  });
  page.on('popup', async popup => {
    await popup.close().catch(() => undefined);
  });
  await page.addInitScript(() => {
    try {
      Object.defineProperty(navigator, 'webdriver', { get: () => false });
    } catch {}
  }).catch(() => undefined);
}

export async function dismissKnownBrowserAndAppBlockers(page: Page, timeout = 3000): Promise<void> {
  const candidates = [
    /^(accept|accept all|allow all|agree|ok|got it|continue|close)$/i,
    /^(allow|use my location|enable location|share location)$/i,
    /^(not now|maybe later|no thanks|skip)$/i,
  ];
  for (const name of candidates) {
    const btn = page.getByRole('button', { name }).first();
    if (await btn.isVisible({ timeout: Math.min(750, timeout) }).catch(() => false)) {
      await btn.click({ timeout: Math.min(1500, timeout) }).catch(() => undefined);
    }
  }
  await page.locator('[role="dialog"], [aria-modal="true"], [class*="cookie" i], [id*="cookie" i], [class*="modal" i], [class*="overlay" i]').evaluateAll(nodes => {
    for (const n of nodes) {
      const e = n as HTMLElement;
      const text = (e.innerText || e.textContent || '').toLowerCase();
      if (text.includes('cookie') || text.includes('permission') || text.includes('location') || text.includes('subscribe')) {
        e.style.pointerEvents = 'none';
      }
    }
  }).catch(() => undefined);
}
"""

    readme = """
# QA AI Robust RCA Harness

This folder was installed by Existing Framework Control. It is additive and does not rewrite your framework.

Recommended adoption:
1. Import `test` and `expect` from `qa-ai-support/testTelemetry.fixture.ts` in new/converted specs.
2. Replace direct fragile `page.locator()` calls inside page classes with `SmartLocator` candidates.
3. Import `installBrowserBlockerAutoHandlers()` and `dismissKnownBrowserAndAppBlockers()` in your shared BasePage/fixture to handle geolocation, notification, cookie, modal and dialog blockers before actions.
4. Keep the Page Object Model contract: spec -> page method -> pageObject/locator vault.
5. Use the pipeline GUI to execute, run robust RCA, apply gated healing, and rerun failed-only.

Failure bundles are written to `failures/run-{timestamp}/{testId}/` and include DOM snapshot, screenshot, trace.zip, and URL.
"""
    targets = {
        "SmartLocator.ts": smart_locator.strip() + "\n",
        "testTelemetry.fixture.ts": telemetry.strip() + "\n",
        "BrowserBlockerGuard.ts": browser_guard.strip() + "\n",
        "README.md": readme.strip() + "\n",
    }
    for name, content in targets.items():
        out = support_dir / name
        if not out.exists():
            out.write_text(content, encoding="utf-8")
            files[str(out)] = "created"
        else:
            files[str(out)] = "already_exists"
    return {
        "ok": True,
        "framework_path": str(root),
        "support_dir": str(support_dir),
        "files": files,
        "message": "Robust RCA support harness installed additively. Import the telemetry fixture gradually; no existing specs were rewritten.",
    }


def read_existing_framework_intelligence_v2() -> dict[str, Any]:
    from qa_pipeline.agents.existing_framework_control.framework_intelligence import INTELLIGENCE_V2_JSON
    if not INTELLIGENCE_V2_JSON.exists():
        return {"ok": False, "message": "Framework Intelligence V2 is not available yet. Click Understand Framework / Deep Index first."}
    try:
        data = json.loads(INTELLIGENCE_V2_JSON.read_text(encoding="utf-8", errors="replace"))
        data["ok"] = bool(data.get("ok", True))
        data["framework_intelligence_v2_url"] = "/artifacts/reports/existing-framework/framework-intelligence-v2.html"
        return data
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def search_existing_framework_rag(query: str = "", top_k: int = 10, framework_path: str = "") -> dict[str, Any]:
    if not str(query or "").strip():
        query = "page object locators fixtures api db test data execution flows"
    try:
        return query_framework_context(query, top_k=max(1, min(int(top_k or 10), 25)), framework_path=framework_path or None)
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}", "message": "Run Understand Framework / Deep Index before searching RAG context."}
