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

PROFILE_DIR = QA_CACHE_DIR / "runtime-mode"
PROFILE_PATH = PROFILE_DIR / "runtime-profile.json"

DEFAULT_PROFILE: dict[str, Any] = {
    "runtime_mode": os.getenv("AIQA_RUNTIME_MODE", "local"),
    "runtime_engine": os.getenv("AIQA_RUNTIME_ENGINE", "docker"),
    "description": "Local PC mode: GUI, selected runtime engine, Codex/Ollama, execution, RCA and reports run from this machine.",
    "control_plane_url": "http://127.0.0.1:8080",
    "vm_public_url": "",
    "use_vdi_agents": False,
    "default_execution_target": "local",
    "docker_runtime": os.getenv("AIQA_DOCKER_RUNTIME", "local"),
    "workspace_root": str(REPO_ROOT),
    "reports_root": str(GENERATED_PLAYWRIGHT_DIR / "reports"),
    "notes": "",
}

MODE_DESCRIPTIONS = {
    "local": "Everything runs on the same local machine. Best for personal laptop/desktop and demos.",
    "vm_control_plane": "GUI, Docker, RAG and reports run on a central VM. VDIs access the GUI by VM URL.",
    "vdi_agent": "The current machine is a lightweight VDI runner agent that connects to a VM control plane.",
    "hybrid": "VM hosts central services, selected execution/fixing jobs can run on VDI agents.",
}


def _now_ms() -> int:
    return int(time.time() * 1000)


def read_runtime_profile() -> dict[str, Any]:
    if not PROFILE_PATH.exists():
        return {**DEFAULT_PROFILE, "exists": False, "mode_descriptions": MODE_DESCRIPTIONS}
    try:
        data = json.loads(PROFILE_PATH.read_text(encoding="utf-8", errors="replace"))
        merged = {**DEFAULT_PROFILE, **(data or {})}
        merged["exists"] = True
        merged["mode_descriptions"] = MODE_DESCRIPTIONS
        return merged
    except Exception as exc:
        return {**DEFAULT_PROFILE, "exists": False, "error": f"{type(exc).__name__}: {exc}", "mode_descriptions": MODE_DESCRIPTIONS}


def save_runtime_profile(data: dict[str, Any]) -> dict[str, Any]:
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    mode = str(data.get("runtime_mode") or "local").strip() or "local"
    if mode not in MODE_DESCRIPTIONS:
        mode = "local"
    engine = str(data.get("runtime_engine") or data.get("execution_engine") or "docker").strip().lower()
    if engine not in {"docker", "host", "auto"}:
        engine = "docker"
    # Compatibility: old GUI value docker_runtime=none means No-Docker Host Runtime.
    if str(data.get("docker_runtime") or "").lower() == "none":
        engine = "host"
    profile = {
        **DEFAULT_PROFILE,
        **data,
        "runtime_mode": mode,
        "runtime_engine": engine,
        "description": MODE_DESCRIPTIONS.get(mode, DEFAULT_PROFILE["description"]),
        "updated_at_epoch_ms": _now_ms(),
    }
    PROFILE_PATH.write_text(json.dumps(profile, indent=2, ensure_ascii=False), encoding="utf-8")
    profile["exists"] = True
    profile["mode_descriptions"] = MODE_DESCRIPTIONS
    return profile


def _run_quick(cmd: list[str], timeout: int = 8) -> dict[str, Any]:
    exe = shutil.which(cmd[0])
    if not exe:
        return {"available": False, "cmd": cmd[0], "message": "not found in PATH", "stdout": "", "stderr": ""}
    try:
        cp = subprocess.run(cmd, cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=timeout)
        return {
            "available": True,
            "cmd": " ".join(cmd),
            "returncode": cp.returncode,
            "ok": cp.returncode == 0,
            "stdout": (cp.stdout or "")[-2000:],
            "stderr": (cp.stderr or "")[-2000:],
        }
    except Exception as exc:
        return {"available": True, "cmd": " ".join(cmd), "ok": False, "error": f"{type(exc).__name__}: {exc}"}


def local_machine_readiness() -> dict[str, Any]:
    """Friendly readiness check for local PC mode.

    This check is intentionally non-blocking. It reports missing tools but does not
    disable the GUI. Users can still use features that do not require a missing tool.
    """
    profile = read_runtime_profile()
    host = socket.gethostname()
    tools = {
        "python": {"available": True, "version": platform.python_version(), "executable": shutil.which("python") or shutil.which("py") or "current interpreter"},
        "git": _run_quick(["git", "--version"]),
        "node": _run_quick(["node", "--version"]),
        "npm": _run_quick(["npm", "--version"]),
        "npx": _run_quick(["npx", "--version"]),
        "docker": _run_quick(["docker", "version", "--format", "{{.Server.Version}}"]),
        "docker_compose": _run_quick(["docker", "compose", "version"]),
        "codex": _run_quick(["codex", "--version"]),
        "java": _run_quick(["java", "-version"]),
        "maven": _run_quick(["mvn", "-version"]),
    }
    docker_running = bool(tools["docker"].get("ok"))
    node_ready = bool(tools["node"].get("available") and tools["npm"].get("available") and tools["npx"].get("available"))
    codex_available = bool(tools["codex"].get("available"))
    blockers = []
    warnings = []
    if not node_ready:
        warnings.append("Node.js/npm/npx not found. Web/API Playwright execution may not work locally until Node.js 20/22 is installed.")
    if not docker_running:
        warnings.append("Docker engine is not reachable. Start Docker Desktop or use VM/remote Docker mode before Docker-based services.")
    if not codex_available:
        warnings.append("Codex CLI is not found. AI patching can use Ollama/deterministic mode or Codex can be installed later.")
    # Local PC is considered GUI-ready even if Docker/AI is not ready yet.
    return {
        "ok": True,
        "runtime_mode": profile.get("runtime_mode", "local"),
        "hostname": host,
        "os": platform.platform(),
        "repo_root": str(REPO_ROOT),
        "tools": tools,
        "docker_running": docker_running,
        "node_ready": node_ready,
        "codex_available": codex_available,
        "warnings": warnings,
        "blockers": blockers,
        "message": "Local GUI is usable. Missing tools are shown as warnings because different features need different runtimes.",
        "recommended_next_steps": [
            "Select Local PC mode if all activities run on this machine.",
            "Start Docker Desktop before Start Docker Stack.",
            "Use Codex/Ollama tab to connect AI provider.",
            "Use Existing Framework Control or API Automation depending on your task.",
        ],
    }
