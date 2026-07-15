# AstraHeal AI — Multi-Agent Playwright Automation Studio

Clean enterprise build for developing, executing, diagnosing, and fixing existing Playwright TypeScript automation frameworks.

## Start here

Read:

```text
docs/00_README_CLEAN_STARTUP.md
```

## Root startup scripts

| Scenario | Windows | Mac/Linux |
|---|---|---|
| Local PC only | `START_GUI_LOCAL_WINDOWS.cmd` | `./START_GUI_LOCAL_MAC.sh` |
| Central VM only | `START_GUI_CENTRAL_VM_WINDOWS.cmd` | `./START_GUI_CENTRAL_VM_MAC.sh` |
| Central VM + worker VMs | `START_GUI_VM_WITH_WORKERS_WINDOWS.cmd` | `./START_GUI_VM_WITH_WORKERS_MAC.sh` |
| Worker VM agent | `START_WORKER_AGENT_WINDOWS.cmd` | `./START_WORKER_AGENT_MAC.sh` |

## Recommended VM setup

```text
VM177 = Central VM: GUI/backend, AI provider, framework source-of-truth, RCA/self-healing, reports
VM45  = Worker VM: worker agent + browser execution
VM135 = Worker VM: worker agent + browser execution
```

Workers do not need OpenAI/DeepSeek/Codex keys. Workers need the worker agent, Node/npm/npx, Playwright browsers, AUT access, and framework path access.

## Open GUI

```text
http://127.0.0.1:8080/astraheal-ai
```

From worker/VDI when VM177 is central:

```text
http://<VM177-IP>:8080/astraheal-ai
```

## Main docs

- `docs/01_LOCAL_PC_WORKFLOW.md`
- `docs/02_CENTRAL_VM_ONLY_WORKFLOW.md`
- `docs/03_VM177_WITH_VM45_VM135_WORKERS.md`
- `docs/04_AI_PROVIDER_CONFIGURATION.md`
- `docs/05_WORKER_AGENT_REFERENCE.md`
- `docs/06_STARTUP_SCRIPTS_REFERENCE.md`
- `docs/07_VALIDATION_AND_TROUBLESHOOTING.md`
- `docs/31_ADD_NEW_TESTS_MULTI_SOURCE_BDD_ATLASSIAN.md`

Legacy reference documents are moved under:

```text
docs/legacy_reference/
```
