from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import unicodedata

from qa_pipeline.core.commands import resolve_command, run_command


@dataclass
class CodexCliResult:
    ok: bool
    stdout: str
    stderr: str
    exit_code: int


def _safe_prompt(prompt: str) -> str:
    """Normalize prompt text before passing it to CLI stdin.

    Windows terminals commonly default to cp1252. Requirements copied from PDFs/SRS
    often contain non-breaking hyphen, smart quotes, bullet characters, and other
    Unicode symbols. Codex itself can handle UTF-8, but Python subprocess pipes must
    be forced to UTF-8 to avoid UnicodeEncodeError before Codex receives the prompt.
    """
    if prompt is None:
        return ""
    prompt = unicodedata.normalize("NFKC", str(prompt))
    replacements = {
        "\u2011": "-",  # non-breaking hyphen
        "\u2010": "-",
        "\u2012": "-",
        "\u2013": "-",
        "\u2014": "-",
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u2022": "-",
        "\u00a0": " ",
    }
    for src, dst in replacements.items():
        prompt = prompt.replace(src, dst)
    return prompt


class CodexCliProvider:
    """Wrapper for locally-authenticated Codex CLI.

    This wrapper intentionally does not accept an API key, username, or password.
    Developers authenticate once with `codex login`; Codex stores the local session.
    The pipeline then invokes `codex exec` for repository-aware code assistance.
    """

    def __init__(self, repo_root: Path, timeout_seconds: int = 600) -> None:
        self.repo_root = repo_root
        self.timeout_seconds = timeout_seconds

    def is_available(self) -> bool:
        return resolve_command("codex") is not None

    def login_status(self) -> CodexCliResult:
        if not self.is_available():
            return CodexCliResult(False, "", "Codex CLI not found. Install it, then run: codex login", 127)
        result = run_command(["codex", "login", "status"], cwd=self.repo_root, timeout=20)
        return CodexCliResult(result.ok, result.stdout, result.stderr or result.error or "", result.returncode or 0)

    def run(self, prompt: str) -> CodexCliResult:
        if not self.is_available():
            return CodexCliResult(False, "", "Codex CLI not found. Install it, then run: codex login", 127)

        codex = resolve_command("codex")
        assert codex is not None
        env = os.environ.copy()
        env.setdefault("PYTHONUTF8", "1")
        env.setdefault("PYTHONIOENCODING", "utf-8")
        env.setdefault("LC_ALL", "C.UTF-8")
        env.setdefault("LANG", "C.UTF-8")

        try:
            result = run_command(
                [codex, "exec", "--skip-git-repo-check", "--sandbox", "workspace-write", "-"],
                cwd=self.repo_root, timeout=self.timeout_seconds, extra_env=env,
                input_text=_safe_prompt(prompt),
            )
            if result.timed_out:
                return CodexCliResult(False, result.stdout or "", f"Codex CLI timed out after {self.timeout_seconds}s", 124)
            return CodexCliResult(result.ok, result.stdout or "", result.stderr or result.error or "", result.returncode or (0 if result.ok else 1))
        except UnicodeError as exc:
            return CodexCliResult(False, "", f"Codex CLI Unicode/encoding error: {exc}", 1)
        except FileNotFoundError:
            return CodexCliResult(False, "", "Codex CLI executable not found in PATH", 127)
        except Exception as exc:
            return CodexCliResult(False, "", f"Codex CLI execution failed: {type(exc).__name__}: {exc}", 1)
