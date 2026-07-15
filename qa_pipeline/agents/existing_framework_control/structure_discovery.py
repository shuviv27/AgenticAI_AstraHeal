from __future__ import annotations

import os
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

EXECUTABLE_SPEC_SUFFIXES = (
    ".spec.ts", ".specs.ts", ".test.ts",
    ".spec.tsx", ".specs.tsx", ".test.tsx",
    ".spec.js", ".specs.js", ".test.js",
    ".spec.jsx", ".specs.jsx", ".test.jsx",
    ".spec.mjs", ".specs.mjs", ".test.mjs",
    ".spec.cjs", ".specs.cjs", ".test.cjs",
)

PLAYWRIGHT_CONFIG_NAMES = (
    "playwright.config.ts", "playwright.config.js", "playwright.config.mjs",
    "playwright.config.cjs", "playwright.config.mts", "playwright.config.cts",
)

IGNORED_DIR_NAMES = {
    "node_modules", ".git", "dist", "build", "coverage", ".next",
    "playwright-report", "test-results", ".codex-backups", ".aiqa-history",
    ".qa-cache", ".npm", "npm-cache", "tmp", "temp",
}

# Ordered from strongest/deepest convention to broadest. The scanner does not
# require one of these names, but they make a candidate executable without
# reading the file body.
TEST_AREA_NAMES = {
    "tests", "test", "specs", "spec", "e2e", "integration", "acceptance",
    "functional", "ui-tests", "ui_tests", "automation-tests", "automation_tests",
}

COMPONENT_ROLE_NAMES: dict[str, set[str]] = {
    "spec_dirs": TEST_AREA_NAMES,
    "page_dirs": {"pages", "page", "screens", "views"},
    "page_object_dirs": {"pageobjects", "page-objects", "page_objects", "objects", "locators", "objectrepository", "object-repository"},
    "config_dirs": {"config", "configs", "configuration", "environments", "environment"},
    "api_dirs": {"api", "apis", "services", "clients", "http", "requests"},
    "ui_base_dirs": {"ui_base", "ui-base", "uibase", "base", "core", "framework"},
    "fixture_dirs": {"fixtures", "fixture", "hooks", "support"},
    "test_data_dirs": {"testdata", "test-data", "test_data", "data", "datasets", "resources"},
    "utility_dirs": {"utils", "utilities", "helpers", "common", "lib", "shared"},
    "reporter_dirs": {"reporters", "reporter", "reporting"},
}

_PLAYWRIGHT_IMPORT_RE = re.compile(
    r"(?:from\s+|require\s*\(\s*)['\"](?:@playwright/test|playwright/test|playwright)['\"]",
    flags=re.I,
)
_PLAYWRIGHT_TEST_CALL_RE = re.compile(
    r"(?<![\w$])(?:test|it)(?:\.(?:only|skip|fixme|fail|slow))?\s*\(",
    flags=re.I,
)
_CUSTOM_TEST_WRAPPER_RE = re.compile(
    r"(?<![\w$])(?:testDetails|testCase|createTest|uiTest|scenario)\s*\(",
    flags=re.I,
)


def _safe_read(path: Path, limit: int = 350_000) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")[:limit]
    except Exception:
        return ""


