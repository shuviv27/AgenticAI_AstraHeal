from __future__ import annotations

import json
import os
import re
from collections import Counter, defaultdict, deque
from datetime import datetime
from pathlib import Path
from typing import Any

from qa_pipeline.core.paths import QA_CACHE_DIR, REPORTS_DIR
from qa_pipeline.core.runtime_logger import log_event
from qa_pipeline.core.tsconfig_alias import load_jsonc
from qa_pipeline.agents.existing_framework_control.structure_discovery import build_structure_profile

CODE_SUFFIXES = {'.ts', '.tsx', '.js', '.jsx', '.mjs', '.cjs'}
SPEC_SUFFIXES = ('.spec.ts', '.specs.ts', '.test.ts', '.spec.js', '.specs.js', '.test.js', '.spec.mjs', '.specs.mjs', '.test.mjs', '.spec.cjs', '.specs.cjs', '.test.cjs', '.feature')
IGNORED = {'node_modules', '.git', 'dist', 'build', 'coverage', 'playwright-report', 'test-results', 'reports', '.next', '.qa-cache', '.aiqa-history', '.codex-backups', '%appdata%', '%AppData%', '.npm', 'npm-cache'}
# Central GUI mirror locations. For existing external frameworks, the selected
# framework owns the source-of-truth memory under <framework>/.qa-cache.
MEMORY_DIR = QA_CACHE_DIR / 'existing-framework' / 'agentic-memory'
REPORT_DIR = REPORTS_DIR / 'existing-framework'
DEEP_JSON = REPORT_DIR / 'agentic-framework-understanding.json'
DEEP_HTML = REPORT_DIR / 'agentic-framework-understanding.html'
MEMORY_JSON = MEMORY_DIR / 'framework-understanding-memory.json'
MEMORY_JSONL = MEMORY_DIR / 'framework-understanding-memory.jsonl'


def framework_agentic_memory_dir(root: Path) -> Path:
    return Path(root).resolve() / '.qa-cache' / 'existing-framework' / 'agentic-memory'


def framework_agentic_reports_dir(root: Path) -> Path:
    return Path(root).resolve() / '.qa-cache' / 'existing-framework' / 'reports'


def _safe_read(path: Path, limit: int = 220_000) -> str:
    try:
        return path.read_text(encoding='utf-8', errors='replace')[:limit]
    except Exception:
        return ''


def _rel(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve())).replace('\\', '/')
    except Exception:
        return str(path).replace('\\', '/')


def _path_under_test_area(parts: tuple[str, ...] | list[str]) -> bool:
    rel = "/".join(str(p).lower() for p in parts if str(p))
    return rel.startswith(("tests/", "src/test/", "src/tests/", "test/", "specs/", "e2e/")) or "/src/test/" in ("/" + rel + "/") or "/tests/" in ("/" + rel + "/")


def _ignored(path: Path, root: Path) -> bool:
    try:
        parts = path.relative_to(root).parts
    except Exception:
        parts = path.parts
    under_test_area = _path_under_test_area(parts)
    for p in parts:
        low = str(p).lower()
        if p in IGNORED or low in IGNORED:
            if low == "reports" and under_test_area:
                continue
            return True
    return False


def _files(root: Path, suffixes: set[str] | None = None, limit: int = 7000) -> list[Path]:
    out: list[Path] = []
    root = Path(root)
    for current, dirs, names in os.walk(root):
        base = Path(current)
        kept_dirs = []
        for d in dirs:
            dlow = d.lower()
            try:
                rel_parts = list((base / d).relative_to(root).parts)
            except Exception:
                rel_parts = [d]
            if (d in IGNORED or dlow in IGNORED) and not (dlow == "reports" and _path_under_test_area(rel_parts)):
                continue
            kept_dirs.append(d)
        dirs[:] = kept_dirs
        for name in names:
            if len(out) >= limit:
                break
            p = base / name
            if not p.is_file() or _ignored(p, root):
                continue
            if suffixes is None or p.suffix.lower() in suffixes or p.name.lower().endswith(SPEC_SUFFIXES):
                out.append(p)
        if len(out) >= limit:
            break
    return sorted(out, key=lambda p: _rel(p, root))


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        if path.name.lower() in {"tsconfig.json", "jsconfig.json"}:
            return load_jsonc(path)
        return json.loads(_safe_read(path, 200_000))
    except Exception:
        return {}


