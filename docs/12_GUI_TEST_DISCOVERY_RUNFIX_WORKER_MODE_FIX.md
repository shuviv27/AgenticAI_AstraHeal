# GUI Test Discovery, Run/Fix and Worker Mode Fix

## Fixed behavior

1. **Find scripts in framework** now lists only executable Playwright test scripts under `tests/**`:
   - `*.spec.ts`
   - `*.specs.ts`
   - `*.test.ts`
   - JavaScript/MJS/CJS equivalents

2. Files under `features/**` are treated as BDD/requirement assets and are not shown in the default Run & Fix selectable script list.

3. **Run chosen tests on this machine** is now clearly scoped for Local PC and Central VM only. It runs selected scripts on the same machine with no worker split and no node-hub shard execution.

4. **Central VM only** distributed planning is forced to one local shard to prevent multiple local Playwright processes from overwriting each other’s reports and making it look like only a few selected scripts ran.

5. The GUI is partitioned into:
   - Find and choose executable test scripts
   - Local PC / Central VM only execution
   - RCA + Self-Healing after any failed run
   - Central VM with worker node-hub
   - Human intervention / manual update memory
   - Stability insights

6. Worker-specific node-hub controls are only shown when Runtime is set to **VM + Worker Agent**.

7. AI-heavy-lifting provider fields are no longer duplicated in the worker section. They follow the provider selected in **Start Here**. Default remains **Codex CLI**.

## Preserved behavior

- Existing API routes remain backward-compatible.
- Cucumber/manual feature execution logic is not removed from lower-level legacy/manual command paths.
- RCA, self-healing, rollback, human approval, failed-only rerun and history/memory files remain intact.
- Existing Playwright report normalization and failed-test inventory generation remain intact.
