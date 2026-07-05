
from __future__ import annotations

import json
import re
import html
import time
import urllib.request
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from qa_pipeline.core.io import read_json, write_json
from qa_pipeline.core.paths import QA_CACHE_DIR, REPO_ROOT, TESTCASES_DIR, feature_testcase_path, ensure_dirs
from qa_pipeline.core.text import safe_id
from qa_pipeline.agents.phase2_source_intake_rag.ingest import write_functional_testcases_markdown
from qa_pipeline.core.active_context import write_active_context, read_active_context
from qa_pipeline.core.runtime_logger import log_event

class _SimpleAppHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.title = ''
        self._tag_stack: list[str] = []
        self._current_a: dict[str, str] | None = None
        self.headings: list[str] = []
        self.buttons: list[str] = []
        self.links: list[dict[str, str]] = []
        self.inputs: list[dict[str, str]] = []
        self.forms = 0
        self._buffer: list[str] = []
        self._capture_title = False
        self._capture_heading = False
        self._capture_button = False
    def handle_starttag(self, tag, attrs):
        d = {k: v or '' for k, v in attrs}
        self._tag_stack.append(tag)
        if tag == 'title':
            self._capture_title = True; self._buffer=[]
        elif tag in {'h1','h2','h3'}:
            self._capture_heading = True; self._buffer=[]
        elif tag == 'button':
            self._capture_button = True; self._buffer=[]
            aria = d.get('aria-label') or d.get('title')
            if aria: self.buttons.append(aria.strip())
        elif tag == 'a':
            self._current_a = {'href': d.get('href',''), 'text': ''}
            self._buffer=[]
        elif tag == 'input':
            self.inputs.append({
                'type': d.get('type','text'),
                'name': d.get('name',''),
                'id': d.get('id',''),
                'placeholder': d.get('placeholder',''),
                'aria_label': d.get('aria-label',''),
                'testid': d.get('data-testid','') or d.get('data-test','') or d.get('data-qa',''),
            })
        elif tag == 'form':
            self.forms += 1
    def handle_data(self, data):
        txt = ' '.join((data or '').split())
        if not txt: return
        if self._capture_title or self._capture_heading or self._capture_button or self._current_a is not None:
            self._buffer.append(txt)
    def handle_endtag(self, tag):
        text = ' '.join(self._buffer).strip()
        if tag == 'title' and self._capture_title:
            self.title = text[:120]
            self._capture_title=False; self._buffer=[]
        elif tag in {'h1','h2','h3'} and self._capture_heading:
            if text and text not in self.headings: self.headings.append(text[:120])
            self._capture_heading=False; self._buffer=[]
        elif tag == 'button' and self._capture_button:
            if text and text not in self.buttons: self.buttons.append(text[:100])
            self._capture_button=False; self._buffer=[]
        elif tag == 'a' and self._current_a is not None:
            self._current_a['text'] = text[:120]
            if self._current_a.get('href') or self._current_a.get('text'):
                self.links.append(dict(self._current_a))
            self._current_a=None; self._buffer=[]
        if self._tag_stack:
            try: self._tag_stack.pop()
            except Exception: pass

def _safe_feature(value: str) -> str:
    return re.sub(r'[^a-z0-9_-]+','_', (value or 'feature').strip().lower()).strip('_') or 'feature'

def _abs_url(base: str, href: str) -> str:
    if not href: return base
    if href.startswith('http://') or href.startswith('https://'): return href
    if href.startswith('/'):
        m = re.match(r'^(https?://[^/]+)', base)
        return (m.group(1) if m else base.rstrip('/')) + href
    return base.rstrip('/') + '/' + href.lstrip('/')

def _write_source_json(payload: dict[str, Any], feature: str, source_type: str = 'app_url') -> Path:
    ensure_dirs()
    out = QA_CACHE_DIR / 'module1_sources' / source_type / feature / f'{feature}.normalized.json'
    out.parent.mkdir(parents=True, exist_ok=True)
    write_json(out, payload)
    return out

def _save_testcases(payload: dict[str, Any], feature: str, source_type: str = 'module1') -> Path:
    path = feature_testcase_path(source_type, feature)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload.setdefault('id', f'module1-{feature}-{int(time.time())}')
    payload.setdefault('feature', feature)
    payload.setdefault('source_type', source_type)
    write_json(path, payload)
    write_functional_testcases_markdown(path, payload)
    write_active_context({
        'channel': 'module1_functional_testcase_generator',
        'source_type': source_type,
        'requested_feature': feature,
        'parent_feature': feature,
        'features': [feature],
        'testcase_paths': [str(path.relative_to(REPO_ROOT))],
        'playwright_generated': False,
        'functional_testcases_reviewed': False,
        'review_gate': 'module1_waiting_for_user_review',
    })
    return path

