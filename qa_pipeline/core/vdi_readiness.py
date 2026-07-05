from __future__ import annotations

import json
import os
import platform
import shutil
import socket
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from qa_pipeline.core.paths import QA_CACHE_DIR, GENERATED_PLAYWRIGHT_DIR, REPO_ROOT
from qa_pipeline.core.runtime_logger import log_event

VDI_DIR = QA_CACHE_DIR / "vdi"
VDI_PROFILE = VDI_DIR / "vdi-runtime-profile.json"
VDI_READINESS_JSON = GENERATED_PLAYWRIGHT_DIR / "reports" / "vdi-readiness-report.json"
VDI_READINESS_MD = GENERATED_PLAYWRIGHT_DIR / "reports" / "vdi-readiness-report.md"
VDI_READINESS_HTML = GENERATED_PLAYWRIGHT_DIR / "reports" / "vdi-readiness-report.html"
VDI_CHECKLIST_MD = GENERATED_PLAYWRIGHT_DIR / "reports" / "client-vdi-preflight-checklist.md"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _run(cmd: list[str], timeout: int = 12) -> dict[str, Any]:
    try:
        cp = subprocess.run(cmd, cwd=str(REPO_ROOT), text=True, capture_output=True, timeout=timeout)
        return {"ok": cp.returncode == 0, "returncode": cp.returncode, "stdout": cp.stdout.strip()[-4000:], "stderr": cp.stderr.strip()[-4000:], "cmd": cmd}
    except FileNotFoundError:
        return {"ok": False, "returncode": 127, "stdout": "", "stderr": "command not found", "cmd": cmd}
    except subprocess.TimeoutExpired as exc:
        return {"ok": False, "returncode": 124, "stdout": (exc.stdout or "")[-4000:] if isinstance(exc.stdout, str) else "", "stderr": "timeout", "cmd": cmd}
    except Exception as exc:
        return {"ok": False, "returncode": 1, "stdout": "", "stderr": f"{type(exc).__name__}: {exc}", "cmd": cmd}


def _which_version(name: str, args: list[str] | None = None) -> dict[str, Any]:
    path = shutil.which(name)
    if not path:
        return {"available": False, "path": "", "version": ""}
    args = args or ["--version"]
    res = _run([name, *args], timeout=10)
    text = (res.get("stdout") or res.get("stderr") or "").splitlines()
    return {"available": True, "path": path, "version": text[0] if text else "available", "raw": res}


def _tcp_probe(host: str, port: int, timeout: float = 4.0) -> dict[str, Any]:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return {"ok": True, "host": host, "port": port, "message": "TCP reachable"}
    except Exception as exc:
        return {"ok": False, "host": host, "port": port, "message": f"{type(exc).__name__}: {exc}"}


