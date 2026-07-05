$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $root
$dirs = @('.qa-cache\host-runtime','.qa-cache\runtime','.qa-cache\rag','.qa-cache\jobs','.qa-cache\artifacts','generated-playwright\reports')
foreach($d in $dirs){ New-Item -ItemType Directory -Force -Path $d | Out-Null }
$state = @{ ok=$true; mode='No-Docker Host Runtime'; startedAt=(Get-Date).ToString('o'); root=$root; message='Host service folders are ready. Start the GUI and use Runtime Mode -> No-Docker Host Runtime.' }
$state | ConvertTo-Json -Depth 5 | Set-Content '.qa-cache\host-runtime\host-runtime-state.json' -Encoding UTF8
Write-Host 'No-Docker Host Services initialized.' -ForegroundColor Green
Write-Host 'Start GUI with START_AI_QA_GUI_NO_DOCKER_WINDOWS.cmd or existing GUI launcher.' -ForegroundColor Cyan