def generate_testcases_from_url(app_url: str, feature: str, provider: str = 'deterministic', model: str = 'llama3') -> dict[str, Any]:
    feature = _safe_feature(feature)
    log_event('module1_url_crawl', f'Generating functional testcases from application URL: {app_url}', progress=5, feature=feature)
    try:
        req = urllib.request.Request(app_url, headers={'User-Agent':'AIQA-Module1-TestcaseCrawler/1.0'})
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw_html = resp.read().decode(resp.headers.get_content_charset() or 'utf-8', errors='replace')
    except Exception as exc:
        raw_html = ''
        title = 'Application page'
        parser = None
        fetch_error = f'{type(exc).__name__}: {exc}'
    else:
        parser = _SimpleAppHTMLParser(); parser.feed(raw_html[:500000])
        title = parser.title or (parser.headings[0] if parser.headings else 'Application page')
        fetch_error = ''
    headings = (parser.headings if parser else [])[:8]
    links = [x for x in (parser.links if parser else []) if x.get('text')][:8]
    buttons = (parser.buttons if parser else [])[:8]
    inputs = (parser.inputs if parser else [])[:10]
    scenarios: list[dict[str, Any]] = [{
        'id': f'{feature.upper()}-URL-001',
        'title': f'Validate {title} page loads successfully',
        'feature': feature,
        'page': 'Home',
        'priority': 'high',
        'test_type': 'smoke',
        'preconditions': ['Application URL should be reachable from the selected runtime environment.'],
        'start_url': app_url,
        'steps': [
            {'action':'goto','target':'application','value': app_url, 'page':'Home'},
            {'action':'verify','target':'page title or primary heading','expected': title if title else 'Application page is displayed', 'page':'Home'},
        ],
        'expected_result': 'Application page should load without browser, network, or authorization errors.',
        'requires_human_review': bool(fetch_error),
    }]
    if links:
        link = links[0]
        scenarios.append({
            'id': f'{feature.upper()}-URL-002',
            'title': f'Validate navigation using {link.get("text")}',
            'feature': feature,
            'page': 'Home',
            'priority': 'medium',
            'test_type': 'functional',
            'preconditions': ['Application home page should be loaded.'],
            'start_url': app_url,
            'steps': [
                {'action':'goto','target':'application','value': app_url, 'page':'Home'},
                {'action':'click_navigate','target': link.get('text') or 'navigation link', 'value': _abs_url(app_url, link.get('href','')), 'page':'Home'},
                {'action':'verify','target':'destination page or URL','expected': f'Destination for {link.get("text")} should open successfully', 'page':'Home'},
            ],
            'expected_result': 'Navigation should complete and destination page should be usable.',
            'requires_human_review': False,
        })
    if inputs or buttons:
        fill_steps = [{'action':'goto','target':'application','value':app_url,'page':'Home'}]
        for inp in inputs[:3]:
            label = inp.get('placeholder') or inp.get('aria_label') or inp.get('name') or inp.get('id') or 'input field'
            fill_steps.append({'action':'fill','target':label,'value':f'${{{safe_id(label).upper()}_VALUE}}','page':'Home'})
        if buttons:
            fill_steps.append({'action':'click','target':buttons[0],'page':'Home'})
        fill_steps.append({'action':'verify','target':'form response or validation message','expected':'User should see successful response or clear validation message','page':'Home'})
        scenarios.append({
            'id': f'{feature.upper()}-URL-003',
            'title': 'Validate visible form or primary action behavior',
            'feature': feature,
            'page': 'Home',
            'priority': 'medium',
            'test_type': 'functional',
            'preconditions': ['Application page should be loaded and test data should be reviewed by QA/business user.'],
            'start_url': app_url,
            'steps': fill_steps,
            'expected_result': 'The application should respond correctly to user input/action.',
            'requires_human_review': True,
        })
    payload = {
        'feature': feature,
        'source_type': 'app_url',
        'source_ref': app_url,
        'source': app_url,
        'page': 'Home',
        'crawl_summary': {'title': title, 'headings': headings, 'links': links, 'buttons': buttons, 'inputs': inputs, 'fetch_error': fetch_error},
        'scenarios': scenarios,
    }
    src = _write_source_json(payload, feature, 'app_url')
    path = _save_testcases(payload, feature, 'module1')
    log_event('module1_url_crawl', f'Application URL testcase generation completed: {path.name}', status='done', progress=100, feature=feature)
    return {'ok': True, 'source_file': str(src.relative_to(REPO_ROOT)), 'testcase_file': str(path.relative_to(REPO_ROOT)), 'testcases': payload, 'markdown_file': str(path.with_name(path.name.replace('.scenarios.json','.scenarios.md')).relative_to(REPO_ROOT)), 'message': 'Generated testcases from application URL. Review missing values and test data before using Module 2.'}

