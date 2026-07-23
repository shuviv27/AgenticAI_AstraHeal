# Failed Workflow GUI and Two-Iteration Guard Fix

This build makes the RCA/self-healing workflow visibly test-level on the GUI and protects the iterative failed-only rerun pipeline.

## Fixed behavior

1. **Explain failed tests** now displays a simple test-by-test summary on the GUI:
   - `spec.ts -> test passed`
   - `spec.ts -> test failed - reason: ...`

2. **Create safe fix plan** now displays a specific safe plan based on the current failed inventory:
   - failed spec
   - failed test title/line when available
   - plain-English failure reason
   - safest fix area, such as pageObjects/locator repository, page method, helper, fixture, or manual review

3. **Fix failed tests safely** approval popup now shows failed test cases, not only spec files, plus the expected patch area and safe files.

4. **Run failed tests again** and **Run failed tests distributed** use the latest remaining failed-test ledger after each rerun iteration. A second failed-only rerun uses remaining failed test cases when exact line evidence is available instead of rerunning full spec files.

5. AstraHeal stops after **one original run + two RCA/self-healing/rerun iterations**. If failures remain, it blocks further automatic patch/rerun cycles and writes a manual-review report with the remaining failed specs/tests.

## Guardrail

Existing first-run execution, distributed execution, runtime progress, Playwright report generation, failed-only rerun reports, RCA, self-healing, rollback, and combined first-run+runs report behavior are preserved.
