# comdirect MiFID-II-Kosteninformationen – Import und Abgrenzung

Stand: 22.10.2026  
Branch: `feature/comdirect-mifid-cost-import`  
Basis: `main` (`55b2eda`)  
Status: implementiert, getestet, **nicht gemergt**

## Ziel und Ergebnis

Alle 23 comdirect-MiFID-II-Kosteninformationen aus dem realen Bestand werden jetzt als eigener Dokumenttyp `kosteninformation_mifid_ii` erkannt, strukturiert ausgewertet, archiviert und in der Importvorschau angezeigt.

Die Belege bleiben strikt von der Wirtschaftsbuchhaltung getrennt:

- keine `BUY`-/`SELL`-/`DIVIDEND`-/`TAX`-Transaktion,
- kein Cashflow, keine Gebührenbuchung,
- keine Änderung von Depot-, Einstands-, Konto- oder Saldenwerten,
- keine Beeinflussung tatsächlicher Gebühren oder Performancekennzahlen,
- tatsächliche Transaktionsgebühren stammen weiterhin ausschließlich aus Wertpapierabrechnungen bzw. Finanzreportbuchungen.

Die Kosteninformation wird in der Vorschau und im archivierten Dokument eindeutig als **„MiFID-II-Kosteninformation – keine ausgeführte Transaktion“** gekennzeichnet.

## Umsetzung

### Erkennung und Parser

Erweitert wurde das bestehende Plugin `pdf_plugins/comdirect_ertraege.py` (Version `1.5`), kein paralleler Importer.

Erkannt werden:

- Dokumenttitel `Kosteninformation zum Wertpapiergeschäft <Datum> - <Uhrzeit>`,
- Wertpapierzeile mit `WKN:`,
- ausgewiesene Gesamtkosten und Renditewirkung.

Extrahiert werden:

- Dokumentdatum und Uhrzeit,
- Referenz aus dem Dateinamen-Suffix,
- Sparplan-Nummer aus dem Dateinamen (`Sparplan Nr. 38`),
- WKN, optional ISIN und Wertpapierbezeichnung,
- Ausführungsplatz, Währung und Kundennummer,
- monatlicher und jährlicher Sparbetrag,
- Kaufkosten pro Jahr, Haltedauerkosten pro Jahr, Verkaufskosten einmalig,
- Dienstleistungskosten der Bank, Fremdkosten, Produktkosten und Zahlungen Dritter,
- Gesamtkosten in EUR und Renditewirkung in Prozent,
- angenommene Laufzeit und Haltedauer,
- Betrachtungszeitraum,
- jede gedruckte Kostenposition mit Originalbezeichnung, Phase (`kauf`, `haltedauer`, `verkauf`), Kategorie (`eigen`, `fremd`, `produkt`) und Bezug (`pro Jahr`/`einmalig`),
- die gedruckte Jahresprojektion als informative JSON-Liste.

Fehlende Kostenzeilen bleiben `None` und werden nicht als `0,00` interpretiert. Gedruckte `0,00` bleiben `0.00`.

Der Parser prüft:

- Monatsbetrag × 12 gegen den Jahresbetrag,
- Summe der Einzelpositionen je Kostenphase gegen den gedruckten Phasenblock,
- Gesamtkosten gegen die Summe der drei Kostenkategorien, sofern alle drei ausgewiesen sind.

Bei fehlender ISIN wird **keine ISIN geraten**. Die Wertpapierkennung lautet dann `WKN:<wkn>`.

### Modell und Persistenz

`CostItem` und `CostReport` wurden ausschließlich additiv um optionale Felder erweitert. Die Daten liegen weiterhin als JSON in `import_model_records`; es gibt **keine SQL-Schemaänderung**.

`CostReport` wird dem ausgewählten Ziel-Depot zugeordnet. Die Original-PDF wird als `BankDocument` gespeichert und mit dem `CostReport` verknüpft.

