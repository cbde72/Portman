from datetime import datetime, timezone
import pytest
from portfolio_v5.models import ImportBatch, Snapshot, Position
from portman.repository_v09 import RepositoryV09
from portman.price_history import historical_positions, history_plan, missing_ranges, save_history, stored_history
from portman.market_data import YahooMarketProvider


@pytest.fixture
def repo(tmp_path):
    result = RepositoryV09(tmp_path / 'history.sqlite', backups=False)
    result.commit_batches([ImportBatch('old', 'old', snapshots=[
        Snapshot('Depot A', '2012-01', '2012-01-01', 'Test', [Position('A', 'Aktie A', quantity='1', value='100')]),
        Snapshot('Depot B', '2013-01', '2013-01-01', 'Test', [Position('A', 'Aktie A', quantity='2', value='200')]),
        Snapshot('Depot A', '2014-01', '2014-01-01', 'Test', [])])])
    result.market.set_feed('A', 'yahoo', 'ABC', 'EUR')
    yield result
    result.close()


def save(repo, start='2012-01-01', end='2012-01-10', **extra):
    data = dict(security_key='A', status='ok', attempted_at='2026-10-08', message='OK', symbol='ABC', currency='EUR',
        history_start=start, history_end=end, prices=[{'date': start, 'close': 100}, {'date': end, 'close': 101}])
    data.update(extra)
    return save_history(repo, data, repo.market.mappings()['A'])


def test_first_holding_including_sold_and_duplicate_depots(repo):
    assert historical_positions(repo)[0]['history_start'] == '2012-01-01'
    assert len(historical_positions(repo)) == 1
    assert historical_positions(repo, 'Depot B')[0]['history_start'] == '2013-01-01'
    assert historical_positions(repo, 'Depot A')[0]['key'] == 'A'


def test_cache_survives_restart_and_only_fetches_missing_edges(repo):
    save(repo)
    p = historical_positions(repo)
    assert history_plan(repo, p, end='2012-01-10') == []
    tasks = history_plan(repo, p, end='2012-01-15')
    assert [(t['history_start'], t['history_end']) for t in tasks] == [('2012-01-11', '2012-01-15')]
    other = RepositoryV09(repo.store.path, backups=False)
    try:
        assert len(stored_history(other, 'A', '2012-01-01')['prices']) == 2
        assert history_plan(other, p, end='2012-01-10') == []
    finally: other.close()
    assert history_plan(repo, p, end='2012-01-10', force=True)[0]['history_start'] == '2012-01-01'


def test_earlier_import_extends_history_without_redownloading(repo):
    save(repo)
    p = [{**historical_positions(repo)[0], 'history_start': '2011-12-01'}]
    assert [(t['history_start'], t['history_end']) for t in history_plan(repo, p, end='2012-01-10')] == [('2011-12-01', '2011-12-31')]


def test_empty_weekend_is_cached_errors_keep_prices_and_mapping_isolated(repo):
    save(repo)
    save(repo, '2012-01-11', '2012-01-12', prices=[])
    assert not history_plan(repo, historical_positions(repo), end='2012-01-12')
    save(repo, status='error', message='Netzwerkfehler', prices=[])
    assert len(stored_history(repo, 'A', '2012-01-01')['prices']) == 2
    repo.market.set_feed('A', 'yahoo', 'OTHER', 'USD')
    assert stored_history(repo, 'A', '2012-01-01')['prices'] == []
    assert history_plan(repo, historical_positions(repo), end='2012-01-10')
    repo.market.set_feed('A', 'yahoo', 'ABC', 'EUR')
    assert len(stored_history(repo, 'A', '2012-01-01')['prices']) == 2


def test_overlapping_intervals_merge():
    assert missing_ranges('2020-01-01', '2020-01-31', [('2020-01-05', '2020-01-12'), ('2020-01-10', '2020-01-20')]) == [
        ('2020-01-01', '2020-01-04'), ('2020-01-21', '2020-01-31')]


def test_provider_requests_exact_dates_without_requiring_current_quote():
    urls = []
    def transport(url):
        urls.append(url)
        return {'chart': {'result': [{'meta': {'symbol': 'ABC', 'currency': 'EUR'},
            'timestamp': [1325462400], 'indicators': {'quote': [{'close': [42]}]}}]}}
    result = YahooMarketProvider(transport).fetch({'key': 'A', 'name': 'A', '_history_request': True,
        'history_start': '2012-01-01', 'history_end': '2012-01-10'}, {'symbol': 'ABC'})
    assert result['status'] == 'ok'
    assert 'period1=1325376000' in urls[0] and 'period2=1326240000' in urls[0]
    assert 'range=' not in urls[0]


def test_history_dialog_does_not_fetch_on_open_and_has_all_past_positions(repo, qapp, monkeypatch):
    from portman.price_history_dialog import PriceHistoryDialog
    from portman import market_widget
    monkeypatch.setattr(market_widget.MarketWorker, 'start', lambda self: pytest.fail('Unexpected network worker'))
    dialog = PriceHistoryDialog(repo)
    assert len(dialog.positions) == 1
    save(repo, end=(datetime.now(timezone.utc).date()).isoformat())
    dialog.start()
    assert 'Kein Internetabruf' in dialog.status.text()
    dialog.reject()


