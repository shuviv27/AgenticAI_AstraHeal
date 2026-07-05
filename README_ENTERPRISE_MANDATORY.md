# Advanced AI QA Automation — Mandatory Enterprise Stack Build

This build treats the technology stack as enterprise-required infrastructure.

## 1. Configure secrets

Copy `.env.example` to `.env` and fill at least the services you will actively use:

```powershell
copy .env.example .env
notepad .env
```

Important values:

```text
JIRA_URL=https://yourcompany.atlassian.net
JIRA_USERNAME=your.email@company.com
JIRA_API_TOKEN=your_atlassian_api_token
GITHUB_TOKEN=your_github_pat
LANGCHAIN_API_KEY=your_langsmith_key
BASE_URL=https://your-app-url
```

Codex is still authenticated through the local CLI:

```powershell
codex login --device-auth
```

The GUI also has a Codex device-auth button, but terminal login is more reliable on locked-down laptops.

## 2. Start mandatory Docker stack

```powershell
START_ENTERPRISE_STACK_WINDOWS.cmd
```

or:

```powershell
docker compose -f infra/docker/docker-compose.yml up -d
```

This starts Redis, Postgres, Qdrant, ChromaDB, MinIO, Prometheus, Grafana, Langfuse, LangSmith bridge, Jira MCP, GitHub MCP, Playwright MCP, Ollama and OWASP ZAP.

## 3. Install Python dependencies

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install -e .
```

## 4. Install Playwright dependencies

```powershell
cd generated-playwright
npm config set registry https://registry.npmjs.org/
npm install --registry=https://registry.npmjs.org/
npx playwright install chromium
npm run build
cd ..
```

## 5. Start GUI

```powershell
START_GUI_WINDOWS.cmd
```

Open:

```text
http://127.0.0.1:8080
```

## 6. Recommended enterprise GUI flow

1. Enterprise Stack -> Check stack.
2. Codex/Ollama -> Check Codex login and/or run device auth.
3. Jira Epic -> enter Jira URL, username/email, API token, Epic key -> fetch epic and generate testcases.
4. App Intelligence -> upload page source/outerHTML if available -> Profile application.
5. Requirement Input -> Generate functional testcases if using SRS/manual files.
6. Generated Playwright -> Generate reusable Playwright.
7. Static Review.
8. Execute distributed/headless or headed.
9. RCA & Self-Healing if failures occur.
10. Reports -> Enterprise HTML report and native Playwright report.

## 7. Distributed execution

Use `shards=5` for about 20 tests per shard when you have 100 tests. The executor runs shards in parallel and merges blob reports into one HTML report.

## 8. Guardrails

- No raw locators in generated specs.
- Specs call page methods.
- Page methods call pageObjects/BasePage helpers.
- Self-healing patches only pageObjects/pages/utils.
- Networkidle is not used as page readiness.
- LLM output is treated as advisory; deterministic guards validate files before execution.
