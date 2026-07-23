# Module 2 Headed Mode Enforcement Fix

Module 2 is focused on existing Playwright framework debugging, RCA, self-healing and failed-only rerun.
For this reason, existing-framework execution is now forced to **headed / visible browser mode** at the backend level.

## What changed

- `Run all existing tests` always sends `headed=True`.
- `Run selected tests` always sends `headed=True`.
- `Run failed tests again` always sends `headed=True`.
- The GUI checkbox is shown as always-on for clarity.
- The backend appends `--headed` to normal Playwright commands.
- For common custom commands such as `npx playwright test`, `npm test`, `npm run e2e`, `pnpm test`, and `yarn test`, the backend forwards `--headed` when possible.

## Why

Visible browser mode is required for debugging:

- unexpected popups
- browser/app permissions
- disabled or non-interactable elements
- locator issues
- dynamic waits
- RCA/self-healing validation

## Verification

After clicking **Run all existing tests**, check the JSON output. The command should contain `--headed`.
