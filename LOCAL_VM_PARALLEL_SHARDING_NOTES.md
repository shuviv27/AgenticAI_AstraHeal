# Local PC / Central VM Parallel Browser Sharding Enhancement

This build keeps the existing single-machine execution button unchanged and adds an optional local/VM parallel execution path under **Run & Fix Tests -> Local PC / Central VM execution**.

## New behavior

- **Run chosen tests on this machine** remains the existing safe single-process behavior.
- **Run chosen tests in local/VM parallel shards** splits the selected `tests/**` Playwright spec/test files into local browser shards on the same PC/VM.
- The field **Tests per local browser instance/shard** controls chunk size.
  - Example: 20 selected tests with value `5` creates 4 parallel browser shards:
    - shard 1: tests 1-5
    - shard 2: tests 6-10
    - shard 3: tests 11-15
    - shard 4: tests 16-20
- Each shard runs with `--workers=1`, so parallelism comes from multiple browser processes, not Playwright workers inside a shard.
- Headed mode is preserved, so visible browser windows are launched when **Visible browser / headed mode** is selected.

## Report and RCA behavior

- Each local shard writes to a unique artifact folder under the framework:
  - `reports/existing-framework/distributed-runs/<run-id>/<shard-id>/`
- A consolidated distributed report is written to:
  - `.aiqa-history/reports/distributed-execution-report.html`
- Failed-only RCA/self-healing inventory is refreshed from failed local shards only.

## Existing behavior preserved

- Feature files under `features/**` remain excluded from executable script discovery.
- Worker node-hub execution remains separate and unchanged.
- AI provider inheritance from Start Here is unchanged.
- Existing single-machine execution is not converted to parallel mode unless the new local/VM parallel button is used.
