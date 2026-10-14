import os
from decimal import Decimal
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtWidgets import QApplication
from portman.repository import PortfolioRepository
from portfolio_v5.models import ImportBatch, Balance, Snapshot, Position
from portman.visualization_data import wealth_at, wealth_history
from portman.visualizations import VisualizationsWidget


def test_visuals_carry_cash_and_depots_to_arbitrary_date(tmp_path, qtbot):
    QApplication.instance() or QApplication([])
    repo = PortfolioRepository(tmp_path / 'db.sqlite')
    widget = None
    try:
        repo.commit_batches([ImportBatch('cash', 'cash', source_sheet='Online ING', balances=[
            Balance('2026-01', 'Liquidität', 'Cash', '100', 'Online ING · 2026-01-05', 1)])])
        for day, value in [('2026-01-10', '200'), ('2026-03-20', '900')]:
            repo.commit_batches([ImportBatch(day, day, snapshots=[
                Snapshot('Depot', day[:7], day, 'ING', [Position('A', 'Aktie', value=value)])])])
        assert wealth_at(repo, '2026-03-15')['total'] == Decimal('300')
        points = wealth_history(repo, '2026-03-15')
        assert points[-1]['date'] == '2026-03-15'
        assert points[-1]['total'] == Decimal('300')
        assert any(p['date'] == '2026-02-28' for p in points)
        assert wealth_at(repo, '2026-03-15', 'Depot')['total'] == Decimal('200')
        assert wealth_at(repo, '2025-12-31')['total'] is None
        widget = VisualizationsWidget(repo, lambda: (None, '2026-03-15'))
        for mode in (0, 1, 2, 5, 6, 8):
            widget.view.setCurrentIndex(mode)
            widget.refresh()
            qtbot.waitUntil(lambda: widget.chart_loader.worker is None, timeout=10000)
            assert widget.fig.axes, widget.note.text()
            widget.canvas.draw()
            assert not any('keine Daten' in text.get_text() for ax in widget.fig.axes for text in ax.texts)
        widget.view.setCurrentIndex(1)
        qtbot.waitUntil(lambda: widget.chart_loader.worker is None, timeout=10000)
        assert sorted(p.get_width() for p in widget.fig.axes[0].patches) == [100, 200]
    finally:
        if widget: widget.close()
        repo.close()


def test_price_comparison_carries_different_trading_days():
    from types import SimpleNamespace
    QApplication.instance() or QApplication([])
    records = {key: {'data': {'symbol': key, 'currency': 'EUR', 'prices': [{'date': day, 'close': value}]}}
               for key, day, value in [('A', '2026-03-12', 100), ('B', '2026-03-13', 200)]}
    repo = SimpleNamespace(market=SimpleNamespace(records=lambda: records),
                           current=lambda *args: [{'key': key, 'name': key} for key in records])
    widget = VisualizationsWidget(repo, lambda: (None, '2026-03-15'))
    try:
        widget.view.setCurrentIndex(9)
        widget.carry_prices.setChecked(True)
        widget.canvas.draw()
        for line in widget.fig.axes[0].lines[:2]:
            assert line.get_xdata()[-1].isoformat() == '2026-03-15'
            assert list(line.get_ydata()) == [100, 100]
    finally: widget.close()


def test_history_cache_reuses_data_and_invalidates(tmp_path, monkeypatch):
    from portman import visualization_data
    repo = PortfolioRepository(tmp_path / 'cache.sqlite')
    other = None
    try:
        repo.save_account('Cash', {'kind': 'Girokonto'}, None)
        repo.add_balance('Cash', '100', '2026-01-01')
        calls = []
        original = visualization_data.wealth_at
        def counted(*args):
            calls.append(args[1])
            return original(*args)
        monkeypatch.setattr(visualization_data, 'wealth_at', counted)
        first = wealth_history(repo, '2026-02-01')
        count = len(calls)
        first[-1]['categories'].clear()
        assert wealth_history(repo, '2026-02-01')[-1]['categories']
        assert len(calls) == count
        repo.add_balance('Cash', '200', '2026-01-15')
        assert wealth_history(repo, '2026-02-01')[-1]['total'] == Decimal('200')
        other = PortfolioRepository(tmp_path / 'cache.sqlite')
        other.add_balance('Cash', '300', '2026-01-20')
        assert wealth_history(repo, '2026-02-01')[-1]['total'] == Decimal('300')
        repo.db.execute('BEGIN')
        repo.db.execute("UPDATE manual_balances SET value='400'")
        assert wealth_history(repo, '2026-02-01')[-1]['total'] == Decimal('400')
        repo.db.rollback()
        assert wealth_history(repo, '2026-02-01')[-1]['total'] == Decimal('300')
    finally:
        if other: other.close()
        repo.close()


def test_crypto_without_market_prices_can_open_charts(tmp_path, qtbot):
    from portman.performance_service import PerformanceService
    from portman.performance_widget import PerformanceWidget
    QApplication.instance() or QApplication([])
    repo = PortfolioRepository(tmp_path / 'unpriced.sqlite')
    widgets = []
    try:
        repo.commit_batches([ImportBatch('wallet', 'wallet', snapshots=[
            Snapshot('Wallet', '2026-10', '2026-10-07', 'Krypto Wallet CSV', [
                Position('BTC', 'Bitcoin', asset_type='Krypto', quantity='1', cost='100', value=None)])])])
        assert PerformanceService(repo).valuation_series('Wallet') == []
        widget = VisualizationsWidget(repo, lambda: ('Wallet', '2026-10-07'))
        widgets.append(widget)
        widget.view.setCurrentIndex(5)
        widget.refresh()
        qtbot.waitUntil(lambda: widget.chart_loader.worker is None, timeout=10000)
        widget.canvas.draw()
        widgets.append(PerformanceWidget(repo, lambda: 'Wallet'))
    finally:
        for widget in widgets: widget.close()
        repo.close()
def test_latest_wealth_history_uses_today_without_local_date_shadowing(tmp_path):
    from portman.repository_v09 import RepositoryV09
    repo = RepositoryV09(tmp_path / 'latest.sqlite', backups=False)
    try:
        repo.save_account('Cash', {'kind': 'Girokonto'})
        repo.add_balance('Cash', '100', '2026-01-01')
        history = wealth_history(repo, '9999-12-31')
        assert history[-1]['total'] == Decimal('100')
    finally:
        repo.close()


