# Windows Execution Policy Fix

If PowerShell shows:

```text
START_GUI_WINDOWS.ps1 cannot be loaded. The file is not digitally signed.
```

this is a Windows PowerShell security policy issue, not a framework issue.

## Recommended launcher

Use the CMD launcher, which does not require running a PowerShell script:

```powershell
.\START_GUI_WINDOWS.cmd
```

## Alternative: run PowerShell with process-level bypass

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\START_GUI_WINDOWS.ps1
```

## Alternative: allow scripts only for the current terminal

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
.\START_GUI_WINDOWS.ps1
```

## Optional: unblock downloaded scripts

```powershell
.\UNBLOCK_WINDOWS_FILES.cmd
```

This removes the Windows downloaded-file blocking marker from PowerShell scripts in this extracted folder.
