#!/usr/bin/env python3
"""AstraHeal AI lightweight worker agent.

Run this file on worker machines such as VM45 or VM135. The worker does not
need AstraHeal AI GUI, Codex login, OpenAI key, or DeepSeek key. It needs only
Python, Node.js/npm/npx, Playwright browsers, AUT access, and access to the
framework path that Central VM assigns.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path
from shutil import which as _which

ROOT = Path(__file__).resolve().parent


def _load_env_file(path: Path) -> dict[str, str]:
    data: dict[str, str] = {}
    if not path.exists():
        return data
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        data[key.strip()] = value.strip().strip('"').strip("'")
    return data


def _post_json(url: str, payload: dict, timeout: int = 20) -> dict:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _get_json(url: str, timeout: int = 20) -> dict:
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _has(cmd: str) -> bool:
    return bool(_which(cmd))


def _version(cmd: list[str]) -> str:
    try:
        p = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=20, check=False)
        return (p.stdout or "").strip().splitlines()[0] if (p.stdout or "").strip() else "not detected"
    except Exception:
        return "not detected"


def _capabilities(cfg: dict[str, str]) -> dict:
    framework_path = cfg.get("AIQA_FRAMEWORK_PATH") or cfg.get("AIQA_WORKSPACE_ROOT") or ""
    return {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "node_available": _has("node"),
        "node_version": _version(["node", "-v"]),
        "npm_available": _has("npm"),
        "npm_version": _version(["npm", "-v"]),
        "npx_available": _has("npx"),
        "git_available": _has("git"),
        "framework_path": framework_path,
        "framework_path_exists": bool(framework_path and Path(framework_path).exists()),
        "browser_execution_role": True,
        "ai_provider_required_on_worker": False,
    }


def _print_start_banner(cfg: dict[str, str]) -> None:
    print("=" * 78)
    print(" AstraHeal AI Worker Agent")
    print("=" * 78)
    print(f"Agent name      : {cfg.get('AIQA_AGENT_NAME', platform.node() or 'worker-agent')}")
    print(f"Central URL     : {cfg.get('AIQA_CONTROL_PLANE_URL', 'http://127.0.0.1:8080')}")
    print(f"Framework path  : {cfg.get('AIQA_FRAMEWORK_PATH') or cfg.get('AIQA_WORKSPACE_ROOT') or '(assigned by central jobs)'}")
    print("Worker AI keys  : Not required. AI keys stay on Central VM.")
    print("Worker purpose  : Browser execution + logs/screenshots/traces/MCP evidence.")
    print("=" * 78)


def main() -> int:
    parser = argparse.ArgumentParser(description="Start AstraHeal AI worker agent.")
    parser.add_argument("--env", default="", help="Path to worker env file. Default: worker-agent.env, then agent.env")
    parser.add_argument("--once", action="store_true", help="Register and poll once, useful for smoke testing.")
    args = parser.parse_args()

    env_file = Path(args.env).expanduser() if args.env else None
    if env_file is None:
        env_file = ROOT / "worker-agent.env"
        if not env_file.exists() and (ROOT / "agent.env").exists():
            env_file = ROOT / "agent.env"

    cfg = {**os.environ, **_load_env_file(env_file)}
    _print_start_banner(cfg)

    server = (cfg.get("AIQA_CONTROL_PLANE_URL") or "http://127.0.0.1:8080").rstrip("/")
    token = (cfg.get("AIQA_AGENT_TOKEN") or "").strip()
    agent_id = (cfg.get("AIQA_AGENT_ID") or "").strip()
    name = cfg.get("AIQA_AGENT_NAME") or platform.node() or "worker-agent"
    framework_path = cfg.get("AIQA_FRAMEWORK_PATH") or cfg.get("AIQA_WORKSPACE_ROOT") or str(ROOT / "workspace")
    poll_seconds = int(cfg.get("AIQA_POLL_INTERVAL_SECONDS") or "5")

    if not token or "<" in token:
        print("ERROR: AIQA_AGENT_TOKEN is missing or still has placeholder value.")
        print("Create token from Central VM GUI, then put it in worker-agent.env.")
        return 2

    if not _has("node") or not _has("npm") or not _has("npx"):
        print("WARNING: Node/npm/npx not fully available. Playwright test jobs may fail on this worker.")

    payload = {
        "token": token,
        "agent_id": agent_id,
        "agent_name": name,
        "hostname": platform.node(),
        "ip_address": cfg.get("AIQA_AGENT_IP", ""),
        "username": os.getenv("USERNAME") or os.getenv("USER") or "unknown",
        "workspace_root": framework_path,
        "capabilities": _capabilities(cfg),
    }

    try:
        reg = _post_json(server + "/api/runner-agents/register", payload)
    except Exception as exc:
        print(f"ERROR: Could not connect/register to Central VM: {type(exc).__name__}: {exc}")
        print("Check AIQA_CONTROL_PLANE_URL, firewall, and Central VM GUI status.")
        return 3

    if not reg.get("ok"):
        print("ERROR: Registration rejected by Central VM:")
        print(json.dumps(reg, indent=2))
        return 4

    agent_id = reg.get("agent_id") or agent_id
    print(f"Worker online: {name} / {agent_id}")
    print("Keep this terminal open while distributed execution is running.")

    while True:
        try:
            hb = {**payload, "agent_id": agent_id, "capabilities": _capabilities(cfg)}
            _post_json(server + "/api/runner-agents/heartbeat", hb, timeout=10)
            q = urllib.parse.urlencode({"agent_id": agent_id, "token": token})
            polled = _get_json(server + "/api/runner-agents/poll?" + q, timeout=20)
            job = polled.get("job")
            if job:
                job_id = job.get("job_id")
                command = job.get("command")
                cwd = job.get("working_dir") or framework_path
                if cwd and not Path(cwd).exists():
                    print(f"WARNING: job working_dir does not exist on worker: {cwd}")
                print(f"\nRunning job {job_id}")
                print(f"Working dir: {cwd}")
                print(f"Command    : {command}")
                run_command = command
                run_cwd = cwd if cwd else None
                # Windows cmd.exe cannot reliably use a UNC share as current directory.
                # For central-shared-framework mode, map the UNC temporarily using pushd.
                if os.name == "nt" and cwd and str(cwd).startswith("\\"):
                    run_command = f'pushd "{cwd}" && {command} & popd'
                    run_cwd = None
                proc = subprocess.run(
                    run_command,
                    shell=True,
                    cwd=run_cwd,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=int(job.get("timeout_seconds") or 7200),
                )
                status = "passed" if proc.returncode == 0 else "failed"
                _post_json(server + "/api/runner-agents/job/complete", {
                    "token": token,
                    "agent_id": agent_id,
                    "job_id": job_id,
                    "status": status,
                    "return_code": proc.returncode,
                    "stdout": proc.stdout,
                    "stderr": proc.stderr,
                })
                print(f"Completed job {job_id}: {status} / return_code={proc.returncode}")
            if args.once:
                print("Smoke test completed. Use without --once for continuous worker mode.")
                return 0
        except KeyboardInterrupt:
            print("Worker agent stopped by user.")
            return 0
        except subprocess.TimeoutExpired as exc:
            print("Job timed out:", exc)
        except Exception as exc:
            print("Agent loop warning:", type(exc).__name__, exc)
        time.sleep(max(2, poll_seconds))


if __name__ == "__main__":
    raise SystemExit(main())
