# Demo Progress Completion and Detached Locator RCA Fix

This enhancement is additive and preserves existing execution, reporting, RCA, self-healing, failed-only rerun, distributed execution, and external-framework RAG cache behavior.

## Fixed GUI progress completion

Long-running AI actions still show an active waiting cursor and percent progress while they are actually running. After backend completion, the GUI now marks the progress pulse as completed and stops the spinner. This prevents screens such as `100% completed / 0% remaining` from still showing a rotating wait cursor.

Quick readiness actions such as **Check Codex health** and **Backend-confirm selected AI provider** no longer use the long AI-heavy spinner pipeline. They still show a progress bar, client action log, backend result, and runtime events, but they complete cleanly.

## Clear action result visibility

Every button now starts with a client-visible action message:

- client action triggered
- request sent to backend
- backend result received
- action-specific summary when available

For **Save runtime choice**, the GUI now shows the saved runtime mode and engine, for example `Local PC / No-Docker Host Runtime`.

## RCA detached-locator enhancement

RCA now explicitly recognizes failures such as:

```text
locator.scrollIntoViewIfNeeded: Element is not attached to the DOM
```

The RCA report now classifies this as `locator_detached_from_dom` and instructs the AI/self-healing flow to:

1. verify the failed test and action from Playwright JSON/trace/error context;
2. inspect current DOM after the page settles;
3. use Playwright MCP/codegen/live DOM evidence to regenerate a stable pageObject locator;
4. avoid stale locator/ElementHandle references;
5. re-query the locator immediately before scroll/click/expect;
6. patch pageObject/page/BasePage helpers, not raw spec locators or hard waits.

## Validation performed

- Python syntax validation for all `qa_pipeline/**/*.py`.
- GUI import validation.
- Frontend JavaScript syntax validation.
- Synthetic detached DOM RCA signal validation.
- Synthetic existing framework learning and selectable discovery validation.
- Synthetic MCP preflight, report endpoint, runtime save, provider confirmation, RCA, and self-heal endpoint smoke validation.

Real enterprise AUT browser execution must still be validated on the target VM/VDI because that runtime is not available in this sandbox.
