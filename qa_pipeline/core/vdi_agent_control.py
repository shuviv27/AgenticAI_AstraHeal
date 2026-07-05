from __future__ import annotations

import json
import os
import platform
import secrets
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from qa_pipeline.core.paths import QA_CACHE_DIR, REPO_ROOT
from qa_pipeline.core.runtime_logger import log_event

AGENT_DIR = QA_CACHE_DIR / "runner-agents"
TOKEN_DIR = AGENT_DIR / "tokens"
AGENTS_DIR = AGENT_DIR / "agents"
JOBS_DIR = AGENT_DIR / "jobs"
PACKAGES_DIR = AGENT_DIR / "packages"


def _ensure() -> None:
    for p in (AGENT_DIR, TOKEN_DIR, AGENTS_DIR, JOBS_DIR, PACKAGES_DIR):
        p.mkdir(parents=True, exist_ok=True)


def _now_ms() -> int:
    return int(time.time() * 1000)


def _safe_name(value: str, default: str = "agent") -> str:
    raw = (value or default).strip()
    cleaned = "".join(ch if ch.isalnum() or ch in "-_ ." else "_" for ch in raw).strip().replace(" ", "-")
    return cleaned or default


def _read_json(path: Path, default: Any) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        pass
    return default


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def create_agent_token(agent_name: str = "", workspace_root: str = "D:\\AI_QA_WORKSPACE", created_by: str = "gui", metadata: Optional[Dict[str, Any]] = None, timeout_seconds: int = 7200) -> Dict[str, Any]:
    _ensure()
    agent_name = _safe_name(agent_name or f"Worker-{platform.node()}", "worker-agent")
    token = "aiqa_agent_" + secrets.token_urlsafe(24)
    agent_id = _safe_name(agent_name.lower()) + "-" + secrets.token_hex(4)
    data = {
        "ok": True,
        "agent_id": agent_id,
        "agent_name": agent_name,
        "token": token,
        "workspace_root": workspace_root or "D:\\AI_QA_WORKSPACE",
        "created_by": created_by,
        "metadata": metadata or {},
        "timeout_seconds": timeout_seconds,
        "created_at_epoch_ms": _now_ms(),
        "status": "token_created",
        "message": "Copy this token into the Worker Agent package. The token tells the VM GUI which worker machine is allowed to connect.",
    }
    _write_json(TOKEN_DIR / f"{token}.json", data)
    log_event("runner_agents", f"Created worker runner token for {agent_name}", status="ok", progress=15)
    return data


def validate_token(token: str) -> Dict[str, Any]:
    _ensure()
    token_data = _read_json(TOKEN_DIR / f"{token}.json", {})
    if not token_data:
        return {"ok": False, "error": "Invalid or unknown agent token."}
    return {"ok": True, **token_data}


def register_agent(payload: Dict[str, Any]) -> Dict[str, Any]:
    _ensure()
    token = str(payload.get("token") or payload.get("AIQA_AGENT_TOKEN") or "").strip()
    valid = validate_token(token)
    if not valid.get("ok"):
        return valid
    agent_id = str(payload.get("agent_id") or valid.get("agent_id"))
    agent_name = str(payload.get("agent_name") or valid.get("agent_name") or agent_id)
    data = {
        **valid,
        "ok": True,
        "agent_id": agent_id,
        "agent_name": agent_name,
        "status": "online",
        "hostname": payload.get("hostname") or platform.node(),
        "ip_address": payload.get("ip_address") or payload.get("host_ip") or payload.get("host") or "",
        "username": payload.get("username") or os.getenv("USERNAME") or os.getenv("USER") or "unknown",
        "workspace_root": payload.get("workspace_root") or valid.get("workspace_root"),
        "capabilities": payload.get("capabilities") or {},
        "last_registered_epoch_ms": _now_ms(),
        "last_heartbeat_epoch_ms": _now_ms(),
        "message": "Worker Agent registered successfully.",
    }
    data.pop("token", None)  # do not store token in visible agent list
    _write_json(AGENTS_DIR / f"{agent_id}.json", data)
    log_event("runner_agents", f"Worker Agent registered: {agent_name}", status="ok", progress=25)
    return data


