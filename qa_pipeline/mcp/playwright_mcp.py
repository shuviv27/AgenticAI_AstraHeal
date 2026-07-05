from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from qa_pipeline.core.commands import resolve_command, run_command
from qa_pipeline.core.paths import GENERATED_PLAYWRIGHT_DIR, REPO_ROOT, REPORTS_DIR
from qa_pipeline.core.project_config import load_project_config
from qa_pipeline.core.url_guard import normalize_base_url

MCP_DIR = REPO_ROOT / 'mcp'
VSCODE_DIR = REPO_ROOT / '.vscode'


def _playwright_bin_exists() -> bool:
    if (GENERATED_PLAYWRIGHT_DIR / 'node_modules' / '@playwright' / 'test').exists():
        return True
    if (GENERATED_PLAYWRIGHT_DIR / 'node_modules' / '.bin' / 'playwright').exists():
        return True
    if (GENERATED_PLAYWRIGHT_DIR / 'node_modules' / '.bin' / 'playwright.cmd').exists():
        return True
    return False


def _write_fallback_playwright_html(title: str, details: dict[str, Any]) -> None:
    html_dir = REPORTS_DIR / 'html'
    html_dir.mkdir(parents=True, exist_ok=True)
    body = json.dumps(details, indent=2, ensure_ascii=False)
    (html_dir / 'index.html').write_text(f"""<!doctype html>
<html><head><meta charset=\"utf-8\"/><title>{title}</title>
<style>body{{font-family:Arial,sans-serif;margin:24px;background:#f8fafc;color:#111827}}.card{{background:white;border:1px solid #dbe3ef;border-radius:12px;padding:18px;margin:14px 0;box-shadow:0 1px 2px #0001}}pre{{white-space:pre-wrap;background:#111827;color:#d1fae5;padding:16px;border-radius:10px;overflow:auto}}.badge{{display:inline-block;padding:4px 9px;border-radius:999px;background:#fee2e2;color:#991b1b;font-weight:700}}</style></head><body>
<h1>{title}</h1><div class=\"card\"><span class=\"badge\">Fallback execution report</span><p>The native Playwright report was not generated, so the pipeline created this readable fallback report.</p></div><div class=\"card\"><pre>{body}</pre></div></body></html>""", encoding='utf-8')


def _ensure_playwright_runtime(auto_install: bool = True) -> dict[str, Any]:
    status: dict[str, Any] = {
        'ok': False,
        'stage': 'playwright_runtime_preflight',
        'generated_playwright_dir': str(GENERATED_PLAYWRIGHT_DIR),
        'auto_install': auto_install,
        'npm_available': bool(resolve_command('npm')),
        'npx_available': bool(resolve_command('npx')),
        'installed_before': _playwright_bin_exists(),
        'steps': [],
    }
    if not status['npm_available']:
        status['error'] = 'npm not found. Install Node.js LTS with npm and reopen the terminal/GUI.'
        _write_fallback_playwright_html('Playwright runtime preflight failed', status)
        return status
    if not status['npx_available']:
        status['error'] = 'npx not found. Install Node.js LTS with npm/npx and reopen the terminal/GUI.'
        _write_fallback_playwright_html('Playwright runtime preflight failed', status)
        return status
    if not (GENERATED_PLAYWRIGHT_DIR / 'package.json').exists():
        status['error'] = 'generated-playwright/package.json not found.'
        _write_fallback_playwright_html('Playwright runtime preflight failed', status)
        return status
    if not _playwright_bin_exists():
        if not auto_install:
            status['error'] = 'Playwright dependencies missing. Run npm install inside generated-playwright.'
            _write_fallback_playwright_html('Playwright runtime preflight failed', status)
            return status
        install = run_command(['npm', 'install', '--registry=https://registry.npmjs.org/'], cwd=GENERATED_PLAYWRIGHT_DIR, timeout=1200)
        status['steps'].append({'name': 'npm_install', 'ok': install.ok, 'returncode': install.returncode, 'command': install.command, 'stdout': install.stdout[-4000:], 'stderr': install.stderr[-4000:], 'error': install.error})
        if not install.ok:
            status['error'] = 'npm install failed. Playwright cannot execute until dependencies are installed.'
            _write_fallback_playwright_html('Playwright runtime preflight failed', status)
            return status
    version = run_command(['npx', '--no-install', 'playwright', '--version'], cwd=GENERATED_PLAYWRIGHT_DIR, timeout=60)
    status['steps'].append({'name': 'playwright_cli_version', 'ok': version.ok, 'returncode': version.returncode, 'command': version.command, 'stdout': version.stdout[-1000:], 'stderr': version.stderr[-1000:], 'error': version.error})
    if not version.ok:
        status['error'] = 'Playwright CLI is unavailable after dependency check.'
        _write_fallback_playwright_html('Playwright runtime preflight failed', status)
        return status
    browser = run_command(['npx', '--no-install', 'playwright', 'install', 'chromium'], cwd=GENERATED_PLAYWRIGHT_DIR, timeout=900)
    status['steps'].append({'name': 'playwright_install_chromium', 'ok': browser.ok, 'returncode': browser.returncode, 'command': browser.command, 'stdout': browser.stdout[-3000:], 'stderr': browser.stderr[-3000:], 'error': browser.error})
    status['chromium_install_ok_or_already_present'] = browser.ok
    status['installed_after'] = _playwright_bin_exists()
    status['ok'] = True
    return status



