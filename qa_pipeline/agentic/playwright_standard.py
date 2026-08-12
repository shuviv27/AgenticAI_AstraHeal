from __future__ import annotations

import json
from pathlib import Path
from typing import Any

STANDARD_ID = 'astraheal-adaptive-enterprise-v1'
STRICT_ID = 'astraheal-strict-src-v1'
MANIFEST_NAME = '.astraheal-playwright-standard.json'


def get_playwright_standards() -> dict[str, Any]:
    return {
        'default': STANDARD_ID,
        'profiles': [
            {
                'id': STANDARD_ID,
                'name': 'AstraHeal Adaptive Enterprise Playwright Standard',
                'recommended': True,
                'description': 'Preserves valid existing architecture while requiring discoverable tests, reusable layers, explicit setup/build commands, and auditable human-approved writes.',
                'physical_layout_policy': 'adaptive',
                'allowed_layout_examples': ['tests/pages/fixtures at repository root', 'src/main + src/test enterprise layout', 'BDD/feature + step-definition hybrid', 'workspace/monorepo layout'],
            },
            {
                'id': STRICT_ID,
                'name': 'AstraHeal Strict src/main + src/test Standard',
                'recommended': False,
                'description': 'Target structure for teams that explicitly choose migration. Bulk moves are never performed implicitly; a file-by-file migration proposal and approval are required.',
                'physical_layout_policy': 'strict_proposal_only',
                'target_layout': {
                    'pages': 'src/main/pages', 'config': 'src/main/config', 'ui_base': 'src/main/ui_base',
                    'specs': 'src/test/specs', 'fixtures': 'src/test/resources/fixtures', 'test_data': 'src/test/resources/testData',
                },
            },
        ],
        'mandatory_rules': [
            f'{MANIFEST_NAME} records the discovered semantic role map so future AI walkthroughs do not depend on one hard-coded folder layout.',
            'package.json is valid and declares Playwright plus TypeScript dependencies.',
            'npm run build exists and is a non-destructive type/build validation command; workspace/monorepo repositories validate both workspace packages and root Playwright TypeScript.',
            'Dependencies needed by root compiler-scoped Playwright sources are declared at the root package boundary; AstraHeal reuses versions already evidenced by package-lock/workspaces before proposing public-registry guesses.',
            'Playwright config is discoverable and points to executable tests without forcing tests into a fixed root folder.',
            'tsconfig/jsconfig path aliases are explicit and resolvable for the discovered architecture.',
            'Generated/dependency/report/cache folders are excluded from framework learning.',
            'Existing locators/page methods/helpers are reused before new members are created.',
            'AstraHeal writes only after a human reviews the exact proposed file/content scope.',
            'Every applied framework setup change is backed up, logged, validated, and reportable.',
        ],
        'required_validation_sequence': [
            'npm config set registry https://registry.npmjs.org/',
            'npm install --registry=https://registry.npmjs.org/',
            'npx playwright install chromium',
            'npm run build',
        ],
    }


def build_standard_manifest(framework_path: str | Path, analysis: dict[str, Any], profile_id: str = STANDARD_ID) -> dict[str, Any]:
    """Create a deterministic semantic role-map for diverse Playwright layouts.

    The manifest standardizes how AstraHeal *understands* a repository without
    forcing a valid client framework into one physical folder convention.
    """
    root = Path(framework_path).expanduser().resolve()

    def dirs(candidates: list[str]) -> list[str]:
        return [rel for rel in candidates if (root / rel).exists()]

    package: dict[str, Any] = {}
    try:
        package = json.loads((root / 'package.json').read_text(encoding='utf-8', errors='replace'))
    except Exception:
        pass
    workspaces = package.get('workspaces') or [] if isinstance(package, dict) else []
    if isinstance(workspaces, dict):
        workspaces = workspaces.get('packages') or []
    test_dir = str(analysis.get('discovered_test_dir') or '').replace('\\', '/')
    return {
        'schema_version': 1,
        'standard_profile': profile_id,
        'standard_name': next((p['name'] for p in get_playwright_standards()['profiles'] if p['id'] == profile_id), profile_id),
        'physical_layout_policy': 'preserve-discovered-layout' if profile_id == STANDARD_ID else 'canonical-src-target-with-explicit-migration-approval',
        'role_map': {
            'executable_test_roots': [test_dir] if test_dir else [],
            'page_roots': dirs(['pages', 'pageObjects', 'pageobjects', 'page-objects', 'src/main/pages', 'src/main/pageObjects', 'src/pages']),
            'fixture_roots': dirs(['fixtures', 'src/test/fixtures', 'src/test/resources/fixtures', 'tests/fixtures']),
            'config_roots': dirs(['config', 'configs', 'src/main/config', 'src/config']),
            'helper_roots': dirs(['utils', 'helpers', 'src/main/ui_base', 'src/main/utils', 'src/test/resources/helpers']),
            'bdd_feature_roots': dirs(['features', 'src/test/features', 'tests/features']),
            'bdd_step_roots': dirs(['step-definitions', 'src/step-definitions', 'src/test/step-definitions', 'tests/step-definitions']),
            'workspace_patterns': [str(x) for x in workspaces] if isinstance(workspaces, list) else [],
        },
        'required_validation_sequence': get_playwright_standards()['required_validation_sequence'],
        'build_contract': {
            'workspace_aware': bool((analysis.get('package_requirements') or {}).get('workspace_aware')),
            'recommended_build_script': (analysis.get('package_requirements') or {}).get('recommended_build_script') or 'tsc --noEmit',
            'build_strategy': (analysis.get('package_requirements') or {}).get('build_strategy') or 'root-typescript-no-emit',
            'workspace_typecheck_paths': (analysis.get('package_requirements') or {}).get('workspace_typecheck_paths') or [],
        },
        'write_policy': 'exact-file-human-approval-required',
        'reuse_policy': 'existing locator/page/helper first; create only when no suitable reusable member exists',
    }


