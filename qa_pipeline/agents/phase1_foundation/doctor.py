from __future__ import annotations

from pathlib import Path

from qa_pipeline.core.commands import command_version, resolve_command
from qa_pipeline.core.paths import REPO_ROOT, GENERATED_PLAYWRIGHT_DIR, TESTCASES_DIR, ensure_dirs


def run_doctor() -> dict:
    ensure_dirs()
    result = {
        "repo_root": str(REPO_ROOT),
        "generated_playwright_exists": GENERATED_PLAYWRIGHT_DIR.exists(),
        "testcases_exists": TESTCASES_DIR.exists(),
        "python": command_version("python"),
        "node": command_version("node"),
        "npm": command_version("npm"),
        "npx": command_version("npx"),
        "codex_cli": "available" if resolve_command("codex") else "not found; optional unless provider=codex",
        "ollama": "available" if resolve_command("ollama") else "not found; optional unless provider=ollama",
    }
    return result
