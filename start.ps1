$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $Root ".conda\env\python.exe"
$PidFile = Join-Path $Root "data\server.pid"
$OutLog = Join-Path $Root "data\server.out.log"
$ErrLog = Join-Path $Root "data\server.err.log"

if (-not (Test-Path -LiteralPath $Python)) {
    Write-Error "Conda environment not found. Run: conda env create -p .conda\env -f environment.yml"
}

$Listener = Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue
if ($Listener) {
    Write-Error "Port 8000 is already used by PID $($Listener.OwningProcess). Run .\stop.ps1 or close the foreground server first."
}

$Process = Start-Process -FilePath $Python -ArgumentList "run.py" -WorkingDirectory $Root -WindowStyle Hidden -RedirectStandardOutput $OutLog -RedirectStandardError $ErrLog -PassThru
Set-Content -LiteralPath $PidFile -Value $Process.Id -Encoding ASCII
Start-Sleep -Milliseconds 700
if ($Process.HasExited) {
    Write-Error "Server failed to start. Check data\server.err.log"
}

Write-Host "LabScribe started: http://127.0.0.1:8000" -ForegroundColor Green
Write-Host "Background PID: $($Process.Id)"
Write-Host "Stop command: .\stop.ps1"
Write-Host "Live log command: Get-Content .\data\server.out.log -Wait"
Write-Host "Error log command: Get-Content .\data\server.err.log -Wait"
