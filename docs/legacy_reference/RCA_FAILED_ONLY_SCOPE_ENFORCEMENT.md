# RCA Failed-Only Scope Enforcement

This build enforces the RCA/self-healing rule that only failed scripts are analyzed, patched, and rerun.

## What changed

1. Playwright execution now writes JSON result artifacts in addition to native HTML reports.
   - Sequential: `generated-playwright/reports/results.json`
   - Distributed: `generated-playwright/reports/json-shards/*.json`
2. `generated-playwright/reports/failed-tests.json` is built from exact Playwright JSON results.
3. If exact failed specs cannot be identified, RCA is blocked instead of assuming that all selected specs failed.
4. RCA analyzes failed scripts one by one and writes:
   - `generated-playwright/reports/root-cause-failed-scripts-report.json`
   - `generated-playwright/reports/root-cause-failed-scripts-report.md`
5. Self-healing uses a strict failed-script scope:
   - failed spec file
   - page classes imported by that failed spec
   - pageObjects imported by those page classes
   - shared `BasePage.ts` / `locatorFactory.ts` only when reusable browser-action/locator resilience is needed
6. After a patch, the RCA guard forces the next run to execute failed scripts only.
7. The consolidated report preserves original passed tests and updates only failed-test rerun status.

## Important behavior

RCA will not analyze already-passed scripts.
Self-healing will not patch pages/pageObjects unrelated to failed specs.
Rerun after patch targets failed specs only.

If the same failed resource reaches the maximum attempt limit, the system blocks automatic patching and asks for user intervention with updated page source, screenshot, credentials/test data, or manual inspection.

## Reports

- Native Playwright latest report: `generated-playwright/reports/html/index.html`
- Original full-run archive: `generated-playwright/reports/full-run-before-failed-only-rerun/index.html`
- Complete RCA rerun report: `generated-playwright/reports/failed-only-consolidated-report.html`

## Recommended workflow

1. Execute generated tests.
2. Open native report and confirm failures.
3. RCA & Self-Healing -> Analyze Root Cause.
4. Review `root-cause-failed-scripts-report.md`.
5. RCA & Self-Healing -> Propose Self-Healing Fix.
6. RCA & Self-Healing -> Apply Self-Healing Patch.
7. RCA & Self-Healing -> Re-run Failed Only.
8. Open the consolidated failed-only report.

