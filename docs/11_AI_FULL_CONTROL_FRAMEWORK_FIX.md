# AstraHeal AI - AI Full-Control Framework Fix

This build adds a guarded **AI full-control framework fix** flow for Playwright TypeScript framework-level issues.

## Why this was added

Earlier MCP readiness fix behavior was conservative. It could diagnose issues and apply a few safe TypeScript patches, but it did not always let the selected AI provider change framework files broadly enough to fix real project build blockers.

The new flow lets the selected backend-confirmed provider change the framework, while still keeping enterprise safety controls.

## What the AI is allowed to do

When you click **AI full-control framework fix**, AstraHeal AI can:

1. Run `npm run build`.
2. Parse TypeScript errors.
3. Identify impacted files.
4. Create backup under `<framework>/.aiqa-history/backups/`.
5. Ask the selected AI provider for a real fix.
6. Apply guarded file changes.
7. Block unsafe edits such as `test.skip`, `test.only`, `test.fixme`, or assertion weakening.
8. Rerun build/list readiness checks.
9. Save a report.

## Provider behavior

| Provider | How files are changed |
|---|---|
| Codex CLI | Codex directly patches files in the selected framework workspace. Requires `codex login`. |
| OpenAI API | OpenAI returns a JSON patch plan. AstraHeal applies exact replacements safely. No Codex login. |
| DeepSeek API | DeepSeek returns a JSON patch plan. AstraHeal applies exact replacements safely. No Codex login. |
| Ollama | Local model returns a JSON patch plan. AstraHeal applies exact replacements safely. |
| Rule-based only | AstraHeal applies built-in deterministic TypeScript fixes only. |

## Safety guardrails

The full-control fix is not blind editing. It is guarded by:

- backend-confirmed selected provider;
- backup before any change;
- impacted-file scope by default;
- exact replacement requirement for API-provider patch plans;
- block list for `test.skip`, `test.only`, `test.fixme`, and related patterns;
- rerun of build/list readiness checks;
- changed-files output;
- rollback possible from backup folder.

## Recommended use

Use this when MCP readiness or Playwright framework readiness fails because of real project code issues, for example:

- `TS2339: Property offsetParent does not exist on type Element`
- `TS18046: error is of type unknown`
- `TS2559: page.locator("a", "b") misuse`
- framework-level TypeScript build blockers

## GUI workflow

1. Go to **Start Here > AI connection**.
2. Select OpenAI, DeepSeek, Codex, Ollama, or Rule-based only.
3. Click **Backend-confirm selected AI provider**.
4. Enter the existing Playwright framework path.
5. Click **AI full-control framework fix**.
6. Confirm the popup.
7. Review output:
   - `changed_files`
   - `backup`
   - `preflight_after`
   - report URL
8. If readiness passes, continue to **Prepare Playwright MCP assist**.

## Report locations

Framework source-of-truth report:

```text
<framework>/.aiqa-history/reports/ai-full-control-framework-fix.html
<framework>/.aiqa-history/reports/ai-full-control-framework-fix.json
```

Backup location:

```text
<framework>/.aiqa-history/backups/mcp-build-fix-<timestamp>/
```

## Important notes

- Worker VMs should not independently patch the framework.
- Run full-control fix from the Central VM/GUI backend machine.
- Worker VMs should execute browsers/tests and send evidence back.
- Review changed files before committing to Git.
