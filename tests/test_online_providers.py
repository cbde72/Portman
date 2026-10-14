import json
import os
import sqlite3
import urllib.error
from unittest.mock import patch

import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from portman.market_data import MarketDataStore
from portman.online_credentials import CredentialStore, protect_windows
from portman.online_providers import MarketProvider, DivvyDiaryProvider, ProviderError, request_json

POSITION = {'key': 'US0378331005', 'isin': 'US0378331005', 'name': 'Apple'}
MAPPING = {'symbol': 'AAPL', 'currency': 'USD'}
SECRET = 'test-private-api-key'


@pytest.fixture
def store():
    db = sqlite3.connect(':memory:'); db.row_factory = sqlite3.Row
    result = MarketDataStore(db)
    yield result
    db.close()


@pytest.mark.parametrize('provider,payload,mapping,price', [
    ('alphavantage', {'Meta Data': {'2. Symbol': 'AAPL'}, 'Time Series (Daily)': {
        '2026-01-02': {'4. close': '100'}, '2026-01-05': {'4. close': '110'}}}, MAPPING, 110),
    ('eodhd', [{'date': '2026-01-05', 'close': 110, 'adjusted_close': 109},
               {'date': '2026-01-02', 'close': 100, 'adjusted_close': 99}], {'symbol': 'AAPL.US', 'currency': 'USD'}, 110),
    ('twelvedata', {'meta': {'symbol': 'AAPL', 'currency': 'USD', 'mic_code': 'XNAS', 'exchange': 'NASDAQ'},
                    'values': [{'datetime': '2026-01-05', 'close': '110'}, {'datetime': '2026-01-02', 'close': '100'}]},
                   {**MAPPING, 'exchange': 'XNAS'}, 110),
    ('finnhub', {'c': 110, 'pc': 100, 't': 1767628800}, MAPPING, 110),
    ('kraken', {'error': [], 'result': {'XXBTZUSD': [[1767312000, 0, 0, 0, '100'],
                                                   [1767571200, 0, 0, 0, '110'],
                                                   [1767657600, 0, 0, 0, '999']], 'last': 1767657600}},
                {'symbol': 'XBTUSD', 'currency': 'USD'}, 110),
])
def test_provider_adapters_and_secret_free_results(provider, payload, mapping, price):
    calls = []
    def transport(url, headers):
        calls.append((url, headers)); return payload
    result = MarketProvider(provider, SECRET, transport).fetch(POSITION, mapping)
    assert result['status'] == 'ok', result
    assert result['currency'] == 'USD' and result['metrics']['price'] == price
    assert SECRET not in json.dumps(result)
    assert len(calls) == 1
    if provider == 'finnhub':
        assert '/quote?' in calls[0][0]
        assert calls[0][1]['X-Finnhub-Token'] == SECRET
        assert result['prices'] == []
        assert 'return_1y_pct' not in result['metrics']
    else:
        assert result['quote_time'] == '2026-01-05'
        assert [p['date'] for p in result['prices']] == ['2026-01-02', '2026-01-05']
        assert result['metrics']['return_1y_pct'] is None
    if provider == 'alphavantage': assert 'outputsize=compact' in calls[0][0]
    if provider == 'twelvedata': assert 'mic_code=XNAS' in calls[0][0] and 'adjust=none' in calls[0][0]


@pytest.mark.parametrize('provider', ['alphavantage','eodhd','finnhub','twelvedata'])
def test_missing_key_or_mapping_does_not_call_network(provider):
    def transport(*_): raise AssertionError('Unexpected network request')
    result = MarketProvider(provider, transport=transport).fetch(POSITION, MAPPING)
    assert result['status'] == 'error' and result['stop_provider']
    result = MarketProvider(provider, SECRET, transport).fetch(POSITION, {})
    assert result['status'] == 'mapping_needed'


@pytest.mark.parametrize('provider,payload', [
    ('alphavantage', {'Note': 'Rate limit ' + SECRET}),
    ('twelvedata', {'status': 'error', 'code': 429, 'message': SECRET}),
    ('eodhd', {'error': SECRET}),
    ('finnhub', {'error': SECRET}),
    ('kraken', {'error': ['EAPI:Rate limit ' + SECRET]}),
])
def test_provider_error_bodies_are_not_persisted(provider, payload):
    result = MarketProvider(provider, SECRET, lambda *_: payload).fetch(POSITION, MAPPING)
    assert result['status'] == 'error' and SECRET not in json.dumps(result)


def test_twelve_data_checks_identity_and_currency():
    for meta in [{'symbol': 'OTHER', 'currency': 'USD'}, {'symbol': 'AAPL', 'currency': 'EUR'},
                 {'symbol': 'AAPL', 'currency': 'USD', 'mic_code': 'OTHER'}]:
        result = MarketProvider('twelvedata', SECRET, lambda *_: {
            'meta': meta, 'values': [{'datetime': '2026-01-05', 'close': '110'}]}).fetch(POSITION, {**MAPPING, 'exchange': 'XNAS'})
        assert result['status'] == 'error'


