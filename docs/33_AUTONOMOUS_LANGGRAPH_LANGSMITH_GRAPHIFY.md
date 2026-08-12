# AstraHeal Autonomous Multi-Agent Architecture

## Purpose

This build converts the previous agent-labelled pipeline into a guarded autonomous multi-agent system while retaining the existing framework scanners, Playwright runners, backups, validation, rollback, worker agents, reports, provider adapters and APIs.

The autonomous layer does not let an LLM bypass deterministic safety. LangGraph coordinates specialised agents; existing Python services are exposed as LangChain tools; deterministic build/test evidence remains the authority.

## New runtime

```text
GUI button
  -> FastAPI creates autonomous run ID
  -> LangGraph supervisor
      -> Framework Discovery Agent
      -> Code Graph Agent
      -> Playwright Gap Agent
      -> MCP / Repair / Execution / RCA agents as required
      -> Independent Review Agent
      -> Reporting Agent
  -> SQLite checkpoint + framework memory
  -> LangSmith trace when configured
  -> Server-Sent Event stream to GUI
```

The implementation is under `qa_pipeline/agentic/`:

- `state.py` — shared LangGraph state.
- `graph.py` — supervisor and specialised agent nodes.
- `tools.py` — LangChain tools wrapping existing deterministic services.
- `runtime.py` — background run manager, graph streaming and cancellation.
- `memory.py` — LangGraph SQLite checkpointer plus durable framework memory.
- `events.py` — run event persistence and SSE streaming.
- `provider_gateway.py` — unified Codex, Ollama, OpenAI, DeepSeek and Perplexity routing.
- `code_graph.py` — built-in code graph and optional Graphify augmentation.
- `playwright_doctor.py` — package/config gap detection, safe fixes and requested command execution.
- `rca_guard.py` — evidence/confidence gate and `No idea to fix` fallback.
- `api.py` — autonomous run, status, stream, memory and code-graph endpoints.

## Agent roles

### Supervisor Agent

Selects only from the allowed next agents for the selected workflow. A configured LLM may choose among valid candidates, but deterministic routing remains the fallback.

### Framework Discovery Agent

Learns:

- nested spec locations;
- page objects, fixtures and helpers;
- TypeScript aliases;
- execution scripts;
- reusable architecture;
- Playwright configuration;
- static dependency relationships;
- framework gaps and risks.

All configured providers can now contribute evidence-bound framework understanding through the common gateway.

### Code Graph Agent

Always builds a local structural graph from files, imports, declarations, tests and references. It stores graph nodes and edges in `astraheal_memory.sqlite3`.

Graphify is optional. When its CLI is installed, AstraHeal runs a code-only Graphify extraction in addition to the built-in graph. Graphify is not the sole memory source because enterprise VMs may be offline or may not have its optional dependencies.

### Playwright Gap Agent

Checks `package.json`, `tsconfig.json` and `playwright.config.*`. It reports missing or invalid dependencies, scripts, path-alias configuration, test discovery and worker configuration.

When command validation is requested it executes, in order:

```bash
npm config set registry https://registry.npmjs.org/
npm install --registry=https://registry.npmjs.org/
npx playwright install chromium
npm run build
```

Exact stdout, stderr and return codes are retained. A command is never assumed successful.

### Framework Repair Agent

After approval it:

1. creates backups;
2. applies safe package/TypeScript/Playwright configuration fixes;
3. runs the required commands;
4. invokes the existing guarded full-control repair only if blockers remain;
5. limits file scope;
6. blocks `test.skip`, `test.only`, `test.fixme`, assertion weakening and unrelated changes;
7. reruns build/list validation.

### MCP Agent

Runs Playwright MCP readiness checks. When the user starts the approved autonomous MCP preparation workflow, safe configuration fixes and selected-provider build fixes can be applied before MCP configuration is prepared.

### Distributed Execution Agent

Retains existing worker-node execution and local/central parallel sharding. Central VM/VDI stability improvements include:

- conservative worker limits (`ASTRAHEAL_LOCAL_PARALLEL_MAX_WORKERS`, default 2 on Windows);
- isolated Windows process groups;
- headless parallel shards by default on VDI/Central VM;
- one automatic isolated-headless retry when a system-abort signature is detected;
- exact shard console logs and improved failure messages.

Set `ASTRAHEAL_ALLOW_PARALLEL_HEADED=true` only when the VDI permits several interactive browser processes.

### Evidence RCA Agent

