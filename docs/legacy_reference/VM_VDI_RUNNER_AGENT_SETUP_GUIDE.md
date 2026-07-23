# VM + VDI Runner Agent Setup Guide

## Is the Runner Agents tab available?

Yes, in this build the GUI includes a **Runner Agents** tab.

Use it when the full AI QA platform is hosted on a stable VM, but browser execution and user-specific Codex fixes must happen inside each user's VDI/Horizon desktop.

## Is Docker Desktop required on each VDI?

No. The recommended setup keeps Docker on the VM. The VDI runs only a lightweight Python runner agent.

## Where does the full source code live?

The full AI QA solution lives on the VM. Users open the VM-hosted GUI from their VDI browser:

```text
http://<VM-IP>:8080
```

## Where does START_VDI_RUNNER_AGENT_WINDOWS.cmd run?

It runs **inside the VDI**, from the downloaded VDI Agent package.

Example VDI folder:

```text
D:\AI_QA_AGENT\START_VDI_RUNNER_AGENT_WINDOWS.cmd
```

## How does the VM know which VDI is connected?

The VM identifies each VDI by:

1. Agent token generated from the GUI
2. Agent ID
3. Agent name
4. VDI hostname
5. Windows username
6. Heartbeat timestamp

The VDI Agent uses outbound polling. This means the VDI calls the VM every few seconds and asks, "Do you have a job for me?" The VM does not need to open a direct connection into the VDI.

## Setup steps

### 1. Start GUI on VM

Run the GUI startup script on the VM and open:

```text
http://<VM-IP>:8080
```

### 2. Open Runner Agents tab

Go to:

```text
Runner Agents
```

### 3. Create token

Enter:

```text
Control Plane URL: http://<VM-IP>:8080
New Agent Name: <user-or-vdi-name>
VDI Workspace Root: D:\AI_QA_WORKSPACE
```

Click:

```text
Create Agent Token
```

### 4. Download VDI Agent package

Click:

```text
Download VDI Agent Package
```

Copy the ZIP to the VDI and extract it to:

```text
D:\AI_QA_AGENT
```

### 5. Start agent from VDI

Inside the VDI, run:

```text
D:\AI_QA_AGENT\START_VDI_RUNNER_AGENT_WINDOWS.cmd
```

### 6. Confirm online status

Back in the VM GUI:

```text
Runner Agents → Show Online Agents
```

The VDI should appear as online.

### 7. Run a job on the selected VDI

Use the simple job form first:

```text
Target Agent ID: copy from Show Online Agents
Working Directory: D:\AI_QA_WORKSPACE\client-web-playwright
Command: npx playwright test --project=chromium
```

Click:

```text
Create VDI Agent Job
```

The agent will run the command inside the VDI and upload stdout/stderr status back to the VM GUI.

## Recommended source-code model

For Codex fixes, the framework should be available inside the VDI as a Git clone:

```text
D:\AI_QA_WORKSPACE\client-web-playwright
D:\AI_QA_WORKSPACE\client-api-playwright
D:\AI_QA_WORKSPACE\client-api-restassured
```

This lets Codex patch the user's local branch safely.

## Important notes

- The VM hosts the heavy GUI, Docker, RAG, reports, and dashboards.
- The VDI runs local browser execution and user-specific Codex fixing.
- Docker Desktop is not required on the VDI.
- The VDI Agent package is small and generated from the VM GUI.
- If the VDI is non-persistent, put the agent and workspace on a persistent D: drive or persistent profile.
