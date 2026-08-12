from __future__ import annotations

import difflib
import json
import os
import re
import shutil
import fnmatch
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable

from qa_pipeline.agentic.framework_cache import compute_framework_fingerprint, load_matching_cache, save_cache
from qa_pipeline.agentic.playwright_standard import MANIFEST_NAME, STANDARD_ID, audit_standard, build_standard_manifest
from qa_pipeline.core.commands import run_command

Progress = Callable[[str, int, str, dict[str, Any] | None], None]


def _emit(progress: Progress | None, stage: str, pct: int, message: str, details: dict[str, Any] | None = None) -> None:
    if progress:
        progress(stage, pct, message, details)


def _jsonc_to_json(text: str) -> str:
    """Remove //, /* */ comments and trailing commas without touching strings."""
    out: list[str] = []
    i = 0
    in_string = False
    escape = False
    while i < len(text):
        ch = text[i]
        nxt = text[i + 1] if i + 1 < len(text) else ''
        if in_string:
            out.append(ch)
            if escape:
                escape = False
            elif ch == '\\':
                escape = True
            elif ch == '"':
                in_string = False
            i += 1
            continue
        if ch == '"':
            in_string = True
            out.append(ch)
            i += 1
            continue
        if ch == '/' and nxt == '/':
            i += 2
            while i < len(text) and text[i] not in '\r\n':
                i += 1
            continue
        if ch == '/' and nxt == '*':
            i += 2
            while i + 1 < len(text) and not (text[i] == '*' and text[i + 1] == '/'):
                i += 1
            i = min(len(text), i + 2)
            continue
        out.append(ch)
        i += 1

    cleaned = ''.join(out)
    out2: list[str] = []
    i = 0
    in_string = False
    escape = False
    while i < len(cleaned):
        ch = cleaned[i]
        if in_string:
            out2.append(ch)
            if escape:
                escape = False
            elif ch == '\\':
                escape = True
            elif ch == '"':
                in_string = False
            i += 1
            continue
        if ch == '"':
            in_string = True
            out2.append(ch)
            i += 1
            continue
        if ch == ',':
            j = i + 1
            while j < len(cleaned) and cleaned[j].isspace():
                j += 1
            if j < len(cleaned) and cleaned[j] in '}]':
                i += 1
                continue
        out2.append(ch)
        i += 1
    return ''.join(out2)


def _load_json(path: Path) -> tuple[dict[str, Any] | None, str]:
    if not path.exists():
        return None, 'missing'
    try:
        text = path.read_text(encoding='utf-8', errors='replace')
        try:
            return json.loads(text), 'ok'
        except Exception:
            # tsconfig/jsconfig are JSONC in real enterprise repos surprisingly
            # often. TypeScript accepts comments/trailing commas, so AstraHeal
            # must not flag a valid compiler config as corrupt merely because
            # Python's strict JSON parser rejects JSONC.
            return json.loads(_jsonc_to_json(text)), 'ok'
    except Exception as exc:
        return None, f'invalid_json: {type(exc).__name__}: {exc}'


def _find_config(root: Path) -> Path | None:
    for name in ('playwright.config.ts', 'playwright.config.js', 'playwright.config.mjs', 'playwright.config.cjs'):
        p = root / name
        if p.exists():
            return p
    found = list(root.glob('**/playwright.config.*'))
    return next((p for p in found if 'node_modules' not in p.parts and '.qa-cache' not in p.parts), None)


_NODE_BUILTINS = {
    'assert', 'buffer', 'child_process', 'cluster', 'console', 'constants', 'crypto', 'dgram', 'diagnostics_channel',
    'dns', 'domain', 'events', 'fs', 'http', 'http2', 'https', 'module', 'net', 'os', 'path', 'perf_hooks',
    'process', 'punycode', 'querystring', 'readline', 'repl', 'stream', 'string_decoder', 'timers', 'tls', 'trace_events',
    'tty', 'url', 'util', 'v8', 'vm', 'wasi', 'worker_threads', 'zlib',
}


def _workspace_dirs(root: Path, package: dict[str, Any] | None) -> list[Path]:
    raw = (package or {}).get('workspaces') or []
    if isinstance(raw, dict):
        raw = raw.get('packages') or []
    if not isinstance(raw, list):
        return []
    found: list[Path] = []
    for item in raw:
        pattern = str(item or '').strip()
        if not pattern:
            continue
        try:
            matches = list(root.glob(pattern))
        except Exception:
            matches = []
        for p in matches:
            if p.is_dir() and (p / 'package.json').exists() and 'node_modules' not in p.parts:
                rp = p.resolve()
                if rp not in found:
                    found.append(rp)
    return sorted(found, key=lambda p: p.as_posix())


def _workspace_packages(root: Path, package: dict[str, Any] | None) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for folder in _workspace_dirs(root, package):
        data, status = _load_json(folder / 'package.json')
        if status != 'ok' or not isinstance(data, dict):
            continue
        items.append({
            'path': folder.relative_to(root).as_posix(),
            'name': str(data.get('name') or folder.name),
            'scripts': data.get('scripts') or {},
            'dependencies': data.get('dependencies') or {},
            'devDependencies': data.get('devDependencies') or {},
            'package': data,
        })
    return items


