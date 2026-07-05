# Common-Cause RCA, One-Retry Policy and Distributed Failed-Only Validation

This build adds the requested enterprise RCA/self-healing enhancements without replacing the existing execution, reporting, rollback, local/VM parallel, or worker node-hub flows.

## What changed

1. **One retry only before RCA**
   - Agentic node-hub execution now clamps immediate retry attempts to one.
   - The GUI default is now `1` instead of `2`.
   - If the first failure and retry failure have the same observable failure type, the run state records it as a stable same-type failure and treats it as a component/flow fix candidate.

2. **Common-cause RCA across workflows**
   - RCA now groups failed workflows by observable failure kind plus component/locator/action signature.
   - Example: if multiple tests fail on the same `Continue` button, the report prioritizes fixing the shared pageObject/page method/helper first.
   - This is shown in the RCA and self-healing reports.

3. **RCA memory/cache**
   - Common-cause findings are persisted in:
     - `generated-playwright/.qa-cache/existing-framework/common-cause-memory.json`
     - `<framework>/.aiqa-history/common-cause-memory.json`
     - `generated-playwright/reports/existing-framework/common-cause-memory.html`
   - Future RCA loads this cache as historical memory.

4. **Parallel RCA while execution continues**
   - Node-hub execution keeps its existing behavior: after one retry fails, RCA/self-healing starts on the Central VM while the worker moves to the next assigned test.
   - Workers remain evidence/execution only. Source patching remains Central VM only.

5. **Distributed failed-only validation after self-healing**
   - Added a new GUI button: **Run failed tests distributed**.
   - This keeps the old sequential **Run failed tests again** button unchanged.
   - The distributed rerun reads the latest failed-test inventory and splits only those failed specs into local/central VM browser shards using the same tests-per-shard setting.

6. **Faster AI patch apply after approval**
   - Codex patch prompts now prioritize common-cause/shared-component files first.
   - Large approved workspaces are capped in the prompt to reduce apparent stuck/waiting behavior.
   - Full policy validation and rollback still audit changed files.
   - Default Codex patch timeout is reduced to 300 seconds and can be overridden with `ASTRAHEAL_CODEX_PATCH_TIMEOUT_SECONDS`.

## Existing features preserved

- Normal existing-framework execution
- Local/VM parallel browser sharding
- Worker node-hub execution
- Central VM-only AI heavy lifting
- Failed-only RCA/self-healing
- Human approval and rollback
- Report 404-safe Playwright landing page
- Existing sequential failed-only rerun
