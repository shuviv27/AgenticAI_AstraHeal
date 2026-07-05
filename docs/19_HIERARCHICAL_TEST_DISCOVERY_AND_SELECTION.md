# Hierarchical Test Discovery and Selection

This build enhances **Find scripts in framework** without changing the existing execution, RCA, self-healing, failed-only rerun, distributed rerun, or reporting flows.

## What changed

When the user clicks **Find scripts in framework**, AstraHeal still discovers only approved executable Playwright files under `tests/**`, but it now also performs a fast static scan inside each spec file and builds a hierarchy:

- spec file
  - Playwright test case 1
  - Playwright test case 2
  - Playwright test case 3

The GUI summary now shows both counts, for example:

`21 spec script(s) contain 150 discovered Playwright test case(s)`

## Where it appears in the GUI

Open:

`Run & Fix Tests -> Find and choose executable test scripts -> Find scripts in framework`

The result appears in the existing checklist area. Each spec can be expanded/collapsed, and each test case can be selected independently.

## Execution behavior

- Selecting a spec-level checkbox selects or unselects every test case under that spec.
- Selecting individual test cases passes Playwright line selectors such as `tests/ui/login.spec.ts:42` to the runner.
- Specs with no statically detected `test(...)` calls remain runnable as whole spec files.
- Existing script-level selection behavior is preserved for fallback and compatibility.

## Guardrails preserved

- Only root `tests/**` executable specs are shown.
- `.codex-backups/**`, `.aiqa-history/**`, reports, node_modules and generated artifacts are excluded.
- Failed-only rerun remains failed-only.
- Local/VM parallel sharding, runtime progress, RCA/self-healing and combined report logic are unchanged.

## Counting note

The hierarchy uses a fast static scan for common Playwright styles such as `test(...)`, `test.only(...)`, `test.skip(...)`, `test.fixme(...)`, and `it(...)`. Final pass/fail status always comes from real Playwright execution reports.
