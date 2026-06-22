$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$LockFile = Join-Path $RepoRoot "data\live\collector.lock"
$ObservationsFile = Join-Path $RepoRoot "data\live\hourly_observations.csv"

if (-not (Test-Path -LiteralPath $LockFile)) {
    Write-Output "Collector is not running: no lock file."
    exit 1
}

$OwnerPid = [int](Get-Content -LiteralPath $LockFile -Raw).Trim()
$Process = Get-Process -Id $OwnerPid -ErrorAction SilentlyContinue
if ($null -eq $Process) {
    Write-Output "Collector lock is stale. PID $OwnerPid is not running."
    exit 2
}

Write-Output "Collector is running. PID: $OwnerPid"
if (Test-Path -LiteralPath $ObservationsFile) {
    $Rows = Import-Csv -LiteralPath $ObservationsFile
    $Hours = @($Rows.timestamp | Sort-Object -Unique).Count
    $Latest = $Rows.timestamp | Sort-Object | Select-Object -Last 1
    Write-Output "Collected hours: $Hours/12 minimum"
    Write-Output "Latest snapshot: $Latest"
}
