from __future__ import annotations

import os
import platform
import shlex
from pathlib import Path
from typing import Any

from qa_pipeline.core.commands import resolve_command, run_command
from qa_pipeline.core.docker_stack import COMPOSE_FILE, docker_available, docker_compose_cmd, docker_status
from qa_pipeline.core.paths import REPO_ROOT

# Keep API automation runtimes Docker-managed so host machines do not need Java/Maven/Node/Playwright.
API_PLAYWRIGHT_IMAGE = os.environ.get("AIQA_API_PLAYWRIGHT_IMAGE", "mcr.microsoft.com/playwright:v1.50.0-noble")
API_RESTASSURED_IMAGE = os.environ.get("AIQA_API_RESTASSURED_IMAGE", "maven:3.9-eclipse-temurin-21")
API_NEWMAN_IMAGE = os.environ.get("AIQA_API_NEWMAN_IMAGE", "postman/newman:alpine")
API_WIREMOCK_IMAGE = os.environ.get("AIQA_API_WIREMOCK_IMAGE", "wiremock/wiremock:latest")
API_MOCKSERVER_IMAGE = os.environ.get("AIQA_API_MOCKSERVER_IMAGE", "mockserver/mockserver:latest")

API_RUNTIME_IMAGES = {
    "api-playwright-runner": API_PLAYWRIGHT_IMAGE,
    "api-restassured-runner": API_RESTASSURED_IMAGE,
    "api-newman-runner": API_NEWMAN_IMAGE,
    "wiremock": API_WIREMOCK_IMAGE,
    "mockserver": API_MOCKSERVER_IMAGE,
}

API_TOOL_SERVICES = ["wiremock", "mockserver"]


def _quote(v: str) -> str:
    return shlex.quote(str(v))


def _docker_image_present(image: str) -> bool:
    proc = run_command(["docker", "image", "inspect", image], cwd=REPO_ROOT, timeout=30)
    return proc.ok


def _host_runtime(command: str, args: list[str] | None = None, timeout: int = 20) -> dict[str, Any]:
    exe = resolve_command(command)
    if not exe:
        return {"available": False, "command": command, "message": f"{command} not found on host; Docker runtime can be used instead."}
    proc = run_command([exe, *(args or ["--version"])], cwd=REPO_ROOT, timeout=timeout)
    return {
        "available": True,
        "command": proc.command,
        "ok": proc.ok,
        "stdout": proc.stdout[-1000:],
        "stderr": proc.stderr[-1000:],
        "message": (proc.stdout or proc.stderr or "available")[-500:],
    }


def api_docker_runtime_status() -> dict[str, Any]:
    """Report API automation prerequisites with Docker-first guidance."""
    status: dict[str, Any] = {
        "ok": False,
        "purpose": "Docker-managed API automation runtime for Playwright API TS/JS and Rest Assured Java frameworks.",
        "host_os": platform.platform(),
        "docker_required": True,
        "host_tools_optional": True,
        "recommended_mode": "docker",
        "api_runtime_images": API_RUNTIME_IMAGES,
        "api_tool_services": API_TOOL_SERVICES,
        "ports": {"wiremock": "8089", "mockserver": "1080"},
        "environment_variables": [
            "API_BASE_URL", "API_AUTH_TOKEN", "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY",
            "MAVEN_OPTS", "JAVA_TOOL_OPTIONS", "NPM_CONFIG_REGISTRY",
        ],
        "notes": [
            "Java 17/21, Maven and Node are no longer mandatory on the host when Docker runtime is used.",
            "For office VPN/VDI apps, ensure Docker containers can route to the same network. Use host.docker.internal for services running on the laptop.",
            "Corporate proxies can be passed through HTTP_PROXY/HTTPS_PROXY/NO_PROXY environment variables.",
            "Maven cache is persisted in Docker volume aiqa_maven_cache to avoid repeated downloads.",
        ],
    }
    if not docker_available():
        status.update({"ok": False, "docker_available": False, "error": "Docker CLI not found. Install/start Docker Desktop, then reopen GUI."})
        return status
    ds = docker_status()
    status["docker"] = ds
    status["docker_available"] = bool(ds.get("docker_available"))
    status["docker_desktop_running"] = bool(ds.get("docker_desktop_running"))
    image_rows = []
    all_present = True
    if status["docker_desktop_running"]:
        for name, image in API_RUNTIME_IMAGES.items():
            present = _docker_image_present(image)
            all_present = all_present and present
            image_rows.append({"name": name, "image": image, "present": present})
    else:
        all_present = False
        for name, image in API_RUNTIME_IMAGES.items():
            image_rows.append({"name": name, "image": image, "present": False})
    status["image_rows"] = image_rows
    status["images_ready"] = all_present
    status["host_runtime"] = {
        "java": _host_runtime("java", ["-version"]),
        "maven": _host_runtime("mvn", ["-version"]),
        "node": _host_runtime("node", ["--version"]),
        "npm": _host_runtime("npm", ["--version"]),
    }
    status["ok"] = bool(status.get("docker_available") and status.get("docker_desktop_running"))
    status["message"] = "API Docker runtime is reachable." if status["ok"] else "Start Docker Desktop and refresh API Docker readiness."
    return status


