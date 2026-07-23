# Real Browser Launch + Existing Spec Discovery Fix

This build fixes the situation where the GUI log says headed execution is running but no Playwright browser appears.

## What changed

- Existing-framework execution now discovers the actual Playwright framework root when the user provides a parent folder.
- The runner scans the framework for `tests/**/*.spec.ts`, `tests/**/*.test.ts`, `*.spec.js`, and `*.test.js` files.
- If a top-level `tests` folder exists, the command runs the complete `tests` folder so every existing spec is included.
- If no `tests` folder exists, all discovered spec files are passed explicitly.
- The default project is now `Auto / use framework default` instead of forcing `chromium`, because many client frameworks have custom project names.
- The GUI now gives both options: visible browser/headed and background/headless.
- In headed mode the backend sends `--headed` and also sets host environment hints such as `HEADED=true`, `HEADLESS=false`, `PW_HEADLESS=false`, and `CI=false`.
- All discovery details are written into the execution output under `discovered_test_scope`.

## Expected command in headed mode

For a normal framework with a `tests` folder, the command should look like:

```powershell
npx --no-install playwright test tests --workers=1 --reporter=line,json,html --headed
```

If the user selects a specific project, for example Chromium, it becomes:

```powershell
npx --no-install playwright test tests --project=chromium --workers=1 --reporter=line,json,html --headed
```

## Expected command in headless mode

```powershell
npx --no-install playwright test tests --workers=1 --reporter=line,json,html
```

## Recommended GUI choice

For local debugging and self-healing:

- Browser/project: `Auto / use framework default`
- Execution display mode: `Visible browser / headed mode`

For CI-like fast execution:

- Browser/project: `Auto / use framework default`
- Execution display mode: `Background / headless mode`

## If browser still does not appear

Check the JSON output from `Run all existing tests`:

- `existing_framework_execution.execution.command` must contain `--headed`.
- `existing_framework_execution.discovered_test_scope.spec_count` must be greater than zero.
- `existing_framework_execution.discovered_test_scope.targets` should normally include `tests`.
- The framework must not hard-code `chromium.launch({ headless: true })` inside custom helper code.
- The run must happen inside an interactive Windows desktop session, not a background Windows service session.
