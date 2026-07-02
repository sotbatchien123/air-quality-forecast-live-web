param(
    [string]$EnvFile = ".env",
    [string]$Workflow = "live_pages.yml",
    [switch]$RunWorkflow,
    [switch]$SkipCollection
)

$ErrorActionPreference = "Stop"

# This script intentionally reads local .env values without printing them.
# It uploads the values as GitHub Actions secrets, configures Pages, and can
# trigger the hourly dashboard workflow once the GitHub CLI is authenticated.

function Resolve-GhCommand {
    $fromPath = Get-Command gh -ErrorAction SilentlyContinue
    if ($fromPath) {
        return $fromPath.Source
    }

    $candidates = @(
        (Join-Path $env:ProgramFiles "GitHub CLI\gh.exe"),
        (Join-Path ${env:ProgramFiles(x86)} "GitHub CLI\gh.exe")
    )
    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path -LiteralPath $candidate)) {
            return $candidate
        }
    }

    throw "GitHub CLI 'gh' is not installed. Install it first: https://cli.github.com/"
}

function Invoke-Gh {
    param(
        [string[]]$Arguments,
        [string]$InputText
    )

    if ($PSBoundParameters.ContainsKey("InputText")) {
        $InputText | & $script:GhCommand @Arguments
    }
    else {
        & $script:GhCommand @Arguments
    }

    if ($LASTEXITCODE -ne 0) {
        throw "gh $($Arguments -join ' ') failed with exit code $LASTEXITCODE"
    }
}

function Get-RepoSlug {
    $remote = (git remote get-url origin).Trim()
    if ($remote -match "github\.com[:/](?<owner>[^/]+)/(?<repo>[^/.]+)(\.git)?$") {
        return "$($Matches.owner)/$($Matches.repo)"
    }
    throw "Cannot parse GitHub owner/repo from origin remote: $remote"
}

function Read-DotEnv {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) {
        throw "Env file not found: $Path"
    }

    $values = @{}
    Get-Content -LiteralPath $Path | ForEach-Object {
        $line = $_.Trim()
        if (-not $line -or $line.StartsWith("#") -or -not $line.Contains("=")) {
            return
        }
        $key, $value = $line.Split("=", 2)
        $key = $key.Trim()
        $value = $value.Trim()
        if ($value.Length -ge 2 -and $value[0] -eq $value[$value.Length - 1] -and $value[0] -in @('"', "'")) {
            $value = $value.Substring(1, $value.Length - 2)
        }
        $values[$key] = $value
    }
    return $values
}

function Write-FilteredSecretFile {
    param(
        [hashtable]$Values,
        [string[]]$Keys
    )

    $missing = @()
    foreach ($key in @("TOMTOM_API_KEY", "DB_HOST", "DB_USERNAME", "DB_PASSWORD", "DB_DATABASE")) {
        if (-not $Values.ContainsKey($key) -or [string]::IsNullOrWhiteSpace($Values[$key])) {
            $missing += $key
        }
    }
    if ($missing.Count -gt 0) {
        throw "Missing required values in .env: $($missing -join ', ')"
    }

    $temp = New-TemporaryFile
    foreach ($key in $Keys) {
        if ($Values.ContainsKey($key) -and -not [string]::IsNullOrWhiteSpace($Values[$key])) {
            Add-Content -LiteralPath $temp.FullName -Value "$key=$($Values[$key])"
        }
    }
    return $temp
}

$script:GhCommand = Resolve-GhCommand
Invoke-Gh -Arguments @("auth", "status") | Out-Null

$repo = Get-RepoSlug
$values = Read-DotEnv -Path $EnvFile
$secretKeys = @(
    "TOMTOM_API_KEY",
    "DB_HOST",
    "DB_PORT",
    "DB_USERNAME",
    "DB_PASSWORD",
    "DB_DATABASE",
    "DB_SSL_MODE",
    "DB_SSL_CA"
)

$secretFile = Write-FilteredSecretFile -Values $values -Keys $secretKeys
try {
    Invoke-Gh -Arguments @("secret", "set", "--repo", $repo, "-f", $secretFile.FullName)
}
finally {
    Remove-Item -LiteralPath $secretFile.FullName -Force -ErrorAction SilentlyContinue
}

$body = '{"build_type":"workflow"}'
$pagesCreated = $false
try {
    Invoke-Gh -Arguments @("api", "--repo", $repo, "--method", "POST", "repos/$repo/pages", "--input", "-") -InputText $body | Out-Null
    $pagesCreated = $true
}
catch {
    Invoke-Gh -Arguments @("api", "--repo", $repo, "--method", "PUT", "repos/$repo/pages", "--input", "-") -InputText $body | Out-Null
}

Write-Output "Configured GitHub Secrets for $repo."
if ($pagesCreated) {
    Write-Output "Created GitHub Pages site with workflow deployment."
}
else {
    Write-Output "Updated GitHub Pages site to use workflow deployment."
}

if ($RunWorkflow) {
    $args = @("workflow", "run", $Workflow, "--repo", $repo)
    if ($SkipCollection) {
        $args += @("-f", "skip_collection=true")
    }
    Invoke-Gh -Arguments $args
    Write-Output "Triggered workflow: $Workflow"
}
