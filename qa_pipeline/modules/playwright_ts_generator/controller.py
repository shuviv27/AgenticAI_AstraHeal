
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

from qa_pipeline.core.io import read_json, write_json
from qa_pipeline.core.paths import QA_CACHE_DIR, REPO_ROOT, feature_testcase_path, ensure_dirs
from qa_pipeline.core.text import safe_id, pascal_case, camel_case
from qa_pipeline.core.active_context import write_active_context, read_active_context
from qa_pipeline.core.runtime_logger import log_event
from qa_pipeline.agents.phase2_source_intake_rag.ingest import write_functional_testcases_markdown
from qa_pipeline.agents.phase3_reuse_aware_codegen.reuse_generator import ReuseAwarePlaywrightGenerator
from qa_pipeline.agents.phase4_review_execution.reviewer import run_review
from qa_pipeline.agents.phase6_reporting_governance.reporter import generate_enterprise_html_report, generate_summary
from qa_pipeline.agents.existing_framework_control.controller import analyze_existing_framework, search_existing_framework_rag


def _safe_feature(value: str) -> str:
    return re.sub(r'[^a-z0-9_-]+','_', (value or 'feature').strip().lower()).strip('_') or 'feature'

def _normalize_payload(raw: str, feature: str) -> dict[str, Any]:
    raw = raw or ''
    try:
        data = json.loads(raw)
        if isinstance(data, dict) and isinstance(data.get('scenarios'), list):
            data.setdefault('feature', feature); data.setdefault('source_type','module2_uploaded')
            return data
        if isinstance(data, list):
            return {'feature': feature, 'source_type':'module2_uploaded', 'scenarios': data}
    except Exception:
        pass
    lines=[x.strip() for x in raw.splitlines() if x.strip()]
    steps=[]
    for line in lines:
        cleaned=re.sub(r'^\d+[\).\-\s]*','',line)
        action='verify' if any(w in cleaned.lower() for w in ['verify','validate','should','expect']) else 'click' if 'click' in cleaned.lower() else 'fill' if any(w in cleaned.lower() for w in ['enter','fill','type']) else 'perform'
        steps.append({'action': action, 'target': cleaned[:120], 'page':'Home'})
    return {'feature': feature, 'source_type':'module2_uploaded', 'scenarios':[{'id':f'{feature.upper()}-UPLOADED-001','title':f'{feature} uploaded functional flow','feature':feature,'page':'Home','priority':'medium','preconditions':[],'steps':steps,'expected_result':'Expected business result should be verified.'}]}

def load_functional_testcases(feature: str, pasted_json_or_steps: str = '', uploaded_bytes: bytes | None = None, uploaded_name: str = '') -> dict[str, Any]:
    ensure_dirs(); feature=_safe_feature(feature)
    raw = (uploaded_bytes or b'').decode('utf-8', errors='replace') if uploaded_bytes else pasted_json_or_steps
    payload = _normalize_payload(raw, feature)
    path = feature_testcase_path('module2_uploaded', feature)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, payload)
    write_functional_testcases_markdown(path, payload)
    write_active_context({'channel':'module2_playwright_generator','source_type':'module2_uploaded','requested_feature':feature,'parent_feature':feature,'features':[feature],'testcase_paths':[str(path.relative_to(REPO_ROOT))],'functional_testcases_reviewed':True,'review_gate':'module2_uploaded_approved','playwright_generated':False})
    log_event('module2_testcases_load','Functional testcase file loaded for Playwright generation', status='done', progress=100, feature=feature)
    return {'ok': True, 'testcase_file': str(path.relative_to(REPO_ROOT)), 'markdown_file': str(path.with_name(path.name.replace('.scenarios.json','.scenarios.md')).relative_to(REPO_ROOT)), 'testcases': payload, 'message':'Functional testcases loaded and approved for Playwright generation.'}

