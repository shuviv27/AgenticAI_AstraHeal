@echo off
title AIQA Fresh Codex Device Auth
echo ============================================================
echo AIQA Fresh Codex Device Auth
echo This will remove any existing Codex credentials, then start a
 echo fresh Codex device-auth login.
echo ============================================================
echo.
where codex >nul 2>nul
if errorlevel 1 (
  echo Codex CLI is not found in PATH.
  echo Install Codex CLI using your organisation-approved method.
  pause
  exit /b 1
)
echo Logging out existing Codex session if present...
codex logout
echo.
echo Starting fresh Codex device-auth login...
codex login --device-auth
echo.
echo After successful login, return to AI QA GUI and click Run Codex Doctor.
pause
