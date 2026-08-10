from __future__ import annotations

import html
import io
import json
import os
import re
import shutil
import subprocess
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from qa_pipeline.agents.existing_framework_control.deep_framework_agents import build_deep_framework_understanding
from qa_pipeline.agents.existing_framework_control.structure_discovery import build_structure_profile
from qa_pipeline.core.active_context import write_active_context
from qa_pipeline.core.io import read_json, write_json
from qa_pipeline.core.paths import QA_CACHE_DIR, REPO_ROOT, feature_testcase_path
from qa_pipeline.agentic.functional_walkthrough import load_walkthrough_evidence, walkthrough_enhanced_testcase_path
from qa_pipeline.agentic.browser_grounded_generation import load_grounded_payload
from qa_pipeline.modules.playwright_ts_generator.codegen_capture import load_codegen_enhanced_payload, latest_codegen_capture
from qa_pipeline.core.runtime_logger import log_event
from qa_pipeline.core.commands import run_command
from qa_pipeline.core.operation_control import check_cancelled
from qa_pipeline.core.text import camel_case, pascal_case, safe_id
from qa_pipeline.agents.phase2_source_intake_rag.ingest import write_functional_testcases_markdown

_TEXT_EXTENSIONS = {'.txt', '.md', '.markdown', '.json', '.csv', '.yaml', '.yml', '.feature'}
_CODE_EXTENSIONS = {'.ts', '.tsx', '.js', '.jsx', '.mjs', '.cjs'}
_VALID_LOCATOR_ROLES = {
    'alert', 'alertdialog', 'application', 'article', 'banner', 'blockquote', 'button', 'caption',
    'cell', 'checkbox', 'code', 'columnheader', 'combobox', 'complementary', 'contentinfo',
    'definition', 'deletion', 'dialog', 'directory', 'document', 'emphasis', 'feed', 'figure',
    'form', 'generic', 'grid', 'gridcell', 'group', 'heading', 'img', 'insertion', 'link', 'list',
    'listbox', 'listitem', 'log', 'main', 'marquee', 'math', 'meter', 'menu', 'menubar',
    'menuitem', 'menuitemcheckbox', 'menuitemradio', 'navigation', 'none', 'note', 'option',
    'paragraph', 'presentation', 'progressbar', 'radio', 'radiogroup', 'region', 'row', 'rowgroup',
    'rowheader', 'scrollbar', 'search', 'searchbox', 'separator', 'slider', 'spinbutton', 'status',
    'strong', 'subscript', 'superscript', 'switch', 'tab', 'table', 'tablist', 'tabpanel', 'term',
    'textbox', 'time', 'timer', 'toolbar', 'tooltip', 'tree', 'treegrid', 'treeitem',
}


def _safe_feature(value: str) -> str:
    return re.sub(r'[^a-z0-9_-]+', '_', (value or 'feature').strip().lower()).strip('_') or 'feature'


