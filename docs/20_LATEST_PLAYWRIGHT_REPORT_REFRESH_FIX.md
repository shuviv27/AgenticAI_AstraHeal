# Latest Playwright Report Refresh Fix

## Problem fixed

After a new execution finished, the **Open Playwright report** button could still show an older Playwright HTML report. This happened because the backend checked legacy report folders in a fixed order, especially:

- `<framework>/reports/existing-framework/html/index.html`
- `<framework>/playwright-report/index.html`

Local/VM parallel runs create fresh shard-native reports and a fresh AstraHeal central landing page, but the older framework-native report path could be opened first.

## What changed

1. The `/api/module2/framework-artifact/playwright-report` endpoint now selects the newest report artifact by file modified time instead of opening the first legacy path.
2. The report endpoint returns no-cache headers:
   - `Cache-Control: no-store, no-cache, must-revalidate, max-age=0`
   - `Pragma: no-cache`
   - `Expires: 0`
3. The GUI appends a timestamp cache-buster when opening the Playwright report.
4. When a new execution starts, AstraHeal writes a fresh in-progress report placeholder so an older report is not shown while the run is still active.
5. Local/VM distributed execution writes/refreshes the central Playwright landing page at run start and during test-count initialization.

## Existing behavior preserved

- Normal existing-framework execution still copies native HTML into `generated-playwright/reports/existing-framework/html/index.html`.
- Local/VM parallel execution still keeps native Playwright HTML per shard.
- The central landing page remains the single safe GUI entry point for distributed runs.
- Failed-only rerun, distributed failed-only rerun, RCA/self-healing, combined report, runtime progress, hierarchical test selection and timeout guard remain unchanged.

## Verification expectation

After a new run completes, clicking **Logs, Reports and AI Memory → Open Playwright report** should open the latest report. The HTTP response includes headers showing the selected source:

- `X-AstraHeal-Report-Source`
- `X-AstraHeal-Report-MTime`

## Static artifact cache protection

The FastAPI middleware also adds no-cache headers to `/artifacts/reports/**` responses. This protects older bookmarked/static report URLs as well as the preferred framework-aware report endpoint.
