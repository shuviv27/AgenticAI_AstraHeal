# Acima / Modern Dynamic Website Alignment Guide

This build is aligned for a modern public web application with dynamic, non-standard components. The uploaded requirements include home-page smoke checks, navigation menu checks, marketplace/product discovery, app store links, social links, footer/legal links, usability, negative/error handling, and accessibility checks.

## What changed for this website type

1. Functional testcase generation now creates one traceable scenario per requirement line instead of compressing the entire SRS into one generic scenario.
2. Generated Playwright uses a single reusable `AcimaPage` layer for the public site flow.
3. The starter locator inventory is already prepared in `generated-playwright/pageObjects/AcimaPage.objects.ts`.
4. The generator prefers accessible locators: `getByRole`, `getByText`, `getByLabel`, href/CSS fallbacks only when required.
5. Navigation and external-link checks use reusable page methods, not raw locators inside specs.
6. Responsive, keyboard, and negative-page scenarios are represented as executable smoke-level methods that can be hardened after Playwright-MCP exploration.

## Why this matters

Modern websites often use generated classes, dynamic menus, overlays, responsive layouts, non-standard cards, and third-party links. Therefore, the framework avoids brittle XPath and CSS-first generation. It uses semantic locators first, then controlled fallback locators in pageObjects.

## Recommended demo setup

Start Docker and your AI provider first, then run the pipeline.

### Windows with Codex

```powershell
.\scripts\START_DOCKER_AND_AI_WINDOWS.ps1 -Provider codex
python -m qa_pipeline.cli serve-gui --host 127.0.0.1 --port 8080
```

### Windows with Ollama

```powershell
.\scripts\START_DOCKER_AND_AI_WINDOWS.ps1 -Provider ollama -Model llama3
python -m qa_pipeline.cli serve-gui --host 127.0.0.1 --port 8080
```

### Mac with Codex

```bash
./scripts/START_DOCKER_AND_AI_MAC.sh codex
python -m qa_pipeline.cli serve-gui --host 127.0.0.1 --port 8080
```

### Mac with Ollama

```bash
./scripts/START_DOCKER_AND_AI_MAC.sh ollama llama3
python -m qa_pipeline.cli serve-gui --host 127.0.0.1 --port 8080
```

## GUI flow for the uploaded SRS

1. Open `http://127.0.0.1:8080`.
2. Go to **Project Setup**.
3. Enter `https://www.acima.com/en` as the Website/Application URL.
4. Set feature as `acima`.
5. Select provider `Codex CLI` or `Ollama`.
6. Save project config.
7. Go to **Requirement Input**.
8. Upload `samples/srs/acima_requirements.txt` or paste the SRS text.
9. Click **Generate Functional Testcases**.
10. Review `testcases/srs/acima/acima.scenarios.json`.
11. Click **Generate Playwright**.
12. Review:
    - `generated-playwright/tests/generated/acima.spec.ts`
    - `generated-playwright/pages/AcimaPage.ts`
    - `generated-playwright/pageObjects/AcimaPage.objects.ts`
    - `generated-playwright/reports/reuse-decision-report.md`
13. Run static review.
14. Run execution only after confirming locators against the real site with Playwright-MCP.

## CLI flow

```bash
python -m qa_pipeline.cli run-e2e \
  --source samples/srs/acima_requirements.txt \
  --source-type srs \
  --feature acima \
  --base-url https://www.acima.com/en \
  --provider codex \
  --model llama3 \
  --skip-npm
```

For Ollama:

```bash
python -m qa_pipeline.cli run-e2e \
  --source samples/srs/acima_requirements.txt \
  --source-type srs \
  --feature acima \
  --base-url https://www.acima.com/en \
  --provider ollama \
  --model llama3 \
  --skip-npm
```

## Files created for the Acima feature

```text
testcases/srs/acima/acima.scenarios.json
generated-playwright/tests/generated/acima.spec.ts
generated-playwright/pages/AcimaPage.ts
generated-playwright/pageObjects/AcimaPage.objects.ts
generated-playwright/reports/reuse-decision-report.md
```

## Where Docker is used

Docker starts the enterprise support layer:

- Redis: event bus and orchestration readiness
- Postgres: run history and metadata readiness
- Qdrant: vector/RAG storage readiness
- MinIO: artifacts, reports, traces, screenshots readiness
- Ollama container: optional local LLM runtime
- GUI container: optional GUI app runtime

The GUI can still run locally without Docker, but the full enterprise stack should be started before pipeline execution for a proper demo.

## Important limitation

The generated tests are based on the uploaded requirements. For dynamic menus and responsive layouts, Playwright-MCP should be used to explore the live DOM and then improve the pageObjects with stable locators. The generator intentionally keeps all locator updates inside `pageObjects` and all reusable actions inside `pages`.
