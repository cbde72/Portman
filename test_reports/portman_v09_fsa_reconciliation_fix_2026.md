# Portman V09 – P1 Freibetragsabgleich 2026

Stand: 23.10.2026

Branch: `feature/production-acceptance-copy-tax-summary`

PR-Strategie: Der Fix ergänzt den noch offenen PR #25, weil die fehlerhafte
Aggregation in der dort neu eingeführten `tax_annual_summary.py` liegt. Ein
zweiter PR mit konkurrierenden Änderungen an derselben GUI wurde vermieden.

## Gesamtbewertung

**PASS.** Ein institutsspezifischer Freistellungsauftrag wird unabhängig von
der Kontenzahl genau einmal berücksichtigt. Ohne belegte Aufteilung zeigt eine
einzelne Kontoansicht den gemeinsamen Rest-FSA als `n. v.`. Die Institutsansicht
summiert nachgewiesenen Verbrauch und berechnet anschließend einmalig
`Instituts-FSA − Verbrauch`.

## Technische Ursache

PR #25 legte den Instituts-FSA von 411,00 € in jeder steuerlich relevanten
Kontozeile zugrunde. Die GUI summierte anschließend die bereits je Konto
berechneten Restbeträge.

Für die zum Fehlerzeitpunkt sichtbaren zwei comdirect-Kontozeilen galt daher:

```text
(411,00 € - 200,80 €) + (411,00 € - 0,00 €) = 621,20 €
411,00 € + 411,00 € = 822,00 € rechnerische FSA-Basis
```

Die Verdopplungshypothese ist damit bestätigt. Es lagen nicht zwei FSA-
Datensätze vor; die produktive Tabelle enthält genau einen Institutsdatensatz:

```sql
SELECT institution_key, institution, year, exemption
FROM institution_tax_years
WHERE institution_key='comdirect' AND year=2026;
-- comdirect | Comdirect | 2026 | 411.00
```

Die Konto-Steuertabelle enthält für die comdirect-Konten leere FSA-Felder. Die
822,00 € entstanden ausschließlich in der GUI-Aggregation, nicht in SQLite.

## Herkunft der 200,80 €

Die produktive Steuerdetail-CSV ist weiterhin nicht importiert
(`tax_details = 0`). Portman kann deshalb nur die vorhandenen PDF-Ereignisse
auswerten:

- drei steuerpflichtige Vorabpauschalen: 192,24 €;
- SAP- und Fresenius-Dividenden mit verbrauchtem FSA: zusammen 8,56 €;
- Summe: 200,80 €.

Dieser Betrag ist eine korrekte, aber unvollständige PDF-Abdeckung. Er wird
nicht mehr als belegter Gesamtverbrauch der Bank ausgegeben. Nach Import der
39-zeiligen comdirect-CSV ersetzt deren dokumentierter Verbrauch von 411,00 €
die PDF-Ableitung für das abgedeckte Institut.

## Korrektur

- Neue zentrale Funktion `aggregate_tax_annual_rows()` aggregiert alle
  Kontozeilen eines Instituts.
- Additive Steuerwerte werden kontenübergreifend summiert.
- Der Instituts-FSA wird nicht auf Konten vervielfältigt.
- Der Rest-FSA wird erst nach der Verbrauchsaggregation einmal berechnet.
- Kontobezogene Restwerte bleiben bei gemeinsamem FSA `n. v.`.
- `used_exemption=0,00` gilt nur als bekannt, wenn ein Steuerereignis oder eine
  CSV-Zeile den Wert tatsächlich belegt.
- Fehlende Verbrauchsdaten bleiben `None`/`n. v.`.
- Bank- und Portman-Werte bleiben getrennt.

Es existiert damit nur eine fachliche Aggregationslogik für die neue Ansicht;
die GUI addiert keine bereits berechneten FSA-Restwerte mehr.

## Vorher/Nachher auf produktivem Snapshot

| Zustand | FSA hinterlegt | Portman verbraucht | Portman verbleibend |
|---|---:|---:|---:|
| Vor Fix, ohne CSV | 411,00 € | 200,80 € | 621,20 € (falsch) |
| Nach Fix, ohne CSV | 411,00 € | 200,80 € | 210,20 € |
| Nach Fix, reale CSV temporär importiert | 411,00 € | 411,00 € | 0,00 € |

Der temporäre CSV-Import ergab außerdem unverändert:

- steuerpflichtige Erträge 523,07 €;
- BMG nach FSA 112,07 €;
- Kapitalertragsteuer 28,02 €;
- Solidaritätszuschlag 1,51 €;
- Kirchensteuer 0,00 €;
- steuerpflichtige Vorabpauschalen 192,24 €.

Vor und nach dem CSV-Test blieben 367 Transaktionen und 24 Steuerereignisse
erhalten. Die CSV erzeugte keine wirtschaftliche Buchung.

## Mehrkonten-, Mehrinstituts- und Jahreswechseltests

Automatisiert geprüft wurden:

- ein Institut mit einem Konto;
- gemeinsamer FSA bei mehreren Konten;
- zwei Institute mit 100,00 € beziehungsweise 300,00 € FSA;
- getrennte Berechnung für 2025 und 2026;
- vollständig, teilweise und nachgewiesen nicht verbrauchter FSA;
- unbekannter Verbrauch bleibt `n. v.`;
- dokumentierte Null bleibt 0,00 €;
- vollständiger realer CSV-Verbrauch;
- keine Verdopplung bei Institutssummen;
- unveränderte übrige Steuerkennzahlen.

Testergebnis:

- FSA-/Steuer-Zieltests: 28 bestanden;
- vollständige Pytest-Suite: 1.118 bestanden, 12 erwartete Skips,
  5 Subtests bestanden;
- zwei bestehende Qt-Deprecation-Warnungen in `tax_detail_view.py`.

## Sicherheit

Die produktive Datenbank wurde ausschließlich mit `mode=ro` und
`PRAGMA query_only=ON` untersucht. Implementierung und CSV-Abnahme liefen auf
temporären SQLite-Kopien. Cashflows, Buchungsarten, Verwendungszwecke,
Steuerereignisse, Bestände, Einstandskosten, Performance und Originalbelege
wurden nicht verändert.