def playwright_mcp_config(headless: bool = True) -> dict[str, Any]:
    args = ['@playwright/mcp@latest']
    if headless:
        args.append('--headless')
    return {
        'mcpServers': {
            'playwright': {
                'command': 'npx',
                'args': args,
            }
        }
    }


def write_playwright_mcp_configs(headless: bool = True) -> dict[str, str]:
    MCP_DIR.mkdir(parents=True, exist_ok=True)
    VSCODE_DIR.mkdir(parents=True, exist_ok=True)
    config = playwright_mcp_config(headless=headless)
    mcp_file = MCP_DIR / 'playwright-mcp.json'
    vscode_file = VSCODE_DIR / 'mcp.json'
    mcp_file.write_text(json.dumps(config, indent=2) + '\n', encoding='utf-8')
    vscode_file.write_text(json.dumps(config, indent=2) + '\n', encoding='utf-8')
    return {
        'mcp_config': str(mcp_file.relative_to(REPO_ROOT)),
        'vscode_mcp_config': str(vscode_file.relative_to(REPO_ROOT)),
    }


def _truthy_env(name: str, default: str = 'false') -> bool:
    return os.getenv(name, default).strip().lower() in {'1', 'true', 'yes', 'y', 'on'}


def mcp_status(headless: bool | None = None, probe_server: bool | None = None, probe_timeout: int | None = None) -> dict[str, Any]:
    """Return Playwright MCP readiness without blocking the GUI by default.

    Older builds ran `npx @playwright/mcp@latest --help` every time MCP assist was
    prepared. On locked-down VMs this can wait on npm/proxy/TLS resolution and make
    the GUI look stuck. The default now writes config and checks npm/npx only.
    Run the live probe only when explicitly requested by environment or API.
    """
    if headless is None:
        headless = os.getenv('PLAYWRIGHT_MCP_HEADLESS', 'true').lower() != 'false'
    if probe_server is None:
        probe_server = _truthy_env('AIQA_MCP_LIVE_PROBE', 'false')
    if probe_timeout is None:
        try:
            probe_timeout = int(os.getenv('AIQA_MCP_LIVE_PROBE_TIMEOUT_SECONDS', '60'))
        except Exception:
            probe_timeout = 60
    probe_timeout = max(10, min(int(probe_timeout), 180))

    files = write_playwright_mcp_configs(headless=headless)
    npx = resolve_command('npx')
    npm = resolve_command('npm')
    status: dict[str, Any] = {
        'npx_available': bool(npx),
        'npm_available': bool(npm),
        'config_files': files,
        'mcp_server_command': 'npx @playwright/mcp@latest' + (' --headless' if headless else ''),
        'live_probe_requested': bool(probe_server),
        'live_probe_timeout_seconds': probe_timeout if probe_server else 0,
        'execution_note': 'MCP config is prepared for AI/browser-assist. Playwright Test remains the deterministic runner for repeatable reports, screenshots, videos and CI.',
        'notes': [
            'Playwright MCP is a browser automation server for AI agents/IDEs.',
            'This repo writes MCP config and verifies prerequisites before execution.',
            'By default the GUI skips the live `npx @playwright/mcp@latest --help` probe to avoid long waits on slow/corporate VMs.',
            'To run the live probe, set AIQA_MCP_LIVE_PROBE=true or call the explicit MCP live-probe endpoint.',
        ],
    }
    if not npx:
        status.update({
            'mcp_probe_ok': False,
            'probe_skipped': False,
            'probe_error': 'npx not found. Install Node.js LTS and reopen terminal.',
        })
        return status

    if not probe_server:
        status.update({
            'mcp_probe_ok': None,
            'probe_skipped': True,
            'probe_error': '',
            'probe_message': 'Live MCP package probe skipped to keep GUI responsive on VMs. npm/npx exists and config files were written.',
        })
        return status

    probe = run_command(['npx', '@playwright/mcp@latest', '--help'], cwd=REPO_ROOT, timeout=probe_timeout)
    status.update({
        'mcp_probe_ok': probe.ok or probe.returncode == 0,
        'probe_skipped': False,
        'probe_command': probe.command,
        'probe_stdout': probe.stdout[-2000:],
        'probe_stderr': probe.stderr[-2000:],
        'probe_error': probe.error,
    })
    return status


