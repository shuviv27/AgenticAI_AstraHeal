# AstraHeal AI VM Startup Stability Guard

This build fixes an import-time Python syntax error in the MCP readiness preflight module.

## Root cause

Python 3.11+ does not allow a backslash inside an f-string expression. The previous MCP preflight enhancement had this pattern while building the Codex prompt:

```text
f"""... {some_expression + '\n' + other_expression} ..."""
```

That is why Uvicorn failed before the GUI could launch.

## Fix applied

The expression is now prepared before the f-string:

```python
build_output_tail = stdout_tail + chr(10) + stderr_tail
build_output_block = json.dumps(build_output_tail, ensure_ascii=False)[:12000]
prompt = f"""
Build output tail:
{build_output_block}
""".strip()
```

## Added guard

Before Uvicorn starts, `RUN_GUI_FIRST.py` now imports the GUI app in a small validation step. If a future import-time syntax issue exists, the launcher prints a readable error instead of a long Uvicorn traceback.

Manual validation command:

```powershell
python scripts\validate_vm_startup.py
```

Expected final line:

```text
VM_STARTUP_VALIDATION_OK
```

## Existing features

This fix does not change execution logic, worker routing, MCP preflight behavior, AI provider behavior, RCA, self-healing, reports, or AstraHeal AI branding. It only fixes startup safety and adds validation.
