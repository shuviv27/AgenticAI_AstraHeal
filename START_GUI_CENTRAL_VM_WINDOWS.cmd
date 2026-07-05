@echo off
cd /d %~dp0
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0START_GUI_CENTRAL_VM_WINDOWS.ps1"
pause