def _root_owned_source_files(root: Path, package: dict[str, Any] | None) -> list[Path]:
    workspace_roots = _workspace_dirs(root, package)
    excluded_parts = {
        'node_modules', '.git', '.qa-cache', 'playwright-report', 'test-results', 'reports', 'coverage', 'dist', 'build',
        '.next', '.turbo', '.cache',
    }
    suffixes = {'.ts', '.tsx', '.js', '.jsx', '.mjs', '.cjs'}
    result: list[Path] = []
    for p in root.rglob('*'):
        if not p.is_file() or p.suffix.lower() not in suffixes:
            continue
        try:
            rel = p.relative_to(root)
        except Exception:
            continue
        if any(part in excluded_parts for part in rel.parts):
            continue
        resolved = p.resolve()
        if any(resolved == ws or ws in resolved.parents for ws in workspace_roots):
            continue
        result.append(p)
    return result


def _compiler_scope_source_files(root: Path, package: dict[str, Any] | None, tsconfig: dict[str, Any] | None) -> list[Path]:
    """Return root-owned JS/TS files that the root compiler contract can reach.

    A RACPAD-style repository may contain unrelated TypeScript tooling under
    folders such as ``agents/`` while the root tsconfig intentionally compiles
    only ``playwright.config.ts`` + ``src/main`` + ``src/test``. Dependency
    repair must follow that compiler boundary or it will propose packages that
    are irrelevant to ``npm run build``.
    """
    all_root = _root_owned_source_files(root, package)
    if not isinstance(tsconfig, dict):
        return all_root
    include = tsconfig.get('include') or []
    exclude = tsconfig.get('exclude') or []
    if isinstance(include, str):
        include = [include]
    if isinstance(exclude, str):
        exclude = [exclude]
    if not include:
        return all_root

    def matches(rel: str, patterns: list[Any]) -> bool:
        rel = rel.replace('\\', '/')
        for raw in patterns:
            pattern = str(raw or '').replace('\\', '/').strip()
            if not pattern:
                continue
            # TypeScript treats a directory include as recursive. Python's
            # fnmatch is used only as a permissive filter; the final file list
            # still comes from real files under the repository root.
            if not any(ch in pattern for ch in '*?['):
                if rel == pattern or rel.startswith(pattern.rstrip('/') + '/'):
                    return True
            if fnmatch.fnmatch(rel, pattern):
                return True
            if pattern.endswith('/**/*') and rel.startswith(pattern[:-4]):
                return True
        return False

    selected: list[Path] = []
    for p in all_root:
        rel = p.relative_to(root).as_posix()
        if matches(rel, list(include)) and not matches(rel, list(exclude)):
            selected.append(p)
    return selected


def _extract_module_specifiers(text: str) -> set[str]:
    specs: set[str] = set()
    patterns = [
        r"(?:import|export)\s+(?:[^'\"]*?\s+from\s+)?['\"]([^'\"]+)['\"]",
        r"require\(\s*['\"]([^'\"]+)['\"]\s*\)",
        r"import\(\s*['\"]([^'\"]+)['\"]\s*\)",
    ]
    for pattern in patterns:
        specs.update(m.group(1).strip() for m in re.finditer(pattern, text, flags=re.MULTILINE) if m.group(1).strip())
    return specs


def _external_package_name(specifier: str) -> str:
    value = str(specifier or '').strip()
    if not value or value.startswith(('.', '/', '#')) or value.startswith('node:'):
        return ''
    first = value.split('/')[0]
    if first in _NODE_BUILTINS:
        return ''
    if value.startswith('@'):
        parts = value.split('/')
        return '/'.join(parts[:2]) if len(parts) >= 2 else value
    return first


def _matches_ts_alias(specifier: str, tsconfig: dict[str, Any] | None) -> bool:
    paths = (((tsconfig or {}).get('compilerOptions') or {}).get('paths') or {}) if isinstance(tsconfig, dict) else {}
    if not isinstance(paths, dict):
        return False
    for key in paths:
        pattern = str(key or '').strip()
        if not pattern:
            continue
        if '*' in pattern:
            if fnmatch.fnmatch(specifier, pattern):
                return True
        elif specifier == pattern or specifier.startswith(pattern.rstrip('/') + '/'):
            return True
    return False


def _preferred_dependency_version(root: Path, package_name: str, package: dict[str, Any] | None) -> str:
    # Reuse a version already trusted by the repository before falling back to
    # npm's current resolution. This is especially important for enterprise
    # workspaces such as RACPAD where root and workspace packages intentionally
    # share one lockfile.
    for ws in _workspace_packages(root, package):
        for section in ('dependencies', 'devDependencies'):
            value = (ws.get(section) or {}).get(package_name)
            if value:
                return str(value)
    lock_path = root / 'package-lock.json'
    try:
        lock = json.loads(lock_path.read_text(encoding='utf-8', errors='replace'))
        entry = (lock.get('packages') or {}).get(f'node_modules/{package_name}') or {}
        version = str(entry.get('version') or '').strip()
        if version:
            return f'^{version}'
    except Exception:
        pass
    return 'latest'