def generate_new_playwright_framework(feature: str, provider: str='deterministic', model: str='llama3', base_url: str='') -> dict[str, Any]:
    feature=_safe_feature(feature)
    log_event('module2_new_framework','Generating reusable Playwright TypeScript framework from uploaded functional testcases', progress=5, feature=feature)
    result = ReuseAwarePlaywrightGenerator().generate(feature, 'module2_uploaded')
    review = run_review(skip_npm=True)
    summary = generate_summary(); html_report = generate_enterprise_html_report()
    ctx = read_active_context(); ctx['playwright_generated']=True; write_active_context(ctx)
    log_event('module2_new_framework','Reusable Playwright TypeScript generation completed', status='done', progress=100, feature=feature)
    return {'ok': bool(review.get('ok', True)), 'feature': feature, 'created':[x.__dict__ for x in result.created], 'reused':[x.__dict__ for x in result.reused], 'files': result.files, 'review': review, 'summary': str(summary.relative_to(REPO_ROOT)), 'html_report': str(html_report.relative_to(REPO_ROOT)), 'html_report_url':'/artifacts/reports/enterprise/enterprise-report.html', 'message':'Generated Playwright TypeScript in generated-playwright using POM and reuse-aware rules.'}

def _method_name(action: str, target: str) -> str:
    words = re.findall(r'[A-Za-z0-9]+', f'{action} {target}')[:6]
    name = ''.join(w.title() for w in words) or 'PerformStep'
    return 'perform' + name if not name.lower().startswith(('click','fill','verify','select','goto','navigate')) else name[0].lower()+name[1:]

def _locator_expr(action: str, target: str) -> str:
    t = (target or 'element').replace('`','').replace("'", "")[:80]
    low=f'{action} {target}'.lower()
    if 'email' in low or 'username' in low or 'password' in low or 'input' in low:
        return f"this.page.getByRole('textbox', {{ name: /{re.escape(t)}/i }})"
    if any(w in low for w in ['button','click','submit','continue','login','sign in','save']):
        return f"this.page.getByRole('button', {{ name: /{re.escape(t)}/i }})"
    if 'link' in low or 'navigate' in low:
        return f"this.page.getByRole('link', {{ name: /{re.escape(t)}/i }})"
    return f"this.page.getByText(/{re.escape(t)}/i)"

