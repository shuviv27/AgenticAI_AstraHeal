# Module 2 Real Browser Discovery and Runtime Log Fix

## What was fixed

1. Existing test discovery now supports migrated enterprise paths such as:
   - `tests/specs/**/*.spec.ts`
   - `tests/specs/**/*.specs.ts`
   - `tests/**/*.spec.ts`
   - `tests/ALL*.spec.ts`
   - `tests/**/*.test.ts`

2. The GUI now has a dedicated **Show tests selected for execution** button.
   Use this before running so you can see exactly which specs the AI selected.

3. For small and medium suites, the backend passes explicit spec files to Playwright.
   This prevents non-standard `.specs.ts` files from being missed by default Playwright `testMatch` patterns.

4. Headed/headless is now a real GUI choice:
   - Visible browser / headed mode adds `--headed` to the command.
   - Background / headless mode does not add `--headed`.

5. Recent runtime events in the progress panel are now filtered to the current action only.
   Old execution messages will not appear after unrelated actions such as **Check this machine**.

## Recommended flow

1. Paste existing framework folder.
2. Select execution display mode: **Visible browser / headed mode**.
3. Click **Learn this framework with AI**.
4. Click **Show tests selected for execution**.
5. Verify selected specs in GUI output.
6. Click **Run all selected existing tests**.
7. If failures exist, use MCP RCA, Explain failed tests, Create safe fix plan, Fix failed tests safely, and Run failed tests again.

## Notes

If browser still does not appear, check whether the client framework itself launches browsers manually with `headless: true` in helper code or config. CLI `--headed` usually overrides Playwright Test config, but it cannot always override custom `chromium.launch({ headless: true })` calls inside test utility code.
