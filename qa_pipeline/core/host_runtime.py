from __future__ import annotations

import json
import os
import platform
import shutil
import socket
import subprocess
import time
from pathlib import Path
from typing import Any

from qa_pipeline.core.paths import QA_CACHE_DIR, REPO_ROOT, GENERATED_PLAYWRIGHT_DIR
from qa_pipeline.core.runtime_logger import log_event

HOST_RUNTIME_DIR = QA_CACHE_DIR / "host-runtime"
HOST_RUNTIME_STATE = HOST_RUNTIME_DIR / "host-runtime-state.json"
HOST_REPORT_DIR = GENERATED_PLAYWRIGHT_DIR / "reports" / "host-runtime"
HOST_REPORT_JSON = HOST_REPORT_DIR / "host-runtime-readiness.json"
HOST_REPORT_HTML = HOST_REPORT_DIR / "host-runtime-readiness.html"

SUPPORTED_TOOLS = {
    "python": {"commands": [["python", "--version"], ["py", "--version"]], "purpose": "GUI backend, RCA, RAG, self-healing orchestration"},
    "git": {"commands": [["git", "--version"]], "purpose": "clone/pull/push frameworks and create branches"},
    "node": {"commands": [["node", "--version"]], "purpose": "Playwright Web/API TypeScript execution"},
    "npm": {"commands": [["npm", "--version"]], "purpose": "install Node/Playwright dependencies"},
    "npx": {"commands": [["npx", "--version"]], "purpose": "run Playwright commands without global installs"},
    "playwright": {"commands": [["npx", "playwright", "--version"]], "purpose": "Web/API browser automation runtime"},
    "java": {"commands": [["java", "-version"]], "purpose": "Rest Assured Java runtime"},
    "maven": {"commands": [["mvn", "-version"]], "purpose": "Rest Assured Java build/test runner"},
    "codex": {"commands": [["codex", "--version"]], "purpose": "AI patching/RCA/self-healing through Codex CLI"},
    "ollama": {"commands": [["ollama", "--version"]], "purpose": "optional local LLM fallback if Codex is unavailable"},
}


def _run(cmd: list[str], timeout: int = 8, cwd: Path | None = None) -> dict[str, Any]:
    exe = shutil.which(cmd[0])
    if not exe:
        return {"available": False, "ok": False, "cmd": " ".join(cmd), "message": f"{cmd[0]} not found in PATH", "stdout": "", "stderr": ""}
    try:
        cp = subprocess.run(cmd, cwd=str(cwd or REPO_ROOT), capture_output=True, text=True, timeout=timeout)
        return {
            "available": True,
            "ok": cp.returncode == 0,
            "returncode": cp.returncode,
            "cmd": " ".join(cmd),
            "stdout": (cp.stdout or "")[-2500:],
            "stderr": (cp.stderr or "")[-2500:],
        }
    except Exception as exc:
        return {"available": True, "ok": False, "cmd": " ".join(cmd), "error": f"{type(exc).__name__}: {exc}", "stdout": "", "stderr": ""}


def _first_ok(commands: list[list[str]], timeout: int = 8) -> dict[str, Any]:
    results = []
    for cmd in commands:
        result = _run(cmd, timeout=timeout)
        results.append(result)
        if result.get("available") and result.get("ok"):
            clean = dict(result)
            clean["attempts"] = [dict(x) for x in results]
            return clean
    last = dict(results[-1]) if results else {"available": False, "ok": False}
    last["attempts"] = [dict(x) for x in results]
    return last


def _tool_status() -> dict[str, Any]:
    statuses = {}
    for name, meta in SUPPORTED_TOOLS.items():
        statuses[name] = {**_first_ok(meta["commands"]), "purpose": meta["purpose"]}
    return statuses


def _ensure_dirs() -> dict[str, str]:
    HOST_RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    HOST_REPORT_DIR.mkdir(parents=True, exist_ok=True)
    for p in [QA_CACHE_DIR / "rag", QA_CACHE_DIR / "runtime", QA_CACHE_DIR / "jobs", QA_CACHE_DIR / "artifacts", GENERATED_PLAYWRIGHT_DIR / "reports"]:
        p.mkdir(parents=True, exist_ok=True)
    return {
        "host_runtime_dir": str(HOST_RUNTIME_DIR),
        "reports_dir": str(GENERATED_PLAYWRIGHT_DIR / "reports"),
        "cache_dir": str(QA_CACHE_DIR),
        "rag_dir": str(QA_CACHE_DIR / "rag"),
        "jobs_dir": str(QA_CACHE_DIR / "jobs"),
        "artifacts_dir": str(QA_CACHE_DIR / "artifacts"),
    }


