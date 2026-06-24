param(
    [string]$TaskName = "DAP391_Live_Hourly_Collector"
)

$ErrorActionPreference = "Stop"
$Runner = (Resolve-Path (Join-Path $PSScriptRoot "run_live_collection_once.ps1")).Path
$StartAt = (Get-Date).Date.AddMinutes(5)
if ($StartAt -le (Get-Date)) {
    $StartAt = $StartAt.AddHours(1)
}
$Action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$Runner`""
$Trigger = New-ScheduledTaskTrigger `
    -Once `
    -At $StartAt `
    -RepetitionInterval (New-TimeSpan -Hours 1) `
    -RepetitionDuration (New-TimeSpan -Days 3650)
$Settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -WakeToRun `
    -MultipleInstances IgnoreNew
Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger $Trigger `
    -Settings $Settings `
    -Description "Collect live traffic/AQI/weather and forecast the next hour for DAP391" `
    -Force | Out-Null

Write-Output "Registered task: $TaskName"
Write-Output "Schedule: every hour at minute 05"
Write-Output "Mode: hidden; battery and missed-start execution enabled"
Write-Output "Runner: $Runner"
Write-Output "Run now: Start-ScheduledTask -TaskName $TaskName"