def run_playwright_test(feature: str = 'login', project: str = 'chromium', use_mcp_context: bool = True, headed: bool = False, base_url: str = '') -> dict[str, Any]:
    """Run generated Playwright test and record MCP readiness in the same report.

    Microsoft Playwright MCP is included for AI/browser-assist readiness. Test execution is
    still performed by Playwright Test because it creates deterministic HTML/JSON reports,
    screenshots, traces, and videos suitable for CI and governance.
    """
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    mcp = mcp_status(headless=not headed) if use_mcp_context else {'enabled': False}
    spec = GENERATED_PLAYWRIGHT_DIR / 'tests' / 'generated' / f'{feature}.spec.ts'
    if not spec.exists():
        available = sorted(str(p.relative_to(GENERATED_PLAYWRIGHT_DIR)) for p in (GENERATED_PLAYWRIGHT_DIR / 'tests' / 'generated').glob('*.spec.ts')) if (GENERATED_PLAYWRIGHT_DIR / 'tests' / 'generated').exists() else []
        return {
            'ok': False,
            'error': (
                f"Generated spec not found for feature '{feature}'. Expected: {spec}. "
                "Generate Reusable Playwright for this feature first, or use the GUI Execute button which can now auto-generate the missing spec when testcase JSON exists."
            ),
            'expected_spec': str(spec),
            'available_specs': available,
            'mcp': mcp,
        }
    runtime = _ensure_playwright_runtime(auto_install=True)
    if not runtime.get('ok'):
        return {'ok': False, 'stage': 'playwright_runtime_preflight_failed', 'error': runtime.get('error', 'Playwright runtime preflight failed.'), 'runtime_preflight': runtime, 'mcp': mcp}
    args = ['npx', '--no-install', 'playwright', 'test', f'tests/generated/{feature}.spec.ts', f'--project={project}']
    if headed:
        args.append('--headed')
    effective_base_url = normalize_base_url(base_url or load_project_config().get('base_url', ''))
    env = {}
    if effective_base_url:
        env['BASE_URL'] = effective_base_url
        env['TEST_BASE_URL'] = effective_base_url
    env['PLAYWRIGHT_MCP_ENABLED'] = 'true' if use_mcp_context else 'false'
    env['PLAYWRIGHT_MCP_HEADLESS'] = 'false' if headed else 'true'
    proc = run_command(args, cwd=GENERATED_PLAYWRIGHT_DIR, timeout=900, extra_env=env)
    if not proc.ok:
        _write_fallback_playwright_html('Playwright execution completed with issue', {'command': proc.command, 'returncode': proc.returncode, 'stdout': proc.stdout[-8000:], 'stderr': proc.stderr[-8000:], 'error': proc.error, 'runtime_preflight': runtime})
    report = {
        'ok': proc.ok,
        'mode': 'headed' if headed else 'headless',
        'base_url': effective_base_url,
        'command': proc.command,
        'returncode': proc.returncode,
        'stdout': proc.stdout[-12000:],
        'stderr': proc.stderr[-12000:],
        'error': proc.error,
        'runtime_preflight': runtime,
        'mcp': mcp,
        'native_playwright_report': 'generated-playwright/reports/html/index.html',
        'enterprise_html_report': 'generated-playwright/reports/enterprise/enterprise-report.html',
        'failure_artifacts_note': 'Screenshots, videos and traces are retained on failure by playwright.config.ts.',
    }
    out = REPORTS_DIR / 'playwright-mcp-execution.json'
    out.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    return report
