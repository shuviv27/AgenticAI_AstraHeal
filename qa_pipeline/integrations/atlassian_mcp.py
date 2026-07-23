from __future__ import annotations

import html
import json
import os
import re
import shutil
import subprocess
import threading
import queue
import time
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import requests

from qa_pipeline.core.paths import QA_CACHE_DIR
from qa_pipeline.integrations.jira_client import JiraClient, JiraCredentials, epic_to_source_text, issue_to_testcase_text


class _VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._ignored = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in {'script', 'style'}:
            self._ignored += 1
        elif tag.lower() in {'p', 'div', 'br', 'li', 'tr', 'h1', 'h2', 'h3', 'h4'}:
            self.parts.append('\n')

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {'script', 'style'} and self._ignored:
            self._ignored -= 1
        elif tag.lower() in {'p', 'div', 'li', 'tr', 'h1', 'h2', 'h3', 'h4'}:
            self.parts.append('\n')

    def handle_data(self, data: str) -> None:
        if not self._ignored and data.strip():
            self.parts.append(data.strip() + ' ')

    def text(self) -> str:
        value = html.unescape(''.join(self.parts))
        return re.sub(r'\n\s*\n+', '\n\n', value).strip()


def _clean_url(value: str) -> str:
    value = (value or '').strip().rstrip('/')
    if value and not value.startswith(('http://', 'https://')):
        value = 'https://' + value
    return value


def _extract_page_id(value: str) -> str:
    raw = (value or '').strip()
    if raw.isdigit():
        return raw
    parsed = urlparse(raw)
    query = parse_qs(parsed.query)
    if query.get('pageId'):
        return query['pageId'][0]
    for pattern in (r'/pages/(\d+)', r'/viewpage\.action.*pageId=(\d+)'):
        match = re.search(pattern, raw)
        if match:
            return match.group(1)
    return raw


@dataclass
class AtlassianCredentials:
    jira_url: str = ''
    confluence_url: str = ''
    username: str = ''
    api_token: str = ''
    password: str = ''

    @classmethod
    def from_values(cls, jira_url: str = '', confluence_url: str = '', username: str = '', api_token: str = '', password: str = '') -> 'AtlassianCredentials':
        return cls(
            jira_url=_clean_url(jira_url or os.getenv('JIRA_URL') or os.getenv('JIRA_BASE_URL') or ''),
            confluence_url=_clean_url(confluence_url or os.getenv('CONFLUENCE_URL') or ''),
            username=(username or os.getenv('JIRA_USERNAME') or os.getenv('JIRA_EMAIL') or '').strip(),
            api_token=(api_token or os.getenv('JIRA_API_TOKEN') or '').strip(),
            password=(password or '').strip(),
        )

    @property
    def secret(self) -> str:
        return self.api_token or self.password

    def safe_summary(self) -> dict[str, Any]:
        return {
            'jira_url': self.jira_url,
            'confluence_url': self.confluence_url,
            'username_present': bool(self.username),
            'api_token_present': bool(self.api_token),
            'password_present': bool(self.password),
            'credential_policy': 'API token is preferred. Password is used only as an in-memory fallback for compatible Jira/Confluence Data Center installations. Secrets are never written to project files or reports.',
        }


def prepare_atlassian_mcp_config() -> dict[str, Any]:
    target = QA_CACHE_DIR / 'atlassian-mcp' / 'mcp-atlassian.json'
    target.parent.mkdir(parents=True, exist_ok=True)
    config = {
        'mcpServers': {
            'atlassian': {
                'command': 'uvx',
                'args': ['mcp-atlassian'],
                'env': {
                    'JIRA_URL': '${JIRA_URL}',
                    'JIRA_USERNAME': '${JIRA_USERNAME}',
                    'JIRA_API_TOKEN': '${JIRA_API_TOKEN}',
                    'CONFLUENCE_URL': '${CONFLUENCE_URL}',
                    'CONFLUENCE_USERNAME': '${JIRA_USERNAME}',
                    'CONFLUENCE_API_TOKEN': '${JIRA_API_TOKEN}',
                    'JIRA_PERSONAL_TOKEN': '${JIRA_PERSONAL_TOKEN}',
                    'CONFLUENCE_PERSONAL_TOKEN': '${CONFLUENCE_PERSONAL_TOKEN}',
                },
            }
        }
    }
    target.write_text(json.dumps(config, indent=2) + '\n', encoding='utf-8')
    return {
        'config_file': str(target),
        'uvx_available': bool(shutil.which('uvx')),
        'docker_available': bool(shutil.which('docker')),
        'contains_secrets': False,
        'message': 'Atlassian MCP configuration was prepared for the official uvx mcp-atlassian launch pattern with environment-variable placeholders only. No username, password, API token, or personal token was stored.',
    }




