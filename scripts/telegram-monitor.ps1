$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

$dataDir = Join-Path $repoRoot "data"
New-Item -ItemType Directory -Force -Path $dataDir | Out-Null

$pidPath = Join-Path $dataDir "telegram-monitor.pid"
$PID | Set-Content -Path $pidPath -Encoding ASCII

.\perpdex.cmd telegram-monitor