def _extract_imports(text: str) -> list[str]:
    pats = [
        r"import\s+(?:type\s+)?(?:[^;]*?)\s+from\s+['\"]([^'\"]+)['\"]",
        r"import\s*\(\s*['\"]([^'\"]+)['\"]\s*\)",
        r"require\s*\(\s*['\"]([^'\"]+)['\"]\s*\)",
    ]
    vals: list[str] = []
    for pat in pats:
        vals.extend(re.findall(pat, text, flags=re.M))
    return vals


def _tsconfig_paths(root: Path) -> dict[str, list[str]]:
    data = _load_json(root / 'tsconfig.json')
    paths = ((data.get('compilerOptions') or {}).get('paths') or {}) if isinstance(data, dict) else {}
    normalized: dict[str, list[str]] = {}
    for k, v in paths.items():
        normalized[str(k)] = [str(x) for x in (v if isinstance(v, list) else [v])]
    return normalized


def _resolve_import(root: Path, base_file: Path, raw: str, ts_paths: dict[str, list[str]]) -> list[Path]:
    value = (raw or '').strip().strip('"\'`').replace('\\', '/')
    if not value or value.startswith(('http:', 'https:', '@playwright/', 'playwright', 'fs', 'path', 'os', 'crypto')):
        return []
    candidates: list[Path] = []

    def add(base: Path) -> None:
        candidates.append(base)
        if base.suffix.lower() not in {'.ts', '.tsx', '.js', '.jsx', '.mjs', '.cjs', '.json'}:
            for s in ['.ts', '.tsx', '.js', '.jsx', '.mjs', '.cjs']:
                candidates.append(Path(str(base) + s))
            for idx in ['index.ts', 'index.tsx', 'index.js', 'index.jsx']:
                candidates.append(base / idx)

    if value.startswith('.'):
        add(base_file.parent / value)
    add(root / value.lstrip('/'))
    if value.startswith('@/'):
        add(root / value[2:])
    m = re.match(r'^@([^/]+)/(.+)$', value)
    if m:
        alias, rest = m.group(1), m.group(2)
        alias_map = {
            'pages': ['pages', 'src/pages', 'app/pages', 'lib/pages'],
            'pageobjects': ['pageObjects', 'pageobjects', 'page-objects', 'src/pageObjects', 'src/pageobjects', 'src/page-objects'],
            'objects': ['pageObjects', 'pageobjects', 'objects', 'src/pageObjects', 'src/objects'],
            'utils': ['utils', 'src/utils', 'helpers', 'src/helpers', 'test-utils'],
            'helpers': ['helpers', 'src/helpers', 'utils', 'src/utils'],
            'fixtures': ['fixtures', 'tests/fixtures', 'src/fixtures', 'src/test/resources/fixtures'],
            'config': ['config', 'src/config', 'src/main/config', 'tests/config', 'src/test/config'],
            'api': ['api', 'src/api', 'src/main/api'],
            'base': ['base', 'src/base', 'src/main/ui_base', 'src/ui_base'],
            'dataloader': ['data-loader', 'dataLoader', 'src/test/resources/data-loader', 'tests/data-loader'],
            'testdata': ['testData', 'test-data', 'src/test/resources/testData', 'tests/testData'],
            'reporters': ['reporters', 'src/test/resources/reporters', 'tests/reporters'],
            'data': ['testData', 'test-data', 'data', 'src/data', 'src/test/resources/testData'],
        }
        for prefix in alias_map.get(alias.lower(), [alias, f'src/{alias}']):
            add(root / prefix / rest)
    for key, mapped_values in ts_paths.items():
        pat = '^' + re.escape(key).replace('\\*', '(.+)') + '$'
        match = re.match(pat, value)
        if match:
            wildcard = match.group(1) if match.groups() else ''
            for mapped in mapped_values:
                add(root / mapped.replace('*', wildcard))
    resolved: list[Path] = []
    seen: set[str] = set()
    for c in candidates:
        try:
            r = c.resolve()
            r.relative_to(root.resolve())
        except Exception:
            continue
        if r.exists() and r.is_file() and not _ignored(r, root):
            k = str(r).lower()
            if k not in seen:
                resolved.append(r); seen.add(k)
    return resolved


