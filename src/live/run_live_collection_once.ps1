param(
    [string]$TomTomKeyFile = "C:\Users\ASUS G615\Air Predict model\key_tom_tom.txt"
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$LiveDir = Join-Path $RepoRoot "data\live"
$LogFile = Join-Path $LiveDir "scheduled_collector.log"
$Python = (Get-Command python).Source

New-Item -ItemType Directory -Force -Path $LiveDir | Out-Null
if (-not (Test-Path -LiteralPath $TomTomKeyFile)) {
    throw "TomTom key file not found: $TomTomKeyFile"
}

Push-Location $RepoRoot
try {
    $StartedAt = Get-Date -Format "yyyy-MM-ddTHH:mm:ssK"
    Add-Content -LiteralPath $LogFile -Value "[$StartedAt] Scheduled collection started"
    $Output = & $Python `
        "src\live\live_hourly_predictor.py" `
        "run" `
        "--tomtom-key-file" `
        $TomTomKeyFile 2>&1
    $ExitCode = $LASTEXITCODE
    $Output | ForEach-Object {
        Add-Content -LiteralPath $LogFile -Value $_.ToString()
    }
    $FinishedAt = Get-Date -Format "yyyy-MM-ddTHH:mm:ssK"
    Add-Content -LiteralPath $LogFile -Value "[$FinishedAt] Exit code: $ExitCode"
    exit $ExitCode
}
finally {
    Pop-Location
}
