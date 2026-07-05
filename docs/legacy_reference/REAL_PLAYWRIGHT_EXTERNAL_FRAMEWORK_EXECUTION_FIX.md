# Real Playwright External Framework Execution Fix

This build fixes the existing-framework execution path for external Playwright repositories.

## What changed

- The runner now resolves `npx`/`npx.cmd` safely instead of assuming the GUI process can directly execute it.
- On Windows, the system writes and runs a debuggable command file at:
  `reports/existing-framework/RUN_EXISTING_PLAYWRIGHT_HEADED.cmd`
- The runner streams stdout and stderr together, so Playwright startup failures are not hidden.
- The system always writes:
  - `reports/existing-framework/execution-console.log` inside the external framework
  - `generated-playwright/reports/existing-framework/execution-report.json` inside the AI module
  - fallback HTML report if Playwright could not generate a native HTML report
- The GUI now shows selected specs before execution and shows the exact Playwright command, working folder, launcher script, exit code, and artifact evidence after execution.
- Headed and headless options remain available from the GUI.

## Expected headed command

Example:

```powershell
npx --no-install playwright test tests/specs/ALL_login.specs.ts --workers=1 --reporter=line,json,html --headed
```

## Troubleshooting

If the browser still does not launch, open the generated launcher script and console log inside the external framework:

```text
<your-framework>\reports\existing-framework\RUN_EXISTING_PLAYWRIGHT_HEADED.cmd
<your-framework>\reports\existing-framework\execution-console.log
```

Common causes:

- Playwright browsers are not installed: run `npx playwright install chromium` in the external framework.
- The external framework has hard-coded `headless: true` in custom browser launch code.
- The GUI server is running in a non-interactive Windows session/service.
- The application URL, proxy, VPN, or certificate blocks browser startup/navigation.
- Playwright config has a custom project name and `Auto` mode should be replaced by the exact project name.
