"""Dynamische Rendering-Engine für beliebige Diagramm-Konfigurationen.

Verwendet ein Registry-Pattern, um Renderer für verschiedene Diagrammtypen zu registrieren.
Jeder Renderer eine Funktion, die (figure, data, config, context) annimmt und einen Notiz-String zurückgibt.

Die Renderer nutzen das gemeinsame Erscheinungsbild aus :mod:`chart_style`
(Palette, Achsen- und Grid-Styling) und arbeiten ausschließlich mit den bereits
aufbereiteten Datenstrukturen aus :mod:`chart_data`. Fehlen für einen Diagrammtyp
spezifische Felder (z. B. OHLC-Daten), greifen sie auf sinnvolle Fallbacks zurück.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal
from importlib.util import find_spec

import matplotlib.dates as mdates
import numpy as np
from matplotlib import colormaps
from matplotlib.patches import Rectangle
from matplotlib.ticker import FuncFormatter, MaxNLocator
from typing import Any

# SciPy und Squarify sind optionale Abhängigkeiten.  Hier wird nur ihre
# Verfügbarkeit geprüft; importiert werden sie erst bei Bedarf, damit der
# Programmstart nicht durch schwere Importe verzögert wird.
SCIPY_AVAILABLE = find_spec("scipy") is not None
SQUARIFY_AVAILABLE = find_spec("squarify") is not None

from .chart_config import ChartConfig, DEFAULT_STYLING, ALL_ACCOUNTS
from .chart_style import (
    COLORS,
    PALETTE,
    compact_number,
    currency_axis,
    date_axis,
    percent_axis,
    percent_x_axis,
    number_axis,
    style_axis,
    apply_professional_style,
    CHART_STYLE,
    get_palette,
)


# Registry der Renderer
_RENDERERS: dict[str, Any] = {}


def register_renderer(chart_type: str):
    """Decorator, um einen Renderer für einen Diagrammtyp zu registrieren."""
    def decorator(func):
        _RENDERERS[chart_type] = func
        return func
    return decorator


def render_chart(figure, data, config: ChartConfig, context: dict) -> str:
    """Rendert ein Diagramm basierend auf der Konfiguration.

    Args:
        figure: Matplotlib-Figure.
        data: Aufbereitete Diagrammdaten.
        config: Diagramm-Konfiguration.
        context: Zusätzliche Kontext-Informationen (as_of, account, etc.).

    Returns:
        Notiz-String für die Anzeige unter dem Diagramm.
    """
    renderer = _RENDERERS.get(config.chart_type)
    if renderer is None:
        return f'Unbekannter Diagrammtyp: {config.chart_type}'
    try:
        return renderer(figure, data, config, context)
    except Exception as error:  # defensive Fallback, damit das Fenster bedienbar bleibt
        _empty_chart(figure.add_subplot(111), f'Diagramm konnte nicht gezeichnet werden: {error}')
        return f'Diagramm "{config.title}" konnte nicht gezeichnet werden: {error}'


def _get_styling(config: ChartConfig) -> dict:
    """Merged Konfigurations-Styling mit Defaults."""
    styling = dict(DEFAULT_STYLING)
    styling.update(config.styling)
    return styling


def _opt(config: ChartConfig, styling: dict, key: str, default=None):
    """Liest eine Option bevorzugt aus ``config.options``, dann aus dem Styling."""
    if key in config.options:
        return config.options[key]
    if key in styling:
        return styling[key]
    return default


def _palette(config: ChartConfig, styling: dict) -> list[str]:
    """Ermittelt die zu verwendende Farbpalette."""
    name = config.options.get('palette') or styling.get('palette') or CHART_STYLE.get('palette', 'default')
    palette = get_palette(name)
    return palette or list(PALETTE)


def _filter_time_range(data: list, time_range: dict) -> list:
    """Filtert Daten nach Zeitraum."""
    start = time_range.get('start')
    end = time_range.get('end')
    if not start and not end:
        return data
    result = []
    for item in data:
        d = item.get('date') or item.get('period', '')
        if start and d < start:
            continue
        if end and d > end:
            continue
        result.append(item)
    return result


def _bucket_key(day: date, kind: str) -> str:
    """Gruppierungsschlüssel einer Periode für die zeitliche Aggregation."""
    if kind == 'weekly':
        year, week, _ = day.isocalendar()
        return f'{year}-W{week:02d}'
    if kind == 'monthly':
        return f'{day.year}-{day.month:02d}'
    return day.isoformat()


def _combine(values: list, method: str):
    """Summe oder Mittelwert – typerhaltend für ``Decimal``-Reihen."""
    return sum(values) if method == 'sum' else sum(values) / len(values)


def _aggregate(rows: list, config: ChartConfig, value_keys: tuple[str, ...]) -> list:
    """Verdichtet Zeitreihen täglich/wöchentlich/monatlich.

    ``last`` wählt je Periode den letzten Stand (Resampling, ideal für
    Bestandsgrößen wie Vermögen und Depotwert), ``sum``/``mean`` fassen die
    Werte innerhalb der Periode zusammen. Kategorien werden konsistent
    mitverdichtet, damit Flächen-, Kreis- und Baumdiagramme korrekt bleiben.
    """
    aggregation = config.aggregation or {}
    kind = aggregation.get('type', 'none')
    method = aggregation.get('method', 'last')
    if kind not in ('daily', 'weekly', 'monthly') or method not in ('last', 'sum', 'mean') or not rows:
        return rows
    buckets: dict[str, list] = {}
    order: list[str] = []
    for row in rows:
        raw = row.get('date')
        if not raw:
            continue
        try:
            day = date.fromisoformat(str(raw)[:10])
        except ValueError:
            return rows
        key = _bucket_key(day, kind)
        if key not in buckets:
            buckets[key] = []
            order.append(key)
        buckets[key].append(row)
    result = []
    for key in order:
        group = buckets[key]
        merged = dict(group[-1])
        if method != 'last' and len(group) > 1:
            for field in value_keys:
                values = [row[field] for row in group if row.get(field) is not None]
                if values:
                    merged[field] = _combine(values, method)
            if any(row.get('categories') for row in group):
                names = {name for row in group for name in (row.get('categories') or {})}
                categories = {}
                for name in names:
                    values = [row['categories'][name] for row in group
                              if (row.get('categories') or {}).get(name) is not None]
                    if values:
                        categories[name] = _combine(values, method)
                merged['categories'] = categories
        if any('observed' in row for row in group):
            merged['observed'] = any(row.get('observed', True) for row in group)
        result.append(merged)
    return result


def _series(data: dict, config: ChartConfig) -> list:
    """Gefilterte und aggregierte Vermögens-/Zeitreihe (Feld ``total``)."""
    return _aggregate(_filter_time_range(data.get('series', []), config.time_range),
                      config, ('total',))


def _rows(data: dict, config: ChartConfig) -> list:
    """Gefilterte und aggregierte Depotwert-Reihe (Feld ``value``)."""
    return _aggregate(_filter_time_range(data.get('rows', []), config.time_range),
                      config, ('value',))


def _apply_axis_labels(ax, config: ChartConfig):
    """Setzt die konfigurierten Achsenbeschriftungen, sofern vorhanden."""
    x_label = (config.axes.get('x', {}) or {}).get('label') or ''
    y_label = (config.axes.get('y', {}) or {}).get('label') or ''
    if x_label:
        ax.set_xlabel(x_label, color=COLORS['text'])
    if y_label:
        ax.set_ylabel(y_label, color=COLORS['text'])


def _empty_chart(axis, message: str = 'Für diese Auswahl sind noch keine Daten vorhanden.'):
    """Zeigt eine leere Diagrammfläche mit Nachricht an."""
    axis.text(0.5, 0.5, message, ha='center', va='center', color=COLORS['muted'],
              transform=axis.transAxes, wrap=True)
    axis.set_axis_off()


def _finish(ax, figure, config: ChartConfig, styling: dict, subtitle: str | None = None):
    """Vereinheitlicht Titel, Achsen-Styling und Raster über :mod:`chart_style`."""
    apply_professional_style(figure, ax, title=config.title, subtitle=subtitle)
    if not styling.get('show_grid', True):
        ax.grid(False)


def _y_format(config: ChartConfig) -> str:
    """Ermittelt das Zahlenformat der y-Achse aus der Achsenkonfiguration."""
    return (config.axes.get('y', {}) or {}).get('type', 'currency')


def _x_format(config: ChartConfig) -> str:
    """Ermittelt das Zahlenformat der x-Achse aus der Achsenkonfiguration."""
    return (config.axes.get('x', {}) or {}).get('type', 'currency')


def _format_value(value: float, fmt: str = 'currency', decimals: int = 0) -> str:
    """Formatiert einen Zahlwert passend für Datenbeschriftungen."""
    if fmt == 'currency':
        return compact_number(value)
    if fmt == 'percent':
        return f'{value:.{decimals}f} %'.replace('.', ',')
    return f'{value:,.{decimals}f}'.replace(',', 'X').replace('.', ',').replace('X', '.')


def _apply_y_axis(ax, config: ChartConfig):
    """Setzt das Zahlenformat der y-Achse anhand der Konfiguration."""
    fmt = _y_format(config)
    if fmt == 'percent':
        percent_axis(ax)
    elif fmt == 'number':
        number_axis(ax)
    else:
        currency_axis(ax)


def _apply_x_axis(ax, config: ChartConfig):
    """Setzt das Zahlenformat der x-Achse (relevant für horizontale Balken)."""
    fmt = _x_format(config)
    if fmt == 'percent':
        percent_x_axis(ax)
    elif fmt == 'number':
        ax.xaxis.set_major_formatter(
            FuncFormatter(lambda value, _pos: f'{value:,.0f}'.replace(',', 'X').replace('.', ',').replace('X', '.'))
        )
    else:
        ax.xaxis.set_major_formatter(FuncFormatter(lambda value, _pos: compact_number(value)))


def _add_data_labels(ax, x, y, config: ChartConfig, styling: dict, fmt: str | None = None,
                     decimals: int = 0, max_points: int = 20, rotation: float = 0):
    """Fügt optionale Datenbeschriftungen hinzu (bei zu vielen Punkten ausgedünnt)."""
    if not _opt(config, styling, 'show_data_labels', False):
        return
    fmt = fmt or _y_format(config)
    count = len(x)
    if count == 0:
        return
    stride = max(1, count // max_points)
    for index in range(count):
        if index % stride and index != count - 1:
            continue
        label = _format_value(float(y[index]), fmt, decimals)
        ax.annotate(label, (x[index], y[index]), textcoords='offset points', xytext=(0, 5),
                    ha='center', va='bottom', fontsize=CHART_STYLE['annotation_fontsize'],
                    color=COLORS['text_light'], rotation=rotation)


def _smooth_series(x, y, samples: int | None = None):
    """Glättet eine Zahlenreihe optional via monotoner kubischer Interpolation (PCHIP).

    Fällt ohne SciPy oder bei zu wenigen Punkten auf die Originaldaten zurück.
    """
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    if not SCIPY_AVAILABLE or len(x) < 3:
        return x, y
    if np.any(np.diff(x) <= 0):
        return x, y
    from scipy.interpolate import PchipInterpolator
    samples = samples or max(len(x) * 12, 60)
    xi = np.linspace(x[0], x[-1], samples)
    yi = PchipInterpolator(x, y)(xi)
    return xi, yi


# ---------------------------------------------------------------------------
# Datenquellen-Helfer
# ---------------------------------------------------------------------------

def _positions(data: dict) -> list[dict]:
    return data.get('positions', []) or []


def _price_records(data: dict) -> list[tuple[str, dict]]:
    """Liefert (Name, Kursdatensatz) für alle verfügbaren Kurshistorien."""
    records = data.get('records', {}) or {}
    choices = data.get('choices', []) or []
    result = []
    for key, name in choices:
        record = records.get(key, {}).get('data', {})
        if record and record.get('prices'):
            result.append((name or key, record))
    return result


def _positions_with_cost(positions: list[dict]) -> list[dict]:
    """Filtert Positionen mit belastbarem Einstandswert."""
    result = []
    for position in positions:
        cost = position.get('cost')
        value = position.get('value')
        if value is None or cost is None:
            continue
        try:
            if Decimal(cost) <= 0:
                continue
        except Exception:
            continue
        result.append(position)
    return result


def _gain(position: dict) -> float:
    """Buchgewinn/Verlust einer Position."""
    return float(Decimal(position['value']) - Decimal(position['cost']))


def _group_positions_by_region(positions: list[dict]) -> dict[str, float]:
    groups: dict[str, float] = defaultdict(float)
    for position in positions:
        value = position.get('value')
        if value is None:
            continue
        groups[position.get('region') or 'Unbekannt'] += float(value)
    return dict(groups)


def _period_series(rows: list[dict], value_key: str = 'value') -> tuple[list[str], list[float]]:
    """Zerlegt eine Zeitreihe in (Datumsstrings, Werte), sortiert nach Datum."""
    cleaned = [(row['date'], float(row[value_key])) for row in rows
               if row.get('date') is not None and row.get(value_key) is not None]
    cleaned.sort(key=lambda pair: pair[0])
    if not cleaned:
        return [], []
    dates, values = zip(*cleaned)
    return list(dates), list(values)


def _changes_by_year(dates: list[str], values: list[float], use_percent: bool = True) -> dict[str, list[float]]:
    """Gruppiert Wertveränderungen (optional in Prozent) nach Kalenderjahr."""
    groups: dict[str, list[float]] = defaultdict(list)
    for index in range(1, len(values)):
        previous, current = values[index - 1], values[index]
        if use_percent:
            if previous == 0:
                continue
            change = (current / previous - 1) * 100
        else:
            change = current - previous
        groups[dates[index][:4]].append(change)
    return dict(groups)


def _returns(values: list[float]) -> list[float]:
    """Periodenrenditen in Prozent."""
    result = []
    for index in range(1, len(values)):
        if values[index - 1]:
            result.append((values[index] / values[index - 1] - 1) * 100)
    return result


# ---------------------------------------------------------------------------
# Line / Area
# ---------------------------------------------------------------------------

@register_renderer('line')
def render_line(figure, data, config: ChartConfig, context: dict) -> str:
    """Rendert ein Liniendiagramm mit optionaler Glättung und Datenbeschriftung."""
    ax = figure.add_subplot(111)
    styling = _get_styling(config)
    palette = _palette(config, styling)
    smooth = bool(_opt(config, styling, 'smooth', False))
    line_color = styling.get('line_color') or palette[0]

    if config.data_source == 'wealth':
        series = _series(data, config)
        if not series:
            _empty_chart(ax)
            return ''
        dates = [date.fromisoformat(r['date']) for r in series]
        values = [float(r['total']) for r in series]
    elif config.data_source == 'valuation':
        rows = _rows(data, config)
        if not rows:
            _empty_chart(ax)
            return ''
        dates = [date.fromisoformat(r['date']) for r in rows]
        values = [float(r['value']) for r in rows]
    else:
        _empty_chart(ax, 'Datenquelle für Liniendiagramm nicht unterstützt.')
        return ''

    x = mdates.date2num(dates)
    if smooth and len(values) >= 3:
        xi, yi = _smooth_series([mdates.date2num(d) for d in dates], values)
        ax.plot(xi, yi, color=line_color, linewidth=styling['line_width'], solid_capstyle='round')
        if styling['fill_alpha'] > 0:
            ax.fill_between(xi, yi, min(values), alpha=styling['fill_alpha'],
                            color=styling.get('fill_color') or line_color)
        ax.scatter(x, values, color=line_color, s=CHART_STYLE['marker_size'] ** 2, zorder=3)
        label_x = list(x)
    else:
        ax.step(dates, values, where='post', marker=styling.get('marker', 'o'),
                color=line_color, linewidth=styling['line_width'],
                markersize=styling.get('marker_size', 4))
        if styling.get('fill_alpha', 0) > 0:
            ax.fill_between(dates, values, step='post', alpha=styling['fill_alpha'],
                            color=styling.get('fill_color') or line_color)
        label_x = dates

    _apply_y_axis(ax, config)
    date_axis(ax)
    _apply_axis_labels(ax, config)
    _add_data_labels(ax, label_x, values, config, styling)
    ax.margins(x=0.02)
    _finish(ax, figure, config, styling)
    return ''


@register_renderer('area')
def render_area(figure, data, config: ChartConfig, context: dict) -> str:
    """Rendert ein gestapeltes Flächendiagramm (optional geglättet)."""
    ax = figure.add_subplot(111)
    styling = _get_styling(config)
    palette = _palette(config, styling)
    smooth = bool(_opt(config, styling, 'smooth', False))

    if config.data_source != 'wealth':
        _empty_chart(ax, 'Datenquelle für Flächendiagramm nicht unterstützt.')
        return ''

    series = _series(data, config)
    if not series:
        _empty_chart(ax)
        return ''

    dates = [date.fromisoformat(r['date']) for r in series]
    categories = sorted({k for r in series for k in r['categories']})
    x = mdates.date2num(dates)
    positive, negative = ([0.0] * len(series), [0.0] * len(series))
    for index, category in enumerate(categories):
        values = [float(r['categories'].get(category, 0)) for r in series]
        upper = [p + max(v, 0) for p, v in zip(positive, values)]
        lower = [p + min(v, 0) for p, v in zip(negative, values)]
        color = palette[index % len(palette)]
        if smooth and len(series) >= 3:
            xs, upper_smooth = _smooth_series(x, upper)
            _, lower_smooth = _smooth_series(x, lower)
            ax.fill_between(xs, lower_smooth, upper_smooth, color=color,
                            alpha=styling['fill_alpha'], label=category)
        else:
            ax.fill_between(dates, positive, upper, step='post', color=color,
                            alpha=styling['fill_alpha'], label=category)
            ax.fill_between(dates, negative, lower, step='post', color=color,
                            alpha=styling['fill_alpha'])
        positive, negative = (upper, lower)

    total = [float(r['total']) for r in series]
    observed = [i for i, r in enumerate(series) if r.get('observed', True)] or None
    ax.step(dates, total, where='post', marker='o', markevery=observed,
            linestyle='--', color=COLORS['text'],
            linewidth=max(1.0, CHART_STYLE['line_width'] - 1.0), label='Nettovermögen')
    _add_data_labels(ax, dates, total, config, styling)

    style_axis(ax, styling['show_grid'])
    _apply_y_axis(ax, config)
    date_axis(ax)
    _apply_axis_labels(ax, config)
    if styling.get('show_legend', True):
        ax.legend(fontsize=CHART_STYLE['legend_fontsize'], frameon=False,
                  labelcolor=COLORS['text'], ncol=min(3, max(1, len(categories) + 1)),
                  loc=styling.get('legend_loc', 'best'))
    _finish(ax, figure, config, styling)
    return ''


# ---------------------------------------------------------------------------
# Bar (vertikal/horizontal) & Kreis
# ---------------------------------------------------------------------------

def _barh_pairs(data, config):
    """Erzeugt (Name, Wert)-Paare für Balkendiagramme aus den bekannten Datenquellen."""
    if config.data_source == 'accounts':
        rows = data.get('rows', [])
        account = config.options.get('account')
        if account and account != ALL_ACCOUNTS:
            rows = [r for r in rows if r['name'] == account]
        return sorted(
            [(r['name'], float(r['balance'] if r['balance'] is not None else r['depot_value']))
             for r in rows if r['balance'] is not None or r['depot_value'] is not None],
            key=lambda p: -p[1]
        )
    if config.data_source == 'positions':
        positions = _positions(data)
        top_n = config.options.get('top_n', CHART_STYLE['top_n'])
        sort_by = config.options.get('sort_by', 'value')
        if sort_by == 'gain':
            return sorted(
                [(p['name'], _gain(p)) for p in _positions_with_cost(positions)],
                key=lambda p: -abs(p[1])
            )[:top_n]
        return sorted([(p['name'], float(p['value'])) for p in positions if p.get('value') is not None],
                      key=lambda p: -p[1])[:top_n]
    if config.data_source == 'wealth':
        series = _series(data, config)
        monthly = {}
        for point in series:
            monthly[point['period']] = point
        series = list(monthly.values())
        pairs = []
        for before, after in zip(series, series[1:]):
            ay, am = map(int, after['period'].split('-'))
            by, bm = map(int, before['period'].split('-'))
            if ay * 12 + am - (by * 12 + bm) == 1:
                pairs.append((after['period'], float(after['total'] - before['total'])))
        return pairs[-CHART_STYLE['max_months']:]
    if config.data_source == 'valuation':
        rows = _rows(data, config)
        return [(r['date'], float(r['value'])) for r in rows][-CHART_STYLE['max_months']:]
    return []


def _draw_barh(ax, pairs, config, styling):
    palette = _palette(config, styling)
    if not pairs:
        _empty_chart(ax)
        return
    names, values = zip(*pairs)
    colors = [COLORS['red'] if v < 0 else palette[i % len(palette)] for i, v in enumerate(values)]
    ax.barh(range(len(names)), values, color=colors, height=0.62)
    ax.set_yticks(range(len(names)), [n[:37] + ('…' if len(n) > 37 else '') for n in names])
    ax.invert_yaxis()
    style_axis(ax, False)
    _apply_x_axis(ax, config)
    ax.xaxis.set_major_locator(MaxNLocator(nbins=4))
    ax.grid(axis='x', color=COLORS['grid'], alpha=CHART_STYLE['grid_alpha'])
    ax.margins(x=0.15)
    _apply_axis_labels(ax, config)
    if _opt(config, styling, 'show_data_labels', False):
        label_format = _x_format(config)
        for index, value in enumerate(values):
            ax.annotate(_format_value(value, label_format), (value, index),
                        textcoords='offset points', xytext=(4 if value >= 0 else -4, 0),
                        ha='left' if value >= 0 else 'right', va='center',
                        fontsize=CHART_STYLE['annotation_fontsize'], color=COLORS['text_light'])
    _finish(ax, ax.figure, config, styling)


@register_renderer('barh')
def render_barh(figure, data, config: ChartConfig, context: dict) -> str:
    """Rendert ein horizontales Balkendiagramm mit optionalen Datenbeschriftungen."""
    ax = figure.add_subplot(111)
    styling = _get_styling(config)
    pairs = _barh_pairs(data, config)
    if not pairs and config.data_source not in ('accounts', 'positions', 'wealth', 'valuation'):
        _empty_chart(ax, 'Datenquelle für Balkendiagramm nicht unterstützt.')
        return ''
    _draw_barh(ax, pairs, config, styling)
    return ''


@register_renderer('bar')
def render_bar(figure, data, config: ChartConfig, context: dict) -> str:
    """Rendert ein vertikales Balkendiagramm mit optionalen Datenbeschriftungen."""
    ax = figure.add_subplot(111)
    styling = _get_styling(config)
    pairs = _barh_pairs(data, config)
    if not pairs:
        _empty_chart(ax)
        return ''
    palette = _palette(config, styling)
    names, values = zip(*pairs)
    colors = [COLORS['red'] if v < 0 else palette[i % len(palette)] for i, v in enumerate(values)]
    positions = range(len(names))
    ax.bar(positions, values, color=colors, width=0.6)
    rotation = 0 if len(names) <= 8 else 45
    ax.set_xticks(list(positions),
                  [str(n)[:24] + ('…' if len(str(n)) > 24 else '') for n in names],
                  rotation=rotation, ha='right' if rotation else 'center')
    _apply_y_axis(ax, config)
    style_axis(ax, styling['show_grid'])
    _apply_axis_labels(ax, config)
    _add_data_labels(ax, list(positions), values, config, styling, rotation=0)
    ax.margins(x=0.04)
    _finish(ax, figure, config, styling)
    return ''


@register_renderer('pie')
def render_pie(figure, data, config: ChartConfig, context: dict) -> str:
    """Rendert ein Kreisdiagramm."""
    ax = figure.add_subplot(111)
    styling = _get_styling(config)
    palette = _palette(config, styling)

    if config.data_source == 'positions':
        positions = _positions(data)
        top_n = config.options.get('top_n', 5)
        groups = _group_positions_by_region(positions)
        total = sum(groups.values())
        if not total:
            _empty_chart(ax)
            return ''
        sorted_groups = sorted(groups.items(), key=lambda p: -p[1])
        if len(sorted_groups) > top_n:
            top = sorted_groups[:top_n]
            rest = sum(v for _, v in sorted_groups[top_n:])
            if rest > 0:
                top.append(('Sonstige', rest))
        else:
            top = sorted_groups
        labels = [k for k, _ in top]
        sizes = [v / total * 100 for _, v in top]
    elif config.data_source == 'wealth':
        series = _series(data, config)
        if not series:
            _empty_chart(ax)
            return ''
        categories = {k: v for k, v in (series[-1].get('categories') or {}).items() if v}
        if not categories:
            _empty_chart(ax)
            return ''
        labels = list(categories.keys())
        sizes = [float(v) for v in categories.values()]
    else:
        _empty_chart(ax, 'Datenquelle für Kreisdiagramm nicht unterstützt.')
        return ''

    colors = [palette[i % len(palette)] for i in range(len(labels))]
    wedges, texts, autotexts = ax.pie(
        sizes, labels=labels, colors=colors, autopct='%1.1f%%', startangle=90,
        textprops={'color': COLORS['text'], 'fontsize': CHART_STYLE['tick_fontsize']},
        wedgeprops={'linewidth': 0.8, 'edgecolor': COLORS['panel']},
    )
    for autotext in autotexts:
        autotext.set_fontsize(CHART_STYLE['tick_fontsize'])
        autotext.set_color(COLORS['text'])
    ax.set_aspect('equal')
    _finish(ax, figure, config, styling)
    return ''


# ---------------------------------------------------------------------------
# Streu
# ---------------------------------------------------------------------------

@register_renderer('scatter')
def render_scatter(figure, data, config: ChartConfig, context: dict) -> str:
    """Rendert ein Streudiagramm Wert gegen Buchgewinn."""
    ax = figure.add_subplot(111)
    styling = _get_styling(config)

    if config.data_source != 'positions':
        _empty_chart(ax, 'Datenquelle für Streudiagramm nicht unterstützt.')
        return ''

    pairs = [(float(p['value']), _gain(p)) for p in _positions_with_cost(_positions(data))]

    if not pairs:
        _empty_chart(ax)
        return ''

    values, gains = zip(*pairs)
    colors = [COLORS['green'] if g >= 0 else COLORS['red'] for g in gains]
    ax.scatter(values, gains, c=colors, alpha=0.65, s=50, edgecolors=COLORS['panel'], linewidths=0.6)
    ax.axhline(0, color=COLORS['muted'], linewidth=0.7, zorder=1)

    ax.set_xlabel(config.axes.get('x', {}).get('label') or 'Wert', color=COLORS['text'])
    ax.set_ylabel(config.axes.get('y', {}).get('label') or 'Gewinn/Verlust', color=COLORS['text'])
    ax.xaxis.set_major_formatter(FuncFormatter(lambda v, p: compact_number(v)))
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, p: compact_number(v)))
    style_axis(ax, styling['show_grid'])
    _finish(ax, figure, config, styling)
    return ''


# ---------------------------------------------------------------------------
# Candlestick
# ---------------------------------------------------------------------------

def _aggregate_closes(rows: list[dict], period: str) -> list[dict]:
    """Aggregiert Schlusskurse zu OHLC-Kerzen (Fallback ohne echte OHLC-Daten)."""
    buckets: dict[str, list[float]] = {}
    order: list[str] = []
    for row in rows:
        iso = row['date']
        day = date.fromisoformat(iso)
        if period == 'weekly':
            year, week, _ = day.isocalendar()
            key = f'{year}-W{week:02d}'
        elif period == 'monthly':
            key = f'{day.year}-{day.month:02d}-01'
        elif period == 'yearly':
            key = f'{day.year}-01-01'
        else:
            key = iso
        if key not in buckets:
            buckets[key] = []
            order.append(key)
        buckets[key].append(float(row['close']))
    result = []
    for key in order:
        closes = buckets[key]
        result.append({
            'date': key,
            'open': closes[0],
            'high': max(closes),
            'low': min(closes),
            'close': closes[-1],
        })
    return result


def _draw_candles(ax, ohlc: list[dict], config: ChartConfig, styling: dict):
    """Zeichnet klassische Candlesticks inkl. Volumen-freier Darstellung."""
    xs = [mdates.date2num(date.fromisoformat(o['date'])) for o in ohlc]
    gaps = [b - a for a, b in zip(xs, xs[1:]) if b > a]
    width = (float(np.median(gaps)) * 0.62) if gaps else 0.6
    for x, candle in zip(xs, ohlc):
        rising = candle['close'] >= candle['open']
        color = COLORS['green'] if rising else COLORS['red']
        ax.vlines(x, candle['low'], candle['high'], color=color, linewidth=0.9, zorder=2)
        bottom = min(candle['open'], candle['close'])
        height = abs(candle['close'] - candle['open'])
        if height == 0:
            height = max((candle['high'] - candle['low']) * 0.002, 1e-9)
        ax.add_patch(Rectangle((x - width / 2, bottom), width, height,
                               facecolor=color, edgecolor=color, linewidth=0.6, zorder=3))
    ax.set_xlim(min(xs) - width, max(xs) + width)
    style_axis(ax, styling['show_grid'])
    date_axis(ax)
    _apply_y_axis(ax, config)
    _apply_axis_labels(ax, config)
    _finish(ax, figure=ax.figure, config=config, styling=styling)


@register_renderer('candlestick')
def render_candlestick(figure, data, config: ChartConfig, context: dict) -> str:
    """Rendert Candlesticks; ohne OHLC-Daten Fallback auf ein Schrittliniendiagramm."""
    ax = figure.add_subplot(111)
    styling = _get_styling(config)

    records = _price_records(data)
    if config.data_source == 'comparison' and records:
        name, record = records[0]
        rows = [r for r in record.get('prices', []) if r.get('close') is not None]
        has_ohlc = any(all(k in r for k in ('open', 'high', 'low')) for r in rows)
        if has_ohlc:
            ohlc = [{
                'date': r['date'],
                'open': float(r.get('open', r['close'])),
                'high': float(r.get('high', r['close'])),
                'low': float(r.get('low', r['close'])),
                'close': float(r['close']),
            } for r in rows]
            _draw_candles(ax, ohlc, config, styling)
            return (f'{name}: Candlestick aus gespeicherten OHLC-Daten. '
                    'Grün: Schlusskurs über Eröffnung, Rot: darunter.')
        aggregate = config.options.get('candle_aggregate')
        if aggregate in ('daily', 'weekly', 'monthly', 'yearly'):
            ohlc = _aggregate_closes(rows, aggregate)
            if ohlc:
                _draw_candles(ax, ohlc, config, styling)
                return (f'{name}: keine echten OHLC-Daten; Kerzen aus Schlusskursen '
                        f'aggregiert ({aggregate}).')

    # Fallback: Schrittliniendiagramm der verfügbaren Schlusskurse
    if records:
        name, record = records[0]
        rows = sorted([r for r in record.get('prices', []) if r.get('close') is not None],
                      key=lambda r: r['date'])
        if rows:
            dates = [date.fromisoformat(r['date']) for r in rows]
            closes = [float(r['close']) for r in rows]
            line_color = styling.get('line_color') or _palette(config, styling)[0]
            ax.step(dates, closes, where='post', marker='o', color=line_color,
                    linewidth=styling['line_width'])
            if styling.get('fill_alpha', 0) > 0:
                ax.fill_between(dates, closes, step='post', alpha=styling['fill_alpha'],
                                color=styling.get('fill_color') or line_color)
            _apply_y_axis(ax, config)
            date_axis(ax)
            ax.margins(x=0.02)
            _finish(ax, figure, config, styling, subtitle='Keine OHLC-Daten – Schrittlinie')
            return (f'{name}: keine OHLC-Daten verfügbar, daher Schrittliniendarstellung '
                    'der Schlusskurse.')

    _empty_chart(ax, 'Für Candlesticks werden gespeicherte Kurshistorien benötigt.')
    return 'Für Candlesticks wird eine gespeicherte Kurshistorie (Vergleichsauswahl) benötigt.'


# ---------------------------------------------------------------------------
# Heatmap
# ---------------------------------------------------------------------------

def _annotate_heatmap(ax, matrix, row_labels, col_labels, fmt='currency'):
    """Beschriftet Heatmap-Zellen mit ihren Werten."""
    for i in range(matrix.shape[0]):
        for j in range(matrix.shape[1]):
            value = matrix[i, j]
            if np.isnan(value):
                continue
            ax.text(j, i, _format_value(float(value), fmt), ha='center', va='center',
                    fontsize=CHART_STYLE['annotation_fontsize'], color=COLORS['text'])


@register_renderer('heatmap')
def render_heatmap(figure, data, config: ChartConfig, context: dict) -> str:
    """Rendert eine Heatmap – je nach Datenquelle Positions- oder Zeitreihenmatrix."""
    ax = figure.add_subplot(111)
    styling = _get_styling(config)
    annotate = bool(_opt(config, styling, 'show_data_labels', False))
    cmap = colormaps['viridis']

    if config.data_source == 'positions':
        positions = sorted([p for p in _positions(data) if p.get('value') is not None],
                           key=lambda p: -float(p['value']))[:config.options.get('top_n', CHART_STYLE['top_n'])]
        if not positions:
            _empty_chart(ax)
            return ''
        columns = ['Wert', 'Gewinn']
        matrix = np.array([
            [float(p['value']), _gain(p)] if p.get('cost') is not None and Decimal(p['cost']) > 0
            else [float(p['value']), np.nan]
            for p in positions
        ], dtype=float)
        # Spaltenweise auf 0..1 normalisieren, damit die Farbintensität vergleichbar ist
        normalized = np.full_like(matrix, np.nan)
        for j in range(matrix.shape[1]):
            column = matrix[:, j]
            finite = column[np.isfinite(column)]
            if finite.size:
                low, high = finite.min(), finite.max()
                normalized[:, j] = (column - low) / (high - low) if high > low else 0.5
        display = np.where(np.isfinite(normalized), normalized, 0.0)
        image = ax.imshow(display, cmap=cmap, aspect='auto', vmin=0, vmax=1)
        ax.set_xticks(range(len(columns)), columns)
        ax.set_yticks(range(len(positions)),
                      [p['name'][:32] + ('…' if len(p['name']) > 32 else '') for p in positions])
        if annotate:
            for i in range(matrix.shape[0]):
                for j in range(matrix.shape[1]):
                    if np.isfinite(matrix[i, j]):
                        ax.text(j, i, _format_value(matrix[i, j]), ha='center', va='center',
                                fontsize=CHART_STYLE['annotation_fontsize'], color=COLORS['text'])
        figure.colorbar(image, ax=ax, fraction=0.03, pad=0.02, label='relativ')
        _finish(ax, figure, config, styling, subtitle='Farbe: spaltenweise relativ')
        ax.grid(False)
        return 'Farbskala je Kennzahl normiert; absolute Werte über die Beschriftung.'

    if config.data_source == 'wealth':
        series = _series(data, config)
        if not series:
            _empty_chart(ax)
            return ''
        categories = sorted({k for r in series for k in r['categories']})
        matrix = np.array([[float(r['categories'].get(c, 0)) for r in series] for c in categories],
                          dtype=float)
        if not matrix.size:
            _empty_chart(ax)
            return ''
        image = ax.imshow(matrix, cmap=cmap, aspect='auto')
        ax.set_yticks(range(len(categories)), categories)
        indices = stride_indices(len(series), target=8)
        ax.set_xticks(indices, [series[i]['period'] for i in indices])
        figure.colorbar(image, ax=ax, fraction=0.03, pad=0.02, label='Wert')
        _finish(ax, figure, config, styling)
        ax.grid(False)
        return 'Kategorien über die Zeit; Farbe entspricht dem jeweiligen Kategorie-Wert.'

    if config.data_source == 'valuation':
        rows = _rows(data, config)
        if not rows:
            _empty_chart(ax)
            return ''
        by_month: dict[tuple[str, int], float] = {}
        for row in rows:
            day = date.fromisoformat(row['date'])
            key = (str(day.year), day.month)
            by_month[key] = float(row['value'])
        years = sorted({year for year, _ in by_month})
        matrix = np.full((len(years), 12), np.nan)
        for (year, month), value in by_month.items():
            matrix[years.index(year), month - 1] = value
        image = ax.imshow(np.where(np.isfinite(matrix), matrix, np.nan),
                          cmap=cmap, aspect='auto')
        ax.set_yticks(range(len(years)), years)
        ax.set_xticks(range(12), ['J', 'F', 'M', 'A', 'M', 'J', 'J', 'A', 'S', 'O', 'N', 'D'])
        if annotate:
            _annotate_heatmap(ax, matrix, years, range(12))
        figure.colorbar(image, ax=ax, fraction=0.03, pad=0.02, label='Depotwert')
        _finish(ax, figure, config, styling, subtitle='Depotwert je Kalendermonat')
        ax.grid(False)
        return 'Depotwert als Kalender-Heatmap (Jahr × Monat).'

    _empty_chart(ax, 'Datenquelle für Heatmap nicht unterstützt.')
    return 'Für Heatmaps werden Positionen, Vermögens- oder Depotwertdaten benötigt.'


def stride_indices(count: int, target: int = 8) -> list[int]:
    """Gleichmäßig verteilte Indizes für Achsenbeschriftungen."""
    if count <= target:
        return list(range(count))
    step = max(1, count // target)
    indices = list(range(0, count, step))
    if indices[-1] != count - 1:
        indices.append(count - 1)
    return indices


# ---------------------------------------------------------------------------
# Boxplot / Violin
# ---------------------------------------------------------------------------

def _distribution_groups(data, config):
    """Ermittelt Verteilungsgruppen (Label -> Werte) je Datenquelle."""
    source = config.data_source
    if source == 'positions':
        groups: dict[str, list[float]] = defaultdict(list)
        for position in _positions_with_cost(_positions(data)):
            groups[position.get('region') or 'Unbekannt'].append(_gain(position))
        return dict(groups)
    if source == 'valuation':
        dates, values = _period_series(_rows(data, config))
    elif source == 'wealth':
        series = _series(data, config)
        dates = [r['date'] for r in series]
        values = [float(r['total']) for r in series]
    else:
        return {}
    return _changes_by_year(dates, values, use_percent=True)


def _draw_distribution(figure, data, config: ChartConfig, styling: dict, violin: bool):
    ax = figure.add_subplot(111)
    groups = _distribution_groups(data, config)
    # Leere Gruppen entfernen
    groups = {label: values for label, values in groups.items() if values}
    if not groups:
        _empty_chart(ax)
        return ''
    palette = _palette(config, styling)
    labels = list(groups.keys())
    datasets = [groups[label] for label in labels]

    if violin:
        parts = ax.violinplot(datasets, showmeans=False, showmedians=True, widths=0.8)
        for index, body in enumerate(parts['bodies']):
            body.set_facecolor(palette[index % len(palette)])
            body.set_edgecolor(COLORS['panel'])
            body.set_alpha(0.7)
        for key in ('cmedians', 'cbars', 'cmins', 'cmaxes'):
            if key in parts:
                parts[key].set_color(COLORS['text'])
        ax.set_xticks(range(1, len(labels) + 1), labels, rotation=0)
        subtitle = 'Verteilung (Violin) · Median markiert'
    else:
        box = ax.boxplot(datasets, patch_artist=True, widths=0.6,
                         medianprops={'color': COLORS['text'], 'linewidth': 1.2},
                         whiskerprops={'color': COLORS['grid']},
                         capprops={'color': COLORS['grid']},
                         flierprops={'marker': 'o', 'markersize': 3,
                                     'markerfacecolor': COLORS['muted'], 'alpha': 0.5})
        for index, patch in enumerate(box['boxes']):
            patch.set_facecolor(palette[index % len(palette)])
            patch.set_edgecolor(COLORS['panel'])
            patch.set_alpha(0.8)
        ax.set_xticks(range(1, len(labels) + 1), labels, rotation=0)
        subtitle = 'Verteilung (Boxplot) · Median markiert'

    if config.data_source in ('wealth', 'valuation'):
        percent_axis(ax)
    elif _y_format(config) == 'number':
        number_axis(ax)
    else:
        currency_axis(ax)
    ax.axhline(0, color=COLORS['muted'], linewidth=0.7, zorder=1)
    style_axis(ax, styling['show_grid'])
    _finish(ax, figure, config, styling, subtitle=subtitle)
    if config.data_source in ('wealth', 'valuation'):
        return 'Verteilung der Veränderungen je Kalenderjahr in Prozent; Ein- und Auszahlungen sind nicht bereinigt.'
    return 'Verteilung der Buchgewinne je Region; Positionen ohne Einstandswert sind ausgeschlossen.'


@register_renderer('boxplot')
def render_boxplot(figure, data, config: ChartConfig, context: dict) -> str:
    """Rendert einen Boxplot für Verteilungen (Buchgewinne je Region bzw. Jahresrenditen)."""
    return _draw_distribution(figure, data, config, _get_styling(config), violin=False)


@register_renderer('violin')
def render_violin(figure, data, config: ChartConfig, context: dict) -> str:
    """Rendert einen Violinplot für Verteilungen."""
    return _draw_distribution(figure, data, config, _get_styling(config), violin=True)


# ---------------------------------------------------------------------------
# Histogramm
# ---------------------------------------------------------------------------

@register_renderer('histogram')
def render_histogram(figure, data, config: ChartConfig, context: dict) -> str:
    """Rendert ein Histogramm – typischerweise über Periodenrenditen."""
    ax = figure.add_subplot(111)
    styling = _get_styling(config)
    palette = _palette(config, styling)

    if config.data_source == 'positions':
        values = [_gain(p) for p in _positions_with_cost(_positions(data))]
        x_label = 'Gewinn/Verlust'
        fmt = 'currency'
    elif config.data_source == 'valuation':
        _, series_values = _period_series(_rows(data, config))
        values = _returns(series_values)
        x_label = 'Periodenrendite'
        fmt = 'percent'
    elif config.data_source == 'wealth':
        series = _series(data, config)
        _, series_values = _period_series(series, value_key='total')
        values = _returns(series_values)
        x_label = 'Periodenrendite'
        fmt = 'percent'
    else:
        _empty_chart(ax, 'Datenquelle für Histogramm nicht unterstützt.')
        return 'Für das Histogramm werden Positions-, Vermögens- oder Depotwertdaten benötigt.'

    values = [v for v in values if v is not None]
    if not values:
        _empty_chart(ax)
        return ''

    bins = config.options.get('bins', 'auto')
    ax.hist(values, bins=bins, color=palette[0], edgecolor=COLORS['panel'], alpha=0.85)
    mean = float(np.mean(values))
    median = float(np.median(values))
    if fmt == 'percent':
        ax.axvline(0, color=COLORS['muted'], linewidth=0.8)
        percent_x_axis(ax)
    else:
        ax.axvline(0, color=COLORS['muted'], linewidth=0.8)
        ax.xaxis.set_major_formatter(FuncFormatter(lambda v, p: compact_number(v)))
    ax.axvline(mean, color=COLORS['blue'], linewidth=1.4, linestyle='--', label=f'Mittel {_format_value(mean, fmt, 2)}')
    ax.axvline(median, color=COLORS['amber'], linewidth=1.4, linestyle=':', label=f'Median {_format_value(median, fmt, 2)}')
    ax.set_xlabel(x_label, color=COLORS['text'])
    number_axis(ax)
    style_axis(ax, styling['show_grid'])
    if styling.get('show_legend', True):
        ax.legend(fontsize=CHART_STYLE['legend_fontsize'], frameon=False,
                  labelcolor=COLORS['text'], loc='best')
    _finish(ax, figure, config, styling)
    note = 'Verteilung der Werte; Mittelwert (gestrichelt) und Median (gepunktet) markiert.'
    if config.data_source in ('wealth', 'valuation'):
        note += ' Periodenveränderungen, nicht zahlungsstrombereinigt.'
    return note


# ---------------------------------------------------------------------------
# Treemap
# ---------------------------------------------------------------------------

def _layoutrow(sizes, x, y, dx, dy):
    covered = sum(sizes)
    width = covered / dy if dy else 0
    rects = []
    for size in sizes:
        height = size / width if width else 0
        rects.append((x, y, width, height))
        y += height
    return rects


def _layoutcol(sizes, x, y, dx, dy):
    covered = sum(sizes)
    height = covered / dx if dx else 0
    rects = []
    for size in sizes:
        width = size / height if height else 0
        rects.append((x, y, width, height))
        x += width
    return rects


def _layout(sizes, x, y, dx, dy):
    return _layoutrow(sizes, x, y, dx, dy) if dx >= dy else _layoutcol(sizes, x, y, dx, dy)


def _leftover_row(sizes, x, y, dx, dy):
    covered = sum(sizes)
    width = covered / dy if dy else 0
    return (x + width, y, dx - width, dy)


def _leftover_col(sizes, x, y, dx, dy):
    covered = sum(sizes)
    height = covered / dx if dx else 0
    return (x, y + height, dx, dy - height)


def _leftover(sizes, x, y, dx, dy):
    return _leftover_row(sizes, x, y, dx, dy) if dx >= dy else _leftover_col(sizes, x, y, dx, dy)


def _worst_ratio(sizes, x, y, dx, dy):
    rects = _layout(sizes, x, y, dx, dy)
    return max(max(w / h, h / w) for _, _, w, h in rects if w > 0 and h > 0)


def _squarify(sizes, x, y, dx, dy):
    """Squarified-Treemap-Layout (Bruls et al.) als eingebauter Fallback."""
    sizes = list(map(float, sizes))
    if not sizes:
        return []
    if len(sizes) == 1:
        return _layout(sizes, x, y, dx, dy)
    index = 1
    while index < len(sizes) and _worst_ratio(sizes[:index], x, y, dx, dy) >= \
            _worst_ratio(sizes[:index + 1], x, y, dx, dy):
        index += 1
    current = sizes[:index]
    remaining = sizes[index:]
    leftover = _leftover(current, x, y, dx, dy)
    return _layout(current, x, y, dx, dy) + _squarify(remaining, *leftover)


def _draw_treemap(ax, figure, labels, values, config, styling, subtitle=None):
    palette = _palette(config, styling)
    pairs = sorted([(label, float(value)) for label, value in zip(labels, values) if value and value > 0],
                   key=lambda pair: -pair[1])
    if not pairs:
        _empty_chart(ax)
        return
    names, sizes = zip(*pairs)
    total = sum(sizes)
    width, height = 100.0, 100.0
    scaled = [size / total * width * height for size in sizes]
    rects = _squarify(scaled, 0, 0, width, height)
    for index, (rect, name, size) in enumerate(zip(rects, names, sizes)):
        x, y, dx, dy = rect
        ax.add_patch(Rectangle((x, y), dx, dy, facecolor=palette[index % len(palette)],
                               edgecolor=COLORS['panel'], linewidth=1.4))
        if dx * dy > total * 0.5:
            ax.text(x + dx / 2, y + dy / 2,
                    f'{name[:20]}\n{size / total * 100:.1f} %'.replace('.', ','),
                    ha='center', va='center', color=COLORS['panel'] if size / total > 0.08 else COLORS['text'],
                    fontsize=CHART_STYLE['annotation_fontsize'], fontweight='bold')
    ax.set_xlim(0, width)
    ax.set_ylim(0, height)
    ax.set_axis_off()
    apply_professional_style(figure, ax, title=config.title, subtitle=subtitle or 'Fläche = Anteil am Gesamtwert')
    ax.set_axis_off()


@register_renderer('treemap')
def render_treemap(figure, data, config: ChartConfig, context: dict) -> str:
    """Rendert eine Treemap – Größe entspricht dem Positions- bzw. Kategoriewert."""
    ax = figure.add_subplot(111)
    styling = _get_styling(config)

    if config.data_source == 'positions':
        positions = _positions(data)
        groups = _group_positions_by_region(positions)
        # Regionen als Kacheln, alternativ Einzelpositionen wenn Option gesetzt
        if config.options.get('by_position'):
            top = sorted([(p['name'], float(p['value'])) for p in positions if p.get('value')],
                         key=lambda pair: -pair[1])[:config.options.get('top_n', CHART_STYLE['top_n'])]
            labels, values = zip(*top) if top else ([], [])
        else:
            labels, values = zip(*sorted(groups.items(), key=lambda pair: -pair[1])) if groups else ([], [])
        _draw_treemap(ax, figure, labels, values, config, styling,
                      subtitle='Regionen nach Depotwert · Fläche = Anteil')
        return 'Treemap der Depotwerte nach Region; Fläche entspricht dem Anteil am Gesamtwert.'
    if config.data_source == 'wealth':
        series = _series(data, config)
        if not series:
            _empty_chart(ax)
            return ''
        categories = {k: v for k, v in (series[-1].get('categories') or {}).items() if v}
        labels = list(categories.keys())
        values = [float(v) for v in categories.values()]
        _draw_treemap(ax, figure, labels, values, config, styling,
                      subtitle='Vermögenskategorien · Fläche = Anteil')
        return 'Treemap der Vermögenskategorien zum letzten Datenpunkt.'

    _empty_chart(ax, 'Datenquelle für Treemap nicht unterstützt.')
    return 'Für die Treemap werden Positions- oder Vermögensdaten benötigt.'


# ---------------------------------------------------------------------------
# Radar
# ---------------------------------------------------------------------------

@register_renderer('radar')
def render_radar(figure, data, config: ChartConfig, context: dict) -> str:
    """Rendert ein Radar-Diagramm der Allokation nach Kategorien."""
    styling = _get_styling(config)
    palette = _palette(config, styling)

    if config.data_source == 'positions':
        groups = _group_positions_by_region(_positions(data))
    elif config.data_source == 'wealth':
        series = _series(data, config)
        groups = {k: float(v) for k, v in (series[-1].get('categories') or {}).items() if v} if series else {}
    else:
        groups = {}

    if len(groups) < 3:
        ax = figure.add_subplot(111)
        _empty_chart(ax, 'Für ein Radar-Diagramm werden mindestens drei Kategorien benötigt.')
        return 'Für das Radar-Diagramm sind mindestens drei Kategorien erforderlich.'

    sorted_groups = sorted(groups.items(), key=lambda pair: -pair[1])
    labels = [label for label, _ in sorted_groups]
    values = [value for _, value in sorted_groups]
    total = sum(values) or 1
    shares = [v / total * 100 for v in values]

    ax = figure.add_subplot(111, polar=True)
    angles = np.linspace(0, 2 * np.pi, len(labels), endpoint=False).tolist()
    closed = shares + shares[:1]
    closed_angles = angles + angles[:1]
    ax.plot(closed_angles, closed, color=palette[0], linewidth=styling['line_width'])
    ax.fill(closed_angles, closed, color=palette[0], alpha=0.25)
    ax.scatter(angles, shares, color=palette[0], s=24, zorder=5)
    for angle, share, label in zip(angles, shares, labels):
        ax.annotate(f'{share:.1f} %'.replace('.', ','), (angle, share),
                    textcoords='offset points', xytext=(0, 8), ha='center',
                    fontsize=CHART_STYLE['annotation_fontsize'], color=COLORS['text_light'])
    ax.set_xticks(angles, labels)
    ax.set_xticklabels([label[:18] + ('…' if len(label) > 18 else '') for label in labels],
                       fontsize=CHART_STYLE['tick_fontsize'], color=COLORS['text'])
    ax.tick_params(colors=COLORS['text'], labelsize=CHART_STYLE['tick_fontsize'])
    ax.set_facecolor(COLORS['panel'])
    ax.grid(color=COLORS['grid'], alpha=CHART_STYLE['grid_alpha'], linewidth=0.7)
    ax.spines['polar'].set_color(COLORS['grid'])
    ax.set_title(config.title, loc='left', color=COLORS['text'],
                 fontsize=styling['title_fontsize'], fontweight='bold', pad=24)
    return 'Allokation nach Kategorien in Prozent des Gesamtwerts.'


# ---------------------------------------------------------------------------
# Kursvergleich
# ---------------------------------------------------------------------------

@register_renderer('comparison')
def render_comparison(figure, data, config: ChartConfig, context: dict) -> str:
    """Rendert einen Kursvergleich (Basis 100)."""
    from .chart_rendering import draw_price_comparison
    as_of = context.get('as_of', '9999-12-31')
    carry_prices = context.get('carry_prices', False)
    records = data.get('records', {})
    choices = data.get('choices', [])
    # Kombiniere records zu einer Liste für draw_price_comparison
    comparison_data = []
    for key, name in choices[:2]:
        record = records.get(key, {}).get('data', {})
        if record:
            comparison_data.append(record)
    if len(comparison_data) < 2:
        _empty_chart(figure.add_subplot(111),
                    'Für den Kursvergleich werden zwei gespeicherte Kurshistorien benötigt.')
        return 'Für den Kursvergleich werden zwei gespeicherte Kurshistorien bis zum gewählten Datum benötigt.'
    return draw_price_comparison(figure, comparison_data, as_of, carry_prices)