def _classify_file(rel: str, text: str) -> dict[str, Any]:
    low = rel.lower()
    kind = 'code'
    if rel.lower().endswith('.feature'): kind = 'bdd_feature'
    elif rel.lower().endswith(SPEC_SUFFIXES): kind = 'spec'
    elif '/pages/' in f'/{low}/' or low.endswith('page.ts') or low.endswith('page.js'): kind = 'page_method_layer'
    elif any(x in low for x in ['pageobjects', 'page-objects', 'page_objects', '/objects/', '/locators/', 'object-repository']): kind = 'locator_object_layer'
    elif any(x in low for x in ['/ui_base/', '/ui-base/', '/uibase/', 'basepage', 'safeaction', 'smartlocator']): kind = 'ui_base_layer'
    elif any(x in low for x in ['/config/', '/configs/', '/configuration/', '/environment/']): kind = 'configuration_layer'
    elif any(x in low for x in ['/api/', '/apis/', '/services/', '/clients/', '/requests/']): kind = 'api_service_layer'
    elif any(x in low for x in ['/utils/', '/helpers/', '/utilities/', '/common/', '/shared/']): kind = 'utility_helper_layer'
    elif any(x in low for x in ['/fixtures/', '/support/', 'fixture', 'hooks', 'world']): kind = 'fixture_layer'
    elif any(x in low for x in ['testdata', 'test-data', 'test_data', '/data/', '/resources/']): kind = 'test_data_layer'
    locators = {
        'getByRole': len(re.findall(r'\.getByRole\s*\(', text)),
        'getByTestId': len(re.findall(r'\.getByTestId\s*\(', text)),
        'getByLabel': len(re.findall(r'\.getByLabel\s*\(', text)),
        'getByText': len(re.findall(r'\.getByText\s*\(', text)),
        'locator': len(re.findall(r'\.locator\s*\(', text)),
        'xpath': len(re.findall(r'xpath=|//[a-zA-Z*]|\[contains\(', text)),
        'css': len(re.findall(r'css=|\.locator\s*\(\s*["\'](?:\.|#|\[)', text)),
    }
    anti_patterns = []
    if re.search(r'waitForTimeout\s*\(', text): anti_patterns.append('blind_waitForTimeout')
    if re.search(r'force\s*:\s*true', text): anti_patterns.append('force_true_click_or_action')
    if re.search(r'test\.(skip|only|fixme)\s*\(', text): anti_patterns.append('test_skip_only_or_fixme')
    if kind == 'spec' and re.search(r'page\.(locator|getByRole|getByText|getByTestId|getByLabel)\s*\(', text): anti_patterns.append('inline_locator_inside_spec')
    functions = re.findall(r'(?:async\s+)?(?:function\s+([A-Za-z_][A-Za-z0-9_]*)|([A-Za-z_][A-Za-z0-9_]*)\s*\([^)]*\)\s*[:\w<>\[\]\s]*=>|(?:public|private|protected)?\s*(?:async\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*\([^)]*\)\s*[:\w<>\[\]\s]*\{)', text)
    names = sorted({n for tup in functions for n in tup if n})[:80]
    classes = re.findall(r'class\s+([A-Za-z_][A-Za-z0-9_]*)', text)
    tests = re.findall(r'test(?:\.\w+)?\s*\(\s*["\']([^"\']{1,160})["\']', text)
    gotos = re.findall(r'page\.goto\s*\(\s*[`"\']([^`"\']+)', text)
    return {
        'kind': kind,
        'locator_counts': locators,
        'anti_patterns': anti_patterns,
        'functions': names,
        'classes': classes[:40],
        'test_titles': tests[:60],
        'page_routes': gotos[:40],
    }


