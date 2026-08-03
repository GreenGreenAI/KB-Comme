$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$env:PYTHONPATH = Join-Path $projectRoot "src"

Push-Location $projectRoot
try {
    python -W error::DeprecationWarning -m unittest discover -s tests -t . -v
    if ($LASTEXITCODE -ne 0) { throw "Tests failed." }

    python scripts/benchmark_user_tasks.py
    if ($LASTEXITCODE -ne 0) { throw "Customer task benchmark failed." }

    python -m compileall -q src tests examples
    if ($LASTEXITCODE -ne 0) { throw "Compilation failed." }

    python scripts/check_docs.py
    if ($LASTEXITCODE -ne 0) { throw "Documentation checks failed." }

    python scripts/check_rulepacks.py
    if ($LASTEXITCODE -ne 0) { throw "Rulepack readiness checks failed." }

    Write-Host "KB Comme checks passed."
}
finally {
    Pop-Location
}