### Importvorschau

Neuer Reiter **`MiFID-II-Kosten`**:

- Summen- und Komponententabelle je Kosteninformation,
- Einzelpositionen mit Phase, Originalbezeichnung, Kategorie, Betrag und Originalzeile,
- Kennzeichnung „Kostensimulation – keine ausgeführte Transaktion“,
- Doppelklick auf eine Zeile öffnet das Original-PDF,
- Kosten-Quellkonten werden gruppiert und einem Depot zugeordnet,
- beim Auslassen einer Kostenquelle werden auch die zugehörigen `CostReport`-Datensätze entfernt.

## Prüfung der 23 realen Kosteninformationen

Alle 23 Dateien unter

`C:\Users\chris\Desktop\history\comdirect\2026\Kosteninformationen`

wurden ohne OCR mit `parse_pdf(..., allow_ocr=False)` gelesen.

Ergebnis:

- 23/23 als `kosteninformation_mifid_ii` erkannt,
- 23 `CostReport`-Datensätze,
- 113 einzelne Kostenpositionen,
- 0 Parserfehler,
- 0 Transaktionen, 0 Snapshots, 0 Salden,
- je 1 `BankDocument` mit Kennzeichnung „keine ausgeführte Transaktion“,
- alle mit Sparplan-Nr. 38,
- alle ohne ausgewiesene ISIN; Zuordnung über WKN ohne geratene ISIN.

