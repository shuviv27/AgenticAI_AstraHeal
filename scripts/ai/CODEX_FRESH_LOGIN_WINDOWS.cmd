@echo off
title AIQA Fresh Codex Login
echo ============================================================
echo AIQA Fresh Codex Login
echo This will remove any existing Codex credentials, then start a
 echo fresh Codex browser login.
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
echo Starting fresh Codex login...
codex login
echo.
echo After successful login, return to AI QA GUI and click Run Codex Doctor.
pause
