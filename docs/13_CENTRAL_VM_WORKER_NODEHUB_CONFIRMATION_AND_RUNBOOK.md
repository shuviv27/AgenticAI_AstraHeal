# Central VM + Worker VM Node-Hub Confirmation and Runbook

This build keeps the existing enterprise node-hub model and strengthens it.

## Confirmed architecture

- Central VM remains the controller/brain/source of truth.
- Central VM can also execute tests as a real worker through the built-in `Central-VM-Worker` entry.
- Worker VMs/VDIs run lightweight polling agents.
- Worker agents execute browser tests from the Central VM shared framework path or from their configured workspace.
- AI/RAG/RCA/self-healing/code patches/reports/AI memory remain centralized on the Central VM unless explicitly changed.
- Worker VMs do not need AI keys for the recommended mode.
- Stable failures are retried immediately before RCA/self-healing.
- RCA/self-healing is now started in parallel after stable failure, so the execution worker can continue its next assigned script.
- Failed tests receive a final rerun after RCA/self-healing has been applied.

## Recommended mode for your organization

Use this mode when you connect to VDIs/VMs through RDP and the AUT is reachable only from those machines:

```text
Runtime Mode: VM + Worker Agent
Execution target mode: Central VM + worker VMs
Include Central VM as worker: checked
Worker workspace mode: Central shared framework folder
AI heavy-lifting mode: central_brain_worker_evidence
Worker AI role: browser_mcp_evidence_only
Codex patch location: central_only
Immediate rerun attempts before RCA: 2
Auto apply AI fixes after stable failure: checked
```

## Example allocation

For 100 tests where Central VM should execute 50 and two worker VMs should execute 25 each:

```text
Central-VM-Worker=50
VM45=25
VM135=25
```

You can use worker names, hostnames, IPs, or agent IDs as long as they match online Runner Agents.

## Step-by-step setup

### 1. Prepare Central VM

1. Keep the AI solution and Playwright framework on the Central VM.
2. Start the GUI on the Central VM.
3. Open the GUI in browser from Central VM.
4. Select the framework path using the existing framework path field.
5. Select AI Provider in Start Here, normally `Codex CLI`.
6. Confirm the selected AI provider from the backend.

### 2. Share the Playwright framework from Central VM

Create a Windows shared folder for the Playwright framework, for example:

```text
\\10.20.5.10\AIQA_Frameworks\client-playwright-framework
```

Give the worker VM users read/write permission if reports/artifacts must be written back to the shared framework.

### 3. Create Worker Agent package from Central VM GUI

1. Go to Runner Agent / Worker setup area.
2. Create one token/package per worker VM, for example:
   - `VM45`
   - `VM135`
3. Download/copy each generated worker ZIP to the respective VM.

### 4. Start Worker Agent on each Worker VM/VDI

On each worker VM through RDP:

1. Extract worker ZIP, for example:

```text
D:\AI_QA_AGENT
```

2. Confirm `agent.env` points to Central VM GUI/backend, for example:

```text
AIQA_CONTROL_PLANE_URL=http://10.20.5.10:8080
```

3. Run:

```text
START_WORKER_AGENT_WINDOWS.cmd
```

4. Keep this window running.
5. In Central VM GUI, refresh runner agents and confirm workers are online.

### 5. Configure Run & Fix Tests tab

1. Select runtime as `VM + Worker Agent`.
2. Click `Find scripts in framework`.
3. Select only required executable tests from `tests/**/*.spec.ts`, `tests/**/*.test.ts`, etc.
4. In Central VM with worker node-hub section:
   - Execution target mode: `Central VM + worker VMs`
   - Include Central VM as worker: checked
   - VM/Worker Agent IDs/names/IPs: `VM45,VM135`
   - Central framework path visible from worker VMs: `\\10.20.5.10\AIQA_Frameworks\client-playwright-framework`
   - Immediate rerun attempts before RCA: `2`
   - Auto apply AI fixes after stable failure: checked
5. For custom allocation, enter:

```text
Central-VM-Worker=50
VM45=25
VM135=25
```

6. Click `Create node-hub plan`.
7. Review the test allocation per worker.
8. Click `Run node-hub execution`.
9. Use `Refresh node-hub status` during execution.
10. Use `Open node-hub report` for the consolidated report.

## Runtime behavior

For each worker allocation:

1. Worker runs one assigned test.
2. If it passes, worker moves to next test.
3. If it fails, the same worker retries it immediately based on configured retry count.
4. If it still fails after retries, Central VM starts RCA/self-healing in parallel.
5. Worker continues with its next assigned test instead of waiting for RCA/self-healing to complete.
6. After assigned tests finish, failed tests are rerun once after fixes.
7. If a test still fails after final rerun, it is added to human intervention.

## Reports and memory

Reports are written under the framework history area and mirrored to the Central VM report area:

```text
<framework>\.aiqa-history\reports\agentic-nodehub-report.html
<framework>\.aiqa-history\reports\agentic-nodehub-report.json
```

The active run state is also kept centrally so status refresh can show progress even when worker VMs are still running.

## Notes

- RDP is used by you to access the worker VMs and start the agent. The framework does not need to automate entering VM passwords.
- Worker agents use outbound polling to Central VM. This is easier for enterprise networks because Central VM does not need to directly open inbound sessions into every worker VM.
- For strict enterprise security, avoid storing VM passwords in the tool. Use normal organization-managed RDP/login methods and run the Worker Agent under the approved user/session.
