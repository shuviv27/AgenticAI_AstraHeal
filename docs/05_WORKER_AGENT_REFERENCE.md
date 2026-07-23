# Worker Agent reference

The worker agent is required on VM45/VM135 when using distributed execution.

## What worker agent does

- Registers with Central VM.
- Sends heartbeat/status.
- Polls Central VM for jobs.
- Executes Playwright commands in assigned framework path.
- Returns stdout/stderr/result to Central VM.

## What worker agent does not do

- It does not run the GUI.
- It does not need AI keys.
- It does not independently patch source code.
- It does not own RCA/self-healing memory.

## Main files

```text
RUN_WORKER_AGENT.py
START_WORKER_AGENT_WINDOWS.cmd
START_WORKER_AGENT_WINDOWS.ps1
START_WORKER_AGENT_MAC.sh
worker-agent.env.example
configs/worker-agent.vm45.example.env
configs/worker-agent.vm135.example.env
```

## Minimum worker prerequisites

```powershell
python --version
node -v
npm -v
npx --version
git --version
npx playwright install
```

For headed browser execution, keep the RDP/Horizon/Omnissa session active and unlocked.

## UNC shared framework path on Windows

The worker agent supports Central VM shared paths such as:

```text
\\10.252.41.177\AIQA_Frameworks\client-playwright-framework
```

On Windows, `cmd.exe` can be unreliable when a UNC path is used directly as the current directory. The worker agent handles this by using `pushd` internally for UNC paths before running Playwright commands.
