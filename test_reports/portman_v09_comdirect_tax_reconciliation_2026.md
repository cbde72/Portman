# Portman V09 – Steuerabgleich 2026 mit comdirect-Referenzdaten

**Prüfdatum:** 23.10.2026  
**Git-Stand:** `main`, Commit `69f7bf07cb5bd31fc0114148dafad2e88a62a8f0` (`Fix tax event booking classifications (#23)`)  
**Gesamtbewertung:** **FAIL**

## Kurzfazit

Die in Portman gespeicherten 24 PDF-Steuerereignisse enthalten die richtigen
steuerpflichtigen Beträge. Insbesondere stimmen die drei steuerlich relevanten
Vorabpauschalen mit insgesamt **192,24 €** exakt mit comdirect überein. In der
Steuerübersicht und in der automatisch erzeugten steuerlichen Detailansicht
werden die vorhandenen Fakten jedoch nicht korrekt zusammengeführt:

- Die comdirect-Referenz weist **523,07 €** steuerlichen Ertrag aus. Portmans
  Steuerübersicht zeigt **680,04 € Kapitalerträge gebucht**.
- Die comdirect-Referenz weist **29,53 € tatsächlich einbehaltene Steuer** aus.
  Portmans Steuerübersicht zeigt **54,42 € Steuern gebucht**. Der Unterschied
  von **24,89 €** ist eine wirtschaftliche Doppelzählung der bis September
  sowohl in Dividendenbuchungen als auch in separaten, cash-neutralen
  `TAX`-Transaktionen enthaltenen Steuer.
- Die Detailansicht zeigt 47 statt 39 Referenzzeilen. Sie enthält 20 zusätzliche
  abgeleitete Dividendenzeilen neben den zugehörigen Steuerereignissen, lässt
  aber 11 belegte Null-Vorabpauschalen und die steuerneutrale A0S9GB-Zeile aus.
- Die drei Zinszeilen sind vorhanden, aber ihre steuerliche
  Bemessungsgrundlage und FSA-Verrechnung fehlen. Aufgrund einer leeren
  Wertpapierkennung wird ihnen außerdem fälschlich WKN `A1KRJ0` zugeordnet.
- Der produktive Bestand enthält keinen importierten comdirect-Steuerdetail-CSV-
  Datensatz (`tax_details=0`). Deshalb können PDF/Finanzreport allein die in der
  CSV belegten FSA-Werte und Nullzeilen nicht vollständig reproduzieren.

Eine Korrektur der Zusammenführungs- und Aggregationslogik ist notwendig. Die
PDF-Parserwerte der drei Vorabpauschalen dürfen dabei nicht geändert oder
nochmals um die Teilfreistellung reduziert werden.

## Sicherheits- und Datenbasis

- Produktive Datenbank: `data/v09/portfolio.sqlite`
- Öffnung: SQLite-URI `mode=ro`, danach `PRAGMA query_only=ON`
- `PRAGMA integrity_check`: `ok`
- `PRAGMA foreign_key_check`: keine Treffer
- GUI-nahe Prüfungen: ausschließlich auf einem per SQLite-Backup-API erzeugten
  temporären Snapshot; Snapshot anschließend gelöscht
- Referenz-CSV:
  `C:\Users\chris\Desktop\history\comdirect\steuerlichedetailansichtexport_1024764924_20261023-0845 (1).csv`
- PDF-Steuerordner: 24 PDFs, 24 strukturierte Steuerereignisse, 0 Parserfehler,
  Plugin jeweils `user.comdirect-ertraege`
- Im gesamten angegebenen PDF-Verzeichnis befinden sich zum Prüfzeitpunkt 126
  physische PDFs. Dieser Auftrag erforderte keinen erneuten Gesamtimport.
- Keine produktive Datenbank, kein PDF und keine bestehende Transaktion wurde
  verändert.

Produktiver Ist-Stand beim Audit:

| Kennzahl | Ist |
| --- | ---: |
| aktive Imports | 94 |
| Transaktionen | 367 |
| `import_model_records` | 145 |
| davon `tax_events` | 24 |
| davon `tax_details` | 0 |
| `booking_details` | 37 |
| `fee_links` | 0 |

