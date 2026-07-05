$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$env:AIQA_RUNTIME_MODE = "central_vm"
$env:AIQA_DEPLOYMENT_TOPOLOGY = "central_vm_only"
Write-Host "Starting AstraHeal AI on Central VM. Browser URL: http://127.0.0.1:8080/astraheal-ai" -ForegroundColor Cyan
Write-Host "Remote URL from worker/VDI: http://<Central-VM-IP>:8080/astraheal-ai" -ForegroundColor Yellow
python .\RUN_GUI_FIRST.py --host 0.0.0.0 --port 8080