def _http_probe(url: str, timeout: int = 8) -> dict[str, Any]:
    if not url:
        return {"ok": None, "url": "", "message": "No URL provided"}
    try:
        req = urllib.request.Request(url, method="GET", headers={"User-Agent": "AIQA-VDI-Readiness/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return {"ok": True, "url": url, "status_code": resp.status, "message": "HTTP reachable"}
    except Exception as exc:
        return {"ok": False, "url": url, "status_code": None, "message": f"{type(exc).__name__}: {exc}"}


def _env_snapshot() -> dict[str, Any]:
    keys = [
        "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "http_proxy", "https_proxy", "no_proxy",
        "BASE_URL", "API_BASE_URL", "AIQA_RUNTIME_MODE", "AIQA_VDI_MODE", "AIQA_DOCKER_MODE",
        "AIQA_DOCKER_HOST", "DOCKER_HOST", "NPM_CONFIG_REGISTRY", "MAVEN_OPTS", "JAVA_TOOL_OPTIONS",
        "PLAYWRIGHT_BROWSERS_PATH", "CODEGEN_PROVIDER", "LLM_PROVIDER", "STRUCTURED_PROVIDER",
    ]
    data: dict[str, Any] = {}
    for k in keys:
        v = os.getenv(k, "")
        if any(secret in k.lower() for secret in ["token", "key", "password", "secret"]):
            v = "***" if v else ""
        data[k] = v
    return data


def _detect_vdi_hints() -> dict[str, Any]:
    hints: list[str] = []
    procs: list[str] = []
    services: list[str] = []
    if platform.system().lower() == "windows":
        task = _run(["cmd", "/c", "tasklist"], timeout=20)
        text = (task.get("stdout") or "").lower()
        for name in ["vmware", "horizon", "vmtoolsd", "viewagent", "wsl", "vpn", "zscaler", "netskope", "globalprotect", "pulse", "cisco", "forticlient", "tanium", "crowdstrike"]:
            if name in text:
                hints.append(name)
        svc = _run(["cmd", "/c", "sc", "query", "type=", "service", "state=", "all"], timeout=25)
        services_text = (svc.get("stdout") or "").lower()
        for name in ["vmware", "horizon", "docker", "vpn", "zscaler", "netskope", "globalprotect", "pulse", "cisco", "forti"]:
            if name in services_text:
                services.append(name)
        sysinfo = _run(["cmd", "/c", "systeminfo"], timeout=30)
        virtualization_hint = ""
        for line in (sysinfo.get("stdout") or "").splitlines():
            if "Hyper-V" in line or "Virtualization" in line:
                virtualization_hint += line.strip() + "\n"
        return {"process_hints": sorted(set(hints)), "service_hints": sorted(set(services)), "virtualization_hint": virtualization_hint.strip(), "raw_systeminfo_ok": sysinfo.get("ok")}
    # Linux/Mac fallback
    for p in ["/sys/class/dmi/id/product_name", "/sys/class/dmi/id/sys_vendor"]:
        try:
            val = Path(p).read_text(encoding="utf-8", errors="ignore").strip()
            if val:
                hints.append(val)
        except Exception:
            pass
    return {"process_hints": sorted(set(hints)), "service_hints": [], "virtualization_hint": "; ".join(hints), "raw_systeminfo_ok": None}


def save_vdi_profile(data: dict[str, Any]) -> dict[str, Any]:
    VDI_DIR.mkdir(parents=True, exist_ok=True)
    payload = {"ok": True, "saved_at": _now(), **data}
    VDI_PROFILE.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    log_event("vdi_profile", "VDI/Horizon runtime profile saved for this repo.", status="done", progress=100, details={k: v for k, v in payload.items() if k not in {"proxy_password", "token"}})
    return {"ok": True, "profile_path": str(VDI_PROFILE), "profile": payload}


def read_vdi_profile() -> dict[str, Any]:
    if not VDI_PROFILE.exists():
        return {"ok": False, "message": "No VDI profile saved yet.", "profile_path": str(VDI_PROFILE)}
    try:
        return {"ok": True, "profile_path": str(VDI_PROFILE), "profile": json.loads(VDI_PROFILE.read_text(encoding="utf-8"))}
    except Exception as exc:
        return {"ok": False, "profile_path": str(VDI_PROFILE), "message": f"{type(exc).__name__}: {exc}"}


def check_vdi_readiness(base_url: str = "", api_base_url: str = "", docker_mode: str = "local", docker_host: str = "") -> dict[str, Any]:
    VDI_DIR.mkdir(parents=True, exist_ok=True)
    tools = {
        "python": {"available": True, "path": sys.executable, "version": sys.version.split()[0]},
        "git": _which_version("git"),
        "docker": _which_version("docker"),
        "docker_compose": _run(["docker", "compose", "version"], timeout=12),
        "node": _which_version("node"),
        "npm": _which_version("npm"),
        "npx": _which_version("npx"),
        "java": _which_version("java"),
        "maven": _which_version("mvn", ["-version"]),
        "codex": _which_version("codex"),
    }
    docker_info = _run(["docker", "info"], timeout=18) if tools["docker"].get("available") else {"ok": False, "stderr": "docker command not found"}
    docker_contexts = _run(["docker", "context", "ls"], timeout=12) if tools["docker"].get("available") else {"ok": False, "stderr": "docker command not found"}
    network = {
        "gui_loopback": _tcp_probe("127.0.0.1", 8080),
        "base_url": _http_probe(base_url or os.getenv("BASE_URL", "")),
        "api_base_url": _http_probe(api_base_url or os.getenv("API_BASE_URL", "")),
        "host_docker_internal": _tcp_probe("host.docker.internal", 80),
    }
    env = _env_snapshot()
    vdi_hints = _detect_vdi_hints()
    docker_ok = bool(docker_info.get("ok"))
    codex_ok = bool(tools["codex"].get("available"))
    java_host_needed = docker_mode == "host"
    node_host_needed = docker_mode == "host"
    blockers: list[str] = []
    warnings: list[str] = []
    if docker_mode in {"local", "remote"} and not docker_ok:
        blockers.append("Docker runtime is not reachable. In VDI/Horizon, ask client IT to enable nested virtualization or provide a remote Docker/CI runner.")
    if java_host_needed and not tools["java"].get("available"):
        blockers.append("Host Java is missing. Use Docker mode for Rest Assured or install JDK 17/21.")
    if java_host_needed and not tools["maven"].get("available"):
        blockers.append("Host Maven is missing. Use Docker mode for Rest Assured or install Maven.")
    if node_host_needed and not tools["node"].get("available"):
        blockers.append("Host Node.js is missing. Use Docker mode for Playwright/API or install Node 20/22 LTS.")
    if not codex_ok:
        warnings.append("Codex CLI was not found. RCA can run deterministic checks, but AI patching needs Codex or Ollama.")
    if not env.get("HTTP_PROXY") and not env.get("HTTPS_PROXY") and (env.get("AIQA_VDI_MODE") or vdi_hints.get("process_hints")):
        warnings.append("No proxy variables detected. Corporate VDIs often need HTTP_PROXY/HTTPS_PROXY/NO_PROXY for Docker, npm, Maven, Codex, and APIs.")
    if network["base_url"].get("ok") is False:
        warnings.append("Application URL is not reachable from this VDI session. Start VPN/client app network or run inside the correct Horizon desktop pool.")
    if network["api_base_url"].get("ok") is False:
        warnings.append("API base URL is not reachable from this VDI session. Check VPN, proxy, DNS, firewall, or service environment.")

    runtime_recommendation = "docker-local" if docker_ok else "remote-docker-or-host-tools"
    if docker_mode == "remote":
        runtime_recommendation = "docker-remote"
    if docker_mode == "host":
        runtime_recommendation = "host-tools"

    data = {
        "ok": not blockers,
        "generated_at": _now(),
        "runtime_recommendation": runtime_recommendation,
        "requested_docker_mode": docker_mode,
        "requested_docker_host": docker_host,
        "host": {
            "hostname": socket.gethostname(),
            "platform": platform.platform(),
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "python_executable": sys.executable,
            "repo_root": str(REPO_ROOT),
        },
        "tools": tools,
        "docker_info": docker_info,
        "docker_contexts": docker_contexts,
        "network": network,
        "environment": env,
        "vdi_hints": vdi_hints,
        "blockers": blockers,
        "warnings": warnings,
        "next_steps": _next_steps(blockers, warnings, docker_ok, docker_mode),
        "report_urls": {
            "json": "/artifacts/reports/vdi-readiness-report.json",
            "html": "/artifacts/reports/vdi-readiness-report.html",
            "checklist": "/artifacts/reports/client-vdi-preflight-checklist.md",
        },
    }
    _write_reports(data)
    log_event("vdi_readiness", "VDI/Horizon readiness check completed.", status="done" if data["ok"] else "warning", progress=100, details={"blockers": blockers, "warnings": warnings, "runtime_recommendation": runtime_recommendation})
    return data


def _next_steps(blockers: list[str], warnings: list[str], docker_ok: bool, docker_mode: str) -> list[str]:
    steps = []
    if blockers:
        steps.append("Resolve blockers before execution/RCA/self-healing. You can still use documentation and deterministic analysis.")
    if not docker_ok and docker_mode != "host":
        steps.append("Ask client IT whether Docker Desktop is allowed in Horizon/VDI and whether nested virtualization is enabled. If not, configure a remote Docker/CI runner.")
    steps.append("Save Project Setup with the application base URL and provider.")
    steps.append("Use Enterprise Stack → Pull images + start from GUI, or API Automation → Pull API Docker Images for API runtimes.")
    steps.append("Use Codex / Ollama → Connect AI provider before AI patching.")
    steps.append("Run Existing Framework Control or API Automation from GUI. RCA/self-healing must remain failed-only.")
    if warnings:
        steps.append("Review warnings with client IT: proxy, VPN, DNS, certificates, API reachability, or tool allow-listing.")
    return steps


def _write_reports(data: dict[str, Any]) -> None:
    VDI_READINESS_JSON.parent.mkdir(parents=True, exist_ok=True)
    VDI_READINESS_JSON.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    md = ["# VDI / Horizon VM Readiness Report", "", f"Generated: {data.get('generated_at')}", "", f"Overall: {'READY' if data.get('ok') else 'ACTION REQUIRED'}", "", "## Runtime recommendation", "", f"- {data.get('runtime_recommendation')}", "", "## Blockers"]
    for b in data.get("blockers") or ["None"]:
        md.append(f"- {b}")
    md.extend(["", "## Warnings"])
    for w in data.get("warnings") or ["None"]:
        md.append(f"- {w}")
    md.extend(["", "## Next steps"])
    for s in data.get("next_steps") or []:
        md.append(f"- {s}")
    md.extend(["", "## Tool summary"])
    for name, info in data.get("tools", {}).items():
        if isinstance(info, dict):
            available = info.get("available", info.get("ok"))
            version = info.get("version") or (info.get("stdout") or "").splitlines()[0:1]
            md.append(f"- {name}: {'OK' if available else 'missing/check'} {version if isinstance(version, str) else ''}")
    VDI_READINESS_MD.write_text("\n".join(md) + "\n", encoding="utf-8")
    html = """<!doctype html><html><head><meta charset='utf-8'><title>VDI Readiness</title><style>body{font-family:Segoe UI,Arial;margin:28px;line-height:1.45}pre{background:#0f172a;color:#dbeafe;padding:16px;border-radius:12px;overflow:auto}.ok{color:#16a34a}.bad{color:#dc2626}.warn{color:#d97706}</style></head><body>"""
    html += f"<h1>VDI / Horizon VM Readiness Report</h1><h2 class={'ok' if data.get('ok') else 'bad'}>{'READY' if data.get('ok') else 'ACTION REQUIRED'}</h2>"
    html += "<h3>Blockers</h3><ul>" + "".join(f"<li>{b}</li>" for b in (data.get("blockers") or ["None"])) + "</ul>"
    html += "<h3>Warnings</h3><ul>" + "".join(f"<li>{w}</li>" for w in (data.get("warnings") or ["None"])) + "</ul>"
    html += "<h3>Next steps</h3><ol>" + "".join(f"<li>{s}</li>" for s in data.get("next_steps", [])) + "</ol>"
    html += "<h3>Raw readiness JSON</h3><pre>" + json.dumps(data, indent=2, ensure_ascii=False).replace("<", "&lt;") + "</pre></body></html>"
    VDI_READINESS_HTML.write_text(html, encoding="utf-8")
    checklist = _client_checklist()
    VDI_CHECKLIST_MD.write_text(checklist, encoding="utf-8")


def _client_checklist() -> str:
    return """# Client VDI / Horizon Preflight Checklist

Use this with client IT before running the AI QA solution in a hosted VDI/Horizon VM.

## Access and security
- Confirm the correct Horizon desktop pool/VDI image for QA automation.
- Confirm whether local admin rights are available or whether tools are preinstalled by IT.
- Confirm approved folders for source code, npm cache, Maven cache, Docker volumes, browser traces, and reports.
- Confirm antivirus/EDR exclusions are not blocking Node, Python, Java, Maven, Docker, browsers, or Codex CLI.

## Network
- Confirm application URL and API base URL are reachable from inside the VDI.
- Confirm VPN/client network is active before Docker Desktop starts when required.
- Confirm DNS and internal certificates are installed in the VDI and Docker runtime.
- Capture HTTP_PROXY, HTTPS_PROXY, and NO_PROXY values if corporate proxy is required.
- Confirm whether `host.docker.internal` works for containers reaching services running on the VDI host.

## Docker / container runtime
- Confirm Docker Desktop is approved for the VDI/Horizon environment.
- Confirm nested virtualization is enabled if Docker Desktop runs inside the VDI.
- If Docker Desktop is not allowed, provide a remote Docker context, CI runner, or Linux execution worker.
- Allow these image families or mirror them to internal registry: Playwright, Maven/Eclipse Temurin, WireMock, MockServer, Newman, Grafana, Prometheus, Chroma/Ollama if used.

## AI provider
- Confirm Codex CLI is approved and can authenticate with `codex login` or device auth.
- If internet is restricted, confirm OpenAI/Codex endpoints are allowed or configure approved LLM provider.
- Never store secrets in screenshots, reports, or source code.

## Test execution
- Use GUI-first launcher only, then control everything from `http://127.0.0.1:8080`.
- Run VDI Readiness first.
- Run Docker/API Docker readiness before execution.
- Run RCA/self-healing only on failed tests and review patches before commit.
"""
