# AstraHeal AI v0.4.4 Build Validation Report

**Build:** `0.4.4`  
**Validation date:** 2026-07-23  
**Primary fix:** Excel functional-test parsing, safe business-page placement, reusable page-object generation, and pre-Playwright TypeScript validation

## Reported failure reproduced

The supplied workbook was processed against a clean copy of the repository-generated default framework.

Observed source structure:

```text
Test_Case | Summery | Step Number | Step Description | Test Data | Expected Result
```

The workbook contains ten grouped testcases with continuation rows. One source ID is `TS_04`; AstraHeal preserves it rather than silently changing business data.

The v0.4.3 failure was reproduced and traced to the generated source layer, not to the workbook upload or rollback mechanism:

1. `pages/BasePage.ts` was selected as the best business page match.
2. The file contained helper exports after the `BasePage` class.
3. Generated methods were inserted at the file's final closing brace instead of the class closing brace.
4. Methods landed inside a helper function, making the TypeScript invalid.
5. All ten specs imported the damaged page layer, so Playwright `--list` failed for every attempted spec.
6. Transactional rollback correctly restored the framework.

## Corrected behavior

### Excel understanding

- Recognizes `Test_Case`, `Test Case ID`, `Summery`, `Summary`, `Step Number`, `Step Description`, `Test Data`, and `Expected Result` header variants.
- Groups continuation rows under the latest testcase ID/title.
- Preserves step order, source test data, per-step expected results, and scenario-level expected results.
- Infers the shared Salesforce application/page context from the workbook content.
- Produces one normalized scenario and one Playwright spec per testcase.

### Framework placement and reuse

- Uses the framework selected in **Existing Framework**.
- For the default framework, detects `testDir: './tests'` and reuses the established `tests/generated` folder.
- Excludes architectural/abstract base files such as `BasePage.ts`, `AbstractPage.ts`, and `PageBase.ts` from business-page selection.
- Reuses an existing concrete business page and linked locator repository when one matches.
- Creates only one reusable `SalesforcePage.ts` and `SalesforcePage.objects.ts` pair when no Salesforce-specific page already exists.
- All ten generated specs share the same page-object pair; support files are not duplicated per testcase.

### Safe source modification

- Finds the exported class declaration and its matching closing brace while respecting comments and quoted strings.
- Inserts generated members inside the actual class boundary.
- Does not patch trailing helper functions or unrelated exports.

### Test data and credential safety

- URLs and usable non-secret spreadsheet values are retained as test input.
- Salesforce username/password values are converted to:

```text
process.env.SALESFORCE_USERNAME
process.env.SALESFORCE_PASSWORD
```

- Raw credential values are excluded from normalized testcase JSON, generated specs, generation reports, and logs.

### Validation and rollback

Validation is now layered:

1. Static TypeScript/JavaScript parse validation checks every changed source/spec file.
2. Playwright `--list` runs when the selected framework has installed local Playwright dependencies.
3. Any failed stage restores existing files and deletes newly created source/spec files.

The static validator resolves either framework-local TypeScript or an installed global TypeScript package.

## Exact workbook verification

The supplied workbook was run through the corrected parser and generator in a clean copy of `generated-playwright`.

| Verification | Result |
|---|---:|
| Normalized testcases | **10** |
| Generated independent specs | **10** |
| Application/page context | **Salesforce** |
| Shared new business page files | **2** |
| Generated spec destination | `tests/generated` |
| Created reusable symbols | **184** |
| Reused symbols across scenarios | **322** |
| TypeScript/JavaScript parser diagnostics | **0** |
| Raw username/password present in generated output | **No** |
| `BasePage.ts` modified | **No** |

The source build intentionally does not include `node_modules`. Therefore an authenticated/local Playwright `--list` run was not available in the packaging environment. The exact generated source passed the TypeScript parser with zero diagnostics. On the user's installed default framework, the existing Playwright `--list` stage remains mandatory and rollback remains active if it reports a framework/runtime problem.

## Automated regression validation

| Validation | Result |
|---|---:|
| Complete Python regression suite | **39/39 passed** |
| Add New Tests regression group | **14/14 passed** |
| Existing recursive discovery/execution group | Passed |
| Explainable RCA/exact approval-scope group | Passed |
| Python compilation (`compileall`) | Passed |
| FastAPI application import | Passed |
| FastAPI route count | **152** |
| GUI inline JavaScript syntax (`node --check`) | Passed |
| Setuptools wheel build | Passed |
| Built wheel version | **0.4.4** |
| `openpyxl` wheel dependency | `openpyxl>=3.1,<4` |
| Final ZIP integrity | **Passed** |
| Clean extraction regression rerun | **39/39 passed** |

## New permanent regression coverage

1. Enterprise Excel aliases `Test_Case` and `Summery` are interpreted correctly.
2. Continuation rows preserve testcase context and step order.
3. Step data and URLs are used by generated calls.
4. Salesforce username/password values become environment variables and raw values are redacted.
5. The default framework uses `tests/generated` rather than writing broadly to `tests`.
6. `BasePage.ts` is not selected as a business page.
7. One reusable Salesforce page/object pair is created when required.
8. Generated page methods are inserted inside the exported class even when helper functions follow it.
9. Existing rollback, multi-source, Gherkin/BDD, Jira/Confluence MCP, recursive discovery, RCA/self-healing, sequential/distributed execution, and BrowserStack tests remain passing.

## Runtime output for the reported workbook

After successful generation on an installed default framework, expected paths are:

```text
generated-playwright/tests/generated/<feature>-<testcase-id>.spec.ts
generated-playwright/pages/SalesforcePage.ts
generated-playwright/pageObjects/SalesforcePage.objects.ts
generated-playwright/.aiqa-history/add-new-tests/<feature>-generation-report.json
generated-playwright/.aiqa-history/add-new-tests/<feature>-generation-report.html
```

A page/locator file is created only because the default framework does not already contain a concrete Salesforce-specific page. When such a page exists, AstraHeal reuses and extends it instead.
## Clean-package verification

A provisional source ZIP was extracted into a new directory and validated independently from the working tree:

- 39/39 regression tests passed;
- Python compilation passed;
- GUI inline JavaScript syntax passed;
- FastAPI imported with 152 routes;
- the exact uploaded workbook again produced ten specs under `tests/generated`;
- `SalesforcePage.ts` and `SalesforcePage.objects.ts` were created once and reused;
- `BasePage.ts` remained byte-for-byte unchanged;
- static TypeScript validation reported zero diagnostics;
- raw supplied username/password values were absent;
- Salesforce credential environment-variable references were present.