def test_invalid_response_does_not_create_zero_quote():
    for payload in [[], [{'date': '2026-01-05', 'close': 0}], [{'date': 'invalid', 'close': 123}],
                    [{'date': '2026-01-05', 'close': 'nan'}]]:
        result = MarketProvider('eodhd', SECRET, lambda *_: payload).fetch(POSITION, MAPPING)
        assert result['status'] == 'error' and 'metrics' not in result


def dividend_result(payload=None):
    if payload is None:
        payload = {'isin': POSITION['isin'], 'dividends': [{'exDate': '2026-09-01', 'payDate': '2026-09-10',
                                                          'amount': .12345, 'currency': 'USD'}]}
    return DivvyDiaryProvider(SECRET, lambda *_: payload).fetch(POSITION)


def test_dividends_keep_precision_and_are_not_transactions(store):
    result = dividend_result()
    assert result['status'] == 'ok'
    assert result['events'][0]['amount'] == '0.12345'
    assert SECRET not in json.dumps(result)
    store.save_dividends(result)
    good = store.dividends()[POSITION['key']]['data']
    assert good['events'][0]['currency'] == 'USD'
    failed = dividend_result({'error': SECRET})
    store.save_dividends(failed)
    current = store.dividends()[POSITION['key']]
    assert current['data'] == good and current['attempt']['status'] == 'error'
    store.save_dividends(dividend_result({'dividends': []}))
    assert store.dividends()[POSITION['key']]['data']['events'] == []
    assert store.db.execute('SELECT COUNT(*) FROM dividend_observations').fetchone()[0] == 3
    assert not store.records()


def test_dividend_empty_key_invalid_isin_bad_amount():
    assert DivvyDiaryProvider().fetch(POSITION)['status'] == 'error'
    assert DivvyDiaryProvider(SECRET).fetch({'key': 'foo'})['status'] == 'mapping_needed'
    for amount in ['NaN', '-1', 'Infinity']:
        result = dividend_result({'dividends': [{'exDate': '2026-09-01', 'amount': amount, 'currency': 'USD'}]})
        assert result['status'] == 'error'
    assert dividend_result({'isin': 'OTHER', 'dividends': []})['status'] == 'error'


def test_history_mapping_changes_and_failed_updates(store):
    store.set_feed(POSITION['key'], 'eodhd', 'AAPL.US', 'USD')
    for price in [100, 110]:
        result = MarketProvider('eodhd', SECRET, lambda *_: [{'date': '2026-01-05', 'close': price}]).fetch(POSITION, {'symbol': 'AAPL.US', 'currency': 'USD'})
        store.save_result(result)
    assert [r['metrics']['price'] for r in store.observation_history(POSITION['key'])] == [110, 100]
    store.save_result({**result, 'status': 'error', 'message': 'Failed'})
    assert store.records()[POSITION['key']]['data']['metrics']['price'] == 110
    store.set_feed(POSITION['key'], 'twelvedata', 'AAPL', 'USD', 'XNAS')
    assert 'data' not in store.records()[POSITION['key']]
    assert len(store.observation_history(POSITION['key'])) == 2
    assert store.mappings()[POSITION['key']]['provider'] == 'twelvedata'
    for provider, symbol, currency in [('unknown','AAPL','USD'), ('kraken','XBTEUR','USD'), ('eodhd','AAPL.US','')]:
        with pytest.raises(ValueError): store.set_feed('key', provider, symbol, currency)


@pytest.mark.parametrize('code', [401, 403, 429, 500])
def test_http_errors_redact_request_url(code):
    url = 'https://example.com/?apikey=' + SECRET
    with patch('urllib.request.OpenerDirector.open', side_effect=urllib.error.HTTPError(url, code, SECRET, {}, None)):
        with pytest.raises(ProviderError) as exc: request_json(url)
    assert SECRET not in str(exc.value)
    assert exc.value.stop == (code in (401,403,429))


def test_session_credentials_and_atomic_encryption_failure(store):
    keys = CredentialStore(store.db, protector=lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError('Failed')))
    keys.update({'eodhd': SECRET}, persist=False)
    assert keys.get('eodhd') == SECRET
    assert store.db.execute('SELECT COUNT(*) FROM online_credentials').fetchone()[0] == 0
    with pytest.raises(ValueError): keys.update({'finnhub': SECRET}, remove=['eodhd'])
    assert keys.get('eodhd') == SECRET
    keys.update({}, remove=['eodhd'])
    assert not keys.has('eodhd')


