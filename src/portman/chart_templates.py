"""Vorgefertigte professionelle Diagramm-Templates für PortMan.

Dieses Modul stellt eine Sammlung professionell gestalteter Chart-Templates bereit,
die als Ausgangspunkt für benutzerdefinierte Diagramme genutzt werden können.
Zusätzlich verwaltet :class:`TemplateManager` eigene (benutzerspezifische)
Vorlagen in einer JSON-Datei neben der Datenbank.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .chart_config import ChartConfig

# Dateiname der eigenen Vorlagen (liegt neben der Datenbank)
CUSTOM_TEMPLATE_FILENAME = 'custom_templates.json'


@dataclass(frozen=True)
class ChartTemplate:
    name: str
    description: str
    category: str
    config: ChartConfig


def get_templates() -> list[ChartTemplate]:
    """Gibt die eingebauten professionellen Vorlagen zurück."""
    return [
        ChartTemplate(
            name="Vermögensverlauf (Linie)",
            description="Professioneller Zeitverlauf des Gesamtvermögens",
            category="Vermögen",
            config=ChartConfig(
                id="tmpl_wealth_trend",
                title="Vermögensverlauf",
                chart_type="line",
                data_source="wealth",
                styling={
                    "line_color": "#2563EB",
                    "fill_color": "#2563EB",
                    "line_width": 2.5,
                    "fill_alpha": 0.05,
                    "show_grid": True,
                    "grid_axis": "y",
                    "palette": "default",
                    "theme": "light",
                    "marker": "o",
                    "marker_size": 3,
                },
                axes={
                    "x": {"type": "date", "label": "Datum"},
                    "y": {"type": "currency", "label": "Vermögen"},
                },
            ),
        ),
        ChartTemplate(
            name="Vermögensstruktur (Gestapelt)",
            description="Entwicklung der Anlageklassen über die Zeit",
            category="Vermögen",
            config=ChartConfig(
                id="tmpl_wealth_stacked",
                title="Vermögensstruktur im Verlauf",
                chart_type="area",
                data_source="wealth",
                styling={
                    "fill_alpha": 0.7,
                    "show_grid": True,
                    "grid_axis": "y",
                    "palette": "tableau",
                    "theme": "light",
                },
                axes={
                    "x": {"type": "date", "label": "Datum"},
                    "y": {"type": "currency", "label": "Vermögen"},
                },
            ),
        ),
        ChartTemplate(
            name="Vermögensverlauf (Monatswerte)",
            description="Vermögen als Monats-Ende-Stände (Resampling, letzter Wert je Monat)",
            category="Vermögen",
            config=ChartConfig(
                id="tmpl_wealth_monthly",
                title="Vermögensverlauf · Monatswerte",
                chart_type="line",
                data_source="wealth",
                aggregation={"type": "monthly", "method": "last"},
                styling={
                    "line_color": "#0891B2",
                    "line_width": 2.2,
                    "fill_alpha": 0.08,
                    "show_grid": True,
                    "grid_axis": "y",
                    "marker": "o",
                    "marker_size": 3,
                },
                axes={
                    "x": {"type": "date", "label": "Datum"},
                    "y": {"type": "currency", "label": "Vermögen"},
                },
            ),
        ),
        ChartTemplate(
            name="Top Positionen (Horizontal)",
            description="Größte Depotpositionen sortiert nach Wert",
            category="Positionen",
            config=ChartConfig(
                id="tmpl_top_positions",
                title="Top 10 Positionen",
                chart_type="barh",
                data_source="positions",
                options={"top_n": 10, "sort_by": "value"},
                styling={
                    "palette": "corporate",
                    "show_grid": True,
                    "grid_axis": "x",
                },
                axes={
                    "x": {"type": "currency", "label": "Marktwert"},
                    "y": {"type": "category", "label": "Wertpapier"},
                },
            ),
        ),
        ChartTemplate(
            name="Gewinn/Verlust Scatter",
            description="Wert vs. Buchgewinn/Verlust pro Position",
            category="Performance",
            config=ChartConfig(
                id="tmpl_gain_scatter",
                title="Gewinn/Verlust vs. Marktwert",
                chart_type="scatter",
                data_source="positions",
                styling={
                    "palette": "default",
                    "show_grid": True,
                    "grid_axis": "both",
                },
                axes={
                    "x": {"type": "currency", "label": "Marktwert"},
                    "y": {"type": "currency", "label": "Buchgewinn/-verlust"},
                },
            ),
        ),
        ChartTemplate(
            name="Gewinnverteilung (Histogramm)",
            description="Verteilung der Buchgewinne aller Positionen",
            category="Performance",
            config=ChartConfig(
                id="tmpl_gain_histogram",
                title="Verteilung der Buchgewinne",
                chart_type="histogram",
                data_source="positions",
                options={"bins": "auto"},
                styling={
                    "palette": "default",
                    "show_grid": True,
                    "grid_axis": "y",
                },
                axes={
                    "x": {"type": "currency", "label": "Gewinn/Verlust"},
                    "y": {"type": "number", "label": "Anzahl"},
                },
            ),
        ),
        ChartTemplate(
            name="Regionen (Kreisdiagramm)",
            description="Aufteilung des Depots nach Regionen",
            category="Allokation",
            config=ChartConfig(
                id="tmpl_regions_pie",
                title="Depotaufteilung nach Regionen",
                chart_type="pie",
                data_source="positions",
                options={"top_n": 6, "sort_by": "value"},
                styling={
                    "palette": "tableau",
                    "show_legend": True,
                },
                axes={
                    "x": {"type": "category", "label": "Region"},
                    "y": {"type": "percent", "label": "Anteil"},
                },
            ),
        ),
        ChartTemplate(
            name="Regionen (Treemap)",
            description="Regionen als Flächenanteile am Depotwert",
            category="Allokation",
            config=ChartConfig(
                id="tmpl_regions_treemap",
                title="Regionen im Depot",
                chart_type="treemap",
                data_source="positions",
                options={"by_position": False},
                styling={"palette": "viridis"},
                axes={
                    "x": {"type": "category", "label": "Region"},
                    "y": {"type": "currency", "label": "Wert"},
                },
            ),
        ),
        ChartTemplate(
            name="Allokation (Radar)",
            description="Vermögenskategorien als Radar-Diagramm",
            category="Allokation",
            config=ChartConfig(
                id="tmpl_allocation_radar",
                title="Allokation im Überblick",
                chart_type="radar",
                data_source="wealth",
                styling={"palette": "default", "line_width": 2.5},
                axes={
                    "x": {"type": "category", "label": "Kategorie"},
                    "y": {"type": "percent", "label": "Anteil"},
                },
            ),
        ),
        ChartTemplate(
            name="Kontenvergleich",
            description="Saldo pro Konto/Depot",
            category="Konten",
            config=ChartConfig(
                id="tmpl_accounts",
                title="Konten & Depots im Vergleich",
                chart_type="barh",
                data_source="accounts",
                styling={
                    "palette": "corporate",
                    "show_grid": True,
                    "grid_axis": "x",
                },
                axes={
                    "x": {"type": "currency", "label": "Saldo/Depotwert"},
                    "y": {"type": "category", "label": "Konto/Depot"},
                },
            ),
        ),
        ChartTemplate(
            name="Depotwert & Drawdown",
            description="Depotwert mit Rückgang vom Höchstwert",
            category="Performance",
            config=ChartConfig(
                id="tmpl_valuation",
                title="Depotwert und Drawdown",
                chart_type="line",
                data_source="valuation",
                styling={
                    "line_color": "#16A34A",
                    "line_width": 2.5,
                    "fill_alpha": 0.08,
                    "show_grid": True,
                    "grid_axis": "y",
                },
                axes={
                    "x": {"type": "date", "label": "Datum"},
                    "y": {"type": "currency", "label": "Depotwert"},
                },
            ),
        ),
        ChartTemplate(
            name="Depotwert (Kalender-Heatmap)",
            description="Depotwert je Kalendermonat als Jahr × Monat Matrix",
            category="Performance",
            config=ChartConfig(
                id="tmpl_valuation_heatmap",
                title="Depotwert je Monat",
                chart_type="heatmap",
                data_source="valuation",
                styling={"palette": "viridis"},
                axes={
                    "x": {"type": "category", "label": "Monat"},
                    "y": {"type": "category", "label": "Jahr"},
                },
            ),
        ),
    ]


class TemplateManager:
    """Lädt, speichert und validiert benutzerspezifische Diagramm-Vorlagen."""

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else None
        self._templates: dict[str, ChartTemplate] = {}

    def load(self) -> dict[str, ChartTemplate]:
        """Lädt eigene Vorlagen aus der JSON-Datei."""
        if self.path is None or not self.path.exists():
            self._templates = {}
            return self._templates
        with open(self.path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        self._templates = {}
        for item in data.get('templates', []):
            template = ChartTemplate(
                name=item['name'],
                description=item.get('description', ''),
                category=item.get('category', 'Eigene'),
                config=ChartConfig.from_dict(item['config']),
            )
            self._templates[template.name] = template
        return self._templates

    def save(self) -> None:
        """Speichert eigene Vorlagen in die JSON-Datei."""
        if self.path is None:
            return
        data = {
            'version': 1,
            'templates': [
                {
                    'name': template.name,
                    'description': template.description,
                    'category': template.category,
                    'config': template.config.to_dict(),
                }
                for template in self._templates.values()
            ],
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def validate(self, template: ChartTemplate) -> list[str]:
        """Validierung; leere Fehlerliste bedeutet gültig."""
        errors: list[str] = []
        if not template.name or not template.name.strip():
            errors.append('Name darf nicht leer sein.')
        elif len(template.name) > 80:
            errors.append('Name darf höchstens 80 Zeichen lang sein.')
        return errors

    def add(self, template: ChartTemplate, overwrite: bool = False) -> str | None:
        """Fügt eine Vorlage hinzu. Gibt eine Fehlermeldung oder ``None`` zurück."""
        errors = self.validate(template)
        if errors:
            return errors[0]
        if template.name in self._templates and not overwrite:
            return f'Es existiert bereits eine Vorlage mit dem Namen „{template.name}".'
        self._templates[template.name] = template
        return None

    def remove(self, name: str) -> bool:
        """Entfernt eine eigene Vorlage. ``True`` wenn gefunden."""
        if name in self._templates:
            del self._templates[name]
            return True
        return False

    def get(self, name: str) -> ChartTemplate | None:
        return self._templates.get(name)

    def user(self) -> list[ChartTemplate]:
        """Nur die eigenen Vorlagen (in Einfügereihenfolge)."""
        return list(self._templates.values())

    def all(self) -> list[ChartTemplate]:
        """Eingebaute und eigene Vorlagen – eigene zuletzt."""
        return get_templates() + self.user()


def default_template_path(repo: Any = None) -> Path:
    """Ermittelt den Speicherort der eigenen Vorlagen.

    Bevorzugt wird eine Datei ``custom_templates.json`` neben der Datenbank.
    Ohne Repository wird auf ein Benutzerverzeichnis zurückgegriffen.
    """
    try:
        original = getattr(repo, 'repository', repo)
        store = getattr(original, 'store', None)
        database_path = getattr(store, 'path', None)
        if database_path:
            return Path(database_path).parent / CUSTOM_TEMPLATE_FILENAME
    except Exception:
        pass
    return Path.home() / '.portman' / CUSTOM_TEMPLATE_FILENAME


def default_template_manager(repo: Any = None) -> TemplateManager:
    """Erstellt einen Manager am Standardpfad und lädt vorhandene Vorlagen."""
    manager = TemplateManager(default_template_path(repo))
    manager.load()
    return manager