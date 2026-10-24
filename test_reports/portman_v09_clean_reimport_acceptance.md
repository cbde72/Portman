# Portman V09 – Abnahme sauberer Neuimport

Prüfdatum: 24.10.2026

Basis: `main` / `089ba29` einschließlich PR #26

Fix-Branch: `fix/v09-clean-reimport-tax-matching`

## Ergebnis

**PASS nach Ursachenfix.** Ein vollständiger Neuimport über dieselben
Speichergrenzen wie die GUI ist in beiden geforderten Reihenfolgen
reproduzierbar. Es ist keine Datenbankreparatur erforderlich.

Die produktive Datenbank `data/v09/portfolio.sqlite` wurde ausschließlich über
eine SQLite-Read-only-Verbindung untersucht. Originaldokumente wurden nur
gelesen. Sämtliche Schreib-, Import- und Wiederholungstests liefen auf neu
erzeugten temporären SQLite-Datenbanken.

## Festgestellte und korrigierte Ursachen

Die GUI-Speicherwege sind vollständig auf `RepositoryV09.commit_batches()`
geführt:

- allgemeiner V09-Import: `ImportSession.apply()` → `repo.commit_batches()`;
- comdirect-Finanzreport: `commit_reports()` → `repo.commit_batches()`.

Zwei verbliebene Neuimportfehler lagen in der Nachverarbeitung:

1. `tax_matching` konnte auf einer frischen Datenbank eine Finanzreport-WKN
   nicht mit der ISIN des Steuerbelegs verbinden, obwohl die importierten
   `securities` diese eindeutige WKN↔ISIN-Brücke enthielten. Dadurch wurden
   Cash-Ausschüttung und Steuerereignis in der FSA-Auswertung doppelt gezählt.
   Das Matching verwendet nun diese persistierte Belegevidenz direkt.
2. Die Steuerlink-Nachverarbeitung verglich bei umbenannten IBAN-Konten den
   Anzeigenamen mit der Beleg-IBAN. Sie vergleicht jetzt die stabilen
   `account_registry`-/`accounts`-Schlüssel. Damit funktionieren sowohl das
   primäre Verrechnungskonto `…2440` als auch das zusätzliche Konto `…2400`.

Die Änderungen erzeugen keine neuen Cashflows und ändern keine Rohbuchungen.

## Dokumentbestand und Importreihenfolgen

Rekursiv geprüft wurde
`C:\Users\chris\Desktop\history\comdirect\2026`.

| Kennzahl | Finanzreports zuerst | Belege zuerst |
|---|---:|---:|
| Physische PDFs | 126 | 126 |
| Eindeutige PDF-Inhalte | 117 | 117 |
| Erkannte/fehlerfreie Batches | 117 | 117 |
| Aktive PDF-Imports | 117 | 117 |
| Zusätzlich vorab vorhandener manueller Import | 1 | 1 |
| Transaktionen einschließlich manuellem Platzhalter | 368 | 368 |
| Dokumentdatensätze | 144 | 144 |
| Kostenberichte | 23 | 23 |
| Steuerereignisse | 24 | 24 |
| `booking_evidence` | 38 | 38 |
| `booking_details` | 37 | 37 |
| Details mit `performance_depot_key = depot 4764924` | 37 | 37 |
| `fee_links` | 4 | 4 |
| verknüpfte Ausschüttungs-/Dividendenereignisse | 7 | 7 |
| Finanzreport-Saldointervalle | 27/27 | 27/27 |
| doppelte Kombinationen Konto/`external_id` | 0 | 0 |
| SQLite `integrity_check` / FK-Fehler | `ok` / 0 | `ok` / 0 |

Die früheren Referenzwerte 93 eindeutige Inhalte und sechs Ereignislinks sind
für den aktuellen Umfang nicht mehr anwendbar. Neu vorhanden sind 23
Ertragsgutschriften und der Steuerbeleg vom 15.10.2026. Die erwarteten 38
Kaufbelege, 37 eindeutigen Gegenbuchungen und vier besteuerten Ausschüttungen
bleiben unverändert.

