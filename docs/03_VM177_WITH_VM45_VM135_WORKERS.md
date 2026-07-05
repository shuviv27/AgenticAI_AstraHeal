# Workflow 3: VM177 Central VM + VM45/VM135 worker VMs

Recommended enterprise setup.

```text
VM177 = Central AstraHeal AI GUI/backend + AI provider + framework source-of-truth
VM45  = Worker agent + browser execution
VM135 = Worker agent + browser execution
```

## Start Central VM177

```powershell
cd C:\AstraHealAI
python scriptsalidate_vm_startup.py
START_GUI_VM_WITH_WORKERS_WINDOWS.cmd
```

Open:

```text
http://127.0.0.1:8080/astraheal-ai
```

From worker VMs:

```text
http://10.252.41.177:8080/astraheal-ai
```

## Share framework from VM177

Example source-of-truth framework:

```text
D:\AI_QA_WORKSPACE\client-playwright-framework
```

Share `D:\AI_QA_WORKSPACE` as:

```text
AIQA_Frameworks
```

Worker-visible UNC path:

```text
\10.252.41.177\AIQA_Frameworks\client-playwright-framework
```

## Create worker tokens

In GUI on VM177:

1. Open Runner Agents / Worker Agents section.
2. Create token for `VM45-worker`.
3. Create token for `VM135-worker`.
4. Copy each token to that worker's `worker-agent.env`.

## Start VM45 worker

Copy the AstraHealAI folder or a generated worker package to VM45.

Create `worker-agent.env` from `configs/worker-agent.vm45.example.env`:

```powershell
cd D:\AstraHealAIWorker
copy configs\worker-agent.vm45.example.env worker-agent.env
notepad worker-agent.env
START_WORKER_AGENT_WINDOWS.cmd
```

## Start VM135 worker

```powershell
cd D:\AstraHealAIWorker
copy configs\worker-agent.vm135.example.env worker-agent.env
notepad worker-agent.env
START_WORKER_AGENT_WINDOWS.cmd
```

## Validate workers

On VM45 and VM135:

```powershell
Test-NetConnection 10.252.41.177 -Port 8080
dir "\10.252.41.177\AIQA_Frameworks\client-playwright-framework"
node -v
npm -v
npx playwright install
```

Workers do not need OpenAI/DeepSeek keys or Codex login. AI provider configuration stays on VM177.