class AtlassianMcpError(RuntimeError):
    pass


class _AtlassianMcpStdioClient:
    """Small read-only MCP client used only for source intake.

    It discovers the server tool schemas at runtime instead of assuming argument
    names. Credentials are supplied through the child-process environment, never
    command-line arguments or generated JSON.
    """

    def __init__(self, creds: AtlassianCredentials, timeout_seconds: int = 45):
        uvx = shutil.which('uvx')
        if not uvx:
            raise AtlassianMcpError('uvx is not available, so the local mcp-atlassian stdio server cannot be launched.')
        self.command = [uvx, 'mcp-atlassian']
        self.timeout_seconds = max(10, min(int(timeout_seconds or 45), 180))
        self.env = os.environ.copy()
        if creds.jira_url:
            self.env['JIRA_URL'] = creds.jira_url
        if creds.confluence_url:
            self.env['CONFLUENCE_URL'] = creds.confluence_url
        if creds.username:
            self.env['JIRA_USERNAME'] = creds.username
            self.env['CONFLUENCE_USERNAME'] = creds.username
        if creds.api_token:
            self.env['JIRA_API_TOKEN'] = creds.api_token
            self.env['CONFLUENCE_API_TOKEN'] = creds.api_token
        elif creds.password:
            # Server/Data Center uses personal-token variables. The GUI field is
            # intentionally described as an optional compatible fallback.
            self.env['JIRA_PERSONAL_TOKEN'] = creds.password
            self.env['CONFLUENCE_PERSONAL_TOKEN'] = creds.password
        self.process: subprocess.Popen[str] | None = None
        self.messages: queue.Queue[dict[str, Any]] = queue.Queue()
        self.stderr_tail: list[str] = []
        self.tools: list[dict[str, Any]] = []
        self.server_info: dict[str, Any] = {}
        self._next_id = 1

    def __enter__(self) -> '_AtlassianMcpStdioClient':
        try:
            self.process = subprocess.Popen(
                self.command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding='utf-8',
                errors='replace',
                bufsize=1,
                env=self.env,
            )
        except Exception as exc:
            raise AtlassianMcpError(f'Could not launch mcp-atlassian: {type(exc).__name__}: {exc}') from exc
        threading.Thread(target=self._read_stdout, daemon=True).start()
        threading.Thread(target=self._read_stderr, daemon=True).start()
        init = self.request('initialize', {
            'protocolVersion': '2025-11-25',
            'capabilities': {},
            'clientInfo': {'name': 'AstraHealAI', 'title': 'AstraHeal AI Atlassian Source Intake', 'version': '0.4.4'},
        })
        self.server_info = ((init.get('result') or {}).get('serverInfo') or {})
        self.notify('notifications/initialized', {})
        listed = self.request('tools/list', {})
        self.tools = ((listed.get('result') or {}).get('tools') or [])
        if not self.tools:
            raise AtlassianMcpError('mcp-atlassian initialized but exposed no tools.')
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        process = self.process
        if not process:
            return
        try:
            if process.stdin:
                process.stdin.close()
            process.wait(timeout=3)
        except Exception:
            try:
                process.terminate()
                process.wait(timeout=3)
            except Exception:
                try:
                    process.kill()
                except Exception:
                    pass

    def _read_stdout(self) -> None:
        process = self.process
        if not process or not process.stdout:
            return
        for raw in process.stdout:
            line = raw.strip()
            if not line:
                continue
            try:
                value = json.loads(line)
                if isinstance(value, dict):
                    self.messages.put(value)
            except Exception:
                self.stderr_tail.append('Non-JSON stdout suppressed: ' + line[:500])
                self.stderr_tail[:] = self.stderr_tail[-30:]

    def _read_stderr(self) -> None:
        process = self.process
        if not process or not process.stderr:
            return
        for raw in process.stderr:
            line = raw.strip()
            if line:
                self.stderr_tail.append(line[:1200])
                self.stderr_tail[:] = self.stderr_tail[-30:]

    def _send(self, payload: dict[str, Any]) -> None:
        process = self.process
        if not process or not process.stdin:
            raise AtlassianMcpError('mcp-atlassian process is not writable.')
        process.stdin.write(json.dumps(payload, separators=(',', ':')) + '\n')
        process.stdin.flush()

    def request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        request_id = self._next_id
        self._next_id += 1
        self._send({'jsonrpc': '2.0', 'id': request_id, 'method': method, 'params': params})
        deadline = time.monotonic() + self.timeout_seconds
        deferred: list[dict[str, Any]] = []
        while time.monotonic() < deadline:
            process = self.process
            if process and process.poll() is not None and self.messages.empty():
                details = ' | '.join(self.stderr_tail[-8:])
                raise AtlassianMcpError(f'mcp-atlassian exited with code {process.returncode}. {details}'.strip())
            try:
                message = self.messages.get(timeout=min(0.5, max(0.05, deadline - time.monotonic())))
            except queue.Empty:
                continue
            if message.get('id') == request_id:
                for item in deferred:
                    self.messages.put(item)
                if message.get('error'):
                    raise AtlassianMcpError(f"MCP {method} failed: {message.get('error')}")
                return message
            deferred.append(message)
        for item in deferred:
            self.messages.put(item)
        raise AtlassianMcpError(f'MCP {method} timed out after {self.timeout_seconds} seconds. ' + ' | '.join(self.stderr_tail[-5:]))

    def notify(self, method: str, params: dict[str, Any]) -> None:
        self._send({'jsonrpc': '2.0', 'method': method, 'params': params})

    def tool(self, name: str) -> dict[str, Any]:
        exact = next((tool for tool in self.tools if tool.get('name') == name), None)
        if exact:
            return exact
        raise AtlassianMcpError(f"Required MCP tool '{name}' is not exposed. Available relevant tools: " + ', '.join(str(x.get('name')) for x in self.tools if any(token in str(x.get('name')).lower() for token in ('jira', 'confluence')))[:2000])

    @staticmethod
    def _argument(tool: dict[str, Any], candidates: tuple[str, ...], value: Any, arguments: dict[str, Any]) -> None:
        properties = ((tool.get('inputSchema') or {}).get('properties') or {})
        normalized = {re.sub(r'[^a-z0-9]', '', str(key).lower()): key for key in properties}
        for candidate in candidates:
            key = normalized.get(re.sub(r'[^a-z0-9]', '', candidate.lower()))
            if key:
                arguments[key] = value
                return

    def call(self, name: str, values: dict[tuple[str, ...], Any]) -> dict[str, Any]:
        tool = self.tool(name)
        arguments: dict[str, Any] = {}
        for candidates, value in values.items():
            if value is not None and value != '':
                self._argument(tool, candidates, value, arguments)
        response = self.request('tools/call', {'name': name, 'arguments': arguments})
        result = response.get('result') or {}
        if result.get('isError'):
            raise AtlassianMcpError(f"MCP tool {name} returned an error: {_mcp_result_text(result)[:3000]}")
        return result


