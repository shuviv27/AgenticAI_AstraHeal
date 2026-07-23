# RCA Failed-Only Rerun + Complete Report Fix

## Problem fixed
After a self-healing patch, users sometimes clicked the normal Execute Generated Test action and the pipeline reran the whole active batch. That wasted time and could make previously passed scripts fail because of app/network/environment variance.

## New behavior
After `Apply Self-Healing Patch`, the pipeline creates a guarded pending state at `.qa-cache/rca_failed_only_pending.json` when failed specs are available from the last run.

While this guard is active:

- `Execute Generated Test - Headed` and `Execute Generated Test - Headless` are redirected to failed-only rerun.
- Distributed execution is also redirected to failed-only distributed rerun.
- Already-passed specs from the original full run are not executed again.
- The original full-run native report is archived before rerun.
- The current native Playwright report shows the failed-only rerun.
- A consolidated complete report combines original passed specs with updated failed-spec rerun results.

## Reports

- Current native Playwright rerun report: `generated-playwright/reports/html/index.html`
- Archived original full-run report: `generated-playwright/reports/full-run-before-failed-only-rerun/index.html`
- Complete consolidated report: `generated-playwright/reports/failed-only-consolidated-report.html`

## Why native Playwright cannot show old passed + rerun results automatically
Native Playwright HTML reflects the latest execution scope. If only failed tests are rerun, native Playwright correctly shows only those failed-only rerun specs. The AI QA consolidated report is the complete enterprise report that preserves original passed tests and updates the failed tests with rerun results.
