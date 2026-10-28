[CmdletBinding()]
param(
    [string]$ProjectRoot = 'C:\Users\chris\Desktop\programming\PortmanNL',
    [string]$ArchiveRoot = 'C:\Users\chris\Desktop\Portman_Cleanup_Backup\Final_Archive_20261027'
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$CopyAllowed = @(
    'test_reports\comdirect_importtest_2026.csv','test_reports\comdirect_importtest_2026_after.csv',
    'test_reports\comdirect_importtest_2026.md','test_reports\final_integration_after_pr20_pr21_2026-10-22.md',
    'test_reports\importqualitaet_datenintegritaet_2026-10-21.md','test_reports\portman_v09_comdirect_tax_reconciliation_2026.md',
    'test_reports\portman_v09_final_production_integrity.md','test_reports\sqlite_reacceptance_after_pr19_2026-10-22.md',
    'test_reports\pdf_parser_audit\run_001','test_reports\pdf_parser_audit\v3_full_utf8',
    'test_reports\pdf_parser_audit\v3_utf8_23_recheck_20261026','test_reports\pdf_parser_audit\v3_utf8_23_recheck2_20261026',
    'test_reports\pdf_parser_audit\v3_utf8_23_recheck3_20261027','tools\pdf_parser_audit.py',
    'tools\pdf_parser_audit_v1.py','tools\pdf_parser_audit_v2.py','tools\test_audit_v2.py','tools\README.md',
    'tools\portman_pdf_parser_testsuite.zip','tools\portman_pdf_parser_testsuite_v2.zip','logs\portman.log'
)
$DeleteProtected = @(
    'data','.tmp','tmp','data\v09\portfolio.sqlite','tmpzk2fl5h9\portfolio.sqlite',
    'tools\Invoice-DVSZMLP9-0001.pdf','test_reports\pdf_parser_audit\run_001',
    'test_reports\pdf_parser_audit\v3_full_utf8','test_reports\pdf_parser_audit\v3_utf8_23_recheck_20261026',
    'test_reports\pdf_parser_audit\v3_utf8_23_recheck2_20261026','test_reports\pdf_parser_audit\v3_utf8_23_recheck3_20261027'
)
$projectFull=[IO.Path]::GetFullPath($ProjectRoot).TrimEnd('\'); $archiveFull=[IO.Path]::GetFullPath($ArchiveRoot).TrimEnd('\')
if($archiveFull.Equals($projectFull,[StringComparison]::OrdinalIgnoreCase)-or $archiveFull.StartsWith($projectFull+'\',[StringComparison]::OrdinalIgnoreCase)){throw "Archiv muss ausserhalb des Repositories liegen: $archiveFull"}
$rows=foreach($relative in $CopyAllowed){
    $source=Join-Path $projectFull $relative
    if(-not(Test-Path -LiteralPath $source)){[pscustomobject]@{Status='MISSING';Path=$relative;Files=0;Bytes=0;Destination=''};continue}
    $item=Get-Item -LiteralPath $source; $files=@(if($item.PSIsContainer){Get-ChildItem -LiteralPath $source -File -Force -Recurse}else{$item})
    [pscustomobject]@{Status='COPY_ALLOWED';Path=$relative;Files=$files.Count;Bytes=[int64](($files|Measure-Object Length -Sum).Sum);Destination=Join-Path $archiveFull $relative}
}
$rows|Format-Table -AutoSize
Write-Host "`nDELETE_PROTECTED (nur Anzeige; keine Loeschoperation vorhanden):"; $DeleteProtected|ForEach-Object{Write-Host "  $_"}
Write-Host "`nManifest: $(Join-Path $archiveFull 'sha256-manifest.csv')"
Write-Host 'Vorschau abgeschlossen; keine Dateien wurden veraendert.'
if($rows.Status -contains 'MISSING'){exit 2}
