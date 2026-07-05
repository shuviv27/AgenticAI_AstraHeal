from __future__ import annotations

import os
import platform
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


WINDOWS = platform.system().lower().startswith("win")


def resolve_command(name: str) -> str | None:
    """Resolve a command in a cross-platform way.

    On Windows, npm/npx/pnpm/codex/ollama may be available as .cmd wrappers.
    Python subprocess with shell=False can fail when only the .cmd wrapper exists,
    so we resolve the exact executable path before calling subprocess.run().
    """
    candidates = [name]
    if WINDOWS:
        candidates = [name, f"{name}.cmd", f"{name}.exe", f"{name}.bat"]
    for candidate in candidates:
        path = shutil.which(candidate)
        if path:
            return path
    return None


@dataclass
class CommandResult:
    ok: bool
    command: str
    returncode: int | None
    stdout: str = ""
    stderr: str = ""
    error: str | None = None


def run_command(args: list[str], cwd: str | Path | None = None, timeout: int = 120, extra_env: dict[str, str] | None = None) -> CommandResult:
    if not args:
        return CommandResult(False, "", None, error="empty command")
    resolved = resolve_command(args[0])
    command_display = " ".join(args)
    if not resolved:
        return CommandResult(False, command_display, None, error=f"command not found: {args[0]}")
    final_args = [resolved, *args[1:]]
    try:
        proc = subprocess.run(
            final_args,
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            timeout=timeout,
            env={**os.environ.copy(), **(extra_env or {})},
            encoding="utf-8",
            errors="replace",
        )
        return CommandResult(
            ok=proc.returncode == 0,
            command=command_display,
            returncode=proc.returncode,
            stdout=proc.stdout,
            stderr=proc.stderr,
        )
    except Exception as exc:  # pragma: no cover - environment specific
        return CommandResult(False, command_display, None, error=str(exc))


def command_version(command: str) -> str:
    result = run_command([command, "--version"], timeout=10)
    if result.ok or result.returncode is not None:
        return (result.stdout.strip() or result.stderr.strip() or f"exit={result.returncode}")
    return f"not available: {result.error}"
