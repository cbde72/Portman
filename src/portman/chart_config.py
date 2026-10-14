"""JSON-basierte Diagramm-Konfiguration mit Validierung und Persistenz.

Dieses Modul ermöglicht die freie Definition von Diagrammen über JSON-Konfigurationen.
Jede Konfiguration beschreibt Typ, Datenquelle, Styling, Achsen, Zeitraum und Aggregation.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# Dateiname der benutzerdefinierten Diagramme (liegt neben der Datenbank)
CONFIG_FILENAME = 'custom_charts.json'

# Sentinel für die Depot-Auswahl einer Diagramm-Konfiguration: erzwingt
# "Alle Konten", auch wenn der globale Filter oben auf ein einzelnes Depot zeigt.
ALL_ACCOUNTS = '*'


# Unterstützte Diagrammtypen und Datenquellen
CHART_TYPES = (
    'line',
    'bar',
    'barh',
    'pie',
    'area',
    'scatter',
    'comparison',
    'candlestick',
    'heatmap',
    'boxplot',
    'violin',
    'histogram',
    'treemap',
    'radar',
)
DATA_SOURCES = ('wealth', 'accounts', 'positions', 'valuation', 'comparison')
AXIS_TYPES = ('date', 'category', 'number')
Y_AXIS_FORMATS = ('currency', 'percent', 'number')
AGGREGATION_TYPES = ('none', 'daily', 'weekly', 'monthly')
AGGREGATION_METHODS = ('last', 'sum', 'mean')

DEFAULT_STYLING: dict[str, Any] = {
    'line_color': '#2563EB',
    'fill_color': '#2563EB',
    'line_width': 2.0,
    'fill_alpha': 0.1,
    'show_grid': True,
    'grid_axis': 'y',
    'title_fontsize': 11,
    'subtitle_fontsize': 9,
    'legend_fontsize': 8,
    'palette': 'default',
    'theme': 'light',
    'show_legend': True,
    'marker': 'o',
    'marker_size': 4,
    'alpha': 0.8,
}

DEFAULT_AXES: dict[str, Any] = {
    'x': {'type': 'date', 'label': ''},
    'y': {'type': 'currency', 'label': ''},
}

DEFAULT_TIME_RANGE: dict[str, Any] = {
    'start': None,
    'end': None,
}

DEFAULT_AGGREGATION: dict[str, Any] = {
    'type': 'none',
    'method': 'last',
}


@dataclass(frozen=True)
class ChartConfig:
    """Eine einzelne Diagramm-Konfiguration.

    Attributes:
        id: Eindeutige Kennung (nur Buchstaben, Zahlen, Bindestriche, Unterstriche).
        title: Angezeigter Diagrammtitel.
        chart_type: Diagrammtyp (line, bar, barh, pie, area, scatter, comparison).
        data_source: Datenquelle (wealth, accounts, positions, valuation, comparison).
        styling: Styling-Optionen (Farben, Linienbreite, Transparenz, Raster).
        axes: Achsen-Konfiguration (Typ und Beschriftung für x und y).
        time_range: Optionaler Zeitraum-Filter (start/end als ISO-Datum).
        aggregation: Aggregationseinstellungen (Typ und Methode).
        options: Typ-spezifische Optionen (z.B. top_n für Balkendiagramme).
        comparison: Ob dies ein Kursvergleichs-Diagramm ist.
        cache_group: Cache-Gruppe für die Diagramm-Daten.
    """
    id: str
    title: str
    chart_type: str
    data_source: str
    styling: dict = field(default_factory=lambda: dict(DEFAULT_STYLING))
    axes: dict = field(default_factory=lambda: dict(DEFAULT_AXES))
    time_range: dict = field(default_factory=lambda: dict(DEFAULT_TIME_RANGE))
    aggregation: dict = field(default_factory=lambda: dict(DEFAULT_AGGREGATION))
    options: dict = field(default_factory=dict)
    comparison: bool = False
    cache_group: int | None = None

    def __post_init__(self):
        if self.cache_group is None:
            object.__setattr__(self, 'cache_group', hash(self.id) % 10000)

    def to_dict(self) -> dict:
        """Konvertiert die Konfiguration für JSON-Serialisierung."""
        return {
            'id': self.id,
            'title': self.title,
            'chart_type': self.chart_type,
            'data_source': self.data_source,
            'styling': self.styling,
            'axes': self.axes,
            'time_range': self.time_range,
            'aggregation': self.aggregation,
            'options': self.options,
            'comparison': self.comparison,
        }

    @classmethod
    def from_dict(cls, data: dict) -> ChartConfig:
        """Erstellt eine Konfiguration aus einem Dictionary."""
        return cls(
            id=data['id'],
            title=data['title'],
            chart_type=data['chart_type'],
            data_source=data['data_source'],
            styling=data.get('styling', dict(DEFAULT_STYLING)),
            axes=data.get('axes', dict(DEFAULT_AXES)),
            time_range=data.get('time_range', dict(DEFAULT_TIME_RANGE)),
            aggregation=data.get('aggregation', dict(DEFAULT_AGGREGATION)),
            options=data.get('options', {}),
            comparison=data.get('comparison', False),
        )


class ChartConfigManager:
    """Lädt, speichert und validiert Diagramm-Konfigurationen.

    Verwaltet eine Sammlung von ChartConfig-Objekten und persistiert sie
    als JSON-Datei. Bietet Validierung und CRUD-Operationen.
    """

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else None
        self._configs: dict[str, ChartConfig] = {}

    def load(self) -> dict[str, ChartConfig]:
        """Lädt Konfigurationen aus der JSON-Datei."""
        if self.path is None or not self.path.exists():
            self._configs = {}
            return self._configs
        with open(self.path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        self._configs = {}
        for item in data.get('charts', []):
            config = ChartConfig.from_dict(item)
            self._configs[config.id] = config
        return self._configs

    def save(self, configs: dict[str, ChartConfig] | None = None) -> None:
        """Speichert Konfigurationen in die JSON-Datei."""
        if self.path is None:
            return
        if configs is not None:
            self._configs = configs
        data = {
            'version': 1,
            'charts': [c.to_dict() for c in self._configs.values()],
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def validate(self, config: ChartConfig) -> list[str]:
        """Validiert eine Konfiguration und gibt eine Liste von Fehlern zurück."""
        errors: list[str] = []
        if not config.id:
            errors.append('ID darf nicht leer sein.')
        if not re.match(r'^[a-zA-Z0-9_-]+$', config.id):
            errors.append('ID darf nur Buchstaben, Zahlen, Bindestriche und Unterstriche enthalten.')
        if not config.title:
            errors.append('Titel darf nicht leer sein.')
        if config.chart_type not in CHART_TYPES:
            errors.append(f'Unbekannter Diagrammtyp: {config.chart_type}')
        if config.data_source not in DATA_SOURCES:
            errors.append(f'Unbekannte Datenquelle: {config.data_source}')
        # Farben validieren
        for key in ('line_color', 'fill_color'):
            color = config.styling.get(key, '')
            if color and not re.match(r'^#[0-9A-Fa-f]{6}$', color):
                errors.append(f'Ungültige Farbe für {key}: {color}')
        aggregation = config.aggregation or {}
        if aggregation.get('type') not in AGGREGATION_TYPES:
            errors.append(f'Unbekannter Aggregationstyp: {aggregation.get("type")}')
        if aggregation.get('method') not in AGGREGATION_METHODS:
            errors.append(f'Unbekannte Aggregationsmethode: {aggregation.get("method")}')
        return errors

    def get(self, chart_id: str) -> ChartConfig | None:
        """Gibt eine Konfiguration nach ID zurück."""
        return self._configs.get(chart_id)

    def add(self, config: ChartConfig) -> list[str]:
        """Fügt eine Konfiguration nach Validierung hinzu. Gibt Fehlerliste zurück."""
        errors = self.validate(config)
        if errors:
            return errors
        self._configs[config.id] = config
        return []

    def remove(self, chart_id: str) -> bool:
        """Entfernt eine Konfiguration. Gibt True zurück, wenn gefunden."""
        if chart_id in self._configs:
            del self._configs[chart_id]
            return True
        return False

    def all(self) -> list[ChartConfig]:
        """Gibt alle Konfigurationen zurück."""
        return list(self._configs.values())


def default_config_path(repo: Any = None) -> Path:
    """Ermittelt den Speicherort der benutzerdefinierten Diagramme.

    Bevorzugt wird eine Datei ``custom_charts.json`` neben der Datenbank.
    Ist kein Repository bzw. kein Pfad verfügbar, wird auf ein Benutzerverzeichnis
    zurückgegriffen, damit die Konfigurationen nicht verloren gehen.
    """
    try:
        original = getattr(repo, 'repository', repo)
        store = getattr(original, 'store', None)
        database_path = getattr(store, 'path', None)
        if database_path:
            return Path(database_path).parent / CONFIG_FILENAME
    except Exception:
        pass
    return Path.home() / '.portman' / CONFIG_FILENAME


def default_manager(repo: Any = None) -> 'ChartConfigManager':
    """Erstellt einen Manager am Standardpfad und lädt vorhandene Konfigurationen."""
    manager = ChartConfigManager(default_config_path(repo))
    manager.load()
    return manager


def default_configs() -> list[ChartConfig]:
    """Standard-Konfigurationen, die den bestehenden hartkodierten Diagrammen entsprechen."""
    return [
        ChartConfig(
            id='default_wealth_line',
            title='Vermögensverlauf',
            chart_type='line',
            data_source='wealth',
            styling={'line_color': '#2563EB', 'fill_alpha': 0.1, 'show_grid': True},
            axes={'x': {'type': 'date', 'label': 'Datum'}, 'y': {'type': 'currency', 'label': 'Vermögen'}},
        ),
        ChartConfig(
            id='default_accounts_barh',
            title='Kontenvergleich',
            chart_type='barh',
            data_source='accounts',
            styling={'show_grid': True},
            axes={'x': {'type': 'currency', 'label': 'Saldo'}, 'y': {'type': 'category', 'label': 'Konto'}},
        ),
        ChartConfig(
            id='default_positions_barh',
            title='Größte Positionen',
            chart_type='barh',
            data_source='positions',
            options={'top_n': 10, 'sort_by': 'value'},
            axes={'x': {'type': 'currency', 'label': 'Wert'}, 'y': {'type': 'category', 'label': 'Position'}},
        ),
        ChartConfig(
            id='default_wealth_area',
            title='Vermögensstruktur',
            chart_type='area',
            data_source='wealth',
            styling={'fill_alpha': 0.75, 'show_grid': True},
            axes={'x': {'type': 'date', 'label': 'Datum'}, 'y': {'type': 'currency', 'label': 'Vermögen'}},
        ),
    ]
