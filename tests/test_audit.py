import os
import sqlite3
from decimal import Decimal
from unittest.mock import patch
import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from portfolio_v5.models import ImportBatch, Snapshot, Position, Balance
from portfolio_v5.importers import parse_deka
from portman.repository import PortfolioRepository
from portman.performance_service import PerformanceService


def batch(depot='Deka/1', cost='80', value='100'):
    return ImportBatch(depot, depot, snapshots=[Snapshot(depot, '2026-01', '2026-01-31', 'DEKA',
        [Position('DE0000000001', 'Titel', isin='DE0000000001', quantity='1', cost=cost, value=value)])])


def test_deka_first_block_not_repeated_heading():
    rows = [['ISIN', 'DE0000000001'], ['Unterdepot', 1], ['Bestand', 3], ['Wert', 100],
            ['Bewertungsdatum', '2026-01-31'], ['Unterdepot', 'Bestand in Stück']]
    parsed = parse_deka(rows, 'DEKA', '2026-01')
    assert [s.account for s in parsed] == ['Deka/1']
    assert parsed[0].positions[0].value == '100.00'


def test_duplicate_migration_preserves_raw_data_and_real_depots(tmp_path):
    path = tmp_path / 'db.sqlite'; r = PortfolioRepository(path)
    r.commit_batches([batch(), batch('Deka/Bestand'), batch('Deka/2', value='200')])
    with r.db: r.db.execute("DELETE FROM meta WHERE key='deka_heading_duplicates_corrected_v1'")
    r.close(); r = PortfolioRepository(path)
    assert r.db.execute('SELECT COUNT(*) FROM snapshots').fetchone()[0] == 3
    assert r.db.execute('SELECT COUNT(*) FROM snapshot_exclusions').fetchone()[0] == 1
    assert sum(Decimal(p['value']) for p in r.current()) == 300
    assert len(r.depots()) == 2
    r.close(); r = PortfolioRepository(path)
    assert r.db.execute('SELECT COUNT(*) FROM snapshot_exclusions').fetchone()[0] == 1
    r.close()


def test_cache_invalidates_local_external_and_rollback(tmp_path):
    r = PortfolioRepository(tmp_path / 'db.sqlite'); r.commit_batches([batch()])
    r.current()[0]['value'] = '999'
    assert r.current()[0]['value'] == '100'
    r.set_account_active('Deka', False); assert r.current() == []
    r.set_account_active('Deka', True); assert len(r.current()) == 1
    r.db.execute("UPDATE accounts SET active=0 WHERE name='Deka'")
    assert r.current() == []
    r.db.rollback(); assert len(r.current()) == 1
    with sqlite3.connect(r.store.path) as other:
        other.execute("UPDATE accounts SET active=0 WHERE name='Deka'")
    assert r.current() == []
    r.close()


def test_unknown_cost_does_not_inflate_gain(tmp_path):
    r = PortfolioRepository(tmp_path / 'db.sqlite')
    r.commit_batches([batch(), batch('Deka/2', cost=None)])
    assert r.current()[0]['cost'] is None
    result = PerformanceService(r).overview()
    assert result['pnl'] == 0 and result['pnl_pct'] is None
    assert not result['cost_complete']
    r.close()


def test_preview_compares_raw_depot_after_mapping(tmp_path):
    r = PortfolioRepository(tmp_path / 'db.sqlite')
    r.commit_batches([batch(), batch('Deka/2', value='200')])
    r.create_accounts(['Ziel']); r.assign_depot('Deka/1', 'Ziel')
    result = r.preview_summary(batch())
    assert result['new'] == result['changed'] == result['missing'] == 0
    r.close()


@pytest.fixture
def qt_app():
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app
    app.processEvents()


