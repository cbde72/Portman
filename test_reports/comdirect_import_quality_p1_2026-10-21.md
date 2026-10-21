# Portman V09 – comdirect Importqualität P1

## Ergebnis

Die drei P1-Bereiche wurden auf `fix/comdirect-import-quality-p1` umgesetzt.
Produktive SQLite-Datenbanken und Original-PDFs wurden nicht verändert. Alle
SQLite-Integrationstests verwendeten neue temporäre Datenbanken.

| PDF-Erkennung | Vorher | Nachher | Differenz |
|---|---:|---:|---:|
| Gesamt | 102 | 102 | 0 |
| Strukturiert | 62 | 79 | +17 |
| Generisch | 40 | 23 | −17 |
| Fehlerhaft | 0 | 0 | 0 |

Die 23 verbleibenden generischen PDFs sind ausschließlich MiFID-II-
Kosteninformationen. Sie werden weiterhin nicht als ausgeführte Trades oder
Cashflows behandelt.

## Fehlerursachen und Korrekturen

### Investment-Ausschüttungen

Finanzreport-Erträge bleiben als unveränderte `BANK_BOOKING`-Quelldatensätze
gespeichert. Die bisherige Linkbildung erwartete bereits aufgelöste
`DIVIDEND`-Datensätze und exakt gleiche Buchungsdaten. Sie fand reale
Finanzreportzeilen deshalb nicht zuverlässig.

`RepositoryV09._link_investment_distribution_taxes()` verwendet nun vor dem
Matching dieselbe konservative `infer_security_booking()`-Sicht wie die GUI.
Verglichen werden Wertpapieridentität über ISIN/WKN, Zieldepot, Cashkonto,
Brutto, Netto, Steuer und Referenzbelege. Buchungstag und Valuta dürfen maximal
drei Tage vom Ertragsdatum abweichen. Nur genau ein Treffer erzeugt einen
Eintrag in der vorhandenen Tabelle `fee_links`; null oder mehrere Treffer
erzeugen einen Prüfhinweis.

Mit den Originalbelegen und den Finanzreports September/Oktober wurden in
beiden Importreihenfolgen genau vier Links erzeugt:

| WKN | Ertragsdatum | Buchung/Valuta | Link |
|---|---|---|---:|
| A0LEW8 | 31.08.2026 | 01.09./02.09.2026 | 1 |
| 593399 | 15.09.2026 | 15.09.2026 | 1 |
| A0D8QZ | 15.09.2026 | 15.09.2026 | 1 |
| A0H074 | 15.09.2026 | 15.09.2026 | 1 |

A0H074 ergibt Brutto 9,10 EUR, Teilfreistellung 2,73 EUR, Steuerbasis
6,37 EUR, Steuer 1,67 EUR und Netto 7,43 EUR. Die separate Steuerbuchung bleibt
`affects_cash=false`; sie erzeugt keinen zusätzlichen Cash- oder
Performanceabfluss. Die Detailansicht verwendet den Link für eine
zusammengeführte Darstellung.

### Defekte comdirect-Kaufabrechnungen

Die beschädigten eingebetteten Fonts liefern lange, scheinbar umfangreiche,
aber numerisch unbrauchbare Texte. Deshalb gewann bisher der generische Handler.
Der bestehende comdirect-Handler erkennt nun die stabile Kombination aus
comdirect-Kopf, `GESCHÄFTSABRECHNUNG` und `Wertpapierkauf` auch ohne bereits
lesbare Detailzahlen. Nur für diese Dokumentfamilie wird bei fehlenden
Pflichtfeldern OCR angefordert.

OCR-Ergebnisse unterhalb der Mindestkonfidenz oder ohne Text werden abgelehnt.
Danach gelten unverändert die harten Prüfungen für ISIN, Stückzahl, Kurs,
Kurswert, Gebühren, Gesamtbetrag, Zahlungsrichtung und Datum. Die 12
unterschiedlichen Altbelege sowie drei identischen Kopien werden strukturiert
erkannt. Content-Hash-Dubletten behalten ihre stabile fachliche Identität und
erzeugen beim Wiederimport keine zweite Buchung.

