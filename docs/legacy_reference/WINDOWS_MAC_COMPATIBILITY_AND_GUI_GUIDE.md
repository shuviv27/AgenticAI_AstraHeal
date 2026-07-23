# Windows/Mac Compatibility and GUI Execution Guide

## What this build supports

| Capability | Supported |
|---|---|
| Windows PowerShell | Yes |
| macOS/Linux terminal | Yes |
| Business GUI upload | Yes |
| Jira story/epic JSON or pasted text | Yes |
| SRS/TXT/Markdown | Yes |
| PDF upload | Yes, via `pypdf` |
| DOCX upload | Yes, via `python-docx` |
| Reuse existing locators | Yes |
| Reuse existing page methods | Yes |
| Generate Playwright under one folder | Yes: `generated-playwright/` |
| Codex CLI login session | Yes |
| Ollama local model | Yes |
| Docker infra services | Yes |

## Version compatibility

Use these versions for the lowest friction:

- Python: **3.12.x** preferred. Python 3.11 supported. Python 3.13 should work but 3.12 is safer for enterprise desktops.
- Node.js: **20 LTS or 22 LTS**. npm must be available in PATH.
- npm: installed with Node.js.
- Playwright: installed by `npm install` inside `generated-playwright/`.
- Docker: Docker Desktop on Windows/Mac, Docker Engine on Linux/CI.
- Codex CLI: install and authenticate once with `codex login`.
- Ollama: install locally or run the Docker profile.

## GUI flow

```text
Jira / PDF / SRS / Test Management input
        ↓
GUI upload or paste
        ↓
Python parser normalizes input
        ↓
testcases/<source_type>/<feature>/<feature>.scenarios.json
        ↓
Python RAG inventory scans generated-playwright/
        ↓
Reuse-aware generation updates pageObjects/pages/tests
        ↓
generated-playwright/tests/generated/<feature>.spec.ts
        ↓
Review report in generated-playwright/reports/
```

## Reuse rule

The generator always scans before writing:

```text
If locator exists in generated-playwright/pageObjects/<PageName>.objects.ts:
    reuse locator
else:
    add locator to that pageObjects file

If function exists in generated-playwright/pages/<PageName>.ts:
    reuse function
else:
    add function to that pages file

Generated spec uses page methods only.
Generated spec must not contain raw locators.
```

## Windows commands

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
cd generated-playwright
npm install
npx playwright install chromium
cd ..
python -m qa_pipeline.cli serve-gui --host 127.0.0.1 --port 8080
```

## macOS commands

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cd generated-playwright
npm install
npx playwright install chromium
cd ..
python -m qa_pipeline.cli serve-gui --host 127.0.0.1 --port 8080
```

## Docker commands

```bash
docker compose -f infra/docker/docker-compose.yml up -d redis postgres qdrant minio
```

With Ollama:

```bash
docker compose -f infra/docker/docker-compose.yml --profile ollama up -d ollama
```

Full GUI in Docker:

```bash
docker compose -f infra/docker/docker-compose.yml --profile app up --build pipeline-gui
```
