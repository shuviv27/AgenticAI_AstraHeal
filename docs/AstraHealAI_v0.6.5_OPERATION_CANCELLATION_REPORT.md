# AstraHeal AI v0.6.5 — Operation Cancellation Enhancement

**Build:** `0.6.5`  
**Date:** 28 July 2026

## Purpose

This release adds a user-controlled way to stop a backend operation that is taking longer than expected. Cancellation applies to autonomous LangGraph runs, Playwright generation and execution, framework analysis and repair, npm/npx/build commands, Codex CLI work, Graphify extraction, local parallel shards and distributed Worker Agent jobs.

## GUI behaviour

While an operation is active, the main progress panel displays:

- elapsed execution time;
- an expected-duration selector: 5, 10, 15, 30, 60 or 120 minutes;
- a warning when the selected expected duration is exceeded;
- a red **Stop current operation** button.

The expected duration is a warning threshold, not an automatic timeout. The user explicitly decides whether to stop the operation.

## Cancellation flow

```text
User clicks Stop current operation
        ↓
GUI requests backend cancellation
        ↓
Backend marks the operation as cancelling
        ↓
AstraHeal-owned child process trees are terminated
        ↓
Python loops stop at cancellation checkpoints
        ↓
Remote Worker Agent jobs receive cancel_requested
        ↓
Run is recorded as cancelled/aborted, not failed
```

## Backend APIs

```text
GET  /api/operations/active
GET  /api/operations/{operation_id}
POST /api/operations/{operation_id}/cancel
POST /api/agentic/runs/{run_id}/cancel
GET  /api/runner-agents/job/status
POST /api/runner-agents/job/{job_id}/cancel
```

Cancellable GUI requests carry:

```text
X-AstraHeal-Operation-Id
X-AstraHeal-Operation-Label
X-AstraHeal-Expected-Seconds
```

## Managed subprocesses

The command runner now registers AstraHeal-owned subprocesses and launches them in an isolated process group. A cancellation request terminates the owned process tree, including child Node.js/browser processes where applicable.

Managed paths include:

- Playwright test execution and test discovery;
- generated-test TypeScript validation and optional execution;
- npm, npx and TypeScript build commands;
- Codex CLI execution;
- Graphify extraction;
- BrowserStack launcher commands;
- local/Central-VM parallel shards;
- existing-framework execution and validation.

## LangGraph cancellation

Each autonomous run is also registered as an operation. Cancellation:

- sets the run cancellation flag;
- stops the graph at the next node/stream checkpoint;
- terminates any subprocess owned by the active node;
- records the run as `cancelled` in SQLite;
- streams an aborted status to the GUI.

## Distributed Worker Agent cancellation

Worker Agent jobs carry the parent operation ID. A v0.6.5 worker polls the Central VM for cancellation while its command is running. When cancellation is requested, the worker terminates its command process tree and returns `cancelled`.

**Deployment note:** Worker packages created by older AstraHeal versions must be regenerated and redeployed to support active remote cancellation.

## Repository safety

- Cancellation never reports an aborted operation as a passed execution.
- Partial, unvalidated generation or framework-repair output is not accepted.
- Existing backup, validation and rollback controls remain active.
- A complete source output that was safely committed before a later test-run cancellation remains available for RCA and rerun.
- Only processes started and registered by AstraHeal are forcefully terminated.

## Validation summary

| Validation | Result |
|---|---|
| Full automated test suite | 78 passed |
| Real long-running child command cancellation | Passed; terminated before the 30-second command completed |
| Operation registry active/completed state | Passed |
| Operation status/cancel API JSON responses | Passed |
| Central-VM remote-job cancellation flag | Passed |
| GUI stop button and operation headers | Passed |
| Python compilation | Passed |
| GUI JavaScript syntax | Passed |
| FastAPI routes | 173 |

## Runtime limitations

- Cooperative Python work stops when it reaches a cancellation checkpoint; repository scans and graph loops now contain checkpoints.
- An external service call that has already left AstraHeal's process boundary may still complete remotely, although AstraHeal stops waiting and cancels its owned local process.
- A separately opened interactive Codex login terminal is an authentication session and is not treated as an active backend AI run.
- Windows process-tree termination and live remote-VM cancellation should be verified once on the target Central VM/VDI after deployment.
