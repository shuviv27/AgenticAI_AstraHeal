#!/usr/bin/env python3
"""GUI-first bootstrapper for the Agentic AI QA project.

Run this single file before using the project. It prepares the Python virtual
environment if needed and opens the FastAPI GUI at http://127.0.0.1:8080.
Everything else—Docker stack, Codex/Ollama readiness, Playwright execution,
RCA, self-healing, failed-only rerun, and reports—is controlled from the GUI.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
DEFAULT_LOCAL_VENV_DIR = REPO_ROOT / ".venv"
CACHE_DIR = REPO_ROOT / ".qa-cache" / "gui-bootstrap"
REQ_FILE = REPO_ROOT / "requirements.txt"
APP_IMPORT = "qa_pipeline.gui.app:app"


def _print_header() -> None:
    print("=" * 78)
    print(" AstraHeal AI - Multi-Agent Automation Studio Launcher")
    print("=" * 78)
    print("This launcher starts the AstraHeal AI web GUI.")
    print("After GUI opens, control Docker, Codex/Ollama, Playwright execution,")
    print("distributed execution, RCA, self-healing, failed-only rerun and reports from the browser.")
    print("=" * 78)


def _path_text_len(path: Path) -> int:
    return len(str(path.resolve()))


def _safe_external_venv_dir() -> Path:
    """Return a short venv path to avoid Windows MAX_PATH issues.

    Some dependencies, especially lxml pulled by python-docx, contain deeply
    nested files. If the repo is extracted under a long Windows path, pip can
    fail with "No such file or directory" while installing wheel contents.
    Keeping the venv outside the extracted repo in a short user path avoids that.
    """
    override = os.environ.get("AIQA_VENV_DIR", "").strip()
    if override:
        return Path(override).expanduser()

    digest = hashlib.sha1(str(REPO_ROOT).encode("utf-8", errors="ignore")).hexdigest()[:10]
    base = os.environ.get("AIQA_VENV_BASE", "").strip()
    if base:
        root = Path(base).expanduser()
    elif os.name == "nt":
        # Short, user-writable, no admin requirement.
        root = Path(os.environ.get("USERPROFILE", str(REPO_ROOT))) / ".aiqa" / "venvs"
    else:
        root = Path(os.environ.get("HOME", str(REPO_ROOT))) / ".aiqa" / "venvs"
    return root / f"astraheal-{digest}"


def _selected_venv_dir() -> Path:
    # For Windows, prefer external short venv when the repo path is long or
    # contains characters that commonly appear in repeated ZIP extractions.
    if os.name == "nt":
        repo_len = _path_text_len(REPO_ROOT)
        if repo_len > 95 or "(" in str(REPO_ROOT) or ")" in str(REPO_ROOT):
            return _safe_external_venv_dir()
    return DEFAULT_LOCAL_VENV_DIR


def _venv_python(venv_dir: Path | None = None) -> Path:
    venv = venv_dir or _selected_venv_dir()
    if os.name == "nt":
        return venv / "Scripts" / "python.exe"
    return venv / "bin" / "python"


def _run(cmd: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    print("\n$ " + " ".join(cmd))
    return subprocess.run(cmd, cwd=str(REPO_ROOT), text=True, check=check)


def _ensure_venv(skip_install: bool = False, reinstall: bool = False) -> Path:
    venv_dir = _selected_venv_dir()
    py = _venv_python(venv_dir)
    if not py.exists():
        print(f"\nCreating Python virtual environment: {venv_dir}")
        if venv_dir != DEFAULT_LOCAL_VENV_DIR:
            print("Using short external venv path to avoid Windows lxml/MAX_PATH install issues.")
            print("Override with AIQA_VENV_DIR if your enterprise policy requires another location.")
        _run([sys.executable, "-m", "venv", str(venv_dir)])

    if skip_install:
        return py

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    marker_name = "requirements." + hashlib.sha1(str(venv_dir).encode("utf-8", errors="ignore")).hexdigest()[:10] + ".installed.ok"
    marker = CACHE_DIR / marker_name
    needs_install = reinstall or not marker.exists()
    if marker.exists() and REQ_FILE.exists():
        try:
            needs_install = needs_install or marker.stat().st_mtime < REQ_FILE.stat().st_mtime
        except OSError:
            needs_install = True

    if needs_install:
        print("\nInstalling/updating Python dependencies required by the GUI...")
        _run([str(py), "-m", "pip", "install", "--upgrade", "pip"])
        if REQ_FILE.exists():
            _run([str(py), "-m", "pip", "install", "--prefer-binary", "-r", str(REQ_FILE)])
        else:
            _run([str(py), "-m", "pip", "install", "fastapi", "uvicorn", "python-multipart", "pydantic"])
        marker.write_text(str(time.time()), encoding="utf-8")

    return py


def _validate_gui_import(py: Path, env: dict[str, str]) -> bool:
    """Fail fast with a readable message before Uvicorn emits a long traceback.

    This catches Python 3.11 syntax/import errors in newly added modules, such as
    f-string expressions that contain backslashes. It does not change any runtime
    feature; it only provides a clearer startup failure message.
    """
    check = subprocess.run(
        [str(py), "-W", "error::SyntaxWarning", "-c", "import qa_pipeline.gui.app as app; print('APP_IMPORT_OK')"],
        cwd=str(REPO_ROOT),
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    if check.returncode == 0:
        return True

    print("\nAstraHeal AI startup validation failed before launching the GUI.")
    print("This usually means a Python syntax/import issue exists in the application code.")
    print("Most common VM/Python 3.11 issue: f-string expression part cannot include a backslash.")
    print("\nAction:")
    print("  1. Use the latest fixed build.")
    print("  2. If you modified files manually, run: python -W error::SyntaxWarning -m compileall -q qa_pipeline RUN_GUI_FIRST.py")
    print("  3. Share the first file/line from the error below if it still fails.")
    if check.stdout.strip():
        print("\nValidation output:")
        print(check.stdout[-4000:])
    if check.stderr.strip():
        print("\nValidation error:")
        print(check.stderr[-8000:])
    return False


def _port_is_busy(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex((host, port)) == 0


def _open_browser_later(url: str, delay: float = 1.8) -> None:
    def _open() -> None:
        time.sleep(delay)
        try:
            webbrowser.open(url)
        except Exception:
            pass

    threading.Thread(target=_open, daemon=True).start()


def _guess_lan_ips() -> list[str]:
    """Return likely LAN IP addresses for user-friendly startup messages."""
    ips: list[str] = []
    try:
        host_name = socket.gethostname()
        for item in socket.getaddrinfo(host_name, None, family=socket.AF_INET):
            ip = item[4][0]
            if ip and not ip.startswith("127.") and ip not in ips:
                ips.append(ip)
    except Exception:
        pass

    # UDP connect does not send packets; it only asks the OS which local IP would be used.
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            ip = sock.getsockname()[0]
            if ip and not ip.startswith("127.") and ip not in ips:
                ips.append(ip)
    except Exception:
        pass

    return ips


def _display_urls(host: str, port: int) -> tuple[str, list[str]]:
    """Convert bind host into browser URLs. 0.0.0.0 is not a browser URL."""
    if host in {"0.0.0.0", "::", ""}:
        local_url = f"http://127.0.0.1:{port}"
        lan_urls = [f"http://{ip}:{port}" for ip in _guess_lan_ips()]
        return local_url, lan_urls
    return f"http://{host}:{port}", []


def main() -> int:
    parser = argparse.ArgumentParser(description="Start the AstraHeal AI web GUI on 127.0.0.1:8080.")
    parser.add_argument("--host", default="127.0.0.1", help="GUI bind host. Default: 127.0.0.1")
    parser.add_argument("--port", type=int, default=8080, help="GUI port. Default: 8080")
    parser.add_argument("--no-browser", action="store_true", help="Do not open the browser automatically.")
    parser.add_argument("--skip-install", action="store_true", help="Skip dependency install and use existing .venv.")
    parser.add_argument("--reinstall", action="store_true", help="Force reinstall requirements before launch.")
    args = parser.parse_args()

    _print_header()
    local_url, lan_urls = _display_urls(args.host, args.port)

    # For a bind-all address, test local loopback for port conflicts.
    port_check_host = "127.0.0.1" if args.host in {"0.0.0.0", "::", ""} else args.host
    if _port_is_busy(port_check_host, args.port):
        print(f"\nGUI port is already in use. Open existing AstraHeal AI session: {local_url}/astraheal-ai")
        if lan_urls:
            print("From another VM/VDI, open one of these URLs if firewall allows it:")
            for item in lan_urls:
                print(f"  {item}/astraheal-ai")
        if not args.no_browser:
            webbrowser.open(local_url + "/astraheal-ai")
        return 0

    py = _ensure_venv(skip_install=args.skip_install, reinstall=args.reinstall)

    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    env.setdefault("PYTHONUTF8", "1")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("AI_QA_GUI_FIRST", "true")

    if not _validate_gui_import(py, env):
        return 1

    print("\nStarting GUI...")
    print(f"Open AstraHeal AI on this VM: {local_url}/astraheal-ai")
    if args.host in {"0.0.0.0", "::", ""}:
        print("Note: 0.0.0.0 is only the server bind address. Do not open http://0.0.0.0:8080 in a browser.")
        if lan_urls:
            print("Open from another VM/VDI using the Central VM IP, for example:")
            for item in lan_urls:
                print(f"  {item}/astraheal-ai")
        else:
            print("Open from another VM/VDI using: http://<Central-VM-IP>:8080/astraheal-ai")
    print("\nNext steps inside GUI:")
    print("  1. Verify prerequisites")
    print("  2. Start mandatory Docker stack")
    print("  3. Connect Codex/Ollama/OpenAI/DeepSeek")
    print("  4. Use AstraHeal AI for framework learning, distributed execution, RCA and self-healing")
    print("\nPress CTRL+C here to stop the GUI server.\n")

    if not args.no_browser:
        _open_browser_later(local_url + "/astraheal-ai")

    cmd = [str(py), "-m", "uvicorn", APP_IMPORT, "--host", args.host, "--port", str(args.port)]
    try:
        return subprocess.call(cmd, cwd=str(REPO_ROOT), env=env)
    except KeyboardInterrupt:
        print("\nGUI stopped.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