def _rel(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except Exception:
        return str(path).replace("\\", "/")


def _normalized_rel(value: str | Path) -> str:
    text = str(value or "").replace("\\", "/").strip().strip("'\"`")
    while text.startswith("./"):
        text = text[2:]
    return text.strip("/")


def _is_ignored_relative(rel: str) -> bool:
    parts = [p.lower() for p in _normalized_rel(rel).split("/") if p]
    return any(part in IGNORED_DIR_NAMES for part in parts)


def _walk(root: Path, *, want_files: bool = True, max_items: int = 30_000) -> Iterable[Path]:
    count = 0
    for current, dirs, names in os.walk(root):
        base = Path(current)
        dirs[:] = [d for d in dirs if d.lower() not in IGNORED_DIR_NAMES]
        items = names if want_files else dirs
        for name in items:
            if count >= max_items:
                return
            path = base / name
            if want_files and not path.is_file():
                continue
            if not want_files and not path.is_dir():
                continue
            count += 1
            yield path


def _config_files(root: Path) -> list[Path]:
    found: list[Path] = []
    for name in PLAYWRIGHT_CONFIG_NAMES:
        direct = root / name
        if direct.exists():
            found.append(direct)
    # Monorepos can place a config below the selected parent folder. Only scan a
    # bounded depth and let the framework-root resolver decide the final root.
    base_depth = len(root.parts)
    for path in _walk(root, want_files=True, max_items=12_000):
        if path.name not in PLAYWRIGHT_CONFIG_NAMES:
            continue
        if len(path.parts) - base_depth > 8:
            continue
        if path not in found:
            found.append(path)
    return sorted(found, key=lambda p: _rel(p, root))


def _join_literal_args(arg_text: str) -> str:
    values = re.findall(r"['\"]([^'\"]+)['\"]", arg_text or "")
    values = [v.replace("\\", "/").strip("/") for v in values if v and v != "__dirname"]
    return "/".join(v for v in values if v)


def _extract_path_variables(text: str) -> dict[str, tuple[str, bool]]:
    values: dict[str, tuple[str, bool]] = {}
    # const TEST_ROOT = './src/test/specs'
    for match in re.finditer(r"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(['\"])(.+?)\2\s*;?", text, flags=re.S):
        value = _normalized_rel(match.group(3))
        if value:
            values[match.group(1)] = (value, False)
    # const TEST_ROOT = path.resolve(__dirname, 'src', 'test', 'specs')
    # const TEST_ROOT = path.resolve(process.cwd(), 'src', 'test', 'specs')
    for match in re.finditer(r"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*path\.(?:resolve|join)\s*\(((?:[^()]|\([^()]*\))*)\)\s*;?", text, flags=re.S):
        args = match.group(2)
        value = _normalized_rel(_join_literal_args(args))
        if value:
            values[match.group(1)] = (value, "process.cwd" in args)
    return values


def _resolve_config_test_dir(root: Path, config_file: Path, value: str, *, from_cwd: bool = False) -> str:
    raw = str(value or "").replace("\\", "/").strip().strip("'\"`")
    if not raw:
        return ""
    base = root if from_cwd else config_file.parent
    try:
        resolved = (base / raw).resolve()
        return resolved.relative_to(root.resolve()).as_posix()
    except Exception:
        # External test roots are intentionally not accepted as executable patch
        # targets for the selected framework.
        return ""


def discover_configured_test_dirs(root: Path) -> list[str]:
    root = Path(root).resolve()
    candidates: list[str] = []
    for cfg in _config_files(root):
        text = _safe_read(cfg)
        variables = _extract_path_variables(text)

        # testDir: './src/test/specs' (relative to the config file).
        for match in re.finditer(r"\btestDir\s*:\s*(['\"])(.+?)\1", text, flags=re.I | re.S):
            value = _resolve_config_test_dir(root, cfg, match.group(2))
            if value:
                candidates.append(value)

        # testDir: path.resolve(__dirname, 'src', 'test', 'specs') or
        # path.resolve(process.cwd(), 'src', 'test', 'specs').
        for match in re.finditer(r"\btestDir\s*:\s*path\.(?:resolve|join)\s*\(((?:[^()]|\([^()]*\))*)\)", text, flags=re.I | re.S):
            args = match.group(1)
            value = _join_literal_args(args)
            resolved = _resolve_config_test_dir(root, cfg, value, from_cwd="process.cwd" in args)
            if resolved:
                candidates.append(resolved)

        # testDir: TEST_ROOT. Simple string/path variables are supported.
        for match in re.finditer(r"\btestDir\s*:\s*([A-Za-z_$][\w$]*)", text, flags=re.I):
            variable = match.group(1)
            variable_value = variables.get(variable)
            if variable_value:
                value, from_cwd = variable_value
                resolved = _resolve_config_test_dir(root, cfg, value, from_cwd=from_cwd)
                if resolved:
                    candidates.append(resolved)

    result: list[str] = []
    seen: set[str] = set()
    for value in candidates:
        rel = _normalized_rel(value)
        if not rel or _is_ignored_relative(rel):
            continue
        key = rel.lower()
        if key not in seen:
            result.append(rel)
            seen.add(key)
    return result


def _under_root(rel: str, directory: str) -> bool:
    rel_low = _normalized_rel(rel).lower()
    dir_low = _normalized_rel(directory).lower()
    return bool(dir_low) and (rel_low == dir_low or rel_low.startswith(dir_low + "/"))


def _conventional_test_area(rel: str) -> str:
    parts = [p for p in _normalized_rel(rel).split("/") if p]
    best_index = -1
    for idx, part in enumerate(parts[:-1]):
        if part.lower() in TEST_AREA_NAMES:
            best_index = idx
    if best_index < 0:
        return ""
    return "/".join(parts[:best_index + 1])


def has_playwright_executable_content(path: Path) -> bool:
    text = _safe_read(path)
    if not text.strip():
        return False
    # Require a test call/wrapper. Import alone is common in fixtures/configs.
    has_call = bool(_PLAYWRIGHT_TEST_CALL_RE.search(text) or _CUSTOM_TEST_WRAPPER_RE.search(text))
    if not has_call:
        return False
    # Imports are strong proof, but custom frameworks may re-export test from a
    # local fixture. A test call in a Playwright-named file is sufficient.
    return bool(_PLAYWRIGHT_IMPORT_RE.search(text) or path.name.lower().endswith(EXECUTABLE_SPEC_SUFFIXES))


def classify_spec_candidate(root: Path, rel_path: str | Path, configured_test_dirs: list[str] | None = None) -> dict[str, Any]:
    root = Path(root).resolve()
    rel = _normalized_rel(rel_path)
    low = rel.lower()
    path = root / rel
    result: dict[str, Any] = {
        "path": rel,
        "accepted": False,
        "reason": "",
        "test_root": "",
        "configured_test_dir": "",
        "content_proof": False,
    }
    if not low.endswith(EXECUTABLE_SPEC_SUFFIXES):
        result["reason"] = "unsupported_spec_suffix"
        return result
    if _is_ignored_relative(rel):
        result["reason"] = "ignored_generated_dependency_or_history_path"
        return result

    configured = configured_test_dirs if configured_test_dirs is not None else discover_configured_test_dirs(root)
    for test_dir in sorted(configured, key=lambda x: len(_normalized_rel(x)), reverse=True):
        if _under_root(rel, test_dir):
            result.update({"accepted": True, "reason": "configured_playwright_test_dir", "test_root": _normalized_rel(test_dir), "configured_test_dir": _normalized_rel(test_dir)})
            return result

    conventional = _conventional_test_area(rel)
    if conventional:
        result.update({"accepted": True, "reason": "conventional_or_enterprise_test_area", "test_root": conventional})
        return result

    if path.exists() and path.is_file():
        proof = has_playwright_executable_content(path)
        result["content_proof"] = proof
        if proof:
            result.update({"accepted": True, "reason": "playwright_executable_content_proof", "test_root": _normalized_rel(path.parent.relative_to(root))})
            return result

    result["reason"] = "spec_named_file_without_test_root_or_executable_content_proof"
    return result


def _component_directory_model(root: Path) -> dict[str, list[str]]:
    buckets: dict[str, list[str]] = {key: [] for key in COMPONENT_ROLE_NAMES}
    for path in _walk(root, want_files=False, max_items=12_000):
        rel = _rel(path, root)
        name = path.name.lower()
        low = rel.lower()
        for role, names in COMPONENT_ROLE_NAMES.items():
            matched = name in names
            if role == "page_object_dirs" and any(token in low for token in ("pageobject", "page-object", "object-repository")):
                matched = True
            if role == "ui_base_dirs" and any(token in low for token in ("ui_base", "ui-base", "basepage")):
                matched = True
            if role == "spec_dirs" and any(part in TEST_AREA_NAMES for part in low.split("/")):
                matched = True
            if matched:
                buckets[role].append(rel)
    return {key: sorted(dict.fromkeys(values))[:200] for key, values in buckets.items()}


def build_structure_profile(root: Path, *, limit: int = 5000) -> dict[str, Any]:
    """Build a deterministic, recursive Playwright framework structure profile.

    Discovery accepts a spec when one of three independent signals is present:
    configured Playwright ``testDir``, a conventional/nested enterprise test area,
    or executable Playwright test content. This keeps legacy ``tests/**`` behavior
    while supporting ``src/test/specs/**`` and unusual monorepo layouts.
    """
    root = Path(root).resolve()
    configured_dirs = discover_configured_test_dirs(root)
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    candidates = 0
    for path in _walk(root, want_files=True, max_items=max(limit * 8, 20_000)):
        if candidates >= limit:
            break
        if not path.name.lower().endswith(EXECUTABLE_SPEC_SUFFIXES):
            continue
        candidates += 1
        rel = _rel(path, root)
        classification = classify_spec_candidate(root, rel, configured_dirs)
        if classification.get("accepted"):
            accepted.append(classification)
        else:
            rejected.append(classification)

    accepted = sorted(accepted, key=lambda x: str(x.get("path") or "").lower())
    roots = sorted(dict.fromkeys(str(x.get("test_root") or "") for x in accepted if x.get("test_root")), key=lambda x: (len(x.split("/")), x.lower()))
    reasons = Counter(str(x.get("reason") or "unknown") for x in accepted)
    components = _component_directory_model(root)

    # Explicitly surface the user's common enterprise split when present.
    source_layout = {
        "has_src": (root / "src").exists(),
        "has_src_main": (root / "src" / "main").exists(),
        "has_src_test": (root / "src" / "test").exists(),
        "has_src_test_specs": (root / "src" / "test" / "specs").exists(),
        "has_root_tests": (root / "tests").exists(),
    }
    return {
        "ok": bool(accepted),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "framework_path": str(root),
        "scan_strategy": "recursive_config_plus_path_plus_content_evidence",
        "candidate_spec_count": candidates,
        "executable_spec_count": len(accepted),
        "executable_specs": [str(x["path"]) for x in accepted],
        "spec_evidence": accepted[:1000],
        "rejected_spec_candidates": rejected[:500],
        "configured_test_dirs": configured_dirs,
        "discovered_test_roots": roots,
        "acceptance_reason_counts": dict(reasons),
        "component_directory_model": components,
        "source_layout": source_layout,
        "safety_rules": [
            "Ignore dependency, build, report, result, cache, backup and history directories.",
            "Keep all legacy tests/** discovery behavior.",
            "Accept custom locations only when Playwright config or executable test content proves the file is runnable.",
            "Never infer a source patch target from filename alone; dependency mapping remains required.",
        ],
    }


def executable_spec_paths(root: Path, *, limit: int = 5000) -> list[Path]:
    profile = build_structure_profile(root, limit=limit)
    return [Path(root).resolve() / rel for rel in profile.get("executable_specs") or []]
