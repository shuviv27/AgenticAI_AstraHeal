# Source Context + JIRA Batch Fix

This build fixes a critical enterprise pipeline issue: after fetching Jira Epic children, the GUI could still execute stale specs generated from an older SRS/PDF/manual upload session.

## Root cause fixed

The previous GUI allowed these disconnected states:

1. User fetched Jira Epic SCRUM-1.
2. Functional testcases were generated for SCRUM-2, SCRUM-3, etc.
3. The `feature` field still pointed to an older feature such as `acima`.
4. Generated Playwright / Execute looked at the old feature and ran old specs.

## New strict source context

After every input source, the backend writes `.qa-cache/active_source_context.json`.

Examples:

- Uploaded SRS/PDF/manual text: `channel=uploaded_or_pasted_source`, one active feature.
- Jira Epic: `channel=jira`, `jira_mode=epic_children`, active features are the child work items only.
- Jira Story/Task/Bug: `channel=jira`, `jira_mode=single_issue`, active feature is that issue only.

Generate Playwright and Execute now read the active context first. If a Jira Epic generated seven child features, only those seven are generated/executed. Old specs left from yesterday are not selected.

## JIRA GUI behavior

The GUI section is now named **JIRA** and supports two modes:

1. **Epic: Fetch Children + Generate Testcases**
   - Fetches Epic and all child Stories/Tasks/Bugs.
   - Generates isolated testcase JSON/Markdown per child issue.
   - Sets active context to only those children.

2. **Story/Task/Bug: Generate Testcase**
   - Fetches one issue.
   - Generates one testcase JSON/Markdown.
   - Sets active context to only that issue.

## Distributed generation/execution

- Functional testcase generation runs in parallel by source blocks / Jira children.
- Playwright generation can batch-generate specs for the active source features.
- Execution can shard only the selected active specs and merge the report.

## App Intelligence clarification

App Intelligence is the app-understanding layer. It uses URL, live DOM crawl, uploaded outerHTML/page source, MCP browser snapshot readiness, failure history, and source requirements to build a context pack.

When context is incomplete, the system now clearly recommends asking the user for:

- login / storageState
- known popups
- shadow DOM / iframe notes
- important page source / outerHTML
- screenshots
- business-critical flows
- stable test attributes

LLM assistance is used for generation/repair, but guardrails control what code is written.