def _rel(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _resolve_under_root(root: Path, value: str, *, allow_missing: bool = True) -> Path | None:
    raw = (value or '').strip().strip('"').strip("'")
    if not raw:
        return None
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        candidate = root / candidate
    candidate = candidate.resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(f'Path must remain inside the selected framework: {raw}') from exc
    if not allow_missing and not candidate.exists():
        raise ValueError(f'Path does not exist inside the selected framework: {raw}')
    return candidate


def _infer_action(text: str, keyword: str = '') -> str:
    low = f'{keyword} {text}'.lower()
    if keyword.lower() == 'then' or re.search(r'\b(?:verify|validate|expect|expects|should|assert|confirm that|visible|displayed|shown)\b', low):
        return 'verify'
    if re.search(r'https?://|\b(?:base url|application url|test environment url|new browser session)\b', low):
        return 'goto'
    if re.search(r'\b(?:enter|enters|fill|fills|type|types|input|inputs|provide|provides)\b', low):
        return 'fill'
    if re.search(r'\b(?:select|selects|choose|chooses|pick|picks)\b', low) and re.search(r'\b(?:dropdown|combobox|list|status|date|time|type|product|source|interest|option as| as )\b', low):
        return 'select'
    if re.search(r'\b(?:click|clicks|tap|taps|press|presses|submit|submits|confirm|confirms|open|opens|navigate|navigates|go to|launch|launches|visit|visits|select|selects|choose|chooses)\b', low):
        return 'click'
    return 'perform'


def _normalise_ui_text(value: str) -> str:
    """Remove documentation-only UI wrappers without changing the actual label.

    Manual testcases commonly write controls as ``<Log In to Sandbox>`` or
    ``[Submit]``. Those brackets describe a GUI control; they are not part of
    the browser accessible name. Keep Gherkin outline placeholders safe by
    stripping angle brackets only when the enclosed text looks like a UI label
    (contains whitespace/punctuation or a known control word).
    """
    text = html.unescape(str(value or ''))
    text = text.replace('‹', '<').replace('›', '>').replace('〈', '<').replace('〉', '>')
    text = text.replace('“', '"').replace('”', '"').replace('‘', "'").replace('’', "'")

    def unwrap_angle(match: re.Match[str]) -> str:
        inner = re.sub(r'\s+', ' ', match.group(1)).strip()
        looks_like_ui = bool(
            re.search(r'\s', inner)
            or re.search(r'\b(?:button|link|login|log\s+in|sign\s+in|submit|continue|next|save|cancel|search|sandbox|username|password)\b', inner, re.I)
        )
        return inner if looks_like_ui else match.group(0)

    # Handle both a whole wrapped label and wrappers embedded in an instruction.
    text = re.sub(r'<\s*([^<>]{1,160}?)\s*>', unwrap_angle, text)
    text = re.sub(r'(?i)\b(?:button|link|tab|icon|field|textbox|option|control)\s*[=:]\s*[<\[]\s*([^>\]]+?)\s*[>\]]', r'\1', text)
    text = re.sub(r'^[\[\(]\s*([^\]\)]+?)\s*[\]\)]$', r'\1', text.strip())
    return re.sub(r'\s+', ' ', text).strip()


def _normalise_locator_value(value: str) -> str:
    text = _normalise_ui_text(value)
    # A full remaining angle wrapper is always documentation notation at the
    # locator boundary; Gherkin examples have already been expanded by now.
    full = re.fullmatch(r'<\s*([^<>]+?)\s*>', text)
    if full:
        text = full.group(1).strip()
    text = text.strip(" \t\r\n<>[]{}\"'`")
    text = re.sub(r'\s+', ' ', text)
    if re.fullmatch(r'(?i)log\s*in\s+to\s+sandbox', text):
        return 'Log In to Sandbox'
    return text


def _normalise_locator_candidate_value(strategy: str, value: str) -> str:
    strategy = str(strategy or '').strip()
    if strategy in {'css', 'xpath'}:
        return str(value or '').strip()
    return _normalise_locator_value(value)


def _clean_step_text(value: str) -> str:
    value = re.sub(r'^\s*(?:step\s*)?\d+[\).:\-\s]+', '', value or '', flags=re.I)
    value = re.sub(r'[*_`]+', '', value)
    return _normalise_ui_text(value).strip(' \t-•')



def _semantic_target(value: str) -> str:
    text = _clean_step_text(value or 'element')
    embedded_action = re.search(r'[,;]\s*(?:then\s+)?(?:click|tap|press|select|open)\s+(?:on\s+)?(.+?)\s*$', text, re.I)
    if embedded_action:
        text = embedded_action.group(1)
    fill_in = re.match(r'^(?:in|on)\s+(.+?),\s*(?:enter|type|fill|input|provide)\b', text, re.I)
    if fill_in:
        text = fill_in.group(1)
    text = re.sub(r'^(?:click|tap|press|enter|fill|type|input|provide|select|choose|verify|validate|assert|confirm|open|navigate to|go to)\s+', '', text, flags=re.I)
    text = re.sub(r'^(?:on|the)\s+', '', text, flags=re.I)
    text = re.sub(r'\s+(?:as|with)\s+["\'`]?[^"\'`]+["\'`]?\s*$', '', text, flags=re.I)
    text = re.sub(r'\s+from\s+(?:the\s+)?dropdown\s*$', '', text, flags=re.I)
    text = re.sub(r'\s+(?:and\s+)?(?:click|press|select|open)\s+.+$', '', text, flags=re.I)
    text = re.sub(r'\s+(?:is|should be|must be)\s+(?:displayed|visible|shown|enabled|available|present)\.?$', '', text, flags=re.I)
    return _normalise_ui_text(text).strip() or 'element'


def _locator_label(value: str) -> str:
    """Return a likely accessible name instead of the full manual instruction."""
    original = _semantic_target(value)
    low = original.lower()
    common = (
        ('log in to sandbox', 'Log In to Sandbox'),
        ('login to sandbox', 'Log In to Sandbox'),
        ('username', 'Username'),
        ('user name', 'Username'),
        ('password', 'Password'),
        ('first name', 'First Name'),
        ('last name', 'Last Name'),
        ('mobile number', 'Mobile Number'),
        ('phone number', 'Phone Number'),
        ('email address', 'Email'),
        ('search box', 'Search'),
        ('app launcher', 'App Launcher'),
    )
    for token, label in common:
        if token in low:
            return label
    quoted = re.findall(r"[\"'`]([^\"'`]{1,80})[\"'`]", original)
    if quoted:
        return quoted[-1].strip()
    concrete = re.search(r'\b(?:is|equals?|matches?)\s+(.+?)\s*$', original, re.I)
    if concrete:
        candidate = concrete.group(1).strip(' .,:;-')
        if candidate and not re.search(r'\b(?:displayed|visible|shown|loaded|listed|opened|present|successfully|expected value)\b', candidate, re.I):
            return candidate[:80]
    text = re.sub(r'\([^)]*\)', '', original)
    text = re.sub(r'\s+home\s*page\s*$', '', text, flags=re.I)
    text = re.sub(r'^(?:valid|existing|created|current|the)\s+', '', text, flags=re.I)
    text = re.sub(r'\s+from\s+(?:the\s+)?search results.*$', '', text, flags=re.I)
    text = re.sub(r'\s+(?:on|in)\s+(?:the\s+)?(?:home page|homepage|page|screen).*$','', text, flags=re.I)
    text = re.sub(r'\s+(?:button|icon|link|tab|section|option|dropdown|textbox|field|control)\s*$', '', text, flags=re.I)
    text = re.sub(r'\s+', ' ', text).strip(' ,.-')
    if len(text) > 80:
        words = text.split()
        text = ' '.join(words[:10])
    return _normalise_locator_value(text or original) or 'element'


def _infer_page_context(title: str, steps: list[dict[str, Any]], fallback: str = 'Home') -> str:
    corpus = ' '.join([title] + [str(step.get('target') or '') for step in steps]).lower()
    if 'salesforce' in corpus or 'customer central' in corpus or 'work queue' in corpus:
        return 'Salesforce'
    if 'loyalty management' in corpus:
        return 'LoyaltyManagement'
    if re.search(r'\blogin|sign in|username|password\b', corpus):
        return 'Login'
    return fallback or 'Home'


def _credential_role(text: str) -> str:
    low = str(text or '').lower()
    if any(token in low for token in ('off hour', 'off-hour', 'oha_chat', 'chat only agent')):
        return 'off_hour_agent'
    if any(token in low for token in ('admin user', 'administrator', 'developer console')):
        return 'admin_user'
    if any(token in low for token in ('store co-worker', 'store coworker', 'henry sms', 'ben sms')):
        return 'store_coworker'
    return 'default'


def _environment_name_for_step(step_text: str, role: str = '') -> str:
    low = step_text.lower()
    effective_role = role or _credential_role(step_text)
    prefix = {
        'store_coworker': 'SALESFORCE_STORE_COWORKER',
        'off_hour_agent': 'SALESFORCE_OFF_HOUR',
        'admin_user': 'SALESFORCE_ADMIN',
    }.get(effective_role, 'SALESFORCE')
    if 'password' in low or 'passcode' in low:
        return f'{prefix}_PASSWORD' if prefix != 'SALESFORCE' else 'SALESFORCE_PASSWORD'
    if any(token in low for token in ('username', 'user name', 'email', 'admin user', 'valid user', 'login id')):
        return f'{prefix}_USERNAME' if prefix != 'SALESFORCE' else 'SALESFORCE_USERNAME'
    if 'verification code' in low or re.search(r'\botp\b', low):
        return 'SALESFORCE_VERIFICATION_CODE'
    semantic = re.sub(r'[^A-Za-z0-9]+', '_', _semantic_target(step_text)).strip('_').upper()
    return (semantic[:64] or 'TEST_DATA')


def _scenario_environment_name(step_text: str, role: str, scenario_id: str) -> str:
    base = _environment_name_for_step(step_text, role)
    scenario_token = re.sub(r'[^A-Z0-9]+', '_', str(scenario_id or 'SCENARIO').upper()).strip('_')[:40] or 'SCENARIO'
    for suffix in ('_USERNAME', '_PASSWORD'):
        if base.endswith(suffix):
            return f"{base[:-len(suffix)]}_{scenario_token}{suffix}"
    return f"{base}_{scenario_token}"



def _inline_step_value(step_text: str, action: str = '') -> str:
    """Extract a concrete test value embedded in a human-readable instruction.

    This intentionally rejects credential language and generic field labels. It
    is used when the spreadsheet's Test Data column is empty or contains N/A,
    for example: ``enter Customer Central`` or ``Select Lead Status as New``.
    """
    clean = _clean_step_text(step_text)
    low = clean.lower()
    if any(token in low for token in ('username', 'user name', 'password', 'passcode', 'verification code', 'otp')):
        return ''
    quoted = re.findall(r"[\"'`]([^\"'`]{1,160})[\"'`]", clean)
    if quoted:
        return quoted[-1].strip()
    as_match = re.search(r'\b(?:as|to)\s+(.+?)\s*$', clean, re.I)
    if as_match:
        candidate = as_match.group(1).strip(' .,:;-')
        if candidate and not re.search(r'\b(?:displayed|visible|loaded|successfully|button|field|page)\b', candidate, re.I):
            return candidate[:500]
    enter_match = re.search(r'\b(?:enter|type|fill|input|provide)\s+(.+?)\s*$', clean, re.I)
    if enter_match:
        candidate = enter_match.group(1).strip(' .,:;-')
        candidate = re.sub(r'^(?:the\s+)?(?:valid\s+)?', '', candidate, flags=re.I)
        # Do not mistake a field name for its value.
        if candidate and not re.search(r'\b(?:username|password|first name|last name|mobile number|phone number|email address|search box|field|textbox|value|date|time|product|notes)\b$', candidate, re.I):
            return candidate[:500]
    return ''


def _concrete_expected_value(step: dict[str, Any]) -> str:
    """Return the concrete assertion value, not a prose success sentence."""
    target = _clean_step_text(str(step.get('target') or step.get('description') or ''))
    quoted = re.findall(r"[\"'`]([^\"'`]{1,160})[\"'`]", target)
    if quoted:
        return quoted[-1].strip()
    candidate = ''
    match = re.search(r'\b(?:is|equals?|matches?|contains?)\s+(.+?)\s*$', target, re.I)
    if match:
        candidate = match.group(1).strip(' .,:;-')
    if not candidate:
        expected = str(step.get('expected') or '').strip()
        if expected and len(expected) <= 100:
            candidate = expected
    if not candidate:
        return ''
    generic = candidate.lower()
    if re.search(r'\b(?:displayed|display|visible|shown|loaded|listed|opened|present|successfully|expected value|entered|populated|selected|created|reflected|updated|removed|completed|page|message)\b', generic):
        return ''
    return candidate[:500]


def _data_key_base(step: dict[str, Any], *, expected: bool = False) -> str:
    action = str(step.get('action') or '').lower()
    target = str(step.get('target') or step.get('description') or 'value')
    low = target.lower()
    if expected:
        prefix = 'expected'
    else:
        prefix = ''
    special = ''
    if action in {'goto', 'open', 'launch', 'navigate'}:
        special = 'applicationUrl'
    elif 'username' in low or 'user name' in low or 'login id' in low or 'admin user' in low:
        special = 'username'
    elif 'password' in low or 'passcode' in low:
        special = 'password'
    elif 'first name' in low:
        special = 'firstName'
    elif 'last name' in low:
        special = 'lastName'
    elif 'mobile' in low or 'phone number' in low:
        special = 'mobileNumber'
    elif 'app launcher' in low and 'search' in low:
        special = 'appLauncherSearch'
    elif 'lead status' in low:
        special = 'leadStatus'
    elif 'product interest' in low:
        special = 'productInterest'
    elif 'lead source' in low:
        special = 'leadSource'
    elif 'lead name' in low:
        special = 'leadName'
    elif 'appointment type' in low:
        special = 'appointmentType'
    elif 'appointment date' in low or ('date' in low and action == 'select'):
        special = 'appointmentDate'
    elif 'appointment time' in low or ('time' in low and action == 'select'):
        special = 'appointmentTime'
    elif 'notes' in low:
        special = 'notes'
    else:
        special = camel_case(_semantic_target(target)) or 'value'
    if expected:
        return 'expected' + special[:1].upper() + special[1:]
    return special


def _scenario_data_key_map(scenario: dict[str, Any]) -> dict[int, dict[str, str]]:
    used: dict[str, int] = {}
    result: dict[int, dict[str, str]] = {}
    for step_index, step in enumerate(scenario.get('steps') or [], 1):
        item: dict[str, str] = {}
        action = str(step.get('action') or '').lower()
        has_value = bool(
            str(step.get('value') or '').strip()
            or str(step.get('value_env') or '').strip()
            or (action in {'goto', 'open', 'launch', 'navigate'} and re.search(r'https?://[^\s]+', str(step.get('target') or '')))
        )
        if has_value:
            base = _data_key_base(step)
            used[base] = used.get(base, 0) + 1
            item['value'] = base if used[base] == 1 else f'{base}Step{step_index}'
        expected = _concrete_expected_value(step) if action in {'verify', 'assert', 'expect', 'validate'} else ''
        if expected:
            base = _data_key_base(step, expected=True)
            used[base] = used.get(base, 0) + 1
            item['expected'] = base if used[base] == 1 else f'{base}Step{step_index}'
        result[step_index] = item
    return result


def _feature_data_export_name(feature: str) -> str:
    name = camel_case(feature) or 'feature'
    return name + 'Data'


def _extract_test_data(step_text: str, raw_value: str) -> dict[str, Any]:
    raw = (raw_value or '').strip()
    if not raw or raw.lower() in {'n/a', 'na', 'none', 'null', '-'}:
        return {}
    low_step = step_text.lower()
    auth_terms = ('password', 'passcode', 'username', 'user name', 'verification code', ' api token', 'token', 'admin user', 'valid user', 'login id')
    raw_looks_credential = bool(re.match(r'^\s*(?:username|user|email|password|passcode)\s*[:=]', raw, re.I))
    if any(token in low_step for token in auth_terms) or raw_looks_credential:
        return {
            'value_env': _environment_name_for_step(step_text),
            'value_sensitive': True,
            'value_source': 'environment_only',
        }
    url_match = re.search(r'https?://[^\s]+', raw)
    if url_match:
        return {'value': url_match.group(0).rstrip('.,;'), 'value_source': 'spreadsheet_test_data'}
    candidate = raw
    labelled = re.match(r'^\s*[^:=]{1,80}\s*[:=]\s*(.+?)\s*$', raw)
    if labelled:
        candidate = labelled.group(1).strip()
    if re.search(r'\b(?:asks?|prompted|displayed|page|message|appears?|successfully)\b', candidate, re.I) and not re.search(r'[=@]|\d{3,}', candidate):
        return {}
    generic = candidate.strip().lower()
    if generic in {'date', 'time', 'product', 'appointment type', 'notes', 'status', 'type'}:
        return {
            'value_env': _environment_name_for_step(step_text),
            # These spreadsheet values are labels/placeholders, not secrets.
            # Keep an optional runtime override, but do not make Playwright test
            # discovery depend on a shell variable that the workbook never
            # actually supplied.
            'value_source': 'optional_runtime_placeholder',
        }
    return {'value': candidate[:500], 'value_source': 'spreadsheet_test_data'}

def _scenario_id(feature: str, index: int, supplied: str = '') -> str:
    if supplied.strip():
        return re.sub(r'[^A-Za-z0-9_-]+', '-', supplied.strip()).strip('-').upper()
    return f'{feature.upper()}-TC-{index:03d}'


def _step_from_text(text: str, page: str = 'Home', keyword: str = '') -> dict[str, Any]:
    clean = _clean_step_text(text)
    expected = ''
    if '=>' in clean:
        clean, expected = [x.strip() for x in clean.split('=>', 1)]
    return {
        'action': _infer_action(clean, keyword),
        'target': clean[:500],
        'page': page or 'Home',
        **({'expected': expected[:500]} if expected else {}),
        **({'gherkin_keyword': keyword.title()} if keyword else {}),
    }


def _parse_json_payload(raw: str, feature: str) -> dict[str, Any] | None:
    try:
        data = json.loads(raw)
    except Exception:
        return None
    if isinstance(data, dict) and isinstance(data.get('scenarios'), list):
        payload = dict(data)
        payload.setdefault('feature', feature)
        payload.setdefault('source_type', 'module2_uploaded')
        return payload
    if isinstance(data, list):
        return {'feature': feature, 'source_type': 'module2_uploaded', 'scenarios': data}
    return None


def _parse_examples(lines: list[str], start: int) -> tuple[list[dict[str, str]], int]:
    rows: list[list[str]] = []
    i = start
    while i < len(lines):
        line = lines[i].strip()
        if not line.startswith('|'):
            break
        rows.append([c.strip() for c in line.strip('|').split('|')])
        i += 1
    if len(rows) < 2:
        return [], i
    headers = rows[0]
    return [dict(zip(headers, row)) for row in rows[1:] if len(row) == len(headers)], i


def _substitute_outline(value: Any, example: dict[str, str]) -> Any:
    if isinstance(value, str):
        for key, replacement in example.items():
            value = value.replace(f'<{key}>', replacement)
        return value
    if isinstance(value, list):
        return [_substitute_outline(v, example) for v in value]
    if isinstance(value, dict):
        return {k: _substitute_outline(v, example) for k, v in value.items()}
    return value


def parse_gherkin(raw: str, feature: str) -> dict[str, Any]:
    lines = [x.rstrip() for x in (raw or '').splitlines()]
    feature_title = feature.replace('_', ' ').title()
    background: list[dict[str, Any]] = []
    scenarios: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    tags: list[str] = []
    section = ''
    last_primary_keyword = ''
    i = 0
    while i < len(lines):
        stripped = lines[i].strip()
        if not stripped or stripped.startswith('#'):
            i += 1
            continue
        if stripped.startswith('@'):
            tags = stripped.split()
            i += 1
            continue
        m = re.match(r'^Feature\s*:\s*(.+)$', stripped, re.I)
        if m:
            feature_title = m.group(1).strip()
            i += 1
            continue
        if re.match(r'^Background\s*:', stripped, re.I):
            section = 'background'
            current = None
            i += 1
            continue
        m = re.match(r'^Scenario(?: Outline| Template)?\s*:\s*(.+)$', stripped, re.I)
        if m:
            current = {
                'id': '',
                'title': m.group(1).strip(),
                'feature': feature,
                'page': pascal_case(feature_title) or 'Home',
                'priority': 'medium',
                'preconditions': [],
                'steps': [],
                'expected_result': '',
                'tags': list(tags),
                'gherkin_source': True,
                'outline': bool(re.match(r'^Scenario(?: Outline| Template)', stripped, re.I)),
            }
            tags = []
            scenarios.append(current)
            section = 'scenario'
            i += 1
            continue
        if re.match(r'^Examples\s*:', stripped, re.I) and current is not None:
            examples, next_i = _parse_examples(lines, i + 1)
            current['examples'] = examples
            i = next_i
            continue
        step_match = re.match(r'^(Given|When|Then|And|But|\*)\s+(.+)$', stripped, re.I)
        if step_match:
            keyword, text = step_match.group(1).title(), step_match.group(2).strip()
            effective_keyword = last_primary_keyword if keyword in {'And', 'But', '*'} and last_primary_keyword else keyword
            if keyword in {'Given', 'When', 'Then'}:
                last_primary_keyword = keyword
            step = _step_from_text(text, current.get('page', 'Home') if current else 'Home', effective_keyword)
            step['gherkin_keyword'] = keyword
            if section == 'background' or current is None:
                background.append(step)
            else:
                current['steps'].append(step)
                if keyword == 'Then':
                    current['expected_result'] = text
            i += 1
            continue
        i += 1

    expanded: list[dict[str, Any]] = []
    for scenario in scenarios:
        check_cancelled()
        steps = [dict(x) for x in background] + list(scenario.get('steps') or [])
        scenario['steps'] = steps
        examples = scenario.pop('examples', [])
        outline = scenario.pop('outline', False)
        if outline and examples:
            for row_no, example in enumerate(examples, 1):
                clone = _substitute_outline(scenario, example)
                clone['title'] = f"{clone.get('title')} [{row_no}]"
                clone['example_data'] = example
                expanded.append(clone)
        else:
            expanded.append(scenario)
    for idx, scenario in enumerate(expanded, 1):
        scenario['id'] = _scenario_id(feature, idx, scenario.get('id', ''))
        if not scenario.get('expected_result'):
            then_step = next((s for s in reversed(scenario.get('steps') or []) if s.get('action') == 'verify'), None)
            scenario['expected_result'] = (then_step or {}).get('target') or 'Expected behavior described by the BDD scenario should be verified.'
    return {
        'feature': feature,
        'feature_title': feature_title,
        'source_type': 'gherkin_bdd',
        'source_format': 'feature',
        'scenario_count': len(expanded),
        'scenarios': expanded,
    }


def _split_plain_blocks(raw: str) -> list[list[str]]:
    lines = [x.rstrip() for x in (raw or '').splitlines()]
    blocks: list[list[str]] = []
    current: list[str] = []
    heading = re.compile(r'^\s*(?:#{1,6}\s*)?(?:test\s*case|testcase|tc|scenario)\s*(?:id|no|number|#)?\s*[:\-]?\s*[A-Za-z0-9_-]+', re.I)
    divider = re.compile(r'^\s*(?:-{3,}|={3,})\s*$')
    for line in lines:
        if heading.match(line) and current:
            blocks.append(current)
            current = [line]
        elif divider.match(line) and current:
            blocks.append(current)
            current = []
        else:
            current.append(line)
    if current:
        blocks.append(current)
    nonempty = [b for b in blocks if any(x.strip() for x in b)]
    return nonempty or [lines]


def _label_value(line: str, labels: tuple[str, ...]) -> str:
    joined = '|'.join(re.escape(x) for x in labels)
    m = re.match(rf'^\s*(?:{joined})\s*[:\-]\s*(.*)$', line, re.I)
    return m.group(1).strip() if m else ''


def _scenario_from_plain_block(block: list[str], feature: str, index: int) -> dict[str, Any]:
    scenario_id = ''
    title = ''
    page = 'Home'
    priority = 'medium'
    preconditions: list[str] = []
    steps: list[dict[str, Any]] = []
    expected_parts: list[str] = []
    section = ''
    for raw_line in block:
        line = raw_line.strip()
        if not line:
            continue
        value = _label_value(line, ('test case id', 'testcase id', 'tc id', 'id'))
        if value:
            scenario_id = value
            continue
        value = _label_value(line, ('test case', 'testcase', 'title', 'scenario', 'test name'))
        if value:
            title = value
            continue
        value = _label_value(line, ('module', 'page', 'screen'))
        if value:
            page = pascal_case(value) or 'Home'
            continue
        value = _label_value(line, ('priority',))
        if value:
            priority = value.lower()
            continue
        if re.match(r'^\s*(preconditions?|prerequisites?)\s*:?\s*$', line, re.I):
            section = 'preconditions'
            continue
        value = _label_value(line, ('precondition', 'preconditions', 'prerequisite'))
        if value:
            preconditions.append(value)
            section = 'preconditions'
            continue
        if re.match(r'^\s*(steps?|test steps?|actions?)\s*:?\s*$', line, re.I):
            section = 'steps'
            continue
        if re.match(r'^\s*(expected results?|expected outcome|result)\s*:?\s*$', line, re.I):
            section = 'expected'
            continue
        value = _label_value(line, ('expected result', 'expected outcome', 'expected'))
        if value:
            expected_parts.append(value)
            section = 'expected'
            continue
        if re.match(r'^(Given|When|Then|And|But)\s+', line, re.I):
            m = re.match(r'^(Given|When|Then|And|But)\s+(.+)$', line, re.I)
            assert m
            steps.append(_step_from_text(m.group(2), page, m.group(1)))
            if m.group(1).lower() == 'then':
                expected_parts.append(m.group(2))
            continue
        if section == 'preconditions':
            preconditions.append(_clean_step_text(line))
        elif section == 'expected':
            expected_parts.append(_clean_step_text(line))
        elif section == 'steps' or re.match(r'^\s*(?:step\s*)?\d+[\).:\-\s]+', line, re.I):
            steps.append(_step_from_text(line, page))
        elif not title:
            title = re.sub(r'^#+\s*', '', line).strip()
        else:
            steps.append(_step_from_text(line, page))
    if not steps and title:
        steps = [_step_from_text(title, page)]
    expected_result = ' '.join(x for x in expected_parts if x) or 'Expected business result should be verified.'
    if expected_parts and not any(step.get('action') == 'verify' for step in steps):
        steps.append(_step_from_text(expected_result, page, 'Then'))
    return {
        'id': _scenario_id(feature, index, scenario_id),
        'title': title or f'{feature.replace("_", " ").title()} test {index}',
        'feature': feature,
        'page': page,
        'priority': priority,
        'preconditions': [x for x in preconditions if x],
        'steps': [x for x in steps if x.get('target')],
        'expected_result': expected_result,
    }



def _jira_field(block: str, name: str) -> str:
    match = re.search(rf'^\s*{re.escape(name)}\s*:\s*(.*)$', block, re.I | re.M)
    return match.group(1).strip() if match else ''


def parse_jira_testcases(raw: str, feature: str) -> dict[str, Any]:
    blocks = [block.strip() for block in re.split(r'(?m)^\s*-{3,}\s*$', raw or '') if re.search(r'(?im)^\s*Jira Key\s*:', block)]
    parsed: list[dict[str, Any]] = []
    for block in blocks:
        key = _jira_field(block, 'Jira Key')
        issue_type = _jira_field(block, 'Issue Type') or 'Issue'
        title = _jira_field(block, 'Title') or f'Validate {key or feature}'
        priority = (_jira_field(block, 'Priority') or 'medium').lower()
        description_match = re.search(r'Description\s*/\s*Acceptance Criteria\s*:\s*(.*)$', block, re.I | re.S)
        description = description_match.group(1).strip() if description_match else ''
        page = pascal_case(feature) or 'Home'
        if re.search(r'(?im)^\s*(Given|When|Then)\s+', description):
            wrapped = f'Feature: {feature}\nScenario: {title}\n{description}'
            gherkin = parse_gherkin(wrapped, feature)
            scenario = (gherkin.get('scenarios') or [{}])[0]
            scenario.update({'id': key or scenario.get('id'), 'title': title, 'priority': priority, 'jira_issue_type': issue_type})
        else:
            lines = [line.strip(' \t-•') for line in description.splitlines() if line.strip()]
            steps = [_step_from_text(line, page) for line in lines if len(line) > 2]
            expected_candidates = [line for line in lines if any(word in line.lower() for word in ('should', 'expected', 'verify', 'displayed', 'visible', 'success', 'error'))]
            expected = expected_candidates[-1] if expected_candidates else f'{title} should satisfy the Jira acceptance criteria.'
            if not steps:
                steps = [_step_from_text(f'Validate {title}', page)]
            if not any(step.get('action') == 'verify' for step in steps):
                steps.append(_step_from_text(expected, page, 'Then'))
            scenario = {
                'id': key,
                'title': title,
                'feature': feature,
                'page': page,
                'priority': priority,
                'preconditions': [],
                'steps': steps,
                'expected_result': expected,
                'jira_issue_type': issue_type,
            }
        parsed.append(scenario)
    if len(parsed) > 1:
        non_epic = [scenario for scenario in parsed if str(scenario.get('jira_issue_type') or '').lower() != 'epic']
        if non_epic:
            parsed = non_epic
    for idx, scenario in enumerate(parsed, 1):
        scenario['id'] = _scenario_id(feature, idx, str(scenario.get('id') or ''))
        scenario.setdefault('feature', feature)
        scenario.setdefault('expected_result', f"{scenario.get('title')} should satisfy the Jira acceptance criteria.")
    return {
        'feature': feature,
        'source_type': 'jira_atlassian',
        'source_format': 'jira_issue_blocks',
        'scenario_count': len(parsed),
        'scenarios': parsed,
    }

def parse_plain_testcases(raw: str, feature: str) -> dict[str, Any]:
    if re.search(r'^\s*Feature\s*:', raw or '', re.I | re.M) or re.search(r'^\s*(Given|When|Then)\s+', raw or '', re.I | re.M):
        return parse_gherkin(raw, feature)
    scenarios = [_scenario_from_plain_block(block, feature, idx) for idx, block in enumerate(_split_plain_blocks(raw), 1)]
    scenarios = [s for s in scenarios if s.get('steps') or s.get('title')]
    return {
        'feature': feature,
        'source_type': 'module2_uploaded',
        'source_format': 'plain_steps',
        'scenario_count': len(scenarios),
        'scenarios': scenarios,
    }


def _extract_docx(uploaded_bytes: bytes) -> str:
    try:
        from docx import Document
        doc = Document(io.BytesIO(uploaded_bytes))
        lines: list[str] = []
        for paragraph in doc.paragraphs:
            if paragraph.text.strip():
                lines.append(paragraph.text)
        for table in doc.tables:
            for row in table.rows:
                values = [cell.text.strip() for cell in row.cells]
                if any(values):
                    lines.append(' | '.join(values))
        return '\n'.join(lines)
    except Exception:
        with zipfile.ZipFile(io.BytesIO(uploaded_bytes)) as zf:
            xml = zf.read('word/document.xml').decode('utf-8', errors='replace')
        return '\n'.join(html.unescape(x) for x in re.findall(r'<w:t[^>]*>(.*?)</w:t>', xml, re.S))


def _extract_pdf(uploaded_bytes: bytes) -> str:
    import pypdf
    reader = pypdf.PdfReader(io.BytesIO(uploaded_bytes))
    return '\n'.join((page.extract_text() or '') for page in reader.pages)


def _find_header_index(headers: list[str], aliases: tuple[str, ...]) -> int | None:
    normalized = [re.sub(r'[^a-z0-9]+', ' ', h.lower()).strip() for h in headers]
    alias_values = [re.sub(r'[^a-z0-9]+', ' ', alias.lower()).strip() for alias in aliases]
    for alias_norm in alias_values:
        for idx, value in enumerate(normalized):
            if value == alias_norm:
                return idx
    for alias_norm in alias_values:
        if len(alias_norm) < 4:
            continue
        for idx, value in enumerate(normalized):
            if alias_norm in value:
                return idx
    return None


def extract_excel_credential_profiles(uploaded_bytes: bytes, feature: str) -> dict[str, dict[str, str]]:
    """Extract scenario credentials for the volatile walkthrough vault only.

    This function is intentionally separate from normalized testcase creation so
    raw usernames/passwords never enter testcase JSON, Markdown, SQLite,
    LangSmith, reports, generated source, or test-data modules.
    """
    import openpyxl

    wb = openpyxl.load_workbook(io.BytesIO(uploaded_bytes), data_only=True, read_only=True)
    profiles: dict[str, dict[str, str]] = {}
    scenario_index = 0
    for ws in wb.worksheets:
        rows = [[str(v).strip() if v is not None else '' for v in row] for row in ws.iter_rows(values_only=True)]
        rows = [r for r in rows if any(r)]
        if not rows:
            continue
        header_row = 0
        for idx, row in enumerate(rows[:15]):
            joined = ' '.join(row).lower()
            if any(key in joined for key in ('test case', 'testcase', 'expected', 'step', 'scenario')):
                header_row = idx
                break
        headers = rows[header_row]
        id_idx = _find_header_index(headers, ('test case id', 'testcase id', 'tc id', 'test case', 'test_case', 'tc', 'id'))
        title_idx = _find_header_index(headers, ('test case title', 'testcase title', 'summary', 'summery', 'scenario summary', 'scenario', 'title', 'test name'))
        step_idx = _find_header_index(headers, ('test step', 'step', 'steps', 'step description', 'action'))
        test_data_idx = _find_header_index(headers, ('test data', 'testdata', 'input data', 'data', 'value'))
        if step_idx is None:
            continue
        current_id = ''
        current_title = ''
        current_scenario_id = ''
        for row in rows[header_row + 1:]:
            def cell(index: int | None) -> str:
                return row[index].strip() if index is not None and index < len(row) else ''
            supplied_id = cell(id_idx)
            title = cell(title_idx)
            if supplied_id or title:
                scenario_index += 1
                current_id = supplied_id
                current_title = title or supplied_id
                current_scenario_id = _scenario_id(feature, scenario_index, supplied_id)
            if not current_scenario_id:
                continue
            step_text = cell(step_idx)
            raw = cell(test_data_idx)
            if not step_text or not raw:
                continue
            username_match = re.match(r'^\s*(?:username|user(?:\s*name)?|email|login\s*id)\s*[:=]\s*(.+?)\s*$', raw, re.I | re.S)
            password_match = re.match(r'^\s*(?:password|passcode)\s*[:=]\s*(.+?)\s*$', raw, re.I | re.S)
            if not username_match and not password_match:
                continue
            profile = profiles.setdefault(current_scenario_id, {
                'username': '',
                'password': '',
                'role': _credential_role(f'{current_title} {step_text}'),
                'profile_id': current_scenario_id,
            })
            if username_match:
                profile['username'] = re.sub(r'\s+', '', username_match.group(1))
                profile['role'] = _credential_role(f'{current_title} {step_text} {profile["username"]}')
            if password_match:
                profile['password'] = password_match.group(1).strip()
    return {key: value for key, value in profiles.items() if value.get('username') or value.get('password')}


def _parse_excel(uploaded_bytes: bytes, feature: str) -> dict[str, Any]:
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(uploaded_bytes), data_only=True, read_only=True)
    scenarios: list[dict[str, Any]] = []
    fallback_lines: list[str] = []
    for ws in wb.worksheets:
        rows = [[str(v).strip() if v is not None else '' for v in row] for row in ws.iter_rows(values_only=True)]
        rows = [r for r in rows if any(r)]
        if not rows:
            continue
        header_row = 0
        for idx, row in enumerate(rows[:15]):
            joined = ' '.join(row).lower()
            if any(key in joined for key in ('test case', 'testcase', 'expected', 'step', 'scenario')):
                header_row = idx
                break
        headers = rows[header_row]
        id_idx = _find_header_index(headers, ('test case id', 'testcase id', 'tc id', 'test case', 'test_case', 'tc', 'id'))
        title_idx = _find_header_index(headers, ('test case title', 'testcase title', 'summary', 'summery', 'scenario summary', 'scenario', 'title', 'test name'))
        step_idx = _find_header_index(headers, ('test step', 'step', 'steps', 'step description', 'action'))
        step_number_idx = _find_header_index(headers, ('step number', 'step no', 'step #', 'sequence'))
        test_data_idx = _find_header_index(headers, ('test data', 'testdata', 'input data', 'data', 'value'))
        expected_idx = _find_header_index(headers, ('expected result', 'expected outcome', 'expected'))
        pre_idx = _find_header_index(headers, ('precondition', 'prerequisite'))
        page_idx = _find_header_index(headers, ('page', 'screen', 'module'))
        priority_idx = _find_header_index(headers, ('priority',))
        if title_idx is None and step_idx is None:
            fallback_lines.append(f'# Sheet: {ws.title}')
            fallback_lines.extend(' | '.join(x for x in row if x) for row in rows)
            continue
        grouped: dict[str, dict[str, Any]] = {}
        last_key = ''
        for row_no, row in enumerate(rows[header_row + 1:], header_row + 2):
            def cell(index: int | None) -> str:
                return row[index].strip() if index is not None and index < len(row) else ''
            supplied_id = cell(id_idx)
            title = cell(title_idx)
            key = supplied_id or title or last_key or f'{ws.title}-{row_no}'
            last_key = key
            scenario = grouped.setdefault(key, {
                'id': supplied_id,
                'title': title or key,
                'feature': feature,
                'page': pascal_case(cell(page_idx)) if cell(page_idx) else 'Home',
                'priority': (cell(priority_idx) or 'medium').lower(),
                'preconditions': [],
                'steps': [],
                'expected_result': '',
                'source_sheet': ws.title,
            })
            if title and not scenario.get('title'):
                scenario['title'] = title
            if cell(pre_idx) and cell(pre_idx) not in scenario['preconditions']:
                scenario['preconditions'].append(cell(pre_idx))
            step_text = cell(step_idx)
            step_number = cell(step_number_idx)
            test_data = cell(test_data_idx)
            expected = cell(expected_idx)
            if step_text:
                step = _step_from_text(step_text, scenario['page'])
                step.update(_extract_test_data(step_text, test_data))
                if not step.get('value') and not step.get('value_env') and str(step.get('action') or '').lower() in {'fill', 'type', 'enter', 'select'}:
                    inline_value = _inline_step_value(step_text, str(step.get('action') or ''))
                    if inline_value:
                        step['value'] = inline_value
                        step['value_source'] = 'step_instruction'
                if step_number:
                    step['step_number'] = step_number
                if expected:
                    step['expected'] = expected
                scenario['steps'].append(step)
            if expected:
                scenario['expected_result'] = expected
        for scenario in grouped.values():
            scenario['page'] = _infer_page_context(str(scenario.get('title') or ''), scenario.get('steps') or [], str(scenario.get('page') or 'Home'))
            role_corpus = ' '.join([str(scenario.get('title') or '')] + [str(step.get('target') or '') for step in scenario.get('steps') or []])
            credential_role = _credential_role(role_corpus)
            scenario['credential_profile'] = credential_role
            for step_index, step in enumerate(scenario.get('steps') or [], 1):
                step['page'] = scenario['page']
                if step.get('value_sensitive') and str(scenario['page']).lower() == 'salesforce':
                    low_target = str(step.get('target') or '').lower()
                    if any(token in low_target for token in ('password', 'passcode')):
                        step['value_env'] = _environment_name_for_step('password', credential_role)
                    elif any(token in low_target for token in ('username', 'user name', 'email', 'admin user', 'valid user', 'login id')):
                        step['value_env'] = _environment_name_for_step('username', credential_role)
            if scenario.get('expected_result') and not any(step.get('action') == 'verify' for step in scenario.get('steps') or []):
                scenario['steps'].append(_step_from_text(scenario['expected_result'], scenario.get('page') or 'Home', 'Then'))
            if scenario.get('steps') or scenario.get('title'):
                scenarios.append(scenario)
    if not scenarios and fallback_lines:
        return parse_plain_testcases('\n'.join(fallback_lines), feature)
    for idx, scenario in enumerate(scenarios, 1):
        scenario['id'] = _scenario_id(feature, idx, scenario.get('id', ''))
        scenario['expected_result'] = scenario.get('expected_result') or 'Expected result from the spreadsheet should be verified.'
    return {
        'feature': feature,
        'source_type': 'module2_uploaded',
        'source_format': 'xlsx',
        'scenario_count': len(scenarios),
        'scenarios': scenarios,
    }