def _find_active_testcase(feature: str, source_type: str = 'module1') -> Path:
    feature = _safe_feature(feature)
    ctx = read_active_context()
    for p in ctx.get('testcase_paths') or []:
        candidate = REPO_ROOT / p
        if candidate.exists() and feature in candidate.name:
            return candidate
    candidate = feature_testcase_path(source_type, feature)
    if candidate.exists(): return candidate
    # search fallback
    matches = list(TESTCASES_DIR.glob(f'**/{feature}.scenarios.json'))
    if matches: return matches[-1]
    raise FileNotFoundError(f'No functional testcase file found for feature={feature}. Generate or upload testcases first.')

def quality_rca_and_complete(feature: str, source_type: str = 'module1', base_url: str = '') -> dict[str, Any]:
    path = _find_active_testcase(feature, source_type)
    data = read_json(path)
    feature = data.get('feature') or _safe_feature(feature)
    issues=[]; human=[]; completed=0
    for sidx, scenario in enumerate(data.get('scenarios', []) or [], 1):
        steps = scenario.setdefault('steps', [])
        scenario.setdefault('preconditions', [])
        if not scenario.get('expected_result'):
            scenario['expected_result'] = 'Expected business result should be verified.'
            issues.append({'scenario': scenario.get('id'), 'issue':'missing_expected_result', 'fix':'Added generic expected result for human review.'})
            human.append({'scenario': scenario.get('id'), 'reason':'Expected result was missing and should be reviewed.'})
            completed += 1
        has_goto = any(str(x.get('action','')).lower() in {'goto','open','launch','navigate'} for x in steps[:2])
        start_url = scenario.get('start_url') or base_url or data.get('start_url') or data.get('source_ref') if str(data.get('source_type','')).lower() == 'app_url' else (base_url or scenario.get('start_url'))
        if not has_goto:
            steps.insert(0, {'action':'goto','target':'application','value': start_url or '${APPLICATION_URL}', 'page': scenario.get('page','Home'), 'generated_by_rca': True})
            issues.append({'scenario': scenario.get('id'), 'issue':'missing_start_navigation', 'fix':'Added a starting goto step so the testcase can run independently.'})
            completed += 1
            if not start_url:
                human.append({'scenario': scenario.get('id'), 'reason':'Application URL is unknown. User must update ${APPLICATION_URL}.'})
        if not any(str(x.get('action','')).lower() in {'verify','assert','expect','validate'} for x in steps):
            steps.append({'action':'verify','target':'expected business result','expected': scenario.get('expected_result','Expected result should be visible'), 'page': scenario.get('page','Home'), 'generated_by_rca': True})
            issues.append({'scenario': scenario.get('id'), 'issue':'missing_final_validation', 'fix':'Added final verification step.'})
            completed += 1
        text = json.dumps(scenario).lower()
        if any(w in text for w in ['checkout','payment','order','dashboard','profile','account']) and not any('login' in json.dumps(x).lower() for x in steps[:3]):
            human.append({'scenario': scenario.get('id'), 'reason':'Scenario appears to start from a protected/middle application state. Login/navigation preconditions should be verified.'})
            scenario['requires_human_review'] = True
        if any('${' in str(x.get('value','')) or '${' in str(x.get('expected','')) for x in steps):
            human.append({'scenario': scenario.get('id'), 'reason':'Placeholder value exists and should be finalized in Test Data step.'})
            scenario['requires_human_review'] = True
    report = {
        'ok': True,
        'feature': feature,
        'testcase_file': str(path.relative_to(REPO_ROOT)),
        'coverage_score': max(0, min(100, 100 - len(human)*10)),
        'issues_found': issues,
        'steps_completed_by_system': completed,
        'human_review_required': human,
        'message': 'Quality RCA completed. System added safe missing navigation/verification steps where possible. Human review is required for unknown business/data gaps.',
    }
    write_json(path, data)
    write_functional_testcases_markdown(path, data)
    report_path = QA_CACHE_DIR / 'module1_reports' / feature / 'testcase-quality-rca.json'
    report_path.parent.mkdir(parents=True, exist_ok=True)
    write_json(report_path, report)
    html_path = report_path.with_suffix('.html')
    html_path.write_text('<html><body><h1>Module 1 Testcase Quality RCA</h1><pre>'+html.escape(json.dumps(report, indent=2))+'</pre></body></html>', encoding='utf-8')
    log_event('module1_quality_rca', 'Functional testcase RCA completed', status='done', progress=100, feature=feature)
    return report | {'testcases': data, 'report_file': str(report_path.relative_to(REPO_ROOT)), 'html_report': str(html_path.relative_to(REPO_ROOT))}

