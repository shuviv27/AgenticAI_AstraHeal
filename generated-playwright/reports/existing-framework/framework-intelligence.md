# Existing Playwright Framework Intelligence

- Framework path: `C:\PROJECTS\qa_acima_testautomation_execution_fixed\qa_acima_fixed`
- Generated at: `2026-07-06T01:53:38`
- Spec count: **47**
- POM grade: **moderate** (65/100)

## Important mode decision
This mode bypasses requirement parsing, functional testcase generation, and generated Playwright script generation. It executes the provided framework in-place and uses failed-only RCA/self-healing when failures occur.

## Discovered scripts
```json
{
  "test": "playwright test --project=chromium --project=api --project=unit",
  "test:ui": "playwright test tests/ui --project=chromium",
  "test:api": "playwright test tests/api --project=api",
  "test:smoke": "playwright test tests/smoke --project=chromium --project=api",
  "test:smoke:ui": "playwright test tests/smoke/ui-smoke.spec.ts --project=chromium",
  "test:smoke:api": "playwright test tests/smoke/api-smoke.spec.ts --project=api",
  "test:smoke:all": "playwright test --grep @smoke --project=chromium --project=api",
  "test:regression": "playwright test --grep @regression --project=chromium --project=api",
  "test:headed": "playwright test --project=chromium --headed",
  "test:debug": "playwright test --project=chromium --debug",
  "test:report": "playwright show-report",
  "test:qa": "cross-env ENV=qa playwright test --project=chromium --project=api --project=unit",
  "test:stage": "cross-env ENV=stage playwright test --project=chromium --project=api --project=unit",
  "test:prod": "cross-env ENV=prod playwright test --project=chromium --project=api --project=unit",
  "test:bdd": "bddgen && playwright test --project=bdd-ui-chromium --project=bdd-api",
  "test:bdd:ui": "bddgen && playwright test --project bdd-ui-chromium",
  "test:bdd:api": "bddgen && playwright test --project bdd-api",
  "test:bdd:smoke": "bddgen && playwright test --project=bdd-ui-chromium --project=bdd-api --grep @smoke",
  "test:bdd:regression": "bddgen && playwright test --project=bdd-ui-chromium --project=bdd-api --grep @regression",
  "codegen": "playwright codegen",
  "install:browsers": "playwright install",
  "agent:analyze": "playwright test",
  "test:unit": "playwright test --project unit --reporter list",
  "test:unit:teams": "playwright test tests/unit/teams/ --project unit --reporter list"
}
```

## Directory model
```json
{
  "spec_dirs": [
    "e2e",
    "specs",
    "tests",
    "tests/api",
    "tests/mobile",
    "tests/smoke",
    "tests/ui",
    "tests/unit",
    "tests/unit/teams"
  ],
  "page_dirs": [
    "pages"
  ],
  "page_object_dirs": [],
  "fixture_dirs": [
    "fixtures"
  ],
  "test_data_dirs": [
    "test-data"
  ],
  "utility_dirs": [
    "agents/failure-analyzer/lib",
    "agents/failure-analyzer/utils",
    "step-definitions/common",
    "utils"
  ]
}
```

## Strict rules
- Bypass Requirement/Input/Testcase/Generated Playwright phases for this mode.
- Do not copy or overwrite the user's framework into generated-playwright.
- Execute the framework in-place from the provided folder.
- RCA and self-healing must use failed-tests inventory only.
- Patch failed specs and their imported page/pageObject/helper files only.
- Prefer PageObjects first, then page methods/BasePage/helpers; avoid raw locator fixes inside specs.
- Robust RCA uses five signals before patching: DOM diff, trace timing, HAR diff, fixture/seed diff, and cross-run flakiness frequency.
- Assertion updates are blocked unless the assertion drift classifier marks the change as cosmetic and above semantic threshold.

## Framework Intelligence V2
- HTML: `generated-playwright/reports/existing-framework/framework-intelligence-v2.html`
- RAG chunks indexed: **950**
- Coverage: architecture, technology stack, trigger flows, normal flows, backend/API/DB hints, test data validation, VDI/VM/VPN hints.

## Playwright Framework Alignment
- Aligned for execution: **True**
- Issue count: **3**
- HTML: `generated-playwright/reports/existing-framework/playwright-framework-alignment.html`
  - **medium**: PageObject/locator folder not detected — Create/use pageObjects/<PageName>.objects.ts and keep locators separate from test specs.
  - **medium**: Inline locators inside specs — RCA/self-healing should prefer pageObjects/pages/helper files; edit specs only when unavoidable.
  - **low**: Trace collection not visible in Playwright config — Enable trace: 'on-first-retry', screenshot/video on failure through approved config update.

## Object repository locator audit
- Locator definitions found: **0**
- Object/page/locator files scanned: **0**
- Static/snapshot matched: **0**
- Need live Playwright MCP/page-state verification: **0**
- HTML: `generated-playwright/reports/existing-framework/object-repository-locator-audit.html`

## Inline locator warnings
Some specs appear to call locators directly. Self-healing will still prefer moving fixes into page/pageObject/helper layers.
