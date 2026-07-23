# Distributed Node-Hub Execution + Parallel RCA Runbook

## Goal
Run a large existing Playwright/Cucumber automation framework across multiple VM/VDI workers from one central VM control plane, while RCA/self-healing triage starts as soon as any shard fails.

## Architecture

```text
Central VM-1 = AstraHeal AI control plane / GUI / RAG / history / consolidated report
VM-2..VM-6 or VDIs = Runner workers / browser execution / AUT access / optional Codex fixing
```

The central VM creates a node-hub run plan:

```text
100 tests + 5 workers = 5 shards of 20 tests each
```

Each worker receives a shard job through the runner-agent polling channel. The agent executes from the existing framework folder and returns stdout/stderr/status to the central VM. When a worker finishes, the central VM immediately creates a parallel RCA event for that shard instead of waiting for all shards to complete.

## Configuration steps

### On central VM-1
1. Extract the Module-2 solution.
2. Run `START_MODULE_GUI_VM_WINDOWS.cmd`.
3. Open `http://127.0.0.1:8080` on VM or `http://<VM-IP>:8080` from worker VDI/VM browser.
4. Select `Hybrid VM + VDI Agent` or VM worker mode.
5. Select Docker or No-Docker runtime depending on client approval.
6. Start required services.
7. Create one runner token for each worker VM/VDI.
8. Download/copy the runner-agent package to each worker.

### On every worker VM/VDI
1. Extract `VDI_AGENT_PACKAGE_<agent>.zip`, for example to `D:\AI_QA_AGENT`.
2. Clone/copy the same existing Playwright framework to a consistent path, for example `D:\AI_QA_WORKSPACE\client-framework`.
3. Run `npm install` and `npx playwright install` once in the framework folder.
4. Ensure AUT opens from that worker machine.
5. Start `START_VDI_RUNNER_AGENT_WINDOWS.cmd`.
6. Confirm the agent appears online in central VM GUI.

## Running distributed execution
1. Deep learn the framework with AI.
2. Find scripts/features in framework.
3. Select scripts/features.
4. Enter browsers/projects and shard count.
5. Enter worker IDs/names or leave blank to use all online workers.
6. Click **Create node-hub run plan**.
7. Click **Run distributed on worker VMs/VDIs**.
8. Use **Refresh distributed run / parallel RCA status** while workers are running.
9. Open the framework-local consolidated distributed report.

## Framework-local source-of-truth reports
Reports are written into the existing framework, not only the AI solution repo:

```text
<existing-framework>/.aiqa-history/reports/distributed-execution-report.html
<existing-framework>/.aiqa-history/reports/distributed-execution-report.json
<existing-framework>/.aiqa-history/distributed-runs/<run-id>/run-state.json
```

The AI solution keeps a GUI mirror under `generated-playwright/reports/existing-framework` only for convenience.

## Parallel RCA behavior
When any shard completes:

```text
worker shard completes/fails
→ central VM receives job completion
→ failed specs/features are extracted from stdout/stderr
→ shard RCA classification is created
→ event is saved to .aiqa-history and central AI memory
→ consolidated report is refreshed
```

This reduces waiting time for large suites because RCA/self-healing triage begins while other shards are still executing.

## Supported framework styles
- Playwright Test frameworks: `tests/**/*.spec.ts`, `tests/**/*.specs.ts`, `tests/**/*.test.ts`.
- BDD/Cucumber Playwright frameworks: `features/**/*.feature` with `cucumber.js` and `src/step-definitions` or `step-definitions`.
- Hybrid frameworks containing both specs and features.

## Important limitations
- True parallel browser execution requires active worker machines/VDIs with Node/npm/Playwright dependencies installed.
- Headed browser execution requires an interactive desktop session, not a Windows background service session.
- Automatic fix application should occur on the machine/workspace where the code is editable and Codex/Ollama is authenticated.
