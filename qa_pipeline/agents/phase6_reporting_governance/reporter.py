from __future__ import annotations

import html
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from qa_pipeline.core.paths import GENERATED_PLAYWRIGHT_DIR, REPORTS_DIR, TESTCASES_DIR, REPO_ROOT, ensure_dirs
from qa_pipeline.core.runtime_logger import write_runtime_summary, read_events


def _rel(path: Path, base: Path = REPO_ROOT) -> str:
    try:
        return str(path.relative_to(base)).replace('\\', '/')
    except Exception:
        return str(path).replace('\\', '/')


def _read_json(path: Path) -> dict[str, Any] | list[Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return None


def generate_summary() -> Path:
    ensure_dirs()
    specs = sorted((GENERATED_PLAYWRIGHT_DIR / 'tests' / 'generated').glob('*.spec.ts'))
    pages = sorted((GENERATED_PLAYWRIGHT_DIR / 'pages').glob('*Page.ts'))
    objects = sorted((GENERATED_PLAYWRIGHT_DIR / 'pageObjects').glob('*Page.objects.ts'))
    testcases = sorted(TESTCASES_DIR.glob('**/*.scenarios.json'))
    out = REPORTS_DIR / 'enterprise-summary.md'
    lines = [
        '# Enterprise QA Pipeline Summary',
        '',
        '## Artifact counts',
        '',
        f'- Functional testcase files: {len(testcases)}',
        f'- Page object files: {len(objects)}',
        f'- Page class files: {len(pages)}',
        f'- Generated spec files: {len(specs)}',
        '',
        '## Generated specs',
        '',
    ]
    for spec in specs:
        lines.append(f'- `{spec.relative_to(GENERATED_PLAYWRIGHT_DIR)}`')
    lines.extend(['', '## Traceability', '', 'Functional testcases are stored under `testcases/` and generated automation stays under `generated-playwright/`.'])
    out.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return out


def _flatten_playwright_tests(results: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not isinstance(results, dict):
        return rows

    def walk_suite(suite: dict[str, Any], parents: list[str]) -> None:
        title = suite.get('title') or ''
        chain = parents + ([title] if title else [])
        for spec in suite.get('specs', []) or []:
            spec_title = spec.get('title') or ''
            for test in spec.get('tests', []) or []:
                for result in test.get('results', []) or []:
                    attachments = []
                    for a in result.get('attachments', []) or []:
                        path = a.get('path')
                        if path:
                            p = Path(path)
                            if not p.is_absolute():
                                p = GENERATED_PLAYWRIGHT_DIR / p
                            attachments.append({'name': a.get('name','artifact'), 'path': _rel(p, GENERATED_PLAYWRIGHT_DIR), 'contentType': a.get('contentType','')})
                    rows.append({
                        'title': ' > '.join([x for x in chain + [spec_title] if x]),
                        'status': result.get('status') or test.get('status') or spec.get('ok'),
                        'duration': result.get('duration', 0),
                        'errors': result.get('errors') or [],
                        'attachments': attachments,
                    })
        for child in suite.get('suites', []) or []:
            walk_suite(child, chain)
    for suite in results.get('suites', []) or []:
        walk_suite(suite, [])
    return rows


def _artifact_links() -> list[dict[str, str]]:
    exts = {'.png': 'Screenshot', '.webm': 'Video', '.zip': 'Trace', '.json': 'JSON'}
    artifacts: list[dict[str, str]] = []
    roots = [GENERATED_PLAYWRIGHT_DIR / 'test-results', GENERATED_PLAYWRIGHT_DIR / 'reports']
    for root in roots:
        if not root.exists():
            continue
        for p in root.rglob('*'):
            if p.is_file() and p.suffix.lower() in exts:
                # Avoid huge node internals; reports/results.json remains useful.
                artifacts.append({'kind': exts[p.suffix.lower()], 'name': p.name, 'path': _rel(p, GENERATED_PLAYWRIGHT_DIR)})
    return artifacts[:100]



def _friendly_error_message(errors: Any) -> str:
    raw = json.dumps(errors, ensure_ascii=False) if errors else ''
    low = raw.lower()
    if 'user friendly failure' in low:
        # Keep the clean message thrown by BasePage.
        m = raw.split('User friendly failure:', 1)
        return 'User friendly failure: ' + m[1].split('\\n', 1)[0].split('"', 1)[0][:600] if len(m) > 1 else raw[:600]
    if 'timeout' in low and ('tobevisible' in low or 'locator' in low):
        return 'The test could not find the expected text/button in time. The app may have loaded the wrong URL, the text changed, the element is hidden behind an overlay, or a stronger locator is required. Try RCA & Self-Healing to crawl the page and propose a locator/page-method fix.'
    if 'net::err' in low or 'navigation' in low:
        return 'The browser could not navigate correctly. Check the application URL, network/VPN, redirects, and whether the page opens manually.'
    if 'strict mode violation' in low:
        return 'The locator matched multiple elements. The framework needs a more specific reusable locator or page method.'
    if 'permission' in low or 'geolocation' in low:
        return 'The page requested a browser permission. The framework will try to grant supported permissions automatically.'
    if raw:
        return raw[:600]
    return ''


def generate_enterprise_html_report() -> Path:
    ensure_dirs()
    generate_summary()
    report_dir = REPORTS_DIR / 'enterprise'
    report_dir.mkdir(parents=True, exist_ok=True)
    out = report_dir / 'enterprise-report.html'

    quality = _read_json(REPORTS_DIR / 'quality-review.json') or {}
    execution = _read_json(REPORTS_DIR / 'playwright-mcp-execution.json') or {}
    root_cause = _read_json(REPORTS_DIR / 'root-cause-report.json') or {}
    self_healing = _read_json(REPORTS_DIR / 'self-healing-report.json') or {}
    results = _read_json(REPORTS_DIR / 'results.json') or {}
    dynamic_dom = _read_json(REPORTS_DIR / 'dynamic-dom-map.json') or {}
    reuse_md = (REPORTS_DIR / 'reuse-decision-report.md').read_text(encoding='utf-8') if (REPORTS_DIR / 'reuse-decision-report.md').exists() else ''
    specs = sorted((GENERATED_PLAYWRIGHT_DIR / 'tests' / 'generated').glob('*.spec.ts'))
    testcases = sorted(TESTCASES_DIR.glob('**/*.scenarios.json'))
    test_rows = _flatten_playwright_tests(results)
    artifacts = _artifact_links()
    runtime_summary = write_runtime_summary()
    runtime_events = read_events(40)

    def status_badge(ok: Any) -> str:
        if ok is True:
            return '<span class="ok">PASS</span>'
        if ok is False:
            return '<span class="bad">FAIL</span>'
        return '<span class="warn">NOT RUN</span>'

    checks_html = ''
    for c in quality.get('checks', []) if isinstance(quality, dict) else []:
        checks_html += f"<tr><td>{html.escape(str(c.get('name','')))}</td><td>{status_badge(c.get('ok'))}</td><td><code>{html.escape(str(c.get('reason') or c.get('error') or c.get('hits') or ''))}</code></td></tr>"

    tests_html = ''
    for i, row in enumerate(test_rows, 1):
        err = ''
        if row.get('errors'):
            friendly = _friendly_error_message(row.get('errors'))
            err = '<div class="warn">Simple explanation: ' + html.escape(friendly) + '</div>'
            err += '<details><summary>Technical error details</summary><pre>' + html.escape(json.dumps(row['errors'], indent=2)[:4000]) + '</pre></details>'
        atts = ''
        for a in row.get('attachments', []):
            href = '/artifacts/' + html.escape(a['path'])
            atts += f'<a class="link" href="{href}" target="_blank">{html.escape(a.get("name","artifact"))}</a> '
        tests_html += f"<tr><td>{i}</td><td>{html.escape(row.get('title',''))}</td><td>{html.escape(str(row.get('status','')))}</td><td>{row.get('duration',0)} ms</td><td>{atts}{err}</td></tr>"
    if not tests_html:
        tests_html = '<tr><td colspan="5">No Playwright JSON results found yet. Run Execute Generated Test to populate this section.</td></tr>'

    artifacts_html = ''
    for a in artifacts:
        href = '/artifacts/' + html.escape(a['path'])
        artifacts_html += f'<li><b>{html.escape(a["kind"])}</b> - <a href="{href}" target="_blank">{html.escape(a["path"])}</a></li>'
    if not artifacts_html:
        artifacts_html = '<li>No screenshots/videos/traces found yet. They appear after Playwright execution, especially on failure.</li>'

    runtime_rows = ''
    for e in runtime_events[-30:]:
        runtime_rows += f"<tr><td>{html.escape(str(e.get('ts','')))}</td><td>{html.escape(str(e.get('stage','')))}</td><td>{html.escape(str(e.get('status','')))}</td><td>{html.escape(str(e.get('progress','')))}</td><td>{html.escape(str(e.get('feature','')))}</td><td>{html.escape(str(e.get('message','')))}</td></tr>"
    if not runtime_rows:
        runtime_rows = '<tr><td colspan="6">No runtime events yet.</td></tr>'
    runtime_suggestions = ''.join(f"<li>{html.escape(str(x))}</li>" for x in runtime_summary.get('self_learning_suggestions', [])) or '<li>No self-learning suggestions yet.</li>'

    spec_links = ''.join(f'<li><code>{html.escape(_rel(p, GENERATED_PLAYWRIGHT_DIR))}</code></li>' for p in specs) or '<li>No generated specs yet.</li>'
    testcase_links = ''.join(f'<li><code>{html.escape(_rel(p, REPO_ROOT))}</code></li>' for p in testcases) or '<li>No functional testcase files yet.</li>'
    play_report_link = '/artifacts/reports/html/index.html'
    dom_summary = dynamic_dom.get('summary', {}) if isinstance(dynamic_dom, dict) else {}
    dom_html = '<p>No dynamic crawl report yet. Click Generate Reusable Playwright to crawl the website before generation.</p>'
    if dom_summary:
        dom_html = '<ul>' + ''.join(f'<li><b>{html.escape(str(k))}</b>: {html.escape(str(v))}</li>' for k, v in dom_summary.items()) + '</ul>'
        dom_html += '<p><a href="/artifacts/reports/dynamic-dom-map.json" target="_blank">Open dynamic DOM map JSON</a> | <a href="/artifacts/reports/' + html.escape(str(dynamic_dom.get('feature', 'feature'))) + '-full-page.png" target="_blank">Open full-page screenshot</a></p>'

    html_text = f'''<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Enterprise AI QA Pipeline Report</title>
<style>
body{{font-family:Segoe UI,Arial,sans-serif;background:#f8fafc;color:#172033;margin:0;padding:24px}}.wrap{{max-width:1280px;margin:auto}}.hero{{background:linear-gradient(135deg,#0f172a,#2563eb);color:white;border-radius:24px;padding:26px;margin-bottom:18px}}.grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:14px}}.card{{background:white;border:1px solid #e2e8f0;border-radius:18px;padding:18px;margin:14px 0;box-shadow:0 8px 24px rgba(15,23,42,.06)}}.metric{{font-size:30px;font-weight:900}}.ok{{color:#16a34a;font-weight:900}}.bad{{color:#dc2626;font-weight:900}}.warn{{color:#d97706;font-weight:900}}table{{width:100%;border-collapse:collapse}}th,td{{border-bottom:1px solid #e2e8f0;text-align:left;padding:10px;vertical-align:top}}th{{background:#eff6ff}}code,pre{{background:#0f172a;color:#dbeafe;border-radius:10px;padding:8px;display:block;white-space:pre-wrap;overflow:auto}}a.link,a{{color:#2563eb;font-weight:700}}.phase{{display:flex;gap:8px;flex-wrap:wrap}}.phase span{{background:#eff6ff;border:1px solid #dbeafe;border-radius:999px;padding:8px 12px;font-weight:800;color:#1e40af}}@media(max-width:900px){{.grid{{grid-template-columns:1fr}}}}
</style></head><body><div class="wrap">
<div class="hero"><h1>Enterprise AI QA Pipeline Report</h1><p>Functional testcases → reusable Playwright → static review → MCP-ready execution → failure artifacts.</p><p>Generated: {html.escape(datetime.now().strftime('%Y-%m-%d %H:%M:%S'))}</p></div>
<div class="grid">
<div class="card"><div class="metric">{len(testcases)}</div><b>Functional testcase files</b></div>
<div class="card"><div class="metric">{len(specs)}</div><b>Generated specs</b></div>
<div class="card"><div class="metric">{status_badge(quality.get('ok') if isinstance(quality, dict) else None)}</div><b>Static review</b></div>
<div class="card"><div class="metric">{status_badge(execution.get('ok') if isinstance(execution, dict) else None)}</div><b>Latest execution</b></div>
</div>
<div class="card"><h2>Phase-wise execution summary</h2><div class="phase"><span>Phase 1: prerequisites/runtime</span><span>Phase 2: functional testcases</span><span>Phase 3: reusable Playwright</span><span>Phase 4: review/execution</span><span>Phase 5: failure evidence/self-healing input</span><span>Phase 6: reporting/governance</span></div></div>
<div class="card"><h2>Functional testcase artifacts</h2><ul>{testcase_links}</ul></div>
<div class="card"><h2>Generated Playwright artifacts</h2><ul>{spec_links}</ul><p><a href="{play_report_link}" target="_blank">Open native Playwright HTML report</a> after execution.</p></div>
<div class="card"><h2>Dynamic DOM crawl before Playwright generation</h2>{dom_html}<p>This crawl scrolls the full page, captures visible links/buttons/headings, and stores a screenshot so AI and guardrails can handle dynamic/non-standard components better.</p></div>
<div class="card"><h2>Runtime logs, progress and self-learning suggestions</h2><p>Prometheus scrapes <code>/metrics</code>; Grafana dashboard <b>AI QA Pipeline Runtime Progress</b> shows the same runtime status.</p><table><tr><th>Time</th><th>Stage</th><th>Status</th><th>Progress</th><th>Feature</th><th>Message</th></tr>{runtime_rows}</table><h3>Self-learning suggestions from log history</h3><ul>{runtime_suggestions}</ul><p><a href="/artifacts/reports/runtime-summary.json" target="_blank">Open runtime-summary.json</a> | <a href="/artifacts/reports/runtime-summary.md" target="_blank">Open runtime-summary.md</a></p></div>
<div class="card"><h2>Static review checks</h2><table><tr><th>Check</th><th>Status</th><th>Details</th></tr>{checks_html or '<tr><td colspan="3">Static review not run yet.</td></tr>'}</table></div>
<div class="card"><h2>Step-by-step Playwright execution results</h2><table><tr><th>#</th><th>Test</th><th>Status</th><th>Duration</th><th>Failure evidence / attachments</th></tr>{tests_html}</table></div>
<div class="card"><h2>Screenshots, videos, traces, and JSON artifacts</h2><ul>{artifacts_html}</ul><p>Playwright is configured with <b>screenshot: only-on-failure</b>, <b>video: retain-on-failure</b>, and <b>trace: retain-on-failure</b>.</p></div>
<div class="card"><h2>Reuse and self-healing input</h2><p>The reuse report identifies whether locators and page methods were reused or created. Failure artifacts become the input for Phase 5 failure classification and self-healing.</p><pre>{html.escape(reuse_md[-8000:] if reuse_md else 'No reuse report yet.')}</pre></div>
<div class="card"><h2>Phase 5 Root Cause Analysis</h2><p>RCA classifies failures such as wrong URL, locator unavailable, clickability/scrolling, sync/navigation, permission, and environment issues.</p><pre>{html.escape(json.dumps(root_cause, indent=2, ensure_ascii=False)[-12000:] if root_cause else 'No RCA report yet. Click Analyze Root Cause after a failed execution.')}</pre></div>
<div class="card"><h2>Phase 5 Self-Healing Report</h2><p>Self-healing creates a guarded patch plan first. It can patch URLs, reusable utilities, BasePage resilience, and pageObjects/page methods under strict rules.</p><pre>{html.escape(json.dumps(self_healing, indent=2, ensure_ascii=False)[-12000:] if self_healing else 'No self-healing report yet. Click Propose Self-Healing Fix or Apply Self-Healing Patch.')}</pre></div>
<div class="card"><h2>Latest execution command/output</h2><pre>{html.escape(json.dumps(execution, indent=2)[-10000:] if execution else 'No execution report yet.')}</pre></div>
</div></body></html>'''
    out.write_text(html_text, encoding='utf-8')
    return out