def _mcp_result_text(result: dict[str, Any]) -> str:
    parts: list[str] = []
    for content in result.get('content') or []:
        if isinstance(content, dict) and content.get('type') == 'text':
            parts.append(str(content.get('text') or ''))
    structured = result.get('structuredContent')
    if structured is not None:
        parts.append(json.dumps(structured, ensure_ascii=False))
    return '\n'.join(x for x in parts if x).strip()


def _json_from_mcp_result(result: dict[str, Any]) -> Any:
    if result.get('structuredContent') is not None:
        return result.get('structuredContent')
    text = _mcp_result_text(result)
    candidates = [text]
    candidates.extend(re.findall(r'```(?:json)?\s*(.*?)```', text, re.I | re.S))
    for candidate in candidates:
        try:
            return json.loads(candidate.strip())
        except Exception:
            continue
    return None


def _issue_dicts_from_value(value: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    seen: set[str] = set()

    def visit(node: Any) -> None:
        if isinstance(node, list):
            for item in node:
                visit(item)
            return
        if not isinstance(node, dict):
            return
        key = str(node.get('key') or node.get('issueKey') or node.get('issue_key') or '').strip().upper()
        if re.match(r'^[A-Z][A-Z0-9]+-\d+$', key) and key not in seen:
            fields = node.get('fields') if isinstance(node.get('fields'), dict) else {}
            summary = fields.get('summary') or node.get('summary') or node.get('title') or key
            issue_type = fields.get('issuetype') or node.get('issuetype') or node.get('issue_type') or {'name': 'Issue'}
            if isinstance(issue_type, str):
                issue_type = {'name': issue_type}
            description = fields.get('description') or node.get('description') or node.get('acceptance_criteria') or node.get('content') or ''
            priority = fields.get('priority') or node.get('priority') or {'name': ''}
            if isinstance(priority, str):
                priority = {'name': priority}
            found.append({'key': key, 'fields': {**fields, 'summary': summary, 'issuetype': issue_type, 'description': description, 'priority': priority}})
            seen.add(key)
        for child in node.values():
            if isinstance(child, (dict, list)):
                visit(child)

    visit(value)
    return found


def _fallback_issue_from_mcp_text(key: str, result: dict[str, Any], issue_type: str = 'Issue') -> dict[str, Any]:
    text = _mcp_result_text(result)
    summary = key
    for line in text.splitlines():
        clean = re.sub(r'^#+\s*', '', line).strip()
        if clean and key not in clean and len(clean) < 220:
            summary = clean
            break
    return {'key': key, 'fields': {'summary': summary, 'issuetype': {'name': issue_type}, 'description': text, 'priority': {'name': ''}}}


def _fetch_via_mcp(
    creds: AtlassianCredentials,
    source_kind: str,
    issue_key: str = '',
    epic_key: str = '',
    jql: str = '',
    confluence_page: str = '',
    max_results: int = 200,
) -> dict[str, Any]:
    timeout = int(os.getenv('ASTRAHEAL_ATLASSIAN_MCP_TIMEOUT', '45') or 45)
    with _AtlassianMcpStdioClient(creds, timeout_seconds=timeout) as client:
        calls: list[str] = []
        if source_kind.startswith('confluence'):
            page_id = _extract_page_id(confluence_page)
            result = client.call('confluence_get_page', {
                ('page_id', 'pageId', 'id'): page_id,
                ('include_metadata', 'includeMetadata'): True,
                ('convert_to_markdown', 'convertToMarkdown'): True,
            })
            calls.append('confluence_get_page')
            text = _mcp_result_text(result)
            if not text:
                raise AtlassianMcpError('confluence_get_page returned no readable content.')
            return {
                'ok': True,
                'source_kind': source_kind,
                'source_text': f'Confluence Page ID: {page_id}\n\n{text}',
                'item_count': 1,
                'items': [{'id': page_id, 'title': f'Confluence page {page_id}'}],
                'transport_used': 'atlassian_mcp_stdio',
                'mcp_tool_calls': calls,
                'mcp_server_info': client.server_info,
                'mcp_discovered_tool_count': len(client.tools),
                'message': 'Confluence content was fetched through the locally launched Atlassian MCP stdio server.',
            }

        if source_kind == 'jira_issue':
            result = client.call('jira_get_issue', {('issue_key', 'issueKey', 'key'): issue_key})
            calls.append('jira_get_issue')
            issues = _issue_dicts_from_value(_json_from_mcp_result(result))
            issue = next((x for x in issues if x.get('key') == issue_key.upper()), None) or (issues[0] if issues else _fallback_issue_from_mcp_text(issue_key.upper(), result))
            return {
                'ok': True,
                'source_kind': source_kind,
                'source_text': issue_to_testcase_text(issue),
                'item_count': 1,
                'items': [{'key': issue.get('key'), 'title': (issue.get('fields') or {}).get('summary'), 'type': ((issue.get('fields') or {}).get('issuetype') or {}).get('name')}],
                'transport_used': 'atlassian_mcp_stdio',
                'mcp_tool_calls': calls,
                'mcp_server_info': client.server_info,
                'mcp_discovered_tool_count': len(client.tools),
                'message': f'Fetched Jira issue {issue_key} through Atlassian MCP.',
            }

        search_jql = jql
        epic: dict[str, Any] | None = None
        if source_kind == 'jira_epic':
            epic_result = client.call('jira_get_issue', {('issue_key', 'issueKey', 'key'): epic_key})
            calls.append('jira_get_issue')
            epic_values = _issue_dicts_from_value(_json_from_mcp_result(epic_result))
            epic = next((x for x in epic_values if x.get('key') == epic_key.upper()), None) or _fallback_issue_from_mcp_text(epic_key.upper(), epic_result, 'Epic')
            search_jql = f'parent = {epic_key} OR "Epic Link" = {epic_key} ORDER BY key ASC'
        search_result = client.call('jira_search', {
            ('jql', 'query'): search_jql,
            ('limit', 'max_results', 'maxResults'): max_results,
        })
        calls.append('jira_search')
        issues = _issue_dicts_from_value(_json_from_mcp_result(search_result))
        if not issues:
            # Some versions return human-readable rows instead of JSON. Preserve
            # each issue block when Jira keys are visible.
            text = _mcp_result_text(search_result)
            keys = list(dict.fromkeys(re.findall(r'\b[A-Z][A-Z0-9]+-\d+\b', text)))
            issues = [_fallback_issue_from_mcp_text(key, {'content': [{'type': 'text', 'text': text}]}) for key in keys]
        if source_kind == 'jira_epic':
            issues = [x for x in issues if x.get('key') != epic_key.upper()]
            if not issues:
                raise AtlassianMcpError('Atlassian MCP returned no child issues for the Epic; secure REST fallback will try additional Jira Epic-link strategies.')
            source_text = epic_to_source_text({'epic': epic or {}, 'children': issues})
            message = f'Fetched Epic {epic_key} and {len(issues)} child item(s) through Atlassian MCP.'
        else:
            if not issues:
                raise AtlassianMcpError('jira_search returned no parseable issues.')
            source_text = '\n\n---\n\n'.join(issue_to_testcase_text(issue) for issue in issues)
            message = f'Fetched {len(issues)} Jira issue(s) through Atlassian MCP.'
        return {
            'ok': True,
            'source_kind': source_kind,
            'source_text': source_text,
            'item_count': len(issues),
            'items': [{'key': x.get('key'), 'title': (x.get('fields') or {}).get('summary'), 'type': ((x.get('fields') or {}).get('issuetype') or {}).get('name')} for x in issues],
            'transport_used': 'atlassian_mcp_stdio',
            'mcp_tool_calls': calls,
            'mcp_server_info': client.server_info,
            'mcp_discovered_tool_count': len(client.tools),
            'message': message,
        }


def _probe_mcp(creds: AtlassianCredentials) -> dict[str, Any]:
    if not shutil.which('uvx'):
        return {'ok': False, 'available': False, 'reason': 'uvx is not installed or not on PATH.'}
    try:
        timeout = min(30, int(os.getenv('ASTRAHEAL_ATLASSIAN_MCP_TIMEOUT', '45') or 45))
        with _AtlassianMcpStdioClient(creds, timeout_seconds=timeout) as client:
            relevant = [str(x.get('name')) for x in client.tools if any(token in str(x.get('name')).lower() for token in ('jira', 'confluence'))]
            return {'ok': True, 'available': True, 'server_info': client.server_info, 'discovered_tool_count': len(client.tools), 'relevant_tools': relevant[:100]}
    except Exception as exc:
        return {'ok': False, 'available': True, 'error': f'{type(exc).__name__}: {exc}'}


class ConfluenceClient:
    def __init__(self, creds: AtlassianCredentials):
        if not creds.confluence_url or not creds.username or not creds.secret:
            raise ValueError('Confluence URL, username/email, and API token (or compatible Data Center password) are required.')
        self.creds = creds
        self.auth = (creds.username, creds.secret)
        self.headers = {'Accept': 'application/json'}

    def _base_candidates(self) -> list[str]:
        base = self.creds.confluence_url.rstrip('/')
        values = [base]
        if not base.endswith('/wiki'):
            values.insert(0, base + '/wiki')
        return list(dict.fromkeys(values))

    def fetch_page(self, page_id_or_url: str) -> dict[str, Any]:
        page_id = _extract_page_id(page_id_or_url)
        if not page_id:
            raise ValueError('Confluence page ID or page URL is required.')
        errors: list[str] = []
        for base in self._base_candidates():
            url = f'{base}/api/v2/pages/{page_id}'
            try:
                resp = requests.get(url, auth=self.auth, headers=self.headers, params={'body-format': 'storage'}, timeout=60)
                if resp.status_code < 400:
                    data = resp.json()
                    body = ((data.get('body') or {}).get('storage') or {}).get('value') or ''
                    return {'id': str(data.get('id') or page_id), 'title': data.get('title') or f'Confluence page {page_id}', 'body_html': body, 'body_text': _html_to_text(body), 'url': url, 'api_version': 'v2'}
                errors.append(f'{url}: HTTP {resp.status_code}: {resp.text[:500]}')
            except Exception as exc:
                errors.append(f'{url}: {type(exc).__name__}: {exc}')
        for base in self._base_candidates():
            url = f'{base}/rest/api/content/{page_id}'
            try:
                resp = requests.get(url, auth=self.auth, headers=self.headers, params={'expand': 'body.storage,version,space'}, timeout=60)
                if resp.status_code < 400:
                    data = resp.json()
                    body = (((data.get('body') or {}).get('storage') or {}).get('value')) or ''
                    return {'id': str(data.get('id') or page_id), 'title': data.get('title') or f'Confluence page {page_id}', 'body_html': body, 'body_text': _html_to_text(body), 'url': url, 'api_version': 'v1'}
                errors.append(f'{url}: HTTP {resp.status_code}: {resp.text[:500]}')
            except Exception as exc:
                errors.append(f'{url}: {type(exc).__name__}: {exc}')
        raise RuntimeError('Confluence page fetch failed. ' + ' | '.join(errors[-4:]))


def _html_to_text(value: str) -> str:
    parser = _VisibleTextParser()
    parser.feed(value or '')
    return parser.text()


def _safe_error(value: Any, creds: AtlassianCredentials) -> str:
    text = str(value or '')
    for secret in (creds.api_token, creds.password):
        if secret:
            text = text.replace(secret, '[REDACTED]')
    return text[:6000]


def _mcp_preferred() -> bool:
    return str(os.getenv('ASTRAHEAL_PREFER_ATLASSIAN_MCP', 'true')).strip().lower() not in {'0', 'false', 'no', 'off'}


def atlassian_status(creds: AtlassianCredentials, include_confluence: bool = False) -> dict[str, Any]:
    mcp = prepare_atlassian_mcp_config()
    result: dict[str, Any] = {'ok': False, 'mcp': mcp, 'credentials': creds.safe_summary(), 'jira': {}, 'confluence': {}, 'mcp_runtime': {'ok': False, 'available': bool(shutil.which('uvx')), 'reason': 'Not probed because credentials are incomplete or MCP preference is disabled.'}}
    try:
        jira_secret = creds.api_token or creds.password
        if not creds.jira_url or not creds.username or not jira_secret:
            raise ValueError('Jira URL, username/email, and API token (or compatible Data Center password) are required.')
        me = JiraClient(JiraCredentials(creds.jira_url, creds.username, jira_secret)).myself()
        result['jira'] = {'ok': True, 'display_name': me.get('displayName'), 'account_id': me.get('accountId')}
        result['ok'] = True
    except Exception as exc:
        result['jira'] = {'ok': False, 'error': f'{type(exc).__name__}: {exc}'}
    if include_confluence and creds.confluence_url:
        result['confluence'] = {'ok': bool(creds.username and creds.secret), 'message': 'Credentials are present. Page access is verified when a page is fetched.'}
    if _mcp_preferred() and creds.username and creds.secret and (creds.jira_url or creds.confluence_url):
        result['mcp_runtime'] = _probe_mcp(creds)
        if result['mcp_runtime'].get('ok'):
            result['ok'] = True
    result['transport_policy'] = 'AstraHeal discovers and calls local mcp-atlassian tools first when uvx is available. Deterministic secure REST is used only as a reported fallback.'
    return result


def fetch_atlassian_source(
    creds: AtlassianCredentials,
    source_kind: str,
    issue_key: str = '',
    epic_key: str = '',
    jql: str = '',
    confluence_page: str = '',
    max_results: int = 200,
) -> dict[str, Any]:
    mcp = prepare_atlassian_mcp_config()
    source_kind = (source_kind or 'jira_issue').strip().lower()
    safe = creds.safe_summary()
    mcp_attempt: dict[str, Any] = {'attempted': False, 'ok': False, 'reason': 'uvx unavailable or MCP preference disabled'}
    if _mcp_preferred() and shutil.which('uvx'):
        mcp_attempt = {'attempted': True, 'ok': False}
        try:
            fetched = _fetch_via_mcp(
                creds=creds,
                source_kind=source_kind,
                issue_key=issue_key,
                epic_key=epic_key,
                jql=jql,
                confluence_page=confluence_page,
                max_results=max_results,
            )
            mcp_attempt = {'attempted': True, 'ok': True, 'tool_calls': fetched.get('mcp_tool_calls') or []}
            return {**fetched, 'mcp': mcp, 'mcp_attempt': mcp_attempt, 'credentials': safe}
        except Exception as exc:
            mcp_attempt = {'attempted': True, 'ok': False, 'error': _safe_error(f'{type(exc).__name__}: {exc}', creds), 'fallback': 'secure_rest'}
    if source_kind.startswith('confluence'):
        page = ConfluenceClient(creds).fetch_page(confluence_page)
        text = f"Confluence Page ID: {page['id']}\nTitle: {page['title']}\n\n{page['body_text']}"
        return {
            'ok': True,
            'source_kind': source_kind,
            'source_text': text,
            'item_count': 1,
            'items': [{'id': page['id'], 'title': page['title']}],
            'transport_used': 'secure_confluence_rest_fallback',
            'mcp': mcp,
            'mcp_attempt': mcp_attempt,
            'credentials': safe,
            'message': 'Confluence content was fetched securely. MCP config is ready; deterministic REST was used for this GUI request so credentials remained in memory only.',
        }
    secret = creds.api_token or creds.password
    client = JiraClient(JiraCredentials(creds.jira_url, creds.username, secret))
    if source_kind == 'jira_epic':
        bundle = client.fetch_epic_with_children(epic_key, max_results=max_results)
        children = bundle.get('children') or []
        return {
            'ok': True,
            'source_kind': source_kind,
            'source_text': epic_to_source_text(bundle),
            'item_count': len(children),
            'items': [{'key': x.get('key'), 'title': (x.get('fields') or {}).get('summary'), 'type': ((x.get('fields') or {}).get('issuetype') or {}).get('name')} for x in children],
            'search_attempts': bundle.get('search_attempts') or [],
            'transport_used': 'secure_jira_rest_fallback',
            'mcp': mcp,
            'mcp_attempt': mcp_attempt,
            'credentials': safe,
            'message': f"Fetched epic {epic_key} and {len(children)} child story/task/bug item(s).",
        }
    if source_kind == 'jira_jql':
        issues = client.search_issues(jql, max_results=max_results)
        blocks = [issue_to_testcase_text(issue) for issue in issues]
        return {
            'ok': True,
            'source_kind': source_kind,
            'source_text': '\n\n---\n\n'.join(blocks),
            'item_count': len(issues),
            'items': [{'key': x.get('key'), 'title': (x.get('fields') or {}).get('summary'), 'type': ((x.get('fields') or {}).get('issuetype') or {}).get('name')} for x in issues],
            'transport_used': 'secure_jira_rest_fallback',
            'mcp': mcp,
            'mcp_attempt': mcp_attempt,
            'credentials': safe,
            'message': f'Fetched {len(issues)} Jira issue(s) using the supplied JQL.',
        }
    issue = client.get_issue(issue_key)
    return {
        'ok': True,
        'source_kind': 'jira_issue',
        'source_text': issue_to_testcase_text(issue),
        'item_count': 1,
        'items': [{'key': issue.get('key'), 'title': (issue.get('fields') or {}).get('summary'), 'type': ((issue.get('fields') or {}).get('issuetype') or {}).get('name')}],
        'transport_used': 'secure_jira_rest_fallback',
        'mcp': mcp,
        'mcp_attempt': mcp_attempt,
        'credentials': safe,
        'message': f'Fetched Jira issue {issue_key}.',
    }
