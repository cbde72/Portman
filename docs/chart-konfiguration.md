# Flexible Diagramm-Konfiguration, Aggregation und Vorlagen

Stand: 12.10.2026

Dieses Dokument beschreibt die erweiterbaren Diagramm-Möglichkeiten von PortmanNL:
JSON-basierte Konfigurationen, zeitliche Aggregation, Vorlagen (eingebaut und
eigene) sowie den Export in mehrere Grafkformate.

## 1. Konfigurationsmodell (`chart_config.py`)

Jedes benutzerdefinierte Diagramm ist eine JSON-freundliche `ChartConfig`:

- `id`, `title`, `chart_type`, `data_source`
- `styling` – Farben, Linienbreite, Transparenz, Raster, Palette, Theme
- `axes` – x/y-Typ (`date`, `category`, `number`) und Beschriftung
- `time_range` – optionaler Zeitraum (`start`/`end` als ISO-Datum)
- `aggregation` – zeitliche Verdichtung (`type`, `method`)
- `options` – typspezifische Optionen (`top_n`, `sort_by`,
  `candle_aggregate`, `by_position`, `bins`, …)

Gespeichert werden eigene Diagramme in `custom_charts.json` neben der
Datenbank (`ChartConfigManager`, Schlüssel `ChartConfigManager.validate`
prüft auch Aggregationstyp und -methode). In der Oberfläche werden sie über
„Diagramm-Einstellungen → Eigene Diagramme verwalten …“ bearbeitet; der
Editor bietet eine Live-Vorschau.

## 2. Zeitliche Aggregation (`dynamic_renderer.py`)

Zeitreihen (`wealth`, `valuation`) können vor dem Zeichnen verdichtet werden:

| `type`    | Gruppe                     | typische Verwendung          |
|-----------|----------------------------|------------------------------|
| `none`    | keine                      | Rohdaten                     |
| `daily`   | ein Punkt je Kalendertag   | Ausreißer-Deduplizierung     |
| `weekly`  | ISO-Kalenderwoche          | Wochen-Charts                |
| `monthly` | Kalendermonat              | Monats-Ende-Stände           |

| `method`  | Bedeutung                                  |
|-----------|--------------------------------------------|
| `last`    | letzter Stand der Periode (Resampling)     |
| `sum`     | Summe über die Periode                     |
| `mean`    | Durchschnitt über die Periode              |

Kategorien (`categories`) und das `observed`-Flag werden konsistent
mitverdichtet, damit Flächen-, Kreis- und Baumdiagramme korrekt bleiben.
`Decimal`-Werte bleiben typerhaltend (Summe/Mittelwert ohne Float-Rundung).
Der Zeitraumfilter (`time_range`) greift vor der Aggregation.

Typische Konfiguration:

```json
{
  "id": "modell_vermoegen",
  "title": "Vermögensverlauf (Monatswerte)",
  "chart_type": "line",
  "data_source": "wealth",
  "aggregation": { "type": "monthly", "method": "last" },
  "axes": {
    "x": { "type": "date", "label": "Datum" },
    "y": { "type": "currency", "label": "Vermögen" }
  }
}
```

## 3. Vorlagen (`chart_templates.py`)

`ChartTemplate` bündelt Name, Beschreibung, Kategorie und eine
`ChartConfig`. `get_templates()` liefert 12 eingebaute Vorlagen, darunter:

- Vermögensverlauf (Linie / gestapelt / Monatswerte)
- Top Positionen, Gewinn/Verlust Scatter, Gewinnverteilung (Histogramm)
- Regionen (Kreisdiagramm / Treemap), Allokation (Radar)
- Kontenvergleich, Depotwert & Drawdown, Depotwert (Kalender-Heatmap)

`TemplateManager` verwaltet **eigene** Vorlagen in `custom_templates.json`
neben der Datenbank: `add` (mit Validierung und Duplikatschutz), `remove`,
`save`/`load`, `user()` und `all()` (eingebaute + eigene). Eine Vorlage lässt
sich im Dialog in ein eigenes Diagramm übernehmen („Aus Vorlage …“) und jedes
eigene Diagramm als Vorlage speichern („Als Vorlage speichern …“). Eigene
Vorlagen können in der Galerie gelöscht werden.

## 4. Export (`chart_style.save_figure`)

`save_figure(figure, path, dpi=None)` speichert eine Figur anhand der
Dateiendung; erlaubte Formate stehen in `CHART_STYLE['export_formats']`
(Standard: `png`, `svg`, `pdf`, `jpg`). Rasterformate verwenden den
Export-DPI (`CHART_STYLE['export_dpi']`, im Einstellungsdialog änderbar),
Vektorformate verlustfrei. Unbekannte Endungen werfen einen
`ValueError`. Die Export-Funktion der Diagramm-Ansicht bietet einen
Formatfilter und ruft `save_figure` auf.

```python
from portman.chart_style import save_figure
save_figure(figure, 'bericht.pdf')            # PDF, Vektor
save_figure(figure, 'grafik.png', dpi=300)    # PNG mit höherer Auflösung
```

## 5. Tests

Die Funktionalität ist in den Tests abgedeckt:

- `tests/test_dynamic_renderer.py` – Aggregation (daily/weekly/monthly,
  Summe/Mittelwert/letzter Wert, Kategorien, Decimal, Zeitraum + Render)
- `tests/test_chart_templates.py` – Templates rendern, Manager-Roundtrip
- `tests/test_chart_cache.py` – typerhaltender Klon und Cache-Semantik
- `tests/test_chart_style.py` – `save_figure` je Format, DPI, Fehlerfall
- `tests/test_modified_dietz.py` – Performance-Berechnung mit vielen
  Punkten/Transaktionen, Gebühren-/Dividenden-Summen