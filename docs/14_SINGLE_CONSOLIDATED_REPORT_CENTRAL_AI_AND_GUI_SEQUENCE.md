# Single Consolidated Report, Central AI Heavy Lifting, and GUI Execution Sequence

## What changed

This build preserves the existing Local PC, Central VM only, local/VM parallel sharding, and Central VM + Worker VM/VDI node-hub behavior. It adds stronger enterprise guarantees for distributed execution:

1. **Single consolidated execution report**
   - Agentic node-hub writes one Central VM source-of-truth report:
     - `generated-playwright/reports/existing-framework/agentic-nodehub-report.html`
     - `generated-playwright/reports/existing-framework/single-consolidated-agentic-nodehub-report.html`
   - It also mirrors the report into the selected framework:
     - `<framework>/.aiqa-history/reports/agentic-nodehub-report.html`
     - `<framework>/.aiqa-history/reports/single-consolidated-agentic-nodehub-report.html`

2. **Central VM-only AI heavy lifting**
   - Workers execute browser commands and return evidence only.
   - Central VM owns framework RAG, RCA, self-healing, AI provider credentials, source patching, backups, rollback, memory, and reporting.
   - If a non-central AI option is posted by mistake, the backend normalizes it to:
     - `ai_heavy_lifting_mode=central_brain_worker_evidence`
     - `worker_ai_role=browser_mcp_evidence_only`
     - `codex_patch_location=central_only`

3. **GUI execution sequence and status**
   - Run & Fix Tests → Central VM with worker node-hub now shows a live `Execution sequence` panel.
   - It displays total/completed/passed/needs-attention counts and a script-by-script table:
     - worker
     - phase
     - test script
     - status
     - retry attempts
     - final rerun status
     - RCA/self-healing status
     - human intervention flag

4. **Playwright framework alignment report**
   - Deep framework understanding now also checks Playwright alignment gaps and writes:
     - `generated-playwright/reports/existing-framework/playwright-framework-alignment.html`
   - This report is human-readable and explains:
     - whether the framework is aligned enough for execution
     - missing/weak Playwright setup items
     - POM/reusability concerns
     - robust RCA/self-healing sequence
   - Understanding mode remains safe: it does not silently rewrite an enterprise framework. Source changes still go through approved fix flow with backup, validation, and rollback.

## Expected enterprise flow

1. Start Central VM GUI.
2. Confirm provider in Start Here, usually Codex CLI.
3. Select Runtime = VM + Worker Agent.
4. Deep learn the framework with AI.
5. Open the Playwright alignment report if needed.
6. Find executable tests under `tests/**`.
7. Start Worker Agents on VDIs/VMs.
8. Configure Central VM + worker VMs.
9. Run node-hub execution.
10. Watch the GUI execution sequence and refresh status.
11. Open the single consolidated node-hub report from Central VM.

## Worker responsibilities

Workers do:

- run assigned Playwright tests
- retry failed tests when Central VM schedules retry jobs
- return stdout/stderr and artifact hints
- optionally collect browser/MCP evidence where AUT access exists only on that VDI/VM

Workers do not:

- run Codex/OpenAI/DeepSeek/Ollama patching
- modify framework source as AI authority
- own AI memory
- own final reports
- decide RCA/self-healing strategy

## Central VM responsibilities

Central VM does:

- test distribution and orchestration
- Central VM as worker execution, when selected
- AI provider confirmation
- framework RAG/memory
- RCA and self-healing
- approved patching with backup/rollback
- failed-only rerun control
- single consolidated reporting
- GUI status and execution sequence