def heartbeat_agent(payload: Dict[str, Any]) -> Dict[str, Any]:
    _ensure()
    token = str(payload.get("token") or "").strip()
    valid = validate_token(token)
    if not valid.get("ok"):
        return valid
    agent_id = str(payload.get("agent_id") or valid.get("agent_id"))
    current = _read_json(AGENTS_DIR / f"{agent_id}.json", {})
    if not current:
        current = register_agent(payload)
    current.update({
        "ok": True,
        "status": "online",
        "last_heartbeat_epoch_ms": _now_ms(),
        "hostname": payload.get("hostname") or current.get("hostname"),
        "ip_address": payload.get("ip_address") or payload.get("host_ip") or payload.get("host") or current.get("ip_address") or "",
        "username": payload.get("username") or current.get("username"),
        "workspace_root": payload.get("workspace_root") or current.get("workspace_root"),
        "capabilities": payload.get("capabilities") or current.get("capabilities") or {},
    })
    current.pop("token", None)
    _write_json(AGENTS_DIR / f"{agent_id}.json", current)
    return {"ok": True, "agent_id": agent_id, "status": "online", "server_time_epoch_ms": _now_ms()}


def list_agents() -> Dict[str, Any]:
    _ensure()
    agents: List[Dict[str, Any]] = []
    cutoff = _now_ms() - 60_000
    for p in AGENTS_DIR.glob("*.json"):
        data = _read_json(p, {})
        if not data:
            continue
        last = int(data.get("last_heartbeat_epoch_ms") or 0)
        data["status"] = "online" if last >= cutoff else "offline"
        data["age_seconds"] = int((_now_ms() - last) / 1000) if last else None
        agents.append(data)
    jobs = []
    for p in sorted(JOBS_DIR.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True)[:50]:
        jobs.append(_read_json(p, {}))
    return {"ok": True, "agents": agents, "jobs": jobs, "message": "Runner Agents are lightweight worker connectors. They do not require Docker Desktop or AI keys on the worker."}


def create_agent_job(agent_id: str, command: str, working_dir: str = "", job_type: str = "command", created_by: str = "gui", metadata: Optional[Dict[str, Any]] = None, timeout_seconds: int = 7200) -> Dict[str, Any]:
    _ensure()
    if not agent_id:
        return {"ok": False, "error": "agent_id is required."}
    if not command:
        return {"ok": False, "error": "command is required."}
    job_id = "job-" + secrets.token_hex(8)
    job = {
        "ok": True,
        "job_id": job_id,
        "agent_id": agent_id,
        "job_type": job_type or "command",
        "command": command,
        "working_dir": working_dir,
        "status": "pending",
        "created_by": created_by,
        "metadata": metadata or {},
        "timeout_seconds": timeout_seconds,
        "created_at_epoch_ms": _now_ms(),
        "message": "Job created. The selected Worker Agent will pick it up on its next poll.",
    }
    _write_json(JOBS_DIR / f"{job_id}.json", job)
    log_event("runner_agents", f"Created Worker Agent job {job_id} for {agent_id}", status="ok", progress=40)
    return job


def poll_agent_job(agent_id: str, token: str) -> Dict[str, Any]:
    valid = validate_token(token)
    if not valid.get("ok"):
        return valid
    if agent_id != valid.get("agent_id"):
        return {"ok": False, "error": "Token does not match this agent_id."}
    pending = []
    for p in sorted(JOBS_DIR.glob("*.json"), key=lambda x: x.stat().st_mtime):
        job = _read_json(p, {})
        if job.get("agent_id") == agent_id and job.get("status") == "pending":
            pending.append((p, job))
    if not pending:
        return {"ok": True, "job": None, "message": "No job for this agent."}
    path, job = pending[0]
    job["status"] = "running"
    job["started_at_epoch_ms"] = _now_ms()
    _write_json(path, job)
    log_event("runner_agents", f"Worker Agent {agent_id} picked up {job.get('job_id')}", status="running", progress=50)
    return {"ok": True, "job": job}


