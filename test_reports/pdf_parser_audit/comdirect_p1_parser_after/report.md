# Portman – PDF-Parser-Audit V2

- Datum (UTC): `2026-10-25T10:02:17.423786+00:00`
- Quellverzeichnis: `C:\Users\chris\Desktop\history`
- Modus: `targeted`; OCR: `False`; Parser-Fingerprint: `ad82dfb95b4bc879`
- PDFs im Scope: **24**; eindeutige SHA-256: **15**; Cache-Treffer: **0**
- Plugin-Ladefehler: **0**; Scanfehler: **0**

## Schweregrade

| Grad | PDFs |
|---|---:|
| ERROR | 2 |
| WARNING | 22 |
| INFO | 0 |
| PASS | 0 |

## Befunde (pro Dokument, Kategorien können mehrfach vorkommen)

| Kategorie | Dokumente |
|---|---:|
| `UNCLASSIFIED_WARNING` | 19 |
| `QUANTITY_CONFLICT` | 15 |
| `OCR_LAYOUT` | 4 |
| `DIVIDEND_TAX` | 3 |
| `PARSER_ERROR` | 2 |
| `MIFID_COST` | 1 |
| `NET_GROSS_MISMATCH` | 1 |

## Parser/Handler

| Plugin | Handler | Dateien | Fehler | Warnungen |
|---|---|---:|---:|---:|
| `(kein Plugin)` | `-` | 2 | 2 | 0 |
| `fnz.finvesto` | `umsatzabrechnung` | 15 | 0 | 15 |
| `user.deka-quartalsbericht` | `quartalsbericht` | 7 | 0 | 7 |

## Vergleich mit Baseline

Verglichen: **24**, Verbesserungen: **22**, Regressionen: **22**, veränderte Befunde: **22**, neu: **0**.
**Teillauf:** Nicht im Scope enthaltene PDFs gelten nicht als entfernt.

### Regressionen (max. 100, vollständige Liste in delta.csv)

- `Deka/Jahresabschlüsse/DEKA20131231_19013465.pdf`: ERROR → WARNING (PARSER_ERROR → UNCLASSIFIED_WARNING)
- `Deka/Jahresabschlüsse/DEKA20141231_21006142.pdf`: ERROR → WARNING (OCR_FAILED,PARSER_ERROR → UNCLASSIFIED_WARNING)
- `Deka/Jahresabschlüsse/DEKA20161231_25781817.pdf`: ERROR → WARNING (OCR_FAILED,PARSER_ERROR → DIVIDEND_TAX)
- `Deka/Jahresabschlüsse/DEKA20171231_29524960.pdf`: ERROR → WARNING (OCR_FAILED,PARSER_ERROR → DIVIDEND_TAX)
- `Deka/Jahresabschlüsse/DEKA20181231_34032032.pdf`: ERROR → WARNING (PARSER_ERROR → UNCLASSIFIED_WARNING)
- `Deka/Jahresabschlüsse/DEKA20191231_41371929.pdf`: ERROR → WARNING (PARSER_ERROR → UNCLASSIFIED_WARNING)
- `Deka/Quartalsbericht/DEKA20200331_44534894.pdf`: ERROR → WARNING (PARSER_ERROR → DIVIDEND_TAX,MIFID_COST)
- `fnz/OnlineAuszug-Nr45-2023-12-29.pdf`: ERROR → WARNING (OCR_LAYOUT,PARSER_ERROR → NET_GROSS_MISMATCH,OCR_LAYOUT,QUANTITY_CONFLICT,UNCLASSIFIED_WARNING)
- `fnz/OnlineAuszug-Nr58-2025-03-28.pdf`: ERROR → WARNING (OCR_LAYOUT,PARSER_ERROR → OCR_LAYOUT,QUANTITY_CONFLICT,UNCLASSIFIED_WARNING)
- `fnz/OnlineAuszug-Nr60-2025-05-01.pdf`: ERROR → WARNING (OCR_LAYOUT,PARSER_ERROR → OCR_LAYOUT,QUANTITY_CONFLICT,UNCLASSIFIED_WARNING)
- `fnz/OnlineAuszug-Nr71-2025-12-24.pdf`: ERROR → WARNING (PARSER_ERROR → QUANTITY_CONFLICT,UNCLASSIFIED_WARNING)
- `fnz/OnlineAuszug-Nr79-2026-04-29.pdf`: ERROR → WARNING (PARSER_ERROR → QUANTITY_CONFLICT,UNCLASSIFIED_WARNING)
- `fnz/OnlineAuszug-Nr88-2026-10-06 (1).pdf`: ERROR → WARNING (PARSER_ERROR → QUANTITY_CONFLICT,UNCLASSIFIED_WARNING)
- `fnz/OnlineAuszug-Nr88-2026-10-06-1 (1).pdf`: ERROR → WARNING (PARSER_ERROR → QUANTITY_CONFLICT,UNCLASSIFIED_WARNING)
- `fnz/OnlineAuszug-Nr88-2026-10-06-1.pdf`: ERROR → WARNING (PARSER_ERROR → QUANTITY_CONFLICT,UNCLASSIFIED_WARNING)
- `fnz/OnlineAuszug-Nr88-2026-10-06-2 (1).pdf`: ERROR → WARNING (PARSER_ERROR → QUANTITY_CONFLICT,UNCLASSIFIED_WARNING)
- `fnz/OnlineAuszug-Nr88-2026-10-06-2.pdf`: ERROR → WARNING (PARSER_ERROR → QUANTITY_CONFLICT,UNCLASSIFIED_WARNING)
- `fnz/OnlineAuszug-Nr88-2026-10-06-3 (1).pdf`: ERROR → WARNING (PARSER_ERROR → QUANTITY_CONFLICT,UNCLASSIFIED_WARNING)
- `fnz/OnlineAuszug-Nr88-2026-10-06-3.pdf`: ERROR → WARNING (PARSER_ERROR → QUANTITY_CONFLICT,UNCLASSIFIED_WARNING)
- `fnz/OnlineAuszug-Nr88-2026-10-06-4 (1).pdf`: ERROR → WARNING (PARSER_ERROR → QUANTITY_CONFLICT,UNCLASSIFIED_WARNING)
- `fnz/OnlineAuszug-Nr88-2026-10-06-4.pdf`: ERROR → WARNING (PARSER_ERROR → QUANTITY_CONFLICT,UNCLASSIFIED_WARNING)
- `fnz/OnlineAuszug-Nr88-2026-10-06.pdf`: ERROR → WARNING (PARSER_ERROR → QUANTITY_CONFLICT,UNCLASSIFIED_WARNING)