def extract_and_normalize_source(
    feature: str,
    pasted_json_or_steps: str = '',
    uploaded_bytes: bytes | None = None,
    uploaded_name: str = '',
    jira_story: str = '',
    jira_epic: str = '',
    source_mode: str = 'auto',
) -> dict[str, Any]:
    feature = _safe_feature(feature)
    uploaded_name = uploaded_name or ''
    suffix = Path(uploaded_name).suffix.lower()
    warnings: list[str] = []
    if uploaded_bytes and suffix in {'.xlsx', '.xlsm'}:
        payload = _parse_excel(uploaded_bytes, feature)
    else:
        extracted = ''
        if uploaded_bytes:
            if suffix in _TEXT_EXTENSIONS:
                extracted = uploaded_bytes.decode('utf-8', errors='replace')
            elif suffix == '.docx':
                extracted = _extract_docx(uploaded_bytes)
            elif suffix == '.pdf':
                extracted = _extract_pdf(uploaded_bytes)
            elif suffix == '.doc':
                try:
                    proc = subprocess.run(['antiword', '-'], input=uploaded_bytes, capture_output=True, timeout=30)
                    extracted = proc.stdout.decode('utf-8', errors='replace') if proc.returncode == 0 else ''
                except Exception:
                    extracted = ''
                if not extracted:
                    raise ValueError('Legacy .doc extraction requires antiword. Save the file as .docx, PDF, TXT, or MD and upload again.')
            else:
                extracted = uploaded_bytes.decode('utf-8', errors='replace')
        raw_parts: list[str] = []
        if jira_epic.strip():
            raw_parts.append('JIRA EPIC:\n' + jira_epic.strip())
        if jira_story.strip():
            raw_parts.append('JIRA STORY/TASK/BUG:\n' + jira_story.strip())
        if pasted_json_or_steps.strip():
            raw_parts.append(pasted_json_or_steps.strip())
        if extracted.strip():
            raw_parts.append(extracted.strip())
        raw = '\n\n---\n\n'.join(raw_parts)
        payload = _parse_json_payload(raw, feature)
        if payload is None:
            force_bdd = source_mode.lower() in {'bdd', 'gherkin', 'cucumber'} or suffix == '.feature'
            if source_mode.lower() == 'jira' or re.search(r'(?im)^\s*Jira Key\s*:', raw):
                payload = parse_jira_testcases(raw, feature)
            else:
                payload = parse_gherkin(raw, feature) if force_bdd else parse_plain_testcases(raw, feature)
    payload['feature'] = feature
    payload['scenario_count'] = len(payload.get('scenarios') or [])
    payload['source_file_name'] = uploaded_name
    payload['source_mode'] = source_mode
    payload['normalization_warnings'] = warnings
    if not payload['scenario_count']:
        raise ValueError('No executable testcase/scenario could be identified. Add Test Case/Scenario headings, numbered steps, or valid Given/When/Then content.')
    for idx, scenario in enumerate(payload['scenarios'], 1):
        scenario.setdefault('id', _scenario_id(feature, idx))
        scenario.setdefault('feature', feature)
        scenario.setdefault('page', 'Home')
        scenario.setdefault('priority', 'medium')
        scenario.setdefault('preconditions', [])
        scenario.setdefault('steps', [])
        scenario.setdefault('expected_result', 'Expected business result should be verified.')
        role = str(scenario.get('credential_profile') or _credential_role(' '.join([str(scenario.get('title') or '')] + [str(step.get('target') or '') for step in scenario.get('steps') or []])))
        scenario['credential_profile'] = role
        for step in scenario.get('steps') or []:
            if step.get('value_sensitive'):
                step['value_env'] = _scenario_environment_name(str(step.get('target') or step.get('description') or 'credential'), role, str(scenario.get('id') or idx))
    return payload


def save_normalized_source(payload: dict[str, Any]) -> dict[str, Any]:
    feature = _safe_feature(str(payload.get('feature') or 'feature'))
    path = feature_testcase_path('module2_uploaded', feature)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, payload)
    write_functional_testcases_markdown(path, payload)
    write_active_context({
        'channel': 'module2_playwright_generator',
        'source_type': 'module2_uploaded',
        'requested_feature': feature,
        'parent_feature': feature,
        'features': [feature],
        'testcase_paths': [str(path.relative_to(REPO_ROOT))],
        'functional_testcases_reviewed': True,
        'review_gate': 'module2_uploaded_approved',
        'playwright_generated': False,
        'scenario_count': len(payload.get('scenarios') or []),
    })
    log_event('module2_testcases_load', f"Normalized {len(payload.get('scenarios') or [])} testcase(s) for existing-framework generation", status='done', progress=100, feature=feature)
    return {
        'ok': True,
        'testcase_file': str(path.relative_to(REPO_ROOT)),
        'markdown_file': str(path.with_name(path.name.replace('.scenarios.json', '.scenarios.md')).relative_to(REPO_ROOT)),
        'testcases': payload,
        'scenario_count': len(payload.get('scenarios') or []),
        'message': f"Identified and normalized {len(payload.get('scenarios') or [])} testcase(s). Each testcase will generate its own Playwright spec in the selected existing framework.",
    }


def _code_files(root: Path, dirs: list[str]) -> list[Path]:
    files: list[Path] = []
    for rel in dirs:
        base = root / rel
        if not base.exists():
            continue
        files.extend(p for p in base.rglob('*') if p.is_file() and p.suffix.lower() in _CODE_EXTENSIONS)
    return sorted(dict.fromkeys(files), key=lambda p: _rel(p, root).lower())


def _tokens(*values: str) -> list[str]:
    ignore = {
        'page', 'test', 'case', 'scenario', 'flow', 'validate', 'verify', 'the', 'and', 'with',
        'click', 'enter', 'select', 'open', 'navigate', 'displayed', 'visible', 'successfully',
        'button', 'field', 'section', 'record', 'created', 'expected', 'result', 'valid', 'new',
    }
    return [x for x in re.findall(r'[a-z0-9]+', ' '.join(values).lower()) if len(x) > 2 and x not in ignore]


def _file_score(path: Path, root: Path, tokens: list[str]) -> int:
    rel = _rel(path, root).lower()
    try:
        text = path.read_text(encoding='utf-8', errors='replace')[:120000].lower()
    except Exception:
        text = ''
    score = sum(6 for token in tokens if token in path.stem.lower())
    score += sum(2 for token in tokens if token in rel)
    score += sum(1 for token in tokens if token in text)
    if 'export class' in text:
        score += 3
    if 'page' in path.stem.lower():
        score += 1
    return score


def _is_concrete_page_file(path: Path) -> bool:
    name = path.stem.lower()
    if name in {'basepage', 'base_page', 'abstractpage', 'pagebase'} or name.startswith(('basepage.', 'abstractpage.')):
        return False
    if any(part.lower() in {'utils', 'utilities', 'helpers', 'fixtures', 'config', 'configs'} for part in path.parts):
        return False
    try:
        text = path.read_text(encoding='utf-8', errors='replace')[:8000]
    except Exception:
        return False
    if re.search(r'export\s+abstract\s+class\s+', text):
        return False
    return bool(re.search(r'export\s+(?:default\s+)?class\s+', text))


def _rank_files(root: Path, files: list[Path], tokens: list[str]) -> list[dict[str, Any]]:
    ranked = [{'path': _rel(path, root), 'score': _file_score(path, root, tokens)} for path in files]
    return sorted(ranked, key=lambda x: (-x['score'], len(x['path']), x['path'].lower()))


def _choose_test_dir(root: Path, profile: dict[str, Any], feature: str, explicit: str = '') -> tuple[Path, list[str]]:
    selected = _resolve_under_root(root, explicit) if explicit else None
    reasons: list[str] = []
    if selected:
        reasons.append('User explicitly selected this test folder.')
        return selected, reasons
    configured = profile.get('configured_test_dirs') or []
    if configured:
        configured_dir = root / configured[0]
        generated_subdir = configured_dir / 'generated'
        if generated_subdir.exists() and (any(generated_subdir.glob('*.spec.*')) or (generated_subdir / '.gitkeep').exists()):
            reasons.append('Selected the existing generated-spec subfolder under Playwright testDir to preserve framework conventions and execution scripts.')
            return generated_subdir, reasons
        reasons.append('Selected from Playwright config testDir discovered by framework learning.')
        return configured_dir, reasons
    roots = profile.get('discovered_test_roots') or []
    if roots:
        reasons.append('Selected from recursively proven executable Playwright test root.')
        return root / roots[0], reasons
    specs = profile.get('executable_specs') or []
    if specs:
        reasons.append('Selected from the parent folder of an existing executable spec.')
        return (root / specs[0]).parent, reasons
    reasons.append('No test root exists; tests is the conventional fallback and will be created inside the selected framework.')
    return root / 'tests', reasons


def _class_name(path: Path, fallback: str) -> str:
    if path.exists():
        text = path.read_text(encoding='utf-8', errors='replace')
        match = re.search(r'export\s+(?:default\s+)?class\s+([A-Za-z_$][\w$]*)', text)
        if match:
            return match.group(1)
    return fallback


def _placement_for_scenario(root: Path, profile: dict[str, Any], scenario: dict[str, Any], feature: str, explicit_page: str = '', explicit_locator: str = '') -> dict[str, Any]:
    components = profile.get('component_directory_model') or {}
    page_dirs = components.get('page_dirs') or []
    object_dirs = components.get('page_object_dirs') or []
    page_files = [path for path in _code_files(root, page_dirs) if _is_concrete_page_file(path)]
    object_files = _code_files(root, object_dirs)
    step_context = ' '.join(str(step.get('target') or '') for step in scenario.get('steps') or [])
    tokens = _tokens(feature, str(scenario.get('page') or ''), str(scenario.get('title') or ''), step_context)
    explicit_page_path = _resolve_under_root(root, explicit_page, allow_missing=True) if explicit_page else None
    explicit_locator_path = _resolve_under_root(root, explicit_locator, allow_missing=True) if explicit_locator else None
    ranked_pages = _rank_files(root, page_files, tokens)
    ranked_objects = _rank_files(root, object_files, tokens)
    page_path = explicit_page_path
    locator_path = explicit_locator_path
    page_reason = 'explicit_user_selection' if page_path else ''
    locator_reason = 'explicit_user_selection' if locator_path else ''
    ambiguous = False
    if page_path is None and ranked_pages:
        context_tokens = _tokens(str(scenario.get('page') or ''))
        matching_context = next((item for item in ranked_pages if any(token in Path(item['path']).stem.lower() for token in context_tokens)), None)
        selected = matching_context or ranked_pages[0]
        selected_name = Path(selected['path']).stem.lower()
        context_matches_name = any(token in selected_name for token in context_tokens)
        if not context_tokens or str(scenario.get('page') or '').lower() in {'home', 'generated'} or context_matches_name:
            page_path = root / selected['path']
            page_reason = 'best_existing_page_match'
            if matching_context is None and len(ranked_pages) > 1 and ranked_pages[0]['score'] == ranked_pages[1]['score'] and ranked_pages[0]['score'] > 0:
                ambiguous = True
        else:
            page_reason = 'no_existing_page_matches_application_context'
    if locator_path is None and page_path is not None:
        linked = next((candidate for candidate in object_files if _locator_binding(page_path, candidate) is not None), None)
        if linked is not None:
            locator_path = linked
            locator_reason = 'existing_locator_repository_imported_or_instantiated_by_selected_page'
        else:
            locator_path = page_path
            locator_reason = 'safe_unified_page_object_placement; no linked locator repository was detected'
    return {
        'scenario_id': scenario.get('id'),
        'scenario_title': scenario.get('title'),
        'recommended_page_file': _rel(page_path, root) if page_path else '',
        'recommended_locator_file': _rel(locator_path, root) if locator_path else '',
        'page_reason': page_reason or 'no_existing_page_match',
        'locator_reason': locator_reason or 'no_existing_locator_match',
        'ambiguous': ambiguous,
        'page_candidates': ranked_pages[:12],
        'locator_candidates': ranked_objects[:12],
    }