def generate_and_save_testdata(feature: str, source_type: str = 'module1') -> dict[str, Any]:
    path = _find_active_testcase(feature, source_type)
    data = read_json(path)
    feature = data.get('feature') or _safe_feature(feature)
    records: dict[str, Any] = {}
    for scenario in data.get('scenarios', []) or []:
        sid = scenario.get('id') or scenario.get('title') or 'scenario'
        values = {}
        for step in scenario.get('steps', []) or []:
            if str(step.get('action','')).lower() in {'fill','type','enter','select','choose'}:
                target = step.get('target') or 'field'
                key = safe_id(str(target)).upper() or 'VALUE'
                val = step.get('value') or ''
                if not val or str(val).startswith('${'):
                    low = str(target).lower()
                    if 'email' in low or 'username' in low: val = 'test.user@example.com'
                    elif 'password' in low: val = 'Password@123'
                    elif 'zip' in low or 'postal' in low: val = '10001'
                    elif 'phone' in low: val = '9999999999'
                    elif 'amount' in low or 'price' in low: val = '100'
                    else: val = f'sample_{safe_id(str(target))}'
                values[key] = {'value': val, 'source': 'ai_generated_candidate', 'requires_human_approval': True}
        records[sid] = values
    out = QA_CACHE_DIR / 'module1_testdata' / feature / f'{feature}.testdata.candidates.json'
    out.parent.mkdir(parents=True, exist_ok=True)
    write_json(out, {'feature': feature, 'testcase_file': str(path.relative_to(REPO_ROOT)), 'records': records, 'status': 'waiting_for_human_review'})
    log_event('module1_testdata', 'Candidate test data generated for human verification', status='done', progress=100, feature=feature)
    return {'ok': True, 'testdata_file': str(out.relative_to(REPO_ROOT)), 'testdata': read_json(out), 'message':'Candidate test data generated. Please review and finalize before automation generation.'}

def save_human_review(feature: str, edited_json: str, source_type: str = 'module1') -> dict[str, Any]:
    path = _find_active_testcase(feature, source_type)
    try:
        data = json.loads(edited_json)
    except Exception as exc:
        return {'ok': False, 'error': f'Edited testcase content must be valid JSON: {type(exc).__name__}: {exc}'}
    if not isinstance(data, dict) or not isinstance(data.get('scenarios'), list):
        return {'ok': False, 'error': 'Edited JSON must contain a scenarios array.'}
    write_json(path, data)
    write_functional_testcases_markdown(path, data)
    mem = QA_CACHE_DIR / 'module1_memory' / 'human_testcase_reviews.jsonl'
    mem.parent.mkdir(parents=True, exist_ok=True)
    mem.write_text(mem.read_text(encoding='utf-8') + json.dumps({'feature': feature, 'testcase_file': str(path.relative_to(REPO_ROOT)), 'saved_at': int(time.time()), 'scenario_count': len(data.get('scenarios', []))}) + '\n' if mem.exists() else json.dumps({'feature': feature, 'testcase_file': str(path.relative_to(REPO_ROOT)), 'saved_at': int(time.time()), 'scenario_count': len(data.get('scenarios', []))})+'\n', encoding='utf-8')
    ctx = read_active_context(); ctx['functional_testcases_reviewed'] = True; ctx['review_gate'] = 'approved_after_module1_human_review'; write_active_context(ctx)
    log_event('module1_human_review', 'Human-reviewed functional testcases saved to memory and approved', status='done', progress=100, feature=feature)
    return {'ok': True, 'testcase_file': str(path.relative_to(REPO_ROOT)), 'markdown_file': str(path.with_name(path.name.replace('.scenarios.json','.scenarios.md')).relative_to(REPO_ROOT)), 'active_context': read_active_context(), 'message':'Human-reviewed testcases saved and approved for Module 2.'}
