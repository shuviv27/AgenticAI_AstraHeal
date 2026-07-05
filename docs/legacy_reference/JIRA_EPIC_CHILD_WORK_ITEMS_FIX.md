# Jira Epic Child Work Items Fix

## Problem fixed

Jira Cloud is removing the legacy `/rest/api/3/search` endpoint. New tenants can return HTTP 410 with a message asking clients to move to `/rest/api/3/search/jql`. The GUI was still using the legacy endpoint, so it could authenticate successfully but returned zero child work items for an Epic.

## Fix

`qa_pipeline/integrations/jira_client.py` now uses the current Jira Cloud enhanced JQL endpoint first:

```text
POST /rest/api/3/search/jql
```

It supports `nextPageToken` pagination and then falls back to legacy/agile methods only if needed.

## Child issue discovery order

For an Epic such as `SCRUM-1`, the client now tries:

```text
parent = SCRUM-1 ORDER BY Rank ASC
project = SCRUM AND parent = SCRUM-1 ORDER BY Rank ASC
"Epic Link" = SCRUM-1 ORDER BY Rank ASC
cf[10014] = SCRUM-1 ORDER BY Rank ASC
issue in linkedIssues(SCRUM-1) ORDER BY Rank ASC
/rest/agile/1.0/epic/SCRUM-1/issue
```

This covers modern team-managed Jira child work items and older company-managed Epic Link styles.

## Generation behavior

When child issues exist, testcase generation now creates one testcase file per child issue only, for example:

```text
testcases/jira_epics/scrum_2/scrum_2.scenarios.json
testcases/jira_epics/scrum_3/scrum_3.scenarios.json
testcases/jira_epics/scrum_4/scrum_4.scenarios.json
testcases/jira_epics/scrum_5/scrum_5.scenarios.json
```

If no child issue is returned, the framework creates a fallback testcase from the Epic summary and clearly reports that no children were returned.

## GUI output added

The Jira response now includes:

```json
{
  "children_count": 4,
  "children_keys": ["SCRUM-2", "SCRUM-3", "SCRUM-4", "SCRUM-5"],
  "search_attempts": [...],
  "parallel_generation_scope": "children_only"
}
```

The API token is still used only for the request and is not saved into `project_config.json`.
