# Microsoft Playwright MCP Assisted RCA and Self-Healing

This Module 2 build keeps the existing deterministic Playwright Test execution, headed mode, RAG indexing, failed-only RCA, self-healing policy, and action-history memory. It adds an optional Microsoft Playwright MCP assist layer for browser-aware diagnosis.

## Why MCP is added

Microsoft Playwright MCP exposes Playwright browser automation through the Model Context Protocol and lets AI tools inspect pages through structured accessibility snapshots instead of guessing from screenshots. In this solution, MCP is used as an assist layer for live-browser/locator reasoning while Playwright Test remains the actual test runner for repeatable reports, traces, screenshots, videos, and failed-test inventory.

## What changed

### New GUI buttons

In **Existing Framework**:

- **Prepare Playwright MCP assist**

In **Run & Fix Tests**:

- **Check failed element with Playwright MCP**
- **Explain failed tests**
- **Create safe fix plan**
- **Fix failed tests safely**
- **Run failed tests again**

In **Logs & Reports**:

- **Open MCP element RCA report**

## MCP-assisted RCA flow

When a test fails because an element is not available, not visible, ambiguous, or not interactable, the RCA now records an auditable evidence chain:

1. Identify which locator/action failed.
2. Check the expected locator text or accessible name on the visible GUI.
3. Check whether the element exists in the DOM/accessibility tree.
4. Check whether the element is interactable, enabled, stable, visible, and not blocked by overlay/popup.
5. Check whether the correct locator strategy exists in the POM framework and patch the correct layer.

The report is saved here:

```text
 generated-playwright/reports/existing-framework/mcp-assisted-rca/mcp-assisted-locator-rca.html
 generated-playwright/reports/existing-framework/mcp-assisted-rca/mcp-assisted-locator-rca.json
 .qa-cache/existing-framework/mcp-assisted-memory.jsonl
```

## Safe fixing rule

The system must still follow the existing guardrails:

- Patch pageObjects/locator modules first.
- Patch reusable page methods/BasePage/helpers second.
- Avoid raw locator fixes inside spec files unless no reusable layer exists.
- Do not skip tests.
- Do not weaken assertions.
- Do not force click by default.
- Do not patch passed scripts.
- Do not patch application/API/DB/environment defects as script defects.

## Recommended use

1. Paste existing framework path.
2. Click **Learn this framework with AI**.
3. Click **Prepare Playwright MCP assist**.
4. Click **Run all existing tests**.
5. If failed, click **Check failed element with Playwright MCP**.
6. Click **Explain failed tests**.
7. Click **Create safe fix plan**.
8. Click **Fix failed tests safely** only if the plan is safe.
9. Click **Run failed tests again**.
10. Open the Playwright, plain-English RCA, MCP element RCA, and AI memory reports.