| Datei | Datum | WKN | Wertpapier | Gesamt EUR | % p.a. | Positionen |
|---|---|---|---:|---:|---:|---:|
| `Kosteninformation_Sparplan_Nr._38_578560_(FRESENIUS_SE+CO.KGAA_O.N.)_vom_06.08.2026_6CC595.pdf` | 2026-08-06 | 578560 | Fresenius SE & Co. KGaA Inhaber-Aktien o.N. | 60,81 | 0,66 | 4 |
| `Kosteninformation_Sparplan_Nr._38_578560_(FRESENIUS_SE+CO.KGAA_O.N.)_vom_16.07.2026_51DDA6.pdf` | 2026-07-16 | 578560 | Fresenius SE & Co. KGaA Inhaber-Aktien o.N. | 55,77 | 0,67 | 4 |
| `Kosteninformation_Sparplan_Nr._38_578560_(FRESENIUS_SE+CO.KGAA_O.N.)_vom_20.07.2026_189A2E.pdf` | 2026-07-20 | 578560 | Fresenius SE & Co. KGaA Inhaber-Aktien o.N. | 56,48 | 0,67 | 4 |
| `Kosteninformation_Sparplan_Nr._38_593399_(ISH.S.EUROP.MID_200_U.ETF)_vom_16.07.2026_A2B37A.pdf` | 2026-07-16 | 593399 | iSh.ST.Europe Mid 200 U.ETF DE Inhaber-Anteile | 163,44 | 0,86 | 5 |
| `Kosteninformation_Sparplan_Nr._38_593399_(ISH.S.EUROP.MID_200_U.ETF)_vom_20.07.2026_6BC967.pdf` | 2026-07-20 | 593399 | iSh.ST.Europe Mid 200 U.ETF DE Inhaber-Anteile | 68,16 | 0,92 | 5 |
| `Kosteninformation_Sparplan_Nr._38_716460_(SAP_SE_O.N.)_vom_20.07.2026_FD3076.pdf` | 2026-07-20 | 716460 | SAP SE Inhaber-Aktien o.N. | 38,20 | 0,74 | 4 |
| `Kosteninformation_Sparplan_Nr._38_A0D8Q4_(IS.DJ_U.S.SELEC.DIV.U.ETF)_vom_06.08.2026_633EA0.pdf` | 2026-08-06 | A0D8Q4 | iSh.DJ U.S.Select Div.U.ETF DE Inhaber-Anteile | 82,53 | 0,93 | 5 |
| `Kosteninformation_Sparplan_Nr._38_A0D8QZ_(ISH.S.EUR.SMALL_200_U.ETF)_vom_25.08.2026_9AE5E4.pdf` | 2026-08-25 | A0D8QZ | iSh.ST.Euro.Small 200 U.ETF DE Inhaber-Anteile | 51,83 | 0,97 | 5 |
| `Kosteninformation_Sparplan_Nr._38_A0H074_(IS.DJ_AS.PAC.S.D.50_U.ETF)_vom_25.08.2026_7F7CFF.pdf` | 2026-08-25 | A0H074 | iSh.DJ Asia Pa.S.D.50 U.ETF DE Inhaber-Anteile | 55,76 | 1,02 | 5 |
| `Kosteninformation_Sparplan_Nr._38_A0JK68_(M.A.-R.INT.COM.IN.UETF)_vom_25.08.2026_49F27D.pdf` | 2026-08-25 | A0JK68 | M.A.-Rog.Int.Comm.Ind.U.ETF Inhaber-Anteile o.N. | 94,86 | 1,81 | 5 |
| `Kosteninformation_Sparplan_Nr._38_A0LEW8_(ISHSII-DEV.MKT.PR.Y.DLDIS)_vom_06.08.2026_05A1ED.pdf` | 2026-08-06 | A0LEW8 | iShsII-Dev.Mkts Prop.Yld U.ETFRegistered Shs USD (Dist) o.N. | 34,13 | 1,10 | 5 |
| `Kosteninformation_Sparplan_Nr._38_A0S9GB_(DT.BOERSE_COM._XETRA-GOLD)_vom_16.09.2026_36146D.pdf` | 2026-09-16 | A0S9GB | Deut. Börse Commodities GmbH Xetra-Gold IHS 2007(09/Und) | 33,23 | 1,03 | 7 |
| `Kosteninformation_Sparplan_Nr._38_A111X9_(IS_C.MSCI_EMIMI_U.ETF_DLA)_vom_02.09.2026_7B522C.pdf` | 2026-09-02 | A111X9 | iShs Core MSCI EM IMI U.ETF Registered Shares o.N. | 51,69 | 0,90 | 5 |
| `Kosteninformation_Sparplan_Nr._38_A111X9_(IS_C.MSCI_EMIMI_U.ETF_DLA)_vom_02.09.2026_BB3EBE.pdf` | 2026-09-02 | A111X9 | iShs Core MSCI EM IMI U.ETF Registered Shares o.N. | 49,92 | 0,91 | 5 |
| `Kosteninformation_Sparplan_Nr._38_A111X9_(IS_C.MSCI_EMIMI_U.ETF_DLA)_vom_10.09.2026_8591B8.pdf` | 2026-09-10 | A111X9 | iShs Core MSCI EM IMI U.ETF Registered Shares o.N. | 73,58 | 0,85 | 5 |
| `Kosteninformation_Sparplan_Nr._38_A1JJTF_(SPDR_MSCI_EM.MAR.SM.C.ETF)_vom_18.08.2026_AFAC71.pdf` | 2026-08-18 | A1JJTF | SPDR MSCI Emer.Mkts Sm.Cap ETF Registered Shares o.N. | 80,80 | 1,23 | 5 |
| `Kosteninformation_Sparplan_Nr._38_A1JSHV_(SPDR_S+P_400_US_MID_CAP)_vom_18.08.2026_7092E0.pdf` | 2026-08-18 | A1JSHV | SPDR S&P 400 US Mid Cap ETF Registered Shares o.N. | 121,09 | 0,89 | 5 |
| `Kosteninformation_Sparplan_Nr._38_ETF039_(AM.-S+P_SM.C.600_SCR.DLD)_vom_10.09.2026_5BB8A6.pdf` | 2026-09-10 | ETF039 | Amundi-S+P SmCap 600 Scr.UETF Reg.Shs.USD Dis. o.N. | 28,31 | 0,89 | 5 |
| `Kosteninformation_Sparplan_Nr._38_ETF039_(AM.-S+P_SM.C.600_SCR.DLD)_vom_16.09.2026_586A97.pdf` | 2026-09-16 | ETF039 | Amundi-S+P SmCap 600 Scr.UETF Reg.Shs.USD Dis. o.N. | 85,53 | 0,64 | 5 |
| `Kosteninformation_Sparplan_Nr._38_LYX05A_(MUL-AM.MSCI_JPN_ETF_YND)_vom_02.09.2026_2A6556.pdf` | 2026-09-02 | LYX05A | MUL-AMUNDI MSCI Japan U.ETF Nam.-Ant. JPY Dis.oN | 57,33 | 0,45 | 5 |
| `Kosteninformation_Sparplan_Nr._38_LYX05A_(MUL-AM.MSCI_JPN_ETF_YND)_vom_02.09.2026_D1C6E1.pdf` | 2026-09-02 | LYX05A | MUL-AMUNDI MSCI Japan U.ETF Nam.-Ant. JPY Dis.oN | 58,45 | 0,45 | 5 |
| `Kosteninformation_Sparplan_Nr._38_LYX05A_(MUL-AM.MSCI_JPN_ETF_YND)_vom_02.10.2026_2C6645.pdf` | 2026-10-02 | LYX05A | MUL-AMUNDI MSCI Japan U.ETF Nam.-Ant. JPY Dis.oN | 13,13 | 5,14 | 5 |
| `Kosteninformation_Sparplan_Nr._38_LYX05A_(MUL-AM.MSCI_JPN_ETF_YND)_vom_24.09.2026_2A9BEA.pdf` | 2026-09-24 | LYX05A | MUL-AMUNDI MSCI Japan U.ETF Nam.-Ant. JPY Dis.oN | 72,39 | 0,43 | 5 |

