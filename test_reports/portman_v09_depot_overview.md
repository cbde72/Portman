# Portman V09 – Depotübersicht

Datum: 28.10.2026
Branch: `main`
Ausgangscommit: `1016e13125a983628ee825c47aa798b41302f539`

## 1. Architektur und Dateien

Die Erweiterung ist eine reine Leseschicht. Parser, SQLite-Schema, Importlogik und bestehende Portfolio-/Steuerberechnungen wurden nicht verändert.

- `src/portman/depot_overview.py`: gebündelte wirtschaftliche Aggregation.
- `src/portman/gui/depot_overview.py`: Reiter, Filter, Tabelle, Detailansicht und Export.
- `src/portman/gui/main_window_v09.py`: Installation des neuen Depot-Reiters.
- `src/portman/gui/portfolio_views.py`: isolierte Aktivierung des Reiters ohne Neuberechnung der bestehenden Positionsansichten.
- `tests/test_depot_overview.py`: synthetische SQLite-Regressionen.

Die Aggregation liest Transaktionen, Endbestände, Steuerereignisse und FIFO-Ergebnisse jeweils gesammelt. Es gibt keine Abfrage pro Wertpapierposition.

## 2. GUI

Der Reiter **Depotübersicht** befindet sich innerhalb der bestehenden Ansicht **Depots**. Er enthält:

- Depotauswahl einschließlich „Alle Depots“;
- Von-/Bis-Datum;
- aktuelles Jahr, letztes Jahr, drei Jahre, Gesamt und benutzerdefiniert;
- alle, aktive oder geschlossene Positionen;
- Aktualisieren, Spaltenauswahl und Export;
- 20 fachliche Kennzahlen und eine Summenzeile.

Erweiterte Gebühren- und Steuerkomponenten sind standardmäßig ausgeblendet und über „Spalten …“ erreichbar. Depot, Zeitraum und Positionsfilter aktualisieren die Ansicht automatisch. Die Berechnung wird verzögert angestoßen, damit mehrere unmittelbar aufeinanderfolgende GUI-Signale nur eine Aktualisierung auslösen.

Doppelklick öffnet die Einzelvorgänge. Dort können Käufe, Verkäufe, Dividenden, Gebühren und Steuern gefiltert werden. Ein Doppelklick auf einen Vorgang öffnet dessen lokale Originalquelle, sofern sie vorhanden ist.

## 3. Kennzahlen

### Bestände

Die Endstückzahl stammt aus `repo.holdings(end, depot)`. Eine Position mit Vorgängen im Zeitraum bleibt auch bei Endbestand null sichtbar und kann als geschlossen gefiltert werden.

### Käufe und Verkäufe

Anzahl und dokumentierter Ausführungswert werden getrennt aggregiert. `gross_amount` hat Vorrang. Fehlt er, wird der Ausführungswert aus dem gebuchten Settlementbetrag und den separat ausgewiesenen Gebühren/Steuern rekonstruiert.

### Dividenden

Netto entspricht dem belegten Buchungsbetrag. Brutto verwendet `gross_income` beziehungsweise `gross_amount`; nur bei fehlender Bruttoangabe erfolgt ein konservativer Rückschluss aus Netto und belegten Abzügen. Bereits konsolidierte Repository-Transaktionen verhindern Doppelzählung von Ausschüttungsbeleg, Steuermitteilung und Kontobuchung. Wiederangelegte Ausschüttungen können einen Bruttoertrag bei Cashflow null ausweisen.

### Gebühren

Gebühren werden nach Kauf, Verkauf und sonstigen Vorgängen getrennt. Vorgänge ohne belastbare Wertpapierkennung erscheinen unter **Nicht zugeordnet** und werden keinem Titel zugeschlagen.

### Steuern

Ausgewiesen werden Kapitalertragsteuer, Solidaritätszuschlag, Kirchensteuer und Quellensteuer. Die Kapitalertragsteuer ist der verbleibende belegte Steuerbetrag nach Abzug der dokumentierten Komponenten.

Steuerereignisse ergänzen den Nachweis nur, wenn sie nicht bereits mit einer Geldbuchung verknüpft sind. Freistellungsbeträge und Vorabpauschalen-Bemessungsgrundlagen sind keine Geldabflüsse. Eine in der Steuermitteilung tatsächlich belegte Steuer wird analytisch ausgewiesen, erzeugt aber ohne Geldbuchung keinen Cashflow.

### FIFO

Realisierte Gewinne und Verluste werden unverändert aus `analysis_v09.realized_profit()` übernommen. Damit gelten weiterhin die bestehenden strengen Regeln für Buchungsabdeckung, Anfangsbestand, Tagesreihenfolge, Kapitalmaßnahmen und Vorabpauschalenanrechnung.

