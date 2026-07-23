# Agentic Multi-Agent Framework Understanding Guide

This build strengthens Module 2 for existing Playwright TypeScript frameworks. It keeps Docker/No-Docker, Local/VM/VDI, headed/headless execution, user-selected tests, Microsoft Playwright MCP assist, RCA, self-healing, reports, and AI memory intact.

## What the two failure buttons mean

### Explain failed tests

This button does not run the browser and does not change files. It reads the latest failed-test inventory, Playwright console log, result JSON, traces/report links, MCP memory when available, RAG framework chunks, and the deep framework memory. It then creates a plain-English RCA report and structured JSON report.

Use it after a test run fails. Output files:

- `generated-playwright/reports/existing-framework/root-cause-report.json`
- `generated-playwright/reports/existing-framework/plain-english-failure-report.html`

### Check failed element with Playwright MCP

This button is for locator/actionability failures. It uses Microsoft Playwright MCP style evidence where available: accessibility/DOM-style page structure, visible text candidates, failed locator/action candidates, and actionability checks. It does not modify files. It writes evidence that the RCA and fix prompt can use.

Output files:

- `generated-playwright/reports/existing-framework/mcp-assisted-rca/mcp-assisted-locator-rca.html`
- `generated-playwright/reports/existing-framework/mcp-assisted-rca/mcp-assisted-locator-rca.json`
- `.qa-cache/existing-framework/mcp-assisted-memory.jsonl`

## New deep framework understanding

Click **Deep learn this framework with AI** before execution/fixing. It now runs multiple deterministic agent passes:

1. Architecture Agent: identifies folders and their role.
2. Code Semantics Agent: extracts classes, functions, test titles, page routes, imports.
3. Dependency Graph Agent: maps spec → page → pageObject → helper/testData chains, including tsconfig aliases.
4. Locator Strategy Agent: counts getByRole, getByTestId, getByLabel, locator, XPath, CSS and anti-patterns.
5. AUT Flow Agent: infers application routes, auth/session/API/business-flow hints from tests and configs.
6. Safe Patch Scope Agent: identifies which files are safe to patch for failed specs.
7. Memory Agent: saves reusable understanding for later RCA/self-healing.

Output files:

- `generated-playwright/reports/existing-framework/agentic-framework-understanding.html`
- `generated-playwright/reports/existing-framework/agentic-framework-understanding.json`
- `.qa-cache/existing-framework/agentic-memory/framework-understanding-memory.json`
- `.qa-cache/existing-framework/agentic-memory/framework-understanding-memory.jsonl`

## Self-healing behavior

The system can auto-patch only when it can safely identify files related to failed specs. It uses this patch order:

1. pageObjects/locator files
2. pages/Page classes and methods
3. BasePage/helpers/utils
4. fixtures/testData only when evidence proves data/fixture issue
5. spec file only when no reusable layer exists

It must ask for human review when:

- safe patch scope is empty
- import graph is unresolved
- failure looks like AUT/product/environment/auth/network defect
- assertion drift is functional/numeric
- Codex/Ollama patch confidence is below guardrail threshold
- a patch would touch unrelated/passed-test files

## Recommended enterprise workflow

1. Start Module 2.
2. Select Local PC, VM Control Plane, or VM + VDI Agent.
3. Select Docker or No-Docker runtime.
4. Enter existing framework path.
5. Click **Deep learn this framework with AI**.
6. Click **Prepare Playwright MCP assist**.
7. Find scripts and select the tests to execute.
8. Run chosen tests in headed mode for debugging.
9. If failures exist, click **Explain failed tests**.
10. Click **Check failed element with Playwright MCP** for locator/actionability issues.
11. Click **Create safe fix plan**.
12. Connect Codex/Ollama only when you want automatic patching.
13. Click **Fix failed tests safely**.
14. Verify changed files in self-healing report.
15. Click **Run failed tests again**.

## VM/VDI note

This build does not change the VM/VDI model. If AUT is accessible on VM, run GUI and framework execution in the RDP VM session. If AUT is accessible only in Horizon/Omnissa VDI, run GUI/control plane on VM and run execution/fixing through the VDI Agent inside the interactive VDI desktop.
