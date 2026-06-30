$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

$logDir = Join-Path $repoRoot "data\logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

$logPath = Join-Path $logDir "archive-monthly.log"

function Write-ArchiveLog {
    param([string]$Message)
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    "$timestamp $Message" | Tee-Object -FilePath $logPath -Append
}

try {
    Write-ArchiveLog "Monthly archive started."
    .\perpdex.cmd archive-month 2>&1 | Tee-Object -FilePath $logPath -Append
    Write-ArchiveLog "Monthly archive finished."
} catch {
    Write-ArchiveLog "Monthly archive failed: $($_.Exception.Message)"
    throw
}
