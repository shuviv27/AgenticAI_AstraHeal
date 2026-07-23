# Exact shard Playwright report and test-level RCA fix

This build fixes a distributed report ambiguity where Local/VM parallel execution could show a progress value such as `109/120` without clearly explaining failures or the remaining/not-reported targets.

## What changed

- AstraHeal now writes an exact first-run Playwright report index:
  - `generated-playwright/reports/existing-framework/first-run-playwright-report.html`
  - `<framework>/.aiqa-history/reports/first-run-playwright-report.html`
- The index links every shard-native Playwright HTML report under:
  - `<framework>/reports/existing-framework/distributed-runs/<run-id>/<shard-id>/html/index.html`
- The index includes:
  - planned selected targets
  - Playwright-reported/runnable tests
  - passed test cases
  - failed test cases
  - unresolved/not-reported selected line targets and reason
- Passed shards no longer show fake failed specs just because command/log text contained spec file names.
- The plain English RCA report now includes a test-by-test table:
  - `spec -> test -> passed/failed -> reason -> safest fix area`
- The self-healing proposal report now includes specific failed tests and recommended fix locations, especially locator repository/pageObject/page method guidance.

## Why unresolved/not-reported targets can appear

When the GUI selection uses line selectors such as `tests/ui/login.spec.ts:42`, Playwright may report fewer runnable tests than static selection count if a line is not a runnable test declaration, the test is filtered/skipped by config/project, or dynamic framework conditions exclude it. These are now shown separately instead of being hidden as missing progress.

## Existing features preserved

- Existing framework learning
- Playwright preflight
- Single and distributed execution
- Local PC/Central VM and VM-worker modes
- Latest Playwright report opening
- Runtime progress counter
- Failed-only rerun
- Combined first-run + rerun report
- RCA and self-healing
- Safe approval and rollback flow
