$ErrorActionPreference = 'Stop'
if(-not (Get-Command npx -ErrorAction SilentlyContinue)){ throw 'npx is not available. Install Node.js LTS first.' }
npx playwright install
Write-Host 'Playwright browsers installed for the current user/cache.' -ForegroundColor Green
