# Portman V09 – P0 GUI-Import-Nachverknüpfung

Prüfdatum: 22.10.2026

Branch: `fix/gui-import-postprocessing`

Ausgangsbasis: `main` / `1c91ae9`

## Ergebnis

**PASS.** Die fehlenden Datensätze entstanden nicht durch uneindeutige Belege,
sondern durch zwei GUI-Speicherpfade, die direkt `Store.import_batch()`
aufriefen. Dadurch wurde die V09-Nachverarbeitung in
`RepositoryV09.commit_batches()` vollständig umgangen. Beide GUI-Pfade
verwenden nun dieselbe Repository-Grenze wie der zuvor erfolgreiche isolierte
Integrationstest.

Die produktive Datenbank wurde ausschließlich lesend untersucht. Sämtliche
Imports und SQL-Abnahmen liefen auf neu erzeugten SQLite-Dateien unter `.tmp/`.
Es wurde keine produktive Reparatur ausgeführt.

## Fehlerursache und Korrektur

| Pfad | Vorher | Nachher |
|---|---|---|
| allgemeiner V09-Importwizard | `ImportSession.apply()` → `repo.store.import_batch()` | `ImportSession.apply()` → `repo.commit_batches()` |
| comdirect-Finanzreport-Vorschau | `commit_reports()` → `repo.store.import_batch()` + manueller Stammdaten-Sync | `commit_reports()` → `repo.commit_batches()` |

Der direkte Store-Aufruf speicherte Imports, Buchungen, Dokumente und
`booking_evidence`, kannte aber bewusst keine V09-Fachnachverarbeitung. Deshalb
liefen weder `_persist_comdirect_trade_details()` noch
`_link_investment_distribution_taxes()`. Das erklärt exakt den produktiven
Stand `38 booking_evidence / 0 booking_details / 0 fee_links`.

Zusätzlich übernimmt die Kaufbeleg-Nachverarbeitung jetzt das gemappte
Zieldepot als `performance_depot_key` in `booking_details`, wenn

- die Belegquelle eindeutig auf ein aktives Depot gemappt ist und
- das Cashkonto als primäres oder zusätzliches Verrechnungskonto dieses
  Depots konfiguriert ist.

Damit bleiben die Rohdaten unverändert; die wirtschaftliche Anreicherung liegt
weiterhin ausschließlich in `booking_details`. Unklare oder nicht erlaubte
Kontozuordnungen werden nicht geraten.

Geänderte Funktionen:

- `portman.import_v09.ImportSession.apply`
- `portman.comdirect_import.commit_reports`
- `portman.repository_v09.RepositoryV09._persist_comdirect_trade_details`

## Reale End-to-End-Abnahme

Alle PDFs unter `C:\Users\chris\Desktop\history\comdirect\2026` wurden erneut
mit `portfolio_v5.pdf_importer.parse_pdf()` und den registrierten Plugins
eingelesen. Danach wurden zwei frische Datenbanken über die tatsächlichen
GUI-Speicherfunktionen aufgebaut: einmal Finanzreports zuerst, einmal alle
anderen Belege zuerst.

| Prüfung | Finanzreport zuerst | Belege zuerst |
|---|---:|---:|
| physische PDFs | 102 | 102 |
| strukturierte Erkennung | 102 | 102 |
| generisch / Parserfehler | 0 / 0 | 0 / 0 |
| eindeutige Inhalte / aktive Imports | 93 / 93 | 93 / 93 |
| Transaktionen | 366 | 366 |
| Dokumentdatensätze | 120 | 120 |
| MiFID-II-CostReports | 23 | 23 |
| Steuerereignisse | 23 | 23 |
| `booking_evidence` | 38 | 38 |
| `booking_details` | **37** | **37** |
| `fee_links` | **4** | **4** |
| verknüpfte Dividendenereignisse | **6** | **6** |
| Saldoabgleiche | **27/27** | **27/27** |
| Wiederholungsimport | 93 `duplicate` | 93 `duplicate` |

Vor und nach dem Wiederholungsimport waren alle Tabellenzähler identisch.
`PRAGMA integrity_check` ergab jeweils `ok`, `PRAGMA foreign_key_check` keine
Zeile und die Abfrage nach doppelten Kombinationen aus Konto und
`external_id` null Treffer.

