# Portman V09 – sichere Cleanup-Archivierung

## Umfang und Schutzmodell

Die Skripte kopieren ausschließlich explizit gelistete Audit- und Berichtsdaten nach
`C:\Users\chris\Desktop\Portman_Cleanup_Backup\Final_Archive_20261027`. Sie enthalten keine
Löschoperation. `COPY_ALLOWED` und `DELETE_PROTECTED` sind getrennt; `run_001` ist kopierbar und
gleichzeitig löschgeschützt. Das Archivziel wird abgelehnt, wenn es im Repository liegt. Absolute
Quellpfade, `..` und Wildcards sind unzulässig. Jede Kopie wird per Dateigröße und SHA-256 geprüft;
das vollständige Manifest wird danach erneut eingelesen und validiert. Finanzdaten bleiben damit
außerhalb des Git-Repositories und dürfen nicht in öffentliche Repositories übertragen werden.

## V3-Fehlerdiagnose

Alle 3.736 Datensätze in `v3_full_utf8/audit.json` enthalten denselben Traceback. Der Worker lief
aus `.worktrees\pdf-parser-audit-v3` und konnte beim Import von `portfolio_v5.pdf_importer` das
Top-Level-Paket `pdf_plugins` nicht finden: `ModuleNotFoundError: No module named 'pdf_plugins'`.
Nicht die PDF-Textextraktion war defekt. `TEXT_EXTRACTION` ist eine Fehlklassifikation: Die breite
Regel reagiert auch auf `OCR`, das im Traceback als `args.allow_ocr` vorkommt.

Der erfolgreiche 23-PDF-Nachtest verwendete einen Werkzeugstand, der Projekt-Root und `src` in
`sys.path` einträgt. Der aktuelle Wrapper setzt zusätzlich beide Verzeichnisse in `PYTHONPATH` und
prüft vor dem Start den Import. Die unterschiedlichen Parser-Fingerprints (`0c5108…` gegenüber
`0dda6c…`) belegen unterschiedliche Auditstände. OCR und die PDFs sind nicht die Ursache.

## Sicherer neuer Vollaudit (nicht ausgeführt)

Zuerst nur die Umgebung prüfen:

```powershell
Set-Location 'C:\Users\chris\Desktop\programming\PortmanNL'
$env:PYTHONPATH = 'C:\Users\chris\Desktop\programming\PortmanNL;C:\Users\chris\Desktop\programming\PortmanNL\src'
python -X utf8 -c "import pdf_plugins; import portfolio_v5.pdf_importer; print('IMPORT_OK')"
```

Erst nach `IMPORT_OK` einen neuen Ausgabeordner verwenden und nie den fehlerhaften Lauf fortsetzen:

```powershell
& 'C:\Users\chris\Desktop\programming\PortmanNL\tools\powershell_audit_v3.ps1' `
  -PdfRoot 'C:\Users\chris\Desktop\history' `
  -Baseline 'C:\Users\chris\Desktop\programming\PortmanNL\test_reports\pdf_parser_audit\run_001\audit.json' `
  -Output 'C:\Users\chris\Desktop\programming\PortmanNL\test_reports\pdf_parser_audit\v3_full_utf8_rerun_20261027' `
  -Timeout 300
```
