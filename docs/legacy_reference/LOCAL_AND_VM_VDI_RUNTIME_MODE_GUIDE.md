# Local + VM/VDI Runtime Mode Guide

This build supports both operating styles without removing existing features.

## Mode 1: Local PC Mode
Use this when you want everything on one machine: GUI, Docker, Codex/Ollama, Playwright Web, API tests, RCA, self-healing and reports.

### Start
Windows:
```powershell
START_AI_QA_GUI_LOCAL_WINDOWS.cmd
```
Mac/Linux:
```bash
./START_AI_QA_GUI_LOCAL_MAC.sh
```

Open:
```text
http://127.0.0.1:8080
```

Inside GUI:
1. Open **Runtime Mode**.
2. Select **Local PC**.
3. Click **Save Runtime Mode**.
4. Click **Check Local Machine Readiness**.
5. Start Docker stack only after Docker Desktop is running.
6. Connect Codex/Ollama.
7. Run Web/API/Existing Framework/RCA/Self-Healing flows.

## Mode 2: VM Control Plane Mode
Use this when a stable VM hosts the GUI, Docker, RAG, reports and API tools. Users open the GUI from their VDIs.

### Start on VM
Windows:
```powershell
START_AI_QA_GUI_VM_CONTROL_PLANE_WINDOWS.cmd
```
Mac/Linux:
```bash
./START_AI_QA_GUI_VM_CONTROL_PLANE_MAC.sh
```

Open on VM:
```text
http://127.0.0.1:8080
```

Open from VDI:
```text
http://<VM-IP>:8080
```

Inside GUI:
1. Open **Runtime Mode**.
2. Select **VM Control Plane** or **Hybrid**.
3. Enter VM public URL, for example `http://10.20.30.40:8080`.
4. Click **Save Runtime Mode**.
5. Open **Enterprise Stack** and start Docker on the VM.
6. Use **Runner Agents** only if execution/fixing must happen inside a user's VDI.

## Mode 3: VDI Agent Mode
Do not run the full repo in each VDI unless needed. The VDI should normally run only the small agent package downloaded from the VM GUI.

Flow:
1. Start GUI on VM.
2. Open GUI from VDI.
3. Go to **Runner Agents**.
4. Create token.
5. Download VDI Agent package.
6. Extract package inside VDI.
7. Run `START_VDI_RUNNER_AGENT_WINDOWS.cmd` inside that VDI.

## Important GUI behavior
Readiness checks are now advisory, not hard blockers. Buttons remain enabled so users can troubleshoot locally even when Docker or Codex is not ready. Individual actions may still fail if their required tool is missing.

## Recommended choice
- Local laptop/developer PC: **Local PC**
- Shared enterprise VM: **VM Control Plane**
- VM plus user-specific browser/Codex execution from VDI: **Hybrid**
