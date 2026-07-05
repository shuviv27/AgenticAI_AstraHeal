param([int[]]$Ports=@(8080,8089,1080,3001,9090,11434))
foreach($p in $Ports){
  $conns = Get-NetTCPConnection -LocalPort $p -ErrorAction SilentlyContinue
  foreach($c in $conns){
    try { Stop-Process -Id $c.OwningProcess -Force -ErrorAction SilentlyContinue; Write-Host "Stopped process $($c.OwningProcess) on port $p" -ForegroundColor Yellow } catch {}
  }
}
