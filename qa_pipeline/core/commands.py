from __future__ import annotations

import os
import platform
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from qa_pipeline.core.operation_control import (
    OperationCancelled,
    check_cancelled,
    popen_process_group_kwargs,
    register_process,
    unregister_process,
)


WINDOWS = platform.system().lower().startswith("win")


def resolve_command(name: str) -> str | None:
    """Resolve a command in a cross-platform way.

    On Windows, npm/npx/pnpm/codex/ollama may be available as .cmd wrappers.
    Python subprocess with shell=False can fail when only the .cmd wrapper exists,
    so we resolve the exact executable path before launching the managed process.
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
    timed_out: bool = False
    cancelled: bool = False


def run_command(
    args: list[str],
    cwd: str | Path | None = None,
    timeout: int = 120,
    extra_env: dict[str, str] | None = None,
    input_text: str | None = None,
) -> CommandResult:
    """Run a command with timeout and user-cancellation support.

    Every child process is registered against the current AstraHeal operation.
    The GUI Stop button can therefore terminate npm, npx, Playwright, Codex and
    their child browser processes rather than merely closing the HTTP request.
    """
    if not args:
        return CommandResult(False, "", None, error="empty command")
    resolved = resolve_command(args[0])
    command_display = " ".join(str(x) for x in args)
    if not resolved:
        return CommandResult(False, command_display, None, error=f"command not found: {args[0]}")
    final_args = [resolved, *[str(x) for x in args[1:]]]
    started = time.time()
    proc: subprocess.Popen[str] | None = None
    try:
        check_cancelled()
        proc = subprocess.Popen(
            final_args,
            cwd=str(cwd) if cwd else None,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.PIPE if input_text is not None else subprocess.DEVNULL,
            text=True,
            env={**os.environ.copy(), **(extra_env or {})},
            encoding="utf-8",
            errors="replace",
            **popen_process_group_kwargs(),
        )
        register_process(proc)
        pending_input = input_text
        while True:
            check_cancelled()
            remaining = max(0.05, float(timeout) - (time.time() - started))
            if remaining <= 0.05 and time.time() - started >= float(timeout):
                from qa_pipeline.core.operation_control import terminate_process_tree

                terminate_process_tree(proc)
                stdout, stderr = proc.communicate(timeout=5)
                return CommandResult(
                    False,
                    command_display,
                    proc.returncode,
                    stdout=stdout or "",
                    stderr=stderr or "",
                    error=f"command timed out after {timeout} seconds",
                    timed_out=True,
                )
            try:
                stdout, stderr = proc.communicate(input=pending_input, timeout=min(0.25, remaining))
                # A cancellation request can terminate the process while
                # communicate() is waiting. Re-check before classifying that
                # terminated process as a normal command failure/completion.
                check_cancelled()
                return CommandResult(
                    ok=proc.returncode == 0,
                    command=command_display,
                    returncode=proc.returncode,
                    stdout=stdout or "",
                    stderr=stderr or "",
                )
            except subprocess.TimeoutExpired:
                pending_input = None
                continue
    except OperationCancelled:
        if proc is not None:
            from qa_pipeline.core.operation_control import terminate_process_tree

            terminate_process_tree(proc)
        raise
    except Exception as exc:  # pragma: no cover - environment specific
        return CommandResult(False, command_display, None, error=str(exc))
    finally:
        if proc is not None:
            unregister_process(proc)


def command_version(command: str) -> str:
    result = run_command([command, "--version"], timeout=10)
    if result.ok or result.returncode is not None:
        return result.stdout.strip() or result.stderr.strip() or f"exit={result.returncode}"
    return f"not available: {result.error}"
