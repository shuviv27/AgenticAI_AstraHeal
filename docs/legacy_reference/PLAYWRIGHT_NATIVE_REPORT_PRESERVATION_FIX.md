# Playwright Native Report Preservation Fix

## Problem
Sequential execution could finish and the GUI could open a fallback report that said:

> Playwright did not generate a native HTML report

This happened even when Playwright produced a native HTML report, because the pipeline wrote the fallback page whenever the Playwright process returned a non-zero exit code. A non-zero exit code is expected when tests fail, but Playwright still produces a useful native HTML report with traces, screenshots, videos, stdout and error details.

## Fix
The executor now:

1. Clears stale Playwright HTML report folders before each new execution.
2. Detects and ignores stale AI QA fallback pages during report normalization.
3. Preserves the native Playwright HTML report when it exists, even if tests fail.
4. Writes the fallback report only if no native Playwright HTML report exists at the end of execution.
5. Normalizes native reports into `generated-playwright/reports/html/index.html`, which is what the GUI opens.

## Expected behavior
If tests pass or fail after Playwright starts, the GUI should open:

```text
generated-playwright/reports/html/index.html
```

If Playwright fails before it can create a native report, the pipeline still creates a fallback report so the GUI link does not show `detail: not found`.