### Verbesserungen (max. 100, vollständige Liste in delta.csv)

- `Deka/Jahresabschlüsse/DEKA20131231_19013465.pdf`: ERROR → WARNING (PARSER_ERROR → UNCLASSIFIED_WARNING)
- `Deka/Jahresabschlüsse/DEKA20141231_21006142.pdf`: ERROR → WARNING (OCR_FAILED,PARSER_ERROR → UNCLASSIFIED_WARNING)
- `Deka/Jahresabschlüsse/DEKA20161231_25781817.pdf`: ERROR → WARNING (OCR_FAILED,PARSER_ERROR → DIVIDEND_TAX)
- `Deka/Jahresabschlüsse/DEKA20171231_29524960.pdf`: ERROR → WARNING (OCR_FAILED,PARSER_ERROR → DIVIDEND_TAX)
- `Deka/Jahresabschlüsse/DEKA20181231_34032032.pdf`: ERROR → WARNING (PARSER_ERROR → UNCLASSIFIED_WARNING)
- `Deka/Jahresabschlüsse/DEKA20191231_41371929.pdf`: ERROR → WARNING (PARSER_ERROR → UNCLASSIFIED_WARNING)
- `Deka/Quartalsbericht/DEKA20200331_44534894.pdf`: ERROR → WARNING (PARSER_ERROR → DIVIDEND_TAX,MIFID_COST)
- `fnz/OnlineAuszug-Nr45-2023-12-29.pdf`: ERROR → WARNING (OCR_LAYOUT,PARSER_ERROR → NET_GROSS_MISMATCH,OCR_LAYOUT,QUANTITY_CONFLICT,UNCLASSIFIED_WARNING)
- `fnz/OnlineAuszug-Nr58-2025-03-28.pdf`: ERROR → WARNING (OCR_LAYOUT,PARSER_ERROR → OCR_LAYOUT,QUANTITY_CONFLICT,UNCLASSIFIED_WARNING)
- `fnz/OnlineAuszug-Nr60-2025-05-01.pdf`: ERROR → WARNING (OCR_LAYOUT,PARSER_ERROR → OCR_LAYOUT,QUANTITY_CONFLICT,UNCLASSIFIED_WARNING)
- `fnz/OnlineAuszug-Nr71-2025-12-24.pdf`: ERROR → WARNING (PARSER_ERROR → QUANTITY_CONFLICT,UNCLASSIFIED_WARNING)
- `fnz/OnlineAuszug-Nr79-2026-04-29.pdf`: ERROR → WARNING (PARSER_ERROR → QUANTITY_CONFLICT,UNCLASSIFIED_WARNING)
- `fnz/OnlineAuszug-Nr88-2026-10-06 (1).pdf`: ERROR → WARNING (PARSER_ERROR → QUANTITY_CONFLICT,UNCLASSIFIED_WARNING)
- `fnz/OnlineAuszug-Nr88-2026-10-06-1 (1).pdf`: ERROR → WARNING (PARSER_ERROR → QUANTITY_CONFLICT,UNCLASSIFIED_WARNING)
- `fnz/OnlineAuszug-Nr88-2026-10-06-1.pdf`: ERROR → WARNING (PARSER_ERROR → QUANTITY_CONFLICT,UNCLASSIFIED_WARNING)
- `fnz/OnlineAuszug-Nr88-2026-10-06-2 (1).pdf`: ERROR → WARNING (PARSER_ERROR → QUANTITY_CONFLICT,UNCLASSIFIED_WARNING)
- `fnz/OnlineAuszug-Nr88-2026-10-06-2.pdf`: ERROR → WARNING (PARSER_ERROR → QUANTITY_CONFLICT,UNCLASSIFIED_WARNING)
- `fnz/OnlineAuszug-Nr88-2026-10-06-3 (1).pdf`: ERROR → WARNING (PARSER_ERROR → QUANTITY_CONFLICT,UNCLASSIFIED_WARNING)
- `fnz/OnlineAuszug-Nr88-2026-10-06-3.pdf`: ERROR → WARNING (PARSER_ERROR → QUANTITY_CONFLICT,UNCLASSIFIED_WARNING)
- `fnz/OnlineAuszug-Nr88-2026-10-06-4 (1).pdf`: ERROR → WARNING (PARSER_ERROR → QUANTITY_CONFLICT,UNCLASSIFIED_WARNING)
- `fnz/OnlineAuszug-Nr88-2026-10-06-4.pdf`: ERROR → WARNING (PARSER_ERROR → QUANTITY_CONFLICT,UNCLASSIFIED_WARNING)
- `fnz/OnlineAuszug-Nr88-2026-10-06.pdf`: ERROR → WARNING (PARSER_ERROR → QUANTITY_CONFLICT,UNCLASSIFIED_WARNING)

