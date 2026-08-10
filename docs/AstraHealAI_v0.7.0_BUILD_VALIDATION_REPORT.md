# AstraHeal AI v0.7.0 — Build Validation Report

**Build:** `0.7.0`  
**Focus:** Page-state-aware Playwright locator capture and multi-stage login reliability

## Summary

This build corrects locator generation when the same native submit control appears in multiple page states with different visible names. It also rejects undefined role/name evidence, preserves CSS selectors, requires unique live matches, and improves runtime diagnostics.

## Validation results

| Validation | Result |
|---|---|
| Python compilation | Passed |
| Automated tests | 93 passed |
| SmartLocator TypeScript syntax transpilation | Passed |
| locatorFactory TypeScript syntax transpilation | Passed |
| Two-stage login browser simulation | Passed using `/usr/bin/chromium` |
| Attached workbook scenario generation | 10 of 10 specs generated |
| Generated Page Object contract | 0 issues |
| Undefined role/value scan | 0 findings |
| SQLite packaged runtime records | 0 |

## Two-stage login simulation evidence

The same DOM control (`id=Login`, `name=Login`, `type=submit`) was captured on two pages.

| Stage | Accessible name | Primary locator | Stable fallbacks | Verified |
|---|---|---|---|---|
| Username | Log In to Sandbox | role=button/name=Log In to Sandbox | `#Login`, `input[name="Login"]` | Yes |
| Password | Log In | role=button/name=Log In | `#Login`, `input[name="Login"]` | Yes |

Both states produced the same stable control signature.

## Attached workbook isolated result

```text
Scenario count:             10
Generated spec count:       10
POM contract:               Passed
Undefined locator roles:    None
Undefined locator values:   None
Stable login selector:      Present
```

## Important limitation

The private Salesforce sandbox could not be reached from the build environment. Exact AUT verification must be executed from the user's Central VM/VDI. The build does not claim live verification against that private environment.