def host_runtime_readiness(scope: str = "all") -> dict[str, Any]:
    dirs = _ensure_dirs()
    tools = _tool_status()
    required_core = ["python", "git"]
    required_web = ["node", "npm", "npx"]
    required_api_java = ["java", "maven"]
    warnings: list[str] = []
    blockers: list[str] = []

    if not tools["python"].get("ok"):
        blockers.append("Python is not available. The GUI backend and RCA engine need Python 3.11/3.12.")
    if not tools["git"].get("available"):
        warnings.append("Git is not available. Existing framework execution can still work from a folder, but branch/PR workflow will be limited.")
    if not all(tools[x].get("available") for x in required_web):
        warnings.append("Node.js/npm/npx are missing. Playwright Web/API TypeScript execution needs Node.js 20/22.")
    if not all(tools[x].get("available") for x in required_api_java):
        warnings.append("Java/Maven are missing. Rest Assured Java execution needs JDK 17/21 and Maven 3.9+.")
    if not tools["playwright"].get("ok"):
        warnings.append("Playwright CLI is not ready in the current repo. Run npm install and npx playwright install inside the target framework or use the GUI install button.")
    if not tools["codex"].get("available"):
        warnings.append("Codex CLI is not found. AI patching can be skipped, use Ollama/deterministic mode, or install Codex later.")

    ok = not blockers
    report = {
        "ok": ok,
        "mode": "no_docker_host_runtime",
        "hostname": socket.gethostname(),
        "os": platform.platform(),
        "python_version": platform.python_version(),
        "repo_root": str(REPO_ROOT),
        "dirs": dirs,
        "tools": tools,
        "warnings": warnings,
        "blockers": blockers,
        "host_services_ready": ok,
        "message": "No-Docker Host Runtime readiness completed. Missing feature-specific tools are warnings unless they block the selected workflow.",
        "recommended_next_steps": [
            "Run INSTALL_HOST_RUNTIME_WINDOWS.ps1 if tools are missing and client IT allows installation.",
            "Run Start Host Services from GUI to initialize local cache, RAG, logs, reports, and job folders.",
            "Run npm install + npx playwright install in Playwright frameworks before Web/API TS execution.",
            "Run mvn test once in Rest Assured projects to warm the Maven cache.",
            "Run codex login or codex login --device-auth if Codex patching is required.",
        ],
        "report_json": str(HOST_REPORT_JSON),
        "report_html": str(HOST_REPORT_HTML),
    }
    _write_report(report)
    return report


def _write_report(report: dict[str, Any]) -> None:
    HOST_REPORT_DIR.mkdir(parents=True, exist_ok=True)
    HOST_REPORT_JSON.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    rows = []
    for name, st in (report.get("tools") or {}).items():
        status = "OK" if st.get("ok") else "FOUND" if st.get("available") else "MISSING"
        rows.append(f"<tr><td>{name}</td><td>{status}</td><td>{st.get('purpose','')}</td><td><code>{st.get('cmd','')}</code></td></tr>")
    html = f"""<!doctype html><html><head><meta charset='utf-8'><title>No-Docker Host Runtime Readiness</title>
<style>body{{font-family:Segoe UI,Arial,sans-serif;margin:28px;color:#172033}}table{{border-collapse:collapse;width:100%}}td,th{{border:1px solid #ddd;padding:8px}}th{{background:#eff6ff}}.ok{{color:#15803d;font-weight:800}}.warn{{color:#b45309;font-weight:800}}.bad{{color:#b91c1c;font-weight:800}}pre{{background:#f8fafc;padding:12px;border-radius:10px;white-space:pre-wrap}}</style></head><body>
<h1>No-Docker Host Runtime Readiness</h1><p><b>Host:</b> {report.get('hostname')}<br><b>Mode:</b> {report.get('mode')}<br><b>Status:</b> {'READY' if report.get('ok') else 'ACTION REQUIRED'}</p>
<h2>Tool Status</h2><table><tr><th>Tool</th><th>Status</th><th>Purpose</th><th>Command</th></tr>{''.join(rows)}</table>
<h2>Warnings</h2><pre>{json.dumps(report.get('warnings',[]), indent=2)}</pre>
<h2>Blockers</h2><pre>{json.dumps(report.get('blockers',[]), indent=2)}</pre>
<h2>Folders</h2><pre>{json.dumps(report.get('dirs',{}), indent=2)}</pre>
</body></html>"""
    HOST_REPORT_HTML.write_text(html, encoding="utf-8")