def preview_generation_placement(
    framework_path: str,
    feature: str,
    target_test_folder: str = '',
    target_page_file: str = '',
    target_locator_file: str = '',
    placement_mode: str = 'confirm_if_ambiguous',
) -> dict[str, Any]:
    root = Path(framework_path).expanduser().resolve()
    if not root.exists():
        return {'ok': False, 'error': f'Framework path does not exist: {root}'}
    feature = _safe_feature(feature)
    testcase_path = feature_testcase_path('module2_uploaded', feature)
    if not testcase_path.exists():
        return {'ok': False, 'error': 'Load/normalize testcase source first.'}
    payload = read_json(testcase_path)
    profile = build_structure_profile(root, limit=7000)
    test_dir, test_reasons = _choose_test_dir(root, profile, feature, target_test_folder)
    placements = [
        _placement_for_scenario(root, profile, scenario, feature, target_page_file, target_locator_file)
        for scenario in payload.get('scenarios') or []
    ]
    unresolved = [p for p in placements if not p.get('recommended_page_file')]
    ambiguous = [p for p in placements if p.get('ambiguous')]
    needs_confirmation = bool(unresolved or (ambiguous and placement_mode == 'confirm_if_ambiguous'))
    return {
        'ok': True,
        'framework_path': str(root),
        'feature': feature,
        'scenario_count': len(placements),
        'recommended_test_folder': _rel(test_dir, root),
        'test_folder_reasons': test_reasons,
        'placements': placements,
        'needs_user_confirmation': needs_confirmation,
        'unresolved_scenarios': [p['scenario_id'] for p in unresolved],
        'ambiguous_scenarios': [p['scenario_id'] for p in ambiguous],
        'message': 'Placement preview completed. No framework source file was modified.' if not needs_confirmation else 'Placement is ambiguous or no reusable page file exists. Select the page/locator target or allow a new support file before generation.',
    }


def _backup_file(root: Path, path: Path, backup_root: Path) -> str:
    rel = _rel(path, root)
    if path.exists():
        target = backup_root / rel
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
    return rel


def _rollback_generation(root: Path, backup_root: Path, created_paths: set[str]) -> dict[str, Any]:
    restored: list[str] = []
    deleted: list[str] = []
    if backup_root.exists():
        for backup in sorted((p for p in backup_root.rglob('*') if p.is_file()), key=lambda p: len(p.parts)):
            rel = backup.relative_to(backup_root)
            target = root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(backup, target)
            restored.append(rel.as_posix())
    for rel in sorted(created_paths, key=lambda value: len(Path(value).parts), reverse=True):
        target = root / rel
        if target.exists() and target.is_file():
            target.unlink()
            deleted.append(rel)
        parent = target.parent
        while parent != root and parent.exists():
            try:
                parent.rmdir()
            except OSError:
                break
            parent = parent.parent
    return {
        'performed': True,
        'restored_files': sorted(dict.fromkeys(restored)),
        'deleted_created_files': sorted(dict.fromkeys(deleted)),
        'reason': 'Playwright validation failed, so AstraHeal restored every pre-existing file from backup and removed every newly created source/spec file.',
    }


def _matching_brace_index(text: str, open_index: int) -> int:
    depth = 0
    quote = ''
    escaped = False
    line_comment = False
    block_comment = False
    i = open_index
    while i < len(text):
        char = text[i]
        nxt = text[i + 1] if i + 1 < len(text) else ''
        if line_comment:
            if char == '\n':
                line_comment = False
            i += 1
            continue
        if block_comment:
            if char == '*' and nxt == '/':
                block_comment = False
                i += 2
                continue
            i += 1
            continue
        if quote:
            if escaped:
                escaped = False
            elif char == '\\':
                escaped = True
            elif char == quote:
                quote = ''
            i += 1
            continue
        if char == '/' and nxt == '/':
            line_comment = True
            i += 2
            continue
        if char == '/' and nxt == '*':
            block_comment = True
            i += 2
            continue
        if char in {'\'', '"', '`'}:
            quote = char
            i += 1
            continue
        if char == '{':
            depth += 1
        elif char == '}':
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def _class_close_index(text: str, class_name: str = '') -> int:
    name = rf'\s+{re.escape(class_name)}\b' if class_name else r'\s+[A-Za-z_$][\w$]*\b'
    match = re.search(rf'export\s+(?:default\s+)?(?:abstract\s+)?class{name}[^{{]*{{', text)
    if not match:
        return -1
    open_index = text.find('{', match.start())
    return _matching_brace_index(text, open_index)


def _append_member(path: Path, member: str, symbol: str) -> bool:
    text = path.read_text(encoding='utf-8', errors='replace') if path.exists() else ''
    if re.search(rf'\b{re.escape(symbol)}\b', text):
        return False
    class_name = _class_name(path, '')
    idx = _class_close_index(text, class_name)
    if idx < 0:
        raise ValueError(f'Could not safely identify exported class boundary in {path}')
    path.write_text(text[:idx].rstrip() + '\n\n' + member.rstrip() + '\n' + text[idx:], encoding='utf-8')
    return True


def _locator_name(target: str) -> str:
    base = camel_case(re.sub(r'[^A-Za-z0-9 ]+', ' ', _semantic_target(target))) or 'element'
    return base if base.lower().endswith('locator') else base + 'Locator'


def _method_name(action: str, target: str) -> str:
    words = re.findall(r'[A-Za-z0-9]+', f'{action} {_semantic_target(target)}')[:7]
    name = ''.join(x[:1].upper() + x[1:] for x in words) or 'PerformStep'
    lower = name[:1].lower() + name[1:]
    return lower if lower.startswith(('click', 'fill', 'verify', 'select', 'goto', 'navigate', 'perform')) else 'perform' + name


def _locator_expression(target: str, action: str) -> str:
    label = re.sub(r"['`\n\r]", '', _locator_label(target))[:120]
    original_label = re.sub(r"['`\n\r]", '', _semantic_target(target))[:120]
    low = f'{action} {target}'.lower()
    escaped = re.escape(label).replace('/', r'\/')
    rx = f'/{escaped}/i'
    if any(x in low for x in ('select', 'dropdown', 'combobox', 'picklist')):
        return f"this.page.getByRole('combobox', {{ name: {rx} }}).or(this.page.getByLabel({rx})).first()"
    if any(x in low for x in ('checkbox', 'check box')):
        return f"this.page.getByRole('checkbox', {{ name: {rx} }}).or(this.page.getByLabel({rx})).first()"
    if any(x in low for x in ('radio', 'option button')):
        return f"this.page.getByRole('radio', {{ name: {rx} }}).or(this.page.getByLabel({rx})).first()"
    if any(x in low for x in ('email', 'username', 'password', 'textbox', 'input', 'field', 'first name', 'last name', 'mobile', 'notes', 'search box')):
        original_rx = f'/{re.escape(original_label).replace(chr(47), chr(92)+chr(47))}/i'
        return f"this.page.getByRole('textbox', {{ name: {rx} }}).or(this.page.getByLabel({rx})).or(this.page.getByPlaceholder({rx})).or(this.page.getByText({original_rx})).first()"
    if any(x in low for x in ('button', 'click', 'submit', 'save', 'continue', 'login', 'sign in', 'icon')):
        original_rx = f'/{re.escape(original_label).replace(chr(47), chr(92)+chr(47))}/i'
        return f"this.page.getByRole('button', {{ name: {rx} }}).or(this.page.getByRole('link', {{ name: {rx} }})).or(this.page.getByText({rx})).or(this.page.getByText({original_rx})).first()"
    if any(x in low for x in ('link', 'navigate', 'menu', 'tab')):
        return f"this.page.getByRole('link', {{ name: {rx} }}).or(this.page.getByRole('button', {{ name: {rx} }})).or(this.page.getByText({rx})).first()"
    if any(x in low for x in ('heading', 'title', 'header')):
        return f"this.page.getByRole('heading', {{ name: {rx} }}).or(this.page.getByText({rx})).first()"
    return f"this.page.getByText({rx}).first()"


def _ts_single_quote(value: str) -> str:
    return str(value).replace('\\', '\\\\').replace("'", "\\'").replace('\r', ' ').replace('\n', ' ')


def _locator_definition(target: str, action: str) -> str:
    label = _ts_single_quote(_locator_label(target)[:120])
    description = _ts_single_quote(_semantic_target(target)[:120])
    original_fallback = f", {{ strategy: 'text', value: '{description}' }}" if description.lower() != label.lower() else ''
    low = f'{action} {target}'.lower()
    if any(x in low for x in ('select', 'dropdown', 'combobox', 'picklist')):
        return f"{{ strategy: 'role', role: 'combobox', value: '{label}', description: '{description}', fallbacks: [{{ strategy: 'label', value: '{label}' }}, {{ strategy: 'text', value: '{label}' }}{original_fallback}] }}"
    if any(x in low for x in ('checkbox', 'check box')):
        return f"{{ strategy: 'role', role: 'checkbox', value: '{label}', description: '{description}', fallbacks: [{{ strategy: 'label', value: '{label}' }}, {{ strategy: 'text', value: '{label}' }}{original_fallback}] }}"
    if any(x in low for x in ('radio', 'option button')):
        return f"{{ strategy: 'role', role: 'radio', value: '{label}', description: '{description}', fallbacks: [{{ strategy: 'label', value: '{label}' }}, {{ strategy: 'text', value: '{label}' }}{original_fallback}] }}"
    if any(x in low for x in ('email', 'username', 'password', 'textbox', 'input', 'field', 'first name', 'last name', 'mobile', 'notes', 'search box')):
        return f"{{ strategy: 'role', role: 'textbox', value: '{label}', description: '{description}', fallbacks: [{{ strategy: 'label', value: '{label}' }}, {{ strategy: 'placeholder', value: '{label}' }}, {{ strategy: 'text', value: '{label}' }}{original_fallback}] }}"
    if any(x in low for x in ('button', 'click', 'submit', 'save', 'continue', 'login', 'sign in', 'icon')):
        css_label = _ts_single_quote(_normalise_locator_value(label)).replace('\"', '\\"')
        css_candidates = (
            f'input[type="submit"][value*="{css_label}" i], '
            f'input[type="button"][value*="{css_label}" i], '
            f'button[title*="{css_label}" i], '
            f'[role="button"][aria-label*="{css_label}" i]'
        )
        login_aliases = ''
        if re.search(r'(?i)log\s*in|login|sign\s*in|sandbox', label + ' ' + description):
            css_candidates = '#Login, input[name="Login"], button[name="Login"], input[type="submit"][value*="log in" i], input[type="button"][value*="log in" i], ' + css_candidates
            login_aliases = ", { strategy: 'role', role: 'button', value: 'Log In to Sandbox' }, { strategy: 'role', role: 'button', value: 'Log In' }, { strategy: 'role', role: 'button', value: 'Login' }"
        return f"{{ strategy: 'role', role: 'button', value: '{label}', description: '{description}', fallbacks: [{{ strategy: 'role', role: 'link', value: '{label}' }}, {{ strategy: 'text', value: '{label}' }}, {{ strategy: 'css', value: '{css_candidates}' }}{login_aliases}{original_fallback}] }}"
    if any(x in low for x in ('link', 'navigate', 'menu', 'tab')):
        return f"{{ strategy: 'role', role: 'link', value: '{label}', description: '{description}', fallbacks: [{{ strategy: 'role', role: 'button', value: '{label}' }}, {{ strategy: 'text', value: '{label}' }}{original_fallback}] }}"
    if any(x in low for x in ('heading', 'title', 'header')):
        return f"{{ strategy: 'role', role: 'heading', value: '{label}', description: '{description}', fallbacks: [{{ strategy: 'text', value: '{label}' }}{original_fallback}] }}"
    return f"{{ strategy: 'text', value: '{label}', description: '{description}', fallbacks: [{{ strategy: 'text', value: '{description}' }}] }}" if description.lower() != label.lower() else f"{{ strategy: 'text', value: '{label}', description: '{description}' }}"


def _create_page_file(path: Path, class_name: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "import { Page } from '@playwright/test';\n\n"
        f"export class {class_name} {{\n"
        "  constructor(private readonly page: Page) {}\n"
        "}\n",
        encoding='utf-8',
    )


def _create_framework_support_files(root: Path, profile: dict[str, Any], class_name: str) -> tuple[Path, Path, list[Path]]:
    components = profile.get('component_directory_model') or {}
    page_dir = root / ((components.get('page_dirs') or ['pages'])[0])
    object_dirs = components.get('page_object_dirs') or []
    page_path = page_dir / f'{class_name}.ts'
    created: list[Path] = []
    base_candidates = [path for path in _code_files(root, components.get('page_dirs') or ['pages']) if path.stem.lower() in {'basepage', 'base_page'}]
    locator_factory = next((path for path in root.rglob('locatorFactory.ts') if path.is_file()), None)
    if base_candidates and object_dirs and locator_factory:
        base_path = base_candidates[0]
        object_dir = root / object_dirs[0]
        locator_name = f'{class_name}Objects'
        locator_path = object_dir / f'{class_name}.objects.ts'
        if not locator_path.exists():
            locator_path.parent.mkdir(parents=True, exist_ok=True)
            factory_import = _relative_import(locator_path, locator_factory)
            locator_path.write_text(
                f"import type {{ LocatorDefinition }} from '{factory_import}';\n\n"
                f"export const {locator_name} = {{\n"
                f"}} satisfies Record<string, LocatorDefinition>;\n",
                encoding='utf-8',
            )
            created.append(locator_path)
        if not page_path.exists():
            page_path.parent.mkdir(parents=True, exist_ok=True)
            base_import = _relative_import(page_path, base_path)
            locator_import = _relative_import(page_path, locator_path)
            page_path.write_text(
                "import type { Page } from '@playwright/test';\n"
                f"import {{ BasePage }} from '{base_import}';\n"
                f"import {{ {locator_name} }} from '{locator_import}';\n\n"
                f"export class {class_name} extends BasePage {{\n"
                "  constructor(page: Page) {\n"
                "    super(page);\n"
                "  }\n"
                "}\n",
                encoding='utf-8',
            )
            created.append(page_path)
        return page_path, locator_path, created
    if not page_path.exists():
        _create_page_file(page_path, class_name)
        created.append(page_path)
    return page_path, page_path, created


def _object_literal_name(path: Path) -> str:
    if not path.exists():
        return ''
    text = path.read_text(encoding='utf-8', errors='replace')
    match = re.search(r'export\s+const\s+([A-Za-z_$][\w$]*)\s*=\s*{', text)
    return match.group(1) if match else ''


def _locator_binding(page_path: Path, locator_path: Path) -> dict[str, str] | None:
    if page_path.resolve() == locator_path.resolve():
        return {'style': 'direct_class_member', 'locator_expression': 'this.{locator}', 'smart_locator_expression': '', 'reference': 'this'}
    if not page_path.exists() or not locator_path.exists():
        return None
    page_text = page_path.read_text(encoding='utf-8', errors='replace')
    object_name = _object_literal_name(locator_path)
    if object_name and re.search(rf'\b{re.escape(object_name)}\b', page_text) and ('getLocator' in page_text or re.search(r'extends\s+BasePage\b', page_text)):
        return {
            'style': 'locator_definition_object',
            'collection': object_name,
            'locator_expression': f'this.getLocator({object_name}.{{locator}})',
            'smart_locator_expression': f'this.getSmartLocator({object_name}.{{locator}})',
            'reference': object_name,
        }
    locator_class = _class_name(locator_path, pascal_case(locator_path.stem))
    if locator_class not in page_text:
        return None
    patterns = [
        rf'this\.([A-Za-z_$][\w$]*)\s*=\s*new\s+{re.escape(locator_class)}\s*\(',
        rf'(?:private|protected|public|readonly|private\s+readonly|protected\s+readonly)?\s*([A-Za-z_$][\w$]*)\s*[:=][^;\n]*\b{re.escape(locator_class)}\b',
    ]
    for pattern in patterns:
        match = re.search(pattern, page_text)
        if match:
            reference = f'this.{match.group(1)}'
            return {'style': 'locator_class_instance', 'locator_expression': reference + '.{locator}', 'smart_locator_expression': '', 'reference': reference}
    return None


def _walkthrough_locator(step: dict[str, Any]) -> dict[str, Any]:
    evidence = step.get('walkthrough') or {}
    locator = dict(evidence.get('locator') or {})
    if evidence.get('status') not in {'verified', 'human_guided_verified', 'adaptive_intermediate_verified', 'authenticated_session_reused', 'codegen_verified'}:
        return {}
    strategy = str(locator.get('strategy') or '').strip()
    value = _normalise_locator_candidate_value(strategy, str(locator.get('value') or ''))
    role = str(locator.get('role') or '').strip().lower()
    if not strategy or not value or value.lower() in {'undefined', 'null', 'none'}:
        return {}
    if strategy == 'role' and role not in _VALID_LOCATOR_ROLES:
        return {}
    locator['value'] = value
    if strategy == 'role':
        locator['role'] = role
    return locator


