# Failed-only rerun 500 fix

## Problem

The endpoint `POST /api/existing-framework/execute/failed-only` could fail with HTTP 500 before rerunning failed tests.

The failure happened inside `_archive_existing_html()` while copying the previous Playwright HTML report:

```text
shutil.Error ... WinError 3 The system cannot find the path specified
```

This can happen on Windows when Playwright HTML report assets under `generated-playwright/reports/existing-framework/html/data` are removed, rewritten, or not fully available while the AI module is trying to archive the previous full-run report before starting failed-only rerun.

## Fix

The archive step is now best-effort and non-blocking.

The system now:

1. Copies the previous HTML report file-by-file.
2. Creates destination folders before copying each file.
3. Skips missing/volatile assets instead of crashing.
4. Writes a fallback archived `index.html` if needed.
5. Logs skipped assets as a warning.
6. Continues with failed-only rerun even if archiving is partial or unavailable.

## Expected behavior

Clicking **Run failed tests again** should no longer return HTTP 500 due to report archive copying.

If some old report screenshots/traces are missing, the GUI should show a warning, but the failed specs should still rerun using the existing real Playwright runner.
