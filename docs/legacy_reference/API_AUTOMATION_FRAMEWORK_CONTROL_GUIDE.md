# API Automation Framework Control Guide

This build adds API automation as a parallel capability beside the existing web Playwright pipeline. Existing web automation, Existing Framework Control, GUI-first launcher, RCA, self-healing, RAG intelligence and selector health remain intact.

## What is supported

The API layer supports two enterprise framework flavours:

1. **Playwright API automation in TypeScript/JavaScript**
   - Generated folder: `generated-api-playwright/`
   - Uses `@playwright/test` request fixtures
   - Generates reusable API client, assertion utility, test data and generated API specs

2. **Rest Assured API automation in Java**
   - Generated folder: `generated-api-restassured/`
   - Uses Maven, JUnit 5 and Rest Assured
   - Generates reusable Java API client, API assertion helper, test data and generated tests

## GUI-first flow

Run only the GUI startup file first:

Windows:

```powershell
START_AI_QA_GUI_WINDOWS.cmd
```

Mac/Linux:

```bash
./START_AI_QA_GUI_MAC.sh
# or
./START_AI_QA_GUI_LINUX.sh
```

Open:

```text
http://127.0.0.1:8080
```

Then open **API Automation** from the left navigation.

## Generate a new API framework from functional testcases

1. Save Project Setup with Application/API base URL.
2. Generate or load functional testcases from SRS/Jira/PDF/Confluence.
3. Open **API Automation**.
4. Select API flavor:
   - `Playwright API - TypeScript / JavaScript`
   - `Rest Assured - Java`
5. Click **Generate API Framework**.

Outputs:

```text
generated-api-playwright/
generated-api-restassured/
generated-playwright/reports/api-framework/api-framework-overview.html
```

## Analyze or index an existing API framework

1. Open **API Automation**.
2. Select `Auto-detect existing framework`, or select a specific flavor.
3. Paste existing API framework root path.
4. Click **Analyze / Index Existing API Framework**.

The system indexes:

- package.json / pom.xml / build.gradle
- Playwright API request specs
- Rest Assured Java tests
- reusable API clients
- fixtures/auth/session helpers
- schemas/contracts
- testData payloads
- endpoint strings
- auth/token hints
- DB/environment/VPN/VDI hints present in repository docs/configs
- RAG chunks for prompt reuse and context awareness

Output:

```text
generated-playwright/reports/api-framework/api-framework-intelligence.html
.qa-cache/existing-framework/rag/framework-chunks.jsonl
```

## Execute API framework

Click **Execute API Framework**.

For generated Playwright API framework, the default command is:

```bash
npx --no-install playwright test -c playwright.api.config.ts
```

For generated Rest Assured framework, the default command is:

```bash
mvn test
```

You can override this in the GUI using **Optional custom API test command**.

Output:

```text
generated-playwright/reports/api-framework/api-consolidated-report.html
.qa-cache/api-framework/failed-api-tests.json
```

## API RCA strategy

Click **Analyze API RCA** after a failure.

The API RCA engine classifies failures into:

- `API_AUTHORIZATION_OR_SESSION`
- `API_SERVER_ENVIRONMENT_OR_VPN`
- `API_ENDPOINT_OR_ROUTE_DRIFT`
- `API_SCHEMA_OR_CONTRACT_DRIFT`
- `API_ASSERTION_DRIFT_OR_PRODUCT_REGRESSION`
- `API_TEST_DATA_OR_PAYLOAD`
- `API_FRAMEWORK_COMPILATION`
- `UNKNOWN_API_FAILURE`

Important guardrail: 401/403/5xx/schema/assertion drift is not blindly healed. It is reported as auth, environment, backend, product or human-review issue unless evidence proves a test framework issue.

Output:

```text
generated-playwright/reports/api-framework/api-root-cause-report.html
```

## API self-healing strategy

Click **Propose API Fix** first. This does not modify files.

Click **Apply API Patch** only after review.

Allowed patch areas:

Playwright API:

```text
tests/
utils/
fixtures/
testData/
playwright.api.config.ts
```

Rest Assured Java:

```text
src/test/
src/main/
pom.xml
build.gradle
testData/
```

Blocked patterns include:

```text
test.skip
test.only
@Disabled
Thread.sleep
waitForTimeout
assertion/status/schema weakening
forcing tests to pass without evidence
```

Output:

```text
generated-playwright/reports/api-framework/api-self-healing-report.html
```

## CLI commands

Generate Playwright API framework:

```bash
python -m qa_pipeline.cli api-framework-generate --feature login --source-type jira --flavor playwright --base-url https://api.example.com
```

Generate Rest Assured API framework:

```bash
python -m qa_pipeline.cli api-framework-generate --feature login --source-type jira --flavor restassured --base-url https://api.example.com
```

Analyze existing API framework:

```bash
python -m qa_pipeline.cli api-framework-analyze --framework-path /path/to/api-framework --flavor auto --base-url https://api.example.com
```

Execute API framework:

```bash
python -m qa_pipeline.cli api-framework-execute --framework-path /path/to/api-framework --flavor auto --base-url https://api.example.com
```

Analyze API RCA:

```bash
python -m qa_pipeline.cli api-framework-rca --framework-path /path/to/api-framework --flavor auto
```

Propose API healing:

```bash
python -m qa_pipeline.cli api-framework-heal --framework-path /path/to/api-framework --flavor auto
```

Apply API healing with Codex:

```bash
python -m qa_pipeline.cli api-framework-heal --framework-path /path/to/api-framework --flavor auto --apply --provider codex
```

## Recommended enterprise workflow

```text
1. Run GUI startup file
2. Start Docker/Codex from GUI
3. Generate/load functional testcases
4. Generate API framework in desired flavor
5. Analyze/index API framework
6. Execute API framework
7. If failed, run API RCA
8. Propose API fix
9. Apply only if policy allows
10. Rerun targeted/failed API tests
11. Review API consolidated report
```

## Important limitation

The system can identify VDI/VM/VPN knowledge only when it exists in the repository, project config, `.env.example`, scripts, README, CI files or comments. For internal applications, document the required VPN/VDI/proxy details so API RCA can avoid misclassifying network failures as test-script defects.

---

## Addendum: Docker-managed Java/Maven/Playwright API runtime

For Rest Assured Java API automation, the preferred enterprise mode is now **Docker runtime from GUI**. This avoids requiring host Java/Maven installation. For Playwright API TS/JS, Docker runtime avoids host Node/npm/Playwright setup.

In the GUI, open **API Automation** and use:

1. **Check API Docker Prereqs**
2. **Pull API Docker Images**
3. Optional: **Start API Mock/Contract Tools**
4. Keep **Run API tests inside Docker runtime** checked
5. **Execute API Framework**

See `docs/API_AUTOMATION_DOCKER_PREREQUISITES_AND_ENTERPRISE_RUNTIME.md` for the complete Docker, VDI/VPN, proxy, MCP/mock-tool, and RCA/self-healing strategy.
