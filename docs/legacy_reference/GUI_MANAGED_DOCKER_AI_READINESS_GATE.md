# GUI-managed Docker + AI Provider Readiness Gate

This enhancement moves the enterprise Docker stack startup into the GUI workflow.

## Why

The enterprise QA pipeline should behave like a controlled platform. Users should not accidentally generate testcases, generate Playwright, run distributed tests, or apply self-healing while the mandatory platform stack is missing.

## New behavior

1. Docker Desktop must be running on the machine.
2. The GUI starts the mandatory Docker stack from **Enterprise Stack -> Pull images + start from GUI**.
3. The backend validates:
   - Docker CLI exists.
   - Docker Desktop engine responds to `docker info`.
   - `infra/docker/docker-compose.yml` is valid.
   - Mandatory images can be pulled.
   - Mandatory containers are running/healthy where health checks exist.
4. The GUI readiness banner stays locked until Docker is ready and the selected AI provider is connected.
5. Workflow buttons for Jira/SRS generation, Playwright generation, execution, RCA, and self-healing are disabled until the readiness gate is green.

## Mandatory Docker services

- Redis: agent bus, job/progress state, stream replay, idempotency locks.
- PostgreSQL: pipeline metadata, testcase records, execution history, RCA/self-heal audit trail.
- Qdrant: vector/RAG store for framework inventory, DOM maps and failure memory.
- ChromaDB: additional vector/RAG test registry and semantic testcase retrieval.
- MinIO: S3-compatible artifact storage for uploads, reports, screenshots, videos and traces.
- Prometheus: metrics collection.
- Grafana: enterprise dashboards.
- Langfuse + Langfuse DB: LLM tracing/prompt/cost observability.
- LangSmith bridge: readiness check for hosted LangSmith tracing variables.
- Jira MCP: Jira/Confluence MCP bridge.
- GitHub MCP: GitHub repo/PR MCP bridge.
- Playwright MCP: Microsoft Playwright MCP-compatible browser-assist server.
- Ollama: local open-source model runtime fallback.
- OWASP ZAP: security scan service.

## AI session management

### Codex

Use **Codex / Ollama -> Codex login/device auth** from the GUI. The GUI runs local Codex login and then checks `codex login status`. The framework never stores ChatGPT username/password or Codex tokens.

### Ollama

Use **Codex / Ollama -> Ensure Ollama Docker model** from the GUI. The backend starts the Docker Ollama service and runs `ollama pull <model>` inside the container.

## New backend APIs

- `GET /api/prereq/readiness`
- `GET /api/docker/readiness`
- `POST /api/docker/pull`
- `POST /api/docker/logs`
- `POST /api/ollama/ensure-model`

## Startup sequence

1. Start Docker Desktop manually.
2. Run `START_GUI_WINDOWS.cmd`.
3. Open `http://127.0.0.1:8080`.
4. Go to **Enterprise Stack** and click **Pull images + start from GUI**.
5. Go to **Codex / Ollama** and connect the selected AI provider.
6. When the readiness banner is green, continue with Jira/SRS/PDF ingestion and generation.

`START_ENTERPRISE_STACK_WINDOWS.cmd` still exists for automation/CI compatibility, but the recommended user flow is now GUI-managed startup.
