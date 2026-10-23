# Portman V09 – P0 Steueraggregation 2026

Stand: 23.10.2026

Branch: `fix/tax-aggregation-p0-2026`

Basis: `main` / `69f7bf0` (PR #23 enthalten)

## Ergebnis

**PASS.** Die Jahresaggregation verwendet nun durchgehend die steuerpflichtige
Bemessungsgrundlage. PDF-Steuerereignis und Finanzreport-Cashbuchung werden auch
ohne `fee_links` konservativ zu genau einem fachlichen Vorgang zusammengeführt.
Die unveränderte comdirect-CSV liefert belegte FSA-, BMG-nach-FSA- und Nullwerte,
ohne Transaktionen anzulegen.

| Kennzahl | Vorher ohne CSV | Nach CSV-Referenzimport | comdirect Soll |
|---|---:|---:|---:|
| Steuerlicher Ertrag | 523,07 € | 523,07 € | 523,07 € |
| Verbrauchter FSA | 200,80 € (PDF-Abdeckung) | 411,00 € | 411,00 € |
| BMG nach FSA | nicht vollständig belegt | 112,07 € | 112,07 € |
| Einbehaltene Steuer inkl. SolZ | 29,53 € | 29,53 € | 29,53 € |
| Vorabpauschalen, steuerpflichtig | 192,24 € / 3 | 192,24 € / 3 | 192,24 € / 3 |
| Automatische Detailzeilen | 27 | 39 Originalzeilen | 39 |

Die Werte wurden aus einem konsistenten Snapshot der produktiven Datenbank
ermittelt. Die Quelle wurde ausschließlich mit SQLite `mode=ro` geöffnet; alle
weiteren Operationen liefen auf einer temporären Kopie. Produktive Daten wurden
nicht verändert.

## Fehlerursachen und Korrekturen

1. `automatic_tax_values()` addierte bei Ausschüttungen den Finanzreport-Brutto-
   betrag und bei Vorabpauschalen die Basis vor Teilfreistellung. Gleichzeitig
   konnten Steuer-Hilfsbuchungen mangels `fee_links` ein zweites Mal eingehen.
   Jetzt liefern Steuerereignisse die steuerpflichtige Basis und belegte Steuer;
   die Cashbuchung liefert nur den tatsächlichen Nettozufluss.
2. Die Verknüpfung hing zu stark von persistierten `fee_links` ab. Der neue
   read-only Matcher verlangt eindeutige Übereinstimmung bei Wertpapier, Depot,
   Datum sowie Brutto oder Netto. Mehrdeutige Fälle bleiben unverknüpft.
3. Ausschüttungsbrutto wurde bisher aus gerundeter BMG plus Teilfreistellung
   rekonstruiert. `TaxEvent.gross_income` bewahrt nun den Original-PDF-Wert;
   Altdaten verwenden weiterhin den kompatiblen Rückfall.
4. Zinszeilen enthielten keine automatische BMG. Belegtes Brutto wird nun als
   BMG ausgewiesen. Leere ISIN/WKN lösen keine zufällige Stammdatenzuordnung mehr
   aus.
5. Die 39 CSV-Zeilen werden verlustfrei als Referenzdaten verwendet. Für das
   abgedeckte Institut ersetzen ihre Summen die berechneten Steueraggregate;
   sie werden niemals zusätzlich addiert und erzeugen keinerlei Cashbuchung.

Geänderte Funktionen: `automatic_tax_values()`, `automatic_tax_detail_records()`,
`RepositoryV09._imported_tax_detail_records()`, comdirect-Steuerparser und der
neue rein lesende Matcher `match_tax_events()`.

## SQL-/Daten-Nachweise

Read-only Ausgangssnapshot:

- 367 Transaktionen
- 24 Steuerereignisse
- vor CSV-Import 27 fachlich zusammengeführte Detailzeilen
- nach CSV-Import 39 Original-Referenzzeilen
- CSV-Wiederimport: Status `duplicate`; Transaktions- und Ereigniszahl unverändert

Die CSV enthält keine Transaktionen und keine Steuerereignisse. Damit bleiben
Cashflows, Kontosalden, Bestände, Einstandskosten und Performance unverändert.
Cash-neutrale TAX-Hilfszeilen zu PDF-Ereignissen werden von der Aggregation
explizit ausgeschlossen.

## Tests

- Zieltests: **34 bestanden**
- Vollständige Suite: **1.105 bestanden, 12 übersprungen, 5 Subtests bestanden**
- Warnungen: zwei bestehende Qt-Deprecation-Warnungen in `tax_detail_view.py`
- Reale comdirect-CSV: **39/39 Zeilen**, alle sechs Sollaggregate erfüllt
- Importreihenfolgen PDF → Finanzreport und Finanzreport → PDF: bestanden
- Wiederimport/Dublettenschutz: bestanden
- fehlende `fee_links`: eindeutiger Fachabgleich bestanden
- Rekursiver PDF-Lauf: **126 physische PDFs**, **126 strukturiert**, **0 Parserfehler**
  (der aktuelle Ordner enthält inzwischen 24 Dateien mehr als die historische
  102-PDF-Referenz); Pluginverteilung: 93 comdirect-Erträge, 10 Finanzreports,
  23 strukturierte Kontoauszüge.

## Unverändert

Keine Buchungsarten oder Verwendungszwecke wurden geändert. Es entstanden keine
neuen wirtschaftlichen Buchungen. Originalbelege und produktive SQLite-Datei
blieben unverändert.