## Soll-Ist-Vergleich der Ertragsarten

Für den Bankvergleich ist die CSV-Spalte `Steuerbemessungsgrundlage` maßgeblich.
`Betrag Brutto`, `BMG nach VV`, `Veränderung FSA`, `BMG nach FSA` und die
Steuerkomponenten werden getrennt ausgewiesen und nicht miteinander vermischt.

| Ertragsart | comdirect steuerlicher Ertrag | Portman-Steuerereignisse/Detailspalte | Abweichung | Bewertung |
| --- | ---: | ---: | ---: | --- |
| Investment-Ausschüttungen | 314,33 € | 314,33 € | 0,00 € | Einzelwerte richtig |
| Vorabpauschale Ausland | 192,24 € | 192,24 € | 0,00 € | exakt richtig |
| Inländische Dividenden | 8,56 € | 8,56 € | 0,00 € | exakt richtig |
| Habenzinsen | 7,94 € | 0,00 € in `Steuerbemessungsgrundlage` | −7,94 € | Detailfeld fehlt |
| **Gesamt** | **523,07 €** | **515,13 €** | **−7,94 €** | Detailansicht unvollständig |

Die Steuerübersicht verwendet eine andere, nicht mit der Bankspalte
vergleichbare Basis:

| GUI-Wert | Portman | comdirect-Vergleichswert | Differenz |
| --- | ---: | ---: | ---: |
| Kapitalerträge gebucht | 680,04 € | 523,07 € | +156,97 € |
| Steuern gebucht | 54,42 € | 29,53 € | +24,89 € |
| Soli gebucht | 0,04 € | 1,51 € | −1,47 € |
| Vorabpauschale (Basis vor Teilfreistellung) | 274,65 € | 274,65 € aus PDFs | 0,00 € |
| davon steuerpflichtig | 192,24 € | 192,24 € | 0,00 € |
| verbrauchter FSA | 192,24 € | 411,00 € | −218,76 € |
| verbleibender FSA | 218,76 € | 0,00 € | +218,76 € |

Der Wert 680,04 € setzt sich aus transaktionsbasierten Bruttowerten und der
Vorabpauschalen-Basis vor Teilfreistellung zusammen. Er entspricht daher weder
der comdirect-Steuerbemessungsgrundlage noch einer einheitlichen Brutto- oder
Nettoertragsdefinition. Zusätzlich ist im gespeicherten Institutsdatensatz eine
manuelle Teilfreistellung von `0,00` vorhanden; diese überschreibt in der GUI
den automatisch ermittelten Wert von 177,20 €.

## Vorabpauschalen im Detail

| WKN | PDF-Basis vor Teilfreistellung | Teilfreistellung | Steuerlicher Ertrag PDF/Portman | comdirect | FSA | BMG nach FSA | Steuer |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| A111X9 | 137,65 € | 41,30 € | 96,35 € | 96,35 € | −96,35 € | 0,00 € | 0,00 € |
| A2H57N | 99,25 € | 29,78 € | 69,47 € | 69,47 € | −69,47 € | 0,00 € | 0,00 € |
| A1JJTF | 37,75 € | 11,33 € | 26,42 € | 26,42 € | −26,42 € | 0,00 € | 0,00 € |
| **Gesamt** | **274,65 €** | **82,41 €** | **192,24 €** | **192,24 €** | **−192,24 €** | **0,00 €** | **0,00 €** |

Ergebnis:

1. Portman erkennt genau diese drei steuerlich relevanten PDF-Ereignisse als
   `vorabpauschale_ausland`.
2. `taxable_income=192,24` enthält die Teilfreistellung bereits. Dieser Betrag
   darf nicht nochmals um 82,41 € reduziert werden.
3. PDF, CSV, Freistellungsauftrag, BMG nach FSA und tatsächliche Steuer stimmen
   für diese drei Fälle exakt überein.
