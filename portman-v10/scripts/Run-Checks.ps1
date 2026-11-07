$ErrorActionPreference = 'Stop'
Push-Location (Split-Path $PSScriptRoot -Parent)
$previousPythonPath = $env:PYTHONPATH
try {
    $python = Join-Path (Get-Location) '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $python)) {
        throw 'V10-Umgebung fehlt. Zuerst: python -m venv .venv'
    }
    $env:PYTHONPATH = Join-Path (Get-Location) 'src'
    & $python -m unittest discover -s tests -v
    if ($LASTEXITCODE -ne 0) { throw 'Prüfungen fehlgeschlagen.' }
} finally {
    $env:PYTHONPATH = $previousPythonPath
    Pop-Location
}
