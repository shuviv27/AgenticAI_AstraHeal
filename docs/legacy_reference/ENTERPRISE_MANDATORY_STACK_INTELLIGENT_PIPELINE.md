# Enterprise Mandatory Stack + Intelligent Web Automation Enhancement

This build treats the enterprise technology stack as required platform infrastructure, not optional add-ons.

## Mandatory Docker stack

Start everything from repo root:

```powershell
START_ENTERPRISE_STACK_WINDOWS.cmd
```

or:

```powershell
docker compose -f infra/docker/docker-compose.yml up -d
```

Mandatory services:

| Service | Purpose |
|---|---|
| Redis | Agent bus, Redis Streams, job status, progress, idempotency and replay. |
| PostgreSQL | Durable pipeline/test/run/RCA/self-healing/audit metadata. |
| Qdrant | Primary vector DB for framework/RAG/failure memory. |
| ChromaDB | Blueprint-compatible vector store for scenarios and semantic dedup. |
| MinIO | S3-compatible storage for uploads, screenshots, traces, videos, reports and backups. |
| Prometheus | Metrics collection. |
| Grafana | KPI dashboards for Phase 5/6: pass rate, flakiness, failure rate, coverage, agent health. |
| Langfuse | LLM prompt/response/cost traces. |
| LangSmith bridge | Local readiness bridge for hosted LangSmith tracing/evaluation. |
| Jira MCP | Jira/Confluence MCP bridge. |
| GitHub MCP | GitHub branch/PR/review MCP bridge. |
| Playwright MCP | Microsoft Playwright MCP-compatible server for VS Code and AI browser assist. |
| Ollama | Local open-source LLM runtime fallback. |
| OWASP ZAP | Security testing tool. |
| k6 | Performance testing tool through manual-tools profile. |

## Intelligent app-understanding layer

Before code generation, use **App Intelligence Profiler** in the GUI. It combines:

1. URL check
2. uploaded page source / outerHTML
3. live DOM crawl
4. shadow DOM hints
5. iframe hints
6. overlay/popup/security risk detection
7. locator strategy recommendation
8. self-healing guardrails

Recommended user inputs for complex apps:

- URL and environment name
- Login/auth approach or storage state
- outerHTML/page source for target pages/components
- known popups, permissions, cookie banners
- iframes/shadow DOM/component library notes
- stable test-id/accessibility label conventions
- SRS/Jira epic/manual testcases

## Strong generation and self-healing contract

The generator must preserve:

```text
spec.ts -> pages/<PageName>Page.ts -> pageObjects/<PageName>Page.objects.ts
```

Self-healing may patch only:

```text
pageObjects/
pages/
utils/
metadata/reports
```

It must not put raw locators in `spec.ts`.

## Test classification

Functional testcase generation now classifies every scenario as:

- smoke
- functional
- regression
- accessibility
- negative
- api
- performance
- security

This appears in testcase JSON as `test_type`, `suite`, and tags.

## Distributed execution

Use the GUI Enterprise Stack page or API `/api/execute/distributed`.

For 100 tests and `shards=5`, Playwright runs about 20 tests per shard in parallel and merges blob reports into one HTML report.

## Self-learning matrix

Repeated failures are stored under:

```text
generated-playwright/reports/self-learning-failure-matrix.json
generated-playwright/reports/self-learning-failure-matrix.md
```

The matrix records repeated signatures and recommends guardrails to improve future generation/RCA/healing.
