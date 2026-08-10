# AstraHeal AI v0.7.2 — RCA Evidence Handoff Fix

## Problem

A failed Playwright run could be visible in the native report while the Plain-English RCA page displayed:

- No failed execution evidence is available yet
- None recorded
- No case-level failure evidence is stored yet

The cause was not the absence of a failure. AstraHeal had two report locations:

- Generated-framework execution: `generated-playwright/reports/failed-tests.json`
- Existing-framework execution: `generated-playwright/reports/existing-framework/failed-tests.json`

The Plain-English RCA route read only the second location. Generated-framework failures were therefore invisible to that report and to parts of the safe-fix handoff.

## Fix

v0.7.2 creates one common execution-evidence handoff across:

- Generated sequential execution
- Generated distributed execution
- Existing-framework execution
- Selected existing tests
- Native Playwright JSON retained inside a selected client framework

The newest execution inventory is authoritative. A newer successful run also replaces an older failure inventory, preventing stale RCA.

## Plain-English RCA behaviour

Immediately after execution, AstraHeal now prepares a report from the latest evidence. It includes:

- Spec file
- Test title
- Source line
- Playwright project
- Attempt count
- Actual error message and stack
- Failure category and confidence
- Plain-English explanation
- Safest fix layer and likely files
- Validation steps
- Self-healing safety decision

`Explain failed tests` can enrich the report with provider-assisted analysis, but a provider call is no longer required merely to show the real failed test and its error.

## Safe-fix connection

The latest common inventory is mirrored into the Existing Framework handoff used by:

1. Explain failed tests
2. Create safe fix plan
3. Apply approved safe fix
4. Rerun failed tests only
5. Rollback when validation becomes worse

## Stale evidence protection

The report chooses the newest execution by file modification time. It does not display an old failed run after a newer successful run.

## Validation

- Generated-framework failed inventory → Plain-English RCA: passed
- Existing-framework failed inventory → Plain-English RCA: passed
- Newest successful run overrides stale failure: passed
- Playwright JSON error/stack retention: passed
- Safe-fix inventory mirroring: passed
- Full pytest suite: 103 passed
- Full unittest suite: 57 passed
