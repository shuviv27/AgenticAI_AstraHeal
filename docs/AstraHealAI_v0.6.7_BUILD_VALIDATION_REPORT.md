# AstraHeal AI v0.6.7 — Build Validation Report

**Build:** `0.6.7`  
**Validation date:** 28 July 2026

## Scope

This release converts generated Playwright specs from synthetic step-number lookups to readable, executable named scenario data. It also creates a Git-ignored local runtime credential file from uploaded workbook credentials and validates each scenario's required environment before Playwright launches a browser.

## Validation results

| Validation | Result |
|---|---|
| Full Python regression suite | 83 passed |
| Python compilation | Passed |
| GUI JavaScript syntax | Passed |
| FastAPI application import | Passed |
| Registered FastAPI routes | 173 |
| Generation route | Present |
| Operation cancellation routes | Present |
| Named test-data generation | Passed |
| `stepValue` removal | Passed |
| Local credential-file generation | Passed |
| Runtime environment loader execution | Passed |
| Scenario-specific preflight | Passed |
| Concrete-versus-prose assertion handling | Passed |
| Spec → page method → locator contract | Passed |
| TypeScript source parsing | Passed |
| Attached workbook generation | Passed |
| SQLite clean schema | Reset before packaging |

## Attached workbook validation

```text
Scenarios:                         10
Generated specs:                   10
Named-data specs:                  10
stepValue occurrences:              0
Page methods:                      91
Locator definitions:               89
POM contract issues:                0
TypeScript diagnostics:             0
Local runtime credential file:     created
Runtime credential loader:         passed
Raw credentials in tracked TS:      0
```

## Runtime data behaviour

- Workbook credentials are held in volatile backend memory after source loading.
- During generation, those credentials are written to `.env.astraheal.local` in the selected framework.
- `.env.astraheal.local` is automatically added to `.gitignore`.
- `testData/astraheal.runtime-env.ts` loads the file automatically.
- Each spec calls `assertRequiredEnvironment(...)` before declaring tests, so missing scenario data is reported before browser launch.
- CI systems should use their secret manager and the generated variable names instead of copying the local file.

## Target-environment limitation

The private Salesforce AUT and its MFA flow were unavailable in the build environment. The browser-grounding agent, Playwright MCP readiness and codegen-compatible replay path remain enabled, but final verified locator coverage and the `Log In to Sandbox` transition must be smoke-tested on the target Central VM/VDI.