## Steuer-, Gebühren- und Kaufverknüpfungen

Die vier `fee_links` verknüpfen die separat gebuchten Steuerbelastungen mit den
Finanzreport-Ausschüttungen für:

- `IE00B1FZS350` / A0LEW8;
- `DE000A0D8QZ7` / A0D8QZ;
- `DE0005933998` / 593399;
- `DE000A0H0744` / A0H074.

SAP und Fresenius bleiben korrekte Nullsteuerfälle ohne künstlichen
`fee_link`. Zusammen mit dem neuen Oktoberereignis besitzen sieben Ereignisse
eine persistente `related_transaction_id`.

Alle 37 eindeutig zuordenbaren Käufe besitzen in `booking_details` den
`performance_depot_key = depot 4764924`. Der Import berücksichtigt das primäre
Verrechnungskonto `IBAN …2440` und das zusätzliche Girokonto `IBAN …2400`.
Gebühren und Steuerbelastungen werden nur an vorhandene Cashflows angehängt;
der Wiederholungsimport erzeugt keine weiteren Transaktionen, Gebühren oder
Links.

## FSA ohne Steuerdetail-CSV

Es wurde keine Steuerdetail-CSV importiert. Aus den PDFs und Finanzreports
ergibt sich institutsweit:

| Prüfung | Ist | Soll |
|---|---:|---:|
| Steuerpflichtige Erträge | 523,07 € | 523,07 € |
| Hinterlegter FSA | 411,00 € | 411,00 € |
| Verbrauchter FSA | 411,00 € | 411,00 € |
| Verbleibender FSA | 0,00 € | 0,00 € |
| BMG nach FSA | 112,07 € | 112,07 € |
| Kapitalertragsteuer | 28,02 € | 28,02 € |
| Solidaritätszuschlag | 1,51 € | 1,51 € |

Der Status bleibt fachlich korrekt qualifiziert als „berechnet;
Steuer-/Verlustdaten nicht vollständig nachgewiesen“, weil nicht jeder
Einzelbeleg einen ausdrücklichen Verlusttopfwert enthält.

## Stammdaten, Einstellungen und Idempotenz

Vor jedem Neuimport wurden ein manueller Import, eine gespeicherte Ansicht,
die Kontostammdaten, die primäre/zusätzliche Verrechnungskontoverknüpfung, die
Instituts-FSA-Einstellung und eine externe Einstellungsdatei angelegt. Nach
beiden Importreihenfolgen und nach dem vollständigen Wiederholungsimport waren
diese Daten unverändert vorhanden. Alle 117 wiederholten PDF-Imports wurden als
`duplicate` erkannt; die Tabellenzähler blieben identisch.

## Verbleibender offener Beleg

Ein Kaufbeleg besitzt weiterhin keine Finanzreport-Gegenbuchung:

- `Wertpapierabrechnung_Kauf_0,014_St._LYX05A_(MUL-AM.MSCI_JPN_ETF_YND)_vom_07.10.2026_AC36DD.pdf`
- Dokumentreferenz `2OINQM8AXNO0038V`

Der Beleg bleibt bewusst nur als `booking_evidence` erhalten. Ohne eindeutigen
Cash-Gegenposten wird weder ein `booking_detail` noch eine zusätzliche
Cashbuchung erzeugt.

## Tests

```text
Gezielte Import-/Steuerregression:
24 passed in 9.12s

Realer Opt-in-Neuimport mit 126 PDFs, zwei Reihenfolgen und Wiederholungsimport:
2 passed in 302.75s

Vollständige Suite:
1121 passed, 14 skipped, 2 warnings, 5 subtests passed in 388.49s
```

Die zwei Warnungen sind bestehende Qt-Deprecation-Warnungen zu
`QSortFilterProxyModel.invalidateFilter()` und betreffen den Import nicht. Die
14 Skips enthalten unter anderem die zwei privaten Realtests im normalen Lauf;
diese wurden separat mit `PORTMAN_REAL_COMDIRECT_ACCEPTANCE=1` erfolgreich
ausgeführt.
