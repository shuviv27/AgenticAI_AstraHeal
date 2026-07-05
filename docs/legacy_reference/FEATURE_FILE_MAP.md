# Feature File Map

This document helps contributors quickly identify which files belong to which feature.

## Login feature

| Layer | File | Purpose |
|---|---|---|
| Business source sample | `samples/jira/login_epic.json` | Sample Jira Epic input. |
| Functional testcase | `testcases/jira_epics/login/login.scenarios.json` | Generated normalized testcase JSON. |
| Locator definitions | `generated-playwright/pageObjects/LoginPage.objects.ts` | Login page locators only. |
| Page methods | `generated-playwright/pages/LoginPage.ts` | Reusable Login page actions and assertions. |
| Generated spec | `generated-playwright/tests/generated/login.spec.ts` | Spec that calls page methods only. |
| Test data | `generated-playwright/testData/login.users.json` | Login test data. |
| Reuse report | `generated-playwright/reports/reuse-decision-report.md` | Shows reused vs created locators/methods. |

## Adding a new feature

1. Add/export input under `samples/` or connect the external source.
2. Run `ingest` to create a testcase file under `testcases/<source_type>/<feature>/`.
3. Run `inventory` so the system knows current locators and methods.
4. Run `generate` to create or update Playwright files.
5. Run `review` to validate the output.
