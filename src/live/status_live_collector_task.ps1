param(
    [string]$TaskName = "DAP391_Live_Hourly_Collector"
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$ObservationsFile = Join-Path $RepoRoot "data\live\hourly_observations.csv"
$PredictionsFile = Join-Path $RepoRoot "data\live\hourly_predictions.csv"

try {
    $Task = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
    $Info = Get-ScheduledTaskInfo -TaskName $TaskName -ErrorAction Stop
}
catch {
    Write-Output "Scheduled task not found or not readable: $TaskName"
    exit 1
}

Write-Output "Task name: $TaskName"
Write-Output "State: $($Task.State)"
Write-Output "Next run: $($Info.NextRunTime)"
Write-Output "Last run: $($Info.LastRunTime)"
Write-Output "Last result: $($Info.LastTaskResult)"
if ($Task.Actions.Count -gt 0) {
    Write-Output "Action: $($Task.Actions[0].Execute) $($Task.Actions[0].Arguments)"
}

if (Test-Path -LiteralPath $ObservationsFile) {
    $Rows = Import-Csv -LiteralPath $ObservationsFile
    $Hours = @($Rows.timestamp | Sort-Object -Unique).Count
    $Latest = $Rows.timestamp | Sort-Object | Select-Object -Last 1
    Write-Output "Collected hours: $Hours/12 minimum"
    Write-Output "Latest observation snapshot: $Latest"
}

if (Test-Path -LiteralPath $PredictionsFile) {
    $Predictions = Import-Csv -LiteralPath $PredictionsFile
    $LatestPrediction = $Predictions.target_timestamp | Sort-Object | Select-Object -Last 1
    Write-Output "Prediction rows: $($Predictions.Count)"
    Write-Output "Latest prediction target: $LatestPrediction"
}
