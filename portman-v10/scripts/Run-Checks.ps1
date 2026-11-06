$ErrorActionPreference = 'Stop'
Push-Location (Split-Path $PSScriptRoot -Parent)
$previousPythonPath = $env:PYTHONPATH
try {
    $env:PYTHONPATH = Join-Path (Get-Location) 'src'
    python -m unittest discover -s tests -v
    if ($LASTEXITCODE -ne 0) { throw 'Prüfungen fehlgeschlagen.' }
} finally {
    $env:PYTHONPATH = $previousPythonPath
    Pop-Location
}
