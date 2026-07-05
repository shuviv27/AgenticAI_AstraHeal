#!/usr/bin/env python3
"""AstraHeal AI VM startup validation gate.

Run this before packaging or before starting the GUI on a VM:

    python scripts/validate_vm_startup.py

It catches import-time failures such as Python 3.11/3.12/3.13 f-string
syntax issues before Uvicorn starts.
"""
from __future__ import annotations

import compileall
import importlib
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

print("AstraHeal AI VM startup validation")
print(f"Repo: {ROOT}")
print(f"Python: {sys.version.split()[0]}")



def _scan_py311_fstring_backslash(root: Path) -> list[tuple[str, int, str]]:
    """Conservative scanner for Python 3.11-incompatible f-string expressions.

    Python 3.12+ relaxed f-string parsing, so compileall on a newer packaging
    machine may not catch a syntax error that a Python 3.11 VM will reject.
    """
    issues: list[tuple[str, int, str]] = []

    def scan(content: str, path: Path) -> None:
        i = 0
        n = len(content)
        while i < n:
            if content[i] in "fFrRbuUB":
                start = i
                prefix = ""
                while i < n and content[i] in "fFrRbuUB":
                    prefix += content[i]
                    i += 1
                if "f" not in prefix.lower() or i >= n or content[i] not in ('"', "'"):
                    i = start + 1
                    continue
                quote = content[i]
                triple = content[i:i + 3] == quote * 3
                qlen = 3 if triple else 1
                i += qlen
                body_start = i
                while i < n:
                    if not triple and content[i] == "\\":
                        i += 2
                        continue
                    if content[i:i + qlen] == quote * qlen:
                        body = content[body_start:i]
                        j = 0
                        depth = 0
                        expr = ""
                        expr_start = 0
                        while j < len(body):
                            ch = body[j]
                            if ch == "{":
                                if j + 1 < len(body) and body[j + 1] == "{":
                                    j += 2
                                    continue
                                if depth == 0:
                                    expr = ""
                                    expr_start = j
                                else:
                                    expr += ch
                                depth += 1
                                j += 1
                                continue
                            if ch == "}":
                                if j + 1 < len(body) and body[j + 1] == "}":
                                    j += 2
                                    continue
                                depth -= 1
                                if depth == 0:
                                    if "\\" in expr:
                                        line = content[:body_start + expr_start].count("\n") + 1
                                        issues.append((str(path.relative_to(root)), line, expr.strip()[:160].replace("\n", "\\n")))
                                    expr = ""
                                elif depth > 0:
                                    expr += ch
                                j += 1
                                continue
                            if depth > 0:
                                expr += ch
                            j += 1
                        i += qlen
                        break
                    i += 1
            else:
                i += 1

    for path in root.rglob("*.py"):
        if any(part in {".venv", "node_modules", "__pycache__"} for part in path.parts):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            text = path.read_text(encoding="latin1")
        scan(text, path)
    return issues

print("\n1. Scanning Python 3.11 f-string compatibility...")
issues = _scan_py311_fstring_backslash(ROOT)
if issues:
    print("FAILED: Python 3.11-incompatible f-string backslash expression found.")
    for path, line, expr in issues:
        print(f"{path}:{line}: {expr}")
    sys.exit(1)
print("OK: Python 3.11 f-string compatibility scan passed.")

print("\n2. Compiling Python files with SyntaxWarning treated as an error...")
ok = compileall.compile_dir(str(ROOT / "qa_pipeline"), quiet=1, force=True)
ok = compileall.compile_file(str(ROOT / "RUN_GUI_FIRST.py"), quiet=1, force=True) and ok
if not ok:
    print("FAILED: Python compile validation failed.")
    sys.exit(1)
print("OK: Python compile validation passed.")

print("\n3. Importing FastAPI GUI app...")
try:
    importlib.import_module("qa_pipeline.gui.app")
except Exception as exc:
    print("FAILED: GUI app import failed.")
    print(f"{type(exc).__name__}: {exc}")
    raise
print("OK: GUI app import passed.")

print("\nVM_STARTUP_VALIDATION_OK")
