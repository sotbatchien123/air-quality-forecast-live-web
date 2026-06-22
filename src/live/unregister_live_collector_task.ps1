param(
    [string]$TaskName = "DAP391_Live_Hourly_Collector"
)

& schtasks.exe /Delete /TN $TaskName /F
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
Write-Output "Removed scheduled task: $TaskName"
