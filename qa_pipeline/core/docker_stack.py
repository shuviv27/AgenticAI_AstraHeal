from __future__ import annotations

import json
import time
from typing import Any

from qa_pipeline.core.commands import resolve_command, run_command
from qa_pipeline.core.paths import REPO_ROOT

COMPOSE_FILE = REPO_ROOT / "infra" / "docker" / "docker-compose.yml"
MANDATORY_SERVICES = [
    "redis", "postgres", "qdrant", "chromadb", "minio",
    "prometheus", "grafana", "langfuse-db", "langfuse", "langsmith-bridge",
    "github-mcp", "jira-mcp", "playwright-mcp", "ollama", "zap",
]
APP_SERVICES = ["pipeline-gui"]
MANUAL_TOOL_SERVICES = ["k6-runner", "wiremock", "mockserver", "api-playwright-runner", "api-restassured-runner", "api-newman-runner"]

SERVICE_PURPOSE = {
    "redis": "Agent bus, job/progress state, stream replay and idempotency locks.",
    "postgres": "Pipeline metadata, testcase records, execution history, RCA/self-heal audit trail.",
    "qdrant": "Vector/RAG store for framework inventory, DOM maps and historical failure memory.",
    "chromadb": "Additional vector/RAG test registry and semantic testcase retrieval.",
    "minio": "S3-compatible artifact storage for uploads, reports, screenshots, videos and traces.",
    "prometheus": "Metrics collection for agents, shards and platform health.",
    "grafana": "Enterprise dashboards for pass rate, flakiness, coverage and stack health.",
    "langfuse-db": "Database used by Langfuse.",
    "langfuse": "LLM prompt, trace and cost observability.",
    "langsmith-bridge": "Local readiness bridge for hosted LangSmith tracing configuration.",
    "github-mcp": "GitHub MCP bridge for PR/repo automation.",
    "jira-mcp": "Jira/Confluence MCP bridge for issue and epic workflows.",
    "playwright-mcp": "Microsoft Playwright MCP-compatible browser-assist server for VS Code/agents.",
    "ollama": "Local open-source model runtime fallback.",
    "zap": "OWASP ZAP security scan service.",
    "wiremock": "Optional API mock server for deterministic API tests and contract replay.",
    "mockserver": "Optional API mock/contract server for controlled backend behavior.",
    "api-playwright-runner": "Optional Docker runtime for Playwright API TS/JS execution.",
    "api-restassured-runner": "Optional Docker runtime for Rest Assured Java/Maven execution.",
    "api-newman-runner": "Optional Docker runtime for Postman/Newman API collections.",
}


def docker_available() -> bool:
    return resolve_command("docker") is not None


def docker_compose_cmd(*args: str) -> list[str]:
    return ["docker", "compose", "-f", str(COMPOSE_FILE), *args]


def _docker_info() -> dict[str, Any]:
    if not docker_available():
        return {"ok": False, "error": "Docker command not found. Install Docker Desktop and reopen the terminal."}
    proc = run_command(["docker", "info"], cwd=REPO_ROOT, timeout=30)
    if proc.ok:
        return {"ok": True, "stdout": proc.stdout[-3000:]}
    return {
        "ok": False,
        "stdout": proc.stdout[-3000:],
        "stderr": proc.stderr[-3000:],
        "error": proc.error or "Docker Desktop is not running or Docker engine is not reachable.",
    }


def _compose_config() -> dict[str, Any]:
    if not COMPOSE_FILE.exists():
        return {"ok": False, "error": f"Compose file not found: {COMPOSE_FILE}"}
    proc = run_command(docker_compose_cmd("config"), cwd=REPO_ROOT, timeout=60)
    return {"ok": proc.ok, "command": proc.command, "stdout": proc.stdout[-4000:], "stderr": proc.stderr[-4000:], "error": proc.error}


