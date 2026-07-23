# Runtime Test Progress, Auditable RCA Checklist, and External MCP Research

This build adds three safe enterprise enhancements without removing existing flows.

## 1. Runtime Playwright test-case progress

Local PC / Central VM parallel execution now tracks test-case progress separately from spec-file progress.

Example: if 21 selected spec files contain 210 Playwright tests, the GUI and distributed report show progress such as:

- `0/210`
- `1/210`
- `10/210`
- `210/210`

How it works:

1. Before execution, Central VM runs a safe Playwright `--list` preflight per shard to count test cases without executing them.
2. During execution, Central VM parses Playwright live output lines like `[10/210]`.
3. The current progress is written to `active-distributed-run.json` and shown in the GUI status panel.
4. If `--list` is unavailable, the system falls back to a static best-effort count and marks the count source in the report.

## 2. Auditable RCA reasoning checklist

RCA reports now show a human-readable checklist of observable diagnostic steps. This is intentionally not hidden chain-of-thought. It is an audit-friendly checklist showing evidence and decisions.

The checklist covers:

1. Failed-only scope confirmation.
2. Locator presence in DOM/accessibility evidence.
3. Locator strategy/address correctness.
4. Visibility/enabled/stable/interactable state.
5. Viewport, scroll, page-size, mobile/footer issues.
6. Popup, modal, permission, cookie, geolocation, overlay interception.
7. Navigation/state synchronization.
8. Test data, auth, API, VPN/proxy/environment issues.
9. Assertion or product-behavior drift.
10. Safest patch location: pageObjects, page methods, BasePage helpers, then specs only if unavoidable.

Reports:

- `generated-playwright/reports/existing-framework/root-cause-report.html`
- `generated-playwright/reports/existing-framework/self-healing-report.html`
- distributed report parallel RCA rows include the same checklist summary.

## 3. Optional external MCP research context

The framework now includes an enterprise-safe MCP-ready external research layer for GitHub/internal repositories/StackOverflow-style search.

Important: external research is disabled by default.

Why disabled by default:

- Enterprise networks may block public access.
- Public code examples can be stale or unsafe.
- Public snippets must never be copied directly into client frameworks.
- Security approval is required before enabling external MCP/search tools.

Generated config:

- `<framework>/.astraheal-external-research.json`

Enable only after approval:

```powershell
$env:ASTRAHEAL_EXTERNAL_RESEARCH_ENABLED="true"
$env:ASTRAHEAL_GITHUB_MCP_ENABLED="true"
```

Reports:

- `generated-playwright/reports/existing-framework/external-research/external-mcp-fix-research.html`

Use rule:

External research is advisory only. Final patching must still follow local framework conventions, failed-only scope, allowed files, backup, validation, and rollback.