### Normale Aktien-Dividenden

Fresenius 578560 und SAP 716460 werden als eigener Dokumenttyp
`dividende_steuer_inland` erkannt. Extrahiert werden Wertpapier, Stückzahl,
Brutto, Steuerbasis vor/nach Verlustverrechnung, verwendeter
Freistellungsauftrag, Kapitalertragsteuer, Solidaritätszuschlag, Kirchensteuer,
Gesamtsteuer, Netto, Datum, Valuta, Depot, Konto und Referenz.

Die belegten Steuerwerte 0,00 EUR bleiben explizite Nullwerte. Es wird keine
Steuer- oder Dividendenbuchung erfunden. Das Ereignis verwendet das bestehende
`TaxEvent`-Modell und der vollständige Originalbeleg bleibt erhalten. Eine
eindeutig gefundene Finanzreport-Dividende wird über
`related_transaction_id` fachlich zugeordnet.

## Geänderte Dateien

- `src/portman/repository_v09.py`: abgeleitete Finanzreport-Dividenden,
  ISIN/WKN- und Datumsmatching, eindeutige Linkbildung.
- `pdf_plugins/comdirect_ertraege.py`: Pluginversion 1.4, gezielte Erkennung
  beschädigter Kaufabrechnungen und normale inländische Dividendensteuer.
- `src/portman/automatic_tax_detail.py`: korrekter Vorgangstyp und Brutto/Netto
  für normale Dividenden-Steuerereignisse.
- `tests/test_comdirect_investment_distribution_tax.py`: rohe
  Finanzreport-`BANK_BOOKING`, beide Importreihenfolgen, Idempotenz und
  dokumentierte Nullsteuer.

## SQL- und API-Nachweis

In den temporären Integrationstests wurden unter anderem geprüft:

```sql
SELECT COUNT(*) FROM fee_links;
SELECT COUNT(*) FROM imports WHERE active=1;
SELECT COUNT(*) FROM transactions;
SELECT COUNT(*) FROM bank_documents;
SELECT COUNT(*) FROM import_model_records WHERE kind='tax_events';
```

Zusätzlich wurden `transactions()`, `tax_events()`, `tax_detail_records()`,
`automatic_tax_values()` und `performance_transactions()` geprüft. A0H074
liefert genau einen wirtschaftlichen Dividendenvorgang und genau einen Link;
wiederholte Imports ändern keine Zähler, Bestände, Salden oder Performance.

## Testergebnisse

- Gezielte comdirect-/Steuer-/Detailtests: 30 bestanden.
- Reale Problemfamilie LS9AVX/A2H57N/LYX05A: 26/26 vorhandene PDFs
  strukturiert, darunter die 15 zuvor generischen Dateien; 0 Fehler.
- Temporäre Originalbeleg-Integration: vier Investment-Ausschüttungen in beiden
  Importreihenfolgen jeweils 4/4 verknüpft.
- Rekursiver Originallauf: 102 geprüft, 79 strukturiert, 23 generisch,
  0 fehlerhaft.
- Gesamte Pytest-Suite: 1070 bestanden, 9 übersprungen, 5 Subtests bestanden,
  0 fehlgeschlagen.
- Zwei bekannte Qt-Deprecation-Warnungen in `tax_detail_view.py`, ohne Bezug zu
  dieser Änderung.

## Verbleibende Risiken und Aufgaben

- Die 23 Kosteninformationen bleiben bewusst generisch. Eine spätere
  strukturierte Kosteninformationsablage darf daraus keine Trades erzeugen.
- OCR bleibt von den in `requirements.txt` deklarierten lokalen Paketen
  `rapidocr`, `onnxruntime` und `pypdfium2` abhängig. Fehlen sie, wird der Beleg
  mit konkreter Fehlermeldung zurückgestellt.
- Bereits bestehende produktive Daten werden nicht automatisch nachverknüpft
  oder migriert; dieser PR wirkt auf neue beziehungsweise bewusst wiederholte
  Importvorgänge.
