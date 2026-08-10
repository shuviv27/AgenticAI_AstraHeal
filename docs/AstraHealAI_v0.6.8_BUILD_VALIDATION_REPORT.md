# AstraHeal AI v0.6.8 — Build Validation Report

**Build:** `0.6.8`  
**Validation date:** 28 July 2026

## Scope

This release corrects false Playwright validation failures caused by evaluating runtime credentials and generic spreadsheet placeholders during `playwright test --list`.

## Validation results

| Validation | Result |
|---|---|
| Full Python regression suite | 86 passed |
| Python compilation | Passed |
| GUI JavaScript syntax | Passed |
| FastAPI application import | Passed |
| Registered FastAPI routes | 173 |
| Generation route | Present |
| Cancellation routes | Present |
| Runtime preflight deferred to `test.beforeAll` | Passed |
| Required credential classification | Passed |
| Optional business-data classification | Passed |
| Runtime-data-only Playwright discovery failure retention | Passed |
| Spec → page method → locator contract | Passed |
| TypeScript source parsing | Passed |
| Attached workbook generation | Passed |
| Raw credentials in generated TypeScript | 0 |
| SQLite clean schema | Reset before packaging |
| ZIP integrity | Passed after packaging |

## Attached workbook validation

```text
Scenarios:                             10
Generated specs:                       10
Specs using test.beforeAll:             10
Top-level runtime assertions:            0
Required credential variables:          20
Optional non-sensitive overrides:         7
Generated optional default bindings:      9
Page methods:                            91
Locator definitions:                     89
POM contract issues:                      0
TypeScript parse diagnostics:             0
Raw credentials in tracked TypeScript:    0
```

Required variables are now limited to the ten username/password pairs. `APPOINTMENT_TYPE`, dates, time, product and activity date are optional overrides and no longer stop Playwright discovery.

## Environment limitation

The build environment could not access the private Salesforce AUT and did not have a complete local Playwright npm installation. Structural generation was validated with the repository contract validator, TypeScript parser, regression tests, and attached-workbook generation. Run `npm install`, `npx playwright install chromium`, and one Central VM/VDI smoke test to validate live AUT behaviour and browser-grounded locators.
