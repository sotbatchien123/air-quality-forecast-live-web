$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$LockFile = Join-Path $RepoRoot "data\live\collector.lock"

if (-not (Test-Path -LiteralPath $LockFile)) {
    Write-Output "Collector is not running."
    exit 0
}

$OwnerPid = [int](Get-Content -LiteralPath $LockFile -Raw).Trim()
$Process = Get-Process -Id $OwnerPid -ErrorAction SilentlyContinue
if ($null -ne $Process) {
    Stop-Process -Id $OwnerPid
    Start-Sleep -Seconds 1
}
Remove-Item -LiteralPath $LockFile -Force -ErrorAction SilentlyContinue
Write-Output "Live collector stopped. PID: $OwnerPid"