def complete_agent_job(payload: Dict[str, Any]) -> Dict[str, Any]:
    token = str(payload.get("token") or "").strip()
    agent_id = str(payload.get("agent_id") or "").strip()
    valid = validate_token(token)
    if not valid.get("ok"):
        return valid
    if agent_id != valid.get("agent_id"):
        return {"ok": False, "error": "Token does not match this agent_id."}
    job_id = str(payload.get("job_id") or "").strip()
    path = JOBS_DIR / f"{job_id}.json"
    job = _read_json(path, {})
    if not job:
        return {"ok": False, "error": f"Unknown job_id: {job_id}"}
    job.update({
        "status": payload.get("status") or "completed",
        "return_code": payload.get("return_code"),
        "stdout_tail": str(payload.get("stdout") or "")[-12000:],
        "stderr_tail": str(payload.get("stderr") or "")[-12000:],
        "completed_at_epoch_ms": _now_ms(),
        "artifact_notes": payload.get("artifact_notes") or "",
    })
    _write_json(path, job)
    log_event("runner_agents", f"Worker Agent job {job_id} completed with status {job.get('status')}", status=str(job.get("status")), progress=100)
    job_type = str(job.get("job_type") or "")
    if job_type.startswith("distributed_playwright_shard"):
        try:
            from qa_pipeline.core.distributed_history import handle_distributed_agent_completion
            handle_distributed_agent_completion(job)
        except Exception as exc:
            log_event("distributed_execution", f"Parallel RCA handoff failed for {job_id}: {type(exc).__name__}: {exc}", status="warning", progress=100)
    if job_type.startswith("agentic_nodehub_test"):
        try:
            from qa_pipeline.core.agentic_nodehub import handle_agentic_nodehub_test_completion
            handle_agentic_nodehub_test_completion(job)
        except Exception as exc:
            log_event("agentic_nodehub", f"Agentic node-hub handoff failed for {job_id}: {type(exc).__name__}: {exc}", status="warning", progress=100)
    return {"ok": True, "job": job}


AGENT_PY = r'''
from __future__ import annotations
import json, os, platform, subprocess, sys, time, urllib.request, urllib.parse
from pathlib import Path


def load_env(path: Path):
    if not path.exists():
        return {}
    data = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        data[k.strip()] = v.strip().strip('"').strip("'")
    return data


def post_json(url, payload, timeout=20):
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def get_json(url, timeout=20):
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def which(cmd):
    from shutil import which as _which
    return bool(_which(cmd))


def capabilities():
    return {
        "python": sys.version.split()[0],
        "node": which("node"),
        "npm": which("npm"),
        "npx": which("npx"),
        "git": which("git"),
        "codex": which("codex"),
        "java": which("java"),
        "maven": which("mvn"),
        "chrome_or_edge_expected": True,
    }


def main():
    here = Path(__file__).resolve().parent
    cfg = load_env(here / "agent.env")
    server = cfg.get("AIQA_CONTROL_PLANE_URL", "http://127.0.0.1:8080").rstrip("/")
    token = cfg.get("AIQA_AGENT_TOKEN", "")
    name = cfg.get("AIQA_AGENT_NAME", platform.node() or "Worker-Agent")
    agent_id = cfg.get("AIQA_AGENT_ID", "")
    workspace = cfg.get("AIQA_WORKSPACE_ROOT", str(here / "workspace"))
    poll_seconds = int(cfg.get("AIQA_POLL_INTERVAL_SECONDS", "5") or "5")
    if not token:
        print("ERROR: AIQA_AGENT_TOKEN is missing in agent.env")
        sys.exit(2)
    payload = {"token": token, "agent_id": agent_id, "agent_name": name, "hostname": platform.node(), "ip_address": cfg.get("AIQA_AGENT_IP", ""), "username": os.getenv("USERNAME") or os.getenv("USER") or "unknown", "workspace_root": workspace, "capabilities": capabilities()}
    reg = post_json(server + "/api/runner-agents/register", payload)
    if not reg.get("ok"):
        print("Registration failed:", json.dumps(reg, indent=2))
        sys.exit(3)
    agent_id = reg.get("agent_id") or agent_id
    print(f"AI QA Worker Runner Agent online: {name} / {agent_id}")
    print(f"Connected to: {server}")
    print(f"Workspace: {workspace}")
    while True:
        try:
            hb = {**payload, "agent_id": agent_id, "capabilities": capabilities()}
            post_json(server + "/api/runner-agents/heartbeat", hb, timeout=10)
            q = urllib.parse.urlencode({"agent_id": agent_id, "token": token})
            polled = get_json(server + "/api/runner-agents/poll?" + q, timeout=20)
            job = polled.get("job")
            if job:
                job_id = job.get("job_id")
                command = job.get("command")
                cwd = job.get("working_dir") or workspace
                Path(cwd).mkdir(parents=True, exist_ok=True)
                print(f"Running job {job_id}: {command} in {cwd}")
                proc = subprocess.run(command, shell=True, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=int(job.get("timeout_seconds") or 7200))
                status = "passed" if proc.returncode == 0 else "failed"
                post_json(server + "/api/runner-agents/job/complete", {"token": token, "agent_id": agent_id, "job_id": job_id, "status": status, "return_code": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr})
                print(f"Completed job {job_id}: {status}")
        except KeyboardInterrupt:
            print("Agent stopped by user.")
            break
        except Exception as exc:
            print("Agent loop warning:", type(exc).__name__, exc)
        time.sleep(max(2, poll_seconds))

if __name__ == "__main__":
    main()
'''


