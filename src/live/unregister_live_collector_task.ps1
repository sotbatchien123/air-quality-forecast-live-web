param(
    [string]$TaskName = "DAP391_Live_Hourly_Collector"
)

$ErrorActionPreference = "Stop"

try {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction Stop
    Write-Output "Removed scheduled task: $TaskName"
}
catch {
    Write-Output "Scheduled task not found or could not be removed: $TaskName"
    exit 1
}