def api_docker_pull_images() -> dict[str, Any]:
    if not docker_available():
        return api_docker_runtime_status()
    pulls = []
    for name, image in API_RUNTIME_IMAGES.items():
        proc = run_command(["docker", "pull", image], cwd=REPO_ROOT, timeout=1800)
        pulls.append({
            "name": name,
            "image": image,
            "ok": proc.ok,
            "command": proc.command,
            "stdout": proc.stdout[-4000:],
            "stderr": proc.stderr[-4000:],
            "error": proc.error,
        })
    status = api_docker_runtime_status()
    status.update({"stage": "api_docker_pull_images", "pulls": pulls, "ok": all(p.get("ok") for p in pulls), "message": "API Docker runtime images pulled/refreshed."})
    return status


def api_docker_start_tools() -> dict[str, Any]:
    """Start optional API mock/contract helper services via docker compose profile api-tools."""
    if not docker_available():
        return api_docker_runtime_status()
    proc = run_command(docker_compose_cmd("--profile", "api-tools", "up", "-d", *API_TOOL_SERVICES), cwd=REPO_ROOT, timeout=900)
    status = api_docker_runtime_status()
    status.update({
        "stage": "api_docker_start_tools",
        "ok": proc.ok,
        "command": proc.command,
        "stdout": proc.stdout[-6000:],
        "stderr": proc.stderr[-6000:],
        "error": proc.error,
        "message": "API helper services started. WireMock: http://127.0.0.1:8089, MockServer: http://127.0.0.1:1080" if proc.ok else "API helper services could not be started.",
    })
    return status


def _docker_env_args(extra_env: dict[str, str] | None = None) -> list[str]:
    env_names = [
        "API_BASE_URL", "API_AUTH_TOKEN", "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY",
        "http_proxy", "https_proxy", "no_proxy", "NPM_CONFIG_REGISTRY", "MAVEN_OPTS", "JAVA_TOOL_OPTIONS",
    ]
    args: list[str] = []
    merged = {k: v for k, v in os.environ.items() if k in env_names and v}
    merged.update({k: v for k, v in (extra_env or {}).items() if v})
    for k, v in merged.items():
        args.extend(["-e", f"{k}={v}"])
    return args


def _docker_volume_path(path: Path) -> str:
    # Docker Desktop on Windows accepts absolute Windows paths passed by Python as a single -v argument.
    return str(path.resolve())


def docker_api_command(framework_path: Path, flavor: str, base_url: str = "", targets: str = "", test_command: str = "") -> list[str]:
    root = framework_path.resolve()
    env_args = _docker_env_args({"API_BASE_URL": base_url})
    common = ["docker", "run", "--rm", "-t", *env_args, "-v", f"{_docker_volume_path(root)}:/workspace", "-w", "/workspace"]
    if flavor == "restassured":
        cmd = (test_command or "mvn -B -ntp test").strip()
        if targets and not test_command:
            cmd = f"mvn -B -ntp test {targets.strip()}"
        return [*common, "-v", "aiqa_maven_cache:/root/.m2", API_RESTASSURED_IMAGE, "bash", "-lc", cmd]
    # Playwright API TS/JS. API tests do not need headed browsers, but this image keeps the runtime enterprise-consistent.
    target_arg = " ".join([x.strip() for x in str(targets or "").replace(",", "\n").splitlines() if x.strip()])
    cmd = test_command.strip() if test_command else ""
    if not cmd:
        config = "-c playwright.api.config.ts" if (root / "playwright.api.config.ts").exists() else ""
        cmd = f"if [ ! -d node_modules ]; then npm install; fi; npx playwright test {config} {target_arg}".strip()
    return [*common, API_PLAYWRIGHT_IMAGE, "bash", "-lc", cmd]


def execute_api_framework_in_docker(framework_path: str, flavor: str, base_url: str = "", targets: str = "", test_command: str = "", timeout: int = 1200) -> dict[str, Any]:
    root = Path(framework_path).expanduser().resolve()
    if not root.exists():
        return {"ok": False, "error": f"API framework path does not exist: {root}"}
    if not docker_available():
        return {"ok": False, "error": "Docker CLI not found. Install/start Docker Desktop or run API tests locally."}
    status = api_docker_runtime_status()
    if not status.get("docker_desktop_running"):
        return {"ok": False, "error": "Docker Desktop is not running or Docker engine is not reachable.", "docker_status": status}
    cmd = docker_api_command(root, flavor=flavor, base_url=base_url, targets=targets, test_command=test_command)
    proc = run_command(cmd, cwd=REPO_ROOT, timeout=timeout)
    return {
        "ok": proc.ok,
        "cmd": proc.command,
        "cwd": str(REPO_ROOT),
        "returncode": proc.returncode,
        "stdout": proc.stdout[-12000:],
        "stderr": proc.stderr[-12000:],
        "error": proc.error,
        "duration_sec": None,
        "docker_runtime": True,
        "image": API_RESTASSURED_IMAGE if flavor == "restassured" else API_PLAYWRIGHT_IMAGE,
    }