## Rekursiver Test aller 102 comdirect-PDFs

Alle 102 PDFs unter `C:\Users\chris\Desktop\history\comdirect\2026` wurden rekursiv mit `parse_pdf(..., allow_ocr=True)` eingelesen.

| Kennzahl | Ergebnis |
|---|---:|
| PDFs insgesamt | 102 |
| strukturiert erkannt | **102** |
| generisch | **0** |
| Parserfehler | **0** |
| Kosteninformationen | 23 |
| Laufzeit | 565,2 s |

Erkannte Handler:

| Handler | Dateien |
|---|---:|
| `finanzreport` | 10 |
| `wertpapierkauf` | 41 |
| `investment_ausschuettung` | 20 |
| `vorabpauschale` | 6 |
| `kosteninformation_mifid_ii` | 23 |
| `dividende_steuer_inland` | 2 |

Die Zählung enthält bewusst auch physische Kopien im Bestand. Die vollständigen Ergebnisse liegen unter `C:\Users\chris\AppData\Local\Temp\opencode\comdirect_mifid_full.json`.

## SQLite-Nachweise zur wirtschaftlichen Neutralität

Verwendet wurden ausschließlich temporäre SQLite-Datenbanken; produktive Datenbanken wurden nicht verändert.

### Nur Kosteninformation

Nach dem Import einer realen Fresenius-Kosteninformation:

| Tabelle/Prüfung | Ergebnis |
|---|---:|
| `transactions` | 0 |
| `snapshots` | 0 |
| `balances` | 0 |
| `booking_evidence` | 0 |
| Holdings | 0 |
| `bank_documents` | 1 |
| `cost_reports` | 1 |

Der gespeicherte `CostReport` ist dem Ziel-Depot zugeordnet (im Test `Depot Test`). Die Kostenpositionen bleiben als Originalzeilen erhalten; die Gesamtkosten betragen `60.81 EUR` bei `0.66 % p.a.`.

### Reihenfolge Wertpapierabrechnung → Kosteninformation

