$ErrorActionPreference = "Continue"

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

$logDir = Join-Path $repoRoot "data\logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

$runnerLog = Join-Path $logDir "live-30s-test-runner.log"
$pidPath = Join-Path $repoRoot "data\live-30s-test.pid"
$PID | Set-Content -Path $pidPath -Encoding UTF8

function Write-RunnerLog {
    param([string]$Message)
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    "$timestamp $Message" | Tee-Object -FilePath $runnerLog -Append
}

$exchanges = @("Hibachi", "Rise", "Hotstuff", "Hyperliquid", "Lighter", "Pacifica")

Write-RunnerLog "Starting PerpDEX live 30s test loop. PID=$PID"
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

    Write-RunnerLog "Sleeping 30 seconds."
    Start-Sleep -Seconds 30
}
