$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$env:PYTHONPATH = Join-Path $projectRoot "src"

Push-Location $projectRoot
try {
    python -W error::DeprecationWarning -m unittest discover -s tests -v
    if ($LASTEXITCODE -ne 0) { throw "Tests failed." }

    python -m compileall -q src tests examples
    if ($LASTEXITCODE -ne 0) { throw "Compilation failed." }

    Write-Host "TradeFlow checks passed."
}
finally {
    Pop-Location
}

