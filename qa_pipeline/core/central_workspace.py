from __future__ import annotations

import re
from pathlib import Path
from typing import Any


def is_windows_unc(path: str) -> bool:
    raw = str(path or "").strip()
    return raw.startswith('\\\\') or raw.startswith('//')


def safe_worker_id(value: str) -> str:
    return re.sub(r'[^A-Za-z0-9_.-]+', '-', str(value or 'worker')).strip('-') or 'worker'


def normalize_workspace_mode(value: str) -> str:
    raw = str(value or '').strip().lower().replace('-', '_').replace(' ', '_')
    aliases = {
        'central': 'central_shared_workspace',
        'central_share': 'central_shared_workspace',
        'share': 'central_shared_workspace',
        'smb': 'central_shared_workspace',
        'unc': 'central_shared_workspace',
        'worker': 'worker_local_framework',
        'worker_local': 'worker_local_framework',
        'local_copy': 'worker_local_framework',
        'existing': 'worker_local_framework',
        'remote_browser': 'remote_browser_controlled_by_central',
        'browser_only': 'remote_browser_controlled_by_central',
    }
    return aliases.get(raw, raw or 'central_shared_workspace')


def resolve_worker_framework_root(*, central_framework_path: str, worker: dict[str, Any], mode: str, central_shared_framework_path: str = '') -> tuple[str, str]:
    """Return (worker_visible_framework_root, explanation).

    The central framework path remains the source of truth for RAG/RCA/fixes/reports.
    The worker visible path is only the location from which the worker process runs tests.
    """
    mode = normalize_workspace_mode(mode)
    if worker.get('is_master_worker'):
        return str(Path(central_framework_path).expanduser().resolve()), 'central VM master worker uses the local source-of-truth framework path'

    if mode == 'central_shared_workspace':
        if central_shared_framework_path:
            return central_shared_framework_path.strip(), 'remote worker runs from central VM SMB/UNC shared framework path; no permanent worker copy is required'
        ws = str(worker.get('workspace_root') or '').strip()
        if ws.startswith('\\\\') or ws.startswith('//'):
            return ws, 'remote worker uses its registered UNC workspace root as the central shared framework path'
        return str(central_framework_path), 'central shared framework path was not provided; command may fail unless worker can see the central path'

    if mode == 'worker_local_framework':
        ws = str(worker.get('framework_path') or worker.get('workspace_root') or '').strip()
        return ws or str(central_framework_path), 'remote worker uses its own registered framework/workspace path; this preserves the previous behavior'

    if mode == 'remote_browser_controlled_by_central':
        return str(Path(central_framework_path).expanduser().resolve()), 'remote-browser mode keeps test runner on central VM; worker hosts only browser endpoint (advanced fixture support required)'

    # Future modes such as ephemeral snapshot can be added here without changing callers.
    return str(central_framework_path), f'unknown workspace mode {mode}; falling back to central framework path'


def with_unique_artifact_env(command: str, *, run_id: str, worker_id: str, phase: str, attempt: int, test_path: str = '') -> str:
    """Prefix Playwright/Cucumber commands with per-worker artifact folders.

    This prevents multiple workers from writing to the same html/json output folders on
    a central shared framework path.
    """
    safe_worker = safe_worker_id(worker_id)
    safe_phase = safe_worker_id(phase)
    safe_test = safe_worker_id(Path(str(test_path or 'test')).stem)[:48]
    base = f'.aiqa-history\\worker-artifacts\\{safe_worker_id(run_id)}\\{safe_worker}\\{safe_phase}-attempt-{int(attempt)+1}-{safe_test}'
    # Playwright HTML/JSON reporters understand these environment variables. Cucumber
    # reports may still use framework-specific report paths; the base env is exposed so
    # custom framework scripts can route artifacts into this folder when configured.
    return (
        f'set AIQA_WORKER_ARTIFACT_DIR={base}&& '
        f'set PLAYWRIGHT_HTML_OUTPUT_DIR={base}\\html&& '
        f'set PLAYWRIGHT_JSON_OUTPUT_NAME={base}\\results.json&& '
        f'set PLAYWRIGHT_HTML_OPEN=never&& '
        f'{command}'
    )


def wrap_command_for_worker_path(command: str, worker_visible_framework_root: str, fallback_working_dir: str = '') -> tuple[str, str]:
    """Return (command, working_dir) for the runner agent.

    For UNC paths, running cmd.exe with a UNC cwd can be unreliable. `pushd` maps
    the share to a temporary drive letter for the lifetime of the command.
    """
    root = str(worker_visible_framework_root or '').strip()
    fallback = str(fallback_working_dir or '').strip() or 'C:\\'
    if is_windows_unc(root):
        escaped = root.replace('"', '')
        return f'pushd "{escaped}" && {command} & set AIQA_RC=%ERRORLEVEL% & popd & exit /b %AIQA_RC%', fallback
    if root:
        return command, root
    return command, fallback
