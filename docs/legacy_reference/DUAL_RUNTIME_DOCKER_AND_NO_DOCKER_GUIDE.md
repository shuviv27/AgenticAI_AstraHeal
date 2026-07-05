# Dual Runtime Guide: Docker Runtime and No-Docker Host Runtime

This build supports two equal runtime engines without removing any existing capability.

## Runtime engines

### Mode 1: Docker Runtime
Use this when Docker Desktop / Docker Engine is approved and stable.

The GUI controls Docker Compose services, Docker API runners, API mock tools, observability services, RCA, self-healing, RAG, reports, Web Playwright and API automation.

### Mode 2: No-Docker Host Runtime
Use this when Docker is blocked, unstable, or not approved on client VMs/VDIs.

The same GUI controls host-based services using normal machine tools:

- Python for GUI/RCA/RAG/orchestration
- Node.js/npm/npx for Playwright Web/API TypeScript execution
- JDK/Maven for Rest Assured Java API automation
- Git for branch/workspace operations
- Codex CLI or Ollama for AI/RCA/self-healing
- Local folders for RAG, logs, job queue, artifacts and reports

## What remains same in both modes

- Same GUI at `127.0.0.1:8080` or `http://<VM-IP>:8080`
- Same Web Playwright flow
- Same API Playwright TS/JS flow
- Same Rest Assured Java flow
- Same Existing Framework Control
- Same API Automation Control
- Same RAG indexing and framework intelligence
- Same RCA and self-healing guardrails
- Same failed-only rerun strategy
- Same VM/VDI Runner Agent communication
- Same HTML/JSON/JUnit reports
- Same Codex/Ollama connection surface

## Local PC: Docker Runtime

1. Extract project to `C:\AI_QA\AdvancedAIAutomation`.
2. Start Docker Desktop.
3. Run `START_AI_QA_GUI_LOCAL_WINDOWS.cmd`.
4. Open `http://127.0.0.1:8080`.
5. Runtime Mode:
   - Deployment topology: `Local PC`
   - Runtime engine: `Docker Runtime`
6. Click `Save Runtime Mode`.
7. Click `Verify prerequisites`.
8. Click `Start selected runtime` from Dashboard or Enterprise Stack.
9. Click `Connect Codex/Ollama`.
10. Use Existing Framework Control, API Automation, or full Jira/SRS/PDF pipeline.

## Local PC: No-Docker Host Runtime

1. Extract project to `C:\AI_QA\AdvancedAIAutomation`.
2. Run this if tools are already installed:
   - `START_AI_QA_GUI_NO_DOCKER_WINDOWS.cmd`
3. If tools are missing and client IT allows host installation, run:
   - `powershell -ExecutionPolicy Bypass -File scripts\host-runtime\INSTALL_HOST_RUNTIME_WINDOWS.ps1 -All`
4. Check host tools:
   - `powershell -ExecutionPolicy Bypass -File scripts\host-runtime\CHECK_HOST_RUNTIME_WINDOWS.ps1`
5. Open GUI at `http://127.0.0.1:8080`.
6. Runtime Mode:
   - Deployment topology: `Local PC`
   - Runtime engine: `No-Docker Host Runtime`
   - Docker/Host runtime detail: `No Docker - host tools only`
7. Click `Save Runtime Mode`.
8. Click `Check No-Docker Readiness`.
9. Click `Start Host Services`.
10. For Playwright projects, run `npm install` and `npx playwright install` inside the framework folder or use the provided Playwright browser install script.
11. For Rest Assured projects, run `mvn test` once to warm dependencies.
12. Run Codex login if AI patching is needed:
    - `codex login` or `codex login --device-auth`
13. Execute/RCA/self-heal from GUI.

## Client VM/VDI: Docker Runtime on VM

Use when Docker is approved on the central VM.

1. Install/extract full solution on the VM.
2. Start Docker Desktop / Docker Engine on VM.
3. Run `START_AI_QA_GUI_VM_CONTROL_PLANE_WINDOWS.cmd` on VM.
4. Open from VM: `http://127.0.0.1:8080`.
5. Open from VDI: `http://<VM-IP>:8080`.
6. Runtime Mode:
   - Deployment topology: `VM Control Plane` or `Hybrid`
   - Runtime engine: `Docker Runtime`
7. Start Docker stack from GUI.
8. If execution must happen inside VDI browser, create/download/start the VDI Runner Agent.
9. Select the VDI Agent in GUI and run execution/fix/RCA jobs.

## Client VM/VDI: No-Docker Host Runtime on VM + VDI Agent

Recommended for restricted client environments where Docker is difficult.

### VM setup

1. Install approved host tools on VM:
   - Python 3.11/3.12
   - Git
   - Node.js 20/22
   - Java 17/21
   - Maven 3.9+
   - Codex CLI or Ollama if central AI is approved
2. Extract solution on VM, for example:
   - `D:\AI_QA\AdvancedAIAutomation`
3. Run:
   - `START_AI_QA_GUI_NO_DOCKER_VM_WINDOWS.cmd`
4. Open from VM:
   - `http://127.0.0.1:8080`
5. Open from VDI:
   - `http://<VM-IP>:8080`
6. Runtime Mode:
   - Deployment topology: `Hybrid`
   - Runtime engine: `No-Docker Host Runtime`
   - Docker/Host runtime detail: `No Docker - host tools only`
7. Click `Save Runtime Mode`.
8. Click `Check No-Docker Readiness`.
9. Click `Start Host Services`.

### VDI setup

1. Open VM GUI from VDI browser: `http://<VM-IP>:8080`.
2. Go to Runner Agents.
3. Create Agent Token.
4. Download VDI Agent Package.
5. Extract on VDI, for example: `D:\AI_QA_AGENT`.
6. Keep user framework workspace on VDI, for example:
   - `D:\AI_QA_WORKSPACE\client-web-playwright`
   - `D:\AI_QA_WORKSPACE\client-api-playwright`
   - `D:\AI_QA_WORKSPACE\client-api-restassured`
7. Run Codex login inside VDI if patching should happen in user workspace:
   - `codex login` or `codex login --device-auth`
8. Start VDI Agent:
   - `START_VDI_RUNNER_AGENT_WINDOWS.cmd`
9. Confirm agent is online in GUI.
10. Existing Framework Control:
    - Execution target: selected VDI Agent
    - Framework path: VDI workspace path
11. Execute, RCA, apply patch and rerun failed-only from GUI.

## Host Runtime scripts

- `scripts/host-runtime/CHECK_HOST_RUNTIME_WINDOWS.ps1`
- `scripts/host-runtime/INSTALL_HOST_RUNTIME_WINDOWS.ps1`
- `scripts/host-runtime/START_HOST_SERVICES_WINDOWS.ps1`
- `scripts/host-runtime/STOP_HOST_SERVICES_WINDOWS.ps1`
- `scripts/host-runtime/INSTALL_PLAYWRIGHT_BROWSERS_WINDOWS.ps1`
- `scripts/host-runtime/FREE_COMMON_PORTS_WINDOWS.ps1`

## Important enterprise recommendation

Keep both runtime engines available.

- Use Docker Runtime where Docker is approved and stable.
- Use No-Docker Host Runtime where Docker, WSL2, nested virtualization or Docker image pulls are blocked.
- Use Hybrid VM + VDI Agent when AUT works smoothly only from VDI browser/network.