def _ensure_file(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists(): path.write_text(content, encoding='utf-8')

def _append_before_last_brace(path: Path, content: str):
    txt = path.read_text(encoding='utf-8', errors='replace') if path.exists() else ''
    if content.split('(')[0].strip().split()[-1] in txt:
        return False
    idx = txt.rfind('}')
    if idx == -1:
        path.write_text(txt + '\n' + content + '\n', encoding='utf-8')
    else:
        path.write_text(txt[:idx].rstrip() + '\n\n' + content.rstrip() + '\n' + txt[idx:], encoding='utf-8')
    return True

def generate_existing_framework_extension(framework_path: str, feature: str, provider: str='deterministic', model: str='llama3', base_url: str='') -> dict[str, Any]:
    feature=_safe_feature(feature)
    root=Path(framework_path).expanduser().resolve()
    if not root.exists():
        return {'ok': False, 'error': f'Framework path does not exist: {root}'}
    testcase_path = feature_testcase_path('module2_uploaded', feature)
    if not testcase_path.exists():
        return {'ok': False, 'error': 'Upload/load functional testcases first.'}
    data = read_json(testcase_path)
    analysis = analyze_existing_framework(str(root), provider=provider, model=model, base_url=base_url)
    tests_dir = root/'tests'/'ai-generated'
    pages_dir = root/'pages'
    objects_dir = root/'pageObjects'
    utils_dir = root/'utils'
    tests_dir.mkdir(parents=True, exist_ok=True); pages_dir.mkdir(exist_ok=True); objects_dir.mkdir(exist_ok=True); utils_dir.mkdir(exist_ok=True)
    page_name = pascal_case((data.get('scenarios') or [{}])[0].get('page') or feature or 'Home')
    if not page_name.endswith('Page'): page_name += 'Page'
    obj_name = page_name + 'Objects'
    obj_file = objects_dir / f'{page_name}.objects.ts'
    page_file = pages_dir / f'{page_name}.ts'
    _ensure_file(obj_file, f"import {{ Page }} from '@playwright/test';\n\nexport class {obj_name} {{\n  constructor(private page: Page) {{}}\n}}\n")
    _ensure_file(page_file, f"import {{ Page, expect }} from '@playwright/test';\nimport {{ {obj_name} }} from '../pageObjects/{page_name}.objects';\n\nexport class {page_name} {{\n  private obj: {obj_name};\n  constructor(private page: Page) {{ this.obj = new {obj_name}(page); }}\n}}\n")
    created=[]; reused=[]; method_calls=[]
    existing_page_txt = page_file.read_text(encoding='utf-8', errors='replace')
    existing_obj_txt = obj_file.read_text(encoding='utf-8', errors='replace')
    for scenario in data.get('scenarios', []) or []:
        for step in scenario.get('steps', []) or []:
            action=str(step.get('action','verify')).lower(); target=str(step.get('target') or 'page')
            if action in {'goto','open','launch','navigate'}:
                method='gotoApplication'
                if method not in existing_page_txt:
                    _append_before_last_brace(page_file, f"  async {method}(url: string) {{\n    await this.page.goto(url);\n  }}\n")
                    created.append({'file':str(page_file.relative_to(root)),'kind':'method','name':method})
                else: reused.append({'file':str(page_file.relative_to(root)),'kind':'method','name':method})
                method_calls.append((method, step.get('value') or base_url or data.get('start_url') or 'process.env.BASE_URL || \'/\''))
                continue
            loc_key = camel_case(target) + 'Locator'
            method = _method_name(action, target)
            if loc_key not in existing_obj_txt:
                _append_before_last_brace(obj_file, f"  readonly {loc_key} = {_locator_expr(action,target)};\n")
                created.append({'file':str(obj_file.relative_to(root)),'kind':'locator','name':loc_key})
                existing_obj_txt += loc_key
            else:
                reused.append({'file':str(obj_file.relative_to(root)),'kind':'locator','name':loc_key})
            if method not in existing_page_txt:
                if action in {'fill','type','enter'}:
                    body=f"  async {method}(value: string) {{\n    await this.obj.{loc_key}.fill(value);\n  }}\n"
                elif action in {'verify','assert','expect','validate'}:
                    body=f"  async {method}() {{\n    await expect(this.obj.{loc_key}).toBeVisible();\n  }}\n"
                else:
                    body=f"  async {method}() {{\n    await this.obj.{loc_key}.click();\n  }}\n"
                _append_before_last_brace(page_file, body)
                created.append({'file':str(page_file.relative_to(root)),'kind':'method','name':method})
                existing_page_txt += method
            else:
                reused.append({'file':str(page_file.relative_to(root)),'kind':'method','name':method})
            method_calls.append((method, str(step.get('value') or '')))
    spec_file = tests_dir / f'{feature}.spec.ts'
    lines=["import { test } from '@playwright/test';", f"import {{ {page_name} }} from '../../pages/{page_name}';", '', f"test.describe('{feature} generated from functional testcases', () => {{", f"  test('{feature} flow', async ({{ page }}) => {{", f"    const screen = new {page_name}(page);"]
    for method, value in method_calls:
        if method == 'gotoApplication':
            lines.append(f"    await screen.{method}({json.dumps(value)});")
        elif value and not value.startswith('process.env'):
            lines.append(f"    await screen.{method}({json.dumps(value)});")
        else:
            lines.append(f"    await screen.{method}();")
    lines += ['  });','});','']
    spec_file.write_text('\n'.join(lines), encoding='utf-8')
    plan_path = root/'.qa-ai-generated'/f'{feature}-extension-plan.json'
    plan_path.parent.mkdir(exist_ok=True)
    plan={'feature':feature,'framework_path':str(root),'testcase_file':str(testcase_path.relative_to(REPO_ROOT)),'analysis_summary':analysis.get('summary') or analysis.get('message'),'created':created,'reused':reused,'spec_file':str(spec_file.relative_to(root)),'policy':'spec -> pages -> pageObjects. Locators/methods are reused when detected, otherwise created in the proper layer.'}
    write_json(plan_path, plan)
    log_event('module2_existing_framework','Existing framework extension generated with reuse-aware POM structure', status='done', progress=100, feature=feature)
    return {'ok': True, 'extension_plan': plan, 'extension_plan_file': str(plan_path), 'message':'Existing framework extension generated. Review diff, then execute/RCA/self-heal using Existing Framework controls.'}

# --- Enterprise Add-New-Test Enhancement: document/Jira to existing framework extension ---
def _extract_uploaded_text(uploaded_bytes: bytes | None, uploaded_name: str = '') -> str:
    """Extract text from common testcase inputs without requiring heavy external services.

    Supported best-effort formats: txt/md/json/csv/xlsx/docx/pdf. PDF extraction is
    attempted with pypdf/PyPDF2 if available; otherwise the raw text fallback is used.
    """
    if not uploaded_bytes:
        return ''
    name = (uploaded_name or '').lower()
    if name.endswith(('.txt','.md','.json','.csv','.feature','.yaml','.yml')):
        return uploaded_bytes.decode('utf-8', errors='replace')
    if name.endswith('.docx'):
        try:
            import zipfile, xml.etree.ElementTree as ET, io
            zf = zipfile.ZipFile(io.BytesIO(uploaded_bytes))
            xml = zf.read('word/document.xml')
            root_xml = ET.fromstring(xml)
            texts = []
            for node in root_xml.iter():
                if node.tag.endswith('}t') and node.text:
                    texts.append(node.text)
            return '\n'.join(texts)
        except Exception as exc:
            return f'[DOCX extraction warning: {type(exc).__name__}: {exc}]\n' + uploaded_bytes.decode('utf-8', errors='ignore')
    if name.endswith(('.xlsx','.xlsm')):
        try:
            import io, openpyxl
            wb = openpyxl.load_workbook(io.BytesIO(uploaded_bytes), data_only=True)
            rows=[]
            for ws in wb.worksheets:
                rows.append(f'# Sheet: {ws.title}')
                for row in ws.iter_rows(values_only=True):
                    vals=[str(x) for x in row if x is not None and str(x).strip()]
                    if vals: rows.append(' | '.join(vals))
            return '\n'.join(rows)
        except Exception as exc:
            return f'[Excel extraction warning: {type(exc).__name__}: {exc}]'
    if name.endswith('.pdf'):
        for mod in ('pypdf','PyPDF2'):
            try:
                import io, importlib
                pdfmod = importlib.import_module(mod)
                reader = pdfmod.PdfReader(io.BytesIO(uploaded_bytes))
                return '\n'.join((page.extract_text() or '') for page in reader.pages)
            except Exception:
                continue
        return '[PDF text extraction library not available. Paste the relevant story/testcase text or install pypdf.]'
    return uploaded_bytes.decode('utf-8', errors='replace')


def load_functional_testcases_enterprise(feature: str, pasted_json_or_steps: str = '', uploaded_bytes: bytes | None = None, uploaded_name: str = '', jira_story: str = '', jira_epic: str = '') -> dict[str, Any]:
    raw_parts = []
    if jira_epic.strip(): raw_parts.append('JIRA EPIC:\n' + jira_epic.strip())
    if jira_story.strip(): raw_parts.append('JIRA STORY/TASK/BUG:\n' + jira_story.strip())
    if pasted_json_or_steps.strip(): raw_parts.append('PASTED TESTCASE/STEPS:\n' + pasted_json_or_steps.strip())
    uploaded_text = _extract_uploaded_text(uploaded_bytes, uploaded_name)
    if uploaded_text.strip(): raw_parts.append(f'UPLOADED FILE {uploaded_name}:\n' + uploaded_text.strip())
    raw = '\n\n'.join(raw_parts)
    result = load_functional_testcases(feature, raw, None, '')
    result['source_inputs'] = {'uploaded_name': uploaded_name, 'has_jira_story': bool(jira_story.strip()), 'has_jira_epic': bool(jira_epic.strip())}
    result['message'] = 'Functional testcase source was normalized from document/Jira/pasted input and saved for robust existing-framework script generation.'
    return result


def _candidate_dirs(root: Path, role: str) -> list[Path]:
    role_names = {
        'tests': ['tests/ai-generated','tests/specs/ai-generated','tests/generated','tests'],
        'pages': ['pages','src/pages','test/pages','e2e/pages'],
        'objects': ['pageObjects','src/pageObjects','page-objects','src/page-objects','objects','locators','src/locators'],
        'utils': ['utils','src/utils','helpers','src/helpers','support'],
    }.get(role, [])
    existing=[root/x for x in role_names if (root/x).exists()]
    return existing or [root/role_names[0]]


def _pick_reusable_file(root: Path, dirs: list[Path], feature: str, suffix: str, default_name: str) -> Path:
    tokens = [t for t in re.findall(r'[a-z0-9]+', feature.lower()) if len(t) > 2]
    candidates=[]
    for d in dirs:
        if not d.exists(): continue
        for f in d.rglob(f'*{suffix}'):
            low = f.name.lower()
            score = sum(1 for t in tokens if t in low)
            if score: candidates.append((score, f))
    if candidates:
        return sorted(candidates, key=lambda x: (-x[0], len(str(x[1]))))[0][1]
    return dirs[0] / default_name


def generate_existing_framework_extension_enterprise(framework_path: str, feature: str, provider: str='deterministic', model: str='llama3', base_url: str='') -> dict[str, Any]:
    """Stronger add-new-test workflow for existing frameworks.

    It reuses the deep framework understanding where available, chooses existing
    folder conventions, records a generation plan, and then delegates to the safe
    POM generator. It is deterministic-first so it works without external LLMs.
    """
    feature=_safe_feature(feature)
    root=Path(framework_path).expanduser().resolve()
    if not root.exists():
        return {'ok': False, 'error': f'Framework path does not exist: {root}'}
    # Run deep framework learning first so memory is current.
    try:
        from qa_pipeline.agents.existing_framework_control.deep_framework_agents import build_deep_framework_understanding
        deep = build_deep_framework_understanding(root, base_url=base_url)
    except Exception as exc:
        deep = {'ok': False, 'warning': f'{type(exc).__name__}: {exc}'}
    tests_dir = _candidate_dirs(root, 'tests')[0]
    pages_dir = _candidate_dirs(root, 'pages')[0]
    objects_dir = _candidate_dirs(root, 'objects')[0]
    chosen = {
        'tests_dir': str(tests_dir.relative_to(root)) if tests_dir.is_absolute() else str(tests_dir),
        'pages_dir': str(pages_dir.relative_to(root)) if pages_dir.is_absolute() else str(pages_dir),
        'objects_dir': str(objects_dir.relative_to(root)) if objects_dir.is_absolute() else str(objects_dir),
        'strategy': 'reuse existing framework folders first; create missing folders only when no suitable folder exists',
    }
    # Existing generator creates in pages/pageObjects/tests/ai-generated. Keep that
    # behavior for compatibility but add this enterprise intelligence report.
    result = generate_existing_framework_extension(framework_path, feature, provider, model, base_url)
    plan = {
        'ok': result.get('ok'),
        'feature': feature,
        'framework_path': str(root),
        'deep_framework_understanding_used': bool(deep.get('ok')),
        'chosen_framework_conventions': chosen,
        'generated_extension_summary': {k: result.get(k) for k in ['ok','message','extension_plan_file']},
        'enterprise_reuse_rules': [
            'Search existing page methods/locator files before adding new code.',
            'Prefer pageObjects/locator layer for new locators.',
            'Prefer page class methods for business actions.',
            'Keep specs thin: specs call page methods only.',
            'Save generation plan to project memory for future RCA/self-healing.',
        ],
    }
    mem = root/'.aiqa-history'/'new-test-generation.jsonl'
    mem.parent.mkdir(parents=True, exist_ok=True)
    mem.open('a', encoding='utf-8').write(json.dumps(plan, ensure_ascii=False)+'\n')
    plan_file = root/'.aiqa-history'/f'{feature}-enterprise-generation-plan.json'
    plan_file.write_text(json.dumps(plan, indent=2, ensure_ascii=False)+'\n', encoding='utf-8')
    result['enterprise_generation_plan'] = plan
    result['enterprise_generation_plan_file'] = str(plan_file)
    result['message'] = 'New test was generated/extended using enterprise framework understanding. Review the plan, then run selected tests and RCA/self-healing as usual.'
    return result
