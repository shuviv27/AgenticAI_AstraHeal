# v12 Agent and Phase Coverage Verification

This build preserves the existing v11 working features and adds an **Agents & Phases** GUI page plus backend registry endpoint.

## What changed without breaking existing behavior

- Added `qa_pipeline/core/agent_registry.py` as the single source of truth for all implemented, stubbed, and planned agents.
- Added backend endpoints:
  - `GET /api/agents`
  - `GET /api/agents/coverage`
- Added GUI left-menu item: **Agents & Phases**.
- Added visible coverage cards for every agent, including files, status, LLM mode, responsibility, outputs, and GUI actions.
- Added stub/adapter modules for planned agents so they are visible and future extensible without disturbing current functional testcase generation, dynamic crawl, Playwright generation, execution, MCP readiness, or reporting.

## Enterprise document alignment

The uploaded enterprise architecture lists the following major agent/service responsibilities:

1. Orchestrator / Workflow Agent
2. Connector Agent
3. Requirements Agent
4. Requirement Quality Gate Agent
5. RAG Knowledge Agent
6. Framework Analyzer Agent
7. Test Design Agent
8. POM and Locator Agent
9. Test Generator Agent
10. API Test Generator Agent
11. Code Review Agent
12. Execution Agent
13. Failure Analysis Agent
14. Self-Healing Agent
15. Root Cause Agent
16. Reporting Agent
17. Drift and Maintenance Agent
18. Model Validation Agent

v12 registers all of the above and also exposes supporting platform agents:

- Environment / Doctor Agent
- Docker Runtime Agent
- Provider Gateway Agent
- Dynamic Web Crawler Agent
- Playwright MCP Agent
- PR Automation Agent
- Security / Governance Agent

## Current maturity model

| Status | Meaning |
|---|---|
| available | Working in the current pipeline flow |
| available/stubbed | Registered and callable as safe metadata/checklist, needs deeper production implementation later |
| planned/stubbed | Intentionally visible but not auto-active, so it does not affect the current working flow |

## Phase mapping

| Phase | Main capabilities visible in GUI |
|---|---|
| Phase 1 | Doctor, project setup, Docker runtime, provider gateway, orchestration metadata |
| Phase 2 | Source upload, parsing, requirement extraction, functional testcase generation, quality scoring, RAG context |
| Phase 3 | Framework analyzer, dynamic crawler, POM/locator generation, reusable Playwright generation, API test placeholder |
| Phase 4 | Static review, execution, MCP readiness, PR metadata placeholder |
| Phase 5 | Failure classification, self-healing proposal placeholder, RCA draft placeholder |
| Phase 6 | HTML reporting, governance checklist, drift maintenance placeholder, model validation matrix |

## How to verify from GUI

1. Start GUI.
2. Open `http://127.0.0.1:8080`.
3. Click **Agents & Phases** from the left menu.
4. Click **Check all agents and phases**.
5. Review:
   - total agent count
   - covered agent count
   - partial/stubbed count
   - missing files if any
   - phase-wise responsibilities

## How to verify from API

```bash
curl http://127.0.0.1:8080/api/agents
```

## Important non-impact promise

The added agent registry and stub modules are read-only/safe by default. They do not change the existing functional testcase generation, Playwright generation, static review, execution, Docker, Codex/Ollama, or report paths.