## 4. Vorzeichenkonvention

- Käufe: negativer gebuchter Cashflow;
- Verkäufe: positiver gebuchter Cashflow;
- Dividenden: positiver gebuchter Cashflow;
- Gebühren und Steuern: analytisch positive Kosten-/Steuerwerte;
- eigenständige Gebühren-/Steuerbuchungen: negativer Cashflow;
- reine Steuer- und Freistellungsnachweise: kein künstlicher Cashflow.

`Transaction.amount` ist der signierte Settlementbetrag und enthält die laut Beleg bereits verrechneten Gebühren und Steuern. Deshalb werden Gebühren und Steuern für den Netto-Cashflow niemals ein zweites Mal abgezogen.

## 5. Datenquellen und Zuordnung

- Endbestand: `holdings(end, depot)`;
- Vorgänge: konsolidierte `RepositoryV09.transactions()`;
- Steuerbelege: `RepositoryV09.tax_events()`;
- realisierte Gewinne: bestehende FIFO-Auswertung;
- Wertpapieridentität: `security_master` über Schlüssel, ISIN oder WKN;
- Depotzuordnung: `performance_depot_key`, Depotquelle und Kontenzuordnung.

Fehlende Wertpapierzuordnungen bleiben sichtbar als **Nicht zugeordnet**.

## 6. Export und Kopieren

Die Qt-weite Kopierunterstützung ermöglicht Strg+A/Strg+C sowie Zellbereichskopien. „Exportieren“ erzeugt CSV oder XLSX. Optional werden sämtliche 20 Spalten exportiert, auch wenn erweiterte Spalten in der Ansicht ausgeblendet sind.

## 7. Tests

Gezielte Tests verwenden ausschließlich temporäre synthetische SQLite-Datenbanken und prüfen:

- einzelne und mehrere Depots;
- Zeitraumfilter;
- Käufe, Verkäufe und geschlossene Positionen;
- Brutto-/Nettodividenden und Wiederanlage;
- Kauf-, Verkaufs- und nicht zugeordnete Gebühren;
- Steuerkomponenten, Quellensteuer und Freistellung;
- Vorabpauschale ohne künstlichen Cashflow;
- FIFO-Gewinne;
- Reimport ohne Doppelzählung;
- Tabellenkopieren, Spalten und CSV/XLSX-Export;
- automatische GUI-Aktualisierung.

```text
python -m pytest -q tests/test_depot_overview.py --basetemp tmp/pytest_depot_overview_targeted2
6 passed

GUI-/Fachregression:
28 passed, 2 bestehende Qt-Deprecation-Warnungen

python -m compileall -q src
erfolgreich

python -m ruff check src --select F
All checks passed
```

Vollständige Regression:

```text
python -m pytest -q --basetemp tmp/pytest_depot_overview
1264 passed, 16 skipped, 2 warnings, 5 subtests passed in 523.50s (0:08:43)
```

Nach der abschließenden Performanceoptimierung der Wertpapier-Aliasauflösung
(ein vorgeladener `security_master`-Index statt Einzelabfragen) wurde die
vollständige Suite erneut ausgeführt:

```text
python -m pytest -q --basetemp tmp/pytest_depot_overview_final_full
1264 passed, 16 skipped, 2 warnings, 5 subtests passed in 423.61s (0:07:03)
```

Die zwei Warnungen sind die bereits bekannte Qt-Deprecation-Warnung für
`QSortFilterProxyModel.invalidateFilter()` in `tax_detail_view.py` und stehen
nicht mit der Depotübersicht in Zusammenhang.

## 8. Offene fachliche Fragen

- Beträge verschiedener Währungen werden derzeit entsprechend der bestehenden Repository-Semantik angezeigt. Für eine gemeinsame Depot-Summe über echte Fremdwährungsbuchungen wäre eine explizite historische EUR-Umrechnung je Vorgang erforderlich; eine ungeprüfte Umrechnung wurde bewusst nicht eingeführt.
- Bei historischen Steuerbelegen ohne verknüpfte Kontobuchung kann die tatsächliche Zahlungswirkung nicht abgeleitet werden. Solche Beträge werden als Steuerbeleg ausgewiesen, nicht als Cashflow.
- Ein unbekannter FIFO-Einstand bleibt in der Detailauswertung unbekannt; es wird kein Einstand geschätzt.

## 9. Sicherheit

Vor Änderungen wurden die betroffenen vorhandenen Dateien nach
`C:\Users\chris\Desktop\Portman_DepotOverview_Backup_20261028`
kopiert und per SHA-256 erfasst. Produktive SQLite-Dateien, Original-PDFs und private Auditdaten wurden nicht verändert.
