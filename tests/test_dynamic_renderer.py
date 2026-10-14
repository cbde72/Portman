"""Tests für die dynamische Rendering-Engine (dynamic_renderer)."""
import os
from decimal import Decimal
from io import BytesIO

os.environ.setdefault('MPLBACKEND', 'Agg')

import matplotlib
matplotlib.use('Agg')

from portman.chart_config import CHART_TYPES, ChartConfig
from portman.chart_style import create_figure
from portman.dynamic_renderer import render_chart, _RENDERERS, _series, _rows


ERROR_MARKER = 'konnte nicht gezeichnet werden'


def _wealth():
    series = []
    total = 100000.0
    for index in range(24):
        month = index % 12 + 1
        year = 2022 + index // 12
        total += 1200 + 300 * ((index % 4) - 2)
        series.append({
            'date': f'{year}-{month:02d}-15',
            'period': f'{year}-{month:02d}',
            'total': total,
            'categories': {'Aktien': total * 0.5, 'Anleihen': total * 0.3, 'Cash': total * 0.2},
            'observed': index % 2 == 0,
        })
    return {'series': series, 'summary': {'categories': series[-1]['categories']}}


def _positions():
    return {'positions': [
        {'name': 'ETF Welt', 'value': 42000.0, 'cost': 30000.0, 'region': 'Nordamerika'},
        {'name': 'ETF Europa', 'value': 18000.0, 'cost': 20000.0, 'region': 'Europa'},
        {'name': 'ETF Asien', 'value': 12000.0, 'cost': 9000.0, 'region': 'Asien'},
        {'name': 'Aktie A', 'value': 8000.0, 'cost': 5000.0, 'region': 'Nordamerika'},
        {'name': 'Aktie B', 'value': 6000.0, 'cost': 7500.0, 'region': 'Europa'},
    ]}


def _accounts():
    return {'rows': [
        {'name': 'Giro', 'balance': 12000.0, 'depot_value': None},
        {'name': 'Depot', 'balance': None, 'depot_value': 85000.0},
    ]}


def _valuation():
    return {'rows': [{'date': r['date'], 'value': r['total'] * 0.8} for r in _wealth()['series']]}


def _comparison(prices):
    return {'records': {'a': {'data': {'symbol': 'A', 'currency': 'EUR', 'prices': prices}}},
            'choices': [('a', 'A')]}


def _config(chart_type, data_source, options=None):
    return ChartConfig(id='test', title='Test', chart_type=chart_type,
                       data_source=data_source, options=options or {},
                       axes={'x': {'type': 'date', 'label': ''}, 'y': {'type': 'currency', 'label': ''}})


def _draw(chart_type, data_source, data, options=None):
    config = _config(chart_type, data_source, options)
    figure = create_figure()
    figure.clear()
    figure.set_layout_engine('constrained')
    note = render_chart(figure, data, config, {'as_of': '9999-12-31'})
    figure.savefig(BytesIO(), format='png')
    assert ERROR_MARKER not in (note or ''), note
    return figure, note


def _draw_config(chart_type, data_source, data, axes=None, aggregation=None, options=None):
    """Zeichnet mit expliziter Achsen-/Aggregationskonfiguration."""
    config = ChartConfig(
        id='test', title='Test', chart_type=chart_type, data_source=data_source,
        options=options or {}, aggregation=aggregation or {},
        axes=axes or {'x': {'type': 'date', 'label': ''}, 'y': {'type': 'currency', 'label': ''}})
    figure = create_figure()
    figure.clear()
    figure.set_layout_engine('constrained')
    note = render_chart(figure, data, config, {'as_of': '9999-12-31'})
    figure.savefig(BytesIO(), format='png')
    assert ERROR_MARKER not in (note or ''), note
    return figure, note


def _agg_config(aggregation, data_source='wealth', chart_type='line'):
    return ChartConfig(
        id='test', title='Test', chart_type=chart_type, data_source=data_source,
        options={}, aggregation=aggregation,
        axes={'x': {'type': 'date', 'label': ''}, 'y': {'type': 'currency', 'label': ''}})


def _dense_wealth(months=4, points_per_month=3):
    """Mehrere Punkte je Monat, um zeitliche Aggregation beobachten zu können."""
    series = []
    index = 0
    for month in range(1, months + 1):
        for point in range(points_per_month):
            index += 1
            total = 10000.0 * index
            series.append({
                'date': f'2023-{month:02d}-{5 + 7 * point:02d}',
                'period': f'2023-{month:02d}',
                'total': total,
                'categories': {'A': total * 0.6, 'B': total * 0.4},
                'observed': True,
            })
    return {'series': series, 'summary': {'categories': series[-1]['categories']}}


def test_all_configured_chart_types_have_a_renderer():
    for chart_type in CHART_TYPES:
        assert chart_type in _RENDERERS, f'Kein Renderer für {chart_type}'


