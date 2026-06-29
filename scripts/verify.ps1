$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$BundledPython = "C:\Users\USER\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if (Test-Path $BundledPython) {
    $Python = $BundledPython
} else {
    $Python = "python"
}

$env:PYTHONPATH = "$Root\src;$env:PYTHONPATH"
$env:PYTHONPYCACHEPREFIX = "$Root\.verify-pycache"
$env:PERPDEX_DB_PATH = "data\phase1-verify.sqlite"

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)]
        [scriptblock] $Command
    )

    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code $LASTEXITCODE"
    }
}

Write-Host "Using Python: $Python"
Write-Host "Using DB: $env:PERPDEX_DB_PATH"

Invoke-Checked { & $Python -m compileall src tests }

& $Python -c "import importlib.util, sys; sys.exit(0 if importlib.util.find_spec('pytest') else 1)"
if ($LASTEXITCODE -eq 0) {
    Invoke-Checked { & $Python -m pytest }
} else {
    Write-Host "pytest is not installed; running fallback smoke checks instead."
    Invoke-Checked { & $Python -m perpdex_bot init-db }
    Invoke-Checked { & $Python -m perpdex_bot seed-mock }
    Invoke-Checked { & $Python -m perpdex_bot overview }
    Invoke-Checked { & $Python -m perpdex_bot storage }
    Invoke-Checked { & $Python scripts\scan_secrets.py }
}

Write-Host "Verification passed."
