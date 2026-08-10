# AstraHeal AI v0.6.7 — Executable Playwright Generation Fix

## Corrected issues

- Removed `stepValue("scenario", "step_n")` from generated specs.
- Generated readable named scenario data (`data.username`, `data.firstName`, `data.expectedLeadStatus`).
- Persisted uploaded workbook credentials to a Git-ignored local runtime file during generation.
- Added an automatic TypeScript runtime environment loader.
- Added scenario-specific environment preflight before browser launch.
- Prevented generic prose outcomes from becoming literal text assertions.
- Improved semantic target extraction for instructions such as "Top rightside..., Click New Lead".
- Improved provisional assertion locators so concrete values such as `New`, `Web`, and `Testlead Simsamta` are used.
- Preserved browser grounding, Playwright MCP/codegen evidence, Page Object generation, validation, rollback, execution, RCA, LangGraph, LangSmith, SQLite memory, distributed execution, and cancellation.

## Attached workbook validation

```text
Scenarios generated:                    10
Named-data specs:                       10
stepValue occurrences:                   0
Page methods:                           91
Locator definitions:                    89
POM contract issues:                     0
TypeScript syntax diagnostics:           0
Git-ignored local credential file:      created
Runtime credential loading:             passed
Raw credentials in tracked TS/spec:      0
```

The private Salesforce AUT was not reachable from the build environment, so verified live locator coverage must be smoke-tested on the Central VM/VDI. Browser grounding is enabled in the generation route and will use the uploaded workbook credentials on that environment.