## Einzelbefunde

Vollständig in `findings.csv` (jede Meldung einzeln), `files.csv` und `audit.json`. Der Markdownbericht enthält nur die ersten 150 ERROR/ WARNING-Dateien.

- **ERROR** `comdirect/Steuermitteilungen/Steuermitteilung_WKN_A111X9(IS_C.MSCI_EMIMI_U.ETF_DLA)_vom_04.01.2021_B861D7.pdf` · `/` · OCR_LAYOUT, PARSER_ERROR
- **WARNING** `Deka/Jahresabschlüsse/DEKA20131231_19013465.pdf` · `user.deka-quartalsbericht/quartalsbericht` · UNCLASSIFIED_WARNING
- **WARNING** `Deka/Jahresabschlüsse/DEKA20141231_21006142.pdf` · `user.deka-quartalsbericht/quartalsbericht` · UNCLASSIFIED_WARNING
- **WARNING** `Deka/Jahresabschlüsse/DEKA20161231_25781817.pdf` · `user.deka-quartalsbericht/quartalsbericht` · DIVIDEND_TAX
- **WARNING** `Deka/Jahresabschlüsse/DEKA20171231_29524960.pdf` · `user.deka-quartalsbericht/quartalsbericht` · DIVIDEND_TAX
- **WARNING** `Deka/Jahresabschlüsse/DEKA20181231_34032032.pdf` · `user.deka-quartalsbericht/quartalsbericht` · UNCLASSIFIED_WARNING
- **WARNING** `Deka/Jahresabschlüsse/DEKA20191231_41371929.pdf` · `user.deka-quartalsbericht/quartalsbericht` · UNCLASSIFIED_WARNING
- **WARNING** `Deka/Quartalsbericht/DEKA20200331_44534894.pdf` · `user.deka-quartalsbericht/quartalsbericht` · DIVIDEND_TAX, MIFID_COST
- **WARNING** `fnz/OnlineAuszug-Nr45-2023-12-29.pdf` · `fnz.finvesto/umsatzabrechnung` · NET_GROSS_MISMATCH, OCR_LAYOUT, QUANTITY_CONFLICT, UNCLASSIFIED_WARNING
- **WARNING** `fnz/OnlineAuszug-Nr58-2025-03-28.pdf` · `fnz.finvesto/umsatzabrechnung` · OCR_LAYOUT, QUANTITY_CONFLICT, UNCLASSIFIED_WARNING
- **WARNING** `fnz/OnlineAuszug-Nr60-2025-05-01.pdf` · `fnz.finvesto/umsatzabrechnung` · OCR_LAYOUT, QUANTITY_CONFLICT, UNCLASSIFIED_WARNING
- **WARNING** `fnz/OnlineAuszug-Nr71-2025-12-24.pdf` · `fnz.finvesto/umsatzabrechnung` · QUANTITY_CONFLICT, UNCLASSIFIED_WARNING
- **WARNING** `fnz/OnlineAuszug-Nr79-2026-04-29.pdf` · `fnz.finvesto/umsatzabrechnung` · QUANTITY_CONFLICT, UNCLASSIFIED_WARNING
- **ERROR** `fnz/OnlineAuszug-Nr81-2026-06-24.pdf` · `/` · PARSER_ERROR
- **WARNING** `fnz/OnlineAuszug-Nr88-2026-10-06 (1).pdf` · `fnz.finvesto/umsatzabrechnung` · QUANTITY_CONFLICT, UNCLASSIFIED_WARNING
- **WARNING** `fnz/OnlineAuszug-Nr88-2026-10-06-1 (1).pdf` · `fnz.finvesto/umsatzabrechnung` · QUANTITY_CONFLICT, UNCLASSIFIED_WARNING
- **WARNING** `fnz/OnlineAuszug-Nr88-2026-10-06-1.pdf` · `fnz.finvesto/umsatzabrechnung` · QUANTITY_CONFLICT, UNCLASSIFIED_WARNING
- **WARNING** `fnz/OnlineAuszug-Nr88-2026-10-06-2 (1).pdf` · `fnz.finvesto/umsatzabrechnung` · QUANTITY_CONFLICT, UNCLASSIFIED_WARNING
- **WARNING** `fnz/OnlineAuszug-Nr88-2026-10-06-2.pdf` · `fnz.finvesto/umsatzabrechnung` · QUANTITY_CONFLICT, UNCLASSIFIED_WARNING
- **WARNING** `fnz/OnlineAuszug-Nr88-2026-10-06-3 (1).pdf` · `fnz.finvesto/umsatzabrechnung` · QUANTITY_CONFLICT, UNCLASSIFIED_WARNING
- **WARNING** `fnz/OnlineAuszug-Nr88-2026-10-06-3.pdf` · `fnz.finvesto/umsatzabrechnung` · QUANTITY_CONFLICT, UNCLASSIFIED_WARNING
- **WARNING** `fnz/OnlineAuszug-Nr88-2026-10-06-4 (1).pdf` · `fnz.finvesto/umsatzabrechnung` · QUANTITY_CONFLICT, UNCLASSIFIED_WARNING
- **WARNING** `fnz/OnlineAuszug-Nr88-2026-10-06-4.pdf` · `fnz.finvesto/umsatzabrechnung` · QUANTITY_CONFLICT, UNCLASSIFIED_WARNING
- **WARNING** `fnz/OnlineAuszug-Nr88-2026-10-06.pdf` · `fnz.finvesto/umsatzabrechnung` · QUANTITY_CONFLICT, UNCLASSIFIED_WARNING

## Grenzen

- Klassifikationen sind regelbasierte Priorisierung, **kein** Beweis, dass Beträge fachlich korrekt oder fehlerhaft sind.
- `INFO` umfasst z. B. normale Plugin-Erkennungsnachrichten; `WARNING` enthält auffällige Vorzeichen und Brutto-Netto-Werte.
- Die Suite führt `parse_pdf()` aus und schreibt keinerlei Portman-Datenbankeinträge.
- Optionaler Cache nutzt Dateigröße, mtime_ns, SHA-256, OCR-Modus und Parser-Fingerprint; SHA wird auch bei Cache-Treffern neu berechnet.
- Für schnelle gezielte Läufe `--only-errors`, `--plugin` und `--issue-code` verwenden; mit `--compare` zu V1/V2 vergleichen.
- Historische Baselines unter `test_reports` unverändert aufbewahren. Berichte nicht öffentlich teilen (Dateinamen/Belegdetails).
