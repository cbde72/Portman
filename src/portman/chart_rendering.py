"""Matplotlib renderers consuming prepared data, without repository or widget access."""
from collections import defaultdict
from datetime import date
from decimal import Decimal
from matplotlib.ticker import FuncFormatter, MaxNLocator
from .date_display import display_dates
from .chart_style import COLORS, PALETTE, compact_number, currency_axis, date_axis, style_axis, CHART_STYLE


def empty_chart(axis):
    axis.text(0.5, 0.5, 'Für diese Auswahl sind noch keine Daten vorhanden.', ha='center', va='center', color=COLORS['muted'], transform=axis.transAxes, wrap=True)
    axis.set_axis_off()


def bar_chart(axis, pairs, title, percent=False):
    if not pairs:
        empty_chart(axis)
        return
    names, values = zip(*pairs)
    axis.barh(range(len(names)), values, color=[COLORS['red'] if v < 0 else PALETTE[i % len(PALETTE)] for i, v in enumerate(values)], height=0.62)
    axis.set_yticks(range(len(names)), [n[:37] + ('…' if len(n) > 37 else '') for n in names])
    axis.invert_yaxis()
    style_axis(axis, False)
    axis.set_title(title, loc='left', color=COLORS['text'], fontsize=CHART_STYLE['title_fontsize'], fontweight='bold', pad=16)
    axis.xaxis.set_major_formatter(FuncFormatter(lambda v, p: f'{v:.0f} %' if percent else compact_number(v)))
    axis.xaxis.set_major_locator(MaxNLocator(nbins=4))
    axis.grid(axis='x', color=COLORS['grid'], alpha=CHART_STYLE['grid_alpha']) 
    axis.margins(x=0.15)


def _style_params():
    return dict(title_fontsize=CHART_STYLE['title_fontsize'], legend_fontsize=CHART_STYLE['legend_fontsize'],
                line_width=CHART_STYLE['line_width'])


def draw_wealth(figure, data, mode):
    sp = _style_params()
    series = data['series']
    if mode == 0:
        ax, allocation = figure.subplots(1, 2, gridspec_kw={'width_ratios': [1.7, 1]})
        summary = data['summary']
        bar_chart(allocation, sorted(((k, float(v)) for k, v in summary['categories'].items() if v), key=lambda p: -p[1]), 'Vermögensaufteilung')
    else:
        ax = figure.add_subplot(111)
    if not series:
        empty_chart(ax)
    elif mode == 8:
        valid = [r for r in series if r['total'] is not None]
        if not valid:
            empty_chart(ax)
        else:
            dates = [date.fromisoformat(r['date']) for r in valid]
            categories = sorted({k for r in valid for k in r['categories']})
            positive, negative = ([0.0] * len(valid), [0.0] * len(valid))
            for index, category in enumerate(categories):
                values = [float(r['categories'].get(category, 0)) for r in valid]
                upper = [p + max(v, 0) for p, v in zip(positive, values)]
                lower = [p + min(v, 0) for p, v in zip(negative, values)]
                ax.fill_between(dates, positive, upper, step='post', color=PALETTE[index % len(PALETTE)], alpha=CHART_STYLE['stack_alpha'], label=category)
                ax.fill_between(dates, negative, lower, step='post', color=PALETTE[index % len(PALETTE)], alpha=CHART_STYLE['stack_alpha'])
                positive, negative = (upper, lower)
            ax.step(dates, [float(r['total']) for r in valid], where='post', marker='o', markevery=[i for i, r in enumerate(valid) if r.get('observed', True)], linestyle='--', color=COLORS['text'], linewidth=max(1.0, sp['line_width'] - 1.0), label='Nettovermögen')
            style_axis(ax)
            currency_axis(ax)
            date_axis(ax)
            ax.legend(fontsize=sp['legend_fontsize'], frameon=False, labelcolor=COLORS['text'], ncol=3)
            ax.set_title('Vermögensstruktur im Zeitverlauf', color=COLORS['text'], loc='left')
    elif mode == 0:
        valid = [r for r in series if r['total'] is not None]
        if not valid:
            empty_chart(ax)
        else:
            dates = [date.fromisoformat(r['date']) for r in valid]
            values = [float(r['total']) for r in valid]
            ax.step(dates, values, where='post', marker='o', markevery=[i for i, r in enumerate(valid) if r.get('observed', True)], linestyle='--', color=COLORS['blue'], linewidth=sp['line_width'])
            ax.fill_between(dates, values, step='post', alpha=0.1, color=COLORS['blue'])
            currency_axis(ax)
            date_axis(ax)
            style_axis(ax)
            ax.set_title('Gesamtvermögen im Zeitverlauf', loc='left', color=COLORS['text'], fontweight='bold', fontsize=sp['title_fontsize'], pad=16)
            ax.margins(x=0.02)
    else:
        monthly = {}
        for point in series:
            monthly[point['period']] = point
        series = list(monthly.values())
        pairs = []
        for before, after in zip(series, series[1:]):
            ay, am = map(int, after['period'].split('-'))
            by, bm = map(int, before['period'].split('-'))
            if (ay * 12 + am - (by * 12 + bm) == 1
                    and before['total'] is not None and after['total'] is not None):
                pairs.append((after['period'], float(after['total'] - before['total'])))
        bar_chart(ax, pairs[-CHART_STYLE['max_months']:], 'Änderung gegenüber dem Vormonat')
    return 'Quelle: gespeicherte Konto- und Depotstände. Punkte: Datenereignisse; gestrichelt: fortgeführte Werte · inklusive Altersvorsorge, abzüglich Schulden. Wertänderungen enthalten Ein- und Auszahlungen; sie sind keine Rendite.'