4. Die CSV enthält zusätzlich elf Vorabpauschalen-Zeilen mit belegtem Nullbetrag.
   Da hierfür keine Einzel-PDFs im Steuerordner liegen und die CSV produktiv
   nicht importiert ist, fehlen sie in Portmans Detailansicht. Sie dürfen nicht
   als unbekannte Beträge nachgebildet werden; nach CSV-Import wären sie als
   nachgewiesene Nullzeilen zu erhalten.

## Tatsächliche Steuerbeträge

| Komponente | comdirect CSV | Portman zugrunde liegende Belege | Portman GUI |
| --- | ---: | ---: | ---: |
| Kapitalertragsteuer | 28,02 € | 28,02 € | nicht separat vollständig aggregiert |
| Solidaritätszuschlag | 1,51 € | 1,51 € | 0,04 € |
| Kirchensteuer | 0,00 € | 0,00 € | nicht abweichend |
| **Summe Steuern** | **29,53 €** | **29,53 €** | **54,42 €** |

Die Belege sind vollständig: 28,63 € entfallen auf Ausschüttungen, 0,90 € auf
Zinsen. In `automatic_tax_values()` werden bei Dividenden die im Finanzreport
gespeicherten Steuern addiert und anschließend die separaten `TAX`-Zeilen
erneut berücksichtigt. `fee_links` ist produktiv leer, sodass der dortige
Schutz nicht greift. Die vier cash-neutralen Steuerzeilen für A0LEW8, A0H074,
A0D8QZ und 593399 sowie A0D8Q4 vom 15.10. erklären die fünf `TAX`-Transaktionen;
bei den vier bis September vorhandenen Cash-Dividenden entsteht die
Doppelzählung von 24,89 €.

## Zeilenabgleich der 39 comdirect-Referenzzeilen

`Teilweise` bedeutet: steuerpflichtiger Betrag und Steuer aus dem PDF stimmen,
aber mindestens FSA/BMG-nach-FSA oder die eindeutige Zusammenführung mit der
Cashzeile fehlt. Die comdirect-CSV ist nicht produktiv importiert, daher ist
keine der CSV-Referenzen als `tax_details` gespeichert.

