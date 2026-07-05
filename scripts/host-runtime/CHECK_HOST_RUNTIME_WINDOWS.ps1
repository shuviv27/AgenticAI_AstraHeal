param([switch]$Json)
$ErrorActionPreference = 'Continue'
function Check-Cmd($Name, $Args='--version') {
  $cmd = Get-Command $Name -ErrorAction SilentlyContinue
  if (-not $cmd) { return [pscustomobject]@{tool=$Name; available=$false; ok=$false; version=''; path=''} }
  try {
    $out = & $Name $Args 2>&1 | Select-Object -First 5 | Out-String
    return [pscustomobject]@{tool=$Name; available=$true; ok=$true; version=$out.Trim(); path=$cmd.Source}
  } catch {
    return [pscustomobject]@{tool=$Name; available=$true; ok=$false; version=$_.Exception.Message; path=$cmd.Source}
  }
}
$checks = @(
  (Check-Cmd 'python' '--version'),
  (Check-Cmd 'git' '--version'),
  (Check-Cmd 'node' '--version'),
  (Check-Cmd 'npm' '--version'),
  (Check-Cmd 'npx' '--version'),
  (Check-Cmd 'java' '-version'),
  (Check-Cmd 'mvn' '-version'),
  (Check-Cmd 'codex' '--version'),
  (Check-Cmd 'ollama' '--version')
)
$result = [pscustomobject]@{
  mode='No-Docker Host Runtime'
  computer=$env:COMPUTERNAME
  user=$env:USERNAME
  checks=$checks
  summary='Python, Git, Node/npm/npx, Java/Maven and Codex/Ollama are checked. Missing feature-specific tools do not block the GUI but will block that feature.'
}
if ($Json) { $result | ConvertTo-Json -Depth 5 } else { $result | Format-List; $checks | Format-Table -AutoSize }