def _folder_roles(files: list[Path], root: Path) -> list[dict[str, Any]]:
    counts: dict[str, Counter] = defaultdict(Counter)
    examples: dict[str, list[str]] = defaultdict(list)
    for f in files:
        rel = _rel(f, root)
        top = rel.split('/')[0] if '/' in rel else '.'
        kind = _classify_file(rel, _safe_read(f, 30_000))['kind']
        counts[top][kind] += 1
        if len(examples[top]) < 8:
            examples[top].append(rel)
    roles = []
    for folder, counter in sorted(counts.items()):
        total = sum(counter.values())
        dominant = counter.most_common(1)[0][0]
        roles.append({'folder': folder, 'dominant_role': dominant, 'file_count': total, 'role_counts': dict(counter), 'examples': examples[folder]})
    return roles


def _build_dependency_graph(root: Path, spec_files: list[Path], all_files: list[Path]) -> dict[str, Any]:
    ts_paths = _tsconfig_paths(root)
    graph: dict[str, list[str]] = {}
    reverse: dict[str, list[str]] = defaultdict(list)
    unresolved: dict[str, list[str]] = {}
    file_set = set(all_files)
    for f in all_files[:5000]:
        text = _safe_read(f, 120_000)
        resolved_rels = []
        missing = []
        for imp in _extract_imports(text):
            res = _resolve_import(root, f, imp, ts_paths)
            if res:
                for r in res:
                    if r in file_set:
                        rr = _rel(r, root); resolved_rels.append(rr); reverse[rr].append(_rel(f, root))
            elif not imp.startswith(('@playwright/', 'playwright')) and not re.match(r'^[a-zA-Z0-9_-]+$', imp):
                missing.append(imp)
        graph[_rel(f, root)] = sorted(set(resolved_rels))
        if missing:
            unresolved[_rel(f, root)] = missing[:40]
    spec_chains = {}
    for spec in spec_files[:400]:
        start = _rel(spec, root)
        visited = {start}
        q = deque([(start, 0)])
        deps: list[str] = []
        while q:
            cur, depth = q.popleft()
            if depth >= 3:
                continue
            for nxt in graph.get(cur, []):
                if nxt in visited:
                    continue
                visited.add(nxt); deps.append(nxt); q.append((nxt, depth + 1))
        spec_chains[start] = deps[:120]
    return {'direct_import_graph': {k: v for k, v in graph.items() if k in spec_chains or v}, 'reverse_import_sample': dict(list(reverse.items())[:200]), 'unresolved_imports': unresolved, 'spec_dependency_chains': spec_chains, 'tsconfig_paths': ts_paths}


def _aut_understanding(root: Path, files: list[Path], base_url: str = '') -> dict[str, Any]:
    routes = []
    auth_hints = Counter()
    domains = []
    api_hints = Counter()
    keywords = Counter()
    for f in files[:3000]:
        text = _safe_read(f, 80_000)
        rel = _rel(f, root)
        for route in re.findall(r'page\.goto\s*\(\s*[`"\']([^`"\']+)', text):
            routes.append({'file': rel, 'route': route[:220]})
        for url in re.findall(r'https?://[^\s"\'`<>]+', text):
            domains.append(url[:240])
        for word in ['login','logout','dashboard','cart','checkout','payment','search','profile','admin','policy','claim','quote','order','invoice','approval','workflow']:
            if word in text.lower(): keywords[word] += 1
        for word in ['token','cookie','session','auth','sso','oauth','jwt','mfa','otp']:
            if word in text.lower(): auth_hints[word] += 1
        for word in ['waitForResponse','request.','axios','fetch(','graphql','api/','/api']:
            if word.lower() in text.lower(): api_hints[word] += 1
    return {'base_url_from_gui': base_url, 'routes_seen_in_tests': routes[:120], 'external_urls_seen': sorted(set(domains))[:80], 'business_domain_keyword_hints': dict(keywords.most_common(25)), 'auth_session_hints': dict(auth_hints.most_common(20)), 'api_backend_hints': dict(api_hints.most_common(20)), 'note': 'This is static AUT understanding from tests/config/docs. MCP/headed execution adds runtime page/accessibility evidence after failures.'}