def audit_standard(framework_path: str | Path, analysis: dict[str, Any], structure: dict[str, Any] | None = None, profile_id: str = STANDARD_ID) -> dict[str, Any]:
    root = Path(framework_path).expanduser().resolve()
    structure = structure or {}
    package = {}
    try:
        package = json.loads((root / 'package.json').read_text(encoding='utf-8', errors='replace'))
    except Exception:
        pass
    scripts = package.get('scripts') or {} if isinstance(package, dict) else {}
    executable = structure.get('executable_specs') or []
    test_roots = structure.get('discovered_test_roots') or ([analysis.get('discovered_test_dir')] if analysis.get('discovered_test_dir') else [])
    roles = structure.get('component_directory_model') or {}
    issues: list[dict[str, Any]] = []
    if not scripts.get('build'):
        issues.append({'rule': 'build_script', 'severity': 'high', 'file': 'package.json', 'message': 'npm run build is required by the AstraHeal validation contract.'})
    for gap in analysis.get('gaps') or []:
        if gap.get('code') == 'required_dependency_missing':
            issues.append({
                'rule': 'compiler_dependency',
                'severity': 'high',
                'file': 'package.json',
                'message': f"Root compiler-scoped source requires {gap.get('dependency')}; AstraHeal can propose the repository-evidenced version {gap.get('recommended_version') or 'for review'}.",
            })
        elif gap.get('code') == 'external_dependency_unresolved':
            issues.append({
                'rule': 'unresolved_compiler_dependency',
                'severity': 'high',
                'file': 'package.json',
                'message': f"Root compiler-scoped source imports {gap.get('dependency')}, but no trusted package-lock/workspace version was found. Do not guess a dependency version silently.",
            })
    if not executable and not analysis.get('discovered_test_dir'):
        issues.append({'rule': 'test_discovery', 'severity': 'critical', 'file': analysis.get('playwright_config') or 'playwright.config.ts', 'message': 'Executable Playwright tests are not discoverable.'})
    if analysis.get('critical_gap_count', 0):
        issues.append({'rule': 'playwright_setup', 'severity': 'critical', 'file': 'setup', 'message': f"{analysis.get('critical_gap_count')} critical Playwright setup gap(s) remain."})
    if profile_id == STRICT_ID:
        target = get_playwright_standards()['profiles'][1]['target_layout']
        current_paths = set(str(x).replace('\\', '/') for x in (test_roots or []))
        if target['specs'] not in current_paths:
            issues.append({'rule': 'strict_specs_path', 'severity': 'advisory', 'file': target['specs'], 'message': 'Strict profile would migrate executable specs to src/test/specs. Migration is proposal-only until explicitly approved.'})
    if not (root / MANIFEST_NAME).exists():
        issues.append({'rule': 'standard_manifest', 'severity': 'advisory', 'file': MANIFEST_NAME, 'message': 'Standard role-map manifest is not installed yet. AstraHeal can propose it for explicit human approval without moving valid framework folders.'})
    return {
        'ok': not any(x.get('severity') == 'critical' for x in issues),
        'profile_id': profile_id,
        'standard': get_playwright_standards(),
        'issues': issues,
        'issue_count': len(issues),
        'architecture_policy': 'Preserve discovered architecture' if profile_id == STANDARD_ID else 'Prepare strict migration proposal; do not bulk-move without exact approval.',
        'detected_test_roots': test_roots,
        'detected_component_model': roles,
        'message': 'Framework is compatible with the adaptive AstraHeal standard.' if not issues else f'Framework standard audit found {len(issues)} item(s) to review.',
    }
