param(
    [string]$TaskName = "DAP391_Live_Hourly_Collector"
)

$ErrorActionPreference = "Stop"
$Runner = (Resolve-Path (Join-Path $PSScriptRoot "run_live_collection_once.ps1")).Path
$FileSystem = New-Object -ComObject Scripting.FileSystemObject
$ShortRunner = $FileSystem.GetFile($Runner).ShortPath
$TaskCommand = "powershell.exe -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File $ShortRunner"

& schtasks.exe `
    /Create `
    /TN $TaskName `
    /TR $TaskCommand `
    /SC HOURLY `
    /MO 1 `
    /ST "00:05" `
    /F

if ($LASTEXITCODE -ne 0) {
    throw "Unable to register scheduled task: $TaskName"
}

$Settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -WakeToRun `
    -MultipleInstances IgnoreNew
Set-ScheduledTask -TaskName $TaskName -Settings $Settings | Out-Null

Write-Output "Registered task: $TaskName"
Write-Output "Schedule: every hour at minute 05"
Write-Output "Mode: hidden; battery and missed-start execution enabled"
Write-Output "Run now: schtasks /Run /TN $TaskName"
