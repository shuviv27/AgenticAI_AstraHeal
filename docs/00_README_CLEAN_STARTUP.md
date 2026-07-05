# AstraHeal AI clean startup guide

This build intentionally exposes only a small set of startup scripts at the project root.
Use these scripts only. The older confusing `START_AI_QA_*`, `START_MODULE_*`, and duplicate GUI startup scripts were removed from the root.

## Root scripts

| Scenario | Windows | Mac/Linux |
|---|---|---|
| Local PC only | `START_GUI_LOCAL_WINDOWS.cmd` | `./START_GUI_LOCAL_MAC.sh` |
| Central VM only | `START_GUI_CENTRAL_VM_WINDOWS.cmd` | `./START_GUI_CENTRAL_VM_MAC.sh` |
| Central VM + worker VMs | `START_GUI_VM_WITH_WORKERS_WINDOWS.cmd` | `./START_GUI_VM_WITH_WORKERS_MAC.sh` |
| Worker VM agent | `START_WORKER_AGENT_WINDOWS.cmd` | `./START_WORKER_AGENT_MAC.sh` |

Core Python entry points remain:

- `RUN_GUI_FIRST.py`
- `RUN_WORKER_AGENT.py`

Do not run old script names from previous builds.