def _locator_definition_from_walkthrough(locator: dict[str, Any], target: str) -> str:
    strategy = str(locator.get('strategy') or '').strip()
    value_raw = _normalise_locator_candidate_value(strategy, str(locator.get('value') or ''))
    role_raw = str(locator.get('role') or '').strip().lower()
    if not strategy or not value_raw:
        raise ValueError('Verified walkthrough locator is missing strategy or value.')
    if strategy == 'role' and role_raw not in _VALID_LOCATOR_ROLES:
        raise ValueError(f'Verified walkthrough role is missing or invalid: {role_raw or "undefined"}')

    value = _ts_single_quote(value_raw)
    role = _ts_single_quote(role_raw)
    description_raw = _normalise_ui_text(str(target or locator.get('value') or 'verified locator'))
    description = _ts_single_quote(description_raw)
    low = f"{description_raw} {value_raw}".lower()

    candidate_defs: list[str] = []
    seen: set[tuple[str, str, str]] = set()

    def add_candidate(st: str, val: str, rl: str = '') -> None:
        st = str(st or '').strip()
        val = _normalise_locator_candidate_value(st, str(val or ''))
        rl = str(rl or '').strip().lower()
        if not st or not val or val.lower() in {'undefined', 'null', 'none'}:
            return
        if st == 'role' and rl not in _VALID_LOCATOR_ROLES:
            return
        key = (st, rl, val)
        if key in seen:
            return
        seen.add(key)
        val_q = _ts_single_quote(val)
        if st == 'role':
            candidate_defs.append(f"{{ strategy: 'role', role: '{_ts_single_quote(rl)}', value: '{val_q}' }}")
        else:
            candidate_defs.append(f"{{ strategy: '{_ts_single_quote(st)}', value: '{val_q}' }}")

    for item in list(locator.get('fallbacks') or [])[:8]:
        add_candidate(str(item.get('strategy') or ''), str(item.get('value') or ''), str(item.get('role') or ''))

    stable = dict(locator.get('stable_attributes') or {})
    dom_id = str(stable.get('dom_id') or '').strip()
    element_name = str(stable.get('name') or '').strip()
    control_type = str(stable.get('type') or '').strip().lower()
    control_value = _normalise_locator_value(str(stable.get('control_value') or ''))
    if dom_id and re.fullmatch(r'[A-Za-z_][\w:.-]*', dom_id):
        add_candidate('css', f'#{dom_id}')
    if element_name and re.fullmatch(r'[A-Za-z_][\w:.-]*', element_name):
        add_candidate('css', f'input[name="{element_name}"], button[name="{element_name}"], [name="{element_name}"]')
    if control_value and control_type in {'button', 'submit', 'reset', 'image'}:
        add_candidate('css', f'input[type="{control_type}"][value="{control_value}"]')

    # Multi-stage login pages frequently reuse the same native submit control
    # while changing only its displayed value. Keep a stable selector and all
    # observed accessible-name aliases so both username and password stages use
    # the exact same DOM control instead of two guessed role/name pairs.
    if any(token in low for token in ('login', 'log in', 'sign in', 'sandbox')):
        add_candidate('css', '#Login, input[name="Login"], button[name="Login"]')
        for alias in ('Log In to Sandbox', 'Log In', 'Login', 'Sign In', 'Continue'):
            if alias.lower() != value_raw.lower():
                add_candidate('role', alias, 'button')
        add_candidate('css', 'input[type="submit"][value*="log in" i], input[type="button"][value*="log in" i], button[type="submit"]')

    fallback_text = f", fallbacks: [{', '.join(candidate_defs[:10])}]" if candidate_defs else ''
    if strategy == 'role':
        return f"{{ strategy: 'role', role: '{role}', value: '{value}', description: '{description}'{fallback_text} }}"
    return f"{{ strategy: '{_ts_single_quote(strategy)}', value: '{value}', description: '{description}'{fallback_text} }}"

def _locator_expression_from_walkthrough(locator: dict[str, Any]) -> str:
    strategy = str(locator.get('strategy') or '')
    value = json.dumps(_normalise_locator_candidate_value(strategy, str(locator.get('value') or '')))
    exact = ', exact: true' if locator.get('exact') else ''
    if strategy == 'testId': return f"this.page.getByTestId({value})"
    if strategy == 'role':
        role = str(locator.get('role') or '').strip()
        if role not in _VALID_LOCATOR_ROLES:
            raise ValueError(f'Invalid verified walkthrough role locator: {role or "missing role"}')
        return f"this.page.getByRole({json.dumps(role)}, {{ name: {value}{exact} }})"
    if strategy == 'label': return f"this.page.getByLabel({value}, {{ exact: {str(bool(locator.get('exact'))).lower()} }})"
    if strategy == 'placeholder': return f"this.page.getByPlaceholder({value}, {{ exact: {str(bool(locator.get('exact'))).lower()} }})"
    if strategy == 'text': return f"this.page.getByText({value}, {{ exact: {str(bool(locator.get('exact'))).lower()} }})"
    if strategy == 'css': return f"this.page.locator({value})"
    raise ValueError(f'Unsupported verified walkthrough locator strategy: {strategy}')


def _find_existing_locator_name(locator_text: str, locator: dict[str, Any]) -> str:
    """Find an existing locator property with the same verified Codegen locator."""
    if not locator:
        return ''
    strategy = str(locator.get('strategy') or '').strip()
    value = _normalise_locator_candidate_value(strategy, str(locator.get('value') or ''))
    role = str(locator.get('role') or '').strip().lower()
    if not strategy or not value:
        return ''
    # Object-repository style: propertyName: { strategy: ..., value: ... }
    for match in re.finditer(r'(?m)^\s*([A-Za-z_$][\w$]*)\s*:\s*\{', locator_text):
        open_index = locator_text.find('{', match.start())
        close_index = _matching_brace_index(locator_text, open_index)
        if close_index < 0:
            continue
        block = locator_text[open_index:close_index + 1]
        st = re.search(r"strategy\s*:\s*['\"]([^'\"]+)['\"]", block)
        val = re.search(r"value\s*:\s*['\"]([^'\"]*)['\"]", block)
        rl = re.search(r"role\s*:\s*['\"]([^'\"]+)['\"]", block)
        if not st or not val:
            continue
        existing_strategy = st.group(1)
        existing_value = _normalise_locator_candidate_value(existing_strategy, val.group(1))
        existing_role = rl.group(1).lower() if rl else ''
        if existing_strategy == strategy and existing_value == value and (strategy != 'role' or existing_role == role):
            return match.group(1)
    # Direct page-member style generated by Playwright locators.
    expressions = {
        'role': rf"getByRole\(\s*['\"]{re.escape(role)}['\"]\s*,\s*\{{[^}}]*name\s*:\s*['\"]{re.escape(value)}['\"]",
        'label': rf"getByLabel\(\s*['\"]{re.escape(value)}['\"]",
        'placeholder': rf"getByPlaceholder\(\s*['\"]{re.escape(value)}['\"]",
        'text': rf"getByText\(\s*['\"]{re.escape(value)}['\"]",
        'testId': rf"getByTestId\(\s*['\"]{re.escape(value)}['\"]",
        'css': rf"locator\(\s*['\"]{re.escape(value)}['\"]",
        'xpath': rf"locator\(\s*['\"](?:xpath=)?{re.escape(value)}['\"]",
    }
    pattern = expressions.get(strategy)
    if pattern:
        for match in re.finditer(r'(?m)^\s*(?:readonly\s+)?([A-Za-z_$][\w$]*)\s*=\s*([^;]+);', locator_text):
            if re.search(pattern, match.group(2)):
                return match.group(1)
    return ''


def _find_existing_method_for_locator(page_text: str, locator_name: str, action: str) -> str:
    if not locator_name:
        return ''
    action_tokens = {
        'fill': ('fill(', 'type('), 'type': ('fill(', 'type('), 'enter': ('fill(', 'type('),
        'select': ('selectOption(', "getByRole('option'", 'getByRole("option"'),
        'verify': ('expect(', 'toBeVisible(', 'toContainText(', 'toHaveText('),
        'assert': ('expect(', 'toBeVisible(', 'toContainText(', 'toHaveText('),
        'expect': ('expect(', 'toBeVisible(', 'toContainText(', 'toHaveText('),
        'validate': ('expect(', 'toBeVisible(', 'toContainText(', 'toHaveText('),
    }.get(action, ('click(',))
    for match in re.finditer(r'(?m)^\s*(?:public\s+|private\s+|protected\s+)?async\s+([A-Za-z_$][\w$]*)\s*\([^)]*\)\s*\{', page_text):
        open_index = page_text.find('{', match.start())
        close_index = _matching_brace_index(page_text, open_index)
        if close_index < 0:
            continue
        block = page_text[open_index:close_index + 1]
        if re.search(rf'\b{re.escape(locator_name)}\b', block) and any(token in block for token in action_tokens):
            return match.group(1)
    return ''


def _append_locator(path: Path, locator: str, target: str, action: str, binding: dict[str, str], walkthrough_locator: dict[str, Any] | None = None) -> bool:
    text = path.read_text(encoding='utf-8', errors='replace') if path.exists() else ''
    if re.search(rf'\b{re.escape(locator)}\b', text):
        return False
    if binding.get('style') == 'locator_definition_object':
        object_name = binding.get('collection') or _object_literal_name(path)
        match = re.search(rf'export\s+const\s+{re.escape(object_name)}\s*=\s*{{', text)
        if not match:
            raise ValueError(f'Could not safely identify locator object boundary in {path}')
        open_index = text.find('{', match.start())
        close_index = _matching_brace_index(text, open_index)
        if close_index < 0:
            raise ValueError(f'Could not safely identify locator object closing brace in {path}')
        definition = _locator_definition_from_walkthrough(walkthrough_locator, target) if walkthrough_locator else _locator_definition(target, action)
        member = f"  {locator}: {definition},"
        path.write_text(text[:close_index].rstrip() + '\n' + member + '\n' + text[close_index:], encoding='utf-8')
        return True
    expression = _locator_expression_from_walkthrough(walkthrough_locator) if walkthrough_locator else _locator_expression(target, action)
    member = f"  readonly {locator} = {expression};"
    return _append_member(path, member, locator)



def _linked_locator_reference(page_path: Path, locator_path: Path) -> str | None:
    binding = _locator_binding(page_path, locator_path)
    return binding.get('reference') if binding else None

def _relative_import(from_file: Path, to_file: Path) -> str:
    rel = os.path.relpath(to_file.with_suffix(''), from_file.parent).replace('\\', '/')
    return rel if rel.startswith('.') else './' + rel


def _unique_spec_path(test_dir: Path, feature: str, scenario: dict[str, Any], index: int) -> Path:
    """Return a stable scenario path for repeatable iterative generation.

    Re-running the same scenario updates its existing spec through the normal
    backup/rollback path instead of creating ``-2``, ``-3`` duplicate specs.
    New scenario IDs still create new independent files.
    """
    label = safe_id(str(scenario.get('id') or scenario.get('title') or index)).replace('_', '-').lower()
    return test_dir / f'{feature}-{label}.spec.ts'


def _step_call(
    step: dict[str, Any],
    method: str,
    *,
    data_reference: str = 'data',
    data_keys: dict[str, str] | None = None,
) -> str:
    action = str(step.get('action') or '').lower()
    keys = dict(data_keys or {})
    value_key = keys.get('value', '')
    expected_key = keys.get('expected', '')
    if action in {'goto', 'open', 'launch', 'navigate'}:
        arg = f'{data_reference}.{value_key}' if value_key else "process.env.BASE_URL || process.env.TEST_BASE_URL || '/'"
        return f'await screen.{method}({arg});'
    if action in {'fill', 'type', 'enter', 'select'}:
        if value_key:
            return f'await screen.{method}({data_reference}.{value_key});'
        return f"throw new Error('Missing concrete test data for: {_ts_single_quote(str(step.get('target') or method))}');"
    if action in {'verify', 'assert', 'expect', 'validate'} and expected_key:
        return f'await screen.{method}({data_reference}.{expected_key});'
    return f'await screen.{method}();'


def _choose_test_data_dir(root: Path, profile: dict[str, Any]) -> Path:
    model = profile.get('component_directory_model') or {}
    existing = [str(value) for value in (model.get('test_data_dirs') or []) if str(value).strip()]
    return root / (existing[0] if existing else 'testData')


def _feature_test_data_files(root: Path, profile: dict[str, Any], feature: str) -> tuple[Path, Path]:
    directory = _choose_test_data_dir(root, profile)
    return directory / f'{feature}.data.ts', directory / f'{feature}.env.example'


def _runtime_environment_loader_text() -> str:
    return """// @ts-nocheck
import { existsSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const LOCAL_ENV_FILE = resolve(process.cwd(), '.env.astraheal.local');
let loaded = false;

export function loadAstraHealLocalEnvironment(): void {
  if (loaded) return;
  loaded = true;
  if (!existsSync(LOCAL_ENV_FILE)) return;
  for (const rawLine of readFileSync(LOCAL_ENV_FILE, 'utf8').split(/\\r?\\n/)) {
    const line = rawLine.trim();
    if (!line || line.startsWith('#')) continue;
    const separator = line.indexOf('=');
    if (separator < 1) continue;
    const key = line.slice(0, separator).trim();
    let value = line.slice(separator + 1).trim();
    if ((value.startsWith('"') && value.endsWith('"')) || (value.startsWith("'") && value.endsWith("'"))) {
      value = value.slice(1, -1);
    }
    if (process.env[key] === undefined) process.env[key] = value;
  }
}

loadAstraHealLocalEnvironment();

export function requiredSecret(name: string): string {
  const value = String(process.env[name] ?? '').trim();
  if (!value) {
    throw new Error(
      `Required runtime credential is missing: ${name}. ` +
      `Reload the testcase workbook and regenerate, or add ${name}=... to ${LOCAL_ENV_FILE}`,
    );
  }
  return value;
}

export function optionalRuntime(name: string, fallback: string): string {
  const value = String(process.env[name] ?? '').trim();
  return value || fallback;
}

function dateText(date: Date): string {
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  return `${month}/${day}/${date.getFullYear()}`;
}

export function todayDate(): string {
  return dateText(new Date());
}

export function futureDate(days = 1): string {
  const date = new Date();
  date.setDate(date.getDate() + days);
  return dateText(date);
}

export function uniqueRunValue(prefix: string): string {
  return `${prefix} ${new Date().toISOString().replace(/[-:.TZ]/g, '').slice(0, 14)}`;
}
"""


def _read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding='utf-8', errors='replace').splitlines():
        line = raw_line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _env_file_value(value: str) -> str:
    # Keep the local file readable while preserving spaces and special symbols.
    escaped = str(value).replace('\\', '\\\\').replace('"', '\\"').replace('\r', '').replace('\n', '\\n')
    return f'"{escaped}"'


def _ensure_local_secret_gitignore(root: Path) -> Path:
    path = root / '.gitignore'
    existing = path.read_text(encoding='utf-8', errors='replace') if path.exists() else ''
    entries = ['.env.astraheal.local', '.env.astraheal.*.local']
    missing = [entry for entry in entries if entry not in {line.strip() for line in existing.splitlines()}]
    if missing:
        prefix = '' if not existing or existing.endswith('\n') else '\n'
        path.write_text(existing + prefix + '\n'.join(missing) + '\n', encoding='utf-8')
    return path


def _scenario_non_sensitive_values(scenario: dict[str, Any]) -> list[tuple[str, str]]:
    values: list[tuple[str, str]] = []
    for step in scenario.get('steps') or []:
        if step.get('value_sensitive'):
            continue
        value = str(step.get('value') or '').strip()
        if value:
            values.append((str(step.get('target') or step.get('description') or '').lower(), value))
    return values


def _optional_runtime_fallback_expression(step: dict[str, Any], scenario: dict[str, Any]) -> tuple[str, str]:
    """Return a runnable TypeScript fallback and a plain-English explanation.

    Functional workbooks often contain labels such as ``Date`` or ``Product``
    instead of an executable value. Those are optional data gaps, not secrets.
    Browser grounding can replace them with a verified value; otherwise the
    generated test uses a deterministic QA-safe fallback that remains overridable
    through the named environment variable.
    """
    target = ' '.join([
        str(step.get('target') or ''),
        str(step.get('description') or ''),
        str(step.get('expected') or ''),
    ]).lower()
    known = _scenario_non_sensitive_values(scenario)

    def first_value(*tokens: str) -> str:
        for label, value in known:
            if all(token in label for token in tokens):
                return value
        return ''

    if 'activity date' in target or 'today' in target:
        return 'todayDate()', 'uses today in MM/DD/YYYY format unless overridden'
    if 'future date' in target or 'appointment date' in target or re.search(r'\bdate\b', target):
        return 'futureDate(1)', 'uses tomorrow in MM/DD/YYYY format unless overridden'
    if 'time' in target:
        return json.dumps('10:00 AM'), 'uses 10:00 AM unless overridden'
    if 'product' in target:
        inferred = first_value('product', 'interest') or first_value('product') or 'Computer'
        return json.dumps(inferred, ensure_ascii=False), f'uses {inferred!r} from scenario context/default unless overridden'
    if 'appointment type' in target:
        return json.dumps('In Store'), "uses 'In Store' unless browser evidence or an override supplies the application-specific option"
    if 'notes' in target:
        return "uniqueRunValue('AstraHeal appointment note')", 'uses a unique non-sensitive note unless overridden'
    if 'status' in target:
        inferred = first_value('status') or 'Active'
        return json.dumps(inferred, ensure_ascii=False), f'uses {inferred!r} from scenario context/default unless overridden'
    if re.search(r'\btype\b', target):
        return json.dumps('General'), "uses 'General' unless overridden"
    return json.dumps('AstraHeal Test Data'), 'uses a visible generated QA value unless overridden'


def _sanitise_scenario_for_iteration_manifest(scenario: dict[str, Any]) -> dict[str, Any]:
    clone = json.loads(json.dumps(scenario, ensure_ascii=False, default=str))
    for step in clone.get('steps') or []:
        walkthrough = step.get('walkthrough') if isinstance(step.get('walkthrough'), dict) else {}
        test_data = walkthrough.get('test_data') if isinstance(walkthrough.get('test_data'), dict) else {}
        if bool(step.get('value_sensitive') or test_data.get('sensitive')):
            step['value'] = ''
            if test_data:
                test_data['value'] = ''
        # Codegen source snippets can contain entered values. The structured
        # locator/action evidence is sufficient for future iterations.
        if isinstance(walkthrough, dict):
            walkthrough.pop('source_code', None)
    return clone


def _merge_iteration_scenarios(root: Path, feature: str, scenarios: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], Path, dict[str, Any]]:
    manifest_path = root / '.aiqa-history' / 'add-new-tests' / f'{feature}-scenario-manifest.json'
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    previous: dict[str, dict[str, Any]] = {}
    if manifest_path.exists():
        try:
            existing = read_json(manifest_path)
            previous = {str(item.get('id') or ''): item for item in (existing.get('scenarios') or []) if str(item.get('id') or '')}
        except Exception:
            previous = {}
    current_ids: list[str] = []
    added: list[str] = []
    updated: list[str] = []
    for scenario in scenarios:
        sid = str(scenario.get('id') or scenario.get('title') or '').strip()
        if not sid:
            continue
        current_ids.append(sid)
        if sid in previous:
            updated.append(sid)
        else:
            added.append(sid)
        previous[sid] = _sanitise_scenario_for_iteration_manifest(scenario)
    merged = list(previous.values())
    payload = {
        'feature': feature,
        'updated_at': datetime.now().isoformat(timespec='seconds'),
        'scenario_count': len(merged),
        'current_iteration_scenario_ids': current_ids,
        'added_scenario_ids': added,
        'updated_scenario_ids': updated,
        'scenarios': merged,
    }
    write_json(manifest_path, payload)
    return merged, manifest_path, payload