def _types_package_for(package_name: str) -> str:
    if not package_name or package_name.startswith('@types/'):
        return ''
    if package_name.startswith('@') and '/' in package_name:
        scope, name = package_name[1:].split('/', 1)
        return f'@types/{scope}__{name}'
    return f'@types/{package_name}'


def _package_known_in_repo(root: Path, package_name: str, package: dict[str, Any] | None) -> bool:
    if not package_name:
        return False
    for ws in _workspace_packages(root, package):
        for section in ('dependencies', 'devDependencies'):
            if package_name in (ws.get(section) or {}):
                return True
    try:
        lock = json.loads((root / 'package-lock.json').read_text(encoding='utf-8', errors='replace'))
        return f'node_modules/{package_name}' in (lock.get('packages') or {})
    except Exception:
        return False


def _infer_package_requirements(root: Path, package: dict[str, Any] | None, tsconfig: dict[str, Any] | None) -> dict[str, Any]:
    package = package or {}
    declared = {
        **(package.get('dependencies') or {}),
        **(package.get('devDependencies') or {}),
        **(package.get('optionalDependencies') or {}),
        **(package.get('peerDependencies') or {}),
    }
    workspace_names = {str(x.get('name') or '') for x in _workspace_packages(root, package)}
    imported: set[str] = set()
    node_runtime_usage = False
    files = _compiler_scope_source_files(root, package, tsconfig)
    ambient_modules: set[str] = set()
    for p in files:
        if not p.name.endswith('.d.ts'):
            continue
        try:
            text = p.read_text(encoding='utf-8', errors='replace')
        except Exception:
            continue
        ambient_modules.update(m.group(1).strip() for m in re.finditer(r"declare\s+module\s+['\"]([^'\"]+)['\"]", text) if m.group(1).strip())
    for p in files:
        try:
            text = p.read_text(encoding='utf-8', errors='replace')
        except Exception:
            continue
        if re.search(r'\b(?:process\.|__dirname\b|__filename\b|Buffer\b)', text):
            node_runtime_usage = True
        for spec in _extract_module_specifiers(text):
            if spec in ambient_modules:
                continue
            if spec.startswith('node:') or spec.split('/')[0] in _NODE_BUILTINS:
                node_runtime_usage = True
            if _matches_ts_alias(spec, tsconfig):
                continue
            pkg = _external_package_name(spec)
            if not pkg or pkg in workspace_names:
                continue
            imported.add(pkg)

    compiler = (tsconfig or {}).get('compilerOptions') or {} if isinstance(tsconfig, dict) else {}
    types = compiler.get('types') or [] if isinstance(compiler, dict) else []
    if isinstance(types, str):
        types = [types]
    if any(str(x).lower() == 'node' for x in types):
        node_runtime_usage = True

    missing_dev: dict[str, str] = {}
    unresolved_imports: list[str] = []
    if '@playwright/test' not in declared and 'playwright' not in declared:
        missing_dev['@playwright/test'] = _preferred_dependency_version(root, '@playwright/test', package)
    if 'typescript' not in declared:
        missing_dev['typescript'] = _preferred_dependency_version(root, 'typescript', package)
    if node_runtime_usage and '@types/node' not in declared:
        missing_dev['@types/node'] = _preferred_dependency_version(root, '@types/node', package)

    # Root-owned source files must declare their direct third-party imports at
    # the root package boundary. For safety, AstraHeal auto-proposes only
    # packages already evidenced by the repository/workspace lock graph; an
    # unknown/private package is reported for review rather than guessed from
    # the public registry.
    for dep in sorted(imported):
        if dep in declared or dep in workspace_names:
            continue
        if _package_known_in_repo(root, dep, package):
            missing_dev[dep] = _preferred_dependency_version(root, dep, package)
            types_dep = _types_package_for(dep)
            if types_dep and types_dep not in declared and _package_known_in_repo(root, types_dep, package):
                missing_dev[types_dep] = _preferred_dependency_version(root, types_dep, package)
        else:
            unresolved_imports.append(dep)

    workspaces = _workspace_packages(root, package)
    workspace_typechecks = [x['path'] for x in workspaces if (x.get('scripts') or {}).get('typecheck')]
    root_has_ts = any(p.suffix.lower() in {'.ts', '.tsx'} for p in files)
    scripts = package.get('scripts') or {}
    root_typecheck = str(scripts.get('typecheck') or '').strip()
    root_typecheck_covers_workspaces = bool(re.search(r'(?:--workspaces\b|\s-ws\b)', root_typecheck))
    root_typecheck_includes_root = '--include-workspace-root' in root_typecheck
    if workspaces and root_typecheck and root_typecheck_covers_workspaces:
        commands = ['npm run typecheck']
        if root_has_ts and not root_typecheck_includes_root:
            commands.append('tsc --noEmit')
        build_script = ' && '.join(commands)
        build_strategy = 'reuse-root-workspace-typecheck-then-root-tsc' if len(commands) > 1 else 'reuse-root-workspace-typecheck'
    elif workspaces and root_typecheck:
        commands = []
        if workspace_typechecks:
            commands.append('npm run typecheck --workspaces --if-present')
        commands.append('npm run typecheck')
        build_script = ' && '.join(commands)
        build_strategy = 'workspace-typecheck-then-existing-root-typecheck' if workspace_typechecks else 'existing-root-typecheck'
    elif workspaces and workspace_typechecks:
        base = 'npm run typecheck --workspaces --if-present'
        build_script = f'{base} && tsc --noEmit' if root_has_ts else base
        build_strategy = 'workspace-typecheck-then-root-tsc' if root_has_ts else 'workspace-typecheck'
    else:
        build_script = 'tsc --noEmit'
        build_strategy = 'root-typescript-no-emit'

    return {
        'workspace_aware': bool(workspaces),
        'workspaces': [{'path': x['path'], 'name': x['name'], 'has_typecheck': bool((x.get('scripts') or {}).get('typecheck'))} for x in workspaces],
        'root_typescript_file_count': len([p for p in files if p.suffix.lower() in {'.ts', '.tsx'}]),
        'compiler_scope_file_count': len(files),
        'ambient_declared_modules': sorted(ambient_modules),
        'root_external_imports': sorted(imported),
        'missing_dev_dependencies': missing_dev,
        'unresolved_external_imports': unresolved_imports,
        'root_typecheck_script': root_typecheck,
        'workspace_typecheck_paths': workspace_typechecks,
        'recommended_build_script': build_script,
        'build_strategy': build_strategy,
    }


