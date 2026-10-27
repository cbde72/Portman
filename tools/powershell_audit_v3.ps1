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
$SourceRoot = Join-Path $ProjectRoot "src"
$OutputWasSpecified = -not [string]::IsNullOrWhiteSpace($Output)
if (-not $Baseline) {
    $Baseline = Join-Path $ProjectRoot "test_reports\pdf_parser_audit\run_001\audit.json"
}
if ($Resume -and -not $OutputWasSpecified) {
    throw "-Resume requires an explicit -Output directory."
}
if (-not $OutputWasSpecified) {
    $Timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $Output = Join-Path $ProjectRoot "test_reports\pdf_parser_audit\v3_$Timestamp"
    $Suffix = 1
    while (Test-Path -LiteralPath $Output) {
        $Output = Join-Path $ProjectRoot "test_reports\pdf_parser_audit\v3_${Timestamp}_$Suffix"
        $Suffix++
    }
}

if (-not (Test-Path -LiteralPath $Baseline -PathType Leaf)) {
    throw "V2 baseline not found: $Baseline"
}
if (-not (Test-Path -LiteralPath $PdfRoot -PathType Container)) {
    throw "PDF root not found: $PdfRoot"
}
if (Test-Path -LiteralPath $Output) {
    if (-not (Test-Path -LiteralPath $Output -PathType Container)) {
        throw "Output path exists and is not a directory: $Output"
    }
    if (-not $Resume) {
        throw "Output directory already exists: $Output. Choose a new directory or use -Resume."
    }
}
elseif ($Resume) {
    throw "Resume output directory not found: $Output"
}

$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
$PythonPathParts = @($ProjectRoot, $SourceRoot)
if (-not [string]::IsNullOrWhiteSpace($env:PYTHONPATH)) {
    $PythonPathParts += $env:PYTHONPATH -split [IO.Path]::PathSeparator
}
$env:PYTHONPATH = ($PythonPathParts | Where-Object { $_ } | Select-Object -Unique) -join [IO.Path]::PathSeparator

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
    $Python = Get-Command python -ErrorAction Stop
    & $Python.Source -X utf8 -c "import portfolio_v5.pdf_importer" | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "The active Python environment cannot import portfolio_v5.pdf_importer."
    }
    & $Python.Source @Arguments
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
