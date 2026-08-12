from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

IGNORE_DIRS = {
    'node_modules', '.git', 'dist', 'build', 'coverage', 'playwright-report', 'test-results',
    'reports', '.next', '.qa-cache', '.aiqa-history', '.codex-backups', 'graphify-out',
    '%appdata%', '%AppData%', '.npm', 'npm-cache',
}
RELEVANT_SUFFIXES = {
    '.ts', '.tsx', '.js', '.jsx', '.mjs', '.cjs', '.json', '.feature', '.md', '.yml', '.yaml',
    '.env', '.txt', '.csv', '.xml', '.properties', '.sh', '.ps1', '.cmd',
}
IMPORTANT_NAMES = {
    'package.json', 'package-lock.json', 'npm-shrinkwrap.json', 'pnpm-lock.yaml', 'yarn.lock',
    'tsconfig.json', 'jsconfig.json', 'playwright.config.ts', 'playwright.config.js',
    'playwright.config.mjs', 'playwright.config.cjs', 'cucumber.js', '.npmrc',
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def framework_cache_root(root: str | Path) -> Path:
    return Path(root).expanduser().resolve() / '.qa-cache' / 'existing-framework'


def compute_framework_fingerprint(root: str | Path, *, limit: int = 20000) -> dict[str, Any]:
    base = Path(root).expanduser().resolve()
    digest = hashlib.sha256()
    count = 0
    latest_mtime_ns = 0
    config_digest = hashlib.sha256()
    for current, dirs, names in os.walk(base):
        dirs[:] = sorted(d for d in dirs if d not in IGNORE_DIRS and d.lower() not in {x.lower() for x in IGNORE_DIRS})
        for name in sorted(names):
            path = Path(current) / name
            suffix = path.suffix.lower()
            if name not in IMPORTANT_NAMES and suffix not in RELEVANT_SUFFIXES:
                continue
            try:
                rel = path.relative_to(base).as_posix()
                stat = path.stat()
            except Exception:
                continue
            count += 1
            latest_mtime_ns = max(latest_mtime_ns, int(stat.st_mtime_ns))
            record = f'{rel}\0{stat.st_size}\0{stat.st_mtime_ns}\n'.encode('utf-8', errors='ignore')
            digest.update(record)
            if name in IMPORTANT_NAMES or rel.startswith('.github/'):
                try:
                    data = path.read_bytes()[:2_000_000]
                except Exception:
                    data = b''
                config_digest.update(rel.encode('utf-8', errors='ignore') + b'\0' + data)
            if count >= limit:
                break
        if count >= limit:
            break
    return {
        'fingerprint': digest.hexdigest(),
        'config_fingerprint': config_digest.hexdigest(),
        'file_count': count,
        'latest_mtime_ns': latest_mtime_ns,
        'root': str(base),
        'computed_at': _now(),
        'limit_reached': count >= limit,
    }


def load_json(path: Path, default: Any = None) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding='utf-8', errors='replace'))
    except Exception:
        pass
    return default


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str) + '\n', encoding='utf-8')


def load_matching_cache(root: str | Path, filename: str, *, fingerprint: dict[str, Any] | None = None) -> dict[str, Any] | None:
    base = Path(root).expanduser().resolve()
    fp = fingerprint or compute_framework_fingerprint(base)
    cached = load_json(framework_cache_root(base) / filename, {}) or {}
    if cached.get('fingerprint') != fp.get('fingerprint'):
        return None
    payload = cached.get('payload')
    if not isinstance(payload, dict):
        return None
    payload = dict(payload)
    payload['cache_hit'] = True
    payload['cache_fingerprint'] = fp.get('fingerprint')
    payload['cache_file_count'] = fp.get('file_count')
    payload['cache_saved_at'] = cached.get('saved_at')
    return payload


def save_cache(root: str | Path, filename: str, payload: dict[str, Any], *, fingerprint: dict[str, Any] | None = None) -> Path:
    base = Path(root).expanduser().resolve()
    fp = fingerprint or compute_framework_fingerprint(base)
    target = framework_cache_root(base) / filename
    write_json(target, {
        'schema_version': 1,
        'saved_at': _now(),
        'fingerprint': fp.get('fingerprint'),
        'config_fingerprint': fp.get('config_fingerprint'),
        'file_count': fp.get('file_count'),
        'payload': payload,
    })
    return target