| Steuerdatum | Referenz | WKN | Vorgang | Brutto | Steuerlicher Ertrag | FSA | BMG nach FSA | Steuer | Portman |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| 15.10.2026 | 1IINR5C2S7N006H5 | A0D8Q4 | Investment-Ausschüttung | 20,25 | 14,18 | 0,00 | 14,18 | -3,74 | Teilweise; PDF-Ereignis richtig, keine Cashbuchung im Datenstand |
| 30.09.2026 | 04INQ5QN72000WUC | — | Habenzinsen | 3,42 | 3,42 | 0,00 | 3,42 | -0,90 | Teilweise; Buchung vorhanden, BMG/FSA fehlen |
| 23.09.2026 | 14INPOPLO9C001CJ | A0S9GB | Brutto = Nettoabr. | 0,00 | 0,00 | 0,00 | 0,00 | 0,00 | Fehlt in Detailansicht |
| 15.09.2026 | 1IINP4025ZX003K5 | 593399 | Investment-Ausschüttung | 35,15 | 24,60 | 0,00 | 24,60 | -6,48 | Teilweise; PDF-Werte richtig, FSA-Feld unbekannt/leer |
| 15.09.2026 | 1IINP4025ZX000SB | A0H074 | Investment-Ausschüttung | 9,10 | 6,37 | 0,00 | 6,37 | -1,67 | Teilweise; PDF-Werte richtig, FSA-Feld unbekannt/leer |
| 15.09.2026 | 1IINP4025ZX00098 | A0D8QZ | Investment-Ausschüttung | 56,12 | 39,29 | 0,00 | 39,29 | -10,36 | Teilweise; PDF-Werte richtig, FSA-Feld unbekannt/leer |
| 31.08.2026 | 20INO6681F3002EV | A0LEW8 | Investment-Ausschüttung | 28,62 | 28,62 | -4,41 | 24,21 | -6,38 | Teilweise; FSA/BMG nach FSA fehlen |
| 29.07.2026 | 12INLZKPRU2002NS | A0Q1YX | Investment-Ausschüttung | 8,66 | 8,66 | -8,66 | 0,00 | 0,00 | Teilweise; FSA/BMG nach FSA fehlen |
| 15.07.2026 | 1CINL28NT9O0070O | A0D8Q4 | Investment-Ausschüttung | 25,78 | 18,05 | -18,05 | 0,00 | 0,00 | Teilweise; FSA/BMG nach FSA fehlen |
| 30.06.2026 | 02INK2N9FCR00X01 | — | Habenzinsen | 2,55 | 2,55 | -2,55 | 0,00 | 0,00 | Teilweise; Buchung vorhanden, BMG/FSA fehlen |
| 15.06.2026 | 1OINIWDRSH0005DS | 593399 | Investment-Ausschüttung | 20,57 | 14,40 | -14,40 | 0,00 | 0,00 | Teilweise; FSA/BMG nach FSA fehlen |
| 15.06.2026 | 1OINIWDRSH0002OL | A0H074 | Investment-Ausschüttung | 12,46 | 8,72 | -8,72 | 0,00 | 0,00 | Teilweise; FSA/BMG nach FSA fehlen |
| 15.06.2026 | 1OINIWDRSH00025B | A0D8QZ | Investment-Ausschüttung | 45,91 | 32,14 | -32,14 | 0,00 | 0,00 | Teilweise; FSA/BMG nach FSA fehlen |
| 29.05.2026 | 24INHYB1ZKZ0055T | A0LEW8 | Investment-Ausschüttung | 27,05 | 27,05 | -27,05 | 0,00 | 0,00 | Teilweise; FSA/BMG nach FSA fehlen |
| 27.05.2026 | 1SINHRMXMUV005VO | 578560 | Inländische Dividende | 4,07 | 4,07 | -4,07 | 0,00 | 0,00 | Pass; PDF-Ereignis und FSA stimmen |
| 08.05.2026 | 0UINGIGZ23C007KN | 716460 | Inländische Dividende | 4,49 | 4,49 | -4,49 | 0,00 | 0,00 | Pass; PDF-Ereignis und FSA stimmen |
| 15.04.2026 | 0GINF3WM7WH000U4 | A0D8Q4 | Investment-Ausschüttung | 22,46 | 15,72 | -15,72 | 0,00 | 0,00 | Teilweise; FSA/BMG nach FSA fehlen |
| 31.03.2026 | 0AINE1XMQ0U00XEH | — | Habenzinsen | 1,97 | 1,97 | -1,97 | 0,00 | 0,00 | Teilweise; Buchung vorhanden, BMG/FSA fehlen |
| 16.03.2026 | 0QINCVHG1UR003FX | 593399 | Investment-Ausschüttung | 5,72 | 4,00 | -4,00 | 0,00 | 0,00 | Teilweise; FSA/BMG nach FSA fehlen |
| 16.03.2026 | 0QINCVHG1UR000Q8 | A0H074 | Investment-Ausschüttung | 2,31 | 1,62 | -1,62 | 0,00 | 0,00 | Teilweise; FSA/BMG nach FSA fehlen |
| 16.03.2026 | 0QINCVHG1UR0007O | A0D8QZ | Investment-Ausschüttung | 10,69 | 7,48 | -7,48 | 0,00 | 0,00 | Teilweise; FSA/BMG nach FSA fehlen |
| 27.02.2026 | 1UINBXLGPRT009JC | A0LEW8 | Investment-Ausschüttung | 22,09 | 22,09 | -22,09 | 0,00 | 0,00 | Teilweise; FSA/BMG nach FSA fehlen |
| 18.02.2026 | 0MINBC5M15C001QW | ETF039 | Investment-Ausschüttung | 28,55 | 19,98 | -19,98 | 0,00 | 0,00 | Teilweise; FSA fehlt, Brutto aus PDF-Feldern 28,54 € |
| 28.01.2026 | 2GIN9Y56YOR002GE | A0Q1YX | Investment-Ausschüttung | 6,73 | 6,72 | -6,72 | 0,00 | 0,00 | Teilweise; FSA fehlt, Brutto aus PDF-Feldern 6,72 € |
| 02.01.2026 | 06IN9TZTSS700IS0 | LYX05A | Vorabpauschale Ausland | 0,00 | 0,00 | 0,00 | 0,00 | 0,00 | Fehlt; belegte Nullzeile nur in CSV |
| 02.01.2026 | 1YIN9MVVAUZ00TM8 | LYX0Y0 | Vorabpauschale Ausland | 0,00 | 0,00 | 0,00 | 0,00 | 0,00 | Fehlt; belegte Nullzeile nur in CSV |
| 02.01.2026 | 1YIN9MVVAUZ00LUD | A2H57N | Vorabpauschale Ausland | 0,00 | 69,47 | -69,47 | 0,00 | 0,00 | Pass |
| 02.01.2026 | 1UIN9I2OPVI00MWU | A0JK68 | Vorabpauschale Ausland | 0,00 | 0,00 | 0,00 | 0,00 | 0,00 | Fehlt; belegte Nullzeile nur in CSV |
| 02.01.2026 | 2AIN9FOMKXM017GA | ETF039 | Vorabpauschale Ausland | 0,00 | 0,00 | 0,00 | 0,00 | 0,00 | Fehlt; belegte Nullzeile nur in CSV |
| 02.01.2026 | 0QIN9DCBVCO01FGV | A1JJTF | Vorabpauschale Ausland | 0,00 | 26,42 | -26,42 | 0,00 | 0,00 | Pass |
| 02.01.2026 | 0QIN9DCBVCO019K7 | A1JSHV | Vorabpauschale Ausland | 0,00 | 0,00 | 0,00 | 0,00 | 0,00 | Fehlt; belegte Nullzeile nur in CSV |
| 02.01.2026 | 0QIN9DCBVCO000SE | A0Q1YX | Vorabpauschale Ausland | 0,00 | 0,00 | 0,00 | 0,00 | 0,00 | Fehlt; belegte Nullzeile nur in CSV |
| 02.01.2026 | 0MIN967YUWH01GEC | A0LEW8 | Vorabpauschale Ausland | 0,00 | 0,00 | 0,00 | 0,00 | 0,00 | Fehlt; belegte Nullzeile nur in CSV |
| 02.01.2026 | 0MIN967YUWH005LR | A111X9 | Vorabpauschale Ausland | 0,00 | 96,35 | -96,35 | 0,00 | 0,00 | Pass |
| 15.01.2026 | 0UIN937038M008T0 | A0D8Q4 | Investment-Ausschüttung | 20,92 | 14,64 | -14,64 | 0,00 | 0,00 | Teilweise; FSA/BMG nach FSA fehlen |
| 02.01.2026 | 2IIN8Z0MGSM010KH | 593399 | Vorabpauschale Inland | 0,00 | 0,00 | 0,00 | 0,00 | 0,00 | Fehlt; belegte Nullzeile nur in CSV |
| 02.01.2026 | 2IIN8Z0MGSM009ZE | A0H074 | Vorabpauschale Inland | 0,00 | 0,00 | 0,00 | 0,00 | 0,00 | Fehlt; belegte Nullzeile nur in CSV |
| 02.01.2026 | 2IIN8Z0MGSM004VJ | A0D8Q4 | Vorabpauschale Inland | 0,00 | 0,00 | 0,00 | 0,00 | 0,00 | Fehlt; belegte Nullzeile nur in CSV |
| 02.01.2026 | 2IIN8Z0MGSM004EB | A0D8QZ | Vorabpauschale Inland | 0,00 | 0,00 | 0,00 | 0,00 | 0,00 | Fehlt; belegte Nullzeile nur in CSV |

