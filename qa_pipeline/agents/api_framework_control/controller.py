from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from qa_pipeline.core.io import read_json
from qa_pipeline.core.paths import QA_CACHE_DIR, GENERATED_PLAYWRIGHT_DIR, REPO_ROOT, feature_testcase_path
from qa_pipeline.llm.codex_cli import CodexCliProvider
from qa_pipeline.llm.ollama import OllamaProvider
from qa_pipeline.core.api_docker_runtime import execute_api_framework_in_docker
from qa_pipeline.agents.existing_framework_control.framework_intelligence import build_framework_rag_index, query_framework_context

GENERATED_API_PLAYWRIGHT_DIR = REPO_ROOT / "generated-api-playwright"
GENERATED_API_RESTASSURED_DIR = REPO_ROOT / "generated-api-restassured"
API_REPORTS_DIR = GENERATED_PLAYWRIGHT_DIR / "reports" / "api-framework"
API_CACHE_DIR = QA_CACHE_DIR / "api-framework"
API_FAILED_INVENTORY = API_CACHE_DIR / "failed-api-tests.json"
API_INTELLIGENCE_JSON = API_REPORTS_DIR / "api-framework-intelligence.json"
API_INTELLIGENCE_HTML = API_REPORTS_DIR / "api-framework-intelligence.html"
API_RCA_JSON = API_REPORTS_DIR / "api-root-cause-report.json"
API_RCA_HTML = API_REPORTS_DIR / "api-root-cause-report.html"
API_HEALING_JSON = API_REPORTS_DIR / "api-self-healing-report.json"
API_HEALING_HTML = API_REPORTS_DIR / "api-self-healing-report.html"
API_CONSOLIDATED_HTML = API_REPORTS_DIR / "api-consolidated-report.html"

API_ALLOWED_PATCH_DIRS = {
    "playwright": ["tests/", "utils/", "fixtures/", "testData/", "playwright.api.config"],
    "restassured": ["src/test/", "src/main/", "pom.xml", "build.gradle", "testData/"],
}
API_BLOCKED_PATTERNS = [
    "test.skip", "test.only", ".skip(", ".only(", "@Disabled", "Assumptions.assumeTrue(false)",
    "Thread.sleep", "waitForTimeout", "verify(false)", "assertTrue(false)", "System.exit(",
]


def _ensure_dirs() -> None:
    for p in [GENERATED_API_PLAYWRIGHT_DIR, GENERATED_API_RESTASSURED_DIR, API_REPORTS_DIR, API_CACHE_DIR]:
        p.mkdir(parents=True, exist_ok=True)


def _h(v: Any) -> str:
    return str(v if v is not None else "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _rel(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")
    except Exception:
        return str(path).replace("\\", "/")


def _safe_name(name: str, default: str = "api") -> str:
    s = re.sub(r"[^a-zA-Z0-9_-]+", "_", (name or default).strip()).strip("_")
    return (s or default).lower()


def _class_name(name: str) -> str:
    parts = re.split(r"[^a-zA-Z0-9]+", name or "GeneratedApi")
    out = "".join(p[:1].upper() + p[1:] for p in parts if p)
    if not out or out[0].isdigit():
        out = "Generated" + out
    return out + "ApiTest" if not out.endswith("ApiTest") else out


def _detect_flavor(root: Path, requested: str = "auto") -> str:
    requested = (requested or "auto").lower().strip()
    if requested in {"playwright", "playwright-ts", "playwright-js", "ts", "js"}:
        return "playwright"
    if requested in {"restassured", "rest-assured", "java"}:
        return "restassured"
    if (root / "pom.xml").exists() or (root / "build.gradle").exists() or list(root.rglob("*RestAssured*.java")):
        return "restassured"
    return "playwright"


def _safe_read(path: Path, limit: int = 220_000) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")[:limit]
    except Exception:
        return ""


def _run(cmd: str, cwd: Path, timeout: int = 300, env: dict[str, str] | None = None) -> dict[str, Any]:
    started = time.time()
    try:
        proc = subprocess.run(cmd, cwd=str(cwd), shell=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout, env={**os.environ, **(env or {})})
        return {
            "ok": proc.returncode == 0,
            "cmd": cmd,
            "cwd": str(cwd),
            "returncode": proc.returncode,
            "stdout": proc.stdout[-12000:],
            "stderr": proc.stderr[-12000:],
            "duration_sec": round(time.time() - started, 2),
        }
    except subprocess.TimeoutExpired as exc:
        return {"ok": False, "cmd": cmd, "cwd": str(cwd), "returncode": 124, "stdout": (exc.stdout or "")[-8000:], "stderr": f"Timed out after {timeout}s\n{exc.stderr or ''}"[-8000:], "duration_sec": round(time.time() - started, 2)}
    except Exception as exc:
        return {"ok": False, "cmd": cmd, "cwd": str(cwd), "returncode": -1, "stdout": "", "stderr": f"{type(exc).__name__}: {exc}", "duration_sec": round(time.time() - started, 2)}


def _load_testcase(feature: str, source_type: str) -> dict[str, Any]:
    path = feature_testcase_path(source_type, _safe_name(feature))
    if path.exists():
        try:
            return read_json(path)
        except Exception:
            pass
    # Accept source type aliases/fallbacks.
    for st in ["srs", "jira", "jira_epics", "pdf", "pdf_docs", "confluence", "test_management"]:
        path = feature_testcase_path(st, _safe_name(feature))
        if path.exists():
            try:
                return read_json(path)
            except Exception:
                continue
    return {
        "feature": _safe_name(feature),
        "page": "API",
        "source_ref": "manual-api-placeholder",
        "scenarios": [
            {
                "id": f"{_safe_name(feature).upper()}-API-001",
                "title": "API health and contract smoke check",
                "api": {"method": "GET", "path": "/", "expected_status": 200},
                "steps": [{"action": "GET", "target": "/", "expected": "HTTP status is less than 500"}],
                "expected_result": "API endpoint responds successfully or reveals a product/environment issue.",
            }
        ],
    }


