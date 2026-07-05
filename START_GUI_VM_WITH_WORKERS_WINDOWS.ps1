$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$env:AIQA_RUNTIME_MODE = "vm_with_workers"
$env:AIQA_DEPLOYMENT_TOPOLOGY = "central_vm_plus_worker_agents"
$env:AIQA_ENABLE_WORKER_AGENTS = "true"
Write-Host "Starting AstraHeal AI Central VM + Worker Agents mode..." -ForegroundColor Cyan
Write-Host "After GUI starts, create worker tokens and run START_WORKER_AGENT_WINDOWS.cmd on VM45/VM135." -ForegroundColor Yellow
python .\RUN_GUI_FIRST.py --host 0.0.0.0 --port 8080
