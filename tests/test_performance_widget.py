import os

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from portfolio_v5.models import ImportBatch, Snapshot, Position
from portman.repository_v09 import RepositoryV09
from portman.performance_widget import PerformanceWidget


def nav_repo(tmp_path):
    repo = RepositoryV09(tmp_path / 'nav.sqlite', backups=False)
    snapshots = [Snapshot('NAV', day[:7], day, 'test', [Position('X', 'X', quantity='1',
                 value=value, currency='EUR')])
                 for day, value in [('2026-01-01', '100'), ('2026-02-01', '90'), ('2026-03-05', '108')]]
    repo.commit_batches([ImportBatch('nav', 'nav', snapshots=snapshots)])
    return repo


def test_risk_cards_show_dip_metrics(qtbot, tmp_path):
    repo = nav_repo(tmp_path)
    try:
        widget = PerformanceWidget(repo, lambda: 'NAV')
        qtbot.addWidget(widget)
        assert widget.labels['volatility'].text() != '–'
        assert widget.labels['semivolatility'].text() != '–'
        assert widget.labels['drawdown'].text() == '-10,00 %'
        assert widget.labels['drawdown_current'].text() == '–'  # recovered to a new high
        assert widget.labels['drawdown_duration'].text().endswith('Tage')
        assert 'font-weight:700' in widget.labels['drawdown'].styleSheet()
        assert 'nicht berechenbar' not in widget.note.text()
    finally:
        repo.close()


def test_empty_account_shows_dashes(qtbot, tmp_path):
    repo = RepositoryV09(tmp_path / 'empty.sqlite', backups=False)
    try:
        widget = PerformanceWidget(repo, lambda: 'Leer')
        qtbot.addWidget(widget)
        assert widget.current_result is None
        assert all(label.text() == '–' for label in widget.labels.values())
        assert 'Keine historischen Bewertungen' in widget.quality.text()
    finally:
        repo.close()


def test_single_valuation_marks_all_cards_uncomputable(qtbot, tmp_path):
    repo = RepositoryV09(tmp_path / 'single.sqlite', backups=False)
    repo.commit_batches([ImportBatch('one', 'one', snapshots=[
        Snapshot('NAV', '2026-01', '2026-01-01', 'test',
                 [Position('X', 'X', quantity='1', value='100', currency='EUR')])])])
    try:
        widget = PerformanceWidget(repo, lambda: 'NAV')
        qtbot.addWidget(widget)
        assert widget.current_result.get('error')
        assert all(label.text() == 'nicht berechenbar' for label in widget.labels.values())
    finally:
        repo.close()


def test_daily_index_overlay_follows_checkbox(qtbot, tmp_path):
    repo = nav_repo(tmp_path)
    try:
        widget = PerformanceWidget(repo, lambda: 'NAV')
        qtbot.addWidget(widget)
        assert widget.chart_checks['daily'].isChecked() is False
        widget.draw_chart()
        labels = [line.get_label() for axis in widget.fig.axes for line in axis.get_lines()]
        assert 'Tagesindex (Bewertung)' not in labels

        widget.chart_checks['daily'].setChecked(True)
        widget.draw_chart()
        twr_axis = widget.fig.axes[1]
        daily_lines = [line for line in twr_axis.get_lines()
                       if line.get_label() == 'Tagesindex (Bewertung)']
        assert len(daily_lines) == 1
        assert len(daily_lines[0].get_xdata()) == len(widget.current_result['daily_index'])
    finally:
        repo.close()


def test_benchmark_selection_fills_cards_and_overlay(qtbot, tmp_path):
    repo = nav_repo(tmp_path)
    from datetime import date, timedelta
    day, end = date(2026, 1, 1), date(2026, 3, 5)
    prices = []
    close = 250.0
    while day <= end:
        prices.append({'date': day.isoformat(), 'close': close})
        close *= 1.0007
        day += timedelta(days=1)
    repo.market.save_result(dict(security_key='BMK', status='ok', attempted_at='2026-01-01',
        message='OK', symbol='IDX', currency='EUR', prices=prices))
    try:
        widget = PerformanceWidget(repo, lambda: 'NAV')
        qtbot.addWidget(widget)
        assert widget.benchmark_combo.findText('IDX') >= 0
        assert widget.labels['benchmark'].text() == '–'

        widget.benchmark_combo.setCurrentText('IDX')
        assert widget.labels['benchmark'].text().startswith('IDX:')
        assert widget.labels['active'].text() != '–'
        assert widget.labels['tracking'].text() != '–'
        lines = [line.get_label() for axis in widget.fig.axes for line in axis.get_lines()]
        assert 'Benchmark' in lines
        assert 'Benchmark IDX' in widget.note.text()
    finally:
        repo.close()
