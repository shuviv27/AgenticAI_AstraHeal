# Report Link Integrity and AI Strategy Fix

This build fixes a report-state issue where distributed execution refreshes could overwrite or confuse the combined first-run + failed-only rerun report.

## Correct report ownership

- **Open Playwright report** opens `latest-playwright-report.html`, which routes to the latest execution stage:
  - first-run report for the original execution
  - failed-only rerun iteration report after rerun 1 or rerun 2
- **Open combined first-run + rerun report** opens only `consolidated-report.html`.
  - It is reserved for the business matrix: first run, rerun 1, rerun 2, final status.
  - It is no longer overwritten by distributed execution report refreshes.
- **Open distributed execution report** opens only `distributed-execution-report.html`.
- **Open report link manifest** opens `report-link-manifest.json` to verify exactly which report each button is expected to open.

## Per-stage Playwright evidence

AstraHeal now snapshots native Playwright HTML per stage:

- `first-run-native-html/index.html`
- `failed-only-rerun-iteration-1-html/index.html`
- `failed-only-rerun-iteration-2-html/index.html`

This prevents rerun 2 from overwriting the native evidence for rerun 1.

## First run count integrity

For a case such as 120 selected line targets but 109 reported by Playwright, the report separates:

- planned/selected targets: 120
- actual Playwright-reported/runnable tests: 109
- unresolved/not reported: 11
- passed and failed counts from the 109 runnable tests

The 11 unresolved targets are not counted as failed; they are shown as not reported by Playwright with likely reasons such as config filtering, skipped/conditional tests, or non-runnable line selectors.

## Failed-only rerun iteration integrity

Each failed-only rerun is appended to `failed-only-rerun-ledger.json`. The second rerun uses only the remaining failures from the latest ledger, not the original first-run failure list.

## AI strategy enhancement

Codex remains the recommended direct patching provider. Claude Code CLI and GitHub Copilot CLI have been added as optional provider-readiness checks for second-opinion RCA/fix planning when allowed by enterprise policy. Direct file patching remains guarded by AstraHeal backup, policy validation, deterministic fallback, and rollback.

For stronger enterprise RCA/self-healing, use:

1. local deterministic selector/actionability checks,
2. Playwright MCP/trace/screenshot evidence,
3. framework-local RAG cache under the external framework `.qa-cache`,
4. optional embedding provider such as Ollama or Hugging Face-compatible embeddings,
5. Codex or approved CLI provider for final patching,
6. failed-only rerun validation and combined report update.