def build_agent_package(control_plane_url: str, token: str, agent_name: str = "", workspace_root: str = "D:\\AI_QA_WORKSPACE") -> Dict[str, Any]:
    _ensure()
    valid = validate_token(token)
    if not valid.get("ok"):
        return valid
    agent_name = agent_name or valid.get("agent_name") or "Worker-Agent"
    agent_id = valid.get("agent_id")
    package_dir = PACKAGES_DIR / f"WORKER_AGENT_PACKAGE_{agent_id}"
    if package_dir.exists():
        shutil.rmtree(package_dir)
    package_dir.mkdir(parents=True)
    (package_dir / "worker_agent.py").write_text((REPO_ROOT / "RUN_WORKER_AGENT.py").read_text(encoding="utf-8") if (REPO_ROOT / "RUN_WORKER_AGENT.py").exists() else AGENT_PY, encoding="utf-8")
    workspace_root_value = workspace_root or valid.get("workspace_root") or r"D:\AI_QA_WORKSPACE"
    env_text = f"""AIQA_CONTROL_PLANE_URL={control_plane_url.rstrip('/')}
AIQA_AGENT_TOKEN={token}
AIQA_AGENT_ID={agent_id}
AIQA_AGENT_NAME={agent_name}
AIQA_WORKSPACE_ROOT={workspace_root_value}
AIQA_POLL_INTERVAL_SECONDS=5
"""
    (package_dir / "agent.env").write_text(env_text, encoding="utf-8")
    (package_dir / "START_WORKER_AGENT_WINDOWS.cmd").write_text("@echo off\r\ncd /d %~dp0\r\npython worker_agent.py\r\npause\r\n", encoding="utf-8")
    (package_dir / "START_WORKER_AGENT_WINDOWS.ps1").write_text("Set-Location $PSScriptRoot\npython .\\worker_agent.py\n", encoding="utf-8")
    (package_dir / "START_WORKER_AGENT_MAC.sh").write_text("#!/usr/bin/env bash\nset -euo pipefail\ncd \"$(dirname \"$0\")\"\npython3 worker_agent.py --env agent.env\n", encoding="utf-8")
    (package_dir / "README_WORKER_AGENT.md").write_text(fr"""# AI QA Worker Runner Agent

Run this package **inside the worker VM/VDI** such as VM45 or VM135, not on the Central VM.

1. Extract this folder on the worker VM/VDI, for example `D:\\AI_QA_AGENT`.
2. Confirm `agent.env` points to the VM GUI/backend.
3. Run `START_WORKER_AGENT_WINDOWS.cmd`.
4. The agent will appear online in the VM GUI under Runner Agents.

Agent ID: `{agent_id}`
Agent Name: `{agent_name}`
Control Plane: `{control_plane_url}`
Workspace: `{workspace_root}`

## Central-source execution model

For enterprise VM execution, keep the Playwright framework and AI solution on the Central VM.
On each worker VM, the agent can execute tests from a Central VM shared path such as:

```text
\\10.20.5.10\AIQA_Frameworks\client-playwright-framework
```

In the GUI, select **Worker execution source = Central shared framework folder** and provide that UNC path.
The worker VM does not need a permanent framework copy; it only needs access to the share, Node.js, npm/npx and Playwright browsers.

The agent uses outbound polling, so the VM does not need to connect directly into the worker.
""", encoding="utf-8")
    zip_path = PACKAGES_DIR / f"WORKER_AGENT_PACKAGE_{agent_id}.zip"
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in package_dir.rglob("*"):
            zf.write(p, p.relative_to(package_dir.parent))
    return {"ok": True, "zip_path": str(zip_path), "agent_id": agent_id, "agent_name": agent_name, "message": "Worker Agent package created. Copy/download this ZIP into the worker VM/VDI and run START_WORKER_AGENT_WINDOWS.cmd there."}