def _locator_strategy(files: list[Path], root: Path) -> dict[str, Any]:
    totals = Counter()
    by_file = []
    anti = []
    for f in files:
        rel = _rel(f, root)
        text = _safe_read(f, 120_000)
        info = _classify_file(rel, text)
        c = Counter(info['locator_counts'])
        totals.update(c)
        if sum(c.values()) or info['anti_patterns']:
            by_file.append({'file': rel, 'kind': info['kind'], 'locator_counts': dict(c), 'anti_patterns': info['anti_patterns']})
        if info['anti_patterns']:
            anti.append({'file': rel, 'anti_patterns': info['anti_patterns']})
    total_locator_calls = sum(totals.values()) or 1
    stable = totals.get('getByRole', 0) + totals.get('getByTestId', 0) + totals.get('getByLabel', 0)
    brittle = totals.get('xpath', 0) + totals.get('css', 0)
    return {'overall_counts': dict(totals), 'stable_locator_ratio': round(stable/total_locator_calls, 3), 'brittle_locator_ratio': round(brittle/total_locator_calls, 3), 'file_level_locator_map': by_file[:500], 'anti_pattern_files': anti[:200], 'recommendations': _locator_recommendations(totals, anti)}


def _locator_recommendations(totals: Counter, anti: list[dict[str, Any]]) -> list[str]:
    recs = []
    if totals.get('xpath', 0) > totals.get('getByRole', 0): recs.append('XPath usage is high. Prefer getByRole/getByTestId/getByLabel where AUT exposes stable accessibility/test id attributes.')
    if totals.get('locator', 0) and not totals.get('getByTestId', 0): recs.append('Generic locator() usage exists but test id strategy is not visible. Consider a formal data-testid contract with dev team.')
    if anti: recs.append('Anti-patterns detected: raw waitForTimeout/force:true/test.skip/inline spec locators. Guarded self-healing should avoid adding more of these.')
    if not recs: recs.append('Locator strategy looks acceptable from static scan. Runtime MCP evidence should still validate actual DOM/actionability on failures.')
    return recs


def _architecture_recommendations(folder_roles: list[dict[str, Any]], locator: dict[str, Any], dep_graph: dict[str, Any]) -> list[str]:
    roles = {r['dominant_role'] for r in folder_roles}
    recs = []
    if 'page_method_layer' not in roles: recs.append('Page method layer is not clearly visible. AI should avoid large spec patches and suggest extracting reusable methods if repeated steps exist.')
    if 'locator_object_layer' not in roles: recs.append('Dedicated pageObjects/locator layer is not clearly visible. Existing locator style must be learned from pages/helpers before patching.')
    if locator.get('brittle_locator_ratio', 0) > 0.35: recs.append('Brittle locator ratio is high. Use MCP/accessibility evidence to migrate unstable locators carefully in related failed scope.')
    unresolved = dep_graph.get('unresolved_imports') or {}
    if unresolved: recs.append('Some imports could not be resolved. Configure tsconfig alias mapping or confirm framework root to improve safe patch scope.')
    recs.append('Before any automatic fix, resolve failed spec dependency chain and patch only the related spec/page/pageObject/helper/testData files.')
    return recs



def _load_reference_framework_profiles() -> dict[str, Any]:
    try:
        profiles_path = REPO_ROOT / 'configs' / 'reference-framework-profiles.json'
        if profiles_path.exists():
            return json.loads(profiles_path.read_text(encoding='utf-8', errors='replace'))
    except Exception as exc:
        return {'warning': f'{type(exc).__name__}: {exc}'}
    return {'profiles': []}

def _detect_framework_family(root: Path, files: list[Path]) -> dict[str, Any]:
    rels = [_rel(f, root).lower() for f in files[:5000]]
    has_cucumber = (root / 'cucumber.js').exists() or any(r.endswith('.feature') for r in rels)
    has_playwright_specs = any(r.endswith(SPEC_SUFFIXES[:-1]) for r in rels)
    family = 'cucumber_playwright_bdd' if has_cucumber else 'playwright_test' if has_playwright_specs else 'unknown'
    return {
        'family': family,
        'has_cucumber_js': (root / 'cucumber.js').exists(),
        'has_feature_files': any(r.endswith('.feature') for r in rels),
        'has_playwright_specs': has_playwright_specs,
        'has_step_definitions': any('step-definitions' in r for r in rels),
        'has_support_world_hooks': any('src/support/world' in r or 'src/support/hooks' in r for r in rels),
    }

