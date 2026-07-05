@echo off
cd /d %~dp0
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0START_GUI_VM_WITH_WORKERS_WINDOWS.ps1"
pause
