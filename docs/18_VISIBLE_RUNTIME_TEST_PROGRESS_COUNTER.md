# Visible runtime test-case progress counter

This build makes the Local/VM parallel runtime test-case counter visible in the GUI during execution.

## Where to see it

Open **Run & Fix Tests** and use **Local PC / Central VM execution → Optional: Local/VM parallel browser sharding**.

When you click **Run chosen tests in local/VM parallel shards**, the live counter appears in two places:

1. Directly below the main progress bar at the top of the GUI:
   - `Runtime test progress: 0/210`
   - `Runtime test progress: 1/210`
   - `Runtime test progress: 10/210`
   - `Runtime test progress: 210/210`
2. Inside the **Runtime test progress** box under the Local/VM parallel browser sharding section.

## Implementation notes

- The backend now runs the long distributed execution through FastAPI's threadpool so the browser can poll `/api/astraheal/distributed/status` while Playwright is still running.
- The GUI polls status every 1.5 seconds during Local/VM parallel execution and updates the visible test-case counter.
- The counter is based on Playwright test-case count, not only spec-file count.
- Per-shard Playwright progress lines such as `[1/210]` are captured and persisted into run state and consolidated reports.
- Retry progress lines are clamped so the counter never goes above the total test-case count.
- Existing execution, RCA, self-healing, failed-only rerun, distributed failed-only rerun, and report paths remain unchanged.
