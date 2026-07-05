from __future__ import annotations

import json, math, os, re, time, hashlib, subprocess, shlex, urllib.parse, threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from qa_pipeline.core.paths import QA_CACHE_DIR, REPORTS_DIR
from qa_pipeline.core.runtime_logger import log_event
from qa_pipeline.core.vdi_agent_control import list_agents, create_agent_job
from qa_pipeline.core.central_workspace import resolve_worker_framework_root, with_unique_artifact_env, wrap_command_for_worker_path

SPEC_SUFFIXES = ('.spec.ts','.specs.ts','.test.ts','.spec.js','.specs.js','.test.js','.spec.mjs','.specs.mjs','.test.mjs','.spec.cjs','.specs.cjs','.test.cjs')
HISTORY_ROOT = QA_CACHE_DIR / 'framework-execution-history'
CENTRAL_REPORT_DIR = REPORTS_DIR / 'existing-framework'
ACTIVE_RUNS = QA_CACHE_DIR / 'distributed-runs'
MASTER_AGENT_ID = '__MASTER_VM__'


def _astraheal_max_wait_ms() -> int:
    raw = os.environ.get('ASTRAHEAL_MAX_EXPLICIT_WAIT_MS') or os.environ.get('ASTRAHEAL_MAX_TEST_TIMEOUT_MS') or '30000'
    try:
        value = int(float(str(raw).strip()))
    except Exception:
        value = 30000
    return max(5000, min(value, 30000))


def _now() -> str:
    return datetime.now().isoformat(timespec='seconds')


def _now_id() -> str:
    return datetime.now().strftime('%Y%m%d-%H%M%S')


def _hash_path(path: str) -> str:
    return hashlib.sha1(str(path).lower().encode('utf-8', errors='ignore')).hexdigest()[:12]


def _safe_read(path: Path, default: Any) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding='utf-8', errors='replace'))
    except Exception:
        pass
    return default


def _write(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')


def _framework_history_dir(framework_path: str) -> Path:
    return HISTORY_ROOT / _hash_path(framework_path or 'unknown')


def _framework_local_history_dir(framework_path: str) -> Path:
    return Path(framework_path).expanduser().resolve() / '.aiqa-history'


def _framework_local_reports_dir(framework_path: str) -> Path:
    return _framework_local_history_dir(framework_path) / 'reports'


def _framework_run_dir(framework_path: str, run_id: str) -> Path:
    return _framework_local_history_dir(framework_path) / 'distributed-runs' / run_id


def _central_run_dir(framework_path: str, run_id: str) -> Path:
    return ACTIVE_RUNS / _hash_path(framework_path or 'unknown') / run_id


def get_framework_distributed_report_path(framework_path: str) -> Path:
    return _framework_local_reports_dir(framework_path) / 'distributed-execution-report.html'


def get_framework_history_report_path(framework_path: str) -> Path:
    return _framework_local_reports_dir(framework_path) / 'framework-execution-history.html'


def append_execution_history(framework_path: str, payload: dict[str, Any], mirror_to_framework: bool = True) -> dict[str, Any]:
    ts = _now()
    record = {**(payload or {}), 'history_recorded_at': ts, 'framework_path': str(framework_path or payload.get('framework_path') or '')}
    key = _hash_path(record['framework_path'])
    central = _framework_history_dir(record['framework_path'])
    central.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, ensure_ascii=False) + '\n'
    with (central / 'executions.jsonl').open('a', encoding='utf-8') as fh:
        fh.write(line)
    _write(central / 'latest-execution.json', record)
    mirrored = False
    local_path = None
    if mirror_to_framework and record['framework_path']:
        try:
            local = _framework_local_history_dir(record['framework_path'])
            local.mkdir(parents=True, exist_ok=True)
            with (local / 'executions.jsonl').open('a', encoding='utf-8') as fh:
                fh.write(line)
            _write(local / 'latest-execution.json', record)
            local_path = str(local / 'executions.jsonl')
            mirrored = True
        except Exception as exc:
            record['framework_history_warning'] = f'{type(exc).__name__}: {exc}'
    log_event('framework_history', 'Execution/RCA history saved for framework.', status='ok', progress=100, details={'framework_key': key, 'mirrored': mirrored})
    return {'ok': True, 'framework_key': key, 'central_history': str(central / 'executions.jsonl'), 'framework_history': local_path, 'mirrored_to_framework': mirrored, 'record': record}


def list_framework_history(framework_path: str = '', limit: int = 50) -> dict[str, Any]:
    dirs = []
    if framework_path:
        dirs.append(_framework_history_dir(framework_path))
        dirs.append(_framework_local_history_dir(framework_path))
    else:
        dirs.extend([p for p in HISTORY_ROOT.glob('*') if p.is_dir()])
    records: list[dict[str, Any]] = []
    for d in dirs:
        f = d / 'executions.jsonl'
        if not f.exists():
            continue
        for line in f.read_text(encoding='utf-8', errors='replace').splitlines()[-limit:]:
            try:
                records.append(json.loads(line))
            except Exception:
                pass
    records = sorted(records, key=lambda r: str(r.get('history_recorded_at') or r.get('generated_at') or ''), reverse=True)[:limit]
    html = write_history_report(records, framework_path)
    return {'ok': True, 'framework_path': framework_path, 'records': records, 'count': len(records), 'html_report': str(html), 'html_report_url': '/artifacts/reports/existing-framework/framework-execution-history.html', 'message': f'Loaded {len(records)} history record(s).'}


def write_history_report(records: list[dict[str, Any]], framework_path: str = '') -> Path:
    CENTRAL_REPORT_DIR.mkdir(parents=True, exist_ok=True)
    rows = []
    for r in records:
        stage = r.get('stage') or r.get('type') or r.get('action') or 'execution'
        status = r.get('status') or ('passed' if r.get('ok') else 'warning')
        selected = r.get('selected_tests') or r.get('failed_specs') or r.get('shards') or []
        if isinstance(selected, list):
            selected = '<br/>'.join(str(x) for x in selected[:12])
        rows.append(f"<tr><td>{r.get('history_recorded_at') or r.get('generated_at') or ''}</td><td>{stage}</td><td>{status}</td><td>{r.get('framework_path') or framework_path}</td><td>{selected}</td><td><pre>{json.dumps(r, indent=2, ensure_ascii=False)[:2500]}</pre></td></tr>")
    html = CENTRAL_REPORT_DIR / 'framework-execution-history.html'
    html.write_text(f"""<!doctype html><html><head><meta charset='utf-8'/><title>Framework Execution History</title>
<style>body{{font-family:Segoe UI,Arial,sans-serif;background:#f8fafc;color:#0f172a;margin:24px}}table{{width:100%;border-collapse:collapse;background:white}}td,th{{border:1px solid #cbd5e1;padding:8px;vertical-align:top}}th{{background:#1e293b;color:white}}pre{{white-space:pre-wrap;max-height:220px;overflow:auto;background:#0f172a;color:#d1fae5;padding:8px;border-radius:6px}}</style></head><body>
<h1>Framework Execution History</h1><p>This report combines execution, RCA, self-healing, human approval and distributed-run memory for the selected framework.</p><table><thead><tr><th>Time</th><th>Stage</th><th>Status</th><th>Framework</th><th>Scope</th><th>Details</th></tr></thead><tbody>{''.join(rows) or '<tr><td colspan="6">No history found.</td></tr>'}</tbody></table></body></html>""", encoding='utf-8')
    return html


def _chunks(items: list[str], count: int) -> list[list[str]]:
    count = max(1, int(count or 1))
    if not items:
        return []
    size = max(1, math.ceil(len(items) / count))
    return [items[i:i+size] for i in range(0, len(items), size)]


def _chunks_by_size(items: list[str], size: int) -> list[list[str]]:
    size = max(1, int(size or 1))
    if not items:
        return []
    return [items[i:i + size] for i in range(0, len(items), size)]


def _safe_env_value(value: Any) -> str:
    return str(value if value is not None else '').replace('\r', ' ').replace('\n', ' ')



def _target_file_part(target: Any) -> str:
    value = str(target or '').replace('\\', '/').strip().strip('"\'`')
    return re.sub(r'(\.(?:specs|spec|test)\.(?:ts|tsx|js|jsx|mjs|cjs))(?::\d+){1,2}$', r'\1', value, flags=re.I)


def _is_line_selected_target(target: Any) -> bool:
    return bool(re.search(r'\.(?:specs|spec|test)\.(?:ts|tsx|js|jsx|mjs|cjs):\d+(?::\d+)?$', str(target or '').replace('\\', '/'), flags=re.I))


def _static_estimate_test_cases(root: Path, tests: list[str]) -> int:
    """Fast fallback when Playwright --list is not available.

    It intentionally counts common Playwright/Cucumber declarations only.  The
    runtime --list preflight is preferred for exact numbers; this keeps GUI
    progress useful when enterprise network/runtime restrictions block --list.
    Individual GUI selections such as tests/login.spec.ts:42 are counted as one
    test case so progress remains useful even when --list is blocked.
    """
    total = 0
    for rel in tests or []:
        if _is_line_selected_target(rel):
            total += 1
            continue
        file_part = _target_file_part(rel)
        path = (root / file_part).resolve()
        if not path.exists() or not path.is_file():
            continue
        text = path.read_text(encoding='utf-8', errors='replace')[:300000]
        if str(file_part).lower().endswith('.feature'):
            total += len(re.findall(r'^\s*Scenario(?: Outline)?:', text, flags=re.M))
        else:
            # Covers test(...), test.only(...), it(...). Hooks/describe/step are excluded approximately.
            total += len(re.findall(r'(?<![A-Za-z0-9_$])(?:test|it)\s*(?:\.only|\.fixme|\.skip|\.fail|\.slow)?\s*\(', text))
    return max(0, total)


def _playwright_list_count(root: Path, tests: list[str], browser: str) -> dict[str, Any]:
    """Ask Playwright for the exact test-case count without executing tests."""
    accepted = [str(t).replace('\\', '/') for t in tests or [] if str(t).strip()]
    static_estimate = _static_estimate_test_cases(root, accepted)
    if not accepted or _is_cucumber(root, accepted):
        return {'ok': False, 'exact': False, 'count': static_estimate, 'source': 'static_fallback', 'message': 'Playwright --list skipped for empty/Cucumber shard.'}
    cmd = ['npx', '--no-install', 'playwright', 'test', *accepted, '--list']
    if browser and str(browser).lower() not in {'auto', 'default', 'all'}:
        cmd.append(f'--project={browser}')
    try:
        result = subprocess.run(cmd, cwd=str(root), text=True, encoding='utf-8', errors='replace', stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=120)
        output = result.stdout or ''
        total = None
        m = re.search(r'Total:\s*(\d+)\s+tests?', output, flags=re.I)
        if m:
            total = int(m.group(1))
        if total is None:
            # Playwright list lines generally include project + › file › title.  This fallback avoids returning 0.
            lines = [ln for ln in output.splitlines() if '›' in ln and not ln.lower().startswith('listing tests')]
            total = len(lines) or static_estimate
        return {'ok': result.returncode == 0 or total > 0, 'exact': bool(m), 'count': int(total or 0), 'source': 'playwright_test_list', 'command': subprocess.list2cmdline(cmd), 'returncode': result.returncode, 'stdout_tail': output[-4000:]}
    except Exception as exc:
        return {'ok': False, 'exact': False, 'count': static_estimate, 'source': 'static_fallback_after_list_error', 'error': f'{type(exc).__name__}: {exc}'}


