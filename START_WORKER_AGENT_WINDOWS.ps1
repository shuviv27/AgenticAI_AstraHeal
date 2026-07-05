$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
if (!(Test-Path ".\worker-agent.env")) {
  Write-Host "worker-agent.env not found. Creating it from worker-agent.env.example..." -ForegroundColor Yellow
  Copy-Item ".\worker-agent.env.example" ".\worker-agent.env" -Force
  Write-Host "Please edit worker-agent.env with Central VM URL and token, then rerun this script." -ForegroundColor Red
  exit 2
}
Write-Host "Starting AstraHeal AI Worker Agent..." -ForegroundColor Cyan
python .\RUN_WORKER_AGENT.py --env .\worker-agent.env