def _write_feature_test_data(
    root: Path,
    profile: dict[str, Any],
    feature: str,
    scenarios: list[dict[str, Any]],
    *,
    runtime_environment: dict[str, str] | None = None,
    data_key_maps: dict[str, dict[int, dict[str, str]]] | None = None,
) -> dict[str, Any]:
    data_path, env_path = _feature_test_data_files(root, profile, feature)
    data_path.parent.mkdir(parents=True, exist_ok=True)
    runtime_path = data_path.parent / 'astraheal.runtime-env.ts'
    secret_path = root / '.env.astraheal.local'
    gitignore_path = _ensure_local_secret_gitignore(root)
    scenarios, iteration_manifest_path, iteration_manifest = _merge_iteration_scenarios(root, feature, scenarios)
    key_maps = {
        str(scenario.get('id') or 'SCENARIO'): _scenario_data_key_map(scenario)
        for scenario in scenarios
    }
    key_maps.update(data_key_maps or {})
    required_env_names: set[str] = set()
    optional_env_names: set[str] = set()
    optional_runtime_defaults: list[dict[str, Any]] = []
    scenario_lines: list[str] = []
    scenario_required_envs: dict[str, list[str]] = {}
    for scenario in scenarios:
        scenario_id = str(scenario.get('id') or 'SCENARIO')
        scenario_keys = key_maps.get(scenario_id) or {}
        properties: list[str] = []
        scenario_env_names: set[str] = set()
        for step_index, step in enumerate(scenario.get('steps') or [], 1):
            action = str(step.get('action') or '').lower()
            walkthrough_data = ((step.get('walkthrough') or {}).get('test_data') or {}) if isinstance(step.get('walkthrough'), dict) else {}
            value = str(step.get('value') or (walkthrough_data.get('value') if not walkthrough_data.get('sensitive') else '') or '').strip()
            env_name = re.sub(r'[^A-Z0-9_]+', '_', str(step.get('value_env') or walkthrough_data.get('environment_variable') or '').upper()).strip('_')
            sensitive = bool(step.get('value_sensitive') or walkthrough_data.get('sensitive'))
            url_match = re.search(r'https?://[^\s]+', str(step.get('target') or ''))
            keys = scenario_keys.get(step_index) or {}
            value_key = keys.get('value', '')
            if value_key:
                if env_name and sensitive:
                    required_env_names.add(env_name)
                    scenario_env_names.add(env_name)
                    properties.append(f'    get {value_key}() {{ return requiredSecret({json.dumps(env_name)}); }},')
                elif env_name:
                    optional_env_names.add(env_name)
                    fallback_expression, fallback_reason = _optional_runtime_fallback_expression(step, scenario)
                    properties.append(f'    get {value_key}() {{ return optionalRuntime({json.dumps(env_name)}, {fallback_expression}); }},')
                    optional_runtime_defaults.append({
                        'scenario_id': scenario_id,
                        'step_index': step_index,
                        'target': step.get('target'),
                        'environment_variable': env_name,
                        'fallback_expression': fallback_expression,
                        'reason': fallback_reason,
                    })
                elif value:
                    properties.append(f'    {json.dumps(value_key)}: {json.dumps(value, ensure_ascii=False)},')
                elif action in {'goto', 'open', 'launch', 'navigate'} and url_match:
                    properties.append(f'    {json.dumps(value_key)}: {json.dumps(url_match.group(0).rstrip(".,;"), ensure_ascii=False)},')
                else:
                    properties.append(f'    {json.dumps(value_key)}: {json.dumps("", ensure_ascii=False)},')
            expected_key = keys.get('expected', '')
            concrete_expected = _concrete_expected_value(step)
            if expected_key and concrete_expected:
                properties.append(f'    {json.dumps(expected_key)}: {json.dumps(concrete_expected, ensure_ascii=False)},')
        scenario_required_envs[scenario_id] = sorted(scenario_env_names)
        scenario_lines.extend([
            f'  {json.dumps(scenario_id)}: {{',
            *properties,
            '  },',
        ])
    export_name = _feature_data_export_name(feature)
    required_export_name = export_name + 'RequiredEnvironment'
    required_lines = [f'  {json.dumps(scenario_id)}: {json.dumps(names)},' for scenario_id, names in scenario_required_envs.items()]
    module = (
        "import { futureDate, optionalRuntime, requiredSecret, todayDate, uniqueRunValue } from './astraheal.runtime-env';\n\n"
        f"export const {required_export_name} = {{\n"
        + '\n'.join(required_lines)
        + "\n} as const;\n\n"
        + "export function assertRequiredEnvironment(names: readonly string[]): void {\n"
        + "  for (const name of names) requiredSecret(name);\n"
        + "}\n\n"
        + f"export const {export_name} = {{\n"
        + '\n'.join(scenario_lines)
        + "\n} as const;\n"
    )
    data_path.write_text(module, encoding='utf-8')
    runtime_path.write_text(_runtime_environment_loader_text(), encoding='utf-8')
    env_path.write_text(
        '# Required credentials. Supply through the CI secret manager or the Git-ignored .env.astraheal.local file.\n'
        + '\n'.join(f'{name}=' for name in sorted(required_env_names))
        + ('\n\n# Optional non-sensitive overrides. Runnable defaults are generated when these are empty.\n' if optional_env_names else '')
        + '\n'.join(f'{name}=' for name in sorted(optional_env_names))
        + ('\n' if required_env_names or optional_env_names else ''),
        encoding='utf-8',
    )
    merged_secrets = _read_env_file(secret_path)
    supplied = dict(runtime_environment or {})
    for name in required_env_names | optional_env_names:
        value = str(supplied.get(name) or '').strip()
        if value:
            merged_secrets[name] = value
    if merged_secrets:
        secret_path.write_text(
            '# AstraHeal local runtime credentials. This file is Git-ignored; do not commit or share it.\n'
            + '\n'.join(f'{name}={_env_file_value(value)}' for name, value in sorted(merged_secrets.items()))
            + '\n',
            encoding='utf-8',
        )
        try:
            os.chmod(secret_path, 0o600)
        except OSError:
            pass
    return {
        'data_path': data_path,
        'environment_example_path': env_path,
        'runtime_loader_path': runtime_path,
        'local_secret_path': secret_path,
        'gitignore_path': gitignore_path,
        'required_environment_variables': sorted(required_env_names),
        'optional_environment_variables': sorted(optional_env_names),
        'optional_runtime_defaults': optional_runtime_defaults,
        'written_environment_variables': sorted(name for name in (required_env_names | optional_env_names) if str(supplied.get(name) or '').strip()),
        'data_key_maps': key_maps,
        'export_name': export_name,
        'required_export_name': required_export_name,
        'scenario_required_environment': scenario_required_envs,
        'iteration_manifest_path': iteration_manifest_path,
        'iteration_manifest': iteration_manifest,
    }


def _ensure_expect_import(path: Path) -> None:
    text = path.read_text(encoding='utf-8', errors='replace') if path.exists() else ''
    if re.search(r"import\s+(?!type\b)[^;]*\bexpect\b[^;]*from\s+['\"]@playwright/test['\"]", text):
        return
    path.write_text("import { expect } from '@playwright/test';\n" + text, encoding='utf-8')


def _method_member(action: str, method: str, locator_ref: str, *, smart_locator_ref: str = '', description: str = 'target element') -> str:
    desc = _ts_single_quote(description or 'target element')
    if smart_locator_ref:
        if action in {'fill', 'type', 'enter'}:
            return f"  async {method}(value: string) {{\n    await {smart_locator_ref}.fill(value);\n  }}"
        if action == 'select':
            return f"  async {method}(value: string) {{\n    const target = await {smart_locator_ref}.firstReachable();\n    await target.selectOption({{ label: value }}).catch(async () => {{\n      await target.click();\n      await this.page.getByRole('option', {{ name: value, exact: true }}).click();\n    }});\n  }}"
        if action in {'verify', 'assert', 'expect', 'validate'}:
            return f"  async {method}(expectedText?: string) {{\n    const target = await {smart_locator_ref}.expectVisible();\n    if (expectedText) await expect(target, '{desc}').toContainText(expectedText);\n    else await expect(target, '{desc}').toBeVisible();\n  }}"
        return f"  async {method}() {{\n    await {smart_locator_ref}.click();\n  }}"
    if action in {'fill', 'type', 'enter'}:
        return f"  async {method}(value: string) {{\n    await {locator_ref}.waitFor({{ state: 'visible' }});\n    await {locator_ref}.fill(value);\n  }}"
    if action == 'select':
        return f"  async {method}(value: string) {{\n    const target = {locator_ref};\n    await target.waitFor({{ state: 'visible' }});\n    await target.selectOption({{ label: value }}).catch(async () => {{\n      await target.click();\n      await this.page.getByRole('option', {{ name: value, exact: true }}).click();\n    }});\n  }}"
    if action in {'verify', 'assert', 'expect', 'validate'}:
        return f"  async {method}(expectedText?: string) {{\n    await {locator_ref}.waitFor({{ state: 'visible' }});\n    if (expectedText) await expect({locator_ref}, '{desc}').toContainText(expectedText);\n    else await expect({locator_ref}, '{desc}').toBeVisible();\n  }}"
    return f"  async {method}() {{\n    await {locator_ref}.waitFor({{ state: 'visible' }});\n    await {locator_ref}.click();\n  }}"


def _generate_report(root: Path, plan: dict[str, Any]) -> tuple[Path, Path]:
    report_dir = root / '.aiqa-history' / 'add-new-tests'
    report_dir.mkdir(parents=True, exist_ok=True)
    json_path = report_dir / f"{plan['feature']}-generation-report.json"
    html_path = report_dir / f"{plan['feature']}-generation-report.html"
    write_json(json_path, plan)
    iteration_dir = report_dir / plan['feature'] / 'iterations'
    iteration_dir.mkdir(parents=True, exist_ok=True)
    iteration_json = iteration_dir / f"{plan.get('iteration_id') or datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    write_json(iteration_json, plan)
    rows = ''.join(
        f"<tr><td>{html.escape(str(x.get('scenario_id')))}</td><td>{html.escape(str(x.get('scenario_title')))}</td><td><code>{html.escape(str(x.get('spec_file')))}</code></td><td><code>{html.escape(str(x.get('page_file')))}</code></td><td><code>{html.escape(str(x.get('locator_file')))}</code></td><td><code>{html.escape(str(x.get('test_data_file')))}</code></td></tr>"
        for x in plan.get('scenario_outputs') or []
    )
    missing = list(plan.get('provisional_locator_risks') or (plan.get('validation') or {}).get('locator_risks') or [])
    blocker_rows = ''.join(
        f"<tr><td>{html.escape(str(x.get('scenario_id') or ''))}</td><td>{html.escape(str(x.get('step_index') or ''))}</td><td>{html.escape(str(x.get('target') or ''))}</td><td><code>{html.escape(str(x.get('required_locator') or ''))}</code></td></tr>"
        for x in missing
    )
    blocker_rows_html = blocker_rows or '<tr><td colspan="4">No provisional locator review items.</td></tr>'
    html_path.write_text(
        "<!doctype html><html><head><meta charset='utf-8'><title>Add New Tests Report</title>"
        "<style>body{font-family:Segoe UI,Arial;margin:24px;background:#f8fafc;color:#0f172a}.card{background:white;border:1px solid #dbe3ef;border-radius:12px;padding:16px;margin:14px 0}table{border-collapse:collapse;width:100%}td,th{border-bottom:1px solid #e2e8f0;padding:8px;text-align:left}code,pre{background:#0f172a;color:#dbeafe;padding:3px 6px;border-radius:6px;white-space:pre-wrap}</style></head><body>"
        f"<h1>Add New Tests Generation Report</h1><div class='card'><b>Framework:</b> <code>{html.escape(str(root))}</code><br/><b>Feature:</b> {html.escape(str(plan.get('feature')))}<br/><b>Scenarios:</b> {plan.get('scenario_count')}<br/><b>Files actually changed:</b> {len(plan.get('changed_files') or [])}</div>"
        f"<div class='card'><h2>Scenario-to-script mapping</h2><table><tr><th>Scenario</th><th>Title</th><th>Generated spec</th><th>Page methods</th><th>Locator repository</th><th>Test data</th></tr>{rows}</table></div>"
        f"<div class='card'><h2>Runtime data contract</h2><b>Data module:</b> <code>{html.escape(str(plan.get('test_data_file') or ''))}</code><br/><b>Access style:</b> {html.escape(str(plan.get('test_data_access_style') or ''))}<br/><b>Local credential file:</b> <code>{html.escape(str(plan.get('local_secret_file') or 'not created'))}</code><br/><b>Runtime loader:</b> <code>{html.escape(str(plan.get('runtime_environment_loader') or ''))}</code><br/><b>Missing required credentials:</b> <code>{html.escape(', '.join(plan.get('missing_runtime_values') or []) or 'none')}</code><br/><b>Optional data overrides:</b> <code>{html.escape(', '.join(plan.get('optional_environment_variables') or []) or 'none')}</code><pre>{html.escape(json.dumps(plan.get('optional_runtime_defaults') or [], indent=2, ensure_ascii=False))}</pre></div>"
        f"<div class='card'><h2>Generated locator review list (does not block generation)</h2><table><tr><th>Scenario</th><th>Step</th><th>Test instruction</th><th>Required locator</th></tr>{blocker_rows_html}</table></div>"
        f"<div class='card'><h2>Iterative generation state</h2><pre>{html.escape(json.dumps(plan.get('iteration_summary') or {}, indent=2, ensure_ascii=False))}</pre><p>Existing scenario IDs are updated in place. New scenario IDs create new specs. Earlier scenario data remains in the shared feature data module.</p></div>"
        f"<div class='card'><h2>Imported Playwright Codegen evidence</h2><pre>{html.escape(json.dumps(plan.get('codegen_capture') or {}, indent=2, ensure_ascii=False))}</pre></div>"
        f"<div class='card'><h2>AI browser grounding and MCP evidence</h2><pre>{html.escape(json.dumps(plan.get('browser_grounding') or {}, indent=2, ensure_ascii=False))}</pre></div>"
        f"<div class='card'><h2>Created and reused symbols</h2><pre>{html.escape(json.dumps({'created': plan.get('created_symbols'), 'reused': plan.get('reused_symbols')}, indent=2, ensure_ascii=False))}</pre></div>"
        f"<div class='card'><h2>Validation</h2><pre>{html.escape(json.dumps(plan.get('validation'), indent=2, ensure_ascii=False))}</pre></div></body></html>",
        encoding='utf-8',
    )
    iteration_html = iteration_dir / f"{plan.get('iteration_id') or datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
    shutil.copy2(html_path, iteration_html)
    return json_path, html_path


