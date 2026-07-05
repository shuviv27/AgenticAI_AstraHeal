# Iterative Failed-Only Report Integrity Fix

This build fixes the report/run-state issue where a second failed-only rerun could replace the original first-run baseline and make the combined report show only the latest rerun scope.

## Correct behavior

1. The first selected execution is saved as the immutable baseline.
2. Each click on Run failed tests again appends a new failed-only rerun iteration.
3. The combined report compares every iteration back to the original first run.
4. Remaining failed tests are rerun at test-case selector level when Playwright JSON line evidence is available.
5. Open Playwright Report opens the latest Playwright-stage router, not the combined business matrix.

## New/updated artifacts

- `generated-playwright/reports/existing-framework/first-run-baseline-inventory.json`
- `generated-playwright/reports/existing-framework/failed-only-rerun-ledger.json`
- `generated-playwright/reports/existing-framework/failed-only-rerun-iteration-N-playwright-report.html`
- `generated-playwright/reports/existing-framework/failed-only-latest-playwright-report.html`
- `generated-playwright/reports/existing-framework/latest-playwright-report.html`
- `generated-playwright/reports/existing-framework/consolidated-report.html`

## Why this matters

If the first run had 109 actual Playwright-reported tests and 12 failed, then the first failed-only rerun must submit only those 12 failed test targets. If 4 recover and 8 remain, the next failed-only rerun must submit only those 8 remaining failed test targets. It must not rerun full spec files that contain 42 tests unless test-case line evidence is unavailable.
