# Portman V09 – Steuerberechnung 2026 / comdirect-Abgleich

Prüfdatum: 23.10.2026

Branch: `fix/vorabpauschale-taxable-basis-2026`

## Gesamtbewertung

**PASS MIT HINWEISEN.** Die vier comdirect-Referenzwerte lassen sich aus den
vorhandenen strukturierten Belegen centgenau reproduzieren. Bei den drei
Vorabpauschalen sind 192,24 EUR ausdrücklich die Summe der
Steuerbemessungsgrundlagen nach Teilfreistellung, nicht die Summe der
Brutto-Vorabpauschalen.

Der Parser speichert die Belege korrekt. Der Fehler lag in
`automatic_tax_values()`: `advance_tax_taxable` enthielt bereits 192,24 EUR,
für das aggregierte `capital_income` wurden jedoch fälschlich 274,65 EUR
Bruttobasis addiert. Der Fix verwendet dort ausschließlich die belegte
steuerpflichtige Bemessungsgrundlage und verhindert einen nachgelagerten
zweiten Abzug derselben Teilfreistellung.

Die produktive SQLite-Datei wurde ausschließlich mit `mode=ro` und
`PRAGMA query_only=ON` geöffnet. Fachliche Abfragen liefen auf einem mit der
SQLite-Backup-API erzeugten temporären Snapshot. Original-PDFs und produktive
Daten wurden nicht verändert.

## Drei Vorabpauschalen im Originalbeleg

Alle drei Dokumente nennen als steuerliche Behandlung den 02.01.2026 und
betreffen das Ertragsjahr 2025. Steuerjahr/Zuflussjahr in Portman ist 2026.

| WKN | ISIN | Dokumentdatum | Ertragsjahr | Brutto | Teilfreistellung | steuerpflichtige BMG | KapESt | SolZ | KiSt | belastete Steuer |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| A1JJTF | IE00B48X4842 | 20.01.2026 | 2025 | 37,75 EUR | 11,33 EUR / 30 % | 26,42 EUR | 0,00 | 0,00 | 0,00 | 0,00 EUR |
| A111X9 | IE00BKM4GZ66 | 19.01.2026 | 2025 | 137,65 EUR | 41,30 EUR / 30 % | 96,35 EUR | 0,00 | 0,00 | 0,00 | 0,00 EUR |
| A2H57N | LU1681041973 | 26.01.2026 | 2025 | 99,25 EUR | 29,78 EUR / 30 % | 69,47 EUR | 0,00 | 0,00 | 0,00 | 0,00 EUR |
| **Summe** | | | | **274,65 EUR** | **82,41 EUR** | **192,24 EUR** | **0,00** | **0,00** | **0,00** | **0,00 EUR** |

Nachweis:

```text
274,65 EUR Brutto − 82,41 EUR Teilfreistellung = 192,24 EUR
26,42 + 96,35 + 69,47 = 192,24 EUR
```

Die Bankreferenz „Vorabpauschale (Ausland) 192,24 EUR“ ist daher ein
steuerpflichtiger Ertrag nach Teilfreistellung. Sie ist weder Bruttoertrag noch
Steuerzahlung.

## Gesamtvergleich 2026

Für Ausschüttungen und Dividenden wurde ebenfalls die in den
Steuermitteilungen ausdrücklich ausgewiesene `taxable_income` summiert. Die
Habenzinsen stammen aus den Finanzreport-Abschlussbuchungen.

| Ertragsart | comdirect | Portman nach Fix | Differenz | Berechnungsgrundlage |
|---|---:|---:|---:|---|
| Investment-Ausschüttungen | 314,33 EUR | 314,33 EUR | 0,00 EUR | 201,21 EUR Inland + 113,12 EUR Ausland, jeweils steuerpflichtige BMG |
| Vorabpauschale Ausland | 192,24 EUR | 192,24 EUR | 0,00 EUR | drei `tax_events.taxable_income` nach Teilfreistellung |
| Inländische Dividenden | 8,56 EUR | 8,56 EUR | 0,00 EUR | SAP 4,49 EUR + Fresenius 4,07 EUR |
| Habenzinsen | 7,94 EUR | 7,94 EUR | 0,00 EUR | 1,97 + 2,55 + 3,42 EUR Bruttozins |
| **Gesamt** | **523,07 EUR** | **523,07 EUR** | **0,00 EUR** | Summe der vier steuerpflichtigen Ertragsarten |

SQL-/Modellnachweis für die Steuerereignisse:

