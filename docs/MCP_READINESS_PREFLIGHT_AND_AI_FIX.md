# MCP Readiness Preflight and AI Build Fix

AstraHeal AI now runs a readiness gate before Microsoft Playwright MCP assist starts. This prevents the GUI from appearing stuck when the client Playwright framework has TypeScript/build/list/browser readiness issues.

## What the preflight checks

1. Valid framework path and `package.json`.
2. `npm run build` if a `build` script exists in `package.json`.
3. `npx playwright test --list` to confirm Playwright can discover tests.
4. `npx playwright install --dry-run chromium` to confirm browser-install command readiness.
5. TypeScript errors are parsed and shown clearly in GUI output and report.

## User choices when preflight fails

When preflight fails, the GUI asks the user to choose:

- **Fix with selected AI provider**: creates a backup of impacted files, uses the selected provider, reruns preflight, and lists changed files. Codex applies direct patches when selected; DeepSeek/OpenAI use API-key guidance plus safe local TypeScript fix application.
- **Continue MCP without build**: prepares MCP anyway for exploratory browser evidence. Use only when you intentionally accept an unclean framework state.
- **Cancel**: no MCP preparation and no file changes.

## Report locations

For an external framework:

```text
<framework>/.aiqa-history/reports/mcp-readiness-preflight.html
<framework>/.aiqa-history/reports/mcp-readiness-preflight.json
```

GUI mirror:

```text
<solution>/generated-playwright/reports/existing-framework/mcp-readiness-preflight.html
```

## Best practice

For enterprise frameworks, do not continue MCP on a broken build unless you only need exploratory DOM evidence. Prefer **Fix with selected AI provider**, then rerun MCP preflight and proceed when the build/list checks pass.
