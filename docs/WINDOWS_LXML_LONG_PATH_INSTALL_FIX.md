# Windows lxml / python-docx install fix

## Problem

On Windows VMs, pip may fail while installing `lxml`, which is pulled by `python-docx`, with an error similar to:

```text
ERROR: Could not install packages due to an OSError: [Errno 2] No such file or directory: ...lxml\isoschematron\resources\xsl\iso-schematron-xslt1\iso_schematron_skeleton_for_xslt1.xsl
```

This is usually caused by a long extraction path, for example:

```text
C:\AIAutomationModulesRepo\MasterSlaveFinalLatest\TestFinalNew\TEST\AdvancedAIAutomation_...(1)\.venv\Lib\site-packages\...
```

`lxml` contains deeply nested files. When `.venv` is created inside a long extracted ZIP folder, Windows path limits can break wheel installation.

## Fix in this build

`RUN_GUI_FIRST.py` now automatically detects long Windows repo paths and creates the Python virtual environment in a short user-writable location instead of inside the extracted repo:

```text
%USERPROFILE%\.aiqa\venvs\astraheal-<hash>
```

This keeps the solution repo unchanged while avoiding lxml/MAX_PATH install failures.

## Optional override

To force a specific short venv location:

```powershell
setx AIQA_VENV_DIR "C:\AIQA_VENVS\astraheal-main"
```

Then reopen PowerShell and run the GUI launcher again.

## Recommended extraction path

Even with this fix, keep the repo path short when possible:

```text
C:\AstraHealAI
D:\AstraHealAI
```

Avoid repeated extracted folder names such as:

```text
AdvancedAIAutomation_...(1)
```
