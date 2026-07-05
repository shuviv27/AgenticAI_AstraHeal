$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $root
New-Item -ItemType Directory -Force -Path '.qa-cache\host-runtime' | Out-Null
@{ ok=$true; mode='No-Docker Host Runtime'; stoppedAt=(Get-Date).ToString('o'); message='Host services marked idle. GUI process is not killed by this script.' } | ConvertTo-Json -Depth 5 | Set-Content '.qa-cache\host-runtime\host-runtime-state.json' -Encoding UTF8
Write-Host 'No-Docker Host Services marked idle.' -ForegroundColor Yellow
