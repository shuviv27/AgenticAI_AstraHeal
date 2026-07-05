@echo off
title AIQA Codex Doctor
echo Checking Codex status...
echo.
codex login status
echo.
codex doctor --json
echo.
pause
