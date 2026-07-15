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

## Deep recursive Playwright framework discovery (0.4.1)

The Existing Framework workflow now supports root and nested enterprise layouts, including:

```text
src/
  main/
    api/
    config/
    pages/
    ui_base/
  test/
    specs/
      <module>/
        <test>.spec.ts
```

- **Find scripts in framework** performs a fast recursive deterministic scan without starting AI/RAG learning.
- **Deep learn this framework with AI** maps architecture, reusable layers, imports, locators and spec dependency chains.
- **AI full-control framework fix** receives that structure/dependency context before proposing changes.
- Sequential, local-parallel, distributed and BrowserStack execution retain the exact discovered spec paths.
- Playwright MCP readiness retries test listing with recursively discovered explicit specs when default `testDir`/`testMatch` discovery does not prove the tests.

Read:

```text
docs/29_DEEP_RECURSIVE_FRAMEWORK_DISCOVERY_AND_AI_CONTROL_FIX.md
BUILD_VALIDATION_REPORT.md
```

## Explainable RCA, exact fix approval scope, and local report paths (0.4.2)

This build fixes three confusing behaviors in the existing-framework workflow:

1. **Plain English RCA is category-specific.** Each failed test now shows observed evidence, failure category and confidence, likely fix layer, recommended files, validation steps, and whether self-healing is safe. Module-resolution, locator, overlay, detached element, navigation, assertion, authentication, browser/runtime and timeout failures no longer receive the same locator-oriented advice.
2. **Runtime AI Fix Approval no longer silently expands to the workspace.** The popup separates recommended patch files, the maximum write boundary, and read/search-only context candidates. The current popup file list is authoritative; only explicitly listed files/folders may be changed. The exact changed files are reported after apply.
3. **Local storage paths are visible.** Open **Logs, Reports and AI Memory → Show local report/log folders** to see absolute paths for native Playwright output, AstraHeal retained reports, RCA/self-healing JSON/HTML, runtime logs, AI action history, failure inventory and backups.

See `docs/30_EXPLAINABLE_RCA_EXACT_APPROVAL_SCOPE_AND_LOCAL_REPORT_PATHS.md`.

## Multi-source Add New Tests workflow (0.4.3)

The **Add new test later** tab now extends the Playwright framework selected in **Existing Framework** instead of assuming a root-level `tests/pages` layout.

- PDF, DOCX, TXT, Markdown, JSON, CSV, XLSX/XLSM and `.feature` sources can contain multiple testcases. AstraHeal normalizes them separately and creates one Playwright spec per testcase/scenario.
- Gherkin `Feature`, `Background`, `Scenario`, `Scenario Outline`, `Examples`, `Given`, `When`, `Then`, `And` and `But` content is preserved as traceable BDD source while generating executable Playwright specs.
- Placement preview shows the configured Playwright `testDir`, recommended existing page/method file, locator repository, ambiguity and new-file requirement before any source change.
- Existing page methods and locators are reused first. A new support file is created only when no safe existing target is available and the user permits it.
- Jira individual issues, Epic children, JQL results and Confluence pages can be fetched from the same tab. Credentials stay in memory for the current request; generated MCP configuration uses environment placeholders only.
- Generated changes are backed up and validated with Playwright `--list` when local dependencies are available. A failed validation automatically restores existing files and deletes newly created specs/support files.

Read:

```text
docs/31_ADD_NEW_TESTS_MULTI_SOURCE_BDD_ATLASSIAN.md
```
