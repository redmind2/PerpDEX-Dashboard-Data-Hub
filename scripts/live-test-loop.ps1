$ErrorActionPreference = "Continue"

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

$logDir = Join-Path $repoRoot "data\logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

$runnerLog = Join-Path $logDir "live-test-runner.log"
$pidPath = Join-Path $repoRoot "data\live-test.pid"
$PID | Set-Content -Path $pidPath -Encoding UTF8

function Get-EnvValue {
    param(
        [string]$Key,
        [string]$DefaultValue
    )

    $envPath = Join-Path $repoRoot ".env"
    if (-not (Test-Path $envPath)) {
        return $DefaultValue
    }

    $line = Get-Content -Path $envPath -Encoding UTF8 |
        Where-Object { $_ -match "^\s*$([regex]::Escape($Key))\s*=" } |
        Select-Object -First 1
    if (-not $line) {
        return $DefaultValue
    }

    $value = ($line -split "=", 2)[1].Trim().Trim('"').Trim("'")
    if (-not $value) {
        return $DefaultValue
    }
    return $value
}

function Get-EnvInt {
    param([string]$Key, [int]$DefaultValue)
    $raw = Get-EnvValue -Key $Key -DefaultValue ([string]$DefaultValue)
    $parsed = 0
    if ([int]::TryParse($raw, [ref]$parsed) -and $parsed -gt 0) {
        return $parsed
    }
    return $DefaultValue
}

function Write-RunnerLog {
    param([string]$Message)
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    "$timestamp $Message" | Tee-Object -FilePath $runnerLog -Append
}

$intervalSeconds = Get-EnvInt -Key "PERPDEX_COLLECTION_INTERVAL" -DefaultValue 300
$exchanges = @("Hibachi", "Rise", "Hotstuff", "Hyperliquid", "Lighter", "Pacifica")

Write-RunnerLog "Starting PerpDEX live test loop. PID=$PID interval_seconds=$intervalSeconds"
Write-RunnerLog "Using .env runtime defaults for DB path, interval, depth, notional depth, timeout, and retries."

.\perpdex.cmd init-db 2>&1 | Tee-Object -FilePath $runnerLog -Append

while ($true) {
    Write-RunnerLog "Collection pass started."

    foreach ($exchange in $exchanges) {
        Write-RunnerLog "Collecting $exchange"
        .\perpdex.cmd collect-live --exchange $exchange --once 2>&1 |
            Tee-Object -FilePath $runnerLog -Append
    }

    Write-RunnerLog "Storage summary"
    .\perpdex.cmd storage 2>&1 | Tee-Object -FilePath $runnerLog -Append

    Write-RunnerLog "Sleeping $intervalSeconds seconds."
    Start-Sleep -Seconds $intervalSeconds
}
