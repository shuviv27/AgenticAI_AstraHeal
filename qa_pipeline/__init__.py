"""Python Agentic AI QA Pipeline.

Environment loading is intentionally centralized here so CLI and GUI commands
work the same on Windows, macOS, local terminals, VS Code, and Docker.
"""
from __future__ import annotations

from pathlib import Path

try:
    from dotenv import load_dotenv  # type: ignore
    _root = Path(__file__).resolve().parents[1]
    load_dotenv(_root / ".env")
    load_dotenv(_root / ".env.agents")
except Exception:
    # dotenv is optional during source inspection; runtime requirements install it.
    pass

__all__ = []
