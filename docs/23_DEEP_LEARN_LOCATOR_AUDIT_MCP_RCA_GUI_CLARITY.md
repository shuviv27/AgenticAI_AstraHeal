# Deep Learn Locator Audit, MCP RCA Clarity, and Failed-Only Progress

This build adds a small demo-safe enhancement without changing the existing AstraHeal execution/RCA/self-healing pipeline.

## Deep learn framework with AI

When the user clicks **Deep learn this framework with AI**, AstraHeal still reads and indexes the selected external Playwright framework. It now also performs a read-only object repository locator audit:

- scans pageObjects, pages, locators, selectors, BasePage, safe actions and helper files
- extracts Playwright locator definitions such as getByRole, getByTestId, getByLabel, getByText and locator()
- classifies locator risk as low, medium or high
- searches local DOM/snapshot/artifact evidence for static matches
- writes a concise GUI result and HTML report

Report:

```text
generated-playwright/reports/existing-framework/object-repository-locator-audit.html
```

Important: a locator not found in static artifacts is not automatically wrong. It may need login, route navigation, scroll, modal state, iframe/shadow DOM or mobile viewport. Live failed-page-state verification is handled by **Check failed element with Playwright MCP**.

## Check failed element with Playwright MCP

This button does not patch files. It creates observable element-level RCA evidence:

- failed locator/action candidate
- visible text/role/testId candidates
- DOM/accessibility presence check plan
- actionability/interactability classification
- missing, detached, hidden, disabled, duplicated, overlay-blocked or permission-blocked element classification
- pageObject/page/helper mapping for the smallest safe fix

Report:

```text
generated-playwright/reports/existing-framework/mcp-assisted-rca/mcp-assisted-locator-rca.html
```

## Explain failed tests

The existing RCA response now surfaces clearer plain-English information in the GUI output where available.

## Create safe fix plan / Fix failed tests safely

The runtime approval dialog now opens with a more specific safe-fix summary: failed spec files, likely failure signals and the expected patch location. It keeps the same guardrails: backup, approval, scoped files, validation and rollback.

## Failed-only rerun progress

The **Run failed tests again** action now shows a failed-only progress counter below the main progress bar. The endpoint still reruns only the failed inventory and does not submit passed tests.

