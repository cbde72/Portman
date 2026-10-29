# Portman V09 – PDF-Parser-Audit V2 (nur Tests)

Die Testsuite ruft die existierende produktive `portfolio_v5.pdf_importer.parse_pdf()`-Funktion auf, **ohne** Imports in SQLite zu speichern. Original-PDFs und Parser-Dateien werden nicht verändert. Benötigt eine eingerichtete lokale Portman-Umgebung.

## Installation

Kopiere `pdf_parser_audit_v2.py` und `pdf_parser_audit_v1.py` zusammen nach `PortmanNL/tools/` (oder in einen anderen gemeinsamen Ordner). Die Testdatei `test_audit_v2.py` ist optional.

PowerShell im Projektverzeichnis:

```powershell
$env:PYTHONPATH = 'src;.'
python tools/pdf_parser_audit_v2.py --root 'C:\Users\chris\Desktop\history' --allow-ocr --compare 'test_reports\pdf_parser_audit\run_001\audit.json' --output 'test_reports\pdf_parser_audit\v2_run_001'
```

Wenn die V1-Datei an einem anderen Ort liegt, `--compare` entsprechend anpassen. Der alte `audit.json`-Stand muss **nicht** geändert werden.

## Schneller wiederholter Lauf (sicherer Cache)

```powershell
python tools/pdf_parser_audit_v2.py --root 'C:\Users\chris\Desktop\history' --allow-ocr --compare 'test_reports\pdf_parser_audit\v2_run_001\audit.json' --cache 'test_reports\pdf_parser_audit\v2_run_001\audit.json' --output 'test_reports\pdf_parser_audit\v2_run_002'
```

Cache-Treffer setzen gleichen PDF-Hash, identische OCR-Einstellung, denselben Scan-Root und identischen Parser-Code-Fingerprint voraus. Jede Datei wird weiterhin erneut gehasht. Beim Wechsel des Parser-Codes erfolgt automatisch ein kompletter Neuparse; damit sind Regressionen nicht durch alte Cachewerte verdeckt.

## Nur vorherige Fehler / bestimmte Parser oder Fehlergruppen

```powershell
python tools/pdf_parser_audit_v2.py --root 'C:\Users\chris\Desktop\history' --allow-ocr --compare 'test_reports\pdf_parser_audit\v2_run_001\audit.json' --only-errors --output 'test_reports\pdf_parser_audit\errors_only'

python tools/pdf_parser_audit_v2.py --root 'C:\Users\chris\Desktop\history' --allow-ocr --compare 'test_reports\pdf_parser_audit\v2_run_001\audit.json' --plugin 'baader.pdf' --issue-code 'BUY_POSITIVE' --output 'test_reports\pdf_parser_audit\baader_buy_signs'
```

Teillauf-Berichte gelten **nicht** als vollständige Gesamtstatistik; nicht geprüfte Dateien werden nicht als entfernt gezählt.

## Ergebnisse

- `report.md`: kompakter Gesamtbericht, Schweregrad-Verteilung, Fehlergruppen, Parser/Handler und Regressionen.
- `files.csv`: eine Zeile pro PDF mit Parser, Handler, Status, Kategorien und Zählern.
- `findings.csv`: **eine Zeile pro Fehler oder Warnung**, geeignet für systematische Fehlerkorrekturen.
- `delta.csv`: Regressionen, Verbesserungen und sonstige Änderungen gegenüber V1/V2.
- `audit.json`: vollständiger reproduzierbarer Datensatz mit jeder Originalwarnung und jedem Parseergebnis.

## Schweregrade

- `ERROR`: Parser hat eine Fehlermeldung geliefert / Ausnahme ausgelöst.
- `WARNING`: fachlich relevante Auffälligkeit oder generischer Fallback, nicht automatisch ein nachgewiesener Fehler.
- `INFO`: normale Plugin-Erkennungs- und Hinweisnachrichten.
- `PASS`: kein Fehler, keine Warnung, kein Hinweis.

Ein Fallback kann ein erwartetes Dokument sein; ein `PASS` beweist noch nicht die buchhalterische Richtigkeit. Die Klassifizierung ist bewusst überprüfbar und kann weiter verfeinert werden.

**Exit-Code 1** bei Parserfehlern, Plugin-Ladefehlern oder Scanfehlern ist für CI gedacht. Der Bericht wird trotzdem geschrieben. Bei den bekannten 217 Fehlern ist Exit-Code 1 daher erwartbar.

## Tests

```powershell
python -m unittest -v tools/test_audit_v2.py
```

Diese sechs isolierten Unit-Tests prüfen Regelklassifizierung sowie V1-Kompatibilität, Verbesserungen/Regressionen und Teilläufe. Sie benötigen keine privaten PDFs.

## Grenzen

- Keine Beleg-gegen-Sollwert-Prüfung ohne Ground-Truth-Datensätze.
- OCR kann Seiteneffekte in lokal konfigurierten externen OCR-Caches haben; die Testsuite selbst schreibt ausschließlich in ihren angegebenen Ausgabeordner.
- Ein vollständiger Lauf mit geändertem Parsercode benötigt erneut Parsezeit; ein schneller Cache darf keine echten Regressionen unterdrücken.
- Berichte enthalten möglicherweise personenbezogene Dateinamen und Bankreferenzen; nicht öffentlich ins Repository committen.