Der Kaufbeleg vom 07.10.2026 (`LU2090063673`, 1,33 EUR) blieb als einziger der
38 Belege ohne `booking_details`, weil kein eindeutiger Finanzreport-Gegenposten
vorliegt. Es wurde keine automatische Zuordnung erzeugt.

## SQL-Nachweise

Zähler nach beiden Importreihenfolgen:

```sql
SELECT COUNT(*) FROM imports WHERE active=1;                         -- 93
SELECT COUNT(*) FROM transactions;                                  -- 366
SELECT COUNT(*) FROM bank_documents;                                -- 120
SELECT COUNT(*) FROM import_model_records WHERE kind='cost_reports'; -- 23
SELECT COUNT(*) FROM import_model_records WHERE kind='tax_events';   -- 23
SELECT COUNT(*) FROM import_model_records
 WHERE kind='booking_evidence';                                     -- 38
SELECT COUNT(*) FROM booking_details;                               -- 37
SELECT COUNT(*) FROM fee_links;                                     -- 4
```

Die vier `fee_links` zeigen auf die besteuerten Finanzreport-Dividenden für
`IE00B1FZS350`, `DE000A0D8QZ7`, `DE0005933998` und `DE000A0H0744`.
Zusätzlich zeigen die Nullsteuer-Ereignisse von SAP (`DE0007164600`) und
Fresenius (`DE0005785604`) per `related_transaction_id` auf ihren jeweiligen
Finanzreport-Cashflow, ohne künstlichen `fee_link`.

Referenzgebühren in `booking_details`:

| Fall | Transaktions-ID im Prüflauf | Datum | Gebühr |
|---|---:|---|---:|
| A111X9 | 330 | 07.09.2026 | 0,46 EUR |
| A0S9GB | 348 | 23.09.2026 | 0,27 EUR |
| SAP 716460 | 272 | 23.07.2026 | 0,43 EUR |

Die 37 angereicherten Käufe besitzen bei der produktiv konfigurierten
Kontobeziehung (`IBAN ...2400` als zusätzliches Verrechnungskonto) den
`performance_depot_key = 'depot 4764924'`. Insgesamt werden in der
Repository-/Performance-Sicht alle 38 erkannten Käufe sowie 20 Dividenden, neun
Gebührenbuchungen und vier Steuerbuchungen diesem Depot zugeordnet. Gebühren
und Steuern bleiben Bestandteil des vorhandenen Cashflows und werden nicht als
zweite wirtschaftliche Buchung erzeugt.

Der Saldoabgleich wurde je Finanzreport und Konto ausgeführt:

```text
Anfangssaldo + Summe(affects_cash=true) = Endsaldo
27 korrekt, 0 abweichend
```

## Automatisierte Regression

Neue Tests bilden nicht nur direkte Repository-Aufrufe nach, sondern beide
produktiven GUI-Speichergrenzen, beide Importreihenfolgen und den
Wiederholungsimport. Sie prüfen Kaufdetails, Depotzuordnung,
Steuer-/Dividendenlinks, Idempotenz und unveränderte Buchungszahlen.

```text
Gezielte Import-/GUI-Regression: 35 passed
Gesamte Pytest-Suite: 1102 passed, 12 skipped
```

## Vorher/Nachher

| Merkmal | produktiver Neuimport vor Fix (nur lesend) | temporärer GUI-Import nach Fix |
|---|---:|---:|
| `booking_details` | 0 | 37 |
| `fee_links` | 0 | 4 |
| Dividenden-Referenzverknüpfungen | 0 | 6 |
| eindeutige Imports / Transaktionen / Dokumente | 93 / 366 / 120 | 93 / 366 / 120 |
| Saldoabgleiche | 27/27 | 27/27 |
| doppelte wirtschaftliche Buchungen | 0 | 0 |

Die Korrektur verändert somit ausschließlich die fehlende abgeleitete
Verknüpfung und Depotzuordnung. Originalbelege, Rohbuchungen, Cashsalden,
Bestände und MiFID-II-Neutralität bleiben erhalten.
