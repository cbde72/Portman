# PR #17 – SQLite-Integration A0H074 nach Korrektur

## Ergebnis

Die im Ausgangsbericht `sqlite_integration_a0h074_2026-10-21.md`
nachgewiesenen P0-/P1-Fehler sind behoben. Die Regressionstests verwenden für
jede Importreihenfolge eine eigene temporäre SQLite-Datenbank. Produktive
Datenbanken und Originalbelege wurden nicht verändert.

| Abnahmewert | Ergebnis |
|---|---:|
| Bruttoertrag | 9,10 EUR |
| Steuerbemessungsgrundlage | 6,37 EUR |
| Teilfreistellung | 2,73 EUR |
| Wirtschaftliche Steuer | 1,67 EUR |
| Netto-Cashflow | 7,43 EUR |
| Fachliche Ausschüttungsvorgänge | 1 |
| Doppelte Steuerbuchungen | 0 |
| Doppelte aktive Dokumente beim Wiederimport | 0 |

## Geprüfte Importfolgen

Beide Folgen liefern denselben wirtschaftlichen Endzustand:

1. Steuermitteilung, danach Finanzreport-Ausschüttung
2. Finanzreport-Ausschüttung, danach Steuermitteilung

Die Steuerbuchung übernimmt in beiden Fällen das gemappte Zieldepot
`depot 4764924`. Die separate Steuermitteilung bleibt als Originalbeleg und
Steuerereignis erhalten, wird aber über den bestehenden `fee_links`-Mechanismus
mit der Dividende verknüpft und nicht als zusätzlicher Cash- oder
Performanceabfluss gezählt. ISIN `DE000A0H0744` und WKN `A0H074` werden dabei
über die vorhandenen `SecurityInfo`-Datensätze als identisches Wertpapier
aufgelöst.

Die Steuerdetailansicht erzeugt eine zusammengeführte Zeile mit dem Vorgang
`Investment-Ausschüttung Inland`, Brutto 9,10 EUR, Steuerbasis 6,37 EUR,
Teilfreistellung 2,73 EUR, KapESt 1,59 EUR, SolZ 0,08 EUR, KiSt 0,00 EUR,
Gesamtsteuer 1,67 EUR und Netto 7,43 EUR.

## SQL- und API-Prüfungen

Die automatisierten Tests prüfen nach beiden Importfolgen und nach dem
Wiederimport unter anderem:

```sql
SELECT COUNT(*) FROM imports WHERE active=1;
SELECT COUNT(*) FROM transactions;
SELECT COUNT(*) FROM bank_documents;
SELECT COUNT(*) FROM import_model_records WHERE kind='tax_events';
SELECT COUNT(*) FROM fee_links;
```

Zusätzlich geprüft wurden `transactions()`, `tax_events()`,
`tax_detail_records()`, `automatic_tax_values(..., 2026)` und
`performance_transactions(...)`. Die Wiederholung beider PDFs liefert jeweils
`status=duplicate`; alle geprüften Zähler bleiben unverändert.

## Testnachweise

- A0H074-Integration und comdirect-Steuerparser: 7 bestanden.
- Angrenzende Steuer-, Settlement-, Performance- und Detailtests:
  76 bestanden, 2 Subtests bestanden.
- Nach Korrektur einer bestehenden Reconciliation-Regression:
  9 gezielte Tests bestanden.
- Rekursiver, schreibgeschützter Originallauf:
  102 PDFs, 62 strukturiert erfolgreich, 40 generisch, 0 fehlerhaft.
- Pluginverteilung: 10 Finanzreports, 26 Wertpapierkäufe,
  6 Vorabpauschalen, 20 Investment-Ausschüttungen, 40 generische Dokumente.

Der finale vollständige Pytest-Lauf ergab 1069 bestandene, 9 übersprungene und
0 fehlgeschlagene Tests sowie 5 bestandene Subtests. Die zwei ausgegebenen
Qt-Deprecation-Warnungen in `tax_detail_view.py` sind bekannt und stehen nicht
mit dieser Änderung in Zusammenhang.