def start_host_services() -> dict[str, Any]:
    dirs = _ensure_dirs()
    state = {
        "ok": True,
        "mode": "no_docker_host_runtime",
        "started_at_epoch_ms": int(time.time() * 1000),
        "hostname": socket.gethostname(),
        "services": {
            "fastapi_gui": {"ready": True, "note": "Current process serves the GUI/API."},
            "local_rag_store": {"ready": True, "path": dirs["rag_dir"]},
            "runtime_logs": {"ready": True, "path": str(QA_CACHE_DIR / "runtime")},
            "job_queue": {"ready": True, "path": dirs["jobs_dir"]},
            "artifact_store": {"ready": True, "path": dirs["artifacts_dir"]},
            "report_store": {"ready": True, "path": dirs["reports_dir"]},
            "host_mock_service": {"ready": True, "note": "Built-in FastAPI mock/service hooks available. WireMock standalone is optional."},
        },
        "message": "No-Docker Host Services are initialized. Use the same GUI buttons for execution, RCA, self-healing, reports and VDI agent communication.",
    }
    HOST_RUNTIME_STATE.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    log_event("host_runtime", "No-Docker Host Services initialized", status="ok", progress=100, details=state)
    return state


def stop_host_services() -> dict[str, Any]:
    state = {"ok": True, "mode": "no_docker_host_runtime", "stopped_at_epoch_ms": int(time.time() * 1000), "message": "Host services stopped/marked idle. The GUI process itself is still running."}
    HOST_RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    HOST_RUNTIME_STATE.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    log_event("host_runtime", "No-Docker Host Services stopped/marked idle", status="ok", progress=100, details=state)
    return state


def host_runtime_status() -> dict[str, Any]:
    readiness = host_runtime_readiness()
    state = {}
    if HOST_RUNTIME_STATE.exists():
        try:
            state = json.loads(HOST_RUNTIME_STATE.read_text(encoding="utf-8", errors="replace"))
        except Exception as exc:
            state = {"error": f"{type(exc).__name__}: {exc}"}
    return {
        "ok": readiness.get("ok", False),
        "enterprise_ready": readiness.get("ok", False),
        "docker_available": False,
        "host_runtime_mode": True,
        "docker_required": False,
        "service_rows": [
            {"service": "fastapi_gui", "ready": True, "state": "running", "health": "ok", "purpose": "GUI/API control plane"},
            {"service": "local_rag_store", "ready": True, "state": "folder", "health": "ok", "purpose": "RAG index and framework intelligence"},
            {"service": "runtime_logs", "ready": True, "state": "jsonl", "health": "ok", "purpose": "progress, RCA and self-healing logs"},
            {"service": "job_queue", "ready": True, "state": "folder", "health": "ok", "purpose": "VM/VDI message communication"},
            {"service": "report_store", "ready": True, "state": "folder", "health": "ok", "purpose": "HTML/JSON/JUnit reports"},
        ],
        "host_readiness": readiness,
        "state": state,
        "message": "No-Docker Host Runtime is selected. Docker stack actions are mapped to host services; Docker Desktop is not required.",
    }


def install_plan() -> dict[str, Any]:
    return {
        "ok": True,
        "mode": "no_docker_host_runtime",
        "windows_script": "scripts/host-runtime/INSTALL_HOST_RUNTIME_WINDOWS.ps1",
        "check_script": "scripts/host-runtime/CHECK_HOST_RUNTIME_WINDOWS.ps1",
        "tools": [
            {"tool": "Python 3.11/3.12", "purpose": "GUI backend, RCA, self-healing"},
            {"tool": "Git", "purpose": "repo clone, branch, PR workflow"},
            {"tool": "Node.js 20/22", "purpose": "Playwright Web/API execution"},
            {"tool": "Playwright browsers", "purpose": "browser automation"},
            {"tool": "JDK 17/21", "purpose": "Rest Assured Java"},
            {"tool": "Maven 3.9+", "purpose": "Rest Assured build/test execution"},
            {"tool": "Codex CLI", "purpose": "AI patching/self-healing"},
            {"tool": "Ollama", "purpose": "optional local LLM fallback"},
        ],
        "message": "Run the install script only if client IT allows host installations. Otherwise use pre-approved software images/golden VM/VDI image.",
    }


def execute_host_command(command: str, cwd: str | Path | None = None, timeout: int = 600) -> dict[str, Any]:
    if not command.strip():
        return {"ok": False, "error": "Command is empty"}
    try:
        cp = subprocess.run(command, cwd=str(cwd or REPO_ROOT), shell=True, capture_output=True, text=True, timeout=timeout)
        return {"ok": cp.returncode == 0, "returncode": cp.returncode, "command": command, "stdout": (cp.stdout or "")[-6000:], "stderr": (cp.stderr or "")[-6000:]}
    except Exception as exc:
        return {"ok": False, "command": command, "error": f"{type(exc).__name__}: {exc}"}
