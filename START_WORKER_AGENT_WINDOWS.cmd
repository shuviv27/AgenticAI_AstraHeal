@echo off
cd /d %~dp0
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0START_WORKER_AGENT_WINDOWS.ps1"
pause
