param(
    [string]$TomTomKeyFile = ""
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$LiveDir = Join-Path $RepoRoot "data\live"
$LogFile = Join-Path $LiveDir "scheduled_collector.log"
$Python = (Get-Command python).Source

New-Item -ItemType Directory -Force -Path $LiveDir | Out-Null
if ($TomTomKeyFile -and -not (Test-Path -LiteralPath $TomTomKeyFile)) {
    throw "TomTom key file not found: $TomTomKeyFile"
}
if (-not $TomTomKeyFile -and -not $env:TOMTOM_API_KEY) {
    throw "Set TOMTOM_API_KEY or pass -TomTomKeyFile with a key file path."
}

Push-Location $RepoRoot
try {
    $StartedAt = Get-Date -Format "yyyy-MM-ddTHH:mm:ssK"
    Add-Content -LiteralPath $LogFile -Value "[$StartedAt] Scheduled collection started"
    $Arguments = @("src\live\live_hourly_predictor.py", "run")
    if ($TomTomKeyFile) {
        $Arguments += @("--tomtom-key-file", $TomTomKeyFile)
    }
    $Output = & $Python @Arguments 2>&1
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
