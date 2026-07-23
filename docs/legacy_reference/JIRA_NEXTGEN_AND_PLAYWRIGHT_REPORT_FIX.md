# Jira next-gen warning and sequential Playwright report fix

This build contains two targeted fixes.

## 1. Jira team-managed / next-gen Agile API warning

When modern Jira Cloud parent JQL already returns Epic child work items, the pipeline no longer calls the legacy Jira Software Agile endpoint `/rest/agile/1.0/epic/<EPIC>/issue`.

Reason: team-managed/next-gen projects can return HTTP 400 from that legacy Agile endpoint even when the correct parent JQL has already succeeded. The old behaviour showed this as a `jql_error`, which looked like a failure although the Epic children were fetched correctly.

New behaviour:

- `parent = EPIC-KEY ORDER BY Rank ASC` remains the primary path.
- If JQL returns children, Agile fallback is skipped and recorded as `skipped: true`.
- `jql_errors` remains empty for this successful case.
- Agile fallback is used only when JQL returns no children.

## 2. Sequential Playwright report generation

The sequential execution path now always normalizes Playwright HTML output to:

```text
generated-playwright/reports/html/index.html
```

This is the path served in the GUI as:

```text
/artifacts/reports/html/index.html
```

Fixes included:

- Removed a recursive helper bug that could break report finalization.
- Sets `PLAYWRIGHT_HTML_OUTPUT_DIR` during sequential execution.
- Copies Playwright's default `playwright-report` folder into `reports/html` when needed.
- Creates a fallback HTML report if Playwright fails before native report creation.

## Recommended flow

1. JIRA -> Fetch Epic + Generate Testcases.
2. Functional Testcases -> Review and Approve.
3. Generated Playwright -> Generate Reusable Playwright.
4. Generated Playwright -> choose Sequential / safe headed debug.
5. Execute Generated Test - Headed.
6. Open Playwright report.
