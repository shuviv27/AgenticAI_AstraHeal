# AstraHeal AI Module-2: Detailed Project Component and File Map

This document explains the important files, folders and runtime components in the repo. It is intended for technical onboarding and VM/VDI setup reviews.

## Root files

| File | Purpose | Significance during run |
|---|---|---|
| `README.md` | Main project overview and quick start. | First file for developers/team leads to understand the platform. |
| `README_FIRST.md` | Practical start guide for the latest build. | Use this before running the GUI. It summarizes the recommended workflow and latest enhancements. |
| `README_ENTERPRISE_MANDATORY.md` | Enterprise usage constraints and mandatory architecture notes. | Explains guardrails, enterprise stack expectations and controlled execution. |
| `requirements.txt` | Core Python dependencies. | Used by `python -m pip install -r requirements.txt`. |
| `requirements-enterprise.txt` | Extra enterprise/observability/runtime dependencies. | Included by `requirements.txt`; used for enterprise stack features. |
| `setup.py` | Python packaging entry point. | Allows editable install or package build for the `qa_pipeline` package. |
| `pyproject.toml` | Modern Python build metadata. | Defines project name, package discovery and Python dependency metadata. |
| `.env.example` | Environment variable template. | Copy to `.env` and configure URLs, runtime engine, Codex/Ollama/OpenAI/DeepSeek keys, VM/VDI options. |
| `.npmrc` | NPM registry / SSL settings. | Keeps generated Playwright npm install pointed to approved npm registry. |
| `.gitignore` | Git ignore rules. | Avoids committing cache, reports, secrets and generated artifacts. |
| `.project-config.example.json` | Example GUI project configuration. | Shows config shape used by GUI actions. |

## Root Windows/Mac/Linux launchers

| File | Purpose |
|---|---|
| `START_MODULE_GUI_WINDOWS.cmd` | Starts Module-2 GUI on Windows. Recommended for simple local/VM run. |
| `START_MODULE_GUI_VM_WINDOWS.cmd` | Starts Module-2 GUI with VM-friendly defaults. |
| `START_AI_QA_GUI_LOCAL_WINDOWS.cmd` | Starts full GUI in Local PC mode. |
| `START_AI_QA_GUI_NO_DOCKER_WINDOWS.cmd` | Starts GUI in No-Docker Host Runtime mode. |
| `START_AI_QA_GUI_VM_CONTROL_PLANE_WINDOWS.cmd` | Starts central VM control plane. Use for VM-1 hub. |
| `START_AI_QA_GUI_NO_DOCKER_VM_WINDOWS.cmd` | Starts central VM using host runtime, no Docker. |
| `START_AI_QA_GUI_VDI_WINDOWS.cmd` | Starts VDI-specific mode when GUI itself is run from VDI. |
| `START_AI_QA_GUI_SELECT_MODE_WINDOWS.cmd` | Interactive mode selector for Windows. |
| `START_GUI_MAC.sh`, `START_AI_QA_GUI_MAC.sh`, `START_MODULE_GUI_MAC.sh` | Mac launchers. |
| `START_AI_QA_GUI_LINUX.sh`, `START_AI_QA_GUI_VDI_LINUX.sh` | Linux launchers. |
| `INSTALL_WINDOWS.ps1`, `INSTALL_GUI_DEPS_WINDOWS.cmd`, `INSTALL_MAC.sh` | Install prerequisites/dependencies. |
| `UNBLOCK_WINDOWS_FILES.cmd` | Removes Windows downloaded-file block flags after extracting ZIP. |

## `qa_pipeline/` package

### `qa_pipeline/gui/`

| File | Purpose |
|---|---|
| `qa_pipeline/gui/app.py` | FastAPI GUI/backend. Defines all HTTP endpoints, including framework learning, execution, distributed run, agentic node-hub, RCA, self-healing, history, provider config and reports. |
| `qa_pipeline/gui/static/index.html` | Single-page GUI. Provides Start Here, Existing Framework, Run & Fix Tests, Add New Tests Later, Logs & Reports and runtime popup controls. |

### `qa_pipeline/core/`