Eine reale Fresenius-Kaufabrechnung wurde zuerst importiert, danach die Kosteninformation.

- `transactions`, `holdings`, `booking_evidence` und `tax_events` blieben unverändert.
- Die tatsächliche Gebühr der Kaufabrechnung blieb vor und nach dem Kostenimport `0.70 EUR`.
- Lediglich `bank_documents` und `cost_reports` kamen hinzu.
- Ein Wiederholungsimport derselben Kosteninformation lieferte `duplicate`; der Zustand blieb unverändert.

### Reihenfolge Kosteninformation → Wertpapierabrechnung

Die umgekehrte Reihenfolge wurde in einer zweiten temporären Datenbank geprüft.

- Nach dem Kostenimport: 0 Transaktionen, 0 Holdings, 0 Buchungsbelege.
- Nach dem anschließenden Wertpapierabrechnungsimport waren Transaktionen, Holdings, Buchungsbelege, Kostenreports und Steuerereignisse identisch zur ersten Reihenfolge.

### Wiederholungsimport

Derselbe Kostenbeleg wurde mit identischer Datei und Zuordnung erneut importiert:

- Status `duplicate`,
- keine zusätzliche `CostReport`-Zeile,
- kein zusätzliches `BankDocument`,
- keine wirtschaftliche Änderung.

## Tests

Neu: `tests/test_comdirect_mifid_cost.py`

Abgedeckt sind:

- Erkennung und vollständige Feldauswertung,
- Originalbezeichnungen, Phasen und Kategorien,
- fehlende Kategorien bleiben `None`,
- ISIN nur bei gedruckter ISIN, sonst `WKN:<wkn>`,
- keine wirtschaftlichen Buchungen,
- Persistenz, Ziel-Depot-Zuordnung und Duplicate-Erkennung,
- beide Importreihenfolgen,
- Importvorschau mit Summen, Einzelpositionen und Kennzeichnung,
- gated Test aller 23 realen Kosteninformationen.

Testergebnisse:

| Suite | Ergebnis |
|---|---|
| Neue MiFID-Tests | 8 passed |
| Gezielte PR-#19-/Plugin-Regression | 59 passed |
| Vollständige Pytest-Suite | **1081 passed, 9 skipped** |

Die vollständige Suite lief mit `QT_QPA_PLATFORM=offscreen` und `--basetemp=.pytest-mifid-full` in 387,2 s.

## Geänderte Dateien

- `pdf_plugins/comdirect_ertraege.py`
- `src/portfolio_v5/models.py`
- `src/portfolio_v5/import_accounts.py`
- `src/portfolio_v5/storage.py`
- `src/portman/import_preview.py`
- `src/portman/repository.py`
- `docs/pdf-import.md`
- `tests/test_comdirect_mifid_cost.py` (neu)
- `test_reports/comdirect_mifid_cost_import.md` (neu)

## Restrisiken und Grenzen

- Die realen comdirect-Kosteninformationen enthalten **keine Depotnummer und keine ISIN**. Die Depotzuordnung erfolgt manuell in der Vorschau; die Wertpapierkennung erfolgt über die WKN. Es wird keine ISIN geraten.
- Sparplan-Nummer und Referenz werden aus dem Dateinamen gelesen, da der Beleginhalt keine explizite Sparplan-Nummer enthält. Bei umbenannten Dateien kann die Sparplan-Nummer leer bleiben und die Duplicate-Identität abweichen.
- Neue Layouts, die `[E]`/`[F]`/`[P]`-Marker oder die gedruckten Phasenüberschriften nicht mehr enthalten, führen zu einem Parserfehler statt zu einer stillen Fehlbuchung. Das ist bewusst konservativ.
- Die Jahresprojektion wird nur informativ gespeichert und nicht in Performance- oder Gebührenkennzahlen übernommen.
- PR #20 (Windows-OCR) ist weiterhin offen und nicht Bestandteil dieses Branches.
