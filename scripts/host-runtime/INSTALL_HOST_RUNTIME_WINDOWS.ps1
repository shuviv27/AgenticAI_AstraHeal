param(
  [switch]$InstallPython,
  [switch]$InstallGit,
  [switch]$InstallNode,
  [switch]$InstallJava,
  [switch]$InstallMaven,
  [switch]$InstallOllama,
  [switch]$InstallCodex,
  [switch]$InstallPlaywrightBrowsers,
  [switch]$All,
  [switch]$DryRun
)
$ErrorActionPreference = 'Stop'
Write-Host 'AI QA No-Docker Host Runtime installer' -ForegroundColor Cyan
Write-Host 'Run only after client IT approval. Uses winget when available. If winget is blocked, install from approved internal software center.' -ForegroundColor Yellow
function Have($cmd){ return [bool](Get-Command $cmd -ErrorAction SilentlyContinue) }
function Run($cmd){ if($DryRun){ Write-Host "DRY-RUN: $cmd" -ForegroundColor DarkGray } else { Write-Host "RUN: $cmd" -ForegroundColor Green; iex $cmd } }
$winget = Have winget
if(-not $winget){ Write-Warning 'winget not found. This script will only print manual guidance.' }
if($All){ $InstallPython=$InstallGit=$InstallNode=$InstallJava=$InstallMaven=$InstallOllama=$InstallCodex=$InstallPlaywrightBrowsers=$true }
if($InstallPython -and -not (Have python)){ if($winget){ Run 'winget install -e --id Python.Python.3.12' } else { Write-Host 'Install Python 3.11/3.12 from approved client software center.' }}
if($InstallGit -and -not (Have git)){ if($winget){ Run 'winget install -e --id Git.Git' } else { Write-Host 'Install Git from approved client software center.' }}
if($InstallNode -and -not (Have node)){ if($winget){ Run 'winget install -e --id OpenJS.NodeJS.LTS' } else { Write-Host 'Install Node.js 20/22 LTS from approved client software center.' }}
if($InstallJava -and -not (Have java)){ if($winget){ Run 'winget install -e --id EclipseAdoptium.Temurin.21.JDK' } else { Write-Host 'Install JDK 17/21 from approved client software center.' }}
if($InstallMaven -and -not (Have mvn)){ if($winget){ Run 'winget install -e --id Apache.Maven' } else { Write-Host 'Install Maven 3.9+ from approved client software center.' }}
if($InstallOllama -and -not (Have ollama)){ if($winget){ Run 'winget install -e --id Ollama.Ollama' } else { Write-Host 'Install Ollama only if local LLM is approved.' }}
if($InstallCodex -and -not (Have codex)){
  if(Have npm){ Run 'npm install -g @openai/codex' } else { Write-Host 'Install Node/npm first, then install Codex CLI using the client-approved package source.' }
}
if($InstallPlaywrightBrowsers){
  if(Have npx){ Run 'npx playwright install' } else { Write-Host 'Install Node/npm first, then run npx playwright install inside each Playwright framework.' }
}
Write-Host 'Install step completed. Run scripts\host-runtime\CHECK_HOST_RUNTIME_WINDOWS.ps1 next.' -ForegroundColor Cyan
