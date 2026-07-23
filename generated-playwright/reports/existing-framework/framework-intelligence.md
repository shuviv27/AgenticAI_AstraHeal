# Existing Playwright Framework Intelligence

- Framework path: `/mnt/data/work/racpad/qa_racpad_ts_automation`
- Generated at: `2026-07-08T18:43:53`
- Spec count: **60**
- POM grade: **moderate** (68/100)

## Important mode decision
This mode bypasses requirement parsing, functional testcase generation, and generated Playwright script generation. It executes the provided framework in-place and uses failed-only RCA/self-healing when failures occur.

## Discovered scripts
```json
{
  "test:ui": "playwright test",
  "test:project": "playwright test --project",
  "test:smoke": "playwright test --grep @smoke --workers=1",
  "test:smoke:list": "playwright test --list --grep @smoke --reporter=list",
  "test:customer-order": "playwright test src/test/specs/customerOrders/customer-order-flow.spec.ts -g \"CustomerOrderFlow.createCustomerOrder\"",
  "test:customer-order:headed": "playwright test src/test/specs/customerOrders/customer-order-flow.spec.ts -g \"CustomerOrderFlow.createCustomerOrder\" --headed",
  "report:extent": "playwright show-report reports/html"
}
```

## Directory model
```json
{
  "spec_dirs": [
    "src/test/resources/data-loader/e2e",
    "src/test/resources/fixtures/e2e",
    "src/test/resources/testData/e2e",
    "src/test/specs",
    "src/test/specs/e2e"
  ],
  "page_dirs": [
    "src/main/pages"
  ],
  "page_object_dirs": [],
  "fixture_dirs": [
    "src/test/resources/fixtures"
  ],
  "test_data_dirs": [
    "src/test/resources/testData"
  ],
  "utility_dirs": [
    "agents/failure-analyzer/lib",
    "agents/failure-analyzer/utils"
  ]
}
```

## Strict rules
- Bypass Requirement/Input/Testcase/Generated Playwright phases for this mode.
- Do not copy or overwrite the user's framework into generated-playwright.
- Execute the framework in-place from the provided folder.
- RCA and self-healing must use failed-tests inventory only.
- Patch failed specs and their imported page/pageObject/helper files only.
- Treat Cannot find module / MODULE_NOT_FOUND for @aliases as a TypeScript path-alias/runtime configuration issue, not a locator/DOM failure.
- Prefer PageObjects first, then page methods/BasePage/helpers; avoid raw locator fixes inside specs.
- Robust RCA uses five signals before patching: DOM diff, trace timing, HAR diff, fixture/seed diff, and cross-run flakiness frequency.
- Assertion updates are blocked unless the assertion drift classifier marks the change as cosmetic and above semantic threshold.

## Framework Intelligence V2
- HTML: `generated-playwright/reports/existing-framework/framework-intelligence-v2.html`
- RAG chunks indexed: **891**
- Coverage: architecture, technology stack, trigger flows, normal flows, backend/API/DB hints, test data validation, VDI/VM/VPN hints.

## Playwright Framework Alignment
- Aligned for execution: **True**
- Issue count: **3**
- HTML: `generated-playwright/reports/existing-framework/playwright-framework-alignment.html`
  - **medium**: PageObject/locator folder not detected — Create/use pageObjects/<PageName>.objects.ts and keep locators separate from test specs.
  - **medium**: Inline locators inside specs — RCA/self-healing should prefer pageObjects/pages/helper files; edit specs only when unavoidable.
  - **low**: Trace collection not visible in Playwright config — Enable trace: 'on-first-retry', screenshot/video on failure through approved config update.

## Object repository locator audit
- Locator definitions found: **1704**
- Object/page/locator files scanned: **66**
- Static/snapshot matched: **1291**
- Need live Playwright MCP/page-state verification: **413**
- HTML: `generated-playwright/reports/existing-framework/object-repository-locator-audit.html`

## Inline locator warnings
Some specs appear to call locators directly. Self-healing will still prefer moving fixes into page/pageObject/helper layers.
