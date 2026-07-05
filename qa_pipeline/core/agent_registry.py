from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

from qa_pipeline.core.paths import REPO_ROOT


@dataclass(frozen=True)
class AgentDefinition:
    phase: str
    module: str
    agent_id: str
    display_name: str
    llm_mode: str
    responsibility: str
    primary_outputs: str
    implementation_files: list[str]
    gui_actions: list[str]
    status: str = "available"
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["files_exist"] = {p: (REPO_ROOT / p).exists() for p in self.implementation_files}
        data["missing_files"] = [p for p, ok in data["files_exist"].items() if not ok]
        data["coverage_status"] = "covered" if not data["missing_files"] else "stubbed/partial"
        return data


AGENT_DEFINITIONS: list[AgentDefinition] = [
    AgentDefinition(
        phase="Phase 1",
        module="Bootstrap and Platform Foundation",
        agent_id="orchestrator-workflow-agent",
        display_name="Orchestrator / Workflow Agent",
        llm_mode="No LLM",
        responsibility="Owns pipeline run state, routing, phase gates, retry decisions, circuit breakers, and manual approval placeholders.",
        primary_outputs="pipeline_run, phase_run, next command, dashboard status",
        implementation_files=["qa_pipeline/agents/phase1_foundation/orchestrator_workflow.py", "qa_pipeline/core/schemas.py", "qa_pipeline/core/project_config.py"],
        gui_actions=["Verify prerequisites", "Project setup", "Run phase sequence"],
        status="available",
    ),
    AgentDefinition(
        phase="Phase 1",
        module="Bootstrap and Platform Foundation",
        agent_id="environment-doctor-agent",
        display_name="Environment / Doctor Agent",
        llm_mode="No LLM",
        responsibility="Checks Python, Node/npm/npx, Docker, Codex, Ollama, and expected folder structure before pipeline execution.",
        primary_outputs="doctor report and prerequisite status",
        implementation_files=["qa_pipeline/agents/phase1_foundation/doctor.py"],
        gui_actions=["Dashboard -> Verify prerequisites"],
        status="available",
    ),
    AgentDefinition(
        phase="Phase 1",
        module="Bootstrap and Platform Foundation",
        agent_id="docker-runtime-agent",
        display_name="Docker Runtime Agent",
        llm_mode="No LLM",
        responsibility="Starts/stops/checks local Docker Compose services: Redis, Postgres, Qdrant, MinIO, optional Ollama, optional GUI container.",
        primary_outputs="docker service status, compose logs hint, running service list",
        implementation_files=["qa_pipeline/core/docker_stack.py", "infra/docker/docker-compose.yml"],
        gui_actions=["Project Setup -> Check Docker", "Start core Docker stack", "Start stack + Ollama"],
        status="available",
    ),
    AgentDefinition(
        phase="Phase 1",
        module="Observability and MCP Runtime",
        agent_id="enterprise-stack-agent",
        display_name="Enterprise Stack Agent",
        llm_mode="No LLM",
        responsibility="Checks and starts optional Grafana, Prometheus, Langfuse, Jira MCP, GitHub MCP, and LangSmith environment readiness without breaking core local execution.",
        primary_outputs="enterprise stack status, observability URLs, MCP readiness hints",
        implementation_files=["qa_pipeline/integrations/observability.py", "infra/docker/docker-compose.yml", "infra/observability/prometheus.yml"],
        gui_actions=["Enterprise Stack -> Check enterprise stack", "Enterprise Stack -> Start observability + MCP stack"],
        status="available",
        notes="LangSmith is configured through LANGCHAIN_* variables because it is SaaS-hosted; Grafana/Prometheus/Langfuse run in Docker profile observability.",
    ),
    AgentDefinition(
        phase="Phase 1",
        module="Observability and MCP Runtime",
        agent_id="jira-github-mcp-agent",
        display_name="Jira/GitHub MCP Agent",
        llm_mode="MCP bridge / No LLM",
        responsibility="Provides optional Jira/Confluence and GitHub MCP bridge configuration for agentic source intake, PR review, and governance workflows.",
        primary_outputs="mcp configs, docker profile status, Jira/GitHub bridge readiness",
        implementation_files=["mcp/jira-github-mcp.json", "infra/docker/docker-compose.yml"],
        gui_actions=["Enterprise Stack -> Start observability + MCP stack", "Jira Epic -> Fetch Epic"],
        status="available",
    ),
    AgentDefinition(
        phase="Phase 1",
        module="Bootstrap and Platform Foundation",
        agent_id="provider-gateway-agent",
        display_name="Provider Gateway Agent",
        llm_mode="Codex CLI / Ollama / deterministic fallback",
        responsibility="Centralizes provider checks and routes AI assistance to Codex CLI or Ollama while preserving deterministic guardrails.",
        primary_outputs="provider health, AI messages, fallback decisions",
        implementation_files=["qa_pipeline/llm/codex_cli.py", "qa_pipeline/llm/ollama.py"],
        gui_actions=["Codex/Ollama -> Check Codex/Ollama"],
        status="available",
    ),
    AgentDefinition(
        phase="Phase 2",
        module="Connectors and Ingestion",
        agent_id="connector-agent",
        display_name="Connector Agent",
        llm_mode="No LLM / MCP-ready",
        responsibility="Normalizes uploaded/pasted Jira, SRS, PDF, DOCX, text, and future Confluence/Test Management inputs into source documents.",
        primary_outputs="source_document, normalized JSON, source metadata",
        implementation_files=["qa_pipeline/agents/phase2_source_intake_rag/connectors.py", "qa_pipeline/parsers/source_parser.py"],
        gui_actions=["Requirement Input -> upload/paste input"],
        status="available",
    ),
    AgentDefinition(
        phase="Phase 2",
        module="Connectors and Ingestion",
        agent_id="jira-api-connector-agent",
        display_name="Jira API Connector Agent",
        llm_mode="No LLM",
        responsibility="Connects to Jira with URL, username/email, and API token; fetches epic, child stories, descriptions, acceptance criteria, and converts them to testcase-generation source text.",
        primary_outputs="Jira epic source text, child issue list, testcase generation source",
        implementation_files=["qa_pipeline/integrations/jira_client.py"],
        gui_actions=["Jira Epic -> Check Jira connection", "Jira Epic -> Fetch Epic + Generate Testcases"],
        status="available",
        notes="API token is used for the request only and is not persisted in project_config.json.",
    ),
    AgentDefinition(
        phase="Phase 2",
        module="Requirements and Quality Scoring",
        agent_id="parallel-testcase-generation-agent",
        display_name="Parallel Testcase Generation Agent",
        llm_mode="Rules + optional downstream Codex/Ollama",
        responsibility="Generates functional testcase JSON/Markdown for multiple Jira issues or pasted blocks concurrently using isolated per-feature files.",
        primary_outputs="multiple testcases/<source>/<feature>/*.scenarios.json files and summary report",
        implementation_files=["qa_pipeline/agents/phase2_source_intake_rag/parallel_testcase_generation.py"],
        gui_actions=["Jira Epic -> Fetch Epic + Generate Testcases", "Jira Epic -> Generate parallel testcase files"],
        status="available",
    ),
    AgentDefinition(
        phase="Phase 2",
        module="Requirements and Quality Scoring",
        agent_id="requirements-agent",
        display_name="Requirements Agent",
        llm_mode="Codex CLI / Ollama + deterministic parser",
        responsibility="Extracts requirements, acceptance criteria, user flow steps, and structured scenarios from source documents.",
        primary_outputs="Requirement objects, functional testcase JSON, missing info list",
        implementation_files=["qa_pipeline/agents/phase2_source_intake_rag/ingest.py", "qa_pipeline/agents/phase2_source_intake_rag/ai_testcase_planner.py"],
        gui_actions=["Requirement Input -> Generate functional testcases"],
        status="available",
    ),
    AgentDefinition(
        phase="Phase 2",
        module="Requirements and Quality Scoring",
        agent_id="requirement-quality-gate-agent",
        display_name="Requirement Quality Gate Agent",
        llm_mode="Rules + optional AI",
        responsibility="Scores extracted scenarios for completeness, duplicate risk, start URL quality, and readiness for Playwright generation.",
        primary_outputs="quality score, warn/block decision, remediation notes",
        implementation_files=["qa_pipeline/agents/phase2_source_intake_rag/requirement_quality_gate.py"],
        gui_actions=["Functional Testcases -> coverage/quality summary"],
        status="available",
    ),
    AgentDefinition(
        phase="Phase 2",
        module="RAG Knowledge and Indexing",
        agent_id="rag-knowledge-agent",
        display_name="RAG Knowledge Agent",
        llm_mode="No LLM + lightweight/vector-ready index",
        responsibility="Indexes requirements, generated testcases, framework inventory, DOM crawl outputs, and reusable component metadata for retrieval.",
        primary_outputs="retrieval context package, source lineage, similarity-ready metadata",
        implementation_files=["qa_pipeline/agents/phase2_source_intake_rag/rag_knowledge_agent.py", "qa_pipeline/rag/lightweight_index.py"],
        gui_actions=["Generated Playwright -> inventory and reuse context"],
        status="available",
    ),
    AgentDefinition(
        phase="Phase 2",
        module="Test Design",
        agent_id="test-design-agent",
        display_name="Test Design Agent",
        llm_mode="Codex CLI / Ollama / rules",
        responsibility="Creates coverage-oriented test scenarios before code generation, including positive, negative, responsive, accessibility, and navigation cases.",
        primary_outputs="TestScenario, coverage map, risk tags",
        implementation_files=["qa_pipeline/agents/phase2_source_intake_rag/test_design_agent.py"],
        gui_actions=["Functional Testcases -> scenario review"],
        status="available",
    ),
    AgentDefinition(
        phase="Phase 3",
        module="Framework Analyzer",
        agent_id="framework-analyzer-agent",
        display_name="Framework Analyzer Agent",
        llm_mode="Static analyzer + optional Codex context",
        responsibility="Scans generated-playwright for existing POMs, locators, methods, fixtures, utilities, test data, and conventions.",
        primary_outputs="framework_profile, reusable component inventory",
        implementation_files=["qa_pipeline/agents/phase3_reuse_aware_codegen/framework_analyzer.py", "qa_pipeline/rag/framework_inventory.py"],
        gui_actions=["Generated Playwright -> Generate Reusable Playwright"],
        status="available",
    ),
    AgentDefinition(
        phase="Phase 3",
        module="POM and Locator Generation",
        agent_id="pom-locator-agent",
        display_name="POM and Locator Agent",
        llm_mode="Codex CLI + deterministic reuse rules",
        responsibility="Creates or updates pageObjects and page classes only when reusable locators/methods do not already exist.",
        primary_outputs="pageObjects/*.objects.ts, pages/*.ts, locator stability metadata",
        implementation_files=["qa_pipeline/agents/phase3_reuse_aware_codegen/pom_locator_agent.py", "qa_pipeline/agents/phase3_reuse_aware_codegen/locator_strategy.py"],
        gui_actions=["Generated Playwright -> Generate Reusable Playwright"],
        status="available",
    ),
    AgentDefinition(
        phase="Phase 3",
        module="Test Code Generation",
        agent_id="test-generator-agent",
        display_name="Test Generator Agent",
        llm_mode="Codex CLI / Ollama assisted + deterministic guardrail",
        responsibility="Generates TypeScript Playwright specs that call page methods and never duplicate raw locators in specs.",
        primary_outputs="tests/generated/*.spec.ts, generation metadata, reuse decision report",
        implementation_files=["qa_pipeline/agents/phase3_reuse_aware_codegen/reuse_generator.py", "qa_pipeline/agents/phase3_reuse_aware_codegen/codex_prompt.py"],
        gui_actions=["Generated Playwright -> Generate Reusable Playwright"],
        status="available",
    ),
    AgentDefinition(
        phase="Phase 3",
        module="Dynamic Web Crawl and DOM Mapping",
        agent_id="dynamic-web-crawler-agent",
        display_name="Dynamic Web Crawler Agent",
        llm_mode="No LLM + Playwright browser crawl",
        responsibility="Crawls the live user-provided URL, scrolls full page, captures DOM, links, text, headings, buttons, images, screenshot, and dynamic page context.",
        primary_outputs="dynamic-dom-map.json, full-page screenshot, crawl metadata",
        implementation_files=["qa_pipeline/agents/phase3_reuse_aware_codegen/dynamic_crawler.py", "generated-playwright/scripts/crawlDynamicPage.ts"],
        gui_actions=["Generated Playwright -> Generate Reusable Playwright"],
        status="available",
    ),
    AgentDefinition(
        phase="Phase 3",
        module="API Test Generation",
        agent_id="api-test-generator-agent",
        display_name="API Test Generator Agent",
        llm_mode="Codex CLI / rules",
        responsibility="Reserved for OpenAPI/Swagger-driven Playwright API tests and contract coverage.",
        primary_outputs="API spec tests, contract test result placeholder",
        implementation_files=["qa_pipeline/agents/phase3_reuse_aware_codegen/api_test_generator.py"],
        gui_actions=["Agents & Phases -> status", "future OpenAPI input"],
        status="planned/stubbed",
        notes="Stub included so the planned architecture is visible without impacting current UI flow.",
    ),
    AgentDefinition(
        phase="Phase 4",
        module="Review and PR Automation",
        agent_id="code-review-agent",
        display_name="Code Review Agent",
        llm_mode="Deterministic tools + optional Codex notes",
        responsibility="Runs static review: folder structure, no inline locators, TypeScript build when enabled, quality-review artifacts.",
        primary_outputs="review_result, quality-review.json, block/warn messages",
        implementation_files=["qa_pipeline/agents/phase4_review_execution/reviewer.py"],
        gui_actions=["Generated Playwright -> Static Review"],
        status="available",
    ),
    AgentDefinition(
        phase="Phase 4",
        module="Review and PR Automation",
        agent_id="pr-automation-agent",
        display_name="PR Automation Agent",
        llm_mode="No LLM / Git CLI-ready",
        responsibility="Prepares branch/PR metadata and future GitHub PR flow after generated tests pass quality gates.",
        primary_outputs="PR-ready metadata, changed file list, reviewer hints",
        implementation_files=["qa_pipeline/agents/phase4_review_execution/pr_automation.py", "scripts/create_git_branches.sh"],
        gui_actions=["Agents & Phases -> status", "future PR action"],
        status="planned/stubbed",
        notes="Stub included; no auto-push is triggered from GUI to avoid unsafe changes.",
    ),
    AgentDefinition(
        phase="Phase 4",
        module="Execution",
        agent_id="execution-agent",
        display_name="Execution Agent",
        llm_mode="No LLM",
        responsibility="Runs Playwright tests headless or headed, applies BASE_URL, stores JSON/HTML/screenshot/video/trace artifacts.",
        primary_outputs="execution_run, test_result, trace/video/screenshot artifacts",
        implementation_files=["qa_pipeline/agents/phase4_review_execution/executor.py", "generated-playwright/playwright.config.ts"],
        gui_actions=["Generated Playwright -> Execute Generated Test - Headless/Headed"],
        status="available",
    ),
    AgentDefinition(
        phase="Phase 4",
        module="Existing Framework Control",
        agent_id="existing-playwright-framework-controller",
        display_name="Existing Playwright Framework Control Agent",
        llm_mode="Static analyzer + Codex CLI self-healing",
        responsibility="Understands and executes a user-provided existing Playwright TypeScript framework in-place, bypassing requirement/testcase/codegen phases, then scopes RCA/self-healing to failed specs only.",
        primary_outputs="framework-intelligence.json, existing execution report, existing failed-tests inventory, existing RCA/self-healing reports, consolidated failed-only rerun report",
        implementation_files=["qa_pipeline/agents/existing_framework_control/controller.py", "qa_pipeline/gui/app.py"],
        gui_actions=["Existing Framework Control -> Understand Framework", "Execute Existing", "Analyze Existing RCA", "Apply Existing Patch", "Re-run Existing Failed Only"],
        status="available",
        notes="This extension is additive and does not disturb the existing Jira/SRS/testcase-generation pipeline.",
    ),
    AgentDefinition(
        phase="Phase 4",
        module="Execution",
        agent_id="distributed-execution-agent",
        display_name="Distributed Execution Agent",
        llm_mode="No LLM",
        responsibility="Runs generated Playwright tests using local shard workers now, with the same commands ready to move to CI runners/containers for true distributed execution.",
        primary_outputs="distributed-execution-report.json, shard stdout/stderr, pass/fail summary",
        implementation_files=["qa_pipeline/agents/phase4_review_execution/executor.py", "generated-playwright/playwright.config.ts"],
        gui_actions=["Enterprise Stack -> Execute distributed/headless", "Enterprise Stack -> Execute distributed/headed"],
        status="available",
    ),
    AgentDefinition(
        phase="Phase 4",
        module="Playwright MCP Integration",
        agent_id="playwright-mcp-agent",
        display_name="Playwright MCP Agent",
        llm_mode="MCP/browser-assist integration",
        responsibility="Writes/checks Microsoft Playwright MCP configuration for AI-assisted browser inspection while Playwright Test remains the deterministic execution runner.",
        primary_outputs="mcp status, config files, readiness result",
        implementation_files=["qa_pipeline/mcp/playwright_mcp.py", "mcp/playwright-mcp.json", ".vscode/mcp.json"],
        gui_actions=["Playwright MCP -> Check Playwright MCP"],
        status="available",
    ),
    AgentDefinition(
        phase="Phase 5",
        module="Failure Intelligence",
        agent_id="failure-analysis-agent",
        display_name="Failure Analysis Agent",
        llm_mode="Rules + Codex/Ollama RCA support",
        responsibility="Classifies execution failures into wrong URL, locator issue, clickability/viewport, sync/navigation, browser permission, environment, data, flaky, or app-behavior categories.",
        primary_outputs="FailureClassification, confidence, retry/heal route",
        implementation_files=["qa_pipeline/agents/phase5_failure_healing/failure_classifier.py", "qa_pipeline/agents/phase5_failure_healing/root_cause_agent.py"],
        gui_actions=["RCA & Self-Healing -> Analyze Root Cause", "Reports -> RCA"],
        status="available",
    ),
    AgentDefinition(
        phase="Phase 5",
        module="Self-Healing and RCA",
        agent_id="self-healing-agent",
        display_name="Self-Healing Agent",
        llm_mode="Rules + Codex/Ollama patch guidance + strict validation",
        responsibility="Creates guarded self-healing proposals and can apply safe patches for wrong URLs, reusable locator fallback support, BasePage resilience, scrolling/clickability, and browser permission issues.",
        primary_outputs="self-healing report, patch backups, validation result, rerun suggestion",
        implementation_files=["qa_pipeline/agents/phase5_failure_healing/self_healing_agent.py"],
        gui_actions=["RCA & Self-Healing -> Propose Self-Healing Fix", "RCA & Self-Healing -> Apply Self-Healing Patch", "Reports -> Self-Healing"],
        status="available",
        notes="Auto-patching is guarded: backup first, pageObjects/pages/utils only, no raw locator in generated specs, static validation after patch.",
    ),
    AgentDefinition(
        phase="Phase 5",
        module="Self-Healing and RCA",
        agent_id="root-cause-agent",
        display_name="Root Cause Agent",
        llm_mode="Rules + Codex/Ollama narrative",
        responsibility="Reads Playwright results, MCP execution logs, screenshots/videos/traces metadata, dynamic DOM crawl, and framework files to identify why tests failed.",
        primary_outputs="root-cause-report.json, root-cause-report.md, likely root cause, fix plan, confidence",
        implementation_files=["qa_pipeline/agents/phase5_failure_healing/root_cause_agent.py"],
        gui_actions=["RCA & Self-Healing -> Analyze Root Cause", "Reports -> RCA"],
        status="available",
    ),
    AgentDefinition(
        phase="Phase 6",
        module="Reporting and Visibility",
        agent_id="reporting-agent",
        display_name="Reporting Agent",
        llm_mode="Templates + optional AI narrative",
        responsibility="Builds enterprise HTML reports with testcase, generation, static review, execution, artifact, self-heal, and traceability sections.",
        primary_outputs="enterprise-report.html, summary markdown, links to native Playwright report",
        implementation_files=["qa_pipeline/agents/phase6_reporting_governance/reporter.py"],
        gui_actions=["Reports -> Refresh enterprise HTML report"],
        status="available",
    ),
    AgentDefinition(
        phase="Phase 6",
        module="Drift and Maintenance",
        agent_id="drift-maintenance-agent",
        display_name="Drift and Maintenance Agent",
        llm_mode="Rules + optional AI",
        responsibility="Detects stale requirements, broken URLs, unstable locators, dependency updates, and drift between source docs and generated tests.",
        primary_outputs="drift event, maintenance recommendation, audit note",
        implementation_files=["qa_pipeline/agents/phase6_reporting_governance/drift_maintenance_agent.py"],
        gui_actions=["Agents & Phases -> status", "future scheduled checks"],
        status="planned/stubbed",
    ),
    AgentDefinition(
        phase="Phase 6",
        module="Model Validation and Governance",
        agent_id="model-validation-agent",
        display_name="Model Validation Agent",
        llm_mode="No LLM + evaluators",
        responsibility="Tracks model validation matrix rows, benchmark outcomes, thresholds, and release recommendations before prompt/model changes.",
        primary_outputs="evaluation_run, scorecard, release recommendation",
        implementation_files=["qa_pipeline/agents/phase6_reporting_governance/model_validation_agent.py"],
        gui_actions=["Agents & Phases -> model validation matrix"],
        status="available/stubbed",
    ),
    AgentDefinition(
        phase="Phase 6",
        module="Security and Governance",
        agent_id="security-governance-agent",
        display_name="Security / Governance Agent",
        llm_mode="No LLM + policy checks",
        responsibility="Documents and checks guardrails: no secrets in prompts, sandboxed code generation, auditability, and human approval thresholds.",
        primary_outputs="governance checklist, policy status, audit hints",
        implementation_files=["qa_pipeline/agents/phase6_reporting_governance/governance_agent.py"],
        gui_actions=["Agents & Phases -> governance checks"],
        status="available/stubbed",
    ),
]


