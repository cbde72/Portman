# Portman V09 – P1-Datenintegrität nach PR #18

Prüfdatum: 22.10.2026
Branch: `fix/pr18-data-integrity`
Ausgangsstand: `main` / `49ff9c8` (PR #18)

## Ergebnis

Die beiden im Bericht `portman_v09_sqlite_integrity_after_pr18.md`
nachgewiesenen P1-Probleme sind behoben. Alle Integrationsprüfungen verwendeten
neu erzeugte temporäre SQLite-Datenbanken. `data/v09/portfolio.sqlite` und die
Original-PDFs wurden nicht verändert.

| Abnahmewert | Vorher | Nachher |
|---|---:|---:|
| September-Steuerlinks | 0 | 4 |
| Korrekte `related_transaction_id` der sechs Referenzfälle | 0 | 6 |
| Strukturierte Kaufgebührendetails der drei Referenzfälle | 0 | 3 |
| Zusätzliche Kauftransaktionen | 0 | 0 |
| Zusätzliche Cashbelastungen | 0 | 0 |
| Finanzreport-Saldodifferenzen | 0/27 | 0/27 |
| Wiederholungsimporte mit Zähleränderung | – | 0 |

## Ursache und Korrektur

### Steuer-/Dividendenverknüpfungen

Die PR-#18-Logik filterte steuerfreie Investment-Ausschüttungen aus, weil sie
ein bereits gesetztes `related_transaction_id` voraussetzte. Bei
steuerpflichtigen Investment-Ausschüttungen blieb diese ID auf der
synthetischen TAX-Payment-ID. Nur reguläre Dividenden wurden auf eine
Finanzreportbuchung umgeschrieben. Dadurch blieben `fee_links` leer oder die
steuerliche Detailansicht konnte Ereignis und Dividende nicht als einen
fachlichen Vorgang darstellen.

Die Linkbildung verarbeitet nun alle belegten Investment-Ausschüttungen und
regulären Dividenden. Rohe `BANK_BOOKING`-Zeilen werden mit
`infer_security_booking()` abgeleitet. Ein automatischer Link entsteht nur bei
genau einem Treffer für Wertpapieridentität, Cashkonto, Zieldepot, Datum/Valuta
innerhalb von drei Tagen, Brutto, Netto, Steuer und belegte Referenzen.

`related_transaction_id` zeigt danach immer auf die fachliche
Finanzreport-Dividende. Bei einem tatsächlich gezahlten, separat gespeicherten
Steuerbetrag verbindet `fee_links` diese Dividende zusätzlich mit der
cash-neutralen TAX-Transaktion. Die Detailansicht verwendet die Dividende als
einzige Primärzeile und reichert sie mit dem Steuerereignis an.

Die Änderung des abgeleiteten `related_transaction_id` beeinflusst den
Duplikatschlüssel des unveränderten Steuer-PDFs nicht mehr. Wiederholungsimporte
bleiben deshalb idempotent.

### Persistenz der Kaufgebühren

Die Importvorschau behandelte Kaufabrechnungen korrekt als nicht-cashwirksame
Evidenz und ließ ihre Transaktion standardmäßig abgewählt. Dabei gingen aber
auch Gebühren, Stückzahl, Kurswert und Belegreferenz vor dem Repository verloren.

Kaufabrechnungen werden nun als `booking_evidence` in der vorhandenen Tabelle
`import_model_records` gespeichert. Sie erzeugen keine zweite Transaktion. Nach
jeder Importausführung wird die Evidenz in beiden Importreihenfolgen gegen rohe
Finanzreportbuchungen geprüft. Nur ein eindeutiger Treffer anhand Cashkonto,
Währung, Betrag, Datum/Valuta und gemeinsamer ISIN/WKN schreibt die belegten
Felder in die vorhandene Tabelle `booking_details`.

`transactions()` überlagert damit genau die ursprüngliche Cashbuchung mit
Wertpapier, Stückzahl, Kurswert, Preis, Gebührenpositionen und Belegreferenzen.
Der bereits inklusive Gebühren gebuchte Gesamtbetrag bleibt unverändert;
Performance und Einstandskosten sehen genau einen BUY-Zahlungsstrom.

## Originalbeleg-Integration

13 relevante Original-PDFs wurden in beiden Reihenfolgen importiert:

- vier Finanzreports;
- A0H074, A0LEW8, 593399 und A0D8QZ;
- Fresenius 578560 und SAP 716460;
- Kaufabrechnungen A111X9, A0S9GB und SAP 716460.

Ergebnis je Reihenfolge:

| Kennzahl | Finanzreport zuerst | Belege zuerst |
|---|---:|---:|
| Importiert | 13 | 13 |
| Fehler | 0 | 0 |
| Rohtransaktionen | 153 | 153 |
| `booking_evidence` | 3 | 3 |
| `booking_details` | 3 | 3 |
| `fee_links` | 4 | 4 |
| Wiederholungsimporte als Dublette | 13/13 | 13/13 |
| Zähler nach Wiederholung stabil | ja | ja |

Fachwerte:

| Fall | Ergebnis |
|---|---|
| A0H074 | Brutto 9,10; Teilfreistellung 2,73; Basis 6,37; Steuer 1,67; Netto 7,43 EUR |
| A0LEW8 | Ertragsdatum 31.08.; Buchung 01.09.; Valuta 02.09.; korrekt verknüpft |
| 593399 | Finanzreport-Dividende und TAX-Information eindeutig verknüpft |
| A0D8QZ | Finanzreport-Dividende und TAX-Information eindeutig verknüpft |
| Fresenius | reguläre Dividende, Nullsteuer, `related_transaction_id` auf Finanzreportbuchung |
| SAP Dividende | reguläre Dividende, Nullsteuer, `related_transaction_id` auf Finanzreportbuchung |
| A111X9 Kauf | 0,46 EUR Provision in `booking_details` |
| A0S9GB Kauf | 0,27 EUR Provision in `booking_details` |
| SAP Kauf | 0,43 EUR Provision in `booking_details` |

Alle vier TAX-Transaktionen bleiben `affects_cash=false`. Es gibt weder eine
zweite Nettoauszahlung noch eine zweite wirtschaftliche Steuerbelastung.

## Salden, PDF-Abdeckung und Tests

Die neun Original-Finanzreports wurden in einer weiteren temporären Datenbank
importiert. Für jeden Import und jedes der drei Konten wurde gerechnet:

```text
Endsaldo − Anfangssaldo − Summe der importierten Cashbuchungen
```

Alle 27 Ergebnisse sind exakt `0.00 EUR`.

Rekursiver PDF-Test mit `portfolio_v5.pdf_importer.parse_pdf()` und den
tatsächlich registrierten Plugins:

| Ergebnis | Anzahl |
|---|---:|
| PDFs gesamt | 102 |
| Eindeutige Inhalte | 93 |
| Strukturiert | 79 |
| Generisch | 23 |
| Parserfehler | 0 |

Die 23 generischen PDFs sind weiterhin ausschließlich Kosteninformationen und
erzeugen keine Trades oder Cashflows.

Finale Pytest-Suite:

```text
1073 passed, 9 skipped, 5 subtests passed, 0 failed
2 bekannte Qt-Deprecation-Warnungen
Laufzeit 285,66 s
```

## SQL-Nachweise

Die temporären Integrationsdatenbanken wurden unter anderem mit folgenden
Abfragen geprüft:

```sql
SELECT COUNT(*) FROM imports WHERE active=1;
SELECT COUNT(*) FROM transactions;
SELECT COUNT(*) FROM booking_details;
SELECT COUNT(*) FROM import_model_records WHERE kind='booking_evidence';
SELECT COUNT(*) FROM fee_links;

SELECT transaction_id,
       json_extract(payload, '$.security') AS security,
       json_extract(payload, '$.fees') AS fees,
       json_extract(payload, '$.gross_amount') AS gross_amount,
       source_hash
FROM booking_details
ORDER BY transaction_id;

SELECT json_extract(payload, '$.security_ref') AS security,
       json_extract(payload, '$.related_transaction_id') AS related_transaction_id,
       json_extract(payload, '$.paid_taxes') AS paid_taxes
FROM import_model_records
WHERE kind='tax_events';

SELECT aux_ref, field, fee_ref, reason
FROM fee_links
ORDER BY aux_ref;

SELECT json_extract(payload, '$.kind') AS kind,
       json_extract(payload, '$.affects_cash') AS affects_cash,
       COUNT(*)
FROM transactions
GROUP BY kind, affects_cash;
```

Für die Gebührenfälle ergaben die Abfragen drei `booking_details` und weiterhin
nur drei ursprüngliche Cashtransaktionen. Für die September-Steuerfälle ergaben
sie vier `fee_links`; die zugehörigen TAX-Zeilen blieben cash-neutral.

## Geänderte Bereiche

- `portfolio_v5.models.ImportBatch`: explizite nicht-cashwirksame
  `booking_evidence`.
- `portfolio_v5.storage`: Speicherung der Evidenz in vorhandenen
  `import_model_records`; abgeleitete Steuerlinks beeinflussen die
  Quelldokument-Deduplizierung nicht.
- `portfolio_v5.import_accounts`: Evidenzkonten werden bei der Zuordnung
  berücksichtigt.
- `portman.import_preview`: comdirect-Kaufbelege bleiben als Evidenz erhalten.
- `portman.repository_v09`: eindeutiger Gebührenabgleich und vollständige
  Steuer-/Dividendenverknüpfung.
- `portman.automatic_tax_detail`: genau eine angereicherte Dividendenzeile.
- `portman.import_v09`: verlustfreie Session-Decodierung der Evidenz.
- `tests/test_comdirect_p1_integrity.py`: beide Reihenfolgen, Idempotenz,
  Nullsteuer, Gebührenpersistenz, Cashflow und Performance.

## Freigabeempfehlung

**PASS.** Die beiden P1-Probleme sind im aktuellen Code behoben und mit
synthetischen sowie realen Originalbelegen in beiden Importreihenfolgen
abgedeckt. Für bereits bestehende produktive Daten wird keine automatische
Migration oder Reparatur ausgeführt; eine spätere Neuverknüpfung muss bewusst
und mit Vorschau erfolgen.
