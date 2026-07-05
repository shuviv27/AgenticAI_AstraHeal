# Central-source worker execution architecture

This build supports the enterprise design where the **Central VM is the source of truth** and worker VMs only execute browser/test commands.

## Recommended architecture

```text
Central VM-1
  - AstraHeal AI / Module-2 GUI
  - FastAPI backend
  - RAG and AI memory
  - Playwright framework source-of-truth
  - RCA and self-healing engine
  - Fix backup / rollback
  - consolidated reports
  - worker job queue
  - optional master worker execution

Worker VM-2 / VM-3 / VM-4
  - lightweight runner agent
  - Node.js/npm/npx
  - Playwright browsers
  - AUT access
  - access to Central VM shared framework path
```

The worker VM does **not** need a permanent Git clone of the Playwright framework.

## Why the worker still needs to see framework files

Playwright tests are Node.js programs. The process that launches the browser must be able to read:

- `package.json`
- `playwright.config.ts`
- test files
- page classes
- locators/pageObjects
- fixtures
- utilities
- `node_modules` or installed dependencies

So a worker VM cannot run a Playwright test from only an IP address. It needs one of these workspace strategies:

| Strategy | Framework source of truth | Worker has permanent copy? | Recommended? |
|---|---|---:|---:|
| Central shared framework folder | Central VM | No | Yes |
| Ephemeral run snapshot | Central VM | No, temporary only | Good for restricted shares |
| Worker local copy | Each worker | Yes | Previous behavior / fallback |
| Remote-browser-only | Central VM | No | Advanced, requires framework fixture changes |

This build implements the **Central shared framework folder** as the recommended default while preserving the previous worker-local behavior.

## GUI configuration

In **Run & Fix Tests → Distributed node-hub execution → Central-source worker execution model**:

```text
Worker execution source = Central shared framework folder - recommended
Central framework path visible from worker VMs = \\10.20.5.10\AIQA_Frameworks\client-playwright-framework
Store RCA, self-healing, AI memory and consolidated reports on Central VM only = checked
```

Example allocation:

```text
master-local=20
qa-worker-10-20-5-31=20
qa-worker-10-20-5-32=20
qa-worker-10-20-5-33=20
```

## Central shared folder setup

On Central VM-1, keep the real framework at:

```text
D:\AI_QA_WORKSPACE\client-playwright-framework
```

Share it as, for example:

```text
\\10.20.5.10\AIQA_Frameworks\client-playwright-framework
```

Recommended share permissions:

- read access to source files
- write access only to safe runtime folders if needed:
  - `.aiqa-history`
  - `test-results`
  - `playwright-report`
  - framework-specific report folders
- do not expose unrelated folders
- use a domain/service account where possible

## Worker VM setup

On each worker VM:

1. Log in once by RDP or enterprise tool.
2. Confirm it can open AUT in browser.
3. Install Node.js and Git if required by the framework.
4. Install Playwright browsers:

```powershell
npx playwright install
```

5. Confirm it can access the central shared framework path:

```powershell
dir "\\10.20.5.10\AIQA_Frameworks\client-playwright-framework"
```

6. Start the runner agent:

```powershell
D:\AI_QA_AGENT\START_VDI_RUNNER_AGENT_WINDOWS.cmd
```

## Runtime behavior

When a test is assigned to a worker:

1. Central VM queues a job for that worker.
2. Worker agent picks up the job by outbound polling.
3. Worker command uses `pushd` to enter the central shared framework path.
4. Worker runs one Playwright/Cucumber command.
5. Playwright browser opens on the worker VM.
6. The result is posted back to Central VM.
7. Central VM performs RCA/self-healing against the central source-of-truth framework.
8. Reports and AI memory remain centralized.

## Why this avoids multiple framework copies

The worker does not need this permanent folder:

```text
D:\AI_QA_WORKSPACE\client-playwright-framework
```

The worker only needs permission to access:

```text
\\10.20.5.10\AIQA_Frameworks\client-playwright-framework
```

The framework remains physically on Central VM.

## Artifact collision protection

When multiple workers run from the same shared framework folder, the system sets per-worker artifact folders:

```text
.aiqa-history\worker-artifacts\<run-id>\<worker-id>\<phase-attempt-test>
```

This reduces conflict between parallel worker reports.

## Centralized RCA and self-healing

All RCA and self-healing still runs on Central VM using:

```text
<central-framework>\.aiqa-history
<AI-solution-repo>\.qa-cache
<AI-solution-repo>\generated-playwright\reports\existing-framework
```

Worker VMs only execute tests and return stdout/stderr/status.

## When to use worker local framework copy

Use **Worker local framework copy** only when:

- SMB/UNC share is blocked
- executing from network share is too slow
- enterprise policy requires isolated local workspaces

This preserves the previous behavior and does not break old workflows.

## Using IP addresses instead of VM names

Worker names like `VM-2` are only friendly aliases. Real enterprise VMs can be identified by IP address.

In each worker agent's `agent.env`, set:

```text
AIQA_AGENT_NAME=qa-worker-10-20-5-31
AIQA_AGENT_IP=10.20.5.31
```

Then in the GUI you can use any of these in the Worker Agent IDs/names field or allocation box:

```text
qa-worker-10-20-5-31
10.20.5.31
```

Example allocation by IP:

```text
master-local=20
10.20.5.31=20
10.20.5.32=20
10.20.5.33=20
```

The system resolves the worker by `agent_id`, `agent_name`, `hostname`, or `ip_address`.