def test_all_charts_and_empty_account_clear(qt_app, tmp_path, qtbot):
    from portman.visualizations import VisualizationsWidget
    from portman.performance_widget import PerformanceWidget
    r = PortfolioRepository(tmp_path / 'db.sqlite'); b = batch()
    b.balances = [Balance('2026-01', 'Liquidität', 'Deka', '100', 'ETF', 2)]
    r.commit_batches([b]); scope = [None, '2026-12-31']
    charts = VisualizationsWidget(r, lambda: tuple(scope))
    for view in range(len(charts.VIEWS)):
        charts.view.setCurrentIndex(view); charts.refresh()
        qtbot.waitUntil(lambda: charts.chart_loader.worker is None, timeout=10000)
        charts.canvas.draw()
        assert charts.fig.axes
    perf = PerformanceWidget(r, lambda: scope[0])
    assert perf.comparison.rowCount() > 0
    scope[0] = 'Leer'; perf.refresh()
    assert perf.comparison.rowCount() == 0 and perf.current_result is None
    assert all(label.text() == '–' for label in perf.labels.values())
    for view in range(len(charts.VIEWS)):
        charts.view.setCurrentIndex(view); charts.refresh()
        qtbot.waitUntil(lambda: charts.chart_loader.worker is None, timeout=10000)
        charts.canvas.draw()
    charts.close(); perf.close(); qt_app.processEvents(); r.close()


def test_quote_comparison_uses_common_dates_and_original_currencies(qt_app, tmp_path, qtbot):
    from portman.visualizations import VisualizationsWidget
    r = PortfolioRepository(tmp_path / 'db.sqlite'); r.commit_batches([batch()])
    data = {'DE0000000001': {'data': {'symbol': 'ABC', 'currency': 'USD',
            'prices': [{'date': '2026-02-01', 'close': 20}, {'date': '2026-02-02', 'close': 30}]}}}
    from portman.market_data import MarketDataStore
    with patch.object(MarketDataStore, 'records', return_value=data):
        charts = VisualizationsWidget(r, lambda: (None, '2026-12-31'))
        charts.view.setCurrentIndex(9); charts.refresh()
        qtbot.waitUntil(lambda: charts.chart_loader.worker is None, timeout=10000)
        assert list(charts.fig.axes[0].lines[0].get_ydata()) == [100, 150]
        assert 'Originalwährung' in charts.note.text()
        charts.close(); qt_app.processEvents()
    r.close()


def test_import_worker_catches_unreadable_file(qt_app, tmp_path):
    from portman.import_worker import ImportWorker
    worker = ImportWorker([tmp_path / 'missing.xlsx']); results = []
    worker.parsed.connect(results.extend); worker.start()
    assert worker.wait(5000)
    qt_app.processEvents()
    assert len(results) == 1 and results[0].errors


def test_import_worker_discovers_pdf_plugins_once_per_bulk_job(qt_app, tmp_path, monkeypatch):
    from portman import import_worker as worker_module
    from portfolio_v5 import pdf_plugins
    calls, catalogs = [], []
    catalog = ([object()], [])

    def discover():
        calls.append(True)
        return catalog

    def parse(path, **options):
        catalogs.append(options['plugin_catalog'])
        return ImportBatch(str(path), str(path))

    monkeypatch.setattr(pdf_plugins, 'discover_plugins', discover)
    monkeypatch.setattr(worker_module, 'parse_file', parse)
    worker = worker_module.ImportWorker([tmp_path / 'one.pdf', tmp_path / 'two.pdf'])
    results = []
    worker.parsed.connect(results.extend)
    worker.start()
    assert worker.wait(5000)
    qt_app.processEvents()

    assert len(calls) == 1
    assert catalogs == [catalog, catalog]
    assert len(results) == 2


def test_market_worker_cancel_stops_before_second_security(qt_app):
    from portman.market_widget import MarketWorker
    worker = MarketWorker([{'key': 'A', 'name': 'A'}, {'key': 'B', 'name': 'B'}], {})
    observations = []
    def fetch(position, mapping):
        worker.requestInterruption()
        return {'security_key': position['key'], 'status': 'mapping_needed'}
    worker.observation.connect(observations.append)
    with patch('portman.online_providers.YahooMarketProvider.fetch', side_effect=fetch), patch('portman.valuation.fetch_fx', side_effect=ValueError):
        worker.start(); assert worker.wait(5000)
    qt_app.processEvents()
    assert [r['security_key'] for r in observations] == ['A']
