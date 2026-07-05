# RCA Failed-Only Rerun Strategy

This build adds a time-saving RCA/self-healing execution loop.

## Problem solved

Earlier, after RCA and self-healing, the user had to rerun the complete active suite. For large Jira/SRS batches this wastes time because only the scripts that failed need immediate validation after a patch.

## New behavior

After any Playwright execution, the pipeline writes:

```text
 generated-playwright/reports/failed-tests.json
```

This file contains:

- failed spec files
- failed feature names
- failed test titles when Playwright JSON results are available
- the previous execution mode
- the native HTML report location

After RCA/self-healing, use:

```text
RCA & Self-Healing -> Re-run Failed Only - Headed
RCA & Self-Healing -> Re-run Failed Only - Headless
```

The pipeline then:

1. reads `failed-tests.json`;
2. archives the previous full-run HTML report to `generated-playwright/reports/full-run-before-failed-only-rerun/`;
3. reruns only the failed spec files;
4. updates the native Playwright HTML report at `generated-playwright/reports/html/index.html` with the failed-only rerun result;
5. writes a consolidated rerun summary at `generated-playwright/reports/failed-only-consolidated-report.html`.

## What this preserves

- Original full-run report is archived before failed-only rerun.
- Native Playwright report remains available for the failed-only rerun.
- Enterprise report includes the failed-only rerun payload.
- The RCA/self-healing flow still patches only allowed framework files.

## Recommended workflow

```text
1. Execute generated tests.
2. If failures occur, open the native Playwright report.
3. Analyze Root Cause.
4. Propose Self-Healing Fix.
5. Apply Self-Healing Patch.
6. Re-run Failed Only - Headed or Headless.
7. Open native Playwright report for rerun and consolidated failed-only summary.
```

## Why this saves time

For a 1000-test suite, if only 7 specs fail, the first post-patch validation executes only those 7 specs. Once the failed-only rerun passes, a full regression run can still be triggered later as a final confidence check.
