# Module 2 - VM/VDI Horizon/Omnissa Setup and User-Selected Test Execution

## Purpose

This Module 2 build is designed for an existing client-owned Playwright TypeScript framework. The user can:

- Learn the existing framework with AI/RAG.
- Select exactly which test scripts should run.
- Run selected scripts in headed or headless mode.
- Run RCA, Microsoft Playwright MCP-assisted locator checks, guarded self-healing, and failed-only rerun.
- Save action history, RCA evidence, fix plan, patch history, and rerun results into AI memory.

## New user-selected test execution flow

1. Open the GUI.
2. Go to **Existing Framework**.
3. Paste the existing Playwright framework root path.
4. Select browser/project and headed/headless mode.
5. Click **Learn this framework with AI**.
6. Go to **Run & Fix Tests**.
7. Use optional filters:
   - Module/folder filter, for example `tests/specs/login`.
   - Include text/file filter, for example `login, checkout, ALL`.
   - Exclude text/file filter, for example `wip, old, draft`.
8. Click **Find scripts in framework**.
9. Tick only the scripts that should run.
10. Click **Run chosen tests**.

Unselected scripts are intentionally skipped.

## Recommended Horizon/Omnissa + RDP-to-VM design

In this organization pattern, users launch their VDI using Horizon/Omnissa. From inside the VDI, the user connects to a central VM through RDP using the VM IP, username and password.

Recommended architecture:

- Horizon/Omnissa VDI: user desktop, AUT/browser access, Codex user login if patching happens in the VDI.
- Central VM: stable control plane, Module 2 GUI, RAG index, action history, reports, job/message coordination.
- Existing Playwright framework: keep it where execution actually happens. If AUT works only from VDI, clone or keep the framework in the VDI workspace and use the VDI Agent. If VM can also access AUT reliably, the framework may stay on VM and execute from VM.

## Best setup for AUT working smoothly from VDI

Use Hybrid VM + VDI Agent mode.

On VM:

1. Extract Module 2 repo to `D:\AI_QA\Module2_ExistingFramework_AI`.
2. Start the GUI with `START_MODULE_GUI_VM_WINDOWS.cmd`.
3. Open `http://127.0.0.1:8080` on VM.
4. From the VDI browser, open `http://<VM-IP>:8080`.
5. Choose runtime mode:
   - Deployment topology: `VM + VDI Agent`.
   - Runtime type: `No-Docker Host Runtime` or `Docker Runtime` if approved.
6. Click **Save runtime choice**.
7. Click **Check this machine**.
8. Click **Start required services**.

On VDI:

1. Open the VM GUI URL in browser: `http://<VM-IP>:8080`.
2. Download/create the VDI Runner Agent from the GUI if used.
3. Extract the agent to `D:\AI_QA_AGENT`.
4. Clone or copy the existing Playwright framework to `D:\AI_QA_WORKSPACE\client-playwright-framework`.
5. Install Node/npm dependencies in the framework if needed.
6. Run `codex login` inside the VDI only if Codex patching should happen from the VDI.
7. Start the VDI Agent.
8. In Module 2 GUI, set existing framework path to the VDI workspace path when the selected VDI Agent executes the job.

## Best setup when VM can access AUT directly

Use VM Control Plane mode.

On VM:

1. Clone/copy the existing Playwright framework to `D:\AI_QA_WORKSPACE\client-playwright-framework`.
2. Run `npm install` in that framework.
3. Run `npx playwright install` if browsers are missing.
4. Start Module 2 GUI.
5. Paste the VM framework path into the GUI.
6. Use **Find scripts in framework** and **Run chosen tests**.

The VDI is then only a remote browser/control screen for the VM-hosted GUI.

## Rule of thumb

- If the AUT opens only from the VDI browser, execute tests from the VDI Agent.
- If the AUT opens from the VM browser, execute tests directly on the VM.
- Keep the GUI centralized on VM to preserve one source of reports, memory, RCA history, and job state.
- Do not run two different GUI servers unless you intentionally want two separate systems.
