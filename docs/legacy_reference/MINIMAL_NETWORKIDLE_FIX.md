# Minimal Network Idle Fix

This build is based on the previous PageSourceAware Acima Dynamic Web build.

Only `generated-playwright/pages/BasePage.ts` was changed to remove hard `networkidle` waits from:

- `waitForPageReady()`
- `waitForStableDom()`

No testcase generation logic, AcimaPage methods, GUI features, agent registry, reports, RCA/self-healing, or page-source-aware generation logic was changed.

Why: modern websites often keep background requests open for analytics, fonts, A/B testing, monitoring, service workers, or telemetry. Waiting for `networkidle` can time out even when the page is visually ready.
