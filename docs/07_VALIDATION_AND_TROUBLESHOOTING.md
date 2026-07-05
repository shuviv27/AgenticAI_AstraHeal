# Validation and troubleshooting

## VM startup validation

```powershell
python scriptsalidate_vm_startup.py
```

Expected:

```text
VM_STARTUP_VALIDATION_OK
```

## Central VM port

```powershell
Test-NetConnection 127.0.0.1 -Port 8080
```

From worker:

```powershell
Test-NetConnection 10.252.41.177 -Port 8080
```

## Windows long-path / lxml issue

Use short extraction path:

```text
C:\AstraHealAI
```

Optional short venv:

```powershell
setx AIQA_VENV_DIR "C:\AIQA_VENVSstraheal-main"
```

Close and reopen PowerShell.

## Python 3.11 safety

This build includes startup validation to catch import-time syntax errors before Uvicorn starts.

## Worker does not appear online

Check:

1. `AIQA_CONTROL_PLANE_URL` points to VM177.
2. `AIQA_AGENT_TOKEN` is copied correctly.
3. VM177 GUI is running.
4. Firewall allows port 8080.
5. Worker can run `Test-NetConnection 10.252.41.177 -Port 8080`.
