# AstraHeal AI - Clean Startup + Worker Agent + AI Full-Control Framework Fix

Start here.

## Windows Central VM with workers

```powershell
cd C:\AstraHealAI
python scripts\validate_vm_startup.py
START_GUI_VM_WITH_WORKERS_WINDOWS.cmd
```

Open:

```text
http://127.0.0.1:8080/astraheal-ai
```

## Windows worker VM

```powershell
copy configs\worker-agent.vm45.example.env worker-agent.env
notepad worker-agent.env
START_WORKER_AGENT_WINDOWS.cmd
```

## AI provider

Go to **Start Here > AI connection**, select provider, then click:

```text
Backend-confirm selected AI provider
```

OpenAI/DeepSeek use API keys. Codex requires `codex login`.

## Full-control framework fixing

For real Playwright TypeScript framework issues, use:

```text
AI full-control framework fix
```

This creates backups, modifies impacted files, blocks unsafe skip/only/fixme changes, reruns build/list checks, and reports changed files.

Read:

```text
docs/11_AI_FULL_CONTROL_FRAMEWORK_FIX.md
```
