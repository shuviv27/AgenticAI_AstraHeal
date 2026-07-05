from __future__ import annotations

import os
from typing import Any

from qa_pipeline.core.commands import resolve_command, run_command
from qa_pipeline.core.paths import REPO_ROOT


MANDATORY_ENTERPRISE_STACK = [
    {"name": "Redis", "url": "redis://localhost:6379", "purpose": "Event bus, Redis Streams, job status, GUI progress and idempotency locks."},
    {"name": "PostgreSQL", "url": "localhost:5432", "purpose": "Durable run/testcase/execution/RCA/self-healing/audit metadata."},
    {"name": "Qdrant", "url": "http://localhost:6333", "purpose": "Primary vector store for framework and failure memory."},
    {"name": "ChromaDB", "url": "http://localhost:8000", "purpose": "Blueprint-compatible vector store for scenarios and semantic dedup."},
    {"name": "MinIO", "url": "http://localhost:9001", "purpose": "S3-compatible artifact storage for files, screenshots, traces, videos, reports and backups."},
    {"name": "Prometheus", "url": "http://localhost:9090", "purpose": "Metrics collection for services, agents, execution shards and quality gates."},
    {"name": "Grafana", "url": "http://localhost:3001", "purpose": "Dashboards for pass rate, failure rate, flakiness, agent health and enterprise KPIs."},
    {"name": "Langfuse", "url": "http://localhost:3002", "purpose": "LLM prompt/response tracing, model/cost tracking and RCA/self-healing explainability."},
    {"name": "LangSmith Bridge", "url": "http://localhost:3003", "purpose": "Local readiness service for mandatory hosted LangSmith evaluation/tracing configuration."},
    {"name": "Jira MCP", "url": "http://localhost:8812", "purpose": "Jira/Confluence MCP bridge for epic/story/testcase ingestion."},
    {"name": "GitHub MCP", "url": "http://localhost:8811", "purpose": "GitHub MCP bridge for branch, PR and review automation."},
    {"name": "Playwright MCP", "url": "http://localhost:8931", "purpose": "Microsoft Playwright MCP-compatible browser assist for VS Code and AI exploration."},
    {"name": "Ollama", "url": "http://localhost:11434", "purpose": "Local LLM fallback for private/offline generation and RCA assistance."},
    {"name": "OWASP ZAP", "url": "http://localhost:8090", "purpose": "Security passive scan tool for enterprise quality gates."},
]


def _env_bool(*keys: str) -> bool:
    return any(bool(os.getenv(k)) for k in keys)


def enterprise_stack_status() -> dict[str, Any]:
    compose = REPO_ROOT / "infra" / "docker" / "docker-compose.yml"
    docker = resolve_command("docker")
    env = {
        "JIRA_URL": _env_bool("JIRA_URL", "JIRA_BASE_URL"),
        "JIRA_USERNAME/JIRA_EMAIL": _env_bool("JIRA_USERNAME", "JIRA_EMAIL"),
        "JIRA_API_TOKEN": _env_bool("JIRA_API_TOKEN"),
        "GITHUB_TOKEN": _env_bool("GITHUB_TOKEN"),
        "LANGFUSE_PUBLIC_KEY": _env_bool("LANGFUSE_PUBLIC_KEY"),
        "LANGFUSE_SECRET_KEY": _env_bool("LANGFUSE_SECRET_KEY"),
        "LANGCHAIN_API_KEY": _env_bool("LANGCHAIN_API_KEY"),
        "OPENAI/CODEX": bool(resolve_command("codex")),
    }
    status: dict[str, Any] = {
        "ok": bool(docker and compose.exists()),
        "enterprise_mode": "mandatory-stack",
        "compose_file": str(compose.relative_to(REPO_ROOT)) if compose.exists() else str(compose),
        "services": MANDATORY_ENTERPRISE_STACK,
        "env_ready": env,
        "start_command": "docker compose -f infra/docker/docker-compose.yml up -d",
        "gui_command": "START_GUI_WINDOWS.cmd or START_GUI_MAC.sh after stack is healthy",
        "note": "In this build Redis/Postgres/Qdrant/ChromaDB/MinIO/Grafana/Prometheus/Langfuse/MCP/ZAP/Ollama are treated as the mandatory enterprise stack, not optional profiles.",
    }
    if docker and compose.exists():
        ps = run_command(["docker", "compose", "-f", str(compose), "ps"], cwd=REPO_ROOT, timeout=40)
        status.update({"ps_ok": ps.ok, "ps_stdout": ps.stdout[-10000:], "ps_stderr": ps.stderr[-4000:], "ps_error": ps.error})
    elif not docker:
        status["error"] = "Docker command not found."
    else:
        status["error"] = "docker-compose.yml not found."
    return status


def langsmith_status() -> dict[str, Any]:
    return {
        "required_in_enterprise_mode": True,
        "enabled": os.getenv("LANGCHAIN_TRACING_V2", "true").lower() == "true",
        "api_key_configured": bool(os.getenv("LANGCHAIN_API_KEY")),
        "project": os.getenv("LANGCHAIN_PROJECT", "ai-qa-pipeline"),
        "endpoint": os.getenv("LANGCHAIN_ENDPOINT", "https://api.smith.langchain.com"),
        "local_bridge": "http://localhost:3003",
        "note": "LangSmith is hosted; the Docker stack includes a local bridge/readiness service and the Python project includes langsmith dependencies.",
    }
