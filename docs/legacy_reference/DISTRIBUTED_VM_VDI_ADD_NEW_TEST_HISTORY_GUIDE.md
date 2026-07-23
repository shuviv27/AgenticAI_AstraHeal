# AstraHeal AI Module-2: Distributed VM/VDI, Add-New-Test, and History Guide

## 1. Distributed execution

Module-2 can split selected existing Playwright specs into shards and execute them across browsers or VDI agents.

Example: 50 specs, 5 shards, browsers = chromium, firefox, webkit, msedge, chrome.
The plan becomes 10 specs per shard.

### Modes

- Local/VM fallback: the VM executes shards sequentially using the same real Playwright runner.
- VDI Agent mode: each shard is queued as a Runner Agent job. The VDI agent polls the VM, runs its assigned command, and reports job status back.

### Recommended enterprise setup

VM:
- Runs Module-2 GUI/control plane.
- Maintains RAG, AI memory, results, history and reports.
- Creates distributed shard plans and agent jobs.

VDIs:
- Run lightweight VDI Runner Agent.
- Hold the existing framework workspace when AUT works only from VDI.
- Execute Playwright browser shards in an interactive Horizon/Omnissa desktop session.

## 2. Add new test into existing framework

The Add New Tests tab accepts PDF/DOCX/MD/TXT/JSON/Excel or Jira Story/Epic text.

The flow is:
1. Load/normalize testcase source.
2. Refresh framework understanding.
3. Generate and add test into existing framework.
4. Review the generated enterprise generation plan in `.aiqa-history`.
5. Run selected generated/existing scripts and use RCA/self-healing if needed.

The generation rule is:

`spec.ts -> page method -> pageObject/locator -> helper/fixture/testData if needed`

AI first uses the existing framework understanding memory to identify likely tests/pages/pageObjects/utils folders and follows existing naming/import conventions where possible.

## 3. Result history and AI memory

Execution history is stored in two places:

1. Central VM/control-plane memory:
   `.qa-cache/framework-execution-history/<framework-hash>/executions.jsonl`

2. Framework-local history:
   `<existing-framework>/.aiqa-history/executions.jsonl`

Recommended enterprise policy:
- Keep framework-local `.aiqa-history` in the branch/workspace for auditability.
- Keep central VM memory for cross-VDI reporting and agentic learning.
- Do not store secrets, passwords, tokens or production data in history.

Open the report from GUI:
`Logs & Reports -> Open framework result history`

## 4. Multiple VDI client-server model

AstraHeal AI can run as a client-server architecture:

- Central VM = server/control plane.
- Multiple Horizon/Omnissa VDIs = clients/runner agents.

The VDI agent uses outbound polling, so the VM does not need to directly connect into the VDI. This fits locked-down client networks better.

## 5. Prerequisites

VM:
- Python 3.11/3.12
- Node/npm if VM executes tests
- Codex/Ollama if central AI fixing is done on VM
- Network access from VDIs to `http://<VM-IP>:8080`

VDI:
- Python for runner agent
- Node/npm/npx and Playwright browsers if VDI executes tests
- Codex login if VDI applies fixes
- Existing framework workspace on persistent drive
- Active interactive Horizon/Omnissa desktop session for headed browser execution