def _parse_playwright_live_progress(line: str) -> tuple[int, int] | None:
    # Examples: [1/210] [chromium] › tests\x.spec.ts:1:1 › title
    m = re.search(r'\[(\d+)\s*/\s*(\d+)\]', line or '')
    if not m:
        return None
    try:
        return int(m.group(1)), int(m.group(2))
    except Exception:
        return None


ProgressCallback = Callable[[str, int, int, str], None]



def _shell_quote_arg(value: Any) -> str:
    text = str(value if value is not None else '')
    return subprocess.list2cmdline([text]) if os.name == 'nt' else shlex.quote(text)


def _html_escape(value: Any) -> str:
    return str(value if value is not None else '').replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;')


def _write_local_shard_launcher(root: Path, shard_dir: Path, command: str, env_overrides: dict[str, str], title: str) -> Path:
    shard_dir.mkdir(parents=True, exist_ok=True)
    if os.name == 'nt':
        script = shard_dir / 'RUN_LOCAL_PARALLEL_SHARD.cmd'
        env_lines = ''.join(f'set {k}={_safe_env_value(v)}\r\n' for k, v in env_overrides.items())
        script.write_text(
            '@echo off\r\n'
            'setlocal enableextensions\r\n'
            f'echo [{title}] Starting at %DATE% %TIME%\r\n'
            f'echo Framework folder: {root}\r\n'
            f'echo Shard artifact folder: {shard_dir}\r\n'
            f'{env_lines}'
            f'cd /d {subprocess.list2cmdline([str(root)])}\r\n'
            f'echo Command: {command}\r\n'
            f'{command}\r\n'
            'set EXITCODE=%ERRORLEVEL%\r\n'
            'echo Playwright shard exited with code %EXITCODE%\r\n'
            'exit /b %EXITCODE%\r\n',
            encoding='utf-8',
        )
        return script
    script = shard_dir / 'run_local_parallel_shard.sh'
    env_lines = ''.join(f'export {k}={shlex.quote(_safe_env_value(v))}\n' for k, v in env_overrides.items())
    script.write_text(
        '#!/usr/bin/env bash\nset -o pipefail\n'
        f"echo '[{title}] Starting'\n"
        f"echo 'Framework folder: {root}'\n"
        f"echo 'Shard artifact folder: {shard_dir}'\n"
        f'{env_lines}'
        f'cd {shlex.quote(str(root))}\n'
        f'echo Command: {shlex.quote(command)}\n'
        f'{command}\n'
        'code=$?\necho "Playwright shard exited with code $code"\nexit $code\n',
        encoding='utf-8',
    )
    script.chmod(0o755)
    return script


def _run_local_parallel_shard_process(root: Path, run_id: str, shard: dict[str, Any], headed: bool, progress_callback: ProgressCallback | None = None) -> dict[str, Any]:
    shard_id = str(shard.get('shard_id') or 'shard')
    browser = str(shard.get('browser') or 'chromium')
    shard_dir = root / 'reports' / 'existing-framework' / 'distributed-runs' / run_id / shard_id
    html_dir = shard_dir / 'html'
    json_file = shard_dir / 'results.json'
    test_results_dir = shard_dir / 'test-results'
    env_overrides = {
        'PLAYWRIGHT_HTML_OPEN': 'never',
        'PLAYWRIGHT_HTML_OUTPUT_DIR': str(html_dir),
        'PLAYWRIGHT_JSON_OUTPUT_NAME': str(json_file),
        'PW_WORKERS': '1',
        'CI': 'false' if headed else os.environ.get('CI', ''),
        'HEADED': 'true' if headed else 'false',
        'HEADLESS': 'false' if headed else 'true',
        'PW_HEADLESS': 'false' if headed else 'true',
        'PLAYWRIGHT_HEADLESS': 'false' if headed else 'true',
        'PLAYWRIGHT_MCP_ENABLED': 'true',
        'PLAYWRIGHT_MCP_HEADLESS': 'false' if headed else 'true',
        'BROWSER': browser,
        'ASTRAHEAL_RUN_ID': run_id,
        'ASTRAHEAL_SHARD_ID': shard_id,
        'ASTRAHEAL_MAX_EXPLICIT_WAIT_MS': str(_astraheal_max_wait_ms()),
        'ASTRAHEAL_MAX_TEST_TIMEOUT_MS': str(_astraheal_max_wait_ms()),
    }
    command = _build_command(root, list(shard.get('tests') or []), browser, headed, output_dir=test_results_dir)
    env = {**os.environ.copy(), **env_overrides}
    launcher = _write_local_shard_launcher(root, shard_dir, command, env_overrides, f'Local/VM parallel shard {shard_id}')
    started = time.time()
    log_event('distributed_execution', f'Starting local/VM parallel browser shard {shard_id}.', status='running', progress=35, details={'command': command, 'tests': shard.get('tests'), 'browser': browser, 'launcher': str(launcher), 'test_case_count': shard.get('test_case_count'), 'max_wait_ms': _astraheal_max_wait_ms()})
    output_lines: list[str] = []
    try:
        popen_args = ['cmd.exe', '/d', '/s', '/c', str(launcher)] if os.name == 'nt' else [str(launcher)]
        proc = subprocess.Popen(popen_args, cwd=str(root), env=env, text=True, encoding='utf-8', errors='replace', stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=1)
        assert proc.stdout is not None
        last_log = 0.0
        for line in proc.stdout:
            line = line.rstrip('\n')
            output_lines.append(line)
            now = time.time()
            parsed_progress = _parse_playwright_live_progress(line)
            if parsed_progress and progress_callback:
                progress_callback(shard_id, parsed_progress[0], parsed_progress[1], line)
            if now - last_log > 1.0:
                log_event('distributed_execution', f'{shard_id}: {line[-240:]}', status='running', progress=45, details={'shard_id': shard_id, 'browser': browser, 'test_case_count': shard.get('test_case_count')})
                last_log = now
        return_code = proc.wait()
    except Exception as exc:
        return_code = None
        output_lines.append(f'{type(exc).__name__}: {exc}')
    duration = round(time.time() - started, 2)
    stdout = '\n'.join(output_lines)[-60000:]
    log_path = shard_dir / 'execution-console.log'
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text('\n'.join([f'Command: {command}', f'CWD: {root}', f'Return code: {return_code}', f'Duration seconds: {duration}', '', stdout]), encoding='utf-8', errors='replace')
    status = 'passed' if return_code == 0 else 'failed'
    result = {
        **shard,
        'mode': 'local_vm_parallel_browser_shard',
        'command': command,
        'launcher_script': str(launcher),
        'artifact_dir': str(shard_dir),
        'html_report': str(html_dir / 'index.html'),
        'json_report': str(json_file),
        'test_results_dir': str(test_results_dir),
        'test_case_count': shard.get('test_case_count'),
        'test_count_source': shard.get('test_count_source'),
        'execution': {'ok': return_code == 0, 'returncode': return_code, 'stdout_tail': stdout[-30000:], 'duration_seconds': duration, 'cwd': str(root)},
        'return_code': return_code,
        'stdout_tail': stdout[-30000:],
        'status': status,
    }
    result['parallel_rca'] = _agentic_rca_for_shard(result)
    log_event('distributed_execution', f'Local/VM parallel browser shard {shard_id} {status}.', status='done' if status == 'passed' else 'warning', progress=75, details={'return_code': return_code, 'artifact_dir': str(shard_dir)})
    return result


