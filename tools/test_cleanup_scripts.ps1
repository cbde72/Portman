Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$ScriptRoot=Split-Path -Parent $MyInvocation.MyCommand.Path
$Preview=Join-Path $ScriptRoot 'cleanup_preview.ps1';$Execute=Join-Path $ScriptRoot 'cleanup_execute.ps1'
$failures=[Collections.Generic.List[string]]::new()
function Assert-True([bool]$Condition,[string]$Message){if(-not$Condition){$failures.Add($Message)}}
$previewText=Get-Content -Raw -LiteralPath $Preview;$executeText=Get-Content -Raw -LiteralPath $Execute
Assert-True ($executeText-notmatch'(?im)^\s*Remove-Item\b') 'Execute must contain no Remove-Item.'
Assert-True ($executeText-notmatch'(?im)^\s*(del|erase|rd|rmdir)\b') 'Execute must contain no deletion command.'
Assert-True ($executeText-match[regex]::Escape('C:\Users\chris\Desktop\Portman_Cleanup_Backup\Final_Archive_20261027')) 'External archive root missing.'
Assert-True ($executeText-match"'test_reports\\pdf_parser_audit\\run_001'") 'run_001 is not COPY_ALLOWED.'
Assert-True ($executeText-match"'data','.tmp','tmp'") 'Broad protected directories missing.'
Assert-True ($previewText-match'DELETE_PROTECTED') 'Preview does not display DELETE_PROTECTED.'
$testBase=Join-Path ([IO.Path]::GetTempPath()) ('portman-cleanup-test-'+[guid]::NewGuid().ToString('N'))
$fixtureRoot=Join-Path $testBase 'repo';$archiveRoot=Join-Path $testBase 'archive'
try{
    New-Item -ItemType Directory -Path (Join-Path $fixtureRoot 'tools') -Force|Out-Null
    $fixture=Join-Path $fixtureRoot 'tools\README.md';[IO.File]::WriteAllText($fixture,"sensitive-test-fixture`n",[Text.UTF8Encoding]::new($false))
    & $Execute -ApproveArchive -ProjectRoot $fixtureRoot -ArchiveRoot $archiveRoot -ArchiveTargets 'tools\README.md'
    $archived=Join-Path $archiveRoot 'tools\README.md';$manifestPath=Join-Path $archiveRoot 'sha256-manifest.csv'
    Assert-True (Test-Path -LiteralPath $fixture -PathType Leaf) 'Source was removed or moved.'
    Assert-True (Test-Path -LiteralPath $archived -PathType Leaf) 'Archive copy missing.'
    Assert-True (Test-Path -LiteralPath $manifestPath -PathType Leaf) 'Manifest missing.'
    Assert-True ((Get-Item $fixture).Length-eq(Get-Item $archived).Length) 'Archived size differs.'
    Assert-True ((Get-FileHash $fixture).Hash-eq(Get-FileHash $archived).Hash) 'Archived SHA-256 differs.'
    $manifest=@(Import-Csv -LiteralPath $manifestPath)
    Assert-True ($manifest.Count-eq 1) 'Manifest entry count differs.'
    Assert-True ($manifest[0].Verified-eq'True') 'Manifest entry is not verified.'
}finally{if(Test-Path -LiteralPath $testBase){Remove-Item -LiteralPath $testBase -Recurse -Force}}
if($failures.Count){$failures|ForEach-Object{Write-Error $_};exit 1}
Write-Host 'PASS: protection lists, external archive guard, copy, size and SHA-256 verification.'
