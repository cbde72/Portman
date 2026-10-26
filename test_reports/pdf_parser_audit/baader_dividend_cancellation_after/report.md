# Portman – PDF-Parser-Audit V2

- Datum (UTC): `2026-10-25T18:50:07.137165+00:00`
- Quellverzeichnis: `C:\Users\chris\Desktop\history`
- Modus: `targeted`; OCR: `False`; Parser-Fingerprint: `edae59e2f9beb747`
- PDFs im Scope: **3**; eindeutige SHA-256: **1**; Cache-Treffer: **0**
- Plugin-Ladefehler: **0**; Scanfehler: **0**

## Schweregrade

| Grad | PDFs |
|---|---:|
| ERROR | 0 |
| WARNING | 3 |
| INFO | 0 |
| PASS | 0 |

## Befunde (pro Dokument, Kategorien können mehrfach vorkommen)

| Kategorie | Dokumente |
|---|---:|
| `DIVIDEND_TAX` | 3 |

## Parser/Handler

| Plugin | Handler | Dateien | Fehler | Warnungen |
|---|---|---:|---:|---:|
| `baader.pdf` | `dividende` | 3 | 0 | 3 |

## Vergleich mit Baseline

Verglichen: **3**, Verbesserungen: **3**, Regressionen: **3**, veränderte Befunde: **3**, neu: **0**.
**Teillauf:** Nicht im Scope enthaltene PDFs gelten nicht als entfernt.

### Regressionen (max. 100, vollständige Liste in delta.csv)

- `baader/3128164_20261007 (1)/3128164/PDF/20240227/3128164_01_0__26172813_wertpapier-ereignis-swift-faehig_526758625_20240227.pdf`: ERROR → WARNING (CANCELLATION → DIVIDEND_TAX)
- `baader/3128164_20261007 (1)/3128164/PDF/3128164_01_0__26172813_wertpapier-ereignis-swift-faehig_526758625_20240227.pdf`: ERROR → WARNING (CANCELLATION → DIVIDEND_TAX)
- `baader/3128164_20261009/3128164/PDF/20240227/3128164_01_0__26172813_wertpapier-ereignis-swift-faehig_526758625_20240227.pdf`: ERROR → WARNING (CANCELLATION → DIVIDEND_TAX)

### Verbesserungen (max. 100, vollständige Liste in delta.csv)

- `baader/3128164_20261007 (1)/3128164/PDF/20240227/3128164_01_0__26172813_wertpapier-ereignis-swift-faehig_526758625_20240227.pdf`: ERROR → WARNING (CANCELLATION → DIVIDEND_TAX)
- `baader/3128164_20261007 (1)/3128164/PDF/3128164_01_0__26172813_wertpapier-ereignis-swift-faehig_526758625_20240227.pdf`: ERROR → WARNING (CANCELLATION → DIVIDEND_TAX)
- `baader/3128164_20261009/3128164/PDF/20240227/3128164_01_0__26172813_wertpapier-ereignis-swift-faehig_526758625_20240227.pdf`: ERROR → WARNING (CANCELLATION → DIVIDEND_TAX)

## Einzelbefunde

Vollständig in `findings.csv` (jede Meldung einzeln), `files.csv` und `audit.json`. Der Markdownbericht enthält nur die ersten 150 ERROR/ WARNING-Dateien.

- **WARNING** `baader/3128164_20261007 (1)/3128164/PDF/20240227/3128164_01_0__26172813_wertpapier-ereignis-swift-faehig_526758625_20240227.pdf` · `baader.pdf/dividende` · DIVIDEND_TAX
- **WARNING** `baader/3128164_20261007 (1)/3128164/PDF/3128164_01_0__26172813_wertpapier-ereignis-swift-faehig_526758625_20240227.pdf` · `baader.pdf/dividende` · DIVIDEND_TAX
- **WARNING** `baader/3128164_20261009/3128164/PDF/20240227/3128164_01_0__26172813_wertpapier-ereignis-swift-faehig_526758625_20240227.pdf` · `baader.pdf/dividende` · DIVIDEND_TAX

## Grenzen

- Klassifikationen sind regelbasierte Priorisierung, **kein** Beweis, dass Beträge fachlich korrekt oder fehlerhaft sind.
- `INFO` umfasst z. B. normale Plugin-Erkennungsnachrichten; `WARNING` enthält auffällige Vorzeichen und Brutto-Netto-Werte.
- Die Suite führt `parse_pdf()` aus und schreibt keinerlei Portman-Datenbankeinträge.
- Optionaler Cache nutzt Dateigröße, mtime_ns, SHA-256, OCR-Modus und Parser-Fingerprint; SHA wird auch bei Cache-Treffern neu berechnet.
- Für schnelle gezielte Läufe `--only-errors`, `--plugin` und `--issue-code` verwenden; mit `--compare` zu V1/V2 vergleichen.
- Historische Baselines unter `test_reports` unverändert aufbewahren. Berichte nicht öffentlich teilen (Dateinamen/Belegdetails).
