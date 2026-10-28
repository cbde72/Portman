[CmdletBinding()]
param(
    [switch]$ApproveArchive,
    [string]$ProjectRoot = 'C:\Users\chris\Desktop\programming\PortmanNL',
    [string]$ArchiveRoot = 'C:\Users\chris\Desktop\Portman_Cleanup_Backup\Final_Archive_20261027',
    [string[]]$ArchiveTargets
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
function Get-NormalRelativePath([string]$Path){
    if([string]::IsNullOrWhiteSpace($Path)-or[IO.Path]::IsPathRooted($Path)-or$Path-match'(^|[\\/])\.\.([\\/]|$)'-or$Path.IndexOfAny(@('*','?'))-ge 0){throw "Unsicherer relativer Pfad: $Path"}
    $Path.Replace('/','\').TrimStart('\')
}
function Test-IsProtected([string]$RelativePath){
    $normal=Get-NormalRelativePath $RelativePath
    foreach($protected in $DeleteProtected){if($normal.Equals($protected,[StringComparison]::OrdinalIgnoreCase)-or$normal.StartsWith($protected+'\',[StringComparison]::OrdinalIgnoreCase)){return $true}}
    return $false
}
if(-not$ApproveArchive){throw 'Abbruch: Reine Archivierung erfordert -ApproveArchive.'}
if($null-eq$ArchiveTargets-or$ArchiveTargets.Count-eq 0){$ArchiveTargets=$CopyAllowed}
foreach($target in $ArchiveTargets){$normal=Get-NormalRelativePath $target;if($CopyAllowed-notcontains$normal){throw "Ziel ist nicht COPY_ALLOWED: $normal"}}
$projectFull=[IO.Path]::GetFullPath($ProjectRoot).TrimEnd('\');$archiveFull=[IO.Path]::GetFullPath($ArchiveRoot).TrimEnd('\')
if($archiveFull.Equals($projectFull,[StringComparison]::OrdinalIgnoreCase)-or$archiveFull.StartsWith($projectFull+'\',[StringComparison]::OrdinalIgnoreCase)){throw "Archiv muss ausserhalb des Repositories liegen: $archiveFull"}
$sourceFiles=[Collections.Generic.List[object]]::new()
foreach($target in $ArchiveTargets){
    $normal=Get-NormalRelativePath $target;$source=Join-Path $projectFull $normal
    if(-not(Test-Path -LiteralPath $source)){throw "Archivquelle fehlt: $source"}
    $item=Get-Item -LiteralPath $source;$items=if($item.PSIsContainer){@(Get-ChildItem -LiteralPath $source -File -Force -Recurse)}else{@($item)}
    foreach($file in $items){$sourceFiles.Add([pscustomobject]@{Source=$file.FullName;Relative=$file.FullName.Substring($projectFull.Length+1)})}
}
if($sourceFiles.Count-eq 0){throw 'Keine Dateien fuer Archivierung gefunden.'}
New-Item -ItemType Directory -Path $archiveFull -Force|Out-Null
$manifest=[Collections.Generic.List[object]]::new()
foreach($file in $sourceFiles|Sort-Object Relative -Unique){
    $destination=Join-Path $archiveFull $file.Relative;New-Item -ItemType Directory -Path (Split-Path -Parent $destination) -Force|Out-Null
    Copy-Item -LiteralPath $file.Source -Destination $destination -Force
    $sourceItem=Get-Item -LiteralPath $file.Source;$archiveItem=Get-Item -LiteralPath $destination
    $sourceHash=(Get-FileHash -LiteralPath $file.Source -Algorithm SHA256).Hash;$archiveHash=(Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash
    if($sourceItem.Length-ne$archiveItem.Length-or$sourceHash-ne$archiveHash){throw "Archivpruefung fehlgeschlagen: $($file.Relative)"}
    $manifest.Add([pscustomobject]@{RelativePath=$file.Relative;Bytes=[int64]$sourceItem.Length;SHA256=$sourceHash;SourceLastWriteTimeUtc=$sourceItem.LastWriteTimeUtc.ToString('o');ArchivedPath=$destination;ArchivedBytes=[int64]$archiveItem.Length;ArchivedSHA256=$archiveHash;Verified=$true})
}
$manifestPath=Join-Path $archiveFull 'sha256-manifest.csv';$manifest|Sort-Object RelativePath|Export-Csv -LiteralPath $manifestPath -NoTypeInformation -Encoding utf8
$roundTrip=@(Import-Csv -LiteralPath $manifestPath)
if($roundTrip.Count-ne$manifest.Count-or@($roundTrip|Where-Object{$_.Verified-ne'True'}).Count-ne 0){throw 'Manifest-Roundtrip-Pruefung fehlgeschlagen.'}
Write-Host "Archivierung erfolgreich: $($manifest.Count) Dateien";Write-Host "SHA-256-Manifest: $manifestPath"
Write-Host 'Keine Quelldatei wurde geloescht; dieses Skript enthaelt keine Loeschoperation.'