def _deterministic_lockfile_update(root: Path, package_before: dict[str, Any], package_after: dict[str, Any]) -> dict[str, Any] | None:
    """Update package-lock root metadata only when all added deps are already locked.

    This keeps a RACPAD-style workspace lockfile consistent with an approved
    package.json dependency addition without inventing integrity/resolution
    metadata. If npm must resolve a brand-new package, the lockfile remains a
    command-generated side effect and is not silently persisted.
    """
    lock_path = root / 'package-lock.json'
    if not lock_path.exists():
        return None
    try:
        lock = json.loads(lock_path.read_text(encoding='utf-8', errors='replace'))
    except Exception:
        return None
    packages = lock.get('packages') or {}
    root_meta = packages.get('')
    if not isinstance(root_meta, dict):
        return None
    changed = False
    for section in ('dependencies', 'devDependencies', 'optionalDependencies', 'peerDependencies'):
        before = package_before.get(section) or {}
        after = package_after.get(section) or {}
        if not isinstance(after, dict):
            continue
        additions = {k: v for k, v in after.items() if before.get(k) != v}
        if not additions:
            continue
        for dep in additions:
            if dep not in before and f'node_modules/{dep}' not in packages:
                return None
        dest = root_meta.setdefault(section, {})
        if not isinstance(dest, dict):
            return None
        for dep, version in additions.items():
            if dest.get(dep) != version:
                dest[dep] = version
                changed = True
    if not changed:
        return None
    return {
        'content': json.dumps(lock, indent=2) + '\n',
        'reason': 'Keep package-lock.json root dependency metadata consistent with the approved package.json additions using versions already present in the existing lock graph.',
    }


def _discover_test_dir(root: Path) -> str:
    candidates = ['tests', 'test', 'src/test/specs', 'src/tests', 'e2e', 'specs']
    for rel in candidates:
        p = root / rel
        if p.exists() and any(p.rglob('*.spec.ts')):
            return rel.replace('\\', '/')
    specs = [p for p in root.rglob('*.spec.ts') if 'node_modules' not in p.parts and '.qa-cache' not in p.parts]
    if specs:
        try:
            common = Path(os.path.commonpath([str(p.parent) for p in specs]))
            return str(common.relative_to(root)).replace('\\', '/')
        except Exception:
            pass
    return 'tests'


