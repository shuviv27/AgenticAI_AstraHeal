# Excel Functional Testcase Generation and Validation Fix

**Build:** 0.4.4  
**Date:** 2026-07-23

## Incident addressed

Uploading an enterprise functional-test workbook produced ten normalized scenarios, but Playwright validation failed for all ten attempted specs and AstraHeal rolled back the change set.

Rollback worked as designed. The generation defect occurred before Playwright execution:

1. The placement scorer treated `pages/BasePage.ts` as a suitable business page object.
2. `BasePage.ts` contained exported helper functions after the class.
3. The old member insertion logic used the file's final closing brace instead of the exported class closing brace.
4. Generated page methods were inserted into a trailing helper function, creating invalid TypeScript.
5. Every generated spec imported the damaged page layer, so all ten `playwright test --list` validations failed together.

The workbook parser also interpreted some common enterprise headers weakly. `Test_Case` could be treated as title data, the source spelling `Summery` was not reliably mapped to title, continuation rows could lose context, and `Test Data` was not consistently carried into generated steps.

## Corrected workbook normalization

The XLSX/XLSM parser now recognizes common variants including:

```text
Test_Case
Test Case ID
Summery
Summary
Step Number
Step Description
Test Data
Expected Result
```

Rows are grouped by the latest non-empty testcase ID/title. Continuation rows retain the active testcase, step order, test data, and expected result.

For the reported workbook, AstraHeal identifies ten independent cases and preserves the source IDs. One source row contains `TS_04`; it is retained rather than silently rewritten to `TC_04`.

## Framework-aware output

For the repository-generated default framework:

```text
generated-playwright/
  playwright.config.ts     testDir: ./tests
  tests/
    generated/
  pages/
  pageObjects/
```

AstraHeal selects `tests/generated` when that established subfolder exists. It creates one spec per normalized testcase.

The placement policy now excludes architectural and abstract base files such as:

```text
BasePage.ts
AbstractPage.ts
PageBase.ts
```

A concrete business page is reused when a semantic match exists. When the framework has no matching Salesforce page, AstraHeal creates one reusable pair only:

```text
pages/SalesforcePage.ts
pageObjects/SalesforcePage.objects.ts
```

All generated specs reuse that pair. New support files are not created per testcase.

## Safe class modification

Member insertion now locates the exported class declaration and finds its matching closing brace while respecting strings and comments. Methods are inserted inside that class, not at the final brace in the file.

This protects files that contain helper functions, constants, or additional exports after the page class.

## Test-data and secret handling

Usable non-secret spreadsheet values are passed to generated methods. URLs are retained as test input. Credential-like fields are not persisted.

For Salesforce scenarios:

```text
username -> process.env.SALESFORCE_USERNAME
password -> process.env.SALESFORCE_PASSWORD
```

Raw username/password values are excluded from normalized testcase JSON, generated specs, HTML/JSON generation reports, and logs.

## Validation and rollback

Validation now has two stages:

1. Static TypeScript/JavaScript parser validation for every changed source/spec file.
2. Playwright `--list` validation when the selected framework has a local Playwright CLI and installed dependencies.

The static validator resolves either the framework-local TypeScript package or an installed global TypeScript package.

When either validation stage fails, transactional rollback remains mandatory:

- pre-existing page/locator files are restored;
- newly created specs are deleted;
- newly created support files are deleted;
- attempted files and diagnostics remain in the generation report;
- no partial framework change is committed.

## Regression coverage

Permanent tests cover:

- `Test_Case` and `Summery` header aliases;
- continuation-row grouping;
- step numbers, expected results, URLs, and test data;
- Salesforce credential conversion and secret redaction;
- default `tests/generated` placement;
- exclusion of `BasePage.ts` from business-page selection;
- creation of a single reusable Salesforce page/locator pair;
- safe class insertion when helper functions follow the class;
- existing multi-source, BDD, Jira/Confluence, recursive discovery, RCA, self-healing, distributed execution, and BrowserStack behavior.
