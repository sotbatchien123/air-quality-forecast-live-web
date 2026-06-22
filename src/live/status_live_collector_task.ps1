param(
    [string]$TaskName = "DAP391_Live_Hourly_Collector"
)

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$ObservationsFile = Join-Path $RepoRoot "data\live\hourly_observations.csv"

& schtasks.exe /Query /TN $TaskName /V /FO LIST
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

if (Test-Path -LiteralPath $ObservationsFile) {
    $Rows = Import-Csv -LiteralPath $ObservationsFile
    $Hours = @($Rows.timestamp | Sort-Object -Unique).Count
    $Latest = $Rows.timestamp | Sort-Object | Select-Object -Last 1
    Write-Output "Collected hours: $Hours/12 minimum"
    Write-Output "Latest snapshot: $Latest"
}
