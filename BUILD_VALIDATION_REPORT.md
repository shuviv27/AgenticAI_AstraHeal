# AstraHeal AI v0.7.2 Build Validation Report

## Scope

Reliable Plain-English RCA evidence routing across generated and existing Playwright execution paths.

## Validation summary

- Python 3.11 compatibility scan: Passed
- Python compilation: Passed
- VM startup validation: Passed
- Full pytest suite: 103 passed
- Full unittest suite: 57 passed
- Generated-framework RCA handoff: Passed
- Existing-framework RCA handoff: Passed
- Latest-run precedence: Passed
- Playwright test-level error/stack retention: Passed
- Safe-fix inventory mirroring: Passed
- FastAPI application import: Passed
- Registered FastAPI routes: 180
- Critical RCA and self-healing routes: Present
- GUI JavaScript syntax: Passed
- SQLite clean-schema check: Passed
- Fresh ZIP extraction validation: Passed

## Behaviour verified

A failed Playwright execution stored in `generated-playwright/reports/failed-tests.json` is now visible in the Plain-English RCA report and can be used by Explain, safe-fix planning and failed-only rerun.

A newer successful execution replaces older failure evidence and produces a clear no-failures report rather than stale RCA.