def _infer_api_scenarios(testcase: dict[str, Any], base_url: str = "") -> list[dict[str, Any]]:
    scenarios = []
    base = (base_url or testcase.get("start_url") or "https://example.com").rstrip("/")
    for idx, sc in enumerate(testcase.get("scenarios") or []):
        api = sc.get("api") if isinstance(sc.get("api"), dict) else {}
        method = str(api.get("method") or "").upper().strip()
        path = str(api.get("path") or api.get("endpoint") or "").strip()
        expected_status = api.get("expected_status") or api.get("status") or 200
        body = api.get("body") or api.get("payload")
        headers = api.get("headers") if isinstance(api.get("headers"), dict) else {}
        # Find endpoints in steps if api block is absent.
        text = json.dumps(sc, ensure_ascii=False)
        if not method:
            m = re.search(r"\b(GET|POST|PUT|PATCH|DELETE)\b", text, re.I)
            method = (m.group(1).upper() if m else "GET")
        if not path:
            m = re.search(r"https?://[^'\"\s)]+", text)
            if m:
                url = m.group(0)
                if url.startswith(base):
                    path = url[len(base):] or "/"
                else:
                    path = url
            else:
                m = re.search(r"['\"](/(?:api/)?[A-Za-z0-9_./{}:-]+)['\"]", text)
                path = m.group(1) if m else "/"
        title = sc.get("title") or f"API scenario {idx+1}"
        scenarios.append({
            "id": sc.get("id") or f"API-{idx+1:03d}",
            "title": title,
            "method": method,
            "path": path,
            "expected_status": int(expected_status) if str(expected_status).isdigit() else 200,
            "body": body,
            "headers": headers,
            "expected_result": sc.get("expected_result") or sc.get("expected") or "API response should satisfy contract and status expectations.",
        })
    return scenarios or [{"id": "API-001", "title": "API health check", "method": "GET", "path": "/", "expected_status": 200, "body": None, "headers": {}, "expected_result": "API health check passes."}]


