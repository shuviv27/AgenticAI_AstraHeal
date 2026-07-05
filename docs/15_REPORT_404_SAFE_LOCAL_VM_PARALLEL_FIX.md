# Report 404 Safe Local/VM Parallel Fix

This build preserves all existing execution/RCA/self-healing behavior and fixes the report regression observed after local/VM parallel shard execution.

## What changed

1. **Open Playwright report no longer 404s**
   - The GUI button now opens a framework-aware backend endpoint.
   - If a normal native Playwright report exists, it opens that report.
   - If the run was local/VM parallel or node-hub distributed, it opens a central landing page at:
     - `generated-playwright/reports/existing-framework/html/index.html`
   - The old static URL is still kept alive so existing buttons/bookmarks do not break.

2. **Combined report no longer 404s**
   - `generated-playwright/reports/existing-framework/consolidated-report.html` always exists.
   - After distributed execution it is refreshed with the single consolidated distributed report.

3. **Shard-native Playwright reports are preserved**
   - Each local/VM parallel shard writes its own HTML/JSON/test-results under:
     - `<framework>/reports/existing-framework/distributed-runs/<run-id>/<shard-id>/`
   - The central report landing page links to each shard report through safe backend endpoints.

4. **Parallel artifact collision fixed**
   - Each local/VM parallel shard now uses a unique Playwright `--output=<shard>/test-results` folder.
   - This avoids shared `test-results/.playwright-artifacts-*` race conditions such as missing trace files.

5. **Backups excluded from runnable discovery**
   - Run & Fix discovery now accepts only root `tests/**` executable Playwright specs.
   - Files under `.codex-backups/**/tests/**`, `.aiqa-history/**`, `features/**`, reports, and test-results are excluded.

6. **Failed inventory is no longer stale**
   - Local/VM parallel failure inventory is merged from per-shard JSON reports where available.
   - If JSON is unavailable, shard console output is used.
   - RCA/self-healing still receives failed specs only.

## Existing features kept intact

- Normal single-machine run.
- Local/VM parallel browser shards.
- Central VM + worker VM/VDI node-hub execution.
- Central VM-only AI heavy lifting.
- Parallel RCA/self-healing triage.
- Failed-only rerun flow.
- Logs & Reports tab links.
