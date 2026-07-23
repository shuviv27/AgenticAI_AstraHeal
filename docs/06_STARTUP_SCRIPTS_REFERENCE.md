# Startup scripts reference

## Windows scripts

| Script | Use case | Bind host |
|---|---|---|
| `START_GUI_LOCAL_WINDOWS.cmd` | Local PC only | `127.0.0.1` |
| `START_GUI_CENTRAL_VM_WINDOWS.cmd` | VM177 only | `0.0.0.0` |
| `START_GUI_VM_WITH_WORKERS_WINDOWS.cmd` | VM177 + VM45/VM135 workers | `0.0.0.0` |
| `START_WORKER_AGENT_WINDOWS.cmd` | VM45/VM135 worker | N/A |

Each `.cmd` calls its matching `.ps1` script with execution-policy bypass.

## Mac/Linux scripts

| Script | Use case |
|---|---|
| `START_GUI_LOCAL_MAC.sh` | Local Mac only |
| `START_GUI_CENTRAL_VM_MAC.sh` | Central host / Mac host |
| `START_GUI_VM_WITH_WORKERS_MAC.sh` | Central host + workers |
| `START_WORKER_AGENT_MAC.sh` | Worker on Mac/Linux |

Run once:

```bash
chmod +x *.sh
```

## Direct Python commands

```powershell
python RUN_GUI_FIRST.py --host 127.0.0.1 --port 8080
python RUN_GUI_FIRST.py --host 0.0.0.0 --port 8080
python RUN_WORKER_AGENT.py --env worker-agent.env
```

## Why a few scripts remain under `scripts/ai`

The root folder is cleaned. A few Codex helper `.cmd` files remain under `scripts/ai` because the GUI uses them for the **Fresh Codex login** button. They are not general startup scripts.