```sql
SELECT json_extract(payload,'$.type') AS type,
       SUM(CAST(json_extract(payload,'$.taxable_income') AS NUMERIC)) AS taxable,
       SUM(CAST(json_extract(payload,'$.advance_tax_base') AS NUMERIC)) AS advance_base,
       SUM(CAST(json_extract(payload,'$.partial_exemption_amount') AS NUMERIC)) AS partial
FROM import_model_records
WHERE kind='tax_events'
  AND COALESCE(json_extract(payload,'$.tax_year'),
               substr(json_extract(payload,'$.date'),1,4))='2026'
GROUP BY type;
```

Ergebnis:

| Typ | steuerpflichtig | Vorab-Brutto | Teilfreistellung |
|---|---:|---:|---:|
| `vorabpauschale_ausland` | 192,24 | 274,65 | 82,41 |
| `investment_ausschuettung_inland` | 201,21 | – | 86,23 |
| `investment_ausschuettung_ausland` | 113,12 | – | 8,56 |
| `dividende_inland` | 8,56 | – | 0,00 |

## Vorher/Nachher im betroffenen Aggregat

| Kennzahl | Vorher | Nachher | Änderung |
|---|---:|---:|---:|
| Vorabpauschale brutto (`advance_tax_base`) | 274,65 | 274,65 | 0,00 |
| Vorabpauschale steuerpflichtig (`advance_tax_taxable`) | 192,24 | 192,24 | 0,00 |
| Teilfreistellung Vorabpauschale | 82,41 | 82,41 | 0,00 |
| Beitrag der Vorabpauschalen zu `capital_income` | **274,65** | **192,24** | **−82,41** |
| gesamtes automatisch gebuchtes `capital_income` im aktuellen Snapshot | 680,04 | 597,63 | −82,41 |

Die letzte Gesamtkennzahl ist keine direkte Entsprechung der Banksumme
523,07 EUR: Die bestehende GUI-Spalte „Kapitalerträge gebucht“ enthält bei
Investment-Ausschüttungen weiterhin die aus Cashbuchungen rekonstruierte
Bruttodarstellung. Diese Darstellung und ihre Berechnung wurden entsprechend
der engen Aufgabenabgrenzung nicht geändert. Der fachliche Vier-Kategorien-
Abgleich oben verwendet für jede Ertragsart die steuerpflichtige Bankbasis.

## Codekorrektur

Geändert wurde ausschließlich `src/portman/tax_overview.py`:

1. Eine ausdrücklich gespeicherte `taxable_income` hat Vorrang.
2. Fehlt sie, wird nur bei gemeinsam belegter Bruttobasis und
   Teilfreistellung `Brutto − Teilfreistellung` berechnet.
3. Bei unvollständigen Fakten wird kein Betrag erfunden; das Ergebnis bleibt
   null/unbekannt statt die Bruttobasis als steuerpflichtig zu behandeln.
4. `capital_income` erhält bei Vorabpauschalen die steuerpflichtige BMG.
5. Die separat sichtbare Teilfreistellung bleibt erhalten, wird in der
   Freistellungs-Fallbackrechnung aber nicht ein zweites Mal abgezogen.

Unverändert bleiben Parserwerte, Bruttobasis, `purpose`, `kind`, GUI-Texte,
Dokumentenreferenzen, Steuerzahlungen, Ausschüttungs-/Dividenden-/Zinswerte,
Cashflows, Salden, Bestände, Einstandskosten und Performance.

## Vollständigkeit der Datenbasis

Die Sammlung enthält die drei eindeutigen Vorabpauschalen vollständig; Kopien
in `Januar` und `Steuerinformationen` haben identische Inhalte und werden nicht
doppelt gezählt. Die vorhandenen Steuerereignisse decken die vier angegebenen
Bankreferenzen centgenau ab.

Der PDF-Zeitraum ist jedoch kein abgeschlossenes Steuerjahr: Der letzte
Finanzreport endet am 01.10.2026 und weist Zinsen nur bis 30.09.2026 aus.
Etwaige Erträge oder Jahresabschlusszinsen des vierten Quartals sind im
vorliegenden Bestand noch nicht belegbar. Das Ergebnis ist deshalb ein PASS
für den dokumentierten Bankstand, nicht die Bestätigung eines vollständigen
Kalenderjahres 2026.

## Regression

Die Tests decken ab:

- alle drei realen PDFs und 192,24 EUR Gesamtsumme;
- ausdrückliche BMG vor berechneter BMG;
- Fallback nur aus vollständig belegtem Brutto und Teilfreistellungsbetrag;
- keine doppelte Teilfreistellung;
- Steuerjahr 2026 versus Ertragsjahr 2025;
- unveränderte Ausschüttungs-, Dividenden- und Zinslogik;
- keine Transaktionen, Cashflows oder Bestandsänderungen durch die drei
  cash-neutralen Vorabpauschalen.

```text
Gezielte Steuer-/Importtests: 38 passed
Gesamte Pytest-Suite: 1105 passed, 12 skipped
```
