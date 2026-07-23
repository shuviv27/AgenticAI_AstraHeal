# Fast Timeout Policy and Failed-Only Rerun Guard

This build preserves the existing execution/RCA/self-healing flows and adds two safety improvements requested for team execution demos and real framework runs.

## 1. Default wait/timeout guard

AstraHeal now caps the default Playwright runner timeout to 30 seconds where the runner/config is controlled by AstraHeal.

Applied areas:

- Existing-framework default Playwright command now adds `--timeout=30000`.
- Local/VM parallel browser shard command now adds `--timeout=30000`.
- Generated Playwright UI framework config now uses `MAX_WAIT_MS <= 30000`.
- Generated UI navigation timeout changed from 60000ms to 30000ms.
- Generated dynamic crawler navigation timeout changed from 60000ms to 30000ms.
- Generated API Playwright config timeout changed from 60000ms to 30000ms.
- AI self-healing prompts now block explicit/default waits above 30000ms.

Configurable lower value:

```bat
set ASTRAHEAL_MAX_EXPLICIT_WAIT_MS=20000
```

Values above 30000 are intentionally capped to 30000 by the AstraHeal runner.

## 2. Run failed tests again remains failed-only

The `Run failed tests again` button continues to call:

```text
/api/existing-framework/execute/failed-only
```

The backend now records `rerun_scope_verification` in the JSON response and failed-only rerun report. This verifies:

- failed specs were read from the latest failed-test inventory;
- an empty target list is blocked;
- only root `tests/**` executable specs are accepted;
- custom commands are ignored unless they contain `{targets}`;
- safe default Playwright execution passes failed specs as explicit targets.

This prevents accidental full-suite reruns from the failed-only button. The separate `Run failed tests distributed` button remains available for fast failed-only distributed validation.
