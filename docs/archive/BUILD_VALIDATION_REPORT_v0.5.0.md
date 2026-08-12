# AstraHeal AI v0.5.0 Autonomous Multi-Agent Build Validation Report

**Build:** `0.5.0`  
**Validation date:** 2026-07-26  
**Scope:** LangChain/LangGraph autonomous orchestration, LangSmith observability, project-root SQLite memory, code-graph indexing, GUI streaming, Playwright framework diagnosis/repair, distributed-execution hardening, and evidence-gated RCA.

## Delivered architecture

The existing deterministic scanners, parsers, Playwright runners, worker protocol, backup/rollback controls, reports, provider adapters, and legacy APIs remain available. A new guarded autonomous layer under `qa_pipeline/agentic/` coordinates them as LangChain tools through a LangGraph supervisor.

Implemented specialist roles:

1. Supervisor Agent
2. Framework Discovery Agent
3. Code Graph Agent
4. Playwright Gap Agent
5. Framework Repair Agent
6. Playwright MCP Agent
7. Validation Agent
8. Distributed Execution Agent
9. Evidence RCA Agent
10. Independent Review Agent
11. Reporting Agent

Supported autonomous workflows:

- `deep_learn`
- `framework_fix`
- `mcp_prepare`
- `distributed_execute`
- `rca`
- `self_heal`
- `full_pipeline`

## Memory and observability

- Root database: `astraheal_memory.sqlite3`
- LangGraph thread checkpoints use the SQLite checkpointer when the dependency is installed.
- Cross-run framework inventory, gaps, code-graph nodes/edges, run metadata, and streaming events are persisted in the same database.
- LangSmith tracing is enabled only when `LANGSMITH_API_KEY` is configured.
- Secrets are not written to SQLite framework memory or autonomous reports.

## Streaming and GUI

- Per-run SSE: `/api/agentic/runs/{run_id}/events`
- Global GUI action SSE: `/api/runtime/events/stream`
- Every GUI API action receives backend start/end events; long-running services continue to publish their existing detailed progress events.
- Autonomous runs show supervisor and agent-level progress in the GUI timeline.
- Duplicate/low-value controls were removed while legacy backend routes were retained for compatibility.

## Playwright framework learning and repair

The deep-learning workflow now combines:

- existing framework inventory and Advanced RAG;
- nested spec/page/fixture/config discovery;
- built-in code relationships stored in SQLite;
- optional Graphify code-only extraction;
- package/config gap analysis;
- selected-provider evidence-bound architecture understanding;
- independent review and a persisted report.

When command validation is requested, the Playwright doctor runs in this exact order:

```bash
npm config set registry https://registry.npmjs.org/
npm install --registry=https://registry.npmjs.org/
npx playwright install chromium
npm run build
```

Safe configuration repair covers missing or invalid `package.json`, `tsconfig.json`, and `playwright.config.*` content. Repository modifications remain backup-first, scope-limited, validated, and rollback-capable.

## Graphify decision

Graphify is integrated as an optional structural augmenter, not as the single source of framework truth. The always-available built-in graph records files, declarations, imports, test/page/config roles, and unresolved relationships in SQLite. When `graphify` is installed, AstraHeal additionally runs:

```bash
graphify extract <framework-root> --code-only --no-viz
```

This hybrid design remains functional on offline corporate VMs and supplements static structure with existing RAG plus live Playwright/MCP evidence.

## Distributed execution correction

Central VM/VDI local parallel execution now includes:

- conservative worker caps, configurable with `ASTRAHEAL_LOCAL_PARALLEL_MAX_WORKERS`;
- isolated Windows process groups and no-window flags;
- headless parallel shards by default on VM/VDI;
- a one-time isolated-headless retry only for recognised system-abort signatures;
- no infrastructure retry for ordinary Playwright assertion/test failures;
- clearer shard evidence and failure messages.

## Hallucination control

RCA and self-healing now require multiple concrete evidence markers plus a minimum confidence threshold. Without sufficient stack, trace, screenshot, locator, network, DOM, stdout/stderr, or return-code evidence, the system returns:

```text
No idea to fix
```

and blocks patch application. Likely speculative patch fields are removed from the response.

## Validation completed

- Python source compilation: **passed**
- GUI JavaScript syntax (`node --check`): **passed**
- FastAPI application import and route registration: **passed**
- Health/status/runs endpoints: **passed**
- Project-root SQLite schema initialization: **passed**
- Guarded deep-learning compatibility workflow: **passed**
- Source wheel build without dependency resolution: **passed**
- Automated test suite: **43 passed**
- VM startup validation script: **passed**
- Final ZIP integrity and clean-extraction validation: **passed**

## Build-environment limitation

This sandbox cannot resolve external PyPI hosts, so LangChain, LangGraph, LangSmith, the SQLite checkpointer, and optional Graphify could not be installed here for live third-party runtime execution. Their supported dependencies and integration APIs are declared in `pyproject.toml` and `setup.py`. The guarded compatibility runner was exercised so legacy behaviour remains usable before installation.

On the Central VM/VDI, install the dependencies and confirm the real graph runtime:

```bash
python -m pip install --upgrade pip
pip install -e .
# Optional Graphify
pip install -e ".[codegraph]"
```

Then open `/api/agentic/status` and verify:

```text
langgraph_available=true
langchain_available=true
langsmith.enabled=true   # when LANGSMITH_API_KEY is configured
```