def draw_accounts(figure, rows, account):
    if account:
        rows = [r for r in rows if r['name'] == account]
    bar_chart(figure.add_subplot(111), sorted([(r['name'], float(r['balance'] if r['balance'] is not None else r['depot_value'])) for r in rows if r['balance'] is not None or r['depot_value'] is not None], key=lambda p: -p[1]), 'Konten und Depots · letzter bekannter Wert')
    return 'Fehlende Salden werden nicht als null interpretiert. Depotwerte werden nicht zusätzlich addiert.'


def draw_depot_value(figure, rows, as_of):
    sp = _style_params()
    rows = list(rows)
    ax, dd = figure.subplots(2, 1, sharex=True, gridspec_kw={'height_ratios': [2, 1]})
    if rows:
        if as_of != '9999-12-31' and rows[-1]['date'] < as_of:
            rows.append({**rows[-1], 'date': as_of})
        dates = [date.fromisoformat(r['date']) for r in rows]
        values = [float(r['value']) for r in rows]
        peak, drawdown = (0, [])
        for value in values:
            peak = max(peak, value)
            drawdown.append((value / peak - 1) * 100 if peak else 0)
        ax.step(dates, values, where='post', marker='o', color=COLORS['blue'], linewidth=sp['line_width'])
        dd.fill_between(dates, drawdown, color=COLORS['red'], alpha=0.22)
        dd.plot(dates, drawdown, color=COLORS['red'], linewidth=1)
        style_axis(ax)
        style_axis(dd)
        currency_axis(ax)
        date_axis(dd)
        dd.set_ylabel('Rückgang %', color=COLORS['text'], fontsize=CHART_STYLE['axis_label_fontsize'])
        ax.set_title('Depotwert und Abstand zum bisherigen Höchstwert', loc='left', color=COLORS['text'], fontsize=sp['title_fontsize'], fontweight='bold')
    else:
        empty_chart(ax)
        empty_chart(dd)
    return 'Rückgang des Depotwerts, nicht zahlungsstrombereinigt. Entnahmen und Depotwechsel können den Verlauf beeinflussen.'