def analyze_playwright_gaps(framework_path: str | Path) -> dict[str, Any]:
    root = Path(framework_path).expanduser().resolve()
    gaps: list[dict[str, Any]] = []
    suggestions: list[str] = []
    package_path = root / 'package.json'
    tsconfig_path = root / 'tsconfig.json'
    config_path = _find_config(root)
    package, package_status = _load_json(package_path)
    tsconfig, tsconfig_status = _load_json(tsconfig_path)
    requirements = _infer_package_requirements(root, package if isinstance(package, dict) else {}, tsconfig if isinstance(tsconfig, dict) else {})

    if package_status != 'ok':
        gaps.append({'code': 'package_json_missing_or_invalid', 'severity': 'critical', 'file': str(package_path), 'details': package_status, 'auto_fixable': True})
    else:
        scripts = package.get('scripts') or {}
        dev = {**(package.get('dependencies') or {}), **(package.get('devDependencies') or {})}
        if '@playwright/test' not in dev and 'playwright' not in dev:
            gaps.append({'code': 'playwright_dependency_missing', 'severity': 'critical', 'file': 'package.json', 'auto_fixable': True})
        if 'typescript' not in dev:
            gaps.append({'code': 'typescript_dependency_missing', 'severity': 'high', 'file': 'package.json', 'auto_fixable': True})
        if not scripts.get('build'):
            gaps.append({
                'code': 'npm_build_script_missing',
                'severity': 'high',
                'file': 'package.json',
                'auto_fixable': True,
                'recommended': requirements.get('recommended_build_script') or 'tsc --noEmit',
                'workspace_aware': bool(requirements.get('workspace_aware')),
                'build_strategy': requirements.get('build_strategy'),
            })
        for dep, version in sorted((requirements.get('missing_dev_dependencies') or {}).items()):
            if dep in {'@playwright/test', 'typescript'}:
                continue
            gaps.append({
                'code': 'required_dependency_missing',
                'severity': 'high',
                'file': 'package.json',
                'dependency': dep,
                'recommended_version': version,
                'auto_fixable': True,
            })
        for dep in requirements.get('unresolved_external_imports') or []:
            gaps.append({
                'code': 'external_dependency_unresolved',
                'severity': 'high',
                'file': 'package.json',
                'dependency': dep,
                'auto_fixable': False,
                'message': 'A root-owned source file imports this package, but AstraHeal could not prove a trusted version from package-lock.json or a workspace package. Human/AI review is required instead of guessing a public-registry version.',
            })
        if not scripts.get('test') and not scripts.get('test:e2e') and not scripts.get('test:ui'):
            suggestions.append("Add a test script such as 'playwright test' for easier CI and human execution.")

    if tsconfig_status != 'ok':
        gaps.append({'code': 'tsconfig_missing_or_invalid', 'severity': 'critical', 'file': str(tsconfig_path), 'details': tsconfig_status, 'auto_fixable': True})
    else:
        compiler = tsconfig.get('compilerOptions') or {}
        ignore_deprecations = str(compiler.get('ignoreDeprecations') or '')
        if ignore_deprecations and not re.fullmatch(r'(?:5\.0|5\.5|6\.0)', ignore_deprecations):
            gaps.append({'code': 'invalid_ignore_deprecations', 'severity': 'high', 'file': 'tsconfig.json', 'value': ignore_deprecations, 'auto_fixable': True})
        if not compiler.get('moduleResolution'):
            suggestions.append("Set compilerOptions.moduleResolution explicitly (usually 'Node' or 'Bundler') when path aliases are used.")
        if compiler.get('paths') and not compiler.get('baseUrl'):
            gaps.append({'code': 'paths_without_base_url', 'severity': 'high', 'file': 'tsconfig.json', 'auto_fixable': True})

    if config_path is None:
        gaps.append({'code': 'playwright_config_missing', 'severity': 'critical', 'file': 'playwright.config.ts', 'auto_fixable': True})
    else:
        text = config_path.read_text(encoding='utf-8', errors='replace')
        if 'defineConfig' not in text:
            suggestions.append('Use defineConfig from @playwright/test for typed, clearer Playwright configuration.')
        if 'testDir' not in text:
            gaps.append({'code': 'playwright_test_dir_missing', 'severity': 'medium', 'file': str(config_path), 'auto_fixable': True, 'recommended': _discover_test_dir(root)})
        if re.search(r'workers\s*:\s*1\b', text):
            suggestions.append('workers: 1 disables local parallelism. Keep it only for debugging; use environment-driven workers for distributed execution.')

    commands = [
        'npm config set registry https://registry.npmjs.org/',
        'npm install --registry=https://registry.npmjs.org/',
        'npx playwright install chromium',
        'npm run build',
    ]
    return {
        'ok': root.exists() and root.is_dir(),
        'framework_path': str(root),
        'is_playwright': bool(config_path or (package and ('@playwright/test' in json.dumps(package) or 'playwright' in json.dumps(package)))),
        'package_json': {'path': str(package_path), 'status': package_status},
        'tsconfig': {'path': str(tsconfig_path), 'status': tsconfig_status},
        'playwright_config': str(config_path) if config_path else '',
        'discovered_test_dir': _discover_test_dir(root),
        'gaps': gaps,
        'gap_count': len(gaps),
        'critical_gap_count': len([g for g in gaps if g.get('severity') == 'critical']),
        'suggestions': suggestions,
        'package_requirements': requirements,
        'required_commands': commands,
        'message': f'Playwright framework gap analysis found {len(gaps)} concrete gap(s).' if gaps else 'No structural Playwright configuration gaps were found.',
    }


