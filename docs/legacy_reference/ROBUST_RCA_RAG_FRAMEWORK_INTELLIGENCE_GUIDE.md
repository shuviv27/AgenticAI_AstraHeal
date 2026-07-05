# Robust RCA, Self-Healing, Locator Strategy, and Framework RAG Intelligence

This extension is additive. It does not replace the existing Jira/SRS/PDF → testcase → Playwright generation pipeline and it does not disturb the existing Existing Framework Control flow.

## Purpose

The system can now understand and index an already-developed Playwright TypeScript framework before execution and RCA. The goal is to make Codex/Ollama calls smaller, safer, and more accurate by retrieving only relevant framework context instead of repeatedly passing the entire project.

## New capabilities

1. **Deep framework understanding**
   - Architecture and Page Object Model structure
   - Technology stack from `package.json`, configs, CI files, and dependencies
   - Triggering flows from npm scripts, CI workflows, specs, hooks, and custom commands
   - Normal flows from page classes, pageObjects, fixtures, actions, locators, and assertions
   - Backend/API/DB connection hints from code, env examples, docs, and dependency usage
   - Test data file validation for JSON/CSV/YAML/readable data files
   - VDI/VM/VPN/proxy hints from repository docs/env/scripts

2. **Local RAG index**
   - Chunks specs, pages, pageObjects, fixtures, utils, test data, docs, and configs
   - Creates local deterministic sparse embeddings
   - Stores the index in `.qa-cache/existing-framework/rag/framework-chunks.jsonl`
   - Supports RAG search from GUI and CLI

3. **Plain-English RCA report**
   - Converts technical Playwright errors into human-friendly explanations
   - Separates likely locator, popup, timing, API, DB, data, environment, assertion, and product issues
   - Writes `generated-playwright/reports/existing-framework/plain-english-failure-report.html`

4. **Safer AI reasoning workflow**
   - Codex/Ollama prompts now instruct the AI to follow a staged RCA workflow internally:
     1. Understand architecture and framework context
     2. Check trace/DOM/HAR/network/data/history evidence
     3. Classify the issue
     4. Decide whether self-healing is safe
     5. Recommend or apply the smallest allowed patch
   - The solution stores an auditable evidence summary, not hidden chain-of-thought text.

## GUI workflow

1. Start the GUI using the single GUI-first launcher.
2. Open `http://127.0.0.1:8080`.
3. Go to **Existing Framework Control**.
4. Paste the existing Playwright framework root path.
5. Click **Understand Framework** or **Deep Index + RAG**.
6. Review **Open Intelligence**.
7. Use **Search RAG Context** to find existing locators, page methods, API waits, fixtures, data files, and utilities.
8. Execute the existing framework headless/headed.
9. If failures occur, click **Analyze Existing RCA**.
10. Open the plain-English RCA report and auditable RCA chain.
11. Propose/apply self-healing only when policy and confidence gates allow it.
12. Rerun failed specs only and review the consolidated report.

## CLI commands

```bash
python -m qa_pipeline.cli existing-framework-analyze --framework-path /path/to/framework --provider deterministic
```

```bash
python -m qa_pipeline.cli existing-framework-intelligence-v2
```

```bash
python -m qa_pipeline.cli existing-framework-rag-search --query "checkout page object API wait locator test data" --top-k 12
```

## Important environment note

The system can infer VDI/VM/VPN/proxy knowledge only from repository files, `.env.example`, scripts, docs, and configuration. If an application works only inside a specific corporate VDI/VPN, add that information to project metadata and documentation so RCA can classify environment/network failures correctly instead of patching test code.

## Self-healing boundaries

Allowed patch areas remain:

- `pageObjects/`
- `pages/`
- `utils/`
- `fixtures/`
- `testData/` only when evidence proves a data issue

Blocked without manual approval:

- assertion weakening
- `test.skip`, `test.fixme`, `.only`
- blind `waitForTimeout`
- broad `force: true`
- passed-spec edits
- product/API/environment issues disguised as script fixes

## Outputs

- `generated-playwright/reports/existing-framework/framework-intelligence-v2.json`
- `generated-playwright/reports/existing-framework/framework-intelligence-v2.html`
- `.qa-cache/existing-framework/rag/framework-chunks.jsonl`
- `.qa-cache/existing-framework/rag/framework-rag-summary.json`
- `generated-playwright/reports/existing-framework/plain-english-failure-report.json`
- `generated-playwright/reports/existing-framework/plain-english-failure-report.html`
