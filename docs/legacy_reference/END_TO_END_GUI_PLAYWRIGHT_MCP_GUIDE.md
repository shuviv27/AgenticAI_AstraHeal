# End-to-End GUI + AI + Playwright-MCP Guide

## Phase responsibility map

| Phase | GUI section | What it does | Main files |
|---|---|---|---|
| Phase 1 | Dashboard / Project Setup | prerequisites, project config, Docker stack, common folders | `qa_pipeline/core/*`, `infra/docker/docker-compose.yml` |
| Phase 2 | Requirement Input / Functional Testcases | PDF/DOCX/Jira/SRS parsing, AI-assisted testcase planning, testcase JSON | `qa_pipeline/parsers/*`, `qa_pipeline/agents/phase2_source_intake_rag/*`, `testcases/*` |
| Phase 3 | Generated Playwright | scans framework inventory, reuses locators/methods, writes TypeScript | `qa_pipeline/rag/framework_inventory.py`, `qa_pipeline/agents/phase3_reuse_aware_codegen/*`, `generated-playwright/*` |
| Phase 4 | Generated Playwright / Reports | static review, Playwright execution, MCP readiness | `qa_pipeline/agents/phase4_review_execution/*`, `qa_pipeline/mcp/playwright_mcp.py` |
| Phase 5 | Reports | failure classification placeholder / future healing | `qa_pipeline/agents/phase5_failure_healing/*` |
| Phase 6 | Reports | summary and governance reports | `qa_pipeline/agents/phase6_reporting_governance/*` |

## GUI flow for a non-technical user

1. Open the GUI.
2. Click **Project Setup**.
3. Enter the application URL, for example `https://your-company-app-url`.
4. Select source type, such as Jira, SRS, PDF, Confluence, or Test Management.
5. Select AI provider: Codex CLI or Ollama.
6. Click **Save project config**.
7. Click **Load required website/application** to check whether the machine can reach the URL.
8. Click **Codex / Ollama** and verify provider readiness.
9. Click **Requirement Input**.
10. Upload your PDF/DOCX/JSON/TXT or paste the requirement.
11. Click **Generate functional testcases**.
12. Review the generated testcase JSON.
13. Click **Generated Playwright**.
14. Click **Generate reusable Playwright**.
15. Open **Reports** and review the generated spec, page class, pageObjects, and reuse report.
16. Click **Static review**.
17. Click **Playwright MCP** and verify readiness.
18. Click **Execute generated test**.

## What Playwright MCP does here

Playwright MCP gives an AI/IDE a browser automation server. This build writes and validates the MCP config, then keeps deterministic Playwright Test execution for repeatable test results. This is intentional: MCP helps AI/browser interaction, while Playwright Test is the stable runner for CI and reports.

## What Docker does here

Docker starts the supporting services in a consistent way:

- Redis: event bus/orchestration readiness.
- Postgres: run history and metadata store.
- Qdrant: vector/RAG storage.
- MinIO: screenshots, traces, Playwright artifacts, generated files.
- Ollama: optional local open-source LLM runtime.
- pipeline-gui: optional containerized GUI runtime.

For the first demo you may run locally without Docker. For enterprise mode, start Docker stack from GUI or terminal.