| File | Purpose |
|---|---|
| `paths.py` | Central paths for repo root, generated reports, cache folders and generated framework folders. |
| `config.py` | Environment/config helpers. |
| `project_config.py` | Saves and loads project-level GUI config. |
| `commands.py` | Safe wrapper around subprocess commands. |
| `runtime_logger.py` | Writes runtime events used by live progress and reports. |
| `runtime_mode.py` | Reads/writes Docker vs No-Docker and Local vs VM/VDI runtime profile. |
| `host_runtime.py` | No-Docker host runtime readiness/start logic. Checks Python, Node, npm, Git, Playwright, Codex/Ollama, etc. |
| `docker_stack.py` | Docker runtime operations such as status, start, stop, pull. |
| `api_docker_runtime.py` | Docker support for API automation services. |
| `vdi_agent_control.py` | Runner-agent token creation, package generation, registration, heartbeat, polling, job creation/completion. Supports VDI and worker VM agents. |
| `vdi_readiness.py` | Readiness checks for VDI/Horizon style execution. |
| `distributed_history.py` | Basic node-hub distributed plan/run/status/report/history. Keeps framework-local `.aiqa-history` reports. |
| `agentic_nodehub.py` | New agentic node-hub orchestration: master VM as worker, explicit worker allocations, immediate rerun, parallel RCA/self-healing events, final failed rerun, report writing. |
| `human_intervention.py` | Human-in-the-loop memory, approval notes and human clarification reports. |
| `action_history.py` | AI action/audit history memory. |
| `agent_registry.py` | Agent capability registry and coverage report. |
| `active_context.py` | Stores active source/testcase context. |
| `app_probe.py` | Checks AUT reachability. |
| `url_guard.py` | URL normalization and guard utilities. |

### `qa_pipeline/agents/existing_framework_control/`

| File | Purpose |
|---|---|
| `controller.py` | Main Module-2 controller for external Playwright framework learning, execution, selected tests, failed-only rerun, RCA, self-healing, approval request, rollback, new test generation into existing framework. |
| `deep_framework_agents.py` | Multi-agent framework understanding: architecture, code semantics, dependency graph, locator strategy, AUT flow, memory. |
| `framework_intelligence.py` | Framework analysis and reusable intelligence reports. |
| `robust_rca.py` | Multi-signal RCA evidence chain and failure classification. |
| `mcp_locator_rca.py` | Playwright MCP-assisted locator/actionability diagnosis. |

### `qa_pipeline/agents/phase2_source_intake_rag/`

| File | Purpose |
|---|---|
| `ingest.py` | Converts uploaded/pasted source content into normalized testcase input. |
| `connectors.py` | Connector helpers for Jira/Confluence-style input. |
| `ai_testcase_planner.py` | AI-assisted testcase planning. |
| `parallel_testcase_generation.py` | Parallel testcase generation helper. |
| `rag_knowledge_agent.py` | RAG knowledge support for source intake. |
| `requirement_quality_gate.py` | Quality gate for unclear requirements. |
| `test_design_agent.py` | Converts requirement intent into test design. |

### `qa_pipeline/agents/phase3_reuse_aware_codegen/`

| File | Purpose |
|---|---|
| `framework_analyzer.py` | Reads framework structure for reuse-aware generation. |
| `reuse_generator.py` | Generates Playwright files while following POM and reuse rules. |
| `dynamic_crawler.py` | Crawls DOM/page source for locator discovery where allowed. |
| `locator_strategy.py` | Locator strategy and stability helpers. |
| `pom_locator_agent.py` | Page object / locator file placement logic. |
| `page_source_analyzer.py` | Uses uploaded or captured page source for codegen. |
| `app_intelligence_profiler.py` | Captures app flow hints and UI structure. |
| `codex_prompt.py` | Builds Codex prompts for code generation. |

### `qa_pipeline/agents/phase4_review_execution/`

| File | Purpose |
|---|---|
| `executor.py` | Generated-framework execution, sequential/distributed modes, failed-only rerun, report handoff. |
| `reviewer.py` | Reviews generated scripts. |
| `pr_automation.py` | PR automation helper. |

### `qa_pipeline/agents/phase5_failure_healing/`

| File | Purpose |
|---|---|
| `root_cause_agent.py` | Root cause analysis for generated-framework runs. |
| `self_healing_agent.py` | Self-healing for generated framework. |
| `failure_classifier.py` | Failure classification. |
| `evidence_collector.py` | Evidence collection utilities. |
| `healing_policy.py` | Policy/guardrail checks for fixes. |
| `enterprise_rca_taxonomy.py` | Enterprise RCA categories. |

### `qa_pipeline/agents/phase6_reporting_governance/`

| File | Purpose |
|---|---|
| `reporter.py` | Generates summary/enterprise HTML reports. |
| `failure_learning_agent.py` | Stores failure learning memory. |
| `governance_agent.py` | Governance checks. |
| `model_validation_agent.py` | Model validation matrix support. |
| `drift_maintenance_agent.py` | Drift/maintenance checks. |

