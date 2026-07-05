# Windows GUI Startup Dependency Fix

## Root cause

The GUI failed because it was launched with the current Python from PATH, which in your case was Anaconda Python:

```text
WARNING: .venv not found. Using current Python from PATH.
```

That Python environment did not have `python-multipart` installed. FastAPI requires `python-multipart` for endpoints that use `Form(...)`, `File(...)`, or `UploadFile`, such as Project Setup and Requirement Upload.

## Fix in this build

`START_GUI_WINDOWS.cmd` now:

1. Creates `.venv` automatically if missing.
2. Activates `.venv`.
3. Installs `requirements.txt` and the editable project if required.
4. Verifies `fastapi`, `uvicorn`, `multipart`, and `qa_pipeline.gui.app` before starting the GUI.
5. Avoids accidental use of Anaconda/global Python.

## Recommended command

From repo root:

```powershell
.
START_GUI_WINDOWS.cmd
```

or explicitly:

```powershell
INSTALL_GUI_DEPS_WINDOWS.cmd
START_GUI_WINDOWS.cmd
```

## Manual fallback

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install -e .
python -m qa_pipeline.cli serve-gui --host 127.0.0.1 --port 8080
```

## Syntax warning fixed

The Python `SyntaxWarning: invalid escape sequence '\s'` was caused by embedded TypeScript code inside a Python triple-quoted string. It was harmless at runtime, but it has been fixed so the console is clean.