## GUI-Prüfung auf temporärem Snapshot

Offscreen wurden die realen Dialogklassen instanziiert und ihre Tabellenmodelle
ausgelesen:

- `TaxDetailDialog`: 47 Zeilen; Vorgangsarten `Dividende`, `Dividende Inland`,
  `Investment-Ausschüttung Inland/Ausland`, `Vorabpauschale Ausland`,
  `Zinsertrag`.
- `TaxOverviewDialog`: comdirect-Zeile mit 680,04 € Kapitalerträgen, 54,42 €
  Steuern, 274,65 € Vorabpauschalen-Basis und 192,24 € steuerpflichtigem Anteil.
- `AccountBookingsDialog` für `Depot 4764924`: 59 Zeilen, darunter genau drei
  virtuelle `VORABPAUSCHALE`-, 19 `DISTRIBUTION`- und zwei `DIVIDEND`-
  Steuerereignisse. Damit ist die Klassifizierung nach PR #23 korrekt; die
  wirtschaftliche Doppelzählung entsteht nicht in dieser Depotansicht, sondern
  in Steuerdetail-/Übersichtsaggregation.
- SAP und Fresenius werden nicht als Vorabpauschale bezeichnet.
- 20 Dividenden-Cashzeilen werden in der steuerlichen Detailansicht zusätzlich
  zu den 21 zugehörigen PDF-Steuerereignissen gezeigt. Ursache ist die fehlende
  Verknüpfung: `fee_links=0`, während `automatic_tax_detail_records()` sein
  `event_by_aux` über diese Links aufbaut.

