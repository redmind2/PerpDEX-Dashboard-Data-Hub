$ErrorActionPreference = "Continue"

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

$logDir = Join-Path $repoRoot "data\logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

$runnerLog = Join-Path $logDir "live-test-runner.log"
$pidPath = Join-Path $repoRoot "data\live-test.pid"
$controlPath = Join-Path $repoRoot "data\control.json"
$PID | Set-Content -Path $pidPath -Encoding ASCII

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

function Get-ControlState {
    if (-not (Test-Path $controlPath)) {
        return [PSCustomObject]@{
            collector_paused = $false
            paused_exchanges = @()
        }
    }

    try {
        $state = Get-Content -Path $controlPath -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($null -eq $state.paused_exchanges) {
            $state | Add-Member -NotePropertyName paused_exchanges -NotePropertyValue @() -Force
        }
        if ($null -eq $state.collector_paused) {
            $state | Add-Member -NotePropertyName collector_paused -NotePropertyValue $false -Force
        }
        return $state
    } catch {
        Write-RunnerLog "Control file read failed; continuing collection. error=$($_.Exception.Message)"
        return [PSCustomObject]@{
            collector_paused = $false
            paused_exchanges = @()
        }
    }
}

function Test-ExchangePaused {
    param(
        [object]$ControlState,
        [string]$Exchange
    )

    foreach ($pausedExchange in @($ControlState.paused_exchanges)) {
        if ([string]::Equals([string]$pausedExchange, $Exchange, [System.StringComparison]::OrdinalIgnoreCase)) {
            return $true
        }
    }
    return $false
}

$intervalSeconds = Get-EnvInt -Key "PERPDEX_COLLECTION_INTERVAL" -DefaultValue 300
$exchanges = @("Hibachi", "Rise", "Hotstuff", "Hyperliquid", "Lighter", "Pacifica")

Write-RunnerLog "Starting PerpDEX live test loop. PID=$PID interval_seconds=$intervalSeconds"
Write-RunnerLog "Using .env runtime defaults for DB path, interval, depth, notional depth, timeout, and retries."

.\perpdex.cmd init-db 2>&1 | Tee-Object -FilePath $runnerLog -Append

while ($true) {
    Write-RunnerLog "Collection pass started."

    $control = Get-ControlState
    if ($control.collector_paused) {
        Write-RunnerLog "Collection pass skipped: collector paused by control file."
        Write-RunnerLog "Sleeping $intervalSeconds seconds."
        Start-Sleep -Seconds $intervalSeconds
        continue
    }

    foreach ($exchange in $exchanges) {
        $control = Get-ControlState
        if ($control.collector_paused) {
            Write-RunnerLog "Collection pass paused before $exchange."
            break
        }
        if (Test-ExchangePaused -ControlState $control -Exchange $exchange) {
            Write-RunnerLog "Skipping ${exchange}: exchange paused by control file."
            continue
        }
        Write-RunnerLog "Collecting $exchange"
        .\perpdex.cmd collect-live --exchange $exchange --once 2>&1 |
            Tee-Object -FilePath $runnerLog -Append
    }

    Write-RunnerLog "Storage summary"
    .\perpdex.cmd storage 2>&1 | Tee-Object -FilePath $runnerLog -Append

    Write-RunnerLog "Sleeping $intervalSeconds seconds."
    Start-Sleep -Seconds $intervalSeconds
}