def _desired_safe_contents(root: Path, analysis: dict[str, Any]) -> dict[str, dict[str, Any]]:
    desired: dict[str, dict[str, Any]] = {}
    package_path = root / 'package.json'
    package, status = _load_json(package_path)
    if status == 'missing':
        package = {'name': root.name.lower().replace(' ', '-'), 'private': True, 'scripts': {}, 'devDependencies': {}}
    if package is not None:
        original = deepcopy(package)
        requirements = analysis.get('package_requirements') or _infer_package_requirements(root, package, (_load_json(root / 'tsconfig.json')[0] or {}))
        package.setdefault('scripts', {})
        package.setdefault('devDependencies', {})
        package['scripts'].setdefault('build', str(requirements.get('recommended_build_script') or 'tsc --noEmit'))
        if not any(package['scripts'].get(k) for k in ('test', 'test:e2e', 'test:ui')):
            package['scripts']['test'] = 'playwright test'
        declared = {**(package.get('dependencies') or {}), **(package.get('devDependencies') or {})}
        for dep, version in sorted((requirements.get('missing_dev_dependencies') or {}).items()):
            if dep == '@playwright/test' and 'playwright' in declared:
                continue
            if dep not in declared:
                package['devDependencies'][dep] = version
                declared[dep] = version
        text = json.dumps(package, indent=2) + '\n'
        if package != original or not package_path.exists():
            added_deps = sorted(set((package.get('devDependencies') or {})) - set((original.get('devDependencies') or {}))) if isinstance(original, dict) else sorted(package.get('devDependencies') or {})
            reason = (
                'Ensure the mandatory npm run build contract is executable for the discovered architecture. '
                f"Build strategy: {requirements.get('build_strategy') or 'root-typescript-no-emit'}; "
                f"recommended build: {requirements.get('recommended_build_script') or 'tsc --noEmit'}."
            )
            if added_deps:
                reason += f" Add repository-evidenced required devDependencies: {', '.join(added_deps)}."
            desired['package.json'] = {'content': text, 'reason': reason}
            lock_update = _deterministic_lockfile_update(root, original if isinstance(original, dict) else {}, package)
            if lock_update:
                desired['package-lock.json'] = lock_update

    tsconfig_path = root / 'tsconfig.json'
    tsconfig, _ = _load_json(tsconfig_path)
    if tsconfig is None:
        tsconfig = {'compilerOptions': {'target': 'ES2022', 'module': 'commonjs', 'moduleResolution': 'Node', 'strict': True, 'esModuleInterop': True, 'resolveJsonModule': True, 'skipLibCheck': True, 'noEmit': True}, 'include': ['**/*.ts']}
    original_ts = deepcopy(tsconfig)
    compiler = tsconfig.setdefault('compilerOptions', {})
    if compiler.get('paths') and not compiler.get('baseUrl'):
        compiler['baseUrl'] = '.'
    ignore = str(compiler.get('ignoreDeprecations') or '')
    if ignore and not re.fullmatch(r'(?:5\.0|5\.5|6\.0)', ignore):
        compiler.pop('ignoreDeprecations', None)
    # Do not normalize already-valid enterprise compiler preferences merely to
    # make the file look like AstraHeal's template. Existing layout/config is
    # preserved unless a concrete diagnosed gap requires a change.
    if tsconfig != original_ts or not tsconfig_path.exists():
        desired['tsconfig.json'] = {'content': json.dumps(tsconfig, indent=2) + '\n', 'reason': 'Normalize safe TypeScript compiler settings required for alias-aware Playwright validation.'}

    config = _find_config(root)
    test_dir = analysis.get('discovered_test_dir') or _discover_test_dir(root)
    if config is None:
        content = (
            "import { defineConfig, devices } from '@playwright/test';\n\n"
            "export default defineConfig({\n"
            f"  testDir: './{test_dir}',\n"
            "  fullyParallel: true,\n"
            "  forbidOnly: !!process.env.CI,\n"
            "  retries: process.env.CI ? 1 : 0,\n"
            "  workers: process.env.PW_WORKERS ? Number(process.env.PW_WORKERS) : undefined,\n"
            "  reporter: [['line'], ['html', { outputFolder: 'playwright-report', open: 'never' }]],\n"
            "  use: { baseURL: process.env.BASE_URL || process.env.TEST_BASE_URL, trace: 'retain-on-failure', screenshot: 'only-on-failure', video: 'retain-on-failure' },\n"
            "  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],\n"
            "});\n"
        )
        desired['playwright.config.ts'] = {'content': content, 'reason': 'Create a minimal typed Playwright configuration using the recursively discovered test directory.'}
    else:
        text = config.read_text(encoding='utf-8', errors='replace')
        if 'testDir' not in text and 'defineConfig' in text:
            updated = re.sub(r'defineConfig\(\s*\{', f"defineConfig({{\n  testDir: './{test_dir}',", text, count=1)
            rel = config.relative_to(root).as_posix()
            desired[rel] = {'content': updated, 'reason': 'Make the existing Playwright config explicitly point to the recursively discovered executable test root.'}
    return desired


def _diff_text(rel: str, before: str, after: str) -> str:
    return '\n'.join(difflib.unified_diff(before.splitlines(), after.splitlines(), fromfile=rel + ' (before)', tofile=rel + ' (after)', lineterm=''))


def build_safe_config_change_plan(framework_path: str | Path, analysis: dict[str, Any] | None = None, *, standard_profile: str = STANDARD_ID) -> dict[str, Any]:
    root = Path(framework_path).expanduser().resolve()
    analysis = analysis or analyze_playwright_gaps(root)
    desired = _desired_safe_contents(root, analysis)
    manifest_content = json.dumps(build_standard_manifest(root, analysis, standard_profile), indent=2, ensure_ascii=False) + '\n'
    manifest_path = root / MANIFEST_NAME
    manifest_before = manifest_path.read_text(encoding='utf-8', errors='replace') if manifest_path.exists() else ''
    if manifest_before != manifest_content:
        desired[MANIFEST_NAME] = {
            'content': manifest_content,
            'reason': 'Install/update AstraHeal\'s semantic Playwright role-map standard so diverse framework layouts remain explicit and fast for future AI walkthroughs without forcing folder moves.',
        }
    changes = []
    for rel, item in desired.items():
        path = root / rel
        before = path.read_text(encoding='utf-8', errors='replace') if path.exists() else ''
        after = str(item.get('content') or '')
        if before == after:
            continue
        changes.append({
            'file': rel,
            'operation': 'update' if path.exists() else 'create',
            'reason': item.get('reason') or 'Safe Playwright setup normalization.',
            'before_excerpt': before[:6000],
            'after_excerpt': after[:6000],
            'diff': _diff_text(rel, before, after)[:16000],
            'proposed_content': after,
            'risk': 'setup/configuration',
        })
    standard = audit_standard(root, analysis, profile_id=standard_profile)
    return {
        'ok': True,
        'stage': 'framework_change_proposal',
        'framework_path': str(root),
        'standard_profile': standard_profile,
        'standard_audit': standard,
        'changes': changes,
        'proposed_files': [x['file'] for x in changes],
        'proposed_file_count': len(changes),
        'required_validation_sequence': analysis.get('required_commands') or [],
        'framework_fingerprint': compute_framework_fingerprint(root).get('fingerprint'),
        'message': f'Prepared {len(changes)} exact safe setup change(s) for human review.' if changes else 'No deterministic setup file changes are required.',
    }