def _write_playwright_api_framework(feature: str, testcase: dict[str, Any], base_url: str) -> dict[str, Any]:
    root = GENERATED_API_PLAYWRIGHT_DIR
    (root / "tests" / "generated").mkdir(parents=True, exist_ok=True)
    (root / "utils").mkdir(parents=True, exist_ok=True)
    (root / "fixtures").mkdir(parents=True, exist_ok=True)
    (root / "testData").mkdir(parents=True, exist_ok=True)
    scenarios = _infer_api_scenarios(testcase, base_url=base_url)
    base = (base_url or testcase.get("start_url") or "https://example.com").rstrip("/")
    package = {
        "name": "generated-api-playwright-enterprise",
        "version": "1.0.0",
        "private": True,
        "scripts": {
            "test:api": "playwright test -c playwright.api.config.ts",
            "test:api:headed": "playwright test -c playwright.api.config.ts --headed",
            "typecheck": "tsc --noEmit",
            "report": "playwright show-report reports/html",
        },
        "devDependencies": {"@playwright/test": "latest", "typescript": "latest", "ts-node": "latest"},
    }
    (root / "package.json").write_text(json.dumps(package, indent=2) + "\n", encoding="utf-8")
    (root / "tsconfig.json").write_text(json.dumps({"compilerOptions": {"target": "ES2022", "module": "CommonJS", "moduleResolution": "node", "strict": True, "types": ["node", "@playwright/test"], "esModuleInterop": True, "resolveJsonModule": True}, "include": ["**/*.ts", "**/*.json"]}, indent=2) + "\n", encoding="utf-8")
    (root / "playwright.api.config.ts").write_text("""import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './tests',
  timeout: 30_000,
  expect: { timeout: 10_000 },
  retries: process.env.CI ? 1 : 0,
  reporter: [
    ['html', { outputFolder: 'reports/html', open: 'never' }],
    ['json', { outputFile: 'reports/api-results.json' }],
    ['junit', { outputFile: 'reports/api-results.xml' }]
  ],
  use: {
    baseURL: process.env.API_BASE_URL,
    extraHTTPHeaders: process.env.API_AUTH_TOKEN ? { Authorization: `Bearer ${process.env.API_AUTH_TOKEN}` } : {},
    trace: 'retain-on-failure',
  },
});
""", encoding="utf-8")
    (root / "utils" / "apiClient.ts").write_text(r"""import { APIRequestContext, APIResponse, TestInfo } from '@playwright/test';

export type ApiRequestOptions = { headers?: Record<string, string>; data?: unknown; params?: Record<string, string | number | boolean> };

export class EnterpriseApiClient {
  constructor(private request: APIRequestContext, private baseUrl: string) {}

  url(path: string): string {
    if (/^https?:\/\//i.test(path)) return path;
    return `${this.baseUrl.replace(/\/$/, '')}/${path.replace(/^\//, '')}`;
  }

  async call(method: string, path: string, options: ApiRequestOptions = {}): Promise<APIResponse> {
    const url = this.url(path);
    const normalized = method.toUpperCase();
    if (normalized === 'GET') return this.request.get(url, options);
    if (normalized === 'POST') return this.request.post(url, options);
    if (normalized === 'PUT') return this.request.put(url, options);
    if (normalized === 'PATCH') return this.request.patch(url, options);
    if (normalized === 'DELETE') return this.request.delete(url, options);
    throw new Error(`[API_FRAMEWORK:UNSUPPORTED_METHOD] ${method}`);
  }

  async attachEvidence(testInfo: TestInfo, response: APIResponse, label: string): Promise<void> {
    const headers = await response.headers();
    let body = '';
    try { body = await response.text(); } catch { body = '<body unavailable>'; }
    await testInfo.attach(`${label}-status.txt`, { body: String(response.status()), contentType: 'text/plain' });
    await testInfo.attach(`${label}-headers.json`, { body: JSON.stringify(headers, null, 2), contentType: 'application/json' });
    await testInfo.attach(`${label}-body.txt`, { body: body.slice(0, 20000), contentType: 'text/plain' });
  }
}
""", encoding="utf-8")
    (root / "utils" / "apiAssertions.ts").write_text("""import { expect, APIResponse } from '@playwright/test';

export async function expectHealthyStatus(response: APIResponse, expectedStatus: number, operation: string) {
  const status = response.status();
  if ([401, 403].includes(status)) throw new Error(`[RCA:API_AUTHORIZATION] ${operation} returned ${status}. Check token, role, session, VPN/VDI or environment.`);
  if (status >= 500) throw new Error(`[RCA:API_SERVER_OR_ENVIRONMENT] ${operation} returned ${status}. Do not self-heal tests until backend/environment is checked.`);
  expect(status, `${operation}: HTTP status`).toBe(expectedStatus);
}

export async function expectJsonIfJson(response: APIResponse, operation: string) {
  const contentType = response.headers()['content-type'] || '';
  if (contentType.includes('application/json')) {
    const body = await response.json();
    expect(body, `${operation}: JSON body`).toBeTruthy();
    return body;
  }
  return null;
}
""", encoding="utf-8")
    data_file = root / "testData" / f"{_safe_name(feature)}.api.scenarios.json"
    data_file.write_text(json.dumps({"base_url": base, "scenarios": scenarios}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    spec = root / "tests" / "generated" / f"{_safe_name(feature)}.api.spec.ts"
    spec.write_text(f"""import {{ test }} from '@playwright/test';
import {{ EnterpriseApiClient }} from '../../utils/apiClient';
import {{ expectHealthyStatus, expectJsonIfJson }} from '../../utils/apiAssertions';
import scenarios from '../../testData/{_safe_name(feature)}.api.scenarios.json';

test.describe('{_h(feature)} API generated suite', () => {{
  for (const scenario of scenarios.scenarios) {{
    test(`${{scenario.id}} - ${{scenario.title}}`, async ({{ request }}, testInfo) => {{
      const baseUrl = process.env.API_BASE_URL || scenarios.base_url || '{base}';
      const client = new EnterpriseApiClient(request, baseUrl);
      const response = await client.call(scenario.method, scenario.path, {{ headers: scenario.headers || {{}}, data: scenario.body || undefined }});
      await client.attachEvidence(testInfo, response, scenario.id);
      await expectHealthyStatus(response, scenario.expected_status, `${{scenario.method}} ${{scenario.path}}`);
      await expectJsonIfJson(response, `${{scenario.method}} ${{scenario.path}}`);
    }});
  }}
}});
""", encoding="utf-8")
    return {"root": str(root), "files": [str(p) for p in [root / "package.json", root / "playwright.api.config.ts", root / "utils" / "apiClient.ts", root / "utils" / "apiAssertions.ts", data_file, spec]], "scenario_count": len(scenarios)}


def _write_restassured_api_framework(feature: str, testcase: dict[str, Any], base_url: str) -> dict[str, Any]:
    root = GENERATED_API_RESTASSURED_DIR
    support = root / "src" / "test" / "java" / "com" / "aiqa" / "api" / "support"
    tests = root / "src" / "test" / "java" / "com" / "aiqa" / "api" / "generated"
    resources = root / "src" / "test" / "resources" / "testData"
    for p in [support, tests, resources]:
        p.mkdir(parents=True, exist_ok=True)
    scenarios = _infer_api_scenarios(testcase, base_url=base_url)
    base = (base_url or testcase.get("start_url") or "https://example.com").rstrip("/")
    (root / "pom.xml").write_text("""<project xmlns="http://maven.apache.org/POM/4.0.0" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:schemaLocation="http://maven.apache.org/POM/4.0.0 https://maven.apache.org/xsd/maven-4.0.0.xsd">
  <modelVersion>4.0.0</modelVersion>
  <groupId>com.aiqa</groupId>
  <artifactId>generated-api-restassured-enterprise</artifactId>
  <version>1.0.0</version>
  <properties><maven.compiler.source>17</maven.compiler.source><maven.compiler.target>17</maven.compiler.target><project.build.sourceEncoding>UTF-8</project.build.sourceEncoding></properties>
  <dependencies>
    <dependency><groupId>io.rest-assured</groupId><artifactId>rest-assured</artifactId><version>5.5.0</version><scope>test</scope></dependency>
    <dependency><groupId>org.junit.jupiter</groupId><artifactId>junit-jupiter</artifactId><version>5.10.3</version><scope>test</scope></dependency>
    <dependency><groupId>com.fasterxml.jackson.core</groupId><artifactId>jackson-databind</artifactId><version>2.17.2</version><scope>test</scope></dependency>
    <dependency><groupId>org.slf4j</groupId><artifactId>slf4j-simple</artifactId><version>2.0.13</version><scope>test</scope></dependency>
  </dependencies>
  <build><plugins><plugin><groupId>org.apache.maven.plugins</groupId><artifactId>maven-surefire-plugin</artifactId><version>3.3.1</version><configuration><useModulePath>false</useModulePath></configuration></plugin></plugins></build>
</project>
""", encoding="utf-8")
    (support / "EnterpriseApiClient.java").write_text("""package com.aiqa.api.support;

import io.restassured.RestAssured;
import io.restassured.response.Response;
import java.util.Map;

public class EnterpriseApiClient {
  private final String baseUrl;
  public EnterpriseApiClient(String baseUrl) { this.baseUrl = baseUrl.replaceAll("/$", ""); }
  public Response call(String method, String path, Map<String, String> headers, Object body) {
    String url = path.matches("^https?://.*") ? path : baseUrl + "/" + path.replaceFirst("^/", "");
    var req = RestAssured.given().relaxedHTTPSValidation().headers(headers == null ? Map.of() : headers);
    String token = System.getenv("API_AUTH_TOKEN");
    if (token != null && !token.isBlank()) req.header("Authorization", "Bearer " + token);
    if (body != null) req.contentType("application/json").body(body);
    return switch (method.toUpperCase()) {
      case "GET" -> req.get(url);
      case "POST" -> req.post(url);
      case "PUT" -> req.put(url);
      case "PATCH" -> req.patch(url);
      case "DELETE" -> req.delete(url);
      default -> throw new IllegalArgumentException("Unsupported API method: " + method);
    };
  }
}
""", encoding="utf-8")
    (support / "ApiAssertions.java").write_text("""package com.aiqa.api.support;

import io.restassured.response.Response;
import static org.junit.jupiter.api.Assertions.*;

public class ApiAssertions {
  public static void expectHealthyStatus(Response response, int expected, String operation) {
    int status = response.statusCode();
    if (status == 401 || status == 403) fail("[RCA:API_AUTHORIZATION] " + operation + " returned " + status + ". Check token, role, session, VPN/VDI or environment.");
    if (status >= 500) fail("[RCA:API_SERVER_OR_ENVIRONMENT] " + operation + " returned " + status + ". Do not self-heal tests until backend/environment is checked.");
    assertEquals(expected, status, operation + " HTTP status");
  }
}
""", encoding="utf-8")
    data = resources / f"{_safe_name(feature)}.api.scenarios.json"
    data.write_text(json.dumps({"base_url": base, "scenarios": scenarios}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    class_name = _class_name(feature)
    methods = []
    for i, sc in enumerate(scenarios):
        method_name = re.sub(r"[^a-zA-Z0-9]+", "_", sc["id"]).strip("_") or f"api_{i+1}"
        if method_name[0].isdigit(): method_name = "api_" + method_name
        headers = sc.get("headers") or {}
        body_java = "null" if sc.get("body") in (None, "") else "\"" + json.dumps(sc.get("body"), ensure_ascii=False).replace('"', '\\"') + "\""
        map_entries = ", ".join([json.dumps(str(k), ensure_ascii=False) + ", " + json.dumps(str(v), ensure_ascii=False) for k, v in headers.items()])
        methods.append(f"""
  @Test
  void {method_name}() {{
    EnterpriseApiClient client = new EnterpriseApiClient(System.getenv().getOrDefault("API_BASE_URL", BASE_URL));
    Response response = client.call("{sc['method']}", "{sc['path']}", Map.of({map_entries}), {body_java});
    ApiAssertions.expectHealthyStatus(response, {int(sc['expected_status'])}, "{sc['method']} {sc['path']}");
  }}
""")
    (tests / f"{class_name}.java").write_text(f"""package com.aiqa.api.generated;

import com.aiqa.api.support.ApiAssertions;
import com.aiqa.api.support.EnterpriseApiClient;
import io.restassured.response.Response;
import org.junit.jupiter.api.Test;
import java.util.Map;

class {class_name} {{
  private static final String BASE_URL = "{base}";
{''.join(methods)}
}}
""", encoding="utf-8")
    return {"root": str(root), "files": [str(root / "pom.xml"), str(support / "EnterpriseApiClient.java"), str(support / "ApiAssertions.java"), str(data), str(tests / f"{class_name}.java")], "scenario_count": len(scenarios)}


def generate_api_framework(feature: str = "api", source_type: str = "srs", flavor: str = "playwright", base_url: str = "", provider: str = "deterministic", model: str = "llama3") -> dict[str, Any]:
    _ensure_dirs()
    feature = _safe_name(feature)
    flavor = _detect_flavor(Path("."), flavor)
    testcase = _load_testcase(feature, source_type)
    if flavor == "restassured":
        generated = _write_restassured_api_framework(feature, testcase, base_url)
    else:
        generated = _write_playwright_api_framework(feature, testcase, base_url)
    ai_guidance = {"provider": provider, "used": False, "message": "Deterministic enterprise API framework generated. AI can be used in the next RCA/self-healing phase."}
    prompt = f"""You are reviewing a generated enterprise API automation framework.
Feature: {feature}
Flavor: {flavor}
Base URL: {base_url}
Scenario summary: {json.dumps(_infer_api_scenarios(testcase, base_url), ensure_ascii=False)[:4000]}
Return concise risk guidance only. Do not edit files.
"""
    if provider == "codex":
        result = CodexCliProvider(REPO_ROOT).run(prompt)
        ai_guidance = {"provider": "codex", "used": True, "ok": result.ok, "message": (result.stdout if result.ok else result.stderr)[-4000:]}
    elif provider == "ollama":
        result = OllamaProvider(model=model).chat(prompt)
        ai_guidance = {"provider": "ollama", "used": True, "ok": result.ok, "message": (result.text if result.ok else result.error)[-4000:]}
    report = {"ok": True, "stage": "api_framework_generated", "feature": feature, "source_type": source_type, "flavor": flavor, "generated": generated, "ai_guidance": ai_guidance, "message": f"Generated enterprise API automation framework in {flavor} flavor."}
    _write_api_overview_html(report)
    return report


def _write_api_overview_html(report: dict[str, Any]) -> None:
    _ensure_dirs()
    html = f"""<!doctype html><html><head><meta charset='utf-8'><title>API Automation Framework</title><style>body{{font-family:Segoe UI,Arial,sans-serif;margin:24px;background:#f8fafc;color:#0f172a}}.card{{background:white;border:1px solid #dbe3ef;border-radius:14px;padding:16px;margin:14px 0}}pre{{white-space:pre-wrap;background:#0f172a;color:#dbeafe;border-radius:10px;padding:14px}}</style></head><body><h1>API Automation Framework</h1><section class='card'><h2>Summary</h2><p>{_h(report.get('message'))}</p><pre>{_h(json.dumps(report, indent=2, ensure_ascii=False))}</pre></section></body></html>"""
    (API_REPORTS_DIR / "api-framework-overview.html").write_text(html, encoding="utf-8")


def analyze_api_framework(framework_path: str = "", flavor: str = "auto", base_url: str = "") -> dict[str, Any]:
    _ensure_dirs()
    root = Path(framework_path).expanduser().resolve() if framework_path else GENERATED_API_PLAYWRIGHT_DIR
    if not root.exists():
        return {"ok": False, "message": f"API framework path does not exist: {root}"}
    detected = _detect_flavor(root, flavor)
    files = [p for p in root.rglob("*") if p.is_file() and not any(part in {"node_modules", ".git", "target", "build", "reports", "playwright-report"} for part in p.parts)]
    ext_counts = Counter(p.suffix.lower() or "<none>" for p in files)
    endpoint_counter = Counter()
    auth_hints, db_hints, data_files, test_files, support_files = [], [], [], [], []
    for p in files[:4000]:
        rel = _rel(p, root)
        low_rel = rel.lower()
        text = _safe_read(p, limit=120_000)
        low = text.lower()
        if low_rel.endswith((".spec.ts", ".test.ts", ".spec.js", ".test.js", "test.java")) or "/src/test/" in f"/{low_rel}":
            test_files.append(rel)
        if any(x in low_rel for x in ["utils", "support", "client", "fixture", "base"]):
            support_files.append(rel)
        if any(x in low_rel for x in ["testdata", "resources", "fixtures", ".env", "data"]):
            data_files.append(rel)
        for endpoint in re.findall(r"https?://[^'\"\s)]+|['\"](/(?:api/)?[A-Za-z0-9_./{}:-]+)['\"]", text):
            endpoint_counter[str(endpoint).strip("'\"")[:220]] += 1
        if any(x in low for x in ["authorization", "bearer", "api_auth_token", "client_secret", "oauth", "jwt", "basic auth"]):
            auth_hints.append(rel)
        if any(x in low for x in ["database_url", "db_host", "postgres", "mysql", "mongo", "jdbc:", "datasource"]):
            db_hints.append(rel)
    pkg = {}
    if (root / "package.json").exists():
        try: pkg = json.loads(_safe_read(root / "package.json"))
        except Exception: pkg = {}
    pom = _safe_read(root / "pom.xml", limit=80_000) if (root / "pom.xml").exists() else ""
    rag = build_framework_rag_index(root, inventory={"api_framework": True, "flavor": detected})
    report = {
        "ok": True,
        "stage": "api_framework_analyzed",
        "framework_path": str(root),
        "flavor": detected,
        "base_url": base_url,
        "file_count": len(files),
        "extension_counts": dict(ext_counts),
        "test_files_sample": test_files[:120],
        "support_files_sample": support_files[:120],
        "test_data_files_sample": data_files[:120],
        "endpoint_samples": [e for e, _ in endpoint_counter.most_common(120)],
        "auth_hint_files": sorted(set(auth_hints))[:80],
        "db_hint_files": sorted(set(db_hints))[:80],
        "technology_stack": {
            "package_scripts": pkg.get("scripts", {}) if isinstance(pkg, dict) else {},
            "maven_detected": bool(pom),
            "rest_assured_detected": "rest-assured" in pom.lower(),
            "playwright_detected": "@playwright/test" in json.dumps(pkg).lower() or any("playwright" in f.lower() for f in test_files),
        },
        "rag_index": rag,
        "rules": [
            "Classify 401/403 as auth/session/role/VPN unless test evidence proves request construction is wrong.",
            "Classify 5xx as backend/environment/product unless test evidence proves bad test data or wrong endpoint.",
            "Do not weaken contract assertions or status expectations without human approval.",
            "Prefer reusable API clients, request builders, schemas, fixtures and testData over duplicated inline calls.",
        ],
    }
    API_INTELLIGENCE_JSON.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    _write_api_intelligence_html(report)
    return report


def _write_api_intelligence_html(report: dict[str, Any]) -> None:
    html = f"""<!doctype html><html><head><meta charset='utf-8'><title>API Framework Intelligence</title><style>body{{font-family:Segoe UI,Arial,sans-serif;margin:24px;background:#f8fafc;color:#0f172a}}.card{{background:white;border:1px solid #dbe3ef;border-radius:14px;padding:16px;margin:14px 0}}pre{{white-space:pre-wrap;background:#0f172a;color:#dbeafe;border-radius:10px;padding:14px;overflow:auto}}</style></head><body><h1>API Framework Intelligence</h1><section class='card'><pre>{_h(json.dumps(report, indent=2, ensure_ascii=False))}</pre></section></body></html>"""
    API_INTELLIGENCE_HTML.write_text(html, encoding="utf-8")


def _framework_root_for_generated(flavor: str) -> Path:
    return GENERATED_API_RESTASSURED_DIR if _detect_flavor(Path("."), flavor) == "restassured" else GENERATED_API_PLAYWRIGHT_DIR


def execute_api_framework(framework_path: str = "", flavor: str = "auto", base_url: str = "", test_command: str = "", targets: str = "", auto_install: bool = True, use_docker: bool = False) -> dict[str, Any]:
    _ensure_dirs()
    root = Path(framework_path).expanduser().resolve() if framework_path else _framework_root_for_generated(flavor)
    if not root.exists():
        return {"ok": False, "message": f"API framework path does not exist: {root}"}
    detected = _detect_flavor(root, flavor)
    env = {"API_BASE_URL": base_url} if base_url else {}
    install = None
    if use_docker:
        # Docker-managed runtime avoids host Java/Maven/Node dependencies and is the recommended enterprise mode.
        run = execute_api_framework_in_docker(str(root), detected, base_url=base_url, targets=targets, test_command=test_command, timeout=1500)
    else:
        if auto_install:
            if detected == "playwright" and (root / "package.json").exists() and not (root / "node_modules").exists():
                install = _run("npm install", cwd=root, timeout=600, env=env)
            # Maven downloads dependencies during mvn test; no separate install needed.
        cmd = test_command.strip()
        if not cmd:
            if detected == "restassured":
                cmd = "mvn test"
            else:
                target_arg = " ".join([x.strip() for x in re.split(r"[\n,]+", targets or "") if x.strip()])
                config = "-c playwright.api.config.ts" if (root / "playwright.api.config.ts").exists() else ""
                cmd = f"npx --no-install playwright test {config} {target_arg}".strip()
        run = _run(cmd, cwd=root, timeout=900, env=env)
    inventory = _collect_api_failures(root, detected, run)
    _write_api_consolidated_report({"root": str(root), "flavor": detected, "run": run, "failed_inventory": inventory})
    return {
        "ok": run.get("ok", False),
        "stage": "api_framework_execution_completed",
        "framework_path": str(root),
        "flavor": detected,
        "install": install,
        "execution": run,
        "docker_runtime": bool(use_docker),
        "failed_inventory": inventory,
        "api_report_url": "/artifacts/reports/api-framework/api-consolidated-report.html",
        "message": "API framework execution completed in Docker runtime." if use_docker else "API framework execution completed. RCA can analyze failed API tests only.",
    }


def _collect_api_failures(root: Path, flavor: str, run: dict[str, Any]) -> dict[str, Any]:
    failed = []
    evidence_files = []
    text = (run.get("stdout") or "") + "\n" + (run.get("stderr") or "")
    if flavor == "playwright":
        result_json = root / "reports" / "api-results.json"
        if result_json.exists():
            evidence_files.append(str(result_json))
            try:
                data = json.loads(_safe_read(result_json, limit=2_000_000))
                for suite in data.get("suites", []):
                    for spec in suite.get("specs", []):
                        for test in spec.get("tests", []):
                            for result in test.get("results", []):
                                if result.get("status") not in {"passed", "skipped"}:
                                    failed.append({"title": spec.get("title") or test.get("title"), "file": spec.get("file"), "status": result.get("status"), "error": json.dumps(result.get("error") or result.get("errors") or {}, ensure_ascii=False)[:4000]})
            except Exception:
                pass
    else:
        for p in (root / "target" / "surefire-reports").glob("*.txt") if (root / "target" / "surefire-reports").exists() else []:
            evidence_files.append(str(p))
            t = _safe_read(p, limit=120_000)
            if "FAILURE" in t or "ERROR" in t or "Failures:" in t or "Errors:" in t:
                failed.append({"title": p.stem, "file": str(p), "status": "failed", "error": t[-4000:]})
    if not failed and not run.get("ok"):
        # Fallback parser from command output.
        failures = re.findall(r"(?im)(?:FAIL|ERROR|Timeout|AssertionError|Expected.*but|status.*(?:401|403|404|500).*)", text)
        failed.append({"title": "api_command_failed", "file": "command-output", "status": "failed", "error": "\n".join(failures[:20]) or text[-4000:]})
    inventory = {"ok": True, "generated_at": datetime.now().isoformat(timespec="seconds"), "framework_path": str(root), "flavor": flavor, "failed_count": len(failed), "failed_tests": failed, "evidence_files": evidence_files, "raw_output_tail": text[-8000:]}
    API_FAILED_INVENTORY.write_text(json.dumps(inventory, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return inventory


def read_api_failed_inventory() -> dict[str, Any]:
    if API_FAILED_INVENTORY.exists():
        try: return json.loads(API_FAILED_INVENTORY.read_text(encoding="utf-8", errors="replace"))
        except Exception as exc: return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    return {"ok": True, "failed_count": 0, "failed_tests": [], "message": "No API failed inventory exists yet. Run API framework execution first."}


def _classify_api_failure(text: str) -> dict[str, Any]:
    low = text.lower()
    category = "UNKNOWN_API_FAILURE"
    healable = False
    risk = "medium"
    strategy = "Collect API response evidence and review manually."
    if any(x in low for x in ["401", "403", "unauthorized", "forbidden", "auth", "token"]):
        category = "API_AUTHORIZATION_OR_SESSION"; healable = False; risk = "high"; strategy = "Check API_AUTH_TOKEN, role, login/session fixture, VPN/VDI and environment. Do not change assertions."
    elif any(x in low for x in ["500", "502", "503", "504", "server error", "econnrefused", "enotfound", "timeout"]):
        category = "API_SERVER_ENVIRONMENT_OR_VPN"; healable = False; risk = "high"; strategy = "Check backend health, service availability, proxy/VPN, VDI route and test environment before patching."
    elif any(x in low for x in ["404", "not found"]):
        category = "API_ENDPOINT_OR_ROUTE_DRIFT"; healable = True; risk = "medium"; strategy = "Verify endpoint contract/OpenAPI/Jira requirement. Patch endpoint mapping only if evidence proves route changed."
    elif any(x in low for x in ["json", "schema", "contract", "deserialize", "jackson", "zod"]):
        category = "API_SCHEMA_OR_CONTRACT_DRIFT"; healable = False; risk = "high"; strategy = "Run contract drift review. Do not update schema/assertions automatically unless change is approved."
    elif any(x in low for x in ["expected", "assertion", "assert", "tobe", "equals"]):
        category = "API_ASSERTION_DRIFT_OR_PRODUCT_REGRESSION"; healable = False; risk = "high"; strategy = "Human approval required before changing status/body/schema assertions."
    elif any(x in low for x in ["testdata", "payload", "body", "invalid request", "400", "bad request"]):
        category = "API_TEST_DATA_OR_PAYLOAD"; healable = True; risk = "medium"; strategy = "Patch request builder/testData only if evidence proves payload is stale or seed data missing."
    elif any(x in low for x in ["cannot find module", "compilation", "tsc", "maven", "surefire", "symbol not found"]):
        category = "API_FRAMEWORK_COMPILATION"; healable = True; risk = "low"; strategy = "Patch imports, dependencies, client utilities or generated test code without weakening validations."
    return {"category": category, "healable": healable, "risk": risk, "strategy": strategy}


def analyze_api_failure(framework_path: str = "", flavor: str = "auto", provider: str = "deterministic", model: str = "llama3", base_url: str = "") -> dict[str, Any]:
    _ensure_dirs()
    inv = read_api_failed_inventory()
    root = Path(framework_path).expanduser().resolve() if framework_path else Path(inv.get("framework_path") or _framework_root_for_generated(flavor))
    detected = _detect_flavor(root, flavor)
    intel = analyze_api_framework(str(root), detected, base_url) if root.exists() else {"ok": False}
    failures = inv.get("failed_tests") or []
    classified = []
    all_text = json.dumps(inv, ensure_ascii=False)
    for f in failures:
        cls = _classify_api_failure(json.dumps(f, ensure_ascii=False))
        classified.append({**f, "rca": cls})
    auto_healable = [f for f in classified if f.get("rca", {}).get("healable")]
    blocked = [f for f in classified if not f.get("rca", {}).get("healable")]
    rag = query_framework_context("api client request response auth token schema payload status endpoint testData fixtures", top_k=12)
    report = {
        "ok": True,
        "stage": "api_rca_completed",
        "framework_path": str(root),
        "flavor": detected,
        "failed_count": len(failures),
        "classified_failures": classified,
        "auto_healable_count": len(auto_healable),
        "manual_review_count": len(blocked),
        "framework_intelligence_summary": intel,
        "rag_context": rag,
        "plain_english_summary": _api_plain_summary(classified),
        "policy": {
            "allowed_patch_dirs": API_ALLOWED_PATCH_DIRS.get(detected, []),
            "blocked_patterns": API_BLOCKED_PATTERNS,
            "status_assertion_changes_require_manual_review": True,
            "schema_contract_changes_require_manual_review": True,
            "failed_only_rerun_required": True,
        },
        "message": "API RCA completed. Only healable framework/test-data/request-builder issues should be patched automatically.",
    }
    API_RCA_JSON.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    _write_api_rca_html(report)
    return report


def _api_plain_summary(classified: list[dict[str, Any]]) -> list[str]:
    if not classified:
        return ["No failed API tests were found. Run API execution first if you expected failures."]
    out = []
    for f in classified[:20]:
        r = f.get("rca", {})
        out.append(f"{f.get('title')}: {r.get('category')} - {r.get('strategy')}")
    return out


def _write_api_rca_html(report: dict[str, Any]) -> None:
    items = "".join(f"<li>{_h(x)}</li>" for x in report.get("plain_english_summary", []))
    html = f"""<!doctype html><html><head><meta charset='utf-8'><title>API RCA Report</title><style>body{{font-family:Segoe UI,Arial,sans-serif;margin:24px;background:#f8fafc;color:#0f172a}}.card{{background:white;border:1px solid #dbe3ef;border-radius:14px;padding:16px;margin:14px 0}}pre{{white-space:pre-wrap;background:#0f172a;color:#dbeafe;border-radius:10px;padding:14px;overflow:auto}}</style></head><body><h1>API RCA Report</h1><section class='card'><h2>Plain English Summary</h2><ul>{items}</ul></section><section class='card'><h2>Structured RCA</h2><pre>{_h(json.dumps(report, indent=2, ensure_ascii=False))}</pre></section></body></html>"""
    API_RCA_HTML.write_text(html, encoding="utf-8")


def _list_patch_files(root: Path, flavor: str) -> list[Path]:
    suffixes = {".ts", ".js", ".json"} if flavor == "playwright" else {".java", ".xml", ".json", ".properties"}
    files = []
    allowed = API_ALLOWED_PATCH_DIRS.get(flavor, [])
    for p in root.rglob("*"):
        if not p.is_file() or p.suffix.lower() not in suffixes:
            continue
        rel = _rel(p, root)
        if any(rel.startswith(a) or rel == a for a in allowed):
            files.append(p)
    return files[:80]


def _diff_backup(root: Path, backups: dict[str, str]) -> dict[str, Any]:
    changed = []
    violations = []
    for rel, before in backups.items():
        p = root / rel
        after = _safe_read(p, limit=300_000)
        if after != before:
            changed.append(rel)
            low = after.lower()
            for pat in API_BLOCKED_PATTERNS:
                if pat.lower() in low and pat.lower() not in before.lower():
                    violations.append({"file": rel, "pattern": pat})
            # crude guard for assertion/status weakening
            if re.search(r"expected_status\s*[:=]\s*[0-9]+", before) and after.count("expected_status") < before.count("expected_status"):
                violations.append({"file": rel, "pattern": "expected_status_removed_or_weakened"})
    return {"changed_files": changed, "violations": violations, "ok": not violations}


def self_heal_api_framework(framework_path: str = "", flavor: str = "auto", provider: str = "codex", model: str = "llama3", base_url: str = "", apply_patch: bool = False) -> dict[str, Any]:
    _ensure_dirs()
    inv = read_api_failed_inventory()
    root = Path(framework_path).expanduser().resolve() if framework_path else Path(inv.get("framework_path") or _framework_root_for_generated(flavor))
    if not root.exists():
        return {"ok": False, "message": f"API framework path does not exist: {root}"}
    detected = _detect_flavor(root, flavor)
    rca = analyze_api_failure(str(root), detected, provider="deterministic", model=model, base_url=base_url)
    healable = [f for f in rca.get("classified_failures", []) if f.get("rca", {}).get("healable")]
    if not healable:
        report = {"ok": False, "stage": "api_self_healing_blocked", "framework_path": str(root), "flavor": detected, "rca": rca, "requires_manual_review": True, "message": "API self-healing blocked. Failures look like auth/environment/server/schema/assertion issues, not safe script fixes."}
        API_HEALING_JSON.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        _write_api_healing_html(report)
        return report
    patch_files = _list_patch_files(root, detected)
    excerpts = { _rel(p, root): _safe_read(p, limit=40_000) for p in patch_files[:25] }
    prompt = f"""You are an enterprise API automation self-healing agent.
Follow staged RCA reasoning internally, but output only a concise patch summary.
Framework flavor: {detected}
Root: {root}
Base URL: {base_url}
RCA: {json.dumps(rca.get('classified_failures', []), ensure_ascii=False)[:12000]}
Relevant files: {json.dumps(excerpts, ensure_ascii=False)[:30000]}
Rules:
- Patch only failed API test dependencies.
- Prefer reusable API client/request builder/schema/testData layers.
- Do not weaken status/body/schema assertions.
- Do not skip/disable tests.
- Do not hide 401/403/5xx product/environment failures.
- Do not change business expected outcomes.
- Keep the patch minimal.
"""
    report: dict[str, Any] = {"ok": True, "stage": "api_self_healing_proposal_created", "framework_path": str(root), "flavor": detected, "rca": rca, "healable_failures": healable, "apply_patch": apply_patch, "message": "API self-healing proposal created. No files changed."}
    if not apply_patch:
        report["proposal"] = {"provider": provider, "recommended_files": list(excerpts)[:20], "instructions": "Review RCA. Apply patch only for request-builder/testData/endpoint mapping/compilation issues. Assertion/schema drift requires approval."}
        if provider == "codex":
            res = CodexCliProvider(REPO_ROOT).run(prompt + "\nReturn a JSON patch proposal only; do not edit files.")
            report["ai_proposal"] = {"ok": res.ok, "message": (res.stdout if res.ok else res.stderr)[-6000:]}
        elif provider == "ollama":
            res = OllamaProvider(model=model).chat(prompt + "\nReturn a JSON patch proposal only; do not edit files.")
            report["ai_proposal"] = {"ok": res.ok, "message": (res.text if res.ok else res.error)[-6000:]}
        API_HEALING_JSON.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        _write_api_healing_html(report)
        return report
    if provider != "codex":
        report.update({"ok": False, "stage": "api_self_healing_apply_blocked", "message": "Apply mode requires Codex CLI so file edits can be guarded and reviewed. Use propose mode for deterministic/Ollama guidance."})
        API_HEALING_JSON.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        _write_api_healing_html(report)
        return report
    backups = {_rel(p, root): _safe_read(p, limit=300_000) for p in patch_files}
    backup_dir = API_CACHE_DIR / "backups" / datetime.now().strftime("%Y%m%d-%H%M%S")
    for rel, text in backups.items():
        dest = backup_dir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text, encoding="utf-8")
    res = CodexCliProvider(root).run(prompt + "\nApply the minimal patch directly in the repository. Do not print unrelated explanations.")
    diff = _diff_backup(root, backups)
    if not res.ok or not diff.get("ok"):
        # Restore all backed up files.
        for rel, text in backups.items():
            (root / rel).write_text(text, encoding="utf-8")
        report.update({"ok": False, "stage": "api_self_healing_patch_reverted", "codex": {"ok": res.ok, "message": (res.stdout if res.ok else res.stderr)[-6000:]}, "policy_diff": diff, "backup_dir": str(backup_dir), "message": "API patch was reverted because Codex failed or policy violations were detected."})
    else:
        report.update({"ok": True, "stage": "api_self_healing_patch_applied", "codex": {"ok": res.ok, "message": res.stdout[-6000:]}, "policy_diff": diff, "backup_dir": str(backup_dir), "message": "API patch applied under policy. Rerun failed API tests only or targeted command next."})
    API_HEALING_JSON.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    _write_api_healing_html(report)
    return report


def _write_api_healing_html(report: dict[str, Any]) -> None:
    html = f"""<!doctype html><html><head><meta charset='utf-8'><title>API Self-Healing Report</title><style>body{{font-family:Segoe UI,Arial,sans-serif;margin:24px;background:#f8fafc;color:#0f172a}}.card{{background:white;border:1px solid #dbe3ef;border-radius:14px;padding:16px;margin:14px 0}}pre{{white-space:pre-wrap;background:#0f172a;color:#dbeafe;border-radius:10px;padding:14px;overflow:auto}}</style></head><body><h1>API Self-Healing Report</h1><section class='card'><p>{_h(report.get('message'))}</p><pre>{_h(json.dumps(report, indent=2, ensure_ascii=False))}</pre></section></body></html>"""
    API_HEALING_HTML.write_text(html, encoding="utf-8")


def _write_api_consolidated_report(report: dict[str, Any]) -> None:
    inv = report.get("failed_inventory", {})
    failed = inv.get("failed_tests", [])
    rows = "".join(f"<tr><td>{_h(f.get('title'))}</td><td>{_h(f.get('file'))}</td><td>{_h(f.get('status'))}</td><td><pre>{_h(f.get('error'))}</pre></td></tr>" for f in failed)
    if not rows:
        rows = "<tr><td colspan='4'>No failed API tests detected.</td></tr>"
    html = f"""<!doctype html><html><head><meta charset='utf-8'><title>API Execution Report</title><style>body{{font-family:Segoe UI,Arial,sans-serif;margin:24px;background:#f8fafc;color:#0f172a}}table{{border-collapse:collapse;width:100%;background:white}}th,td{{border:1px solid #dbe3ef;padding:8px;vertical-align:top}}th{{background:#eff6ff}}pre{{white-space:pre-wrap;max-height:220px;overflow:auto}}</style></head><body><h1>API Execution Report</h1><p>Framework: <code>{_h(report.get('root'))}</code> | Flavor: <b>{_h(report.get('flavor'))}</b> | Status: <b>{'PASSED' if report.get('run',{}).get('ok') else 'FAILED'}</b></p><table><thead><tr><th>Test</th><th>File</th><th>Status</th><th>Error Evidence</th></tr></thead><tbody>{rows}</tbody></table></body></html>"""
    API_CONSOLIDATED_HTML.write_text(html, encoding="utf-8")


def search_api_framework_rag(query: str, top_k: int = 10) -> dict[str, Any]:
    return query_framework_context(query or "api request response schema auth endpoint payload testData", top_k=top_k)
