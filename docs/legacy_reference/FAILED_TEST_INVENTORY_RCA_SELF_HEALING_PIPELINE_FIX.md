# Failed-Test Inventory, RCA, MCP and Self-Healing Pipeline Fix

This build fixes the post-execution agentic pipeline for existing external Playwright frameworks.

## Problem fixed

The real browser runner was able to launch and execute selected tests, but RCA and self-healing could remain blocked when the failed inventory was empty. This happened most often when:

- The existing framework used `tests/specs/**/*.specs.ts` naming.
- Playwright JSON reporter output was not produced in the expected file location.
- Failure details were present only in the console output.
- The GUI clicked `Explain failed tests`, `Check failed element with Playwright MCP`, `Create safe fix plan`, or `Run failed tests again`, but no failed specs were available to those downstream agents.

## Fixes included

1. Console-output failure extraction now supports `.specs.ts`, `.spec.ts`, `.test.ts`, `.js`, `.mjs`, `.cjs`, and nested `tests/specs` folders.
2. If JSON report is unavailable, the system extracts failed specs from the Playwright console log.
3. If Playwright fails while running a small explicit target list, those selected spec files are carried into failed-only inventory with a review note instead of blocking RCA silently.
4. MCP locator RCA now falls back to the last execution inventory framework path if the GUI field is empty.
5. `Create safe fix plan` now always produces a deterministic human-readable fix plan even if Codex is not logged in or enterprise auth blocks automatic patching.
6. `Fix failed tests safely` still requires Codex/Ollama for actual file patching and keeps guardrails intact.
7. `Run failed tests again` uses the real external-framework Playwright runner and opens the browser when headed mode is selected.

## Correct workflow

1. Learn this framework with AI.
2. Show tests selected for execution.
3. Run all selected existing tests.
4. If tests fail, click Explain failed tests.
5. Click Check failed element with Playwright MCP.
6. Click Create safe fix plan.
7. Click Fix failed tests safely if Codex is connected and the patch is safe.
8. Click Run failed tests again.

## Reports to check

- `generated-playwright/reports/existing-framework/failed-tests.json`
- `generated-playwright/reports/existing-framework/plain-english-failure-report.html`
- `generated-playwright/reports/existing-framework/mcp-assisted-rca/mcp-assisted-locator-rca.html`
- `generated-playwright/reports/existing-framework/self-healing-report.json`
- `<external-framework>/reports/existing-framework/execution-console.log`
