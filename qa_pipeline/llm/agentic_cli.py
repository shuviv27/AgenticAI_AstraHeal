from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class AgenticCliStatus:
    ok: bool
    provider: str
    command: str
    available: bool
    authenticated_hint: bool
    stdout: str = ""
    stderr: str = ""
    message: str = ""


def _run(cmd: list[str], cwd: Path | None = None, timeout: int = 20) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(cmd, cwd=str(cwd) if cwd else None, text=True, capture_output=True, timeout=timeout)
        return proc.returncode, proc.stdout or "", proc.stderr or ""
    except Exception as exc:
        return 999, "", f"{type(exc).__name__}: {exc}"


class AgenticCliProvider:
    """Readiness wrapper for optional external coding CLIs.

    AstraHeal treats Claude Code and GitHub Copilot CLI as optional second-opinion
    coding assistants.  They can be used for fix-plan guidance in approved
    workspaces, but the default direct patching path remains Codex plus
    deterministic guardrail fallbacks until the organization explicitly enables
    these CLIs in its security policy.
    """

    def __init__(self, provider: str, root: str | Path | None = None) -> None:
        self.provider = (provider or "").strip().lower().replace("-", "_")
        self.root = Path(root or ".").resolve()

    @property
    def command(self) -> str:
        if self.provider in {"claude", "claude_cli", "claude_code"}:
            return "claude"
        if self.provider in {"github_copilot", "copilot", "copilot_cli"}:
            return "gh"
        return self.provider

    def status(self) -> AgenticCliStatus:
        cmd = self.command
        available = shutil.which(cmd) is not None
        if not available:
            return AgenticCliStatus(False, self.provider, cmd, False, False, message=f"{cmd} CLI was not found on PATH.")
        if cmd == "claude":
            code, out, err = _run([cmd, "--version"], self.root, timeout=15)
            ok = code == 0
            return AgenticCliStatus(ok, "claude", cmd, True, ok, out[-1500:], err[-1500:], "Claude Code CLI is available." if ok else "Claude CLI exists but version/status check failed.")
        if cmd == "gh":
            # GitHub Copilot CLI is exposed through the GitHub CLI extension/subcommands.
            code_v, out_v, err_v = _run([cmd, "--version"], self.root, timeout=15)
            code_c, out_c, err_c = _run([cmd, "copilot", "--help"], self.root, timeout=15)
            ok = code_v == 0 and code_c == 0
            return AgenticCliStatus(ok, "github_copilot", cmd, True, ok, (out_v + "\n" + out_c)[-1500:], (err_v + "\n" + err_c)[-1500:], "GitHub CLI with Copilot CLI is available." if ok else "GitHub CLI exists but Copilot CLI was not available/authenticated.")
        code, out, err = _run([cmd, "--version"], self.root, timeout=15)
        return AgenticCliStatus(code == 0, self.provider, cmd, True, code == 0, out[-1500:], err[-1500:], f"{cmd} CLI status checked.")
