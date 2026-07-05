# Phase 5/6 Enterprise Stack Enhancement

This build keeps the existing GUI, Playwright generation, RCA/self-healing, Codex/Ollama, Docker, and reporting flow intact. It adds optional enterprise capabilities aligned to the blueprint:

- Grafana + Prometheus for QA/agent metrics and KPI dashboards.
- Langfuse for LLM prompt, response, cost and trace observability.
- LangSmith configuration support through `LANGCHAIN_*` variables.
- Jira API connector using Jira URL + username/email + API token.
- Jira MCP and GitHub MCP optional Docker profile for future agent/IDE bridge flows.
- Parallel functional testcase generation for multiple Jira issues or pasted blocks.
- Local distributed Playwright execution using `--shard=i/n`.

## Start core stack only

```powershell
cd C:\AI_QA_PIPELINE\AdvancedAIAutomation_EnterpriseStack_Jira_Distributed_Build
docker compose -f infra/docker/docker-compose.yml up -d redis postgres qdrant minio
```

## Start observability stack

```powershell
docker compose -f infra/docker/docker-compose.yml --profile observability up -d prometheus grafana langfuse-db langfuse
```

Open:

- Grafana: http://localhost:3001, default local user/pass `admin/admin` unless changed in `.env`.
- Prometheus: http://localhost:9090.
- Langfuse: http://localhost:3002.

## Start Jira/GitHub MCP stack

```powershell
docker compose -f infra/docker/docker-compose.yml --profile mcp up -d jira-mcp github-mcp
```

Required environment variables:

```powershell
$env:JIRA_URL="https://yourcompany.atlassian.net"
$env:JIRA_USERNAME="name@company.com"
$env:JIRA_API_TOKEN="your-atlassian-api-token"
$env:GITHUB_TOKEN="your-github-pat"
```

## Jira Epic to Testcases

GUI path:

```text
Jira Epic -> enter Jira URL, username/email, API token, Epic key -> Check Jira connection -> Fetch Epic + Generate Testcases
```

API behavior:

1. Calls `/rest/api/3/myself` to verify credentials.
2. Reads the epic by key.
3. Tries child issue JQL patterns: `parent = EPIC`, `"Epic Link" = EPIC`, and linked issues.
4. Converts Jira ADF descriptions to plain text.
5. Generates isolated testcase JSON/Markdown in parallel under `testcases/jira_epics/<issue_key>/`.

The API token is used for the request only and is not saved into `project_config.json`.

## Parallel testcase generation

Manual input can be pasted as multiple blocks separated by `---` in the Jira Epic screen. The backend uses a worker pool and writes each feature to a separate file to avoid same-session overwrites.

## Distributed execution

GUI path:

```text
Enterprise Stack -> Execute distributed/headless or headed
```

The backend runs Playwright shards locally:

```powershell
npx playwright test tests/generated/<feature>.spec.ts --project=chromium --shard=1/4
npx playwright test tests/generated/<feature>.spec.ts --project=chromium --shard=2/4
npx playwright test tests/generated/<feature>.spec.ts --project=chromium --shard=3/4
npx playwright test tests/generated/<feature>.spec.ts --project=chromium --shard=4/4
```

For true distributed execution, run each shard command on separate CI runners or containers. The local GUI implementation proves the same contract without requiring a cluster.

## What happens if these services are not started?

The existing local workflow still works. You can generate and execute Playwright scripts without Grafana, Langfuse, Jira MCP, GitHub MCP, or LangSmith. These services add enterprise traceability, observability, and integration depth; they are not required for a simple local Acima smoke test.