## A0D8Q4 vom 15.10.2026

PDF, CSV und gespeichertes Steuerereignis stimmen überein: Brutto 20,25 €,
Teilfreistellung 6,07 €, steuerlicher Ertrag/BMG 14,18 €, Kapitalertragsteuer
3,55 €, Soli 0,19 €, Gesamtsteuer 3,74 €. Das Ereignis ist als
`investment_ausschuettung_inland` gespeichert (Import-ID 71,
`import_model_records.rowid=124`). Im Datenbestand endet der letzte
Finanzreport vor dieser Buchung; deshalb existiert keine zugehörige Cash-
Dividende. Portman berücksichtigt die cash-neutrale Steuerzeile in der
Steuerübersicht, nicht aber den Ertrag. Das erzeugt für diesen Fall eine
asymmetrische Aggregation, ist aber keine Parserabweichung.

## SQL-Nachweise

Die folgenden Abfragen wurden gegen die produktive Datenbank mit
`PRAGMA query_only=ON` ausgeführt:

```sql
PRAGMA integrity_check;
PRAGMA foreign_key_check;

SELECT kind, COUNT(*)
FROM import_model_records
GROUP BY kind
ORDER BY kind;
-- booking_evidence 38, securities 83, tax_events 24

SELECT COUNT(*)
FROM import_model_records
WHERE kind = 'tax_details';
-- 0

SELECT COUNT(*) FROM fee_links;
-- 0

SELECT rowid, import_id, kind, payload
FROM import_model_records
WHERE kind = 'tax_events'
ORDER BY import_id, rowid;
```

Relevante IDs:

| Fall | `rowid` | `import_id` | Referenz | Typ | steuerlicher Ertrag | Steuer | `related_transaction_id` |
| --- | ---: | ---: | --- | --- | ---: | ---: | --- |
| A111X9 | 4 | 11 | 0MIN967YUWH005LR | vorabpauschale_ausland | 96,35 | 0,00 | leer |
| A1JJTF | 6 | 12 | 0QIN9DCBVCO01FGV | vorabpauschale_ausland | 26,42 | 0,00 | leer |
| A2H57N | 8 | 13 | 1YIN9MVVAUZ00LUD | vorabpauschale_ausland | 69,47 | 0,00 | leer |
| SAP 716460 | 24 | 21 | 0UINGIGZ23C007KN | dividende_inland | 4,49 | 0,00 | leer |
| Fresenius 578560 | 26 | 22 | 1SINHRMXMUV005VO | dividende_inland | 4,07 | 0,00 | leer |
| A0LEW8 | 40 | 29 | 20INO6681F3002EV | investment_ausschuettung_ausland | 28,62 | 6,38 | separate TAX-ID |
| 593399 | 42 | 30 | 1IINP4025ZX003K5 | investment_ausschuettung_inland | 24,60 | 6,48 | separate TAX-ID |
| A0D8QZ | 44 | 31 | 1IINP4025ZX00098 | investment_ausschuettung_inland | 39,29 | 10,36 | separate TAX-ID |
| A0H074 | 46 | 32 | 1IINP4025ZX000SB | investment_ausschuettung_inland | 6,37 | 1,67 | separate TAX-ID |
| A0D8Q4 15.10. | 124 | 71 | 1IINR5C2S7N006H5 | investment_ausschuettung_inland | 14,18 | 3,74 | separate TAX-ID |