RCA must contain multiple concrete evidence markers and a confidence score above the threshold. When evidence is insufficient, AstraHeal returns:

```text
No idea to fix
```

and blocks patch application. This behaviour also guards the existing generated-framework, existing-framework and API self-healing GUI routes.

### Independent Review Agent

Reviews unresolved framework, build, execution and RCA findings independently before the final result is marked successful.

### Reporting Agent

Writes autonomous run JSON and Markdown reports under:

```text
generated-playwright/reports/agentic/
```

and binds the latest run summary into framework memory.

## SQLite memory

The project-root database is:

```text
astraheal_memory.sqlite3
```

It contains:

- LangGraph checkpoint tables created by `langgraph-checkpoint-sqlite`;
- autonomous run metadata;
- streaming events;
- cross-run framework memory;
- code graph nodes;
- code graph edges.

Each run uses a unique LangGraph thread ID to prevent state contamination. Cross-run knowledge is deliberately stored in the framework-memory tables keyed by framework path.

## LangSmith

Configure:

```env
LANGSMITH_API_KEY=...
LANGSMITH_PROJECT=astraheal-autonomous-multi-agent
LANGSMITH_ENDPOINT=https://api.smith.langchain.com
LANGSMITH_TRACING=true
LANGCHAIN_TRACING_V2=true
```

LangGraph and LangChain node/tool calls are then traced under the configured project. The GUI and `/api/agentic/status` show whether tracing is enabled.

Secrets remain environment variables and are not written into the SQLite memory, prompts, reports or project configuration.

## Streaming

Two streaming layers are included:

1. `/api/agentic/runs/{run_id}/events` streams autonomous supervisor/agent events.
2. `/api/runtime/events/stream` streams backend runtime events for every GUI API action.

The GUI opens the relevant SSE stream immediately after a button click, updates progress percentages, displays stage messages and closes the stream when the action completes.

## Graphify recommendation

Graphify is a good optional fit for static structural understanding because it creates a knowledge graph from code and documents. AstraHeal uses it as an augmentation, not the primary runtime dependency.

Recommended hybrid approach:

```text
Built-in AST/import graph     -> always available, fast, persisted in SQLite
Graphify code-only graph      -> optional richer structural augmentation
Existing framework RAG       -> searchable chunks and business context
LangGraph framework memory   -> durable decisions, gaps and validated outcomes
Live Playwright/MCP evidence  -> runtime DOM, trace, network and failure truth
```

This is stronger than using Graphify alone because static code relationships cannot prove runtime browser behaviour, current DOM state, environment failures or test-data conditions.

Optional installation:

```bash
pip install -e ".[codegraph]"
# or
pip install -r requirements-codegraph.txt
```

AstraHeal invokes:

```bash
graphify extract <framework-root> --code-only --no-viz
```

When Graphify is unavailable or fails, the built-in graph remains active and the workflow continues with an explicit warning.

## Installation

```bash
python -m pip install --upgrade pip
pip install -e .
```

With optional Graphify:

```bash
pip install -e ".[codegraph]"
# or
pip install -r requirements-codegraph.txt
```

Start the GUI using the existing platform-specific scripts. The new dependencies in `pyproject.toml` install LangChain, LangGraph, the SQLite checkpointer and LangSmith.

## Autonomous API

Start a run:

```text
POST /api/agentic/runs/start
```

Supported workflows:

- `deep_learn`
- `framework_fix`
- `mcp_prepare`
- `distributed_execute`
- `rca`
- `self_heal`
- `full_pipeline`

Other endpoints:

```text
GET  /api/agentic/status
GET  /api/agentic/runs
GET  /api/agentic/runs/{run_id}
GET  /api/agentic/runs/{run_id}/events
POST /api/agentic/runs/{run_id}/cancel
POST /api/agentic/code-graph/index
POST /api/agentic/code-graph/query
GET  /api/agentic/memory
```

## GUI simplification

The GUI keeps Start Here focused on runtime and AI-provider connectivity. Framework learning, code-graph indexing, Playwright health checks, guarded repair and MCP preparation are consolidated under Existing Framework. RCA/self-healing remains under Run & Fix Tests, while agent-service health and technical reports are under Logs & Reports. Existing backend routes remain available for compatibility.

## Safety boundary

“Autonomous” means autonomous planning, routing, tool use, validation and reporting within approved scope. It does not mean unrestricted file modification. Repository changes still require approval and remain subject to backup, scope, diff, forbidden-pattern, build and Playwright validation gates.
