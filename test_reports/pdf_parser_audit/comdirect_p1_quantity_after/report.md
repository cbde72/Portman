# Portman – PDF-Parser-Audit V2

- Datum (UTC): `2026-10-25T10:02:05.620854+00:00`
- Quellverzeichnis: `C:\Users\chris\Desktop\history`
- Modus: `targeted`; OCR: `False`; Parser-Fingerprint: `ad82dfb95b4bc879`
- PDFs im Scope: **6**; eindeutige SHA-256: **6**; Cache-Treffer: **0**
- Plugin-Ladefehler: **0**; Scanfehler: **0**

## Schweregrade

| Grad | PDFs |
|---|---:|
| ERROR | 6 |
| WARNING | 0 |
| INFO | 0 |
| PASS | 0 |

## Befunde (pro Dokument, Kategorien können mehrfach vorkommen)

| Kategorie | Dokumente |
|---|---:|
| `OCR_LAYOUT` | 6 |
| `QUANTITY_CONFLICT` | 5 |
| `TEXT_EXTRACTION` | 1 |

## Parser/Handler

| Plugin | Handler | Dateien | Fehler | Warnungen |
|---|---|---:|---:|---:|
| `(kein Plugin)` | `-` | 6 | 6 | 0 |

## Vergleich mit Baseline

Verglichen: **6**, Verbesserungen: **1**, Regressionen: **1**, veränderte Befunde: **1**, neu: **0**.
**Teillauf:** Nicht im Scope enthaltene PDFs gelten nicht als entfernt.

### Regressionen (max. 100, vollständige Liste in delta.csv)

- `comdirect/Abrechnungen/Wertpapierabrechnung_Kauf_1,003_St._WKN_A0LEW8(ISHSII-DEV.MKT.PR.Y.DLDIS)_vom_01.06.2022_E051A2.pdf`: ERROR → ERROR (OCR_LAYOUT,QUANTITY_CONFLICT → OCR_LAYOUT,TEXT_EXTRACTION)

### Verbesserungen (max. 100, vollständige Liste in delta.csv)

- `comdirect/Abrechnungen/Wertpapierabrechnung_Kauf_1,003_St._WKN_A0LEW8(ISHSII-DEV.MKT.PR.Y.DLDIS)_vom_01.06.2022_E051A2.pdf`: ERROR → ERROR (OCR_LAYOUT,QUANTITY_CONFLICT → OCR_LAYOUT,TEXT_EXTRACTION)

## Einzelbefunde

Vollständig in `findings.csv` (jede Meldung einzeln), `files.csv` und `audit.json`. Der Markdownbericht enthält nur die ersten 150 ERROR/ WARNING-Dateien.

- **ERROR** `comdirect/Abrechnungen/Wertpapierabrechnung_Kauf_1,001_St._WKN_A0D8QZ(ISH.S.EUR.SMALL_200_U.ETF)_vom_04.10.2016_BF00EF.pdf` · `/` · OCR_LAYOUT, QUANTITY_CONFLICT
- **ERROR** `comdirect/Abrechnungen/Wertpapierabrechnung_Kauf_1,001_St._WKN_A0LEW8(ISH.II.DEV.M.PR.Y.U.ETF)_vom_01.08.2016_1067EA.pdf` · `/` · OCR_LAYOUT, QUANTITY_CONFLICT
- **ERROR** `comdirect/Abrechnungen/Wertpapierabrechnung_Kauf_1,003_St._WKN_A0LEW8(ISHSII-DEV.MKT.PR.Y.DLDIS)_vom_01.06.2022_E051A2.pdf` · `/` · OCR_LAYOUT, TEXT_EXTRACTION
- **ERROR** `comdirect/Abrechnungen/Wertpapierabrechnung_Kauf_1,003_St._WKN_A111X9(IS_C.MSCI_EMIMI_U.ETF_DLA)_vom_02.03.2020_FF13A6.pdf` · `/` · OCR_LAYOUT, QUANTITY_CONFLICT
- **ERROR** `comdirect/Abrechnungen/Wertpapierabrechnung_Kauf_1,007_St._WKN_A111X9(IS_C.MSCI_EMIMI_U.ETF_DLA)_vom_07.10.2019_309C2D.pdf` · `/` · OCR_LAYOUT, QUANTITY_CONFLICT
- **ERROR** `comdirect/Abrechnungen/Wertpapierabrechnung_Kauf_2,004_St._WKN_A0H074(IS.DJ_AS.PAC.S.D.30_U.ETF)_vom_01.02.2016_75CE1B.pdf` · `/` · OCR_LAYOUT, QUANTITY_CONFLICT

## Grenzen

- Klassifikationen sind regelbasierte Priorisierung, **kein** Beweis, dass Beträge fachlich korrekt oder fehlerhaft sind.
- `INFO` umfasst z. B. normale Plugin-Erkennungsnachrichten; `WARNING` enthält auffällige Vorzeichen und Brutto-Netto-Werte.
- Die Suite führt `parse_pdf()` aus und schreibt keinerlei Portman-Datenbankeinträge.
- Optionaler Cache nutzt Dateigröße, mtime_ns, SHA-256, OCR-Modus und Parser-Fingerprint; SHA wird auch bei Cache-Treffern neu berechnet.
- Für schnelle gezielte Läufe `--only-errors`, `--plugin` und `--issue-code` verwenden; mit `--compare` zu V1/V2 vergleichen.
- Historische Baselines unter `test_reports` unverändert aufbewahren. Berichte nicht öffentlich teilen (Dateinamen/Belegdetails).