def apply_safe_config_fixes(framework_path: str | Path, analysis: dict[str, Any] | None = None, *, approved_files: Iterable[str] | None = None, standard_profile: str = STANDARD_ID) -> dict[str, Any]:
    root = Path(framework_path).expanduser().resolve()
    plan = build_safe_config_change_plan(root, analysis, standard_profile=standard_profile)
    approved = {str(x).replace('\\', '/').strip() for x in (approved_files or plan.get('proposed_files') or []) if str(x).strip()}
    changed: list[str] = []
    backups: list[str] = []
    blocked: list[str] = []
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    backup_root = root / '.qa-cache' / 'existing-framework' / 'backups' / f'setup-{stamp}'
    for change in plan.get('changes') or []:
        rel = str(change.get('file') or '').replace('\\', '/')
        if rel not in approved:
            blocked.append(f'{rel}: not included in human-approved file scope')
            continue
        target = (root / rel).resolve()
        try:
            target.relative_to(root)
        except Exception:
            blocked.append(f'{rel}: path escapes framework root')
            continue
        if target.exists():
            backup = backup_root / rel
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, backup)
            backups.append(str(backup))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(str(change.get('proposed_content') or ''), encoding='utf-8')
        changed.append(rel)
    return {
        'ok': True,
        'changed_files': changed,
        'backups': backups,
        'blocked': blocked,
        'applied_plan': [{k: v for k, v in x.items() if k != 'proposed_content'} for x in plan.get('changes') or [] if x.get('file') in changed],
        'message': 'Approved safe Playwright configuration fixes applied.' if changed else 'No approved deterministic configuration changes were applied.',
    }


def _snapshot_files(root: Path, names: Iterable[str]) -> dict[str, dict[str, Any] | None]:
    snap: dict[str, dict[str, Any] | None] = {}
    for rel in names:
        p = root / rel
        try:
            if p.exists():
                stat = p.stat()
                snap[rel] = {"bytes": p.read_bytes(), "atime_ns": int(stat.st_atime_ns), "mtime_ns": int(stat.st_mtime_ns)}
            else:
                snap[rel] = None
        except Exception:
            snap[rel] = None
    return snap


def _restore_snapshot(root: Path, snap: dict[str, dict[str, Any] | None], allowed: set[str]) -> tuple[list[dict[str, Any]], list[str]]:
    diffs: list[dict[str, Any]] = []
    restored: list[str] = []
    for rel, before_info in snap.items():
        p = root / rel
        before_bytes = before_info.get("bytes") if isinstance(before_info, dict) else None
        after_bytes = p.read_bytes() if p.exists() else None
        if after_bytes == before_bytes:
            continue
        before = (before_bytes or b'').decode('utf-8', errors='replace')
        after = (after_bytes or b'').decode('utf-8', errors='replace')
        diffs.append({'file': rel, 'operation': 'update' if before_bytes is not None else 'create', 'diff': _diff_text(rel, before, after)[:16000], 'before_excerpt': before[:5000], 'after_excerpt': after[:5000]})
        if rel not in allowed:
            if before_bytes is None:
                try:
                    p.unlink(missing_ok=True)
                except Exception:
                    pass
            else:
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(before_bytes)
                try:
                    os.utime(p, ns=(int(before_info.get("atime_ns") or 0), int(before_info.get("mtime_ns") or 0)))
                except Exception:
                    pass
            restored.append(rel)
    return diffs, restored


