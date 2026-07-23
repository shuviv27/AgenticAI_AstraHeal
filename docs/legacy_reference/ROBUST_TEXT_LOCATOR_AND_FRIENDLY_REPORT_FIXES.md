# Robust Text Locator and Friendly Report Fixes

This enhancement fixes failures where simple visible text such as `Shop with Acima Leasing`, `Shop In-store`, and `Shop Online` was not identified reliably on modern/dynamic pages.

## What changed

1. **Robust text matching**
   - Whitespace-insensitive matching.
   - Unicode hyphen normalization.
   - Body visible text fallback for split headings and marketing components.

2. **Button/link fallback**
   - If a visual button is actually implemented as an `<a>` link, the framework tries link, button, text, and CSS text fallback.
   - This specifically improves modern design-system components where visual role and DOM role differ.

3. **Better functional testcase parsing**
   - Compound requirements such as `Verify “Shop In-store” and “Shop Online” buttons are visible` now generate two separate steps.
   - Hero heading requirements generate a simple step for `Shop with Acima Leasing` and another for the lease-to-own description.

4. **Markdown functional testcases**
   - Every generated testcase JSON now also creates a simple Markdown file:
     `testcases/<source>/<feature>/<feature>.scenarios.md`
   - The GUI shows this Markdown preview first so business users can review simple steps before generating Playwright.

5. **User-friendly failure messages**
   - The enterprise HTML report now includes a simple explanation before technical stack traces.
   - Examples: wrong URL, text/button not found, strict locator ambiguity, permission issue, navigation issue.

6. **Existing architecture preserved**
   - Specs still call page methods only.
   - Page methods still use pageObjects first.
   - Robust helpers only act as fallback inside reusable page classes/BasePage.

## Correct pattern preserved

```text
generated-playwright/tests/generated/<feature>.spec.ts
  -> generated-playwright/pages/<Feature>Page.ts
      -> generated-playwright/pageObjects/<Feature>Page.objects.ts
```

## Recommended validation

```powershell
cd generated-playwright
npm config set registry https://registry.npmjs.org/
npm install --registry=https://registry.npmjs.org/
npx playwright install chromium
npm run build
$env:BASE_URL="https://www.acima.com/en"
npx playwright test tests/generated/acima.spec.ts --project=chromium --headed
```
