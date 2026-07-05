# Playwright TypeScript Generator - Decoupled Runbook

## Purpose

Focused Module 2 for new/existing Playwright TypeScript framework generation, execution, RCA, self-healing and failed-only reruns.

## Docker and No-Docker

The module keeps the same dual runtime foundation as the enterprise pipeline. Use Docker when available, or No-Docker Host Runtime when Docker is blocked by client policy.

## Local PC End-to-End

1. Install approved tools or run `scripts/host-runtime/INSTALL_HOST_RUNTIME_WINDOWS.ps1 -All`.
2. Start GUI with `START_MODULE_GUI_WINDOWS.cmd`.
3. Open `http://127.0.0.1:8080`.
4. Choose `Local PC` and runtime engine.
5. Save runtime mode.
6. Check readiness.
7. Run module-specific actions.
8. Review output and reports.

## Client VM/VDI End-to-End

1. Setup this module on central VM.
2. Start GUI on VM using `START_MODULE_GUI_VM_WINDOWS.cmd`.
3. Users open `http://<VM-IP>:8080` from VDI.
4. Choose `Hybrid VM + VDI Agent` only if VDI must execute browser/Codex work.
5. Create/download VDI Agent from Runner Agents tab when needed.
6. Execute module actions from the same VM-hosted GUI.

## Guardrails

- Do not remove shared runtime/RCA/self-healing modules.
- Do not mix Module 1 and Module 2 responsibilities in GUI.
- Module 1 produces approved functional testcases.
- Module 2 consumes approved functional testcases and creates/extends Playwright TypeScript automation.