def test_visual_refresh_reuses_axes_and_updates_after_write(repo, qapp, qtbot):
    from portman.visualizations import VisualizationsWidget
    widget = VisualizationsWidget(repo, lambda: (None, '2013-01-01'))
    widget.view.setCurrentIndex(2)
    widget.refresh()
    qtbot.waitUntil(lambda: widget.chart_loader.worker is None, timeout=10000)
    assert widget.fig.axes, widget.note.text()
    first = widget.fig.axes[0]
    widget.refresh()
    assert widget.fig.axes[0] is first
    repo.add_balance('Depot A', '100', '2013-01-01')
    widget.refresh()
    qtbot.waitUntil(lambda: widget.chart_loader.worker is None, timeout=10000)
    assert widget.fig.axes[0] is not first
    widget.close()


def test_monthly_carry_does_not_recalculate_every_month(repo, monkeypatch):
    from portman import visualization_data
    calls = []
    original = visualization_data.wealth_at
    def counted(*args):
        calls.append(args[1]); return original(*args)
    monkeypatch.setattr(visualization_data, 'wealth_at', counted)
    series = visualization_data.wealth_history(repo, '2026-10-07')
    assert len(series) > 150
    assert len(calls) <= 4


def test_regular_quotes_extend_archive_without_erasing_older_prices(repo):
    save(repo)
    repo.market.save_result(dict(security_key='A', status='ok', attempted_at='2026-10-08', message='OK', symbol='ABC', currency='EUR',
        metrics={'price': 123}, prices=[{'date': '2020-01-02', 'close': 123}]))
    assert [p['date'] for p in stored_history(repo, 'A', '2012-01-01')['prices']] == ['2012-01-01', '2012-01-10', '2020-01-02']


def test_worker_stores_prices_and_offline_reopen(repo, qtbot, monkeypatch):
    from portman.price_history_dialog import PriceHistoryDialog
    from portman.market_widget import MarketProvider, MarketWorker
    calls = []
    def fetch(self, p, mapping):
        calls.append(p['key'])
        return dict(security_key=p['key'], attempted_at='2026-10-08', status='ok', message='OK', symbol='ABC', currency='EUR',
            prices=[{'date': p['history_start'], 'close': 100}])
    monkeypatch.setattr(MarketProvider, 'fetch', fetch)
    monkeypatch.setattr(MarketWorker, 'last_request', {})
    dialog = PriceHistoryDialog(repo)
    dialog.start()
    qtbot.waitUntil(lambda: dialog.load.isEnabled(), timeout=5000)
    assert calls == ['A']
    assert len(dialog.saved['A']['prices']) == 1
    dialog.start()
    assert calls == ['A']
    dialog.reject()


def test_long_twelve_data_requests_are_split_below_provider_row_limit(repo):
    repo.market.set_feed('A', 'twelvedata', 'ABC', 'EUR')
    tasks = history_plan(repo, historical_positions(repo), end='2026-10-07')
    assert len(tasks) == 2
    assert tasks[0]['history_start'] == '2012-01-01'
    assert tasks[-1]['history_end'] == '2026-10-07'


def test_first_activity_override_per_depot_and_reset(repo):
    from portman.price_history import save_first_activity
    save_first_activity(repo, 'Depot B', 'A', '2010-02-03')
    assert historical_positions(repo, 'Depot B')[0]['history_start'] == '2010-02-03'
    assert historical_positions(repo)[0]['history_start'] == '2010-02-03'
    other = RepositoryV09(repo.store.path, backups=False)
    try:
        assert historical_positions(other, 'Depot B')[0]['history_start'] == '2010-02-03'
    finally:
        other.close()
    assert historical_positions(repo, 'Depot A')[0]['history_start'] == '2012-01-01'
    assert history_plan(repo, historical_positions(repo), end='2010-02-04')[0]['history_start'] == '2010-02-03'
    save_first_activity(repo, 'Depot B', 'A', '')
    assert historical_positions(repo, 'Depot B')[0]['history_start'] == '2013-01-01'


def test_truncated_history_does_not_cache_missing_years(repo):
    save(repo, start='2010-01-01', end='2014-01-01', prices=[{'date':'2012-01-02','close':100}])
    ranges = history_plan(repo, [{**historical_positions(repo)[0], 'history_start':'2010-01-01'}], end='2014-01-01')
    assert [(p['history_start'], p['history_end']) for p in ranges] == [('2010-01-01','2012-01-01'), ('2012-01-03','2014-01-01')]


def test_purchase_precedes_statement_and_manual_date_wins(repo):
    from portfolio_v5.models import Transaction
    from portman.price_history import save_first_activity
    repo.commit_batches([ImportBatch('purchase', 'purchase', transactions=[
        Transaction('Depot A', 'buy-a', '2010-03-04', 'BUY', '-100', 'EUR', 'A', '1')])])
    assert historical_positions(repo, 'Depot A')[0]['history_start'] == '2010-03-04'
    assert historical_positions(repo, 'Depot B')[0]['history_start'] == '2013-01-01'
    save_first_activity(repo, 'Depot A', 'A', '2011-05-06')
    assert historical_positions(repo, 'Depot A')[0]['history_start'] == '2011-05-06'


def test_purchase_without_statement_is_included(repo):
    from portfolio_v5.models import Transaction
    repo.commit_batches([ImportBatch('new-purchase', 'new-purchase', transactions=[
        Transaction('Depot A', 'buy-b', '2011-02-03', 'BUY', '-100', 'EUR', 'B', '1')])])
    positions = {p['key']: p for p in historical_positions(repo, 'Depot A')}
    assert positions['B']['history_start'] == '2011-02-03'
