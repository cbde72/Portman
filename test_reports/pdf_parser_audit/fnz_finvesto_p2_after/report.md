# Portman – PDF-Parser-Audit V2

- Datum (UTC): `2026-10-25T15:27:25.291133+00:00`
- Quellverzeichnis: `C:\Users\chris\Desktop\history\fnz`
- Modus: `full`; OCR: `True`; Parser-Fingerprint: `95b2e3362f3dc378`
- PDFs im Scope: **22**; eindeutige SHA-256: **13**; Cache-Treffer: **0**
- Plugin-Ladefehler: **0**; Scanfehler: **0**

## Schweregrade

| Grad | PDFs |
|---|---:|
| ERROR | 0 |
| WARNING | 21 |
| INFO | 1 |
| PASS | 0 |

## Befunde (pro Dokument, Kategorien können mehrfach vorkommen)

| Kategorie | Dokumente |
|---|---:|
| `UNCLASSIFIED_WARNING` | 21 |
| `QUANTITY_CONFLICT` | 15 |
| `GENERIC_FALLBACK` | 5 |
| `OCR_LAYOUT` | 3 |
| `MIFID_COST` | 1 |
| `NET_GROSS_MISMATCH` | 1 |

## Parser/Handler

| Plugin | Handler | Dateien | Fehler | Warnungen |
|---|---|---:|---:|---:|
| `fnz.finvesto` | `depotauszug` | 1 | 0 | 0 |
| `fnz.finvesto` | `umsatzabrechnung` | 16 | 0 | 16 |
| `generic.kontoauszug` | `generic` | 5 | 0 | 5 |

## Vergleich mit Baseline

Verglichen: **0**, Verbesserungen: **0**, Regressionen: **0**, veränderte Befunde: **0**, neu: **22**.

### Regressionen (max. 100, vollständige Liste in delta.csv)


### Verbesserungen (max. 100, vollständige Liste in delta.csv)


## Einzelbefunde

Vollständig in `findings.csv` (jede Meldung einzeln), `files.csv` und `audit.json`. Der Markdownbericht enthält nur die ersten 150 ERROR/ WARNING-Dateien.

- **WARNING** `IndividuelleKosteninformationEx-postaggregiert-2026-07-06.pdf` · `generic.kontoauszug/generic` · GENERIC_FALLBACK, MIFID_COST, UNCLASSIFIED_WARNING
- **WARNING** `OnlineAuszug-Nr4-2024-09-20.pdf` · `generic.kontoauszug/generic` · GENERIC_FALLBACK, UNCLASSIFIED_WARNING
- **WARNING** `OnlineAuszug-Nr4-2025-05-23.pdf` · `generic.kontoauszug/generic` · GENERIC_FALLBACK, UNCLASSIFIED_WARNING
- **WARNING** `OnlineAuszug-Nr45-2023-12-29.pdf` · `fnz.finvesto/umsatzabrechnung` · NET_GROSS_MISMATCH, OCR_LAYOUT, QUANTITY_CONFLICT, UNCLASSIFIED_WARNING
- **WARNING** `OnlineAuszug-Nr58-2025-03-28.pdf` · `fnz.finvesto/umsatzabrechnung` · OCR_LAYOUT, QUANTITY_CONFLICT, UNCLASSIFIED_WARNING
- **WARNING** `OnlineAuszug-Nr60-2025-05-01.pdf` · `fnz.finvesto/umsatzabrechnung` · OCR_LAYOUT, QUANTITY_CONFLICT, UNCLASSIFIED_WARNING
- **WARNING** `OnlineAuszug-Nr71-2025-12-24.pdf` · `fnz.finvesto/umsatzabrechnung` · QUANTITY_CONFLICT, UNCLASSIFIED_WARNING
- **WARNING** `OnlineAuszug-Nr79-2026-04-29.pdf` · `fnz.finvesto/umsatzabrechnung` · QUANTITY_CONFLICT, UNCLASSIFIED_WARNING
- **WARNING** `OnlineAuszug-Nr81-2026-06-24.pdf` · `fnz.finvesto/umsatzabrechnung` · UNCLASSIFIED_WARNING
- **WARNING** `OnlineAuszug-Nr88-2026-10-06 (1).pdf` · `fnz.finvesto/umsatzabrechnung` · QUANTITY_CONFLICT, UNCLASSIFIED_WARNING
- **WARNING** `OnlineAuszug-Nr88-2026-10-06-1 (1).pdf` · `fnz.finvesto/umsatzabrechnung` · QUANTITY_CONFLICT, UNCLASSIFIED_WARNING
- **WARNING** `OnlineAuszug-Nr88-2026-10-06-1.pdf` · `fnz.finvesto/umsatzabrechnung` · QUANTITY_CONFLICT, UNCLASSIFIED_WARNING
- **WARNING** `OnlineAuszug-Nr88-2026-10-06-2 (1).pdf` · `fnz.finvesto/umsatzabrechnung` · QUANTITY_CONFLICT, UNCLASSIFIED_WARNING
- **WARNING** `OnlineAuszug-Nr88-2026-10-06-2.pdf` · `fnz.finvesto/umsatzabrechnung` · QUANTITY_CONFLICT, UNCLASSIFIED_WARNING
- **WARNING** `OnlineAuszug-Nr88-2026-10-06-3 (1).pdf` · `fnz.finvesto/umsatzabrechnung` · QUANTITY_CONFLICT, UNCLASSIFIED_WARNING
- **WARNING** `OnlineAuszug-Nr88-2026-10-06-3.pdf` · `fnz.finvesto/umsatzabrechnung` · QUANTITY_CONFLICT, UNCLASSIFIED_WARNING
- **WARNING** `OnlineAuszug-Nr88-2026-10-06-4 (1).pdf` · `fnz.finvesto/umsatzabrechnung` · QUANTITY_CONFLICT, UNCLASSIFIED_WARNING
- **WARNING** `OnlineAuszug-Nr88-2026-10-06-4.pdf` · `fnz.finvesto/umsatzabrechnung` · QUANTITY_CONFLICT, UNCLASSIFIED_WARNING
- **WARNING** `OnlineAuszug-Nr88-2026-10-06.pdf` · `fnz.finvesto/umsatzabrechnung` · QUANTITY_CONFLICT, UNCLASSIFIED_WARNING
- **WARNING** `OnlineAuszug-Nr9-2023-08-22.pdf` · `generic.kontoauszug/generic` · GENERIC_FALLBACK, UNCLASSIFIED_WARNING
- **WARNING** `VL-Information-2026-08-13.pdf` · `generic.kontoauszug/generic` · GENERIC_FALLBACK, UNCLASSIFIED_WARNING

## Grenzen

- Klassifikationen sind regelbasierte Priorisierung, **kein** Beweis, dass Beträge fachlich korrekt oder fehlerhaft sind.
- `INFO` umfasst z. B. normale Plugin-Erkennungsnachrichten; `WARNING` enthält auffällige Vorzeichen und Brutto-Netto-Werte.
- Die Suite führt `parse_pdf()` aus und schreibt keinerlei Portman-Datenbankeinträge.
- Optionaler Cache nutzt Dateigröße, mtime_ns, SHA-256, OCR-Modus und Parser-Fingerprint; SHA wird auch bei Cache-Treffern neu berechnet.
- Für schnelle gezielte Läufe `--only-errors`, `--plugin` und `--issue-code` verwenden; mit `--compare` zu V1/V2 vergleichen.
- Historische Baselines unter `test_reports` unverändert aufbewahren. Berichte nicht öffentlich teilen (Dateinamen/Belegdetails).
