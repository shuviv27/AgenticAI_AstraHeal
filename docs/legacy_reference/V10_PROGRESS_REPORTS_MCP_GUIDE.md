# v10 GUI Progress, Reports, and Playwright MCP Guide

## What changed in v10

- All left-menu sections are clickable.
- All main buttons show click feedback, a progress bar, percent indicator, and stage log.
- Functional testcase generation shows progress while AI provider/deterministic fallback runs.
- `Generate Reusable Playwright`, `Static Review`, and `Execute Generated Test` buttons now show progress and result previews.
- Execution supports both headless and headed mode from the GUI.
- Playwright MCP config is generated and probed before MCP-ready execution.
- Enterprise HTML report is generated at `generated-playwright/reports/enterprise/enterprise-report.html`.
- Native Playwright HTML report remains available at `generated-playwright/reports/html/index.html` after execution.
- Playwright is configured to retain screenshots, videos, and traces on failure.

## Important concept

Playwright MCP is an AI/browser-assist server. This project prepares and checks MCP config so an AI agent or IDE can use it, but deterministic test execution still uses Playwright Test. This is intentional because Playwright Test produces reliable CI output, JSON results, HTML reports, screenshots, videos, and traces.

## Build and run from a clean Windows folder

```powershell
cd C:\
Remove-Item -Recurse -Force C:\AI_QA_V10 -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Path C:\AI_QA_V10 | Out-Null
Expand-Archive "$env:USERPROFILE\Downloads\AdvancedAIAutomation_DynamicWeb_AI_Docker_Build_v10_Progress_MCP_Reports.zip" -DestinationPath C:\AI_QA_V10 -Force
cd C:\AI_QA_V10

chcp 65001
$env:PYTHONUTF8="1"
$env:PYTHONIOENCODING="utf-8"
Set-ExecutionPolicy -Scope Process Bypass

python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install -e .
python -m qa_pipeline.cli doctor

cd generated-playwright
npm install
npx playwright install chromium
npm run build
cd ..
```

## Start Docker stack

Start Docker Desktop first, then run:

```powershell
docker compose -f infra/docker/docker-compose.yml down --remove-orphans
docker compose -f infra/docker/docker-compose.yml pull redis postgres qdrant minio
docker compose -f infra/docker/docker-compose.yml up -d redis postgres qdrant minio
docker compose -f infra/docker/docker-compose.yml ps
```

Optional Ollama container:

```powershell
docker compose -f infra/docker/docker-compose.yml --profile ollama up -d ollama
```

## Configure Codex CLI

```powershell
npm install -g @openai/codex
codex login
# restricted laptop/VDI:
# codex login --device-auth
codex --version
'"Return JSON only: {\"ok\": true}"' | codex exec --skip-git-repo-check --sandbox read-only -
```

Do not store ChatGPT username/password in `.env`.

## Start GUI

```powershell
.\.venv\Scripts\Activate.ps1
.\START_GUI_WINDOWS.ps1
```

Open:

```text
http://127.0.0.1:8080
```

## Recommended GUI flow

1. Dashboard -> Verify prerequisites.
2. Project Setup -> Save project config.
3. Project Setup -> Start Docker + selected AI.
4. Codex/Ollama -> Check Codex/Ollama.
5. Playwright MCP -> Check Playwright MCP.
6. Requirement Input -> Upload SRS/PDF/DOCX or paste text.
7. Requirement Input -> Generate functional testcases.
8. Functional Testcases -> Review testcase JSON.
9. Generated Playwright -> Generate Reusable Playwright.
10. Generated Playwright -> Static Review.
11. Generated Playwright -> Execute Generated Test - Headless or Headed.
12. Reports -> Open enterprise HTML report and native Playwright report.

## What Static Review does

Static Review checks:

- `generated-playwright/pageObjects/` exists.
- `generated-playwright/pages/` exists.
- `generated-playwright/tests/generated/` exists.
- `BasePage.ts` and `locatorFactory.ts` exist.
- Generated specs do not directly use raw locators such as `getByRole`, `getByTestId`, `locator`, or XPath.
- TypeScript build is run when npm dependencies are installed and `skip_npm` is not checked.

## What the enterprise HTML report contains

- Artifact counts.
- Functional testcase artifacts.
- Generated Playwright files.
- Static review checks.
- Step-by-step Playwright execution results.
- Failure screenshots/videos/traces/JSON links.
- Reuse and self-healing input summary.

## Failure screenshots and videos

The file `generated-playwright/playwright.config.ts` has:

```ts
trace: 'retain-on-failure'
screenshot: 'only-on-failure'
video: 'retain-on-failure'
```

After a failed execution, artifacts are collected under `generated-playwright/test-results/` and linked from the enterprise HTML report.
