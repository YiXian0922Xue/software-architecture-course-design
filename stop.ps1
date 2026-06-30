$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = (Resolve-Path (Join-Path $Root ".conda\env\python.exe") -ErrorAction SilentlyContinue).Path
$PidFile = Join-Path $Root "data\server.pid"
$Listener = Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue

if (-not $Listener) {
    Remove-Item -LiteralPath (Join-Path $Root "data\server.pid") -Force -ErrorAction SilentlyContinue
    Write-Host "LabScribe is not running; port 8000 is free."
    exit 0
}

$Process = Get-Process -Id $Listener.OwningProcess -ErrorAction Stop
$ManagedPid = if (Test-Path -LiteralPath $PidFile) { [int](Get-Content -LiteralPath $PidFile -Raw) } else { 0 }
$IsManaged = $ManagedPid -eq $Process.Id
if (-not $IsManaged -and $Python -and $Process.Path -ne $Python) {
    Write-Error "Port 8000 belongs to another process (PID $($Process.Id), $($Process.Path)); it was not terminated."
}

Stop-Process -Id $Process.Id -Force
Remove-Item -LiteralPath $PidFile -Force -ErrorAction SilentlyContinue
Write-Host "LabScribe stopped; port 8000 is free." -ForegroundColor Green