def _publish_local_parallel_failed_inventory(root: Path, summary: dict[str, Any], headed: bool, run_role: str = 'first_run') -> dict[str, Any]:
    try:
        from qa_pipeline.agents.existing_framework_control.controller import (
            _persist_execution_report,
            _walk_playwright_json,
            _extract_failed_specs_from_stdout,
            _is_tests_folder_executable_spec,
            _normalize_existing_spec_path,
            _spec_compare_key,
            _dedupe_case_records,
            _case_record,
            _record_first_run_baseline,
            _write_latest_playwright_router,
            EXISTING_REPORTS_DIR,
            EXISTING_INVENTORY_JSON,
        )
        shard_results = list(summary.get('shard_results') or [])
        all_targets: list[str] = []
        stdout_parts: list[str] = []
        all_specs: set[str] = set()
        failed_specs: set[str] = set()
        passed_specs: set[str] = set()
        failed_tests: list[dict[str, Any]] = []
        all_test_cases: list[dict[str, Any]] = []
        failed_test_cases: list[dict[str, Any]] = []
        passed_test_cases: list[dict[str, Any]] = []
        spec_statuses: dict[str, str] = {}
        test_statuses: dict[str, str] = {}

        def clean_spec(value: Any) -> str:
            return _normalize_existing_spec_path(value, root=root)

        def accept(value: Any) -> str:
            v = clean_spec(value)
            return v if _is_tests_folder_executable_spec(v) else ''

        for sr in shard_results:
            tests = [accept(t) for t in (sr.get('tests') or [])]
            tests = [t for t in tests if t]
            all_targets.extend(tests)
            all_specs.update(tests)
            stdout = str((sr.get('execution') or {}).get('stdout_tail') or sr.get('stdout_tail') or '')
            stdout_parts.append(stdout)
            parsed_ok = False
            json_report = Path(str(sr.get('json_report') or '')) if sr.get('json_report') else None
            if json_report and json_report.exists():
                try:
                    parsed = _walk_playwright_json(json.loads(json_report.read_text(encoding='utf-8', errors='replace')), root=root)
                    parsed_all = [accept(x) for x in (parsed.get('all_specs') or [])]
                    parsed_failed = [accept(x) for x in (parsed.get('failed_specs') or [])]
                    parsed_passed = [accept(x) for x in (parsed.get('passed_specs') or [])]
                    parsed_all = [x for x in parsed_all if x]
                    parsed_failed = [x for x in parsed_failed if x]
                    parsed_passed = [x for x in parsed_passed if x]
                    parsed_cases: list[dict[str, Any]] = []
                    for rec in parsed.get('all_test_cases') or []:
                        if not isinstance(rec, dict):
                            continue
                        spec = accept(rec.get('spec'))
                        if spec:
                            parsed_cases.append(_case_record(spec, rec.get('title') or '', rec.get('status') or 'unknown', rec.get('projectName') or '', rec.get('errors') or [], {k: v for k, v in rec.items() if k not in {'id','spec','title','status','projectName','errors'}}))
                    parsed_cases = _dedupe_case_records(parsed_cases)
                    if parsed_all or parsed_failed or parsed_passed or parsed_cases:
                        parsed_ok = True
                        all_specs.update(parsed_all)
                        failed_specs.update(parsed_failed)
                        passed_specs.update(x for x in parsed_passed if _spec_compare_key(x) not in {_spec_compare_key(y) for y in failed_specs})
                        all_test_cases.extend(parsed_cases)
                        for rec in parsed_cases:
                            status = str(rec.get('status') or '').lower()
                            test_statuses[rec.get('id')] = status
                            if status in {'failed', 'timedout', 'interrupted'}:
                                failed_test_cases.append(rec)
                                failed_specs.add(rec.get('spec'))
                            else:
                                passed_test_cases.append(rec)
                        for k, v in (parsed.get('spec_statuses') or {}).items():
                            ak = accept(k)
                            if ak:
                                spec_statuses[ak] = 'failed' if str(v).lower() == 'failed' or ak in parsed_failed else 'passed'
                        for ft in parsed.get('failed_tests') or []:
                            spec = accept(ft.get('spec'))
                            if spec:
                                failed_tests.append({**ft, 'spec': spec})
                except Exception as exc:
                    sr['json_parse_warning'] = f'{type(exc).__name__}: {exc}'
            if not parsed_ok and sr.get('status') == 'failed':
                exact = [accept(x) for x in _extract_failed_specs_from_stdout(stdout, root)]
                exact = [x for x in exact if x]
                if not exact:
                    exact = tests
                failed_specs.update(exact)
                for spec in exact[:50]:
                    rec = _case_record(spec, 'Failure detected from local/VM parallel shard output', 'failed', sr.get('browser'), [{'message': stdout[-6000:]}], {'granularity': 'spec_file_fallback'})
                    failed_tests.append(rec)
                    failed_test_cases.append(rec)
                    all_test_cases.append(rec)
            elif sr.get('status') == 'passed' and not parsed_ok:
                passed_specs.update(tests)
                for spec in tests:
                    all_test_cases.append(_case_record(spec, '', 'passed', sr.get('browser'), [], {'granularity': 'spec_file_fallback'}))

        # Anything explicitly selected and not failed is treated as passed/recovered for inventory purposes.
        failed_keys = {_spec_compare_key(s) for s in failed_specs}
        all_specs.update(all_targets)
        passed_specs.update(x for x in all_specs if _spec_compare_key(x) not in failed_keys)
        if not all_test_cases:
            for spec in all_specs:
                status = 'failed' if _spec_compare_key(spec) in failed_keys else 'passed'
                all_test_cases.append(_case_record(spec, '', status, '', [], {'granularity': 'spec_file_fallback'}))
        all_test_cases = _dedupe_case_records(all_test_cases)
        failed_test_cases = _dedupe_case_records([r for r in [*failed_test_cases, *all_test_cases] if str(r.get('status') or '').lower() in {'failed', 'timedout', 'interrupted'}])
        failed_ids = {r.get('id') for r in failed_test_cases}
        passed_test_cases = _dedupe_case_records([r for r in [*passed_test_cases, *all_test_cases] if r.get('id') not in failed_ids and str(r.get('status') or '').lower() not in {'failed', 'timedout', 'interrupted'}])
        for spec in all_specs:
            spec_statuses.setdefault(spec, 'failed' if _spec_compare_key(spec) in failed_keys else 'passed')
        for rec in all_test_cases:
            if rec.get('id'):
                test_statuses.setdefault(rec.get('id'), rec.get('status'))
        aggregate_stdout = '\n'.join(stdout_parts)[-140000:]
        execution_console = root / 'reports' / 'existing-framework' / 'execution-console.log'
        execution_console.parent.mkdir(parents=True, exist_ok=True)
        execution_console.write_text(aggregate_stdout, encoding='utf-8', errors='replace')
        inventory = {
            'ok': True,
            'source': 'local_vm_parallel_distributed_execution',
            'framework_path': str(root),
            'generated_at': _now(),
            'target_args': sorted(dict.fromkeys(all_targets), key=_spec_compare_key),
            'all_specs': sorted(all_specs, key=_spec_compare_key),
            'passed_specs': sorted(passed_specs - failed_specs, key=_spec_compare_key),
            'failed_specs': sorted(failed_specs, key=_spec_compare_key),
            'failed_count': len({_spec_compare_key(s) for s in failed_specs}),
            'failed_tests': failed_test_cases[:200],
            'all_test_cases': all_test_cases,
            'passed_test_cases': passed_test_cases,
            'failed_test_cases': failed_test_cases,
            'test_case_count': len(all_test_cases),
            'passed_test_case_count': len(passed_test_cases),
            'failed_test_case_count': len(failed_test_cases),
            'inventory_granularity': 'test_case' if any(r.get('granularity') != 'spec_file_fallback' for r in all_test_cases) else 'spec_file_fallback',
            'spec_statuses': dict(sorted(spec_statuses.items(), key=lambda kv: _spec_compare_key(kv[0]))),
            'test_statuses': test_statuses,
            'results_json': 'per-shard-json-reports',
            'native_html_report': 'generated-playwright/reports/existing-framework/html/index.html',
            'execution_console_log': str(execution_console),
            'extraction_note': 'Merged per-shard Playwright JSON reports when available; otherwise used shard console output. Paths reported relative to testDir are normalized to avoid duplicate tests/... and non-tests/... rows.',
            'note': 'Existing-framework RCA/self-healing uses failed_specs only. Combined reports use test-case level counts when Playwright JSON is available; otherwise they clearly fall back to spec-file granularity.',
        }
        try:
            exact_report = _write_exact_distributed_playwright_reports(root, summary, inventory)
            inventory['exact_first_run_playwright_report'] = exact_report
            summary['exact_first_run_playwright_report'] = exact_report
            # Preserve the planned/static denominator so users can see why 109/120
            # happened instead of silently converting the run total to 109.  The
            # exact report explains unresolved/not-reported targets.
            progress_state = summary.get('runtime_test_progress') or {}
            if exact_report.get('summary'):
                actual_cases = int((exact_report.get('summary') or {}).get('playwright_reported_test_cases') or len(all_test_cases) or 0)
                planned_cases = int((exact_report.get('summary') or {}).get('planned_selected_targets') or progress_state.get('total') or actual_cases or 0)
                unresolved = int((exact_report.get('summary') or {}).get('unresolved_or_not_reported_targets') or max(0, planned_cases - actual_cases))
                if actual_cases:
                    summary['runtime_test_progress'] = {**progress_state, 'completed': actual_cases, 'total': planned_cases, 'display': f'{actual_cases}/{planned_cases}' if planned_cases else f'{actual_cases}/?', 'percent': int((actual_cases / planned_cases) * 100) if planned_cases else 100, 'planned_or_static_target_count': planned_cases, 'actual_playwright_reported_test_cases': actual_cases, 'unresolved_or_not_reported_targets': unresolved, 'count_integrity_note': 'Completed/total keeps the user-selected planned count. Actual Playwright-reported tests and unresolved/not-reported targets are shown separately.'}
            try:
                if str(run_role or 'first_run') == 'first_run':
                    _record_first_run_baseline(root, inventory, distributed_summary=summary)
                _write_latest_playwright_router('Latest Playwright report: first distributed run' if str(run_role or 'first_run') == 'first_run' else 'Latest Playwright report: failed-only distributed rerun', '<p>The latest execution is the first distributed/local parallel run. Open the exact shard report index to see native Playwright HTML per shard, passed/failed counts, and unresolved/not-reported selected tests.</p>', [('Open exact first-run Playwright shard report index', '/artifacts/reports/existing-framework/first-run-playwright-report.html'), ('Open distributed execution report', '/artifacts/reports/existing-framework/distributed-execution-report.html'), ('Open combined first-run + rerun report', '/artifacts/reports/existing-framework/consolidated-report.html')])
            except Exception as exc:
                inventory['baseline_record_warning'] = f'{type(exc).__name__}: {exc}' 
        except Exception as exc:
            inventory['exact_report_warning'] = f'{type(exc).__name__}: {exc}'
        EXISTING_INVENTORY_JSON.parent.mkdir(parents=True, exist_ok=True)
        EXISTING_INVENTORY_JSON.write_text(json.dumps(inventory, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
        aggregate_execution = {
            'ok': all(sr.get('status') == 'passed' for sr in shard_results),
            'returncode': 0 if all(sr.get('status') == 'passed' for sr in shard_results) else 1,
            'stdout': aggregate_stdout,
            'stderr': '',
            'command': 'AstraHeal local/VM parallel browser shards',
            'cwd': str(root),
            'duration_seconds': sum(float((sr.get('execution') or {}).get('duration_seconds') or 0) for sr in shard_results),
        }
        report = {
            'ok': bool(aggregate_execution.get('ok')),
            'stage': 'local_vm_parallel_distributed_execution_completed',
            'mode': 'headed' if headed else 'headless',
            'execution_mode': 'local_vm_parallel_browser_shards',
            'framework_path': str(root),
            'targets': sorted(dict.fromkeys(all_targets), key=_spec_compare_key),
            'execution': aggregate_execution,
            'failed_test_inventory': inventory,
            'distributed_run': {k: summary.get(k) for k in ['run_id', 'stage', 'message', 'runtime_test_progress']},
            'playwright_html_report_url': '/api/module2/framework-artifact/playwright-report?framework_path=' + _framework_query(str(root)),
            'distributed_html_report_url': summary.get('html_report_url'),
            'message': 'Local/VM parallel distributed execution completed. Open Playwright report now opens the central landing page with shard-native reports. RCA/self-healing uses failed scripts only.',
        }
        _persist_execution_report(report)
        try:
            (EXISTING_REPORTS_DIR / 'local-parallel-distributed-execution-report.json').write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
        except Exception:
            pass
        return {'ok': True, 'failed_test_inventory': inventory, 'execution_report_stage': report['stage']}
    except Exception as exc:
        return {'ok': False, 'error': f'{type(exc).__name__}: {exc}'}

def _is_cucumber(root: Path, tests: list[str]) -> bool:
    return bool(tests) and all(t.lower().endswith('.feature') for t in tests) or (root / 'cucumber.js').exists() and any(t.lower().endswith('.feature') for t in tests)


def _build_command(root: Path, tests: list[str], browser: str, headed: bool, output_dir: Path | str | None = None) -> str:
    quoted = ' '.join('"' + t.replace('"','') + '"' for t in tests)
    if _is_cucumber(root, tests):
        # Cucumber Playwright frameworks usually read HEADLESS/BROWSER from config/world.js.
        return f'set HEADLESS={"false" if headed else "true"}&& set BROWSER={browser or "chromium"}&& npx --no-install cucumber-js {quoted} --format progress-bar --format json:reports/cucumber-json/cucumber-aiqa.json --format html:reports/html-report/cucumber-report.html'
    args = f'npx --no-install playwright test {quoted} --workers=1 --reporter=line,json,html --timeout={_astraheal_max_wait_ms()} --retries=1'
    if output_dir:
        args += ' --output=' + _shell_quote_arg(output_dir)
    if browser and browser.lower() not in {'auto','default','all'}:
        args += f' --project={browser}'
    if headed:
        args += ' --headed'
    return args


def _read_selected_tests(framework_path: str, selected_tests: str) -> tuple[Path, list[str]]:
    from qa_pipeline.agents.existing_framework_control.controller import (
        _resolve_framework_path,
        _find_executable_tests_under_tests,
        _is_tests_folder_executable_spec,
        _parse_target_patterns,
        _rel_to,
    )
    root = _resolve_framework_path(framework_path)
    tests = [x.replace('\\','/').strip() for x in _parse_target_patterns(selected_tests) if x.strip()]
    if not tests:
        latest = _safe_read(QA_CACHE_DIR / 'existing-framework' / 'last-executed-user-selection.json', {})
        tests = latest.get('selected_tests') or []
    if not tests:
        tests = [_rel_to(p, root) for p in _find_executable_tests_under_tests(root, limit=5000)]
    validated: list[str] = []
    seen: set[str] = set()
    for t in tests:
        normalized = t.replace('\\', '/')
        if not normalized or normalized.startswith('node_modules/') or not _is_tests_folder_executable_spec(normalized):
            continue
        key = normalized.lower()
        if key not in seen:
            validated.append(normalized)
            seen.add(key)
    return root, validated


def _normalize_execution_target_mode(mode: str) -> str:
    m = str(mode or '').strip().lower().replace('-', '_').replace(' ', '_')
    aliases = {
        'central': 'central_only',
        'central_vm': 'central_only',
        'local': 'central_only',
        'local_only': 'central_only',
        'master_only': 'central_only',
        'worker': 'workers_only',
        'workers': 'workers_only',
        'worker_only': 'workers_only',
        'remote_only': 'workers_only',
        'all': 'central_and_workers',
        'hybrid': 'central_and_workers',
        'central_workers': 'central_and_workers',
        'central_plus_workers': 'central_and_workers',
    }
    m = aliases.get(m, m)
    return m if m in {'central_only', 'workers_only', 'central_and_workers'} else 'central_and_workers'


def _match_agent(agent: dict[str, Any], token: str) -> bool:
    t = str(token or '').strip().lower()
    return t in {
        str(agent.get('agent_id') or '').lower(),
        str(agent.get('agent_name') or '').lower(),
        str(agent.get('hostname') or '').lower(),
        str(agent.get('ip_address') or '').lower(),
        str(agent.get('host') or '').lower(),
        str(agent.get('host_ip') or '').lower(),
    }


def _central_worker_record(name: str = 'Central-VM-Worker') -> dict[str, Any]:
    return {
        'agent_id': MASTER_AGENT_ID,
        'agent_name': name or 'Central-VM-Worker',
        'hostname': 'central-control-plane',
        'ip_address': '127.0.0.1',
        'host': '127.0.0.1',
        'status': 'online',
        'is_master_worker': True,
        'execution_location': 'central_vm',
    }


def _resolve_execution_workers(agent_ids: str, execution_target_mode: str, master_worker_name: str = 'Central-VM-Worker') -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    mode = _normalize_execution_target_mode(execution_target_mode)
    online_agents = list_agents().get('agents') or []
    online_agents = [a for a in online_agents if a.get('status') == 'online']
    requested = [a.strip() for a in (agent_ids or '').replace('\n', ',').split(',') if a.strip()]
    if requested:
        selected = []
        for req in requested:
            if req.strip().lower() in {'master', 'local', 'central', 'central-vm', 'vm-1', MASTER_AGENT_ID.lower(), (master_worker_name or '').lower()}:
                continue
            for a in online_agents:
                if _match_agent(a, req) and a not in selected:
                    selected.append(a)
        online_agents = selected
    workers: list[dict[str, Any]] = []
    if mode in {'central_only', 'central_and_workers'}:
        workers.append(_central_worker_record(master_worker_name))
    if mode in {'workers_only', 'central_and_workers'}:
        workers.extend(online_agents)
    if not workers and mode != 'workers_only':
        workers.append(_central_worker_record(master_worker_name))
    return workers, online_agents


def create_distributed_plan(framework_path: str, selected_tests: str = '', browsers: str = 'chromium,firefox,webkit,msedge,chrome', shard_count: int = 5, agent_ids: str = '', worker_workspace_mode: str = 'central_shared_workspace', central_shared_framework_path: str = '', centralize_reports_and_ai_memory: bool = True, execution_target_mode: str = 'central_and_workers', master_worker_name: str = 'Central-VM-Worker', tests_per_shard: int = 0) -> dict[str, Any]:
    central_control_warnings: list[str] = []
    if not centralize_reports_and_ai_memory:
        central_control_warnings.append('Centralized reports/AI memory was requested as false, but distributed enterprise mode forces Central VM consolidation to keep one source of truth.')
    centralize_reports_and_ai_memory = True
    root, tests = _read_selected_tests(framework_path, selected_tests)
    browser_list = [b.strip() for b in (browsers or '').replace('\n', ',').split(',') if b.strip()] or ['chromium']
    execution_target_mode = _normalize_execution_target_mode(execution_target_mode)
    workers, online_agents = _resolve_execution_workers(agent_ids, execution_target_mode, master_worker_name)

    local_tests_per_shard = max(0, int(tests_per_shard or 0))
    requested_shards = max(1, int(shard_count or len(browser_list) or len(workers) or 1))
    local_parallel_enabled = bool(execution_target_mode == 'central_only' and (local_tests_per_shard > 0 or requested_shards > 1))

    if execution_target_mode == 'central_only' and local_tests_per_shard > 0:
        groups = _chunks_by_size(tests, local_tests_per_shard) if workers else []
        shard_strategy = 'tests_per_local_browser_instance'
    else:
        shard_total = requested_shards if execution_target_mode != 'central_only' else requested_shards
        groups = _chunks(tests, shard_total) if workers else []
        shard_strategy = 'shard_count'

    shards = []
    for idx, group in enumerate(groups, start=1):
        browser = browser_list[(idx - 1) % len(browser_list)]
        worker = workers[(idx - 1) % len(workers)]
        shards.append({
            'shard_id': f'shard-{idx:02d}',
            'browser': browser,
            'tests': group,
            'test_count': len(group),
            'agent_id': worker.get('agent_id'),
            'agent_name': worker.get('agent_name'),
            'is_master_worker': bool(worker.get('is_master_worker')),
            'worker_execution_location': worker.get('execution_location') or 'worker_vm',
        })

    if execution_target_mode == 'central_only' and local_parallel_enabled:
        agent_mode = 'local_or_central_vm_parallel_browser_shards'
        msg = (f'Local/VM parallel plan created: {len(tests)} executable tests/** script(s) split into {len(shards)} browser shard(s) '
               f'using {local_tests_per_shard or "auto"} test(s) per local browser instance. No worker VM/VDI agents are required.')
    elif execution_target_mode == 'central_only':
        agent_mode = 'central_vm_only'
        msg = f'Central/local single-machine plan created: {len(tests)} executable tests/** script(s) across {len(shards)} shard(s).'
    else:
        agent_mode = 'vm_worker_agents_only' if execution_target_mode == 'workers_only' else 'central_vm_plus_worker_agents'
        msg = f'Node-hub plan created: {len(tests)} executable tests/** script(s) across {len(shards)} shard(s). Execution target mode: {execution_target_mode}.'

    plan = {
        'ok': bool(tests and shards),
        'stage': 'node_hub_distributed_execution_plan_created',
        'generated_at': _now(),
        'framework_path': str(root),
        'total_tests': len(tests),
        'browsers': browser_list,
        'execution_target_mode': execution_target_mode,
        'agent_mode': agent_mode,
        'local_parallel_enabled': local_parallel_enabled,
        'tests_per_shard': local_tests_per_shard,
        'requested_shard_count': requested_shards,
        'actual_shard_count': len(shards),
        'shard_strategy': shard_strategy,
        'worker_workspace_mode': worker_workspace_mode or 'central_shared_workspace',
        'central_shared_framework_path': central_shared_framework_path or '',
        'centralize_reports_and_ai_memory': True,
        'single_consolidated_execution_report': True,
        'central_ai_heavy_lifting_only': True,
        'worker_ai_disabled': True,
        'central_control_enforcement_warnings': central_control_warnings,
        'source_of_truth': 'central_vm_framework_and_ai_memory',
        'online_agents': online_agents,
        'available_execution_workers': workers,
        'shards': shards,
        'message': msg if shards else f'No executable Playwright tests were resolved for mode {execution_target_mode}. Use Find scripts first and select tests/**/*.spec.ts/specs.ts/test.ts files.',
    }
    _write(CENTRAL_REPORT_DIR / 'distributed-execution-plan.json', plan)
    try:
        local_reports = _framework_local_reports_dir(str(root)); local_reports.mkdir(parents=True, exist_ok=True)
        _write(local_reports / 'distributed-execution-plan.json', plan)
        plan['framework_plan_path'] = str(local_reports / 'distributed-execution-plan.json')
    except Exception as exc:
        plan['framework_plan_warning'] = f'{type(exc).__name__}: {exc}'
    plan['central_plan_path'] = str(CENTRAL_REPORT_DIR / 'distributed-execution-plan.json')
    plan['framework_report_folder'] = str(_framework_local_reports_dir(str(root)))
    log_event('distributed_execution', plan['message'], status='ok' if tests else 'warning', progress=100, details={'shards': len(shards), 'tests': len(tests), 'framework_report_folder': plan.get('framework_report_folder'), 'local_parallel_enabled': local_parallel_enabled})
    return plan

def _empty_run_state(run_id: str, plan: dict[str, Any]) -> dict[str, Any]:
    total_cases = int(plan.get('total_test_cases') or sum(int(s.get('test_case_count') or 0) for s in (plan.get('shards') or [])) or 0)
    return {'ok': True, 'run_id': run_id, 'stage': 'distributed_node_hub_execution_started', 'generated_at': _now(), 'framework_path': plan.get('framework_path'), 'plan': plan, 'shard_results': [], 'parallel_rca_events': [], 'single_consolidated_execution_report': True, 'central_ai_heavy_lifting_only': True, 'runtime_test_progress': {'completed': 0, 'total': total_cases, 'exact': bool(plan.get('test_case_count_exact')), 'display': f'0/{total_cases}' if total_cases else '0/?', 'per_shard': {}}, 'message': 'Distributed node-hub execution started. Failed shard RCA/self-healing triage begins as soon as a shard completes.'}


def _save_run_state(summary: dict[str, Any]) -> None:
    framework_path = str(summary.get('framework_path') or '')
    run_id = str(summary.get('run_id') or 'latest')
    for d in [_central_run_dir(framework_path, run_id), _framework_run_dir(framework_path, run_id)]:
        try:
            d.mkdir(parents=True, exist_ok=True)
            _write(d / 'run-state.json', summary)
        except Exception as exc:
            summary.setdefault('history_warnings', []).append(f'{d}: {type(exc).__name__}: {exc}')
    try:
        _write(_framework_local_reports_dir(framework_path) / 'active-distributed-run.json', summary)
        _write(CENTRAL_REPORT_DIR / 'active-distributed-run.json', summary)
    except Exception:
        pass


def _extract_failed_specs_from_text(text: str) -> list[str]:
    failed = set()
    for m in re.finditer(r'([A-Za-z]:)?[^\n\r:]*?(?:tests|features)[/\\][^\n\r:]+?\.(?:specs?|test)\.(?:ts|js|mjs|cjs)|(?:features[/\\][^\n\r:]+?\.feature)', text or '', flags=re.I):
        val = m.group(0).replace('\\','/').strip(' "\'()[]')
        idx = min([i for i in [val.lower().find('/tests/'), val.lower().find('tests/'), val.lower().find('/features/'), val.lower().find('features/')] if i >= 0] or [0])
        failed.add(val[idx:].lstrip('/'))
    return sorted(failed)


def _distributed_auditable_rca_checklist(text: str, classification: str) -> list[dict[str, Any]]:
    low = (text or '').lower()
    def hit(keys: list[str], yes: str, no: str = 'needs_evidence') -> str:
        return yes if any(k in low for k in keys) else no
    return [
        {'order': 1, 'check': 'Failed-only scope confirmed', 'status': 'done', 'decision': 'Only failed specs from this shard are eligible for RCA/self-healing.'},
        {'order': 2, 'check': 'Locator exists in DOM/accessibility snapshot', 'status': hit(['locator', 'not found', 'tobevisible', 'waiting for'], 'locator_dom_check_required'), 'decision': 'Use MCP/browser evidence or trace before changing locator.'},
        {'order': 3, 'check': 'Locator strategy/address correctness', 'status': hit(['strict mode', 'nth(', 'resolved to', 'aria-label'], 'locator_strategy_check_required'), 'decision': 'Prefer stable role/testId/label locator in POM/pageObject layer.'},
        {'order': 4, 'check': 'Interactability/actionability', 'status': hit(['intercepts pointer events', 'not visible', 'not enabled', 'detached', 'locator.click'], 'actionability_check_required'), 'decision': 'Patch shared click/helper with stable wait, scroll, overlay handling; avoid force:true by default.'},
        {'order': 5, 'check': 'Viewport/scroll/page-size', 'status': hit(['outside of the viewport', 'scrolling into view', 'footer', 'mobile'], 'viewport_scroll_check_required'), 'decision': 'Scroll into view and use responsive/mobile-aware page method when needed.'},
        {'order': 6, 'check': 'Popup/modal/permission/cookie overlay', 'status': hit(['popup', 'modal', 'permission', 'cookie', 'geolocation', 'chakra-modal'], 'overlay_check_required'), 'decision': 'Dismiss known blockers in reusable helper before action.'},
        {'order': 7, 'check': 'Navigation/data/environment/assertion drift', 'status': classification, 'decision': 'Classify environment/data/product defects separately from safe code self-healing.'},
    ]


def _agentic_rca_for_shard(shard_result: dict[str, Any]) -> dict[str, Any]:
    text = json.dumps(shard_result, ensure_ascii=False)
    status = shard_result.get('status') or ('failed' if shard_result.get('return_code') else 'passed')
    # Important: for a passed shard, do not infer failed specs from the command
    # line or normal application logs.  Older reports showed bogus failed_specs
    # for passed shards because the regex saw test file names in the command.
    failed_specs = [] if status == 'passed' else _extract_failed_specs_from_text(text)
    if not failed_specs and status == 'failed':
        failed_specs = list(shard_result.get('tests') or [])
    classification = 'passed'
    if status == 'failed':
        low = text.lower()
        if 'timeout' in low: classification = 'timeout_or_slow_aut'
        elif 'strict mode violation' in low or 'locator' in low or 'not found' in low: classification = 'locator_or_dom_change'
        elif 'expect' in low or 'assert' in low: classification = 'assertion_or_product_behavior_drift'
        elif 'net::' in low or 'econn' in low or 'certificate' in low: classification = 'environment_network_or_certificate'
        else: classification = 'framework_or_application_failure'
    checklist = _distributed_auditable_rca_checklist(text, classification)
    return {'generated_at': _now(), 'shard_id': shard_result.get('shard_id'), 'agent_id': shard_result.get('agent_id'), 'agent_name': shard_result.get('agent_name'), 'browser': shard_result.get('browser'), 'status': status, 'failed_specs': failed_specs, 'classification': classification, 'auditable_rca_reasoning_checklist': checklist, 'privacy_note': 'Visible RCA checklist of observable checks; not hidden chain-of-thought.', 'parallel_action': 'RCA triage created immediately after shard completion; self-healing can use this before the full distributed run completes.'}


def handle_distributed_agent_completion(job: dict[str, Any]) -> dict[str, Any]:
    meta = job.get('metadata') or {}
    framework_path = meta.get('framework_path') or job.get('working_dir') or ''
    run_id = meta.get('run_id') or 'unknown-run'
    shard = meta.get('shard') or {}
    shard_result = {**shard, 'mode': 'vm_worker_agent', 'job_id': job.get('job_id'), 'agent_id': job.get('agent_id'), 'status': 'passed' if job.get('return_code') == 0 else 'failed', 'return_code': job.get('return_code'), 'stdout_tail': job.get('stdout_tail'), 'stderr_tail': job.get('stderr_tail'), 'completed_at_epoch_ms': job.get('completed_at_epoch_ms')}
    rca = _agentic_rca_for_shard(shard_result)
    # Load and update run state from central or framework folder.
    state_path = _central_run_dir(framework_path, run_id) / 'run-state.json'
    state = _safe_read(state_path, {}) or _safe_read(_framework_run_dir(framework_path, run_id) / 'run-state.json', {}) or {'run_id': run_id, 'framework_path': framework_path, 'plan': {'shards': []}, 'shard_results': [], 'parallel_rca_events': []}
    existing = [r for r in state.get('shard_results', []) if r.get('shard_id') != shard_result.get('shard_id')]
    existing.append(shard_result)
    state['shard_results'] = sorted(existing, key=lambda x: x.get('shard_id') or '')
    state.setdefault('parallel_rca_events', []).append(rca)
    total = len((state.get('plan') or {}).get('shards') or [])
    completed = len(state['shard_results'])
    state['stage'] = 'distributed_node_hub_execution_completed' if total and completed >= total else 'distributed_node_hub_execution_in_progress'
    state['ok'] = all(r.get('status') in {'passed','queued','running'} for r in state.get('shard_results', []))
    state['message'] = f'{completed}/{total or "?"} shard(s) completed. Parallel RCA events: {len(state.get("parallel_rca_events") or [])}.'
    _save_run_state(state)
    write_distributed_report(state)
    append_execution_history(framework_path, {'type': 'parallel_shard_rca', 'run_id': run_id, 'shard_result': shard_result, 'parallel_rca': rca}, mirror_to_framework=True)
    log_event('distributed_execution', f"Parallel RCA completed for {shard_result.get('shard_id')}", status='warning' if shard_result.get('status') == 'failed' else 'ok', progress=100, details=rca)
    return {'ok': True, 'run_id': run_id, 'parallel_rca': rca}


def run_distributed_plan(framework_path: str, selected_tests: str = '', browsers: str = 'chromium,firefox,webkit,msedge,chrome', shard_count: int = 5, agent_ids: str = '', headed: bool = True, run_on_agents: bool = True, worker_workspace_mode: str = 'central_shared_workspace', central_shared_framework_path: str = '', centralize_reports_and_ai_memory: bool = True, execution_target_mode: str = 'central_and_workers', master_worker_name: str = 'Central-VM-Worker', tests_per_shard: int = 0, run_role: str = 'first_run') -> dict[str, Any]:
    plan = create_distributed_plan(framework_path, selected_tests, browsers, shard_count, agent_ids, worker_workspace_mode, central_shared_framework_path, centralize_reports_and_ai_memory, execution_target_mode, master_worker_name, tests_per_shard=tests_per_shard)
    root = Path(plan['framework_path'])
    run_id = 'run-' + _now_id()
    summary = _empty_run_state(run_id, plan)
    _save_run_state(summary)
    try:
        write_distributed_report(summary)
    except Exception as exc:
        summary['initial_report_warning'] = f'{type(exc).__name__}: {exc}'
        _save_run_state(summary)
    is_local_parallel = bool(plan.get('execution_target_mode') == 'central_only' and plan.get('local_parallel_enabled'))
    log_event('distributed_execution', 'Local/VM parallel execution started.' if is_local_parallel else 'Distributed node-hub execution started.', status='running', progress=10, details={'run_id': run_id, 'shards': len(plan.get('shards') or []), 'local_parallel_enabled': is_local_parallel})

    if not plan.get('ok'):
        summary['ok'] = False
        summary['stage'] = 'distributed_plan_has_no_runnable_shards'
        summary['message'] = plan.get('message') or 'No runnable shards were created.'
        _save_run_state(summary)
        return summary

    local_runtime_preflight: dict[str, Any] = {}
    if is_local_parallel:
        try:
            from qa_pipeline.agents.existing_framework_control.controller import _ensure_runtime
            local_runtime_preflight = _ensure_runtime(root, auto_install=True)
        except Exception as exc:
            local_runtime_preflight = {'ok': False, 'error': f'{type(exc).__name__}: {exc}'}
        summary['local_runtime_preflight'] = local_runtime_preflight
        if not local_runtime_preflight.get('ok'):
            summary['ok'] = False
            summary['stage'] = 'local_vm_parallel_runtime_preflight_failed'
            summary['message'] = local_runtime_preflight.get('error') or 'Runtime preflight failed before local/VM parallel browser shards could start.'
            _save_run_state(summary)
            write_distributed_report(summary)
            return summary

    # Runtime test-case counting: this is separate from spec-file count.  It lets
    # the GUI show 1/210, 10/210, etc. while Playwright is running.
    count_reports: list[dict[str, Any]] = []
    if is_local_parallel:
        total_cases = 0
        exact = True
        for shard in plan.get('shards') or []:
            c = _playwright_list_count(root, list(shard.get('tests') or []), str(shard.get('browser') or 'chromium'))
            shard['test_case_count'] = int(c.get('count') or 0)
            shard['test_count_source'] = c.get('source')
            shard['test_count_exact'] = bool(c.get('exact'))
            count_reports.append({'shard_id': shard.get('shard_id'), **c})
            total_cases += int(c.get('count') or 0)
            exact = exact and bool(c.get('exact'))
        plan['total_test_cases'] = total_cases
        plan['test_case_count_exact'] = exact
        plan['test_case_count_reports'] = count_reports
        summary['plan'] = plan
        summary['runtime_test_progress'] = {'completed': 0, 'total': total_cases, 'exact': exact, 'display': f'0/{total_cases}' if total_cases else '0/?', 'per_shard': {}}
        summary['message'] = f'Runtime Playwright test-case progress initialized: 0/{total_cases or "?"}. Script files: {plan.get("total_tests")}. Shards: {len(plan.get("shards") or [])}.'
        _save_run_state(summary)
        try:
            write_distributed_report(summary)
        except Exception as exc:
            summary['progress_report_warning'] = f'{type(exc).__name__}: {exc}'
            _save_run_state(summary)
        log_event('distributed_execution', summary['message'], status='running', progress=15, details={'run_id': run_id, 'test_case_count_reports': count_reports[:20]})

    progress_lock = threading.RLock()
    per_shard_progress: dict[str, dict[str, Any]] = {}

    def _update_runtime_progress(shard_id: str, local_completed: int, local_total: int, line: str) -> None:
        with progress_lock:
            local_total_safe = max(0, int(local_total or 0))
            local_completed_safe = max(0, int(local_completed or 0))
            # Playwright live lines may exceed the denominator when retries are printed
            # (for example [20/12]). Clamp each shard so GUI progress never goes
            # above the real test-case total.
            if local_total_safe:
                local_completed_safe = min(local_completed_safe, local_total_safe)
            per_shard_progress[shard_id] = {'completed': local_completed_safe, 'total': local_total_safe, 'last_line': line[-240:], 'updated_at': _now()}
            completed_cases = sum(int(v.get('completed') or 0) for v in per_shard_progress.values())
            known_total = int(plan.get('total_test_cases') or 0)
            # If Playwright emitted a more reliable local denominator than pre-count, use it.
            live_total = sum(int(v.get('total') or 0) for v in per_shard_progress.values())
            total_cases = max(known_total, live_total)
            percent = int((completed_cases / total_cases) * 100) if total_cases else 0
            summary['runtime_test_progress'] = {
                'completed': completed_cases,
                'total': total_cases,
                'exact': bool(plan.get('test_case_count_exact')),
                'display': f'{completed_cases}/{total_cases}' if total_cases else f'{completed_cases}/?',
                'percent': max(0, min(100, percent)),
                'per_shard': dict(per_shard_progress),
            }
            summary['stage'] = 'local_vm_parallel_distributed_execution_in_progress'
            summary['message'] = f"Runtime Playwright test progress: {summary['runtime_test_progress']['display']} test case(s) completed."
            _save_run_state(summary)
            log_event('distributed_execution', summary['message'], status='running', progress=max(20, min(95, percent)), details={'run_id': run_id, 'shard_id': shard_id, 'line': line[-240:], 'runtime_test_progress': summary['runtime_test_progress']})

    def run_local_shard(shard: dict[str, Any]) -> dict[str, Any]:
        if is_local_parallel:
            return _run_local_parallel_shard_process(root, run_id, shard, headed, progress_callback=_update_runtime_progress if is_local_parallel else None)
        from qa_pipeline.agents.existing_framework_control.controller import execute_existing_framework
        result = execute_existing_framework(framework_path=str(root), project=shard.get('browser') or 'auto', headed=headed, targets='\n'.join(shard['tests']), execution_mode='distributed_local_shard', shards=1, use_mcp_assist=True)
        sr = {**shard, 'mode': 'local_vm_parallel_shard', 'execution': result, 'status': 'passed' if result.get('ok') else 'failed'}
        sr['parallel_rca'] = _agentic_rca_for_shard(sr)
        return sr

    futures = []
    max_local_workers = max(1, min(len(plan.get('shards') or []), 8))
    with ThreadPoolExecutor(max_workers=max_local_workers) as pool:
        for shard in plan.get('shards') or []:
            command = _build_command(root, shard['tests'], shard.get('browser') or 'auto', headed)
            if run_on_agents and shard.get('agent_id') and not shard.get('is_master_worker'):
                agent = next((a for a in (plan.get('online_agents') or []) if a.get('agent_id') == shard.get('agent_id')), {})
                worker_visible_root, workspace_note = resolve_worker_framework_root(central_framework_path=str(root), worker=agent, mode=str(plan.get('worker_workspace_mode') or 'central_shared_workspace'), central_shared_framework_path=str(plan.get('central_shared_framework_path') or ''))
                command_with_env = with_unique_artifact_env(command, run_id=run_id, worker_id=str(shard.get('agent_id') or shard.get('agent_name') or 'worker'), phase=str(shard.get('shard_id') or 'shard'), attempt=0, test_path='shard')
                command_with_env, job_cwd = wrap_command_for_worker_path(command_with_env, worker_visible_root, fallback_working_dir=str(agent.get('workspace_root') or 'C:\\\\'))
                metadata = {'run_id': run_id, 'framework_path': str(root), 'central_framework_path': str(root), 'test_case_count': shard.get('test_case_count'), 'worker_visible_framework_root': worker_visible_root, 'workspace_note': workspace_note, 'worker_workspace_mode': plan.get('worker_workspace_mode'), 'shard': shard, 'parallel_rca': True, 'headed': headed, 'single_consolidated_execution_report': True, 'central_ai_heavy_lifting_only': True, 'worker_ai_disabled': True}
                job = create_agent_job(shard['agent_id'], command=command_with_env, working_dir=job_cwd, job_type='distributed_playwright_shard_agentic', created_by='distributed_gui', metadata=metadata, timeout_seconds=7200)
                summary['shard_results'].append({**shard, 'mode': 'vm_worker_agent_job', 'job': job, 'command': command, 'status': 'queued'})
                log_event('distributed_execution', f"Queued {shard['shard_id']} on {shard.get('agent_name')} for parallel VM execution.", status='running', progress=30, details={'command': command, 'run_id': run_id})
            else:
                futures.append(pool.submit(run_local_shard, shard))
        for fut in as_completed(futures):
            sr = fut.result()
            summary['shard_results'].append(sr)
            summary.setdefault('parallel_rca_events', []).append(sr.get('parallel_rca') or {})
            _save_run_state(summary)

    summary['stage'] = 'local_vm_parallel_distributed_execution_completed' if is_local_parallel else 'distributed_node_hub_execution_started_or_completed'
    summary['run_role'] = run_role
    summary['ok'] = all(r.get('status') in {'queued', 'passed'} for r in summary.get('shard_results', []))
    if is_local_parallel:
        completed = len(summary.get('shard_results') or [])
        failed = len([r for r in summary.get('shard_results') or [] if r.get('status') == 'failed'])
        summary['message'] = f'Local/VM parallel run completed: {completed} browser shard(s), {failed} failed shard(s). Failed-only RCA/self-healing inventory was refreshed from this run.'
    else:
        summary['message'] = 'Distributed node-hub run launched. VM worker shards run asynchronously; local fallback shards completed now. Parallel RCA starts as soon as each shard finishes.'
    if is_local_parallel:
        progress_state = summary.get('runtime_test_progress') or {}
        total_cases = int(progress_state.get('total') or plan.get('total_test_cases') or 0)
        completed_cases = int(progress_state.get('completed') or 0)
        # If no live [n/total] lines were seen, fall back to per-shard totals for finished shard processes.
        if completed_cases == 0 and summary.get('shard_results'):
            completed_cases = sum(int(r.get('test_case_count') or 0) for r in summary.get('shard_results') or [])
        summary['runtime_test_progress'] = {**progress_state, 'completed': completed_cases, 'total': total_cases, 'display': f'{completed_cases}/{total_cases}' if total_cases else f'{completed_cases}/?', 'percent': int((completed_cases / total_cases) * 100) if total_cases else 0, 'run_finished': True}
    report_info = write_distributed_report(summary)
    primary_report = report_info.get('framework_html_report') or report_info.get('central_html_report')
    root_url_path = str(root).replace('\\', '/')
    summary['html_report'] = primary_report
    summary['framework_html_report'] = report_info.get('framework_html_report')
    summary['central_html_report'] = report_info.get('central_html_report')
    summary['framework_report_folder'] = str(_framework_local_reports_dir(str(root)))
    summary['html_report_url'] = '/api/module2/framework-artifact/distributed-report?framework_path=' + _framework_query(str(root))
    summary['central_mirror_report_url'] = '/artifacts/reports/existing-framework/distributed-execution-report.html'
    summary['playwright_html_report_url'] = '/api/module2/framework-artifact/playwright-report?framework_path=' + _framework_query(str(root))
    summary['existing_framework_consolidated_report_url'] = '/artifacts/reports/existing-framework/consolidated-report.html'

    if is_local_parallel:
        summary['failed_inventory_publish'] = _publish_local_parallel_failed_inventory(root, summary, headed, run_role=run_role)
        _save_run_state(summary)
        report_info = write_distributed_report(summary)
        summary['framework_html_report'] = report_info.get('framework_html_report')
        summary['central_html_report'] = report_info.get('central_html_report')
        summary['html_report'] = report_info.get('framework_html_report') or report_info.get('central_html_report')
        summary['playwright_html_report_url'] = '/api/module2/framework-artifact/playwright-report?framework_path=' + _framework_query(str(root))
        summary['existing_framework_consolidated_report_url'] = '/artifacts/reports/existing-framework/consolidated-report.html'

    append_execution_history(str(root), {'type': 'local_vm_parallel_distributed_execution' if is_local_parallel else 'distributed_node_hub_execution', **summary, 'html_report': summary.get('html_report'), 'framework_html_report': summary.get('framework_html_report'), 'central_html_report': summary.get('central_html_report')}, mirror_to_framework=True)
    log_event('distributed_execution', 'Local/VM parallel report generated.' if is_local_parallel else 'Distributed node-hub report generated.', status='done' if summary['ok'] else 'warning', progress=100, details={'framework_report': summary.get('framework_html_report'), 'central_mirror_report': summary.get('central_html_report'), 'failed_inventory_publish': summary.get('failed_inventory_publish')})
    return summary


def _status_class(status: Any) -> str:
    s = str(status or '').lower()
    if s in {'passed', 'expected', 'skipped'}:
        return 'ok'
    if s in {'failed', 'timedout', 'interrupted'}:
        return 'bad'
    return 'warn'


def _failure_reason_from_case(rec: dict[str, Any]) -> str:
    text = json.dumps(rec.get('errors') or rec, ensure_ascii=False).lower()
    if 'element(s) not found' in text or 'locator' in text and 'not found' in text:
        return 'locator is missing or not found in the current DOM'
    if 'strict mode violation' in text:
        return 'locator is ambiguous and matches multiple elements'
    if 'not attached to the dom' in text or 'detached' in text:
        return 'locator became detached from the DOM before the action'
    if 'intercepts pointer events' in text or 'chakra-modal' in text or 'modal' in text or 'overlay' in text:
        return 'element is blocked by a modal, overlay, cookie, permission or page layer'
    if 'timeout' in text or 'timed out' in text or '30000ms exceeded' in text:
        return 'test timed out, likely due to slow AUT, blocked navigation, missing element or long wait'
    if 'tohaveurl' in text or 'received string' in text:
        return 'navigation or URL assertion did not reach the expected page state'
    if 'expected' in text and 'received' in text:
        return 'assertion result is different from expected product behavior/data'
    if text.strip():
        return 'failure evidence is available in trace, screenshot, video or error-context'
    return 'passed'


def _case_line_key(rec: dict[str, Any]) -> tuple[str, int]:
    spec = str(rec.get('spec') or '').replace('\\', '/').lower()
    try:
        line = int(rec.get('line') or 0)
    except Exception:
        line = 0
    return spec, line


def _selector_line_key(target: str) -> tuple[str, int] | None:
    raw = str(target or '').replace('\\', '/').strip().strip('"\'`')
    m = re.search(r'^(.*?\.(?:specs|spec|test)\.(?:ts|tsx|js|jsx|mjs|cjs)):(\d+)(?::\d+)?$', raw, flags=re.I)
    if not m:
        return None
    spec = re.sub(r'^.*?(?=tests/)', '', m.group(1)).replace('//', '/').lower()
    try:
        return spec, int(m.group(2))
    except Exception:
        return spec, 0


def _native_report_link(framework_path: str, run_id: str, shard_id: str) -> str:
    return f"/api/module2/framework-artifact/distributed-shard-report?framework_path={_framework_query(framework_path)}&run_id={urllib.parse.quote(str(run_id or ''))}&shard_id={urllib.parse.quote(str(shard_id or ''))}"


def _write_exact_distributed_playwright_reports(root: Path, summary: dict[str, Any], inventory: dict[str, Any]) -> dict[str, Any]:
    """Write first-run exact Playwright report index + test-case ledger.

    Native Playwright HTML stays inside every shard folder.  This report links those
    exact native reports and gives management/users the missing summary: executed,
    passed, failed, and unresolved selectors.
    """
    framework_path = str(root)
    run_id = str(summary.get('run_id') or '')
    local_reports = _framework_local_reports_dir(framework_path)
    local_reports.mkdir(parents=True, exist_ok=True)
    CENTRAL_REPORT_DIR.mkdir(parents=True, exist_ok=True)

    all_cases = list(inventory.get('all_test_cases') or [])
    passed_cases = list(inventory.get('passed_test_cases') or [])
    failed_cases = list(inventory.get('failed_test_cases') or [])
    planned_targets: list[str] = []
    for sr in summary.get('shard_results') or []:
        planned_targets.extend([str(x).replace('\\','/') for x in (sr.get('tests') or [])])
    planned_count = len(planned_targets)
    actual_count = len(all_cases)
    failed_count = len(failed_cases)
    passed_count = len(passed_cases)

    actual_line_keys = {_case_line_key(r) for r in all_cases if _case_line_key(r)[1]}
    unresolved_targets = []
    for target in planned_targets:
        key = _selector_line_key(target)
        if key and key not in actual_line_keys:
            unresolved_targets.append({
                'target': target,
                'reason': 'This selected line target was not reported by Playwright JSON. It may be inside a skipped/conditional test, filtered out by project/config, not a runnable test declaration line, or not selected by Playwright after retries/config resolution.'
            })
    if not unresolved_targets and planned_count > actual_count:
        unresolved_targets.append({
            'target': f'{planned_count - actual_count} target(s)',
            'reason': 'The plan/static fallback counted more selected targets than Playwright actually reported. Use the native shard reports to confirm skipped/filtered tests or non-runnable line selectors.'
        })

    case_rows = []
    for rec in all_cases:
        status = str(rec.get('status') or 'unknown').lower()
        reason = _failure_reason_from_case(rec) if status in {'failed','timedout','interrupted'} else 'passed'
        line = rec.get('line') or ''
        case_rows.append(
            f"<tr><td><code>{_html_escape(rec.get('spec'))}</code></td><td>{_html_escape(line)}</td><td>{_html_escape(rec.get('title') or '(whole spec fallback)')}</td><td class='{_status_class(status)}'>{_html_escape(status)}</td><td>{_html_escape(reason)}</td></tr>"
        )
    unresolved_rows = ''.join(f"<tr><td><code>{_html_escape(u.get('target'))}</code></td><td>{_html_escape(u.get('reason'))}</td></tr>" for u in unresolved_targets)
    shard_rows = []
    for sr in summary.get('shard_results') or []:
        sid = str(sr.get('shard_id') or '')
        status = str(sr.get('status') or 'unknown')
        link = _native_report_link(framework_path, run_id, sid) if sid else '#'
        parsed_count = len([c for c in all_cases if str(c.get('shard_id') or '') == sid])
        # Per-shard parsed count is often not available in case records; fall back to live total/status data.
        prog = ((summary.get('runtime_test_progress') or {}).get('per_shard') or {}).get(sid) or {}
        live_display = f"{prog.get('completed','?')}/{prog.get('total','?')}"
        shard_rows.append(f"<tr><td>{_html_escape(sid)}</td><td class='{_status_class(status)}'>{_html_escape(status)}</td><td>{_html_escape(sr.get('test_case_count') or '')}</td><td>{_html_escape(live_display)}</td><td><a target='_blank' href='{link}'>Open exact native Playwright HTML for this shard</a></td><td><code>{_html_escape(sr.get('json_report') or '')}</code></td></tr>")

    summary_card = {
        'run_id': run_id,
        'framework_path': framework_path,
        'planned_selected_targets': planned_count,
        'playwright_reported_test_cases': actual_count,
        'passed_test_cases': passed_count,
        'failed_test_cases': failed_count,
        'unresolved_or_not_reported_targets': len(unresolved_targets),
        'native_shard_report_count': len(summary.get('shard_results') or []),
        'unresolved_targets': unresolved_targets[:200],
    }
    body = f"""<!doctype html><html><head><meta charset='utf-8'/><title>Exact First Run Playwright Report Index</title>
<style>body{{font-family:Segoe UI,Arial,sans-serif;background:#f8fafc;color:#0f172a;margin:24px}}.card{{background:white;border:1px solid #dbe3ef;border-radius:14px;padding:16px;margin:14px 0}}table{{width:100%;border-collapse:collapse;background:white}}th,td{{border:1px solid #cbd5e1;padding:8px;vertical-align:top}}th{{background:#1e293b;color:white}}code{{background:#0f172a;color:#dbeafe;padding:2px 6px;border-radius:6px}}.ok{{color:#16a34a;font-weight:800}}.bad{{color:#dc2626;font-weight:800}}.warn{{color:#b45309;font-weight:800}}pre{{white-space:pre-wrap;background:#0f172a;color:#dbeafe;padding:10px;border-radius:8px;max-height:360px;overflow:auto}}</style></head><body>
<h1>Exact First Run Playwright Report Index</h1>
<div class='card'><p>This page does not replace Playwright native HTML. It links the exact native HTML generated inside every shard and gives an accurate first-run ledger.</p><pre>{_html_escape(json.dumps(summary_card, indent=2, ensure_ascii=False))}</pre></div>
<div class='card'><h2>Summary</h2><p><b>Planned selected targets:</b> {planned_count} &nbsp; <b>Playwright reported/runnable tests:</b> {actual_count} &nbsp; <b>Passed:</b> <span class='ok'>{passed_count}</span> &nbsp; <b>Failed:</b> <span class='bad'>{failed_count}</span> &nbsp; <b>Unresolved/not reported:</b> <span class='warn'>{len(unresolved_targets)}</span></p><p>If unresolved targets are shown, they are not hidden failures; they are selected line targets or static estimates that Playwright did not report as runnable tests. Open the shard-native reports to verify project filters, skipped tests, line selector accuracy, and config behavior.</p></div>
<div class='card'><h2>Shard-native Playwright HTML reports</h2><table><thead><tr><th>Shard</th><th>Status</th><th>Planned/runnable count</th><th>Live completed/total</th><th>Native Playwright HTML</th><th>JSON report</th></tr></thead><tbody>{''.join(shard_rows) or '<tr><td colspan="6">No shard reports found.</td></tr>'}</tbody></table></div>
<div class='card'><h2>Unresolved / not-reported selected targets</h2><table><thead><tr><th>Target</th><th>Reason</th></tr></thead><tbody>{unresolved_rows or '<tr><td colspan="2">None. Playwright reported all selected runnable tests.</td></tr>'}</tbody></table></div>
<div class='card'><h2>Test-by-test first-run ledger</h2><table><thead><tr><th>Spec</th><th>Line</th><th>Test title</th><th>Status</th><th>Plain English reason</th></tr></thead><tbody>{''.join(case_rows) or '<tr><td colspan="5">No test-case records were available. Check shard-native reports.</td></tr>'}</tbody></table></div>
</body></html>"""
    local_file = local_reports / 'first-run-playwright-report.html'
    central_file = CENTRAL_REPORT_DIR / 'first-run-playwright-report.html'
    local_json = local_reports / 'first-run-playwright-report.json'
    central_json = CENTRAL_REPORT_DIR / 'first-run-playwright-report.json'
    for f in [local_file, central_file]:
        f.write_text(body, encoding='utf-8')
    for f in [local_json, central_json]:
        _write(f, {'summary': summary_card, 'all_test_cases': all_cases, 'failed_test_cases': failed_cases, 'passed_test_cases': passed_cases})
    return {
        'ok': True,
        'summary': summary_card,
        'framework_first_run_report': str(local_file),
        'central_first_run_report': str(central_file),
        'first_run_report_url': '/artifacts/reports/existing-framework/first-run-playwright-report.html',
    }

def get_distributed_run_status(framework_path: str = '', run_id: str = '') -> dict[str, Any]:
    framework_path = str(framework_path or '')
    candidates = []
    if run_id and framework_path:
        candidates += [_central_run_dir(framework_path, run_id) / 'run-state.json', _framework_run_dir(framework_path, run_id) / 'run-state.json']
    if framework_path:
        candidates += [_framework_local_reports_dir(framework_path) / 'active-distributed-run.json']
    candidates += [CENTRAL_REPORT_DIR / 'active-distributed-run.json']
    for p in candidates:
        data = _safe_read(p, {})
        if data:
            write_distributed_report(data)
            return {'ok': True, 'run_state': data, 'message': data.get('message') or 'Distributed run state loaded.'}
    return {'ok': False, 'message': 'No active distributed run state found yet.'}


def _framework_query(framework_path: str) -> str:
    return urllib.parse.quote(str(framework_path or '').replace('\\', '/'), safe='')


def _write_central_playwright_report_landing(summary: dict[str, Any], distributed_report_body: str = '') -> None:
    """Keep the GUI's existing Open Playwright report button alive after distributed runs."""
    framework_path = str(summary.get('framework_path') or '')
    run_id = str(summary.get('run_id') or '')
    encoded_framework = _framework_query(framework_path)
    html_dir = CENTRAL_REPORT_DIR / 'html'
    html_dir.mkdir(parents=True, exist_ok=True)
    shard_rows: list[str] = []
    for sr in summary.get('shard_results') or []:
        sid = str(sr.get('shard_id') or '')
        if sid:
            link = f"/api/module2/framework-artifact/distributed-shard-report?framework_path={encoded_framework}&run_id={urllib.parse.quote(run_id)}&shard_id={urllib.parse.quote(sid)}"
            report_cell = f"<a href='{link}' target='_blank'>Open shard Playwright report</a>"
        else:
            report_cell = _html_escape(sr.get('html_report') or 'not available')
        tests = '<br/>'.join(_html_escape(t) for t in (sr.get('tests') or []))
        shard_rows.append(
            f"<tr><td>{_html_escape(sid)}</td><td>{_html_escape(sr.get('agent_name') or sr.get('agent_id') or 'local/central VM')}</td>"
            f"<td>{_html_escape(sr.get('browser') or '')}</td><td>{_html_escape(sr.get('status') or 'queued')}</td><td>{report_cell}</td><td><pre>{tests}</pre></td></tr>"
        )
    distributed_link = f"/api/module2/framework-artifact/distributed-report?framework_path={encoded_framework}" if framework_path else '/artifacts/reports/existing-framework/distributed-execution-report.html'
    exact_info = summary.get('exact_first_run_playwright_report') or (((summary.get('failed_inventory_publish') or {}).get('failed_test_inventory') or {}).get('exact_first_run_playwright_report') or {})
    exact_link = exact_info.get('first_run_report_url') if isinstance(exact_info, dict) else ''
    exact_html = f"<p><a href='{_html_escape(exact_link)}' target='_blank'>Open exact first-run Playwright shard report index</a></p>" if exact_link else ''
    native_note = 'Native Playwright HTML is kept per shard for distributed execution. This page is the single GUI-safe Playwright report entry point and does not overwrite RCA, self-healing, or Log & Reports artifacts.'
    landing = f"""<!doctype html><html><head><meta charset='utf-8'/><title>AstraHeal Playwright Report</title>
<style>body{{font-family:Segoe UI,Arial,sans-serif;background:#f8fafc;color:#0f172a;margin:24px}}.card{{background:#fff;border:1px solid #cbd5e1;border-radius:14px;padding:16px;margin:14px 0}}table{{width:100%;border-collapse:collapse;background:#fff}}td,th{{border:1px solid #cbd5e1;padding:8px;vertical-align:top}}th{{background:#1e293b;color:#fff}}pre{{white-space:pre-wrap;max-height:180px;overflow:auto;background:#0f172a;color:#d1fae5;padding:8px;border-radius:8px}}a{{color:#2563eb;font-weight:700}}</style></head><body>
<h1>AstraHeal Playwright Report</h1>
<div class='card'><p>{_html_escape(native_note)}</p><p><b>Run ID:</b> {_html_escape(run_id)}<br/><b>Framework:</b> {_html_escape(framework_path)}<br/><b>Status:</b> {_html_escape(summary.get('stage') or '')}</p><p><a href='{distributed_link}' target='_blank'>Open single consolidated distributed execution report</a></p>{exact_html}</div>
<div class='card'><h2>Shard-native Playwright reports</h2><table><thead><tr><th>Shard</th><th>Worker</th><th>Browser</th><th>Status</th><th>Native report</th><th>Scripts</th></tr></thead><tbody>{''.join(shard_rows) or '<tr><td colspan="6">No shard results are available yet. Refresh status after execution starts.</td></tr>'}</tbody></table></div>
<div class='card'><h2>Raw run summary</h2><pre>{_html_escape(json.dumps(summary, indent=2, ensure_ascii=False)[:20000])}</pre></div>
</body></html>"""
    (html_dir / 'index.html').write_text(landing, encoding='utf-8')
    # Important: do NOT write consolidated-report.html here.
    # consolidated-report.html is reserved for the business matrix: first run +
    # failed-only rerun iteration 1 + failed-only rerun iteration 2.  Older
    # builds overwrote it with the distributed execution report, so the
    # "Open combined first-run + rerun report" button opened the wrong page
    # after a later distributed status refresh.  Distributed reports now remain
    # under distributed-execution-report.html and the Playwright router/landing.
    _write(CENTRAL_REPORT_DIR / 'playwright-report-router.json', summary)


def write_distributed_report(summary: dict[str, Any]) -> dict[str, str]:
    CENTRAL_REPORT_DIR.mkdir(parents=True, exist_ok=True)
    rows = []
    for s in summary.get('shard_results') or []:
        rca = s.get('parallel_rca') or {}
        if not rca and s.get('job'):
            rca = {'note': 'VM worker job is queued/running. RCA will appear after the agent completes this shard.'}
        rows.append(f"<tr><td>{s.get('shard_id')}</td><td>{s.get('agent_name') or s.get('agent_id') or 'local VM'}</td><td>{s.get('browser')}</td><td>{s.get('test_count')}</td><td>{s.get('status')}</td><td><pre>{'<br/>'.join(s.get('tests') or [])}</pre></td><td><pre>{json.dumps(rca, indent=2, ensure_ascii=False)[:4000]}</pre></td><td><pre>{json.dumps(s.get('job') or s.get('execution') or {}, indent=2, ensure_ascii=False)[:4000]}</pre></td></tr>")
    rca_rows = []
    for r in summary.get('parallel_rca_events') or []:
        rca_rows.append(f"<li><b>{r.get('shard_id')}</b> / {r.get('agent_name') or r.get('agent_id')}: {r.get('classification')} — failed specs: {', '.join(r.get('failed_specs') or [])}</li>")
    framework_path = str(summary.get('framework_path') or '')
    progress_state = summary.get('runtime_test_progress') or {}
    progress_display = _html_escape(progress_state.get('display') or '0/?')
    progress_percent = _html_escape(progress_state.get('percent') if progress_state.get('percent') is not None else '')
    progress_exact = 'exact from Playwright --list' if progress_state.get('exact') else 'best effort / static fallback when exact list was unavailable'
    per_shard_progress_rows = []
    for sid, info in (progress_state.get('per_shard') or {}).items():
        per_shard_progress_rows.append(f"<tr><td>{_html_escape(sid)}</td><td>{_html_escape(info.get('completed'))}/{_html_escape(info.get('total'))}</td><td><pre>{_html_escape(info.get('last_line') or '')}</pre></td></tr>")
    inv_summary = (((summary.get('failed_inventory_publish') or {}).get('failed_test_inventory') or {}).get('exact_first_run_playwright_report') or summary.get('exact_first_run_playwright_report') or {})
    inv_counts = (inv_summary.get('summary') or {}) if isinstance(inv_summary, dict) else {}
    exact_link = inv_summary.get('first_run_report_url') if isinstance(inv_summary, dict) else ''
    progress_extra = ''
    if inv_counts:
        progress_extra = f"<p><b>Actual Playwright-reported tests:</b> {_html_escape(inv_counts.get('playwright_reported_test_cases'))} &nbsp; <b>Passed:</b> <span style='color:#16a34a;font-weight:800'>{_html_escape(inv_counts.get('passed_test_cases'))}</span> &nbsp; <b>Failed:</b> <span style='color:#dc2626;font-weight:800'>{_html_escape(inv_counts.get('failed_test_cases'))}</span> &nbsp; <b>Unresolved/not reported:</b> <span style='color:#b45309;font-weight:800'>{_html_escape(inv_counts.get('unresolved_or_not_reported_targets'))}</span></p>"
    if exact_link:
        progress_extra += f"<p><a href='{_html_escape(exact_link)}' target='_blank'>Open exact first-run Playwright shard report index</a></p>"
    progress_card = f"""<div class='note'><h2>Runtime Playwright test-case progress</h2><p><b>{progress_display}</b> test case(s) completed. <b>Percent:</b> {progress_percent}% &nbsp; <b>Count source:</b> {_html_escape(progress_exact)}</p>{progress_extra}<p>This is test-case progress, not only spec-file progress. If static fallback over-counted line selectors, the exact first-run report explains unresolved/not-reported targets.</p><table><thead><tr><th>Shard</th><th>Live completed/total</th><th>Last Playwright progress line</th></tr></thead><tbody>{''.join(per_shard_progress_rows) or '<tr><td colspan="3">No live Playwright [n/total] progress lines captured yet. Refresh while execution is running.</td></tr>'}</tbody></table></div>"""
    framework_report = ''
    central_report = CENTRAL_REPORT_DIR / 'distributed-execution-report.html'
    report_body = f"""<!doctype html><html><head><meta charset='utf-8'/><title>Distributed Node-Hub Execution Report</title>
<style>body{{font-family:Segoe UI,Arial,sans-serif;background:#f8fafc;margin:24px;color:#111827}}table{{width:100%;border-collapse:collapse;background:white}}td,th{{border:1px solid #cbd5e1;padding:8px;vertical-align:top}}th{{background:#312e81;color:white}}pre{{white-space:pre-wrap;max-height:260px;overflow:auto;background:#0f172a;color:#d1fae5;padding:8px;border-radius:6px}}.note{{background:#ecfeff;border:1px solid #67e8f9;padding:12px;border-radius:10px;margin:12px 0}}.warn{{background:#fff7ed;border:1px solid #fb923c;padding:12px;border-radius:10px;margin:12px 0}}</style></head><body><h1>Single Consolidated Distributed Node-Hub Execution Report</h1><div class='note'><b>Architecture:</b> Local PC/Central VM parallel mode runs multiple browser shards on the same machine. VM/VDI node-hub mode keeps Central VM as the source-of-truth for framework/RAG/RCA/self-healing/reports while worker agents execute browser shards. RCA starts as soon as each shard completes, not only after the full run. <b>Worker AI role:</b> evidence only; all source patching and provider-based AI heavy lifting stay on the Central VM.</div>{progress_card}<p>{summary.get('message')}</p><p><b>Run ID:</b> {summary.get('run_id')} &nbsp; <b>Framework:</b> {framework_path}</p><p><b>Spec files:</b> {(summary.get('plan') or {}).get('total_tests')} &nbsp; <b>Test cases:</b> {(summary.get('plan') or {}).get('total_test_cases') or (progress_state.get('total') or '?')} &nbsp; <b>Shards:</b> {len((summary.get('plan') or {}).get('shards') or [])} &nbsp; <b>Completed/queued shard rows:</b> {len(summary.get('shard_results') or [])}</p><div class='warn'><h2>Parallel RCA/self-healing triage</h2><ul>{''.join(rca_rows) or '<li>No parallel RCA events yet. Refresh after VM worker shards complete.</li>'}</ul></div><table><thead><tr><th>Shard</th><th>Execution worker</th><th>Browser</th><th>Spec files</th><th>Status</th><th>Test Scripts</th><th>Parallel RCA</th><th>Execution/Job Details</th></tr></thead><tbody>{''.join(rows) or '<tr><td colspan="8">No shard results found.</td></tr>'}</tbody></table></body></html>"""
    central_report.write_text(report_body, encoding='utf-8')
    try:
        (CENTRAL_REPORT_DIR / 'single-consolidated-distributed-execution-report.html').write_text(report_body, encoding='utf-8')
    except Exception:
        pass
    try:
        if framework_path:
            local_reports = _framework_local_reports_dir(framework_path)
            local_reports.mkdir(parents=True, exist_ok=True)
            framework_file = local_reports / 'distributed-execution-report.html'
            framework_file.write_text(report_body, encoding='utf-8')
            (local_reports / 'single-consolidated-distributed-execution-report.html').write_text(report_body, encoding='utf-8')
            _write(local_reports / 'distributed-execution-report.json', summary)
            _write(local_reports / 'single-consolidated-distributed-execution-report.json', summary)
            framework_report = str(framework_file)
    except Exception as exc:
        summary['framework_report_warning'] = f'{type(exc).__name__}: {exc}'
    try:
        _write(CENTRAL_REPORT_DIR / 'distributed-execution-report.json', summary)
    except Exception:
        pass
    try:
        _write_central_playwright_report_landing(summary, report_body)
    except Exception as exc:
        summary['central_playwright_landing_warning'] = f'{type(exc).__name__}: {exc}'
    return {'framework_html_report': framework_report, 'central_html_report': str(central_report), 'central_playwright_landing': str(CENTRAL_REPORT_DIR / 'html' / 'index.html'), 'central_consolidated_report': str(CENTRAL_REPORT_DIR / 'consolidated-report.html')}