### `qa_pipeline/llm/`

| File | Purpose |
|---|---|
| `codex_cli.py` | Local Codex CLI wrapper. Used for direct workspace-aware file modifications. |
| `ollama.py` | Local Ollama chat wrapper. |
| `openai_compatible.py` | Dependency-free OpenAI-compatible chat client for OpenAI/DeepSeek RCA and proposal guidance. |

### `qa_pipeline/rag/`

| File | Purpose |
|---|---|
| `framework_inventory.py` | Builds inventory of framework files. |
| `lightweight_index.py` | Lightweight JSONL index/query for RAG context without requiring heavy vector DB setup. |

### `qa_pipeline/mcp/`

| File | Purpose |
|---|---|
| `playwright_mcp.py` | Playwright MCP integration helper. |

### `qa_pipeline/integrations/`

| File | Purpose |
|---|---|
| `jira_client.py` | Jira API integration helper. |
| `observability.py` | Observability/metrics integration. |

### `qa_pipeline/modules/`

| Folder | Purpose |
|---|---|
| `functional_testcase_generator/` | Module-1 controller for functional testcase generation. |
| `playwright_ts_generator/` | Module-2 generated Playwright TypeScript generation controller. |

## `generated-playwright/`

This is the sample/generated Playwright framework inside the solution repo. It is not the source of truth when you use an external framework.

| Folder/File | Purpose |
|---|---|
| `generated-playwright/package.json` | Node dependencies/scripts for generated framework. |
| `generated-playwright/playwright.config.ts` | Playwright config for generated framework. |
| `generated-playwright/tests/` | Generated sample specs. |
| `generated-playwright/pages/` | Generated page classes. |
| `generated-playwright/pageObjects/` | Generated locator objects. |
| `generated-playwright/utils/` | Reusable helpers such as safe actions, locator factory, popup/dialog handling. |
| `generated-playwright/fixtures/` | Playwright fixtures and telemetry. |
| `generated-playwright/testData/` | Generated test data. |
| `generated-playwright/reports/` | GUI mirror reports. For external frameworks, source-of-truth reports live in `<framework>/.aiqa-history/reports`. |

## `generated-api-playwright/` and `generated-api-restassured/`

These are API automation outputs.

| Folder | Purpose |
|---|---|
| `generated-api-playwright/` | Playwright API testing framework. |
| `generated-api-restassured/` | Java Rest Assured framework. |

## `infra/`

| Folder/File | Purpose |
|---|---|
| `infra/docker/docker-compose.yml` | Enterprise Docker stack definition. |
| `infra/docker/Dockerfile.pipeline` | Pipeline container image definition. |
| `infra/observability/prometheus.yml` | Prometheus configuration. |

## `configs/`

| File | Purpose |
|---|---|
| `configs/self-healing-policy.json` | Guardrails for patch validation. |
| `configs/vdi-runtime-profile.example.json` | Example VDI runtime profile. |
| `configs/reference-framework-profiles.json` | Seed learning profiles from uploaded Playwright/SFCC-style frameworks. |

## `docs/`

Contains detailed guides for runtime setup, distributed execution, Playwright MCP, RCA, self-healing, VM/VDI, Docker/No-Docker, human approval popup, policy modes, new test generation and report locations.

## `.qa-cache/`

Runtime memory/cache folder. Do not commit sensitive content.

| Folder | Purpose |
|---|---|
| `.qa-cache/existing-framework/` | RAG chunks, framework understanding memory, failed inventory and agentic memory. |
| `.qa-cache/runner-agents/` | Runner-agent tokens, agents, jobs and generated worker packages. |
| `.qa-cache/framework-execution-history/` | Central cross-framework history. |
| `.qa-cache/agentic-nodehub-runs/` | Agentic node-hub run state mirror. |
| `.qa-cache/runtime/` | Live runtime logs/status. |

## External Playwright framework folders

When you point the GUI to an existing framework outside this repo, reports/history are written inside that framework:

```text
<framework>/.aiqa-history/executions.jsonl
<framework>/.aiqa-history/latest-execution.json
<framework>/.aiqa-history/reports/distributed-execution-report.html
<framework>/.aiqa-history/reports/agentic-nodehub-report.html
<framework>/.aiqa-history/agentic-nodehub-runs/<run-id>/run-state.json
```

This keeps the audit trail with the framework branch/workspace instead of only inside the AI solution repo.