def get_agent_registry() -> list[dict[str, Any]]:
    return [agent.to_dict() for agent in AGENT_DEFINITIONS]


def get_phase_summary() -> dict[str, Any]:
    registry = get_agent_registry()
    summary: dict[str, Any] = {}
    for item in registry:
        phase = item["phase"]
        phase_item = summary.setdefault(phase, {"total": 0, "covered": 0, "partial_or_stubbed": 0, "agents": []})
        phase_item["total"] += 1
        phase_item["agents"].append(item["display_name"])
        if item["coverage_status"] == "covered" and "stub" not in item["status"]:
            phase_item["covered"] += 1
        else:
            phase_item["partial_or_stubbed"] += 1
    return summary


def get_missing_agent_items() -> list[dict[str, Any]]:
    return [agent for agent in get_agent_registry() if agent["missing_files"] or "stub" in agent["status"]]


def get_agent_coverage_report() -> dict[str, Any]:
    registry = get_agent_registry()
    return {
        "ok": True,
        "total_agents": len(registry),
        "available_agents": len([a for a in registry if a["coverage_status"] == "covered"]),
        "partial_or_stubbed_agents": len([a for a in registry if a["coverage_status"] != "covered" or "stub" in a["status"]]),
        "phase_summary": get_phase_summary(),
        "agents": registry,
        "missing_or_stubbed": get_missing_agent_items(),
        "important_note": "Stubbed/planned agents are registered and visible in GUI without changing existing working pipeline behavior. Production automation can be enabled phase-wise later.",
    }