def _parse_ps_json(text: str) -> list[dict[str, Any]]:
    text = (text or "").strip()
    if not text:
        return []
    try:
        data = json.loads(text)
        if isinstance(data, list):
            return [x for x in data if isinstance(x, dict)]
        if isinstance(data, dict):
            return [data]
    except Exception:
        pass
    items: list[dict[str, Any]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            if isinstance(obj, dict):
                items.append(obj)
        except Exception:
            continue
    return items


def _compose_ps() -> dict[str, Any]:
    proc_json = run_command(docker_compose_cmd("ps", "--all", "--format", "json"), cwd=REPO_ROOT, timeout=45)
    services: list[dict[str, Any]] = []
    if proc_json.ok:
        services = _parse_ps_json(proc_json.stdout)
    if not services:
        proc = run_command(docker_compose_cmd("ps"), cwd=REPO_ROOT, timeout=45)
        return {"ok": proc.ok, "command": proc.command, "stdout": proc.stdout[-10000:], "stderr": proc.stderr[-4000:], "error": proc.error, "services": []}
    return {"ok": True, "command": proc_json.command, "stdout": proc_json.stdout[-10000:], "stderr": proc_json.stderr[-4000:], "error": proc_json.error, "services": services}


def _service_name(item: dict[str, Any]) -> str:
    return str(item.get("Service") or item.get("Name") or item.get("Names") or item.get("service") or "")


def _service_state(item: dict[str, Any]) -> str:
    return str(item.get("State") or item.get("Status") or item.get("state") or item.get("status") or "")


def _service_health(item: dict[str, Any]) -> str:
    return str(item.get("Health") or item.get("health") or "")


def _evaluate_services(services: list[dict[str, Any]]) -> dict[str, Any]:
    by_service: dict[str, dict[str, Any]] = {}
    for item in services:
        name = _service_name(item)
        if name:
            by_service[name] = item
    service_rows: list[dict[str, Any]] = []
    missing: list[str] = []
    not_ready: list[str] = []
    for svc in MANDATORY_SERVICES:
        item = by_service.get(svc)
        if not item:
            missing.append(svc)
            service_rows.append({"service": svc, "ready": False, "state": "missing", "health": "", "purpose": SERVICE_PURPOSE.get(svc, "")})
            continue
        state = _service_state(item).lower()
        health = _service_health(item).lower()
        running = ("running" in state or state == "running")
        # Some public/bridge images do not define meaningful health checks. Running is acceptable
        # for bridge/readiness services and ZAP; real credential/API checks happen in dedicated GUI tabs.
        health_ok = health in ("", "healthy") or "healthy" in health
        health_tolerant_services = {"langsmith-bridge", "github-mcp", "jira-mcp", "playwright-mcp", "ollama", "zap", "grafana", "prometheus", "langfuse"}
        ready = running and (health_ok or svc in health_tolerant_services)
        if not ready:
            not_ready.append(svc)
        service_rows.append({"service": svc, "ready": ready, "state": _service_state(item), "health": _service_health(item), "purpose": SERVICE_PURPOSE.get(svc, "")})
    return {
        "enterprise_ready": not missing and not not_ready,
        "missing_services": missing,
        "not_ready_services": not_ready,
        "service_rows": service_rows,
        "ready_count": sum(1 for r in service_rows if r["ready"]),
        "total_count": len(MANDATORY_SERVICES),
    }


def docker_status() -> dict[str, Any]:
    docker = resolve_command("docker")
    status: dict[str, Any] = {
        "docker_available": bool(docker),
        "compose_file": str(COMPOSE_FILE.relative_to(REPO_ROOT)) if COMPOSE_FILE.exists() else str(COMPOSE_FILE),
        "compose_file_exists": COMPOSE_FILE.exists(),
        "mandatory_services": MANDATORY_SERVICES,
        "app_services": APP_SERVICES,
        "manual_tool_services": MANUAL_TOOL_SERVICES,
        "enterprise_mode": True,
        "service_purpose": SERVICE_PURPOSE,
        "gui_managed": True,
        "important_rule": "Start/validate the mandatory Docker platform from the GUI Enterprise Stack page. Docker Desktop must be running first.",
        "how_it_is_used": list(SERVICE_PURPOSE.values()),
    }
    if not docker:
        status.update({"ok": False, "enterprise_ready": False, "error": "Docker command not found. Install/start Docker Desktop, then reopen terminal."})
        return status
    version = run_command(["docker", "--version"], timeout=15)
    compose_version = run_command(["docker", "compose", "version"], timeout=20)
    status["docker_version"] = version.stdout.strip() or version.stderr.strip() or version.error
    status["docker_compose_version"] = compose_version.stdout.strip() or compose_version.stderr.strip() or compose_version.error
    info = _docker_info()
    status["docker_desktop_running"] = bool(info.get("ok"))
    status["docker_info"] = info
    if not info.get("ok"):
        status.update({"ok": False, "enterprise_ready": False, "error": info.get("error")})
        return status
    config = _compose_config()
    status["compose_config_ok"] = bool(config.get("ok"))
    if not config.get("ok"):
        status.update({"ok": False, "enterprise_ready": False, "compose_config": config, "error": config.get("error") or config.get("stderr")})
        return status
    ps = _compose_ps()
    status.update({
        "ok": bool(ps.get("ok")),
        "ps_command": ps.get("command"),
        "ps_stdout": ps.get("stdout", "")[-10000:],
        "ps_stderr": ps.get("stderr", "")[-4000:],
        "ps_error": ps.get("error"),
        "start_all_command": "docker compose -f infra/docker/docker-compose.yml up -d",
        "start_gui_container_command": "docker compose -f infra/docker/docker-compose.yml --profile app up -d --build pipeline-gui",
        "start_k6_tool_command": "docker compose -f infra/docker/docker-compose.yml --profile manual-tools run --rm k6-runner run /scripts/load-test.js",
    })
    evaluation = _evaluate_services(ps.get("services", []))
    status.update(evaluation)
    status["blocking"] = not status.get("enterprise_ready", False)
    return status


def docker_pull() -> dict[str, Any]:
    if not docker_available():
        return docker_status()
    info = _docker_info()
    if not info.get("ok"):
        return {"ok": False, "enterprise_ready": False, "stage": "docker_info", "error": info.get("error"), "docker_info": info}
    config = _compose_config()
    if not config.get("ok"):
        return {"ok": False, "enterprise_ready": False, "stage": "compose_config", "error": config.get("error") or config.get("stderr"), "compose_config": config}
    proc = run_command(docker_compose_cmd("pull", *MANDATORY_SERVICES), cwd=REPO_ROOT, timeout=1800)
    status = docker_status()
    status.update({"stage": "pull", "pull_ok": proc.ok, "pull_command": proc.command, "pull_stdout": proc.stdout[-12000:], "pull_stderr": proc.stderr[-12000:], "pull_error": proc.error})
    return status


def _wait_until_ready(timeout_seconds: int = 420, interval_seconds: int = 8) -> dict[str, Any]:
    end = time.time() + timeout_seconds
    latest = docker_status()
    while time.time() < end:
        latest = docker_status()
        if latest.get("enterprise_ready"):
            latest["wait_ok"] = True
            return latest
        time.sleep(interval_seconds)
    latest["wait_ok"] = False
    latest["error"] = latest.get("error") or f"Mandatory enterprise stack did not become ready within {timeout_seconds}s. Click Refresh, then Docker logs for not_ready_services. If a service is exited, click Stop stack and Start stack again."
    return latest


def docker_start(include_ollama: bool = True, include_gui: bool = False, include_observability: bool = True, include_mcp: bool = True) -> dict[str, Any]:
    """Start mandatory enterprise stack from GUI/backend.

    include_* parameters are accepted for backward compatibility with older GUI buttons.
    Enterprise mode starts all mandatory services regardless of those flags.
    """
    if not docker_available():
        return docker_status()
    info = _docker_info()
    if not info.get("ok"):
        status = docker_status()
        status.update({"start_ok": False, "stage": "docker_info", "error": info.get("error")})
        return status
    config = _compose_config()
    if not config.get("ok"):
        status = docker_status()
        status.update({"start_ok": False, "stage": "compose_config", "error": config.get("error") or config.get("stderr"), "compose_config": config})
        return status
    pull = run_command(docker_compose_cmd("pull", *MANDATORY_SERVICES), cwd=REPO_ROOT, timeout=1800)
    if not pull.ok:
        status = docker_status()
        status.update({"start_ok": False, "stage": "pull", "pull_ok": False, "pull_command": pull.command, "pull_stdout": pull.stdout[-12000:], "pull_stderr": pull.stderr[-12000:], "pull_error": pull.error})
        return status
    args = ["up", "-d", "--remove-orphans", *MANDATORY_SERVICES]
    if include_gui:
        args = ["--profile", "app", "up", "-d", "--build", "--remove-orphans", *MANDATORY_SERVICES, "pipeline-gui"]
    proc = run_command(docker_compose_cmd(*args), cwd=REPO_ROOT, timeout=1200)
    status = _wait_until_ready()
    status.update({
        "stage": "up_and_wait",
        "pull_ok": pull.ok,
        "pull_command": pull.command,
        "pull_stdout": pull.stdout[-12000:],
        "pull_stderr": pull.stderr[-12000:],
        "start_command": proc.command,
        "start_ok": proc.ok,
        "start_stdout": proc.stdout[-12000:],
        "start_stderr": proc.stderr[-12000:],
        "start_error": proc.error,
        "message": "Enterprise Docker stack started and validated." if status.get("enterprise_ready") else "Docker stack started but one or more mandatory services are not ready yet.",
    })
    return status


def docker_stop() -> dict[str, Any]:
    if not docker_available():
        return docker_status()
    proc = run_command(docker_compose_cmd("down"), cwd=REPO_ROOT, timeout=300)
    return {"ok": proc.ok, "enterprise_ready": False, "command": proc.command, "stdout": proc.stdout[-5000:], "stderr": proc.stderr[-5000:], "error": proc.error}


def docker_logs(service: str = "", tail: int = 120) -> dict[str, Any]:
    if not docker_available():
        return docker_status()
    args = ["logs", f"--tail={int(tail)}"]
    if service:
        args.append(service)
    proc = run_command(docker_compose_cmd(*args), cwd=REPO_ROOT, timeout=120)
    return {"ok": proc.ok, "command": proc.command, "stdout": proc.stdout[-12000:], "stderr": proc.stderr[-12000:], "error": proc.error}


def ollama_ensure_model(model: str = "llama3") -> dict[str, Any]:
    """Ensure Ollama container is running and the requested model is pulled."""
    model = (model or "llama3").strip()
    if not docker_available():
        return docker_status()
    info = _docker_info()
    if not info.get("ok"):
        return {"ok": False, "error": info.get("error"), "docker_info": info}
    up = run_command(docker_compose_cmd("up", "-d", "ollama"), cwd=REPO_ROOT, timeout=600)
    if not up.ok:
        return {"ok": False, "stage": "start_ollama", "command": up.command, "stdout": up.stdout[-8000:], "stderr": up.stderr[-8000:], "error": up.error}
    pull = run_command(docker_compose_cmd("exec", "-T", "ollama", "ollama", "pull", model), cwd=REPO_ROOT, timeout=1800)
    status = docker_status()
    status.update({
        "ok": pull.ok,
        "stage": "ollama_pull_model",
        "model": model,
        "command": pull.command,
        "stdout": pull.stdout[-12000:],
        "stderr": pull.stderr[-12000:],
        "error": pull.error,
        "message": f"Ollama model '{model}' is ready." if pull.ok else f"Ollama model '{model}' could not be pulled. Check Docker/Ollama logs.",
    })
    return status
