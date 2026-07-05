# Dynamic Web Gap Analysis and Fixes

## Gaps found from the uploaded SRS

1. The requirement document is not a simple login flow. It contains multiple public website flows: home page, navigation, marketplace, mobile app links, external social links, footer/legal links, responsive checks, negative paths, and accessibility checks.
2. A basic text-step parser can incorrectly compress all requirements into one testcase. This build now creates one scenario per SRS requirement line.
3. Dynamic websites may not expose stable `data-testid` values. The framework now prefers `getByRole`, `getByText`, `getByLabel`, href/CSS fallback, and starter reusable pageObjects.
4. Menus and external links may open in the same tab or a new tab. BasePage now supports navigation and maybe-new-tab verification helpers.
5. Responsive/accessibility checks need Playwright-MCP assisted DOM exploration before final hardening. The repo now produces smoke-level executable methods and keeps enhancement points in page classes.

## Fixes added

- Added `samples/srs/acima_requirements.txt`.
- Added modern website parser rules in `qa_pipeline/parsers/source_parser.py`.
- Added dynamic locator strategy in `qa_pipeline/agents/phase3_reuse_aware_codegen/locator_strategy.py`.
- Added reusable modern web helpers in `generated-playwright/pages/BasePage.ts`.
- Added starter reusable Acima page object inventory in `generated-playwright/pageObjects/AcimaPage.objects.ts`.
- Added starter reusable Acima page methods in `generated-playwright/pages/AcimaPage.ts`.
- Added Docker + AI startup scripts for Windows/Mac.
- Added GUI sample loader for the Acima SRS.
- Added base URL support for CLI runs.

## Still expected to be improved after live Playwright-MCP exploration

- Exact menu opening behavior if the site uses hamburger/mega-menu overlays.
- Exact external App Store / Google Play labels if they are image-only links.
- Exact 404 message text if the site uses a custom error route.
- Accessibility assertions beyond smoke-level keyboard reachability.
- Store search/filter behavior on Marketplace after observing the live DOM.