def build_deep_framework_understanding(root: Path, inventory: dict[str, Any] | None = None, base_url: str = '', failure_scope: list[str] | None = None) -> dict[str, Any]:
    """Multi-agent deterministic framework understanding for enterprise Playwright repos.

    This creates auditable, reusable project memory. It does not modify the user framework.
    The output is intentionally structured so RCA/self-healing prompts can include it.
    """
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    structure_profile = build_structure_profile(root, limit=7000)
    all_files = _files(root, CODE_SUFFIXES | {'.json', '.md', '.txt', '.yaml', '.yml', '.feature'}, limit=7000)
    executable_rel_specs = set(structure_profile.get('executable_specs') or [])
    spec_files = [p for p in all_files if _rel(p, root) in executable_rel_specs]
    feature_files = [p for p in all_files if p.name.lower().endswith('.feature')]
    file_profiles = []
    for f in all_files[:2500]:
        rel = _rel(f, root)
        text = _safe_read(f, 140_000)
        info = _classify_file(rel, text)
        file_profiles.append({'file': rel, **info, 'size': f.stat().st_size if f.exists() else 0})
    folder_roles = _folder_roles(all_files, root)
    dep_graph = _build_dependency_graph(root, spec_files, all_files)
    locator = _locator_strategy(all_files, root)
    aut = _aut_understanding(root, all_files, base_url)
    framework_family = _detect_framework_family(root, all_files)
    reference_profiles = _load_reference_framework_profiles()
    failed_scope = failure_scope or []
    relevant_failed_chains = {s: dep_graph.get('spec_dependency_chains', {}).get(s, []) for s in failed_scope}
    report = {
        'ok': True,
        'stage': 'agentic_multi_agent_framework_understanding_completed',
        'generated_at': datetime.now().isoformat(timespec='seconds'),
        'framework_path': str(root),
        'agents': {
            'architecture_agent': 'folder/file role mapping and POM layer detection',
            'code_semantics_agent': 'classes/functions/test titles/page routes/import graph',
            'locator_strategy_agent': 'locator style, brittle selectors, anti-patterns',
            'aut_flow_agent': 'AUT routes, business keywords, auth/session/API hints',
            'safe_patch_scope_agent': 'spec dependency chains and allowed patch candidates',
            'memory_agent': 'writes reusable understanding into project memory',
        },
        'inventory_summary': {
            'total_files_scanned': len(all_files),
            'spec_count': len(spec_files),
            'feature_file_count': len(feature_files),
            'sample_specs': [_rel(p, root) for p in spec_files[:80]],
            'discovered_test_roots': structure_profile.get('discovered_test_roots') or [],
        },
        'structure_discovery': structure_profile,
        'component_directory_model': structure_profile.get('component_directory_model') or {},
        'folder_role_map': folder_roles,
        'file_profiles_sample': file_profiles[:600],
        'dependency_graph': dep_graph,
        'locator_strategy': locator,
        'aut_understanding': aut,
        'framework_family_detection': framework_family,
        'reference_framework_profiles_used': reference_profiles,
        'failed_scope_dependency_chains': relevant_failed_chains,
        'architecture_recommendations': _architecture_recommendations(folder_roles, locator, dep_graph),
        'rca_self_healing_policy': {
            'explain_failed_tests': 'Use execution logs, failed inventory, dependency chain, RAG chunks, MCP evidence and framework memory to classify root cause.',
            'check_failed_element_with_mcp': 'Use runtime accessibility/DOM/actionability evidence for the failed locator/action; does not modify files.',
            'safe_fix_order': ['pageObjects/locator modules', 'page methods/BasePage/helpers', 'fixtures/testData if evidence proves data issue', 'spec file only when no reusable layer exists'],
            'human_intervention_required_when': ['safe patch scope is empty', 'failure is environment/auth/network/product defect', 'assertion drift is functional or numeric', 'Codex/Ollama patch confidence is below threshold', 'unresolved import graph prevents safe mapping'],
        },
    }
    local_memory_dir = framework_agentic_memory_dir(root)
    local_report_dir = framework_agentic_reports_dir(root)
    local_memory_dir.mkdir(parents=True, exist_ok=True)
    local_report_dir.mkdir(parents=True, exist_ok=True)
    report['cache_storage_policy'] = {
        'selected_framework_owns_cache': True,
        'framework_local_memory_dir': str(local_memory_dir),
        'framework_local_reports_dir': str(local_report_dir),
        'central_gui_memory_mirror': str(MEMORY_DIR),
        'central_gui_report_mirror': str(REPORT_DIR),
        'why': 'Existing-framework learning follows the user-selected framework path. Central files are compatibility mirrors for the GUI only.',
    }
    DEEP_JSON.write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    MEMORY_JSON.write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    (local_report_dir / 'agentic-framework-understanding.json').write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    (local_memory_dir / 'framework-understanding-memory.json').write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    entry = {'ts': report['generated_at'], 'type': 'framework_understanding', 'framework_path': str(root), 'summary': report['inventory_summary'], 'recommendations': report['architecture_recommendations']}
    for target in (MEMORY_JSONL, local_memory_dir / 'framework-understanding-memory.jsonl'):
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open('a', encoding='utf-8') as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + '\n')
    _write_html(report)
    try:
        (local_report_dir / 'agentic-framework-understanding.html').write_text(DEEP_HTML.read_text(encoding='utf-8', errors='replace'), encoding='utf-8')
    except Exception:
        pass
    log_event('existing_framework_deep_agents', 'Agentic multi-agent framework understanding completed and saved to project memory.', status='done', progress=100, details={'framework_path': str(root), 'spec_count': len(spec_files)})
    return report


