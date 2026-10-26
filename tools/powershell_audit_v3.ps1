[CmdletBinding()]
param(
    [string]$PdfRoot = "C:\Users\chris\Desktop\history",
    [string]$Baseline,
    [string]$Output,
    [switch]$Resume,
    [double]$Timeout = 300
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
if (-not $Baseline) {
    $Baseline = Join-Path $ProjectRoot "test_reports\pdf_parser_audit\run_001\audit.json"
}
if (-not $Output) {
    $Output = Join-Path $ProjectRoot "test_reports\pdf_parser_audit\v3_full_utf8"
}

if (-not (Test-Path -LiteralPath $Baseline -PathType Leaf)) {
    throw "V2 baseline not found: $Baseline"
}
if (-not (Test-Path -LiteralPath $PdfRoot -PathType Container)) {
    throw "PDF root not found: $PdfRoot"
}

$Python = Get-Command python -ErrorAction Stop
& $Python.Source -c "import portfolio_v5.pdf_importer" | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "The active Python environment cannot import portfolio_v5.pdf_importer."
}

$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
$Arguments = @(
    "-X", "utf8", (Join-Path $ProjectRoot "tools\pdf_audit_v3.py"),
    "--root", $PdfRoot,
    "--baseline", $Baseline,
    "--output", $Output,
    "--allow-ocr",
    "--timeout", $Timeout
)
$Arguments += if ($Resume) { "--resume" } else { "--no-cache" }

Push-Location $ProjectRoot
try {
    & $Python.Source @Arguments
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
