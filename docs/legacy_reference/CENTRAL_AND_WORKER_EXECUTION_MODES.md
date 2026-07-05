# Central VM and Worker VM execution modes

This build supports three explicit execution target modes without removing any existing Module-2 features.

## Mode 1: Central VM only

Use this when the user wants the central VM to run all selected tests by itself.

Configuration in GUI:

```text
Execution target mode = Central VM only
Central worker display name = Central-VM-Worker
Worker allocation = optional
```

Behavior:

```text
Central VM
  ├─ GUI / FastAPI control plane
  ├─ Playwright framework source of truth
  ├─ Browser execution
  ├─ RCA / self-healing
  ├─ AI memory
  └─ consolidated report
```

This mode is useful for smoke testing, small suites, debugging, or when worker VMs are not available.

## Mode 2: Central VM + worker VMs

Use this when the central VM should also execute tests along with worker VMs.

Configuration in GUI:

```text
Execution target mode = Central VM + worker VMs
Include central VM as worker = checked
VM/VDI Agent IDs or IP addresses = 10.20.5.31,10.20.5.32
```

Example allocation:

```text
Central-VM-Worker=25
10.20.5.31=25
10.20.5.32=25
10.20.5.33=25
```

Behavior:

```text
Central VM
  ├─ control plane + worker execution
  ├─ AI memory / RCA / self-healing
  └─ consolidated report

Worker VMs
  ├─ runner agent
  ├─ browser execution
  └─ send result events back to Central VM
```

This is the recommended mode when the central VM has enough CPU/RAM and browser access.

## Mode 3: Worker VMs only

Use this when the central VM should coordinate only and should not execute tests.

Configuration in GUI:

```text
Execution target mode = Worker VMs only
VM/VDI Agent IDs or IP addresses = 10.20.5.31,10.20.5.32,10.20.5.33
```

Behavior:

```text
Central VM
  ├─ GUI / control plane only
  ├─ RAG / RCA / self-healing coordination
  ├─ AI memory
  └─ reports

Worker VMs
  └─ browser/test execution
```

If no worker agents are online, this mode intentionally returns a configuration warning instead of silently falling back to central execution.

## Framework source strategy

The best enterprise setup remains central-source execution:

```text
Central VM framework path:
D:\AI_QA_WORKSPACE\client-playwright-framework

Worker-visible shared path:
\\10.20.5.10\AIQA_Frameworks\client-playwright-framework
```

Worker VMs execute from the shared central framework path or from a temporary/synchronized workspace, while RCA, self-healing, AI memory and consolidated reports remain centralized.

## What stayed unchanged

The following existing features remain available:

```text
Local PC Docker / No-Docker
VM/VDI Docker / No-Docker
central-source worker execution
worker-local fallback mode
basic distributed execution
agentic node-hub execution
parallel RCA/self-healing
runtime human approval popup
rollback
framework-local reports
combined reports
history and AI memory
AI provider selection
```