## Ursachen und betroffene Funktionen

### P0 – doppelte Steueraggregation

`src/portman/tax_overview.py`, `automatic_tax_values()`:

- Dividenden addieren `tx.taxes`.
- Separate `TAX`-Transaktionen addieren denselben wirtschaftlichen Steuerbetrag
  nochmals.
- Der Ausschluss arbeitet nur über `fee_links`; produktiv sind keine Links
  vorhanden.

Folge: 24,89 € Doppelzählung und GUI-Steuern 54,42 € statt 29,53 €.

### P0 – falsche Ertragsbasis der Jahresübersicht

`src/portman/tax_overview.py:116` addiert für Vorabpauschalen
`advance_tax_base` (274,65 €) zu `capital_income`, obwohl die comdirect-
Ertragsspalte bereits den nach Teilfreistellung steuerpflichtigen Betrag von
192,24 € enthält. Gleichzeitig stammen Ausschüttungen in der Übersicht aus
Transaktions-Bruttowerten statt vollständig aus den 24 Steuerereignissen.

Folge: gemischte Basis, fehlender A0D8Q4-Oktoberertrag und 680,04 € statt
523,07 €. Ein bloßer Austausch von Basis gegen steuerpflichtigen Betrag reicht
nicht aus; die Ausschüttungsquelle und Dublettenlogik müssen ebenfalls
vereinheitlicht werden.

### P1 – doppelte Detailzeilen und fehlende Zusammenführung

`src/portman/automatic_tax_detail.py:167-176` und `:206-212` bauen die
Zuordnung zwischen Steuerereignis und Dividendenbuchung über `fee_links` auf.
Bei `fee_links=0` bleiben PDF-Ereignis und Cashzeile getrennt. Dadurch erscheinen
20 zusätzliche Dividendenzeilen und Steuerwerte doppelt in der Ansicht.

### P1 – unvollständige Zinsdetails

`src/portman/automatic_tax_detail.py:117-134` befüllt bei `INTEREST` zwar
`Gewinn/Verlust`, aber nicht `BMG nach VV`, `Veränderung FSA`, `BMG nach FSA`
oder `Steuerbemessungsgrundlage`. `automatic_tax_detail._security()` fragt auch
bei leerer Kennung `isin='' OR wkn=''` ab und findet dadurch zufällig ein
Wertpapier; die Zinszeilen zeigen WKN `A1KRJ0`.

### P1 – fehlende CSV-Abdeckung und Nullwerte

`RepositoryV09._imported_tax_detail_records()` kann die originalen 32 CSV-
Spalten verlustfrei liefern, wird im produktiven Datenbestand aber nicht
genutzt, weil kein `tax_details`-Import existiert. PDF/Finanzreport enthalten
nicht alle FSA- und belegten Nullzeilen. Diese Lücke darf nicht durch erfundene
Nullwerte geschlossen werden.

### P2 – 0,01-€-Bruttorekonstruktion

`automatic_tax_detail._event_values()` rekonstruiert Ausschüttungsbrutto als
`taxable_income + partial_exemption_amount`. Bei A0Q1YX vom 28.01. und ETF039
vom 18.02. ergibt das jeweils 0,01 € weniger als das in der CSV belegte Brutto.
Die steuerliche Bemessungsgrundlage bleibt korrekt; für eine exakte
Bruttodarstellung muss ein belegtes Bruttofeld Vorrang haben.

## Tests

### Reale, automatisierte Prüfharnesses

Ohne dauerhafte Repository-Test- oder Produktcodeänderung wurden temporäre,
automatisierte Prüfharnesses ausgeführt:

