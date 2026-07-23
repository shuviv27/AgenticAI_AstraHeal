# Combined Matrix Test-Case Normalization Fix

This build fixes the combined **first-run + failed-only rerun** report.

## Problem fixed

The previous combined report could show incorrect totals and duplicate rows when Playwright reported the same file in different formats, for example:

- `tests/ui/login.spec.ts`
- `ui/login.spec.ts`

It also counted spec files instead of real Playwright test cases when JSON evidence was available. This made the report look like 37 rows even when the actual Playwright run contained around 95/96 test cases.

## New behavior

The consolidated report now:

1. Uses Playwright test-case level records when JSON reporter evidence is available.
2. Normalizes spec paths so `tests/...` and non-prefixed `...` paths are compared as the same file.
3. Shows passed first-run tests as **Not rerun by design**.
4. Shows only originally failed tests in the failed-only rerun column.
5. Flags any unexpected extra rerun evidence instead of silently treating it as a first-run pass duplicate.
6. Falls back to spec-file granularity only when Playwright JSON test-case records are unavailable.

## Expected matrix

For a first run such as:

- Total: 95
- Passed: 65
- Failed: 30

The combined matrix should show the 95 first-run test cases, with the 30 failed cases having failed-only rerun status and the 65 passed cases marked as **Not rerun by design**.

## Existing features preserved

- Run failed tests again remains failed-only.
- Distributed failed-only rerun remains available.
- RCA and self-healing still use failed specs only.
- 30-second timeout guard remains active.
- Report404-safe Playwright report landing page remains active.