def test_line_smooth_adds_interpolated_points():
    data = _wealth()
    _, _ = _draw('line', 'wealth', data)
    step_points = len(_wealth()['series'])
    figure, _ = _draw('line', 'wealth', data, {'smooth': True})
    line = figure.axes[0].lines[0]
    assert len(line.get_xdata()) > step_points


def test_area_and_barh_draw():
    figure, _ = _draw('area', 'wealth', _wealth())
    assert figure.axes
    figure, _ = _draw('barh', 'positions', _positions(), {'top_n': 5})
    assert figure.axes[0].patches


def test_candlestick_uses_ohlc_when_available():
    prices = [{'date': f'2023-01-{day:02d}', 'open': 100 + day, 'high': 103 + day,
               'low': 98 + day, 'close': 101 + day} for day in range(1, 6)]
    figure, note = _draw('candlestick', 'comparison', _comparison(prices))
    assert 'OHLC' in note
    assert figure.axes[0].patches  # Kerzenkörper


def test_candlestick_falls_back_to_step_chart():
    prices = [{'date': f'2023-01-{day:02d}', 'close': 100 + day} for day in range(1, 6)]
    figure, note = _draw('candlestick', 'comparison', _comparison(prices))
    assert 'Schrittlinie' in note
    assert figure.axes[0].lines


def test_candlestick_aggregates_closes_on_demand():
    prices = [{'date': f'2023-01-{day:02d}', 'close': 100 + day} for day in range(1, 21)]
    figure, note = _draw('candlestick', 'comparison', _comparison(prices), {'candle_aggregate': 'weekly'})
    assert 'aggregiert' in note
    assert figure.axes[0].patches


def test_heatmap_for_positions_and_time_series():
    figure, _ = _draw('heatmap', 'positions', _positions())
    assert figure.axes[0].images
    figure, _ = _draw('heatmap', 'wealth', _wealth())
    assert figure.axes[0].images


def test_boxplot_and_violin_draw_distributions():
    figure, _ = _draw('boxplot', 'positions', _positions())
    assert figure.axes[0].artists or figure.axes[0].patches
    figure, note = _draw('violin', 'valuation', _valuation())
    assert 'Verteilung' in note


def test_histogram_returns():
    figure, note = _draw('histogram', 'wealth', _wealth())
    assert figure.axes[0].patches
    assert 'Median' in note


def test_treemap_uses_value_as_area():
    figure, _ = _draw('treemap', 'positions', _positions())
    rectangles = figure.axes[0].patches
    assert rectangles, 'Treemap ohne Kacheln'
    assert max(rect.get_width() * rect.get_height()
               for rect in rectangles) > min(rect.get_width() * rect.get_height()
                                             for rect in rectangles)


def test_radar_requires_three_categories():
    figure, _ = _draw('radar', 'wealth', _wealth())
    assert len(figure.axes[0].collections) >= 1  # gefüllte Fläche
    small = {'series': [{'date': '2023-01-15', 'period': '2023-01', 'total': 100.0,
                         'categories': {'A': 60.0, 'B': 40.0}, 'observed': True}]}
    figure, note = _draw('radar', 'wealth', small)
    assert 'mindestens drei' in note


def test_empty_positions_do_not_raise():
    for chart_type in _RENDERERS:
        _draw(chart_type, 'positions', {'positions': []})


# ---------------------------------------------------------------------------
# Zeitliche Aggregation
# ---------------------------------------------------------------------------

def test_monthly_aggregation_keeps_last_point_per_month():
    data = _dense_wealth(months=4, points_per_month=3)
    series = _series(data, _agg_config({'type': 'monthly', 'method': 'last'}))
    assert len(series) == 4
    assert [row['date'] for row in series] == ['2023-01-19', '2023-02-19', '2023-03-19', '2023-04-19']
    # letzter Punkt je Monat: 3., 6., 9., 12. Eintrag
    assert [float(row['total']) for row in series] == [30000.0, 60000.0, 90000.0, 120000.0]


def test_monthly_aggregation_sums_and_means_values():
    data = _dense_wealth(months=2, points_per_month=3)
    summed = _series(data, _agg_config({'type': 'monthly', 'method': 'sum'}))
    assert [float(row['total']) for row in summed] == [60000.0, 150000.0]
    averaged = _series(data, _agg_config({'type': 'monthly', 'method': 'mean'}))
    assert [float(row['total']) for row in averaged] == [20000.0, 50000.0]


def test_aggregation_combines_categories_consistently():
    data = _dense_wealth(months=1, points_per_month=3)
    averaged = _series(data, _agg_config({'type': 'monthly', 'method': 'mean'}))
    row = averaged[0]
    # A: 60 %, B: 40 % des Monatsmittelwerts (20000)
    assert float(row['categories']['A']) == 12000.0
    assert float(row['categories']['B']) == 8000.0


