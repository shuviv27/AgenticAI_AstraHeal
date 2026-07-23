# Explainable RCA, Exact Runtime Approval Scope, and Local Report Paths

**Build:** 0.4.2  
**Area:** Existing Framework → RCA, Self-Healing, Runtime AI Fix Approval, Logs and Reports

## Why the previous output was confusing

The older Plain English RCA used the same generic locator recommendation for many failures:

> Check live DOM with Playwright MCP/codegen, then update pageObjects/locator repository or reusable page method; avoid hard waits and test skips.

That advice is reasonable only when evidence points to a DOM/locator issue. It is incorrect or incomplete for module imports, browser crashes, authentication, environment problems, assertion drift, navigation, or an unclassified timeout.

The older Runtime AI Fix Approval also expanded an approved local/VM patch scope to a bounded set of framework TypeScript/JavaScript files. Therefore, a run with 3 failed specs and 5 failed tests could display 65 allowed files. The number meant “maximum files Codex was permitted to modify,” not “65 files will be changed,” but the UI did not explain that clearly and the write boundary was broader than necessary.

## 0.4.2 behavior

### Evidence-based test-level RCA

Each failed test now includes:

- observed error evidence;
- deterministic failure category;
- confidence percentage;
- plain-English cause;
- likely framework layer;
- recommended files, when evidence supports a file change;
- validation steps;
- self-healing safety decision.

Current categories include:

- TypeScript/module/path-alias resolution;
- ambiguous locator;
- missing locator or wrong page state;
- overlay or click blocker;
- detached/rerendered element;
- navigation or redirect;
- assertion/product behavior mismatch;
- authentication/authorization;
- browser/runtime crash;
- timeout or unfinished state;
- unknown/insufficient evidence.

A locator change is not recommended for module, authentication, browser, environment, or unverified assertion failures.

### Runtime approval counts

The popup now shows three different counts:

1. **Recommended patch files** — the smallest likely patch set based on the current failure category and dependency graph.
2. **Maximum approval boundary** — the complete RCA-derived list that AI could modify only after approval. It does not mean every file will change.
3. **Context-only candidates** — additional framework files that AI may read/search to understand a non-standard framework. They are not writable unless the user explicitly adds their file/folder paths.

The file textarea in the current popup is authoritative for the current patch attempt:

- removing a path removes write permission;
- adding an exact file/folder grants only that path;
- an empty list blocks patching;
- previous human approvals are retained as context but do not silently expand a new patch attempt;
- broad workspace write scope is disabled by default.

An exceptional broad write scope requires the explicit environment opt-in:

```text
ASTRAHEAL_ALLOW_BROAD_WORKSPACE_PATCH_SCOPE=true
```

This opt-in is not recommended for normal use.

## Local storage locations

The GUI button **Show local report/log folders** returns absolute paths and whether each artifact currently exists.

For an AstraHeal installation rooted at `<ASTRAHEAL_ROOT>`:

### Central retained reports

```text
<ASTRAHEAL_ROOT>/generated-playwright/reports/existing-framework/
```

Important files include:

```text
plain-english-failure-report.html
plain-english-failure-report.json
root-cause-report.html
root-cause-report.json
self-healing-report.html
self-healing-report.json
failed-tests.json
execution-report.json
latest-playwright-report.html
html/index.html
consolidated-report.html
report-manifest.json
```

### Runtime logs, AI memory, and backups

```text
<ASTRAHEAL_ROOT>/.qa-cache/runtime/runtime-events.jsonl
<ASTRAHEAL_ROOT>/.qa-cache/runtime/current-status.json
<ASTRAHEAL_ROOT>/.qa-cache/ai-memory/action-history.jsonl
<ASTRAHEAL_ROOT>/.qa-cache/existing-framework/common-cause-memory.json
<ASTRAHEAL_ROOT>/.qa-cache/existing-framework/human-intervention/human-intervention-memory.jsonl
<ASTRAHEAL_ROOT>/.qa-cache/existing-framework/backups/
```

### Native output inside the selected Playwright framework

The most common native Playwright paths are:

```text
<FRAMEWORK_ROOT>/playwright-report/index.html
<FRAMEWORK_ROOT>/test-results/
<FRAMEWORK_ROOT>/reports/existing-framework/execution-console.log
```

Alternative framework reporter locations are also detected:

```text
<FRAMEWORK_ROOT>/reports/existing-framework/html/index.html
<FRAMEWORK_ROOT>/reports/html-report/index.html
<FRAMEWORK_ROOT>/reports/existing-framework/test-results/
```

Playwright first writes its native output under the selected framework. AstraHeal then copies or retains the latest report under its central report folder so GUI links remain stable across first runs and failed-only reruns.

## Safety and compatibility

The change preserves:

- recursive `src/test/specs/**` and legacy root `tests/**` discovery;
- sequential and distributed execution;
- failed-only rerun and combined reporting;
- BrowserStack execution-only integration;
- provider connectivity gates;
- backups, policy validation, rollback and changed-file reporting;
- MCP-assisted locator evidence;
- existing framework learning and full-control fix flows.