@pytest.mark.skipif(os.name != 'nt', reason='Windows DPAPI')
def test_dpapi_roundtrip_and_persistence(store):
    cipher = protect_windows(SECRET.encode())
    assert SECRET.encode() not in cipher
    assert protect_windows(cipher, decrypt=True).decode() == SECRET
    store.credentials.update({'eodhd': SECRET})
    fresh = CredentialStore(store.db)
    assert fresh.has('eodhd') and fresh.get('eodhd') == SECRET
    assert SECRET.encode() not in bytes(store.db.execute('SELECT encrypted FROM online_credentials').fetchone()[0])


def test_worker_respects_daily_budget_and_provider_stop():
    from PySide6.QtCore import Qt
    from portman.market_widget import MarketWorker
    positions = [{**POSITION, 'key': str(i)} for i in range(2)]
    mappings = {p['key']: {**MAPPING, 'provider': 'alphavantage'} for p in positions}
    for budget, expected_calls in [(25, 0), (0, 1)]:
        worker = MarketWorker(positions, mappings, keys={'alphavantage': SECRET}, usage={'alphavantage': budget})
        results = []
        worker.observation.connect(results.append, Qt.ConnectionType.DirectConnection)
        with patch('portman.valuation.fetch_fx', side_effect=ValueError), patch('portman.market_widget.MarketProvider.fetch',
            return_value={'security_key': '0', 'status': 'error', 'message': 'Rate limit', 'stop_provider': True}) as fetch:
            worker.run()
        assert fetch.call_count == expected_calls
        assert len(results) == 2 and all(r['status'] == 'error' for r in results)


def test_market_widget_sources_and_dividends(tmp_path):
    from PySide6.QtWidgets import QApplication
    from portman.repository import PortfolioRepository
    from portman.market_widget import MarketWidget
    from portman.online_dialogs import FeedDialog, OnlineCredentialsDialog
    from portfolio_v5.models import ImportBatch, Snapshot, Position
    app = QApplication.instance() or QApplication([])
    repo = PortfolioRepository(tmp_path / 'test.sqlite')
    repo.commit_batches([ImportBatch('test', 'hash', snapshots=[Snapshot('Bank', '2026-01','2026-01-05', 'test',
        [Position(POSITION['key'], POSITION['name'], isin=POSITION['isin'], quantity='1', value='100', currency='USD')])])])
    original = repo.holdings()
    repo.market.save_dividends(dividend_result())
    widget = MarketWidget(repo, lambda: (None, '9999-12-31'))
    assert widget.dividend_table.rowCount() == 1
    assert widget.dividend_table.item(0,3).text() == '0,12345'
    dialog = FeedDialog(repo.market, POSITION)
    dialog.provider.setCurrentIndex(dialog.provider.findData('eodhd'))
    dialog.symbol.setText('AAPL.US'); dialog.currency.setText('USD'); dialog.save()
    widget.refresh()
    assert widget.table.item(0,8).text() == 'EODHD'
    credentials = OnlineCredentialsDialog(repo.market)
    assert 'divvydiary' in credentials.fields
    assert repo.holdings() == original
    for w in [widget, dialog, credentials]: w.close()
    app.processEvents(); repo.close()


@pytest.mark.parametrize('provider,payload,symbol', [
    ('leeway', [{'time':'2026-01-02','value':100}], 'AAPL.US'),
    ('quandl', {'dataset':{'column_names':['Date','Close'], 'data':[['2026-01-02',100]]}}, 'WIKI/AAPL'),
    ('sifting', {'meta':{'symbol':'AAPL'}, 'data':[{'t':1767312000000,'c':100}]}, 'AAPL'),
    ('coingecko', {'prices':[[1767312000000,100]]}, 'bitcoin'),
])
def test_added_providers(provider, payload, symbol):
    calls = []
    def get(url, headers):
        calls.append((url,headers))
        return payload
    p = {**POSITION, '_history_request':True, 'history_start':'2026-01-01','history_end':'2026-01-03'}
    result = MarketProvider(provider, SECRET, get).fetch(p, {'symbol':symbol,'currency':'USD'})
    assert result['status'] == 'ok', result
    assert result['metrics']['price'] == 100
    assert SECRET not in json.dumps(result)
    assert len(calls) == 1
    if provider != 'coingecko': assert '2026-01-01' in calls[0][0]


def test_sifting_pagination():
    calls = []
    def get(url, headers):
        calls.append(url)
        return {'meta':{'symbol':'AAPL', 'next_cursor':'next' if len(calls)==1 else None},
                'data':[{'t':1767312000000 + len(calls)*86400000,'c':100}]}
    result = MarketProvider('sifting', SECRET, get).fetch(POSITION, MAPPING)
    assert result['status'] == 'ok' and len(result['prices']) == 2
    assert 'cursor=next' in calls[1]
