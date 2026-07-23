# AstraHeal AI Module-2: Agentic Node-Hub Master-Worker + Parallel RCA/Self-Healing Runbook

This build adds an agentic node-hub execution mode without removing the existing manual execution, RCA, self-healing, approval-popup, rollback, distributed report, history, Docker/No-Docker, Local PC and VM/VDI features.

## 1. What changed

### Master VM is also a worker

The central VM can now act as both:

```text
VM-1 = control plane + GUI + AI/RAG memory + consolidated report + worker
VM-2 = worker agent
VM-3 = worker agent
VM-4 = worker agent
```

In the GUI, enable:

```text
Include central VM-1 as worker = checked
Master worker display name = VM-1-Master-Worker
```

### User-controlled script allocation

The user can now tell the system exactly how many scripts each worker should execute:

```text
VM-1-Master-Worker=25
VM-02=25
VM-03=25
VM-04=25
```

If allocation is blank, tests are split evenly across available workers.

### Agentic parallel execution logic

Each worker runs its assigned tests one by one.

For each test:

```text
Run test
  ↓
If passed → move to next test
  ↓
If failed → rerun immediately on same worker
  ↓
If failed again → rerun second time
  ↓
If still failed → mark stable failure, start RCA/self-healing in parallel, then continue next assigned test
```

After the worker finishes its assigned tests:

```text
Rerun failed tests after fixes
  ↓
If still failing → mark human intervention required
```

This avoids waiting for 1000 tests to finish before RCA starts.

## 2. LangChain / LangGraph style architecture

This build does not force a heavy LangChain/LangGraph dependency into the runtime. Instead, it implements the same orchestration pattern using deterministic Python state machines so it works on locked-down VMs/VDIs.

Conceptually, it maps to LangGraph like this:

```text
START
  → PlanShardAllocationNode
  → WorkerExecutionNode per VM in parallel
      → RunSingleTestNode
      → ImmediateRerunDecisionNode
      → StableFailureNode
      → ParallelRCANode
      → SelfHealingNode
      → ContinueNextTestNode
  → WorkerFinalRerunNode
  → ConsolidatedReportNode
  → END / HumanInterventionNode
```

Graph branches are independent per worker, and failed-test RCA/self-healing branches are started while other workers continue execution.

## 3. VM setup

### Central VM-1

1. Extract the Module-2 solution.
2. Install Python dependencies:

```powershell
python -m pip install -r requirements.txt
```

3. Start the GUI:

```powershell
START_MODULE_GUI_VM_WINDOWS.cmd
```

4. Open:

```text
http://127.0.0.1:8080
```

5. Make sure worker VMs can open:

```text
http://<VM-1-IP>:8080
```

6. Select:

```text
Runtime topology = Hybrid VM + VDI Agent / Worker Agent
Runtime engine = No-Docker Host Runtime or Docker Runtime based on approval
AI provider = Codex CLI - default patching provider
```

### Worker VMs / VDIs

1. Create runner-agent token/package from the VM-1 GUI.
2. Copy the worker package to every VM/VDI, for example:

```text
D:\AI_QA_AGENT
```

3. Configure `agent.env`:

```text
AIQA_CONTROL_PLANE_URL=http://<VM-1-IP>:8080
AIQA_AGENT_NAME=VM-02
AIQA_WORKSPACE_ROOT=D:\AI_QA_WORKSPACE
```

4. Ensure the same Playwright framework path exists or is mapped on each worker:

```text
D:\AI_QA_WORKSPACE\client-playwright-framework
```

5. Install framework dependencies inside the framework folder:

```powershell
cd D:\AI_QA_WORKSPACE\client-playwright-framework
npm install --registry=https://registry.npmjs.org/
npx playwright install
```

6. Start worker agent:

```powershell
D:\AI_QA_AGENT\START_VDI_RUNNER_AGENT_WINDOWS.cmd
```

## 4. GUI workflow

1. Open **Existing Framework**.
2. Enter the external framework path.
3. Click **Deep learn this framework with AI**.
4. Click **Find scripts in framework**.
5. Select tests.
6. In **Distributed node-hub execution**, enter workers and allocation.
7. Enable **Include central VM-1 as worker**.
8. Set **Immediate rerun attempts before RCA = 2**.
9. Enable **Auto apply AI fixes after stable failure** only when Codex is configured and backups/rollback are acceptable.
10. Click **Create agentic node-hub plan**.
11. Click **Run agentic node-hub execution**.
12. Click **Refresh agentic node-hub status** during execution.
13. Open the framework-local report:

```text
<framework>\.aiqa-history\reports\agentic-nodehub-report.html
```

## 5. AI provider setup

### Codex CLI - recommended default for direct fixes

On the machine where fixes are applied:

```powershell
codex login
codex doctor --json
```

In GUI:

```text
AI provider = Codex CLI - default patching provider
```

### Ollama

```powershell
ollama serve
ollama pull llama3
```

`.env`:

```text
OLLAMA_HOST=http://localhost:11434
OLLAMA_MODEL=llama3
```

### DeepSeek API

`.env`:

```text
DEEPSEEK_API_KEY=<your-approved-key>
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat
```

### OpenAI API

`.env`:

```text
OPENAI_API_KEY=<your-approved-key>
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-4.1-mini
```

OpenAI/DeepSeek are used for RCA and fix-proposal guidance in this build. Direct file writing is still Codex-backed so the local/VM/VDI workspace remains auditable and rollback-safe.

## 6. Reports and history

Source-of-truth report lives in the external framework:

```text
<framework>\.aiqa-history\reports\agentic-nodehub-report.html
<framework>\.aiqa-history\reports\agentic-nodehub-report.json
<framework>\.aiqa-history\agentic-nodehub-runs\<run-id>\run-state.json
```

The central solution keeps GUI mirrors only:

```text
<solution>\generated-playwright\reports\existing-framework\agentic-nodehub-report.html
<solution>\.qa-cache\agentic-nodehub-runs\<run-id>\run-state.json
```

## 7. Safety model

The new agentic mode still preserves enterprise safety:

```text
Backup before applying fixes
Changed files are recorded
Rollback remains available
Human intervention is recorded when final rerun still fails
Direct destructive test hiding such as test.skip/test.only/test.fixme remains blocked by policy
Manual RCA/self-healing buttons remain available for troubleshooting
```