def run_required_commands(framework_path: str | Path, *, progress: Progress | None = None, stop_on_failure: bool = False, preserve_project_files: bool = False, allowed_project_changes: Iterable[str] | None = None) -> dict[str, Any]:
    root = Path(framework_path).expanduser().resolve()
    commands = [
        (['npm', 'config', 'set', 'registry', 'https://registry.npmjs.org/'], 15, 'Setting npm registry'),
        (['npm', 'install', '--registry=https://registry.npmjs.org/'], 35, 'Installing npm dependencies'),
        (['npx', 'playwright', 'install', 'chromium'], 60, 'Installing Playwright Chromium'),
        (['npm', 'run', 'build'], 82, 'Running TypeScript/build validation'),
    ]
    controlled_files = ['package.json', 'package-lock.json', 'npm-shrinkwrap.json', 'pnpm-lock.yaml', 'yarn.lock', '.npmrc']
    snapshot = _snapshot_files(root, controlled_files) if preserve_project_files else {}
    allowed = {str(x).replace('\\', '/') for x in (allowed_project_changes or [])}
    results = []
    env = {'npm_config_registry': 'https://registry.npmjs.org/', 'PLAYWRIGHT_HTML_OPEN': 'never'}
    for args, pct, title in commands:
        _emit(progress, 'playwright_doctor', pct, title, {'command': args})
        timeout = 1200 if 'install' in args else 300
        result = run_command(args, cwd=root, timeout=timeout, extra_env=env)
        item = {'ok': result.ok, 'command': result.command, 'return_code': result.returncode, 'stdout_tail': result.stdout[-12000:], 'stderr_tail': result.stderr[-12000:], 'error': result.error}
        results.append(item)
        _emit(progress, 'playwright_doctor', min(95, pct + 8), f"{title}: {'passed' if result.ok else 'failed'}", {'command': args, 'return_code': result.returncode})
        if not result.ok and stop_on_failure:
            break
    side_effect_diffs: list[dict[str, Any]] = []
    restored: list[str] = []
    if preserve_project_files:
        side_effect_diffs, restored = _restore_snapshot(root, snapshot, allowed)
    ok = all(r.get('ok') for r in results) and len(results) == len(commands)
    _emit(progress, 'playwright_doctor', 100, 'Playwright prerequisite command sequence completed.' if ok else 'Playwright command sequence completed with blockers.', {'ok': ok})
    return {
        'ok': ok,
        'framework_path': str(root),
        'commands': results,
        'source_side_effects_detected': side_effect_diffs,
        'source_side_effects_restored': restored,
        'preserved_unapproved_project_files': bool(preserve_project_files),
        'message': 'All requested Playwright commands passed.' if ok else 'One or more requested Playwright commands failed. Review exact stdout/stderr; no success is assumed.',
    }


def diagnose_and_prepare(
    framework_path: str | Path,
    *,
    apply_fixes: bool = False,
    run_commands: bool = True,
    progress: Progress | None = None,
    reuse_cached_validation: bool = False,
    preserve_command_source_changes: bool = False,
    approved_files: Iterable[str] | None = None,
    standard_profile: str = STANDARD_ID,
) -> dict[str, Any]:
    root = Path(framework_path).expanduser().resolve()
    analysis = analyze_playwright_gaps(root)
    _emit(progress, 'playwright_doctor', 8, analysis.get('message', 'Gap analysis completed.'), {'gap_count': analysis.get('gap_count')})
    proposal = build_safe_config_change_plan(root, analysis, standard_profile=standard_profile)
    fixes = {'ok': True, 'changed_files': [], 'message': 'Fix mode disabled.', 'proposal': proposal}
    if apply_fixes:
        fixes = apply_safe_config_fixes(root, analysis, approved_files=approved_files, standard_profile=standard_profile)
        _emit(progress, 'playwright_doctor', 12, fixes.get('message', 'Safe fixes completed.'), {'changed_files': fixes.get('changed_files')})
        analysis = analyze_playwright_gaps(root)

    commands = {'ok': True, 'commands': [], 'message': 'Command execution disabled.'}
    fp = compute_framework_fingerprint(root)
    if run_commands and analysis.get('is_playwright'):
        cached = None
        if reuse_cached_validation:
            cached = load_matching_cache(root, 'playwright-command-validation-cache.json', fingerprint=fp)
            deps_ready = (root / 'node_modules').exists() and ((root / 'node_modules' / '@playwright' / 'test').exists() or (root / 'node_modules' / 'playwright').exists())
            if cached and cached.get('ok') and deps_ready:
                commands = cached
                commands['cache_hit'] = True
                commands['message'] = 'Reused prior successful npm/Playwright setup validation because repository fingerprint and installed dependency markers are unchanged.'
                _emit(progress, 'playwright_doctor', 72, commands['message'], {'cache_hit': True})
            else:
                cached = None
        if not cached:
            commands = run_required_commands(root, progress=progress, preserve_project_files=preserve_command_source_changes, allowed_project_changes=approved_files)
            commands['cache_hit'] = False
            if commands.get('ok'):
                # Recompute after command run/restore so the cache keys the final visible project state.
                save_cache(root, 'playwright-command-validation-cache.json', commands, fingerprint=compute_framework_fingerprint(root))

    final_analysis = analyze_playwright_gaps(root)
    standard = audit_standard(root, final_analysis, profile_id=standard_profile)
    ok = bool(commands.get('ok') and final_analysis.get('critical_gap_count', 0) == 0)
    return {
        'ok': ok,
        'analysis_before': analysis,
        'safe_fixes': fixes,
        'change_proposal': proposal,
        'command_validation': commands,
        'analysis_after': final_analysis,
        'standard_audit': standard,
        'standard_profile': standard_profile,
        'message': 'Playwright framework preparation passed.' if ok else 'Playwright framework still has validated blockers. Review the gap, exact proposed changes, and command evidence before execution.',
    }
