from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from qa_pipeline.core.paths import QA_CACHE_DIR, REPO_ROOT
from qa_pipeline.core.text import safe_id

ACTIVE_CONTEXT_FILE = QA_CACHE_DIR / 'active_source_context.json'


def _rel(path: str | Path) -> str:
    try:
        return str(Path(path).relative_to(REPO_ROOT))
    except Exception:
        return str(path)


def safe_feature(value: str) -> str:
    value = safe_id(value or 'feature')
    return value.strip('_') or 'feature'


def write_active_context(context: dict[str, Any]) -> dict[str, Any]:
    QA_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    context = dict(context)
    context.setdefault('version', 1)
    context.setdefault('active', True)
    context['features'] = [safe_feature(str(f)) for f in context.get('features', []) if str(f).strip()]
    context['source_type'] = context.get('source_type') or 'srs'
    ACTIVE_CONTEXT_FILE.write_text(json.dumps(context, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    return context


def read_active_context() -> dict[str, Any]:
    if not ACTIVE_CONTEXT_FILE.exists():
        return {}
    try:
        data = json.loads(ACTIVE_CONTEXT_FILE.read_text(encoding='utf-8'))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def clear_active_context(reason: str = '') -> dict[str, Any]:
    ctx = {'active': False, 'reason': reason}
    return write_active_context(ctx)


def matches_active_context(feature: str, source_type: str = '') -> bool:
    ctx = read_active_context()
    if not ctx.get('active'):
        return False
    feature = safe_feature(feature)
    source_type = (source_type or '').strip()
    if source_type and ctx.get('source_type') and source_type != ctx.get('source_type'):
        # tolerate Jira UI values that are equivalent
        if not ({source_type, ctx.get('source_type')} <= {'jira', 'jira_epics'}):
            return False
    candidates = {safe_feature(str(ctx.get('parent_feature', ''))), safe_feature(str(ctx.get('requested_feature', ''))), safe_feature(str(ctx.get('epic_key', '')))}
    candidates.update(safe_feature(str(f)) for f in ctx.get('features', []) or [])
    return feature in candidates


def active_features_for_request(feature: str, source_type: str = '') -> list[str]:
    ctx = read_active_context()
    if matches_active_context(feature, source_type):
        return [safe_feature(str(f)) for f in ctx.get('features', []) or []]
    return []
