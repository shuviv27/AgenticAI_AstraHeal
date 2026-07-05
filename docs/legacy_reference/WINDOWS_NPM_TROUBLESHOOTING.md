# Windows npm troubleshooting

## Symptom

`python -m qa_pipeline.cli doctor` shows Node is available but npm is not available, or `run-e2e` fails at Step 5 review with:

```text
FileNotFoundError: [WinError 2] The system cannot find the file specified
```

## Root cause

The Python pipeline reached the Playwright TypeScript review step and tried to run:

```text
npm --prefix generated-playwright run build
```

On Windows, this fails when `npm.cmd` is not installed or not available in PATH. Sometimes Node is available but npm is missing or not visible to the current terminal.

## Quick workaround

You can complete Python ingestion + reuse-aware generation without npm validation:

```powershell
python -m qa_pipeline.cli run-e2e --source samples\jira\login_epic.json --source-type jira --feature login --skip-npm
```

This skips the TypeScript build step only. It still creates/reuses locators, page methods, generated specs, testcases, and reports.

## Permanent fix

Install Node.js LTS with npm, then reopen PowerShell/VS Code terminal:

```powershell
winget install OpenJS.NodeJS.LTS
```

Validate:

```powershell
where node
where npm
node -v
npm -v
```

Then install Playwright dependencies:

```powershell
cd generated-playwright
npm install
npx playwright install chromium
cd ..
```

Run again:

```powershell
python -m qa_pipeline.cli run-e2e --source samples\jira\login_epic.json --source-type jira --feature login
npm --prefix generated-playwright run smoke
```
