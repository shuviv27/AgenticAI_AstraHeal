# MCP Assist Fast Prepare and Stuck Prevention

## Why the old flow looked stuck

After an AI build fix, the GUI used to call the full MCP prepare endpoint again. That could repeat:

1. `npm run build`
2. `npx playwright test --list`
3. `npx playwright install --dry-run <browser>`
4. `npx @playwright/mcp@latest --help`

On slow client VMs, proxy-restricted networks, or blocked npm registries, the final live MCP package probe can wait a long time. The GUI looked stuck at **Preparing Microsoft Playwright MCP assist after AI build fix**.

## New behavior

The normal Prepare MCP action now runs in two phases:

1. Readiness preflight checks framework readiness and shows build/list/browser errors clearly.
2. MCP prepare writes MCP config and checks npm/npx quickly.

After preflight passes or after AI build fix completes, the prepare step uses fast mode and does **not** repeat heavy checks. It also skips the live `npx @playwright/mcp@latest --help` probe by default.

## What is still validated

Fast prepare validates:

- framework path
- `package.json`
- `npm`
- `npx`
- MCP config file creation

## What is skipped by default

To avoid VM hangs, fast prepare skips:

- duplicate `npm run build`
- duplicate `npx playwright test --list`
- duplicate browser install dry-run
- live `@playwright/mcp` package probe

## When to run the live probe

Run the explicit live probe only if you need to confirm the VM can download/start the MCP package:

```powershell
# From GUI: click Optional MCP live probe
```

or set this before starting the GUI:

```powershell
setx AIQA_MCP_LIVE_PROBE true
setx AIQA_MCP_LIVE_PROBE_TIMEOUT_SECONDS 60
```

Then restart the GUI.

## Recommended enterprise setting

For client VMs and worker VMs:

```text
Keep MCP live probe disabled by default.
Use Playwright Test for deterministic execution.
Use MCP-style/browser evidence only when needed for RCA/self-healing.
```
