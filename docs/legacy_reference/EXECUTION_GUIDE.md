# End-to-End Execution Guide

## A. Fresh setup

```bash
cd AdvancedAIAutomation_Reusability_Enterprise_Build
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
cd generated-playwright
npm install
npx playwright install chromium
cd ..
```

## B. Execute the complete demo flow

```bash
python -m qa_pipeline.cli run-e2e --source samples/jira/login_epic.json --source-type jira --feature login
```

This command performs:

1. Phase 1 doctor check
2. Framework inventory scan
3. Phase 2 testcase ingestion
4. Phase 3 reuse-aware Playwright generation
5. Phase 4 review/static validation
6. Phase 6 summary report generation

## C. Run smoke test

```bash
npm --prefix generated-playwright run smoke
```

## D. Run generated test against your application

```bash
export BASE_URL=https://your-application-url
export TEST_USERNAME=your-user
export TEST_PASSWORD=your-password
npm --prefix generated-playwright test -- --project=chromium tests/generated/login.spec.ts
```

## E. Validate that scripts are not isolated

Open:

```text
generated-playwright/reports/reuse-decision-report.md
```

Confirm that specs call page methods and do not inline locators.

The review command also checks generated specs for inline locator usage:

```bash
python -m qa_pipeline.cli review
```