1. Referenz-CSV mit `parse_comdirect_tax_detail()` lesen, alle 39 Zeilen und
   sämtliche Steuer-/FSA-Spalten aggregieren.
2. Produktivdatenbank read-only prüfen, konsistent snapshotten und mit
   `RepositoryV09.tax_detail_records()`, `automatic_tax_values()` und
   `tax_overview()` auswerten.
3. Alle 24 Steuer-PDFs mit `portfolio_v5.pdf_importer.parse_pdf()` und den
   registrierten Plugins parsen.
4. `TaxDetailDialog`, `TaxOverviewDialog` und `AccountBookingsDialog` offscreen
   gegen den temporären Snapshot instanziieren und Tabellenwerte prüfen.

Die Harnesses bestätigen die im Bericht genannten Sollwerte und schlagen für
680,04 €, 54,42 €, die 47 Detailzeilen sowie die fehlenden Zins-/FSA-Felder
fachlich fehl. Sie wurden nach dem Audit nicht als Projektcode behalten, weil
der Auftrag ausdrücklich keine Codeänderungen vor der Entscheidung über einen
Fix erlaubt.

### Bestehende Tests

```text
Gezielte Steuertests:
44 passed, 2 warnings

Vollständige Suite:
1103 passed, 12 skipped, 2 warnings, 5 subtests passed
Laufzeit: 517,52 s
```

Die beiden Warnungen sind die bestehende Qt-Deprecation-Warnung zu
`QSortFilterProxyModel.invalidateFilter()` in `tax_detail_view.py:88`. Dass die
Suite trotz des FAIL-Befunds besteht, zeigt die fehlende reale
Jahresabgleich-Abdeckung.

## Priorisierte Korrekturempfehlungen

1. **P0:** In `automatic_tax_values()` eine Steuerkomponente genau einmal
   zählen. Cash-neutrale `TAX`-Hilfstransaktionen müssen mit der Dividenden-
   beziehungsweise Ausschüttungszeile zusammengeführt oder bei bereits
   enthaltener Steuer aus der Aggregation ausgeschlossen werden.
2. **P0:** Für die Steuerjahresübersicht eine eindeutige Basis festlegen. Für
   den comdirect-Abgleich ist `taxable_income`/`Steuerbemessungsgrundlage`
   maßgeblich. Vorabpauschalen dürfen nicht mit `advance_tax_base` in den
   steuerlichen Gesamtertrag eingehen.
3. **P1:** Die bestehende Zuordnung anhand Referenz, ISIN/WKN, Datum, Betrag,
   Konto und Depot auch ohne `fee_links` nutzen; PDF-Ereignis und Cashzeile in
   der Detailansicht fachlich zu einer Zeile zusammenführen.
4. **P1:** Zinszeilen vollständig befüllen und `_security()` bei leerer Kennung
   sofort mit leerem Namen/WKN beenden.
5. **P1:** Den comdirect-Steuerdetail-CSV-Import als offizielle Quelle für FSA,
   BMG nach FSA und belegte Nullzeilen verwenden. Unbekannte PDF-Felder dürfen
   nicht als `0,00` erfunden werden.
6. **P2:** Ein im Beleg vorhandenes Bruttofeld speichern/verwenden, statt es
   ausschließlich aus gerundeter Bemessungsgrundlage plus Teilfreistellung zu
   rekonstruieren.
7. Nach Freigabe eines Fixes persistente Regressionstests mit der realen CSV
   und den 24 PDFs ergänzen. Erwartet werden 39 fachliche Referenzzeilen,
   523,07 € steuerlicher Ertrag, 411,00 € FSA, 112,07 € BMG nach FSA, 29,53 €
   Steuer und keine zusätzliche wirtschaftliche Steuerwirkung.

## Entscheidung

**Eine Korrektur ist notwendig.** Die drei Vorabpauschalen und die PDF-Parser
sind nicht die Ursache. Zu korrigieren sind die nachgelagerte Zuordnung,
Dublettenunterdrückung und die Definition der aggregierten steuerlichen
Ertragsbasis. Bis zu diesem Audit wurden bewusst weder Code noch produktive
Daten geändert.
