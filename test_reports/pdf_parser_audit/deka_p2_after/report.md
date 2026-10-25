# Portman – PDF-Parser-Audit V2

- Datum (UTC): `2026-10-25T18:36:52.883961+00:00`
- Quellverzeichnis: `C:\Users\chris\Desktop\history\Deka`
- Modus: `full`; OCR: `True`; Parser-Fingerprint: `9bcd330a1c0c6b14`
- PDFs im Scope: **38**; eindeutige SHA-256: **38**; Cache-Treffer: **0**
- Plugin-Ladefehler: **0**; Scanfehler: **0**

## Schweregrade

| Grad | PDFs |
|---|---:|
| ERROR | 0 |
| WARNING | 23 |
| INFO | 15 |
| PASS | 0 |

## Befunde (pro Dokument, Kategorien können mehrfach vorkommen)

| Kategorie | Dokumente |
|---|---:|
| `DIVIDEND_TAX` | 20 |
| `MIFID_COST` | 8 |
| `GENERIC_FALLBACK` | 3 |
| `UNCLASSIFIED_WARNING` | 3 |
| `OCR_FAILED` | 3 |

## Parser/Handler

| Plugin | Handler | Dateien | Fehler | Warnungen |
|---|---|---:|---:|---:|
| `generic.kontoauszug` | `generic` | 3 | 0 | 3 |
| `user.deka-quartalsbericht` | `quartalsbericht` | 35 | 0 | 20 |

## Vergleich mit Baseline

Verglichen: **0**, Verbesserungen: **0**, Regressionen: **0**, veränderte Befunde: **0**, neu: **38**.

### Regressionen (max. 100, vollständige Liste in delta.csv)


### Verbesserungen (max. 100, vollständige Liste in delta.csv)


## Einzelbefunde

Vollständig in `findings.csv` (jede Meldung einzeln), `files.csv` und `audit.json`. Der Markdownbericht enthält nur die ersten 150 ERROR/ WARNING-Dateien.

- **WARNING** `DEKA20221231_99640415.pdf` · `generic.kontoauszug/generic` · GENERIC_FALLBACK, UNCLASSIFIED_WARNING
- **WARNING** `DEKA20231231_138491488.pdf` · `generic.kontoauszug/generic` · GENERIC_FALLBACK, UNCLASSIFIED_WARNING
- **WARNING** `DEKA20241231_174937504.pdf` · `generic.kontoauszug/generic` · GENERIC_FALLBACK, UNCLASSIFIED_WARNING
- **WARNING** `Jahresabschlüsse/DEKA20131231_19013465.pdf` · `user.deka-quartalsbericht/quartalsbericht` · DIVIDEND_TAX
- **WARNING** `Jahresabschlüsse/DEKA20141231_21006142.pdf` · `user.deka-quartalsbericht/quartalsbericht` · DIVIDEND_TAX, OCR_FAILED
- **WARNING** `Jahresabschlüsse/DEKA20161231_25781817.pdf` · `user.deka-quartalsbericht/quartalsbericht` · DIVIDEND_TAX, OCR_FAILED
- **WARNING** `Jahresabschlüsse/DEKA20171231_29524960.pdf` · `user.deka-quartalsbericht/quartalsbericht` · DIVIDEND_TAX, OCR_FAILED
- **WARNING** `Jahresabschlüsse/DEKA20181231_34032032.pdf` · `user.deka-quartalsbericht/quartalsbericht` · DIVIDEND_TAX
- **WARNING** `Jahresabschlüsse/DEKA20191231_41371929.pdf` · `user.deka-quartalsbericht/quartalsbericht` · DIVIDEND_TAX
- **WARNING** `Jahresabschlüsse/DEKA20201231_61675838.pdf` · `user.deka-quartalsbericht/quartalsbericht` · DIVIDEND_TAX
- **WARNING** `Jahresabschlüsse/DEKA20211231_79276660.pdf` · `user.deka-quartalsbericht/quartalsbericht` · DIVIDEND_TAX
- **WARNING** `Jahresabschlüsse/DEKA20221231_100608364.pdf` · `user.deka-quartalsbericht/quartalsbericht` · DIVIDEND_TAX
- **WARNING** `Jahresabschlüsse/DEKA20231231_139243216.pdf` · `user.deka-quartalsbericht/quartalsbericht` · DIVIDEND_TAX
- **WARNING** `Jahresabschlüsse/DEKA20241231_175703965.pdf` · `user.deka-quartalsbericht/quartalsbericht` · DIVIDEND_TAX
- **WARNING** `Jahresabschlüsse/DEKA20251231_215511193.pdf` · `user.deka-quartalsbericht/quartalsbericht` · DIVIDEND_TAX
- **WARNING** `Quartalsbericht/DEKA20190331_35887307.pdf` · `user.deka-quartalsbericht/quartalsbericht` · DIVIDEND_TAX, MIFID_COST
- **WARNING** `Quartalsbericht/DEKA20200331_44534894.pdf` · `user.deka-quartalsbericht/quartalsbericht` · DIVIDEND_TAX, MIFID_COST
- **WARNING** `Quartalsbericht/DEKA20210331_64997752.pdf` · `user.deka-quartalsbericht/quartalsbericht` · DIVIDEND_TAX, MIFID_COST
- **WARNING** `Quartalsbericht/DEKA20220331_83951314.pdf` · `user.deka-quartalsbericht/quartalsbericht` · DIVIDEND_TAX, MIFID_COST
- **WARNING** `Quartalsbericht/DEKA20230331_115022659.pdf` · `user.deka-quartalsbericht/quartalsbericht` · DIVIDEND_TAX, MIFID_COST
- **WARNING** `Quartalsbericht/DEKA20240331_151504638.pdf` · `user.deka-quartalsbericht/quartalsbericht` · DIVIDEND_TAX, MIFID_COST
- **WARNING** `Quartalsbericht/DEKA20250331_188373340.pdf` · `user.deka-quartalsbericht/quartalsbericht` · DIVIDEND_TAX, MIFID_COST
- **WARNING** `Quartalsbericht/DEKA20260331_227486158.pdf` · `user.deka-quartalsbericht/quartalsbericht` · DIVIDEND_TAX, MIFID_COST

## Grenzen

- Klassifikationen sind regelbasierte Priorisierung, **kein** Beweis, dass Beträge fachlich korrekt oder fehlerhaft sind.
- `INFO` umfasst z. B. normale Plugin-Erkennungsnachrichten; `WARNING` enthält auffällige Vorzeichen und Brutto-Netto-Werte.
- Die Suite führt `parse_pdf()` aus und schreibt keinerlei Portman-Datenbankeinträge.
- Optionaler Cache nutzt Dateigröße, mtime_ns, SHA-256, OCR-Modus und Parser-Fingerprint; SHA wird auch bei Cache-Treffern neu berechnet.
- Für schnelle gezielte Läufe `--only-errors`, `--plugin` und `--issue-code` verwenden; mit `--compare` zu V1/V2 vergleichen.
- Historische Baselines unter `test_reports` unverändert aufbewahren. Berichte nicht öffentlich teilen (Dateinamen/Belegdetails).