def test_daily_aggregation_keeps_one_point_per_day():
    data = {'series': [
        {'date': '2023-01-05', 'period': '2023-01', 'total': 1.0, 'observed': True},
        {'date': '2023-01-05', 'period': '2023-01', 'total': 2.0, 'observed': False},
        {'date': '2023-01-06', 'period': '2023-01', 'total': 3.0, 'observed': True},
    ]}
    series = _series(data, _agg_config({'type': 'daily', 'method': 'last'}))
    assert len(series) == 2
    assert series[0]['total'] == 2.0
    assert series[0]['observed'] is True  # eines der Tageswerte ist beobachtet


def test_weekly_aggregation_groups_by_iso_week():
    # 2022-12-31 und 2023-01-01 liegen beide in ISO-KW 52 (2022)
    data = {'series': [
        {'date': '2022-12-31', 'period': '2022-12', 'total': 5.0, 'observed': True},
        {'date': '2023-01-01', 'period': '2023-01', 'total': 6.0, 'observed': True},
        {'date': '2023-01-03', 'period': '2023-01', 'total': 7.0, 'observed': True},
    ]}
    weekly = _series(data, _agg_config({'type': 'weekly', 'method': 'sum'}))
    assert len(weekly) == 2
    assert [float(row['total']) for row in weekly] == [11.0, 7.0]
    assert weekly[0]['date'] == '2023-01-01'


def test_aggregation_preserves_decimal_values():
    data = {'series': [
        {'date': '2023-01-05', 'period': '2023-01', 'total': Decimal('100.50'),
         'categories': {'A': Decimal('60.30')}, 'observed': True},
        {'date': '2023-01-19', 'period': '2023-01', 'total': Decimal('200.25'),
         'categories': {'A': Decimal('120.15')}, 'observed': True},
    ]}
    summed = _series(data, _agg_config({'type': 'monthly', 'method': 'sum'}))
    assert summed[0]['total'] == Decimal('300.75')
    assert summed[0]['categories']['A'] == Decimal('180.45')
    averaged = _series(data, _agg_config({'type': 'monthly', 'method': 'mean'}))
    assert averaged[0]['total'] == Decimal('150.375')
    assert averaged[0]['categories']['A'] == Decimal('90.225')


def test_valuation_rows_aggregate_monthly():
    data = {'rows': [
        {'date': '2023-01-05', 'value': 100.0},
        {'date': '2023-01-19', 'value': 120.0},
        {'date': '2023-02-05', 'value': 90.0},
    ]}
    rows = _rows(data, _agg_config({'type': 'monthly', 'method': 'last'}, data_source='valuation'))
    assert [row['date'] for row in rows] == ['2023-01-19', '2023-02-05']
    assert [float(row['value']) for row in rows] == [120.0, 90.0]


def test_line_render_applies_monthly_aggregation():
    data = _dense_wealth(months=4, points_per_month=3)
    figure, _ = _draw('line', 'wealth', data)
    assert len(figure.axes[0].lines[0].get_xdata()) == 12
    figure, _ = _draw_config('line', 'wealth', data,
                             aggregation={'type': 'monthly', 'method': 'last'})
    assert len(figure.axes[0].lines[0].get_xdata()) == 4


def test_time_range_filters_before_aggregation():
    data = _dense_wealth(months=4, points_per_month=3)
    config = ChartConfig(
        id='test', title='Test', chart_type='line', data_source='wealth',
        options={}, aggregation={'type': 'monthly', 'method': 'last'},
        time_range={'start': '2023-02-01', 'end': '2023-03-31'},
        axes={'x': {'type': 'date', 'label': ''}, 'y': {'type': 'currency', 'label': ''}})
    series = _series(data, config)
    assert len(series) == 2
    assert [row['date'] for row in series] == ['2023-02-19', '2023-03-19']


# ---------------------------------------------------------------------------
# Achsenbeschriftungen
# ---------------------------------------------------------------------------

def test_axis_labels_are_applied_to_common_charts():
    labeled = {'x': {'type': 'date', 'label': 'Zeitachse'},
               'y': {'type': 'currency', 'label': 'Wertachse'}}
    cases = [
        ('line', 'wealth', _wealth()),
        ('area', 'wealth', _wealth()),
        ('barh', 'positions', _positions()),
        ('bar', 'positions', _positions()),
    ]
    for chart_type, source, data in cases:
        figure, _ = _draw_config(chart_type, source, data, axes=labeled)
        ax = figure.axes[0]
        assert ax.get_xlabel() == 'Zeitachse', chart_type
        assert ax.get_ylabel() == 'Wertachse', chart_type


def test_axis_labels_are_applied_to_candlesticks():
    prices = [{'date': f'2023-01-{day:02d}', 'open': 100 + day, 'high': 103 + day,
               'low': 98 + day, 'close': 101 + day} for day in range(1, 6)]
    axis_cfg = {'x': {'type': 'date', 'label': 'Handelsdatum'},
                'y': {'type': 'currency', 'label': 'Kurs'}}
    figure, _ = _draw_config('candlestick', 'comparison', _comparison(prices), axes=axis_cfg)
    assert figure.axes[0].get_xlabel() == 'Handelsdatum'
    assert figure.axes[0].get_ylabel() == 'Kurs'
