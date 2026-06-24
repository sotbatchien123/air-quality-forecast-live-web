param(
    [string]$TomTomKeyFile = "",
    [int]$Minute = 5,
    [switch]$RunNow
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$LiveDir = Join-Path $RepoRoot "data\live"
$LockFile = Join-Path $LiveDir "collector.lock"
$CollectorLog = Join-Path $LiveDir "collector_12h.log"

New-Item -ItemType Directory -Force -Path $LiveDir | Out-Null

if (Test-Path -LiteralPath $LockFile) {
    $OwnerPid = (Get-Content -LiteralPath $LockFile -Raw).Trim()
    throw "Collector lock already exists for PID $OwnerPid. Run status_live_collector.ps1."
}
if ($TomTomKeyFile -and -not (Test-Path -LiteralPath $TomTomKeyFile)) {
    throw "TomTom key file not found: $TomTomKeyFile"
}
if (-not $TomTomKeyFile -and -not $env:TOMTOM_API_KEY) {
    throw "Set TOMTOM_API_KEY or pass -TomTomKeyFile with a key file path."
}

$Python = (Get-Command python).Source
$Pythonw = Join-Path (Split-Path -Parent $Python) "pythonw.exe"
if (-not (Test-Path -LiteralPath $Pythonw)) {
    throw "pythonw.exe not found next to: $Python"
}
$Arguments = @(
    "src\live\live_hourly_predictor.py",
    "run-forever",
    "--minute", $Minute,
    "--log-file", "`"$CollectorLog`""
)
if ($TomTomKeyFile) {
    $Arguments += @("--tomtom-key-file", "`"$TomTomKeyFile`"")
}
if ($RunNow) {
    $Arguments += "--run-now"
}

$Process = Start-Process `
    -FilePath $Pythonw `
    -ArgumentList $Arguments `
    -WorkingDirectory $RepoRoot `
    -WindowStyle Hidden `
    -PassThru

$Ready = $false
for ($Attempt = 1; $Attempt -le 30; $Attempt++) {
    Start-Sleep -Seconds 1
    $Process.Refresh()
    if ($Process.HasExited) {
        throw "Collector exited during startup. Check $CollectorLog"
    }
    if (Test-Path -LiteralPath $LockFile) {
        $Ready = $true
        break
    }
}
if (-not $Ready) {
    Stop-Process -Id $Process.Id -ErrorAction SilentlyContinue
    throw "Collector did not create its lock within 30 seconds. Check $CollectorLog"
}

Write-Output "Live collector started. PID: $($Process.Id)"
Write-Output "Schedule: minute $Minute every hour"
Write-Output "Log: $CollectorLog"