def load_deep_framework_memory() -> dict[str, Any]:
    if MEMORY_JSON.exists():
        try:
            return json.loads(MEMORY_JSON.read_text(encoding='utf-8', errors='replace'))
        except Exception as exc:
            return {'ok': False, 'error': f'{type(exc).__name__}: {exc}'}
    return {'ok': False, 'message': 'No deep framework memory exists yet. Click Learn this framework with AI.'}


def _h(v: Any) -> str:
    return str(v if v is not None else '').replace('&','&amp;').replace('<','&lt;').replace('>','&gt;')


def _write_html(report: dict[str, Any]) -> None:
    cards = []
    for key in ['agents', 'inventory_summary', 'structure_discovery', 'component_directory_model', 'framework_family_detection', 'reference_framework_profiles_used', 'folder_role_map', 'locator_strategy', 'aut_understanding', 'architecture_recommendations', 'rca_self_healing_policy']:
        cards.append(f"<section class='card'><h2>{_h(key.replace('_',' ').title())}</h2><pre>{_h(json.dumps(report.get(key), indent=2, ensure_ascii=False))}</pre></section>")
    html = f"""<!doctype html><html><head><meta charset='utf-8'><title>Agentic Framework Understanding</title>
<style>body{{font-family:Segoe UI,Arial,sans-serif;margin:24px;background:#07111f;color:#e5edf8}}.card{{background:#0f1b2d;border:1px solid #25415f;border-radius:16px;padding:16px;margin:14px 0;box-shadow:0 10px 30px rgba(0,0,0,.22)}}pre{{white-space:pre-wrap;background:#07111f;border:1px solid #223752;color:#dbeafe;border-radius:12px;padding:14px;overflow:auto}}code{{background:#17243a;padding:3px 7px;border-radius:7px}}.pill{{display:inline-block;background:#1d4ed8;color:white;border-radius:999px;padding:4px 10px;margin-right:6px}}</style></head><body>
<h1>Agentic Multi-Agent Framework Understanding</h1><p><span class='pill'>Architecture</span><span class='pill'>Code Semantics</span><span class='pill'>Locator Strategy</span><span class='pill'>AUT Flow</span><span class='pill'>Safe Patch Scope</span><span class='pill'>Memory</span></p><p>Framework: <code>{_h(report.get('framework_path'))}</code></p>{''.join(cards)}</body></html>"""
    DEEP_HTML.write_text(html, encoding='utf-8')