def _generation_block_result(
    root: Path,
    feature: str,
    *,
    stage: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    plan = {
        'ok': False,
        'feature': feature,
        'framework_path': str(root),
        'stage': stage,
        'message': message,
        'scenario_count': len({str(x.get('scenario_id') or '') for x in ((details or {}).get('missing_walkthrough_evidence') or []) if x.get('scenario_id')}),
        'changed_files': [],
        'created_symbols': [],
        'reused_symbols': [],
        'scenario_outputs': [],
        'validation': {'ok': False, 'stage': stage, **(details or {})},
        'generated_at': datetime.now(timezone.utc).isoformat(),
    }
    json_path, html_path = _generate_report(root, plan)
    return {
        'ok': False,
        'stage': stage,
        'message': message,
        'generation_report': str(json_path),
        'generation_report_html': str(html_path),
        **(details or {}),
    }


def _validate_typescript_syntax(root: Path, source_files: list[str]) -> dict[str, Any]:
    node = shutil.which('node')
    files = [rel for rel in source_files if Path(rel).suffix.lower() in {'.ts', '.tsx', '.js', '.jsx', '.mjs', '.cjs'} and (root / rel).exists()]
    if not node or not files:
        return {'ok': None, 'skipped': True, 'reason': 'Node.js or generated TypeScript/JavaScript source files are unavailable.'}
    script = r"""
const fs = require('fs');
let ts;
try { ts = require('typescript'); }
catch (error) { console.log(JSON.stringify({ skipped: true, reason: String(error) })); process.exit(0); }
const diagnostics = [];
for (const file of process.argv.slice(1)) {
  const text = fs.readFileSync(file, 'utf8');
  const kind = file.endsWith('.tsx') ? ts.ScriptKind.TSX : file.endsWith('.jsx') ? ts.ScriptKind.JSX : file.endsWith('.js') ? ts.ScriptKind.JS : ts.ScriptKind.TS;
  const source = ts.createSourceFile(file, text, ts.ScriptTarget.Latest, true, kind);
  for (const item of source.parseDiagnostics || []) {
    const pos = source.getLineAndCharacterOfPosition(item.start || 0);
    diagnostics.push({ file, line: pos.line + 1, column: pos.character + 1, code: item.code, message: ts.flattenDiagnosticMessageText(item.messageText, ' ') });
  }
}
console.log(JSON.stringify({ skipped: false, diagnostics }));
process.exit(diagnostics.length ? 2 : 0);
"""
    try:
        env = os.environ.copy()
        local_typescript = root / 'node_modules' / 'typescript'
        if not local_typescript.exists():
            npm = shutil.which('npm')
            if npm:
                npm_root = run_command([npm, 'root', '-g'], timeout=15)
                global_root = (npm_root.stdout or '').strip() if npm_root.returncode == 0 else ''
                if global_root:
                    existing_node_path = env.get('NODE_PATH', '').strip()
                    env['NODE_PATH'] = os.pathsep.join(x for x in (global_root, existing_node_path) if x)
        proc = run_command([node, '-e', script, *files], cwd=root, timeout=60, extra_env=env)
        raw = (proc.stdout or '').strip().splitlines()
        payload = json.loads(raw[-1]) if raw else {}
        if payload.get('skipped'):
            return {'ok': None, 'skipped': True, 'reason': payload.get('reason') or 'TypeScript package is unavailable.'}
        diagnostics = payload.get('diagnostics') or []
        return {
            'ok': not diagnostics,
            'skipped': False,
            'diagnostic_count': len(diagnostics),
            'diagnostics': diagnostics[:100],
            'files_checked': files,
        }
    except Exception as exc:
        return {'ok': None, 'skipped': True, 'reason': f'{type(exc).__name__}: {exc}'}


def _playwright_command(root: Path) -> list[str] | None:
    local = root / 'node_modules' / '.bin' / ('playwright.cmd' if os.name == 'nt' else 'playwright')
    if local.exists():
        return [str(local)]
    npx = shutil.which('npx')
    return [npx, '--no-install', 'playwright'] if npx else None



def _resolve_typescript_import(source_file: Path, import_path: str) -> Path | None:
    if not import_path.startswith('.'):
        return None
    base = (source_file.parent / import_path).resolve()
    candidates = [base, Path(str(base) + '.ts'), Path(str(base) + '.tsx'), base.with_suffix('.ts'), base.with_suffix('.tsx'), base / 'index.ts', base / 'index.tsx']
    return next((item for item in candidates if item.is_file()), None)


def _validate_generated_pom_contract(root: Path, specs: list[str]) -> dict[str, Any]:
    """Prove that spec calls, page methods and locator objects form one complete contract.

    Playwright transpilation does not always perform full TypeScript type checking.
    This additional gate catches the exact class of incomplete generation where a
    spec calls a method that was never created, or a page method references a
    locator repository property that does not exist.
    """
    issues: list[dict[str, Any]] = []
    checked_pages: set[Path] = set()
    checked_locator_files: set[Path] = set()
    for rel in specs:
        spec = (root / rel).resolve()
        if not spec.exists():
            issues.append({'file': rel, 'kind': 'missing_spec', 'message': 'Generated spec file does not exist.'})
            continue
        text = spec.read_text(encoding='utf-8', errors='replace')
        imports_found = re.findall(r"import\s*\{\s*([A-Za-z_$][\w$]*)\s*\}\s*from\s*['\"]([^'\"]+)['\"]", text)
        page_import = next(((name, path) for name, path in imports_found if path.startswith('.')), None)
        if not page_import:
            issues.append({'file': rel, 'kind': 'missing_page_import', 'message': 'Generated spec does not import a relative page-object class.'})
            continue
        page_class, import_path = page_import
        page_file = _resolve_typescript_import(spec, import_path)
        if not page_file:
            issues.append({'file': rel, 'kind': 'unresolved_page_import', 'message': f'Cannot resolve page-object import {import_path}.'})
            continue
        page_text = page_file.read_text(encoding='utf-8', errors='replace')
        if not re.search(rf'export\s+(?:default\s+)?class\s+{re.escape(page_class)}\b', page_text):
            issues.append({'file': _rel(page_file, root), 'kind': 'missing_page_class', 'message': f'Imported class {page_class} is not declared.'})
        for method in sorted(set(re.findall(r'\bscreen\.([A-Za-z_$][\w$]*)\s*\(', text))):
            if not re.search(rf'\b(?:async\s+)?{re.escape(method)}\s*\(', page_text):
                issues.append({'file': rel, 'kind': 'missing_page_method', 'symbol': method, 'page_file': _rel(page_file, root), 'message': f'Spec calls screen.{method}(), but the page method is missing.'})
        if page_file in checked_pages:
            continue
        checked_pages.add(page_file)
        imports = {
            alias: _resolve_typescript_import(page_file, path)
            for alias, path in re.findall(r"import\s*\{\s*([A-Za-z_$][\w$]*)\s*\}\s*from\s*['\"]([^'\"]+)['\"]", page_text)
        }
        for alias, locator in sorted(set(re.findall(r'\b([A-Za-z_$][\w$]*)\.([A-Za-z_$][\w$]*Locator)\b', page_text))):
            if alias in {'this', 'page'} or locator == 'getSmartLocator':
                continue
            locator_file = imports.get(alias)
            if locator_file is None:
                issues.append({'file': _rel(page_file, root), 'kind': 'unresolved_locator_import', 'symbol': f'{alias}.{locator}', 'message': f'Page method references {alias}.{locator}, but its import cannot be resolved.'})
                continue
            locator_text = locator_file.read_text(encoding='utf-8', errors='replace')
            if locator_file not in checked_locator_files:
                checked_locator_files.add(locator_file)
                for malformed in re.finditer(r"value\s*:\s*(['\"])\s*<([^<>]+)>\s*\1", locator_text):
                    issues.append({
                        'file': _rel(locator_file, root),
                        'kind': 'malformed_locator_value',
                        'value': malformed.group(2),
                        'message': 'Locator value contains documentation angle brackets. Use the actual accessible name without < and >.',
                    })
                for invalid in re.finditer(r"(?:role|value)\s*:\s*(['\"])(?:undefined|null|none)?\1", locator_text, re.I):
                    issues.append({
                        'file': _rel(locator_file, root),
                        'kind': 'invalid_locator_attribute',
                        'message': 'Locator role/name is empty or undefined. Regenerate it from live Playwright/MCP evidence or use a verified stable selector.',
                    })
                for role_object in re.finditer(r"strategy\s*:\s*['\"]role['\"][^}]{0,500}", locator_text, re.I | re.S):
                    fragment = role_object.group(0)
                    role_match = re.search(r"role\s*:\s*['\"]([^'\"]*)['\"]", fragment, re.I)
                    value_match = re.search(r"value\s*:\s*['\"]([^'\"]*)['\"]", fragment, re.I)
                    role_value = role_match.group(1).strip().lower() if role_match else ''
                    name_value = value_match.group(1).strip() if value_match else ''
                    if role_value not in _VALID_LOCATOR_ROLES or not name_value or name_value.lower() in {'undefined', 'null', 'none'}:
                        issues.append({
                            'file': _rel(locator_file, root),
                            'kind': 'invalid_role_locator',
                            'role': role_value,
                            'value': name_value,
                            'message': 'Role locator requires a valid ARIA role and a non-empty accessible name.',
                        })
            if not re.search(rf'\b{re.escape(locator)}\s*:', locator_text):
                issues.append({'file': _rel(page_file, root), 'kind': 'missing_locator_definition', 'symbol': f'{alias}.{locator}', 'locator_file': _rel(locator_file, root), 'message': f'Page method references {alias}.{locator}, but the locator is not defined.'})
    return {
        'ok': not issues,
        'checked_spec_count': len(specs),
        'checked_page_count': len(checked_pages),
        'issue_count': len(issues),
        'issues': issues,
        'plain_english_reason': ('Every generated spec call is backed by a page method and every generated page-method locator reference is backed by a locator definition.' if not issues else 'The generated spec/page/locator contract is incomplete.'),
    }


def _validate_specs(root: Path, specs: list[str], enabled: bool, source_files: list[str] | None = None, *, execute_generated: bool = False, execution_env: dict[str, str] | None = None, required_environment_variables: list[str] | None = None) -> dict[str, Any]:
    if not enabled:
        return {'ok': None, 'skipped': True, 'reason': 'Validation was disabled by the user.'}
    contract = _validate_generated_pom_contract(root, specs)
    if contract.get('ok') is False:
        return {
            'ok': False, 'skipped': False, 'stage': 'page_object_contract',
            'plain_english_reason': 'One or more generated specs, page methods, or locator definitions are incomplete. Playwright execution was not attempted, and rollback is required.',
            'page_object_contract': contract,
        }
    syntax = _validate_typescript_syntax(root, source_files or specs)
    if syntax.get('ok') is False:
        return {
            'ok': False,
            'skipped': False,
            'stage': 'typescript_syntax',
            'plain_english_reason': 'Generated TypeScript/JavaScript contains a syntax error. Playwright execution was not attempted, and rollback is required.',
            'syntax': syntax,
            'page_object_contract': contract,
        }
    command = _playwright_command(root)
    if not command or not (root / 'package.json').exists():
        return {
            'ok': None,
            'skipped': True,
            'reason': 'Local Playwright CLI or package.json is unavailable; static syntax validation completed but Playwright --list could not run.',
            'syntax': syntax,
            'page_object_contract': contract,
        }
    args = [*command, 'test', *specs, '--list']
    try:
        validation_env = os.environ.copy()
        validation_env.update({str(k): str(v) for k, v in dict(execution_env or {}).items() if str(k) and str(v)})
        # Structural discovery must not be confused with a live execution. The
        # generated specs now defer credential preflight to beforeAll, but this
        # environment also keeps older generated files compatible.
        validation_env['ASTRAHEAL_PLAYWRIGHT_DISCOVERY_ONLY'] = '1'
        proc = run_command(args, cwd=root, timeout=180, extra_env=validation_env)
        stderr = proc.stderr[-12000:]
        stdout = proc.stdout[-12000:]
        combined = (stdout + '\n' + stderr).strip()
        runtime_data_only = bool(re.search(
            r'Required (?:runtime credential|environment variable) is missing\s*:\s*[A-Z0-9_]+',
            combined,
            re.I,
        ))
        first_error = ''
        for line in combined.splitlines():
            stripped = line.strip()
            if re.search(r'\b(?:Error|TypeError|ReferenceError|SyntaxError)\b', stripped):
                first_error = stripped
                break
        result = {
            'ok': (proc.returncode == 0) if not runtime_data_only else None,
            'skipped': False,
            'stage': ('playwright_list_runtime_data_deferred' if runtime_data_only else 'playwright_list'),
            'command': ' '.join(args),
            'returncode': proc.returncode,
            'stdout': stdout,
            'stderr': stderr,
            'first_error': first_error,
            'syntax': syntax,
            'page_object_contract': contract,
            'plain_english_reason': (
                'Playwright successfully discovered every generated testcase.'
                if proc.returncode == 0 else
                'Playwright discovery reached a runtime-data preflight from an older/generated file. Source files are retained because this is not a TypeScript, page-method, locator, or import defect; supply the named runtime input before live execution.'
                if runtime_data_only else
                'Playwright could not load one or more generated specs or their dependent page/locator files. Review the first error and impacted file below; AstraHeal will roll back the attempted changes.'
            ),
        }
        if proc.returncode != 0 or not execute_generated:
            result['runtime_execution'] = {
                'ok': None,
                'skipped': True,
                'reason': (
                    'Runtime data is incomplete; structural files were retained and live execution was not attempted.'
                    if runtime_data_only else
                    'Static Playwright discovery failed.'
                    if proc.returncode != 0 else
                    'Post-generation execution was not requested.'
                ),
            }
            return result
        required = list(required_environment_variables or [])
        volatile = {str(k): str(v) for k, v in dict(execution_env or {}).items() if str(k) and str(v)}
        missing = [name for name in required if not volatile.get(name) and not os.getenv(name)]
        if missing:
            result['runtime_execution'] = {
                'ok': None, 'skipped': True,
                'reason': 'Generated tests were loaded successfully, but live execution was skipped because required environment variables are unavailable.',
                'missing_environment_variables': missing,
            }
            return result
        run_args = [*command, 'test', *specs, '--workers=1']
        run_env = os.environ.copy(); run_env.update(volatile)
        runtime = run_command(run_args, cwd=root, timeout=1200, extra_env=run_env)
        def redact_runtime_output(value: str) -> str:
            cleaned = str(value or '')
            for secret in sorted(set(volatile.values()), key=len, reverse=True):
                if secret:
                    cleaned = cleaned.replace(secret, '[REDACTED]')
            return cleaned[-20000:]
        result['runtime_execution'] = {
            'ok': runtime.returncode == 0,
            'skipped': False,
            'command': ' '.join(run_args),
            'returncode': runtime.returncode,
            'stdout': redact_runtime_output(runtime.stdout),
            'stderr': redact_runtime_output(runtime.stderr),
            'plain_english_reason': ('Every newly generated Playwright testcase executed successfully.' if runtime.returncode == 0 else 'The generated files loaded successfully, but one or more live browser tests failed. Files are retained so RCA/self-healing can inspect the exact failure.'),
        }
        return result
    except Exception as exc:
        return {'ok': False, 'skipped': False, 'error': f'{type(exc).__name__}: {exc}'}


def generate_existing_framework_tests(
    framework_path: str,
    feature: str,
    provider: str = 'deterministic',
    model: str = 'llama3',
    base_url: str = '',
    target_test_folder: str = '',
    target_page_file: str = '',
    target_locator_file: str = '',
    placement_mode: str = 'confirm_if_ambiguous',
    allow_new_support_files: bool = True,
    validate_generated: bool = True,
    bdd_output_mode: str = 'playwright_specs',
    use_walkthrough_evidence: bool = False,
    require_walkthrough_evidence: bool = False,
    execute_generated_after_creation: bool = False,
    runtime_environment: dict[str, str] | None = None,
    browser_grounding_result: dict[str, Any] | None = None,
    use_codegen_capture: bool = True,
) -> dict[str, Any]:
    root = Path(framework_path).expanduser().resolve()
    if not root.exists():
        return {'ok': False, 'error': f'Framework path does not exist: {root}'}
    feature = _safe_feature(feature)
    testcase_path = feature_testcase_path('module2_uploaded', feature)
    if not testcase_path.exists():
        return {'ok': False, 'error': 'Load/normalize testcase source first.'}
    original_payload = read_json(testcase_path)
    walkthrough_report = load_walkthrough_evidence(feature) if use_walkthrough_evidence else {}
    enhanced_path = walkthrough_enhanced_testcase_path(feature)
    walkthrough_available = bool(use_walkthrough_evidence and enhanced_path.exists())
    walkthrough_ready = bool(walkthrough_report.get('ready_for_generation') and walkthrough_available)
    # Browser grounding is integrated into generation. Every verified locator and
    # verified AI-discovered prerequisite action is merged into the ordered
    # scenario. Partial browser evidence enriches generation but never blocks it.
    payload = load_grounded_payload(feature, original_payload) if walkthrough_available else original_payload
    codegen_capture = latest_codegen_capture(str(root), feature) if use_codegen_capture else {}
    if use_codegen_capture and codegen_capture.get('ok'):
        payload = load_codegen_enhanced_payload(str(root), feature, payload)
    scenarios = payload.get('scenarios') or []
    if not scenarios:
        return {'ok': False, 'error': 'No normalized scenarios are available.'}
    log_event('module2_existing_framework', f'Preparing {len(scenarios)} new Playwright specs in the selected framework', progress=5, feature=feature)
    profile = build_structure_profile(root, limit=7000)
    try:
        deep = build_deep_framework_understanding(root, base_url=base_url)
    except Exception as exc:
        deep = {'ok': False, 'warning': f'{type(exc).__name__}: {exc}'}
    try:
        from qa_pipeline.mcp.playwright_mcp import mcp_status
        mcp_readiness = mcp_status(headless=False, probe_server=False)
    except Exception as exc:
        mcp_readiness = {'mcp_probe_ok': False, 'error': f'{type(exc).__name__}: {exc}'}
    preview = preview_generation_placement(str(root), feature, target_test_folder, target_page_file, target_locator_file, placement_mode)
    if not preview.get('ok'):
        return preview
    if placement_mode == 'confirm_if_ambiguous' and not target_page_file:
        ambiguous = preview.get('ambiguous_scenarios') or []
        unresolved = preview.get('unresolved_scenarios') or []
        if ambiguous or (unresolved and not allow_new_support_files):
            return {
                'ok': False,
                'needs_user_input': True,
                'placement_preview': preview,
                'message': 'Generation stopped safely before changing files because page/locator placement is ambiguous or support-file creation was not permitted. Select the target page/locator file, allow required support-file creation, or choose automatic placement explicitly.',
            }
    for item in preview.get('placements') or []:
        page_rel = item.get('recommended_page_file') or ''
        locator_rel = item.get('recommended_locator_file') or ''
        if page_rel and locator_rel and page_rel != locator_rel:
            page_candidate = root / page_rel
            locator_candidate = root / locator_rel
            if _locator_binding(page_candidate, locator_candidate) is None:
                return {
                    'ok': False,
                    'needs_user_input': True,
                    'placement_preview': preview,
                    'message': f"The selected locator file {locator_rel} is not visibly linked to {page_rel}. Select the same page file for locators, or choose an existing locator repository already imported and instantiated by that page class. No files were changed.",
                }
    provisional_locator_risks: list[dict[str, Any]] = []
    for scenario in scenarios:
        placement = next((p for p in (preview.get('placements') or []) if p.get('scenario_id') == scenario.get('id')), {})
        locator_rel = placement.get('recommended_locator_file') or placement.get('recommended_page_file') or ''
        locator_file = root / locator_rel if locator_rel else None
        locator_text = locator_file.read_text(encoding='utf-8', errors='replace') if locator_file and locator_file.exists() else ''
        for step_index, step in enumerate(scenario.get('steps') or [], 1):
            action = str(step.get('action') or 'perform').lower()
            if action in {'goto', 'open', 'launch', 'navigate', 'wait'}:
                continue
            locator_name = _locator_name(str(step.get('target') or 'element'))
            if locator_text and re.search(rf'\b{re.escape(locator_name)}\b', locator_text):
                continue
            if not _walkthrough_locator(step):
                provisional_locator_risks.append({
                    'scenario_id': scenario.get('id'),
                    'step_index': step_index,
                    'target': step.get('target'),
                    'required_locator': locator_name,
                    'severity': 'review',
                    'generation_blocked': False,
                    'message': 'A reusable locator was not found. AstraHeal will create a SmartLocator candidate bundle and continue generation.',
                })
    # Backward-compatible input: the old strict checkbox is intentionally ignored.
    # Missing walkthrough evidence is now reported as locator risk, never as a
    # code-generation blocker.
    strict_walkthrough_requested_but_ignored = bool(require_walkthrough_evidence)

    test_dir = root / preview['recommended_test_folder']
    test_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_root = root / '.aiqa-history' / 'backups' / 'add-new-tests' / timestamp
    changed_files: list[str] = []
    created_paths: set[str] = set()
    created_symbols: list[dict[str, Any]] = []
    reused_symbols: list[dict[str, Any]] = []
    scenario_outputs: list[dict[str, Any]] = []
    placement_by_id = {p['scenario_id']: p for p in preview.get('placements') or []}
    test_data_path, env_example_path = _feature_test_data_files(root, profile, feature)
    data_key_maps = {
        str(scenario.get('id') or 'SCENARIO'): _scenario_data_key_map(scenario)
        for scenario in scenarios
    }
    runtime_loader_path = test_data_path.parent / 'astraheal.runtime-env.ts'
    local_secret_path = root / '.env.astraheal.local'
    gitignore_path = root / '.gitignore'
    for support_path in (test_data_path, env_example_path, runtime_loader_path, local_secret_path, gitignore_path):
        _backup_file(root, support_path, backup_root)
        if not support_path.exists():
            created_paths.add(_rel(support_path, root))
    data_bundle = _write_feature_test_data(
        root, profile, feature, scenarios,
        runtime_environment=runtime_environment,
        data_key_maps=data_key_maps,
    )
    required_environment_variables = list(data_bundle.get('required_environment_variables') or [])
    data_export_name = str(data_bundle.get('export_name') or _feature_data_export_name(feature))
    required_data_export_name = str(data_bundle.get('required_export_name') or (data_export_name + 'RequiredEnvironment'))
    for key in ('data_path', 'environment_example_path', 'runtime_loader_path', 'gitignore_path'):
        support_path = data_bundle.get(key)
        if isinstance(support_path, Path) and support_path.exists():
            changed_files.append(_rel(support_path, root))
    if local_secret_path.exists():
        changed_files.append(_rel(local_secret_path, root))

    for index, scenario in enumerate(scenarios, 1):
        placement = placement_by_id.get(scenario.get('id')) or {}
        page_rel = placement.get('recommended_page_file')
        page_path = root / page_rel if page_rel else None
        auto_locator_path: Path | None = None
        if page_path is None or not page_path.exists():
            if not allow_new_support_files:
                return {'ok': False, 'needs_user_input': True, 'placement_preview': preview, 'message': f"No reusable page file exists for {scenario.get('id')}. Select a page file or allow creation of a support file only when required."}
            class_name = pascal_case(str(scenario.get('page') or feature)) or 'GeneratedPage'
            if not class_name.endswith('Page'):
                class_name += 'Page'
            page_path, auto_locator_path, created_support = _create_framework_support_files(root, profile, class_name)
            for created_path in created_support:
                created_paths.add(_rel(created_path, root))
                changed_files.append(_rel(created_path, root))
                created_symbols.append({'file': _rel(created_path, root), 'kind': 'support_file', 'name': created_path.stem, 'reason': 'No semantically matching concrete page file existed; one reusable application page/locator pair was created and shared by all related testcases.'})
        class_name = _class_name(page_path, pascal_case(page_path.stem))
        locator_rel = placement.get('recommended_locator_file') or (_rel(auto_locator_path, root) if auto_locator_path else _rel(page_path, root))
        locator_path = root / locator_rel
        binding = _locator_binding(page_path, locator_path)
        if binding is None:
            return {'ok': False, 'needs_user_input': True, 'placement_preview': preview, 'message': f'Locator file {locator_rel} is not linked to page file {_rel(page_path, root)}. No further files were changed.'}
        _backup_file(root, page_path, backup_root)
        if locator_path.resolve() != page_path.resolve():
            _backup_file(root, locator_path, backup_root)
        text = page_path.read_text(encoding='utf-8', errors='replace')
        locator_text = locator_path.read_text(encoding='utf-8', errors='replace')
        calls: list[dict[str, Any]] = []
        for step_index, step in enumerate(scenario.get('steps') or [], 1):
            action = str(step.get('action') or 'perform').lower()
            target = str(step.get('target') or 'element')
            if action in {'goto', 'open', 'launch', 'navigate'}:
                method = 'gotoApplication'
                if re.search(r'\bgotoApplication\s*\(', text):
                    reused_symbols.append({'file': _rel(page_path, root), 'kind': 'method', 'name': method, 'scenario_id': scenario.get('id')})
                else:
                    member = ("  async gotoApplication(url: string) {\n    await this.goto(url);\n    await this.verifyPageLoadedSuccessfully();\n  }" if re.search(r'extends\s+BasePage\b', text) else "  async gotoApplication(url: string) {\n    await this.page.goto(url, { waitUntil: 'domcontentloaded' });\n    await this.page.locator('body').waitFor({ state: 'visible' });\n  }")
                    if _append_member(page_path, member, method):
                        text += '\n' + member
                        changed_files.append(_rel(page_path, root))
                        created_symbols.append({'file': _rel(page_path, root), 'kind': 'method', 'name': method, 'scenario_id': scenario.get('id')})
                calls.append({'step_index': step_index, 'label': str(step.get('description') or step.get('target') or f'Step {step_index}'), 'call': _step_call(step, method, data_reference='data', data_keys=(data_key_maps.get(str(scenario.get('id') or 'SCENARIO')) or {}).get(step_index, {})), 'browser_grounded': bool(_walkthrough_locator(step)), 'generated_prerequisite': bool(step.get('generated_by_walkthrough'))})
                continue
            walkthrough_locator = _walkthrough_locator(step)
            exact_existing_locator = _find_existing_locator_name(locator_text, walkthrough_locator) if walkthrough_locator else ''
            locator = exact_existing_locator or _locator_name(target)
            method = _method_name(action, target)
            if re.search(rf'\b{re.escape(locator)}\b', locator_text):
                reused_symbols.append({'file': _rel(locator_path, root), 'kind': 'locator', 'name': locator, 'scenario_id': scenario.get('id'), 'evidence': 'exact Codegen/live locator match' if exact_existing_locator else 'existing locator name'})
            else:
                if _append_locator(locator_path, locator, target, action, binding, walkthrough_locator=walkthrough_locator):
                    locator_text = locator_path.read_text(encoding='utf-8', errors='replace')
                    changed_files.append(_rel(locator_path, root))
                    evidence_source = str(((step.get('walkthrough') or {}).get('source') or ''))
                    created_symbols.append({'file': _rel(locator_path, root), 'kind': 'locator', 'name': locator, 'scenario_id': scenario.get('id'), 'evidence': ('verified locator from Playwright Codegen' if evidence_source == 'playwright_codegen' else ('verified live browser locator from AI functional walkthrough' if walkthrough_locator else 'provisional semantic locator; verify with Playwright MCP/codegen/live DOM before production use'))})
            exact_existing_method = _find_existing_method_for_locator(text, locator, action)
            if exact_existing_method:
                method = exact_existing_method
                reused_symbols.append({'file': _rel(page_path, root), 'kind': 'method', 'name': method, 'scenario_id': scenario.get('id'), 'evidence': f'existing method already uses locator {locator}'})
            elif re.search(rf'\b{re.escape(method)}\s*\(', text):
                reused_symbols.append({'file': _rel(page_path, root), 'kind': 'method', 'name': method, 'scenario_id': scenario.get('id')})
            else:
                locator_expression = str(binding.get('locator_expression') or 'this.{locator}').format(locator=locator)
                smart_locator_expression = str(binding.get('smart_locator_expression') or '').format(locator=locator)
                if action in {'verify', 'assert', 'expect', 'validate'}:
                    _ensure_expect_import(page_path)
                    text = page_path.read_text(encoding='utf-8', errors='replace')
                member = _method_member(action, method, locator_expression, smart_locator_ref=smart_locator_expression, description=target)
                if _append_member(page_path, member, method):
                    text += '\n' + member
                    changed_files.append(_rel(page_path, root))
                    created_symbols.append({'file': _rel(page_path, root), 'kind': 'method', 'name': method, 'scenario_id': scenario.get('id')})
            calls.append({'step_index': step_index, 'label': str(step.get('description') or step.get('target') or f'Step {step_index}'), 'call': _step_call(step, method, data_reference='data', data_keys=(data_key_maps.get(str(scenario.get('id') or 'SCENARIO')) or {}).get(step_index, {})), 'browser_grounded': bool(_walkthrough_locator(step)), 'generated_prerequisite': bool(step.get('generated_by_walkthrough'))})
        spec_path = _unique_spec_path(test_dir, feature, scenario, index)
        spec_path.parent.mkdir(parents=True, exist_ok=True)
        spec_existed = spec_path.exists()
        if spec_existed:
            _backup_file(root, spec_path, backup_root)
        else:
            created_paths.add(_rel(spec_path, root))
        import_path = _relative_import(spec_path, page_path)
        title = str(scenario.get('title') or scenario.get('id') or f'{feature} {index}')
        source_id = str(scenario.get('id') or '')
        data_import_path = _relative_import(spec_path, test_data_path)
        lines = [
            "import { test } from '@playwright/test';",
            f"import {{ {class_name} }} from '{import_path}';",
            f"import {{ {data_export_name}, {required_data_export_name}, assertRequiredEnvironment }} from '{data_import_path}';",
            '',
            f"test.describe({json.dumps(feature + ' - generated from approved testcase source')}, () => {{",
            "  test.beforeAll(() => {",
            f"    assertRequiredEnvironment({required_data_export_name}[{json.dumps(source_id)}]);",
            "  });",
            '',
            f"  test({json.dumps(source_id + ' - ' + title)}, async ({{ page }}) => {{",
            f"    const data = {data_export_name}[{json.dumps(source_id)}];",
            f"    const screen = new {class_name}(page);",
        ]
        for call_item in calls:
            step_title = f"Step {call_item['step_index']}: {call_item['label']}"
            if call_item.get('generated_prerequisite'):
                step_title += ' [AI-discovered prerequisite]'
            if call_item.get('browser_grounded'):
                step_title += ' [browser verified]'
            lines.extend([
                f"    await test.step({json.dumps(step_title)}, async () => {{",
                f"      {call_item['call']}",
                "    });",
            ])
        lines.extend(['  });', '});', ''])
        spec_path.write_text('\n'.join(lines), encoding='utf-8')
        changed_files.append(_rel(spec_path, root))
        scenario_outputs.append({
            'scenario_id': scenario.get('id'),
            'scenario_title': title,
            'spec_file': _rel(spec_path, root),
            'page_file': _rel(page_path, root),
            'locator_file': _rel(locator_path, root),
            'test_data_file': _rel(test_data_path, root),
        'iteration_manifest_file': _rel(Path(data_bundle.get('iteration_manifest_path')), root) if data_bundle.get('iteration_manifest_path') else '',
        'iteration_summary': data_bundle.get('iteration_manifest') or {},
            'environment_example_file': _rel(env_example_path, root),
            'runtime_environment_loader': _rel(runtime_loader_path, root),
            'local_secret_file': _rel(local_secret_path, root) if local_secret_path.exists() else '',
            'bdd_source': bool(scenario.get('gherkin_source')),
            'spec_update_mode': 'updated_existing' if spec_existed else 'created_new',
        })

    changed_files = sorted(dict.fromkeys(changed_files))
    specs = [x['spec_file'] for x in scenario_outputs]
    validation = _validate_specs(root, specs, validate_generated, changed_files, execute_generated=execute_generated_after_creation, execution_env=runtime_environment, required_environment_variables=required_environment_variables)
    validation_failure_summary = str(
        validation.get('first_error')
        or validation.get('plain_english_reason')
        or validation.get('error')
        or ''
    ).strip()
    attempted_changed_files = list(changed_files)
    attempted_specs = list(specs)
    rollback = {'performed': False, 'restored_files': [], 'deleted_created_files': [], 'reason': ''}
    if validation.get('ok') is False:
        rollback = _rollback_generation(root, backup_root, created_paths)
        changed_files = []
        specs = []
    runtime_execution = validation.get('runtime_execution') or {}
    plan = {
        'ok': validation.get('ok') is not False,
        'structural_validation_ok': validation.get('ok') is not False,
        'runtime_execution_ok': runtime_execution.get('ok'),
        'generated_at': datetime.now().isoformat(timespec='seconds'),
        'iteration_id': timestamp,
        'feature': feature,
        'framework_path': str(root),
        'testcase_file': str(testcase_path.relative_to(REPO_ROOT)),
        'browser_grounding': dict(browser_grounding_result or {}),
        'codegen_capture': codegen_capture if use_codegen_capture else {},
        'codegen_capture_used': bool(use_codegen_capture and codegen_capture.get('ok')),
        'walkthrough_evidence_used': bool(walkthrough_available),
        'walkthrough_evidence_optional': True,
        'strict_walkthrough_requested_but_ignored': strict_walkthrough_requested_but_ignored,
        'provisional_locator_risks': provisional_locator_risks,
        'provisional_locator_count': len(provisional_locator_risks),
        'walkthrough_report': str((walkthrough_report_path := (QA_CACHE_DIR / 'functional_walkthrough' / feature / 'latest.json')).relative_to(REPO_ROOT)) if walkthrough_ready else '',
        'scenario_count': len(scenarios),
        'test_data_file': _rel(test_data_path, root),
        'environment_example_file': _rel(env_example_path, root),
        'runtime_environment_loader': _rel(runtime_loader_path, root),
        'local_secret_file': _rel(local_secret_path, root) if local_secret_path.exists() else '',
        'runtime_values_written': list(data_bundle.get('written_environment_variables') or []),
        'missing_runtime_values': sorted(set(required_environment_variables) - set(data_bundle.get('written_environment_variables') or [])),
        'optional_environment_variables': list(data_bundle.get('optional_environment_variables') or []),
        'optional_runtime_defaults': list(data_bundle.get('optional_runtime_defaults') or []),
        'test_data_access_style': 'named scenario data object; no stepValue indirection',
        'required_environment_variables': required_environment_variables,
        'generated_spec_count': len(specs),
        'attempted_spec_count': len(attempted_specs),
        'scenario_outputs': scenario_outputs,
        'changed_files': changed_files,
        'attempted_changed_files': attempted_changed_files,
        'rollback': rollback,
        'created_symbols': created_symbols,
        'reused_symbols': reused_symbols,
        'placement_preview': preview,
        'deep_framework_understanding_used': bool(deep.get('ok')),
        'provider_requested': provider,
        'model_requested': model,
        'bdd_output_mode': bdd_output_mode,
        'mcp_readiness': mcp_readiness,
        'mcp_codegen_policy': {
            'reuse_first': True,
            'live_locator_evidence': ('Imported Playwright Codegen evidence is authoritative for recorded steps; browser-grounding evidence is used next; existing framework locators are reused before creating new locators.' if codegen_capture.get('ok') else ('Optional verified locator evidence was reused where available.' if walkthrough_available else 'No walkthrough is required. Existing locators are reused first; missing locators are generated as SmartLocator candidate bundles and listed for optional post-generation MCP/codegen refinement.')),
            'codegen_command': f"npx --no-install playwright codegen {base_url}" if base_url else 'Set Application/base URL, then run npx --no-install playwright codegen <URL> from the selected framework.',
            'no_hidden_browser_interaction': True,
        },
        'backup_root': str(backup_root),
        'validation': validation,
        'policy': 'One normalized testcase/scenario produces one Playwright spec. Existing page files and methods are reused first; new support files are created only when no suitable file exists and the user permits it.',
    }
    json_report, html_report = _generate_report(root, plan)
    history = root / '.aiqa-history' / 'new-test-generation.jsonl'
    history.parent.mkdir(parents=True, exist_ok=True)
    with history.open('a', encoding='utf-8') as handle:
        handle.write(json.dumps(plan, ensure_ascii=False) + '\n')
    event_message = (f'Generated and executed {len(specs)} Playwright spec(s) successfully' if runtime_execution.get('ok') is True else (f'Generated {len(specs)} Playwright spec(s) for {len(scenarios)} testcase(s)' if validation.get('ok') is not False else f'Validation failed; rolled back {len(attempted_specs)} attempted Playwright spec(s) and restored the framework'))
    log_event('module2_existing_framework', event_message, status='done' if plan['ok'] else 'warning', progress=100, feature=feature, details={'changed_files': changed_files, 'attempted_changed_files': attempted_changed_files, 'validation': validation, 'rollback': rollback})
    return {
        'ok': plan['ok'],
        'generated_spec_count': len(specs),
        'attempted_spec_count': len(attempted_specs),
        'scenario_count': len(scenarios),
        'generated_specs': specs,
        'attempted_generated_specs': attempted_specs,
        'changed_files': changed_files,
        'attempted_changed_files': attempted_changed_files,
        'rollback': rollback,
        'created_symbols': created_symbols,
        'reused_symbols': reused_symbols,
        'scenario_outputs': scenario_outputs,
        'test_data_file': _rel(test_data_path, root),
        'iteration_manifest_file': _rel(Path(data_bundle.get('iteration_manifest_path')), root) if data_bundle.get('iteration_manifest_path') else '',
        'iteration_summary': data_bundle.get('iteration_manifest') or {},
        'environment_example_file': _rel(env_example_path, root),
        'runtime_environment_loader': _rel(runtime_loader_path, root),
        'local_secret_file': _rel(local_secret_path, root) if local_secret_path.exists() else '',
        'runtime_values_written': list(data_bundle.get('written_environment_variables') or []),
        'missing_runtime_values': sorted(set(required_environment_variables) - set(data_bundle.get('written_environment_variables') or [])),
        'optional_environment_variables': list(data_bundle.get('optional_environment_variables') or []),
        'optional_runtime_defaults': list(data_bundle.get('optional_runtime_defaults') or []),
        'test_data_access_style': 'named scenario data object; no stepValue indirection',
        'required_environment_variables': required_environment_variables,
        'provisional_locator_count': len(provisional_locator_risks),
        'provisional_locator_risks': provisional_locator_risks,
        'browser_grounding': dict(browser_grounding_result or {}),
        'codegen_capture': codegen_capture if use_codegen_capture else {},
        'codegen_capture_used': bool(use_codegen_capture and codegen_capture.get('ok')),
        'validation': validation,
        'generation_report': str(json_report),
        'generation_report_html': str(html_report),
        'extension_plan': plan,
        'next_actions': [
            'Run the newly generated/updated specs sequentially.',
            'If a test fails, click Explain failed tests to generate the stable Plain-English RCA report.',
            'Review the RCA, create a safe fix plan, approve only the recommended files, then rerun failed tests only.',
        ],
        'plain_english_rca_report_url': '/api/existing-framework/rca/plain-english/report',
        'message': (
            f"Generated and successfully executed {len(specs)} Playwright spec file(s) from {len(scenarios)} testcase(s)."
            if runtime_execution.get('ok') is True else
            (f"Generated {len(specs)} Playwright spec file(s), but live execution found a failure. Generated files were retained for evidence-grounded RCA and self-healing; review the runtime section of the generation report."
             if validation.get('ok') is not False and runtime_execution.get('ok') is False else
             (f"Generated {len(specs)} complete Playwright spec file(s) from {len(scenarios)} testcase(s) with named test data, page methods, locator definitions and a Git-ignored local runtime credential file. Exact changed files and reuse decisions are listed in the generation report."
              if validation.get('ok') is not False else
              f"Playwright validation failed for {len(attempted_specs)} attempted spec file(s). AstraHeal automatically rolled back all generated source/spec changes. First diagnostic: {validation_failure_summary or 'See the validation section of the generation report.'}"))
        ),
    }
