# AstraHeal AI heavy-lifting balance: Codex + Playwright MCP + VM workers

This guide explains where AI work should run when AstraHeal AI executes and fixes a large Playwright framework across a Central VM and worker VMs.

## Recommended enterprise model

```text
Central VM
  = AI brain + source-of-truth
  = GUI, RAG memory, framework understanding, new script generation, RCA, self-healing, Codex patching, reports, history

Worker VMs
  = browser/test execution + Playwright MCP/DOM evidence collection
  = no permanent source-code patching
```

This keeps the framework consistent and avoids five workers making conflicting code changes.

## Why workers still participate in AI heavy lifting

Some AUTs are reachable only from a specific VM/VDI because of VPN, certificates, SSO, proxy, network zone, browser profile, or test data access. In those cases, the worker VM should collect browser evidence, such as:

- DOM snapshot / page source
- Playwright MCP evidence
- accessibility-style element information
- screenshot/trace/video location
- locator/actionability failure information
- console/network tail where available

The worker sends these artifacts back to Central VM. Central VM then performs RCA and fix application against the central framework source.

## Provider responsibility split

| Capability | Preferred provider/location |
|---|---|
| Framework understanding | Central VM RAG scanner + Codex optional review |
| AUT/web scraping | Central first, worker fallback if AUT reachable only on worker |
| DOM crawl for exact locators | Worker Playwright/MCP evidence when required |
| New script generation | Codex CLI on Central VM |
| Reuse-law validation | Central VM RAG + deterministic dependency graph |
| RCA | Central VM, using logs + worker evidence |
| Self-healing patch | Codex CLI on Central VM only |
| Trial reasoning | OpenAI / DeepSeek / Ollama |
| Execution | Central worker and/or worker VMs |

## Reusability laws for new test generation

Generated code must follow this order:

```text
spec.ts
  -> page method
    -> pageObject / locator file
      -> helper / fixture / testData when required
```

Rules:

1. If a locator exists, reuse it.
2. If a page method exists, reuse it.
3. If a helper exists, reuse it.
4. If a new locator is needed, add it to the most suitable existing pageObject/locator file.
5. If a new page action is needed, add it to the most suitable existing page class.
6. Avoid creating isolated test logic directly inside specs unless the framework itself follows that pattern.
7. Do not add `test.skip`, `test.only`, or `test.fixme` as a fix.
8. Do not weaken assertions without approval.

## New GUI controls

In **Run & Fix Tests**, use:

```text
AI heavy-lifting mode = Central brain + worker MCP/browser evidence
Worker AI role = Browser + Playwright MCP evidence only
DOM crawl mode = Worker MCP when AUT is reachable only on worker
Codex patch location = Central VM source-of-truth only
```

Click:

```text
Create AI heavy-lifting plan
Open AI heavy-lifting report
```

The report is stored in:

```text
<existing-framework>/.aiqa-history/reports/ai-heavy-lifting-plan.html
<existing-framework>/.aiqa-history/reports/ai-heavy-lifting-plan.json
```

A GUI mirror is also kept under the AI solution reports folder.

## Runtime flow during distributed execution

```text
1. Central VM learns framework and AUT context.
2. Central VM creates distributed/agentic node-hub plan.
3. Central and/or worker VMs execute assigned tests.
4. If a test fails, the same worker reruns it immediately.
5. If still failing, the worker sends failure artifacts to Central VM.
6. Central VM starts RCA and self-healing while other workers continue execution.
7. Codex applies minimal source fix on Central VM with backup/rollback.
8. Failed tests are rerun after fixes.
9. Central VM writes single consolidated report and history.
```

## Prerequisites

### Central VM

- Python 3.11+
- Node.js/npm/npx if Central VM also executes tests
- Codex CLI logged in if it will apply fixes
- Optional OpenAI/DeepSeek/Ollama provider configuration
- Shared framework path if workers execute from central source
- Firewall open for GUI/control plane port 8080

### Worker VMs

- Node.js/npm/npx
- Playwright browsers installed
- Runner agent started
- Access to AUT
- Access to central shared framework path, or a configured worker-local copy mode
- No permanent source patching required

## Best practice

Use Codex CLI on Central VM for heavy code work and use workers for browser/MCP evidence. This gives the best balance of speed, safety, and consistency.