def draw_positions(figure, positions, mode):
    ax = figure.add_subplot(111)
    if mode == 2:
        bar_chart(ax, sorted([(p['name'], float(p['value'])) for p in positions], key=lambda p: -p[1])[:CHART_STYLE['top_n']], 'Die zehn größten Positionen')
    elif mode == 3:
        pairs = sorted([(p['name'], float(Decimal(p['value']) - Decimal(p['cost']))) for p in positions if p.get('cost') is not None and Decimal(p['cost']) > 0], key=lambda p: -abs(p[1]))[:CHART_STYLE['top_n']]
        bar_chart(ax, pairs, 'Buchgewinne und Verluste · absolut')
        return 'Ohne Positionen mit fehlendem Einstandswert. Ausschüttungen sind nicht enthalten.'
    elif mode == 7:
        values = sorted((float(p['value']) for p in positions if float(p['value']) > 0), reverse=True)
        total = sum(values)
        if not total:
            empty_chart(ax)
        else:
            weights = [v / total * 100 for v in values]
            cumulative = []
            for weight in weights:
                cumulative.append((cumulative[-1] if cumulative else 0) + weight)
            ax.bar(range(1, len(values) + 1), weights, color=COLORS['blue'], label='Einzelgewicht')
            ax.plot(range(1, len(values) + 1), cumulative, color=COLORS['green'], label='Kumuliertes Gewicht')
            style_axis(ax)
            ax.set_ylim(0, 105)
            ax.set_xlabel('Positionen nach Größe', color=COLORS['text'])
            ax.set_ylabel('Depotanteil %', color=COLORS['text'])
            ax.legend(frameon=False, labelcolor=COLORS['text'])
            ax.set_title(f'Top 5: {sum(weights[:5]):.1f} % · Top 10: {sum(weights[:10]):.1f} %', loc='left', color=COLORS['text'])
        return 'Positive Positionswerte; ETF-Einzelbestandteile sind nicht durchgerechnet.'
    else:
        groups = defaultdict(float)
        for p in positions:
            groups[p.get('region') or 'Unbekannt'] += float(p['value'])
        total = sum(groups.values())
        bar_chart(ax, sorted([(k, v / total * 100) for k, v in groups.items()], key=lambda p: -p[1]) if total else [], 'Regionen nach Depotwert', True)
        return 'Hinterlegte Regionen. Die ETF-Durchrechnung ist separat verfügbar.'
    return ''


def draw_price_comparison(figure, data, as_of, carry_prices):
    ax = figure.add_subplot(111)
    series = [{p['date']: p['close'] for p in d.get('prices', []) if p['date'] <= as_of and p['close'] > 0} for d in data]
    if not all(series):
        empty_chart(ax)
        return 'Für den Kursvergleich werden zwei gespeicherte Kurshistorien bis zum gewählten Datum benötigt.'
    observations = [set(values) for values in series]
    if carry_prices:
        days = set(series[0]) | set(series[1])
        if as_of != '9999-12-31':
            days.add(as_of)
        carried = [{}, {}]
        last = [None, None]
        for day in sorted(days):
            for index in (0, 1):
                last[index] = series[index].get(day, last[index])
            if all((value is not None for value in last)):
                for index in (0, 1):
                    carried[index][day] = last[index]
        series = carried
        dates = sorted(series[0])
    else:
        dates = sorted(set(series[0]) & set(series[1]))
    if not dates:
        empty_chart(ax)
        return 'Keine gemeinsamen Handelstage. Zeitraum erweitern oder letzte Kurse ausdrücklich fortführen.'
    for index, (d, values) in enumerate(zip(data, series)):
        ax.plot([date.fromisoformat(day) for day in dates], [100 * values[day] / values[dates[0]] for day in dates], color=PALETTE[index], label=f"{d.get('symbol', '')} · {d.get('currency', '')}", linewidth=1.8, linestyle='--' if carry_prices else '-', drawstyle='steps-post' if carry_prices else 'default', marker='o', markevery=[i for i, day in enumerate(dates) if day in observations[index]][::max(1, len(dates) // 50)])
    style_axis(ax)
    date_axis(ax)
    ax.axhline(100, color=COLORS['muted'], linewidth=0.7)
    ax.set_ylabel('Startwert = 100', color=COLORS['text'])
    ax.legend(frameon=False, labelcolor=COLORS['text'])
    sources = ', '.join(sorted({str(d.get('source_url') or d.get('provider') or 'Gespeicherte Kurshistorie') for d in data}))
    return display_dates(f"{dates[0]} bis {dates[-1]} · {('Gestrichelt: fortgeschriebene Kurse; Punkte: Beobachtungen' if carry_prices else 'Gemeinsame Handelstage; nur beobachtete Schlusskurse')}. Originalwährung, ohne Wechselkursbereinigung oder Ausschüttungen. Quelle: {sources}.")
