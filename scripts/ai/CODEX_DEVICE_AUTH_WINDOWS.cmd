@echo off
title AIQA Codex Device Auth
echo Starting Codex device authentication...
echo.
echo This terminal is intentionally separate from the GUI.
echo Complete the login flow, then return to the GUI and click Check Codex/Ollama.
echo.
codex login --device-auth
echo.
echo If login completed successfully, you can close this window.
pause
