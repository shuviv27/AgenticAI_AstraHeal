$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$env:AIQA_RUNTIME_MODE = "local_pc"
$env:AIQA_DEPLOYMENT_TOPOLOGY = "local_only"
Write-Host "Starting AstraHeal AI for Local PC mode..." -ForegroundColor Cyan
python .\RUN_GUI_FIRST.py --host 127.0.0.1 --port 8080
