import json
import os
from copy import deepcopy
from dataclasses import asdict
from datetime import date
from unittest.mock import Mock

import pytest
import requests

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from portman.comdirect_banking import (ComdirectClient, BankingError, Cancelled,
    fetch_comdirect, parse_positions, parse_transactions, BASE)
from portfolio_v5.models import ImportBatch, Balance, Snapshot
from portman.repository import PortfolioRepository

TODAY = date(2026, 9, 25)
POSITION = {'depotId': 'depot-api-id', 'positionId': 'pos-1',
    'instrument': {'isin': 'DE0000000001', 'wkn': 'ABC123', 'name': 'Test ETF'},
    'quantity': {'value': '6.847', 'unit': 'XXX'},
    'currentValue': {'value': '61.62', 'unit': 'EUR'},
    'purchaseValue': {'value': '50.00', 'unit': 'EUR'},
    'currentPrice': {'price': {'value': '9.00', 'unit': 'USD'}, 'priceDateTime': '2026-09-24T12:00:00Z'}}
ACCOUNT = {'accountId': 'account-api-id', 'account': {'iban': 'DE001234567890', 'accountDisplayId': '12345'},
    'balance': {'value': '-12.34', 'unit': 'EUR'},
    'availableCashAmount': {'value': '1000', 'unit': 'EUR'}}
TRANSACTION = {'reference': 'booking-ref', 'bookingStatus': 'BOOKED', 'bookingDate': '2026-09-24',
    'amount': {'value': '-7.23', 'unit': 'EUR'}, 'valutaDate': '2026-09-32',
    'remittanceInfo': 'Testbuchung', 'creditor': {'holderName': 'Testempfänger'}}


@pytest.fixture(autouse=True)
def isolated_comdirect_runtime(monkeypatch):
    import portman.comdirect_banking as banking
    from portman.comdirect_requests import RequestQueue
    from portman.comdirect_cache import FETCH_CACHE
    clock = [0.0]
    def sleep(seconds):
        clock[0] += seconds
    monkeypatch.setattr(banking, 'REQUEST_QUEUE', RequestQueue(clock=lambda: clock[0], sleep=sleep))
    FETCH_CACHE.clear()
    yield
    FETCH_CACHE.clear()


def response(body=None, status=200, headers=None):
    return Mock(status_code=status, headers=headers or {}, json=Mock(return_value=body))


def collection(rows, index=0, matches=None):
    return {'values': rows, 'paging': {'index': index, 'matches': len(rows) if matches is None else matches}}


def login_responses(kind='P_TAN_PUSH'):
    auth = {'id': 'challenge-id', 'typ': kind,
            'link': {'href': '/api/session/v1/authentications/auth-id', 'method': 'GET'}}
    return [response({'access_token': 'primary-secret'}), response([{'identifier': 'bank-session-id'}]),
        response({}, 201, {'x-once-authentication-info': json.dumps(auth)}),
        *([response({'status': 'AUTHENTICATED'})] if kind == 'P_TAN_PUSH' else []),
        response({'identifier': 'bank-session-id'}), response({'access_token': 'secondary-secret'})]


def fake_http(*, position=None, kind='P_TAN_PUSH'):
    http = Mock()
    http.request.side_effect = login_responses(kind) + [response(collection([deepcopy(ACCOUNT)])),
        response(collection([deepcopy(TRANSACTION)])),
        response(collection([{'depotId': 'depot-api-id', 'depotDisplayId': '98765'}])),
        response(collection([deepcopy(POSITION if position is None else position)])), response(None, 204)]
    return http


def fetch(http, root, **kwargs):
    return fetch_comdirect('user-secret', 'pin-secret', 'client-secret-id', 'client-secret-value',
        source_root=root, today=TODAY, history_start=date(2026, 9, 1),
        client_factory=lambda cancelled, progress: ComdirectClient(cancelled, progress, session=http), **kwargs)


def test_full_fetch_only_previews_and_revokes(tmp_path):
    http = fake_http()
    batches = fetch(http, tmp_path)
    assert len(batches) == 3 and not any(b.errors for b in batches)
    assert batches[0].balances[0].value == '-12.34'  # Never available cash including credit.
    assert batches[1].transactions[0].amount == '-7.23'
    assert batches[1].transactions[0].value_date == ''
    position = batches[2].snapshots[0].positions[0]
    assert (position.quantity, position.value, position.cost, position.currency) == ('6.847', '61.62', '50.00', 'EUR')
    assert position.quote_date == '2026-09-24'
    assert batches[2].snapshots[0].date_basis == 'retrieval'
    assert not list(tmp_path.iterdir())
    raw = json.dumps([asdict(b) for b in batches])
    assert all(secret not in raw for secret in ('pin-secret', 'client-secret', 'primary-secret', 'secondary-secret'))
    calls = http.request.call_args_list
    assert calls[-1].args == ('DELETE', BASE + '/oauth/revoke')
    assert all(c.kwargs['allow_redirects'] is False and c.kwargs['timeout'] for c in calls)
    assert calls[1].kwargs['headers']['Authorization'] == 'Bearer primary-secret'
    assert calls[6].kwargs['headers']['Authorization'] == 'Bearer secondary-secret'
    assert calls[4].args[1].endswith('/bank-session-id')
    assert calls[5].kwargs['data']['token'] == 'primary-secret'
    http.close.assert_called_once()


@pytest.mark.parametrize('kind', ['P_TAN', 'M_TAN'])
def test_manual_tan_used_only_for_session_activation(tmp_path, kind):
    http = fake_http(kind=kind)
    fetch(http, tmp_path, challenge=lambda auth: '123456')
    calls = http.request.call_args_list
    assert calls[3].kwargs['headers']['x-once-authentication'] == '123456'
    assert all('123456' not in json.dumps(c.kwargs) for i, c in enumerate(calls) if i != 3)


def test_push_rejection_never_activates_session_and_revokes(tmp_path):
    http = Mock()
    http.request.side_effect = login_responses()[:3] + [response({'status': 'REJECTED'}), response(None, 204)]
    with pytest.raises(BankingError, match='abgelehnt'):
        fetch(http, tmp_path)
    assert all(call.args[0] != 'PATCH' for call in http.request.call_args_list)
    assert http.request.call_args.args == ('DELETE', BASE + '/oauth/revoke')


def test_cancellation_during_push_wait_revokes(tmp_path):
    http = Mock()
    http.request.side_effect = login_responses()[:3] + [response({'status': 'PENDING'}), response(None, 204)]
    with pytest.raises(Cancelled):
        fetch(http, tmp_path, cancelled=lambda: http.request.call_count >= 4)
    assert http.request.call_args.args == ('DELETE', BASE + '/oauth/revoke')


@pytest.mark.parametrize('code', [301, 400, 401, 403, 429, 500])
def test_http_errors_no_secret_or_retry(code):
    http = Mock()
    http.request.return_value = response({'error': 'pin-secret'}, code)
    client = ComdirectClient(session=http)
    with pytest.raises(BankingError) as error:
        client.login('user', 'pin-secret', 'id', 'secret', lambda a: None)
    assert 'pin-secret' not in str(error.value)
    assert http.request.call_count == 1


def test_network_error_is_redacted():
    http = Mock()
    http.request.side_effect = requests.ConnectionError('secret')
    with pytest.raises(BankingError, match='nicht erreichbar'):
        ComdirectClient(session=http).data('GET', '/api/test')


@pytest.mark.parametrize('url', ['https://evil.example/api/tan', '//evil.example/api/tan',
    'http://api.comdirect.de/api/tan', 'https://api.comdirect.de@evil.example/api/tan'])
def test_external_tan_link_never_receives_token(url):
    http = Mock()
    client = ComdirectClient(session=http)
    client.token = 'secret'
    with pytest.raises(BankingError):
        client.data('GET', url)
    http.request.assert_not_called()


def test_pagination_collects_every_page():
    http = Mock()
    http.request.side_effect = [response(collection([{'id': 1}], matches=2)),
                                  response(collection([{'id': 2}], index=1, matches=2))]
    assert len(ComdirectClient(session=http).collection('/api/test')) == 2
    assert http.request.call_args.kwargs['params']['paging-first'] == 1


@pytest.mark.parametrize('pages', [
    [{}], [{'values': []}], [collection([], matches=2)],
    [collection([{}], matches=2), collection([{}], index=0, matches=2)],
    [collection([{}], matches=2), collection([{}], index=1, matches=3)],
    [collection([{}, {}], matches=1)],
])
def test_incomplete_collection_never_becomes_complete_depot(pages):
    http = Mock()
    http.request.side_effect = [response(p) for p in pages]
    with pytest.raises(BankingError):
        ComdirectClient(session=http).collection('/api/test')


def test_explicit_empty_collection():
    http = Mock()
    http.request.return_value = response(collection([]))
    assert ComdirectClient(session=http).collection('/api/test') == []


def test_missing_depot_is_visible_in_preview(tmp_path):
    from PySide6.QtWidgets import QApplication, QLabel
    from portman.import_preview import ImportPreviewDialog
    QApplication.instance() or QApplication([])
    http = Mock()
    http.request.side_effect = login_responses() + [response(collection([deepcopy(ACCOUNT)])),
        response(collection([deepcopy(TRANSACTION)])), response(collection([])), response(None, 204)]
    batches = fetch(http, tmp_path)
    assert batches[0].balances and not batches[0].errors
    assert batches[-1].errors and not batches[-1].snapshots
    assert 'keine Depots zurückgegeben' in batches[-1].errors[0]
    repo = PortfolioRepository(tmp_path / 'preview.sqlite')
    try:
        widget = ImportPreviewDialog(repo, batches)
        assert any('keine Depots zurückgegeben' in label.text() for label in widget.findChildren(QLabel))
        widget.close()
    finally:
        repo.close()


@pytest.mark.parametrize('field,value', [('currentValue', None),
    ('currentValue', {'value': 'NaN', 'unit': 'EUR'}),
    ('currentValue', {'value': '1', 'unit': 'USD'}),
    ('quantity', {'value': '1', 'unit': 'EUR'}), ('depotId', 'wrong-depot'),
    ('instrument', {'isin': 'invalid'})])
def test_bad_depot_preserves_successful_accounts(tmp_path, field, value):
    position = deepcopy(POSITION)
    position[field] = value
    batches = fetch(fake_http(position=position), tmp_path)
    assert batches[0].balances and not batches[0].errors
    assert batches[-1].errors and not batches[-1].snapshots


def test_duplicate_positions_and_bookings_rejected():
    with pytest.raises(BankingError):
        parse_positions([POSITION, POSITION], 'depot-api-id')
    with pytest.raises(BankingError):
        parse_transactions([TRANSACTION, TRANSACTION], 'source', date(2026, 9, 1), TODAY)


def test_cancellation_prevents_next_request_and_revokes(tmp_path):
    http = fake_http()
    with pytest.raises(Cancelled):
        fetch(http, tmp_path, cancelled=lambda: http.request.call_count >= 1)
    assert http.request.call_count == 1  # No token accepted after cancellation.
    http.close.assert_called_once()


def test_repeat_import_preserves_other_banks_and_undo(tmp_path):
    repo = PortfolioRepository(tmp_path / 'test.sqlite')
    try:
        batches = fetch(fake_http(), tmp_path)
        account = batches[0].balances[0].account
        repo.commit_batches([ImportBatch('overview.xlsx', 'original', balances=[
            Balance('2026-09', 'Liquidität', account, '100', 'Overview', 1),
            Balance('2026-09', 'Liquidität', 'Andere Bank', '700', 'Overview', 2)])])
        first = repo.commit_batches(batches)
        assert all(r['status'] == 'imported' for r in first)
        assert all(r['status'] == 'duplicate' for r in repo.commit_batches(fetch(fake_http(), tmp_path)))
        assert {b['account']: b['value'] for b in repo.balances()} == {account: '-12.34', 'Andere Bank': '700'}
        assert len(repo.transactions()) == 1
        repo.undo_import(first[0]['id'])
        assert {b['account']: b['value'] for b in repo.balances()} == {account: '100', 'Andere Bank': '700'}
    finally:
        repo.close()


@pytest.mark.parametrize('empty', [False, True])
def test_online_preview_always_synchronizes_depot(tmp_path, empty):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication
    from portman.import_preview import ImportPreviewDialog
    QApplication.instance() or QApplication([])
    repo = PortfolioRepository(tmp_path / 'test.sqlite')
    try:
        batches = fetch(fake_http(), tmp_path)
        depot = batches[2]
        if empty:
            depot.snapshots[0].positions = []
        preview = ImportPreviewDialog(repo, batches)
        for column in (0, 8):
            item = preview.table.item(2, column)
            assert item.checkState() == Qt.CheckState.Checked
            assert not item.flags() & Qt.ItemFlag.ItemIsUserCheckable
            item.setCheckState(Qt.CheckState.Unchecked)
        preview.table.item(0, 0).setCheckState(Qt.CheckState.Unchecked)
        selected = preview.selected_batches()
        assert [batch.path for batch in selected] == [batches[1].path, depot.path]
        assert selected[-1].snapshots[0].complete
        assert len(selected[-1].snapshots[0].positions) == (0 if empty else 1)
        preview.reject()
    finally:
        repo.close()


def test_transactions_send_date_window(tmp_path):
    http = fake_http()
    fetch(http, tmp_path, cache=None)
    call = next(c for c in http.request.call_args_list if c.args[1].endswith('/transactions'))
    assert call.kwargs['params'] == {'transactionState': 'BOOKED',
        'min-bookingDate': '2026-09-01', 'max-bookingDate': '2026-09-25', 'paging-first': 0}


def test_cache_avoids_login_and_isolated_from_preview_edits(tmp_path):
    from portman.comdirect_cache import MemoryCache
    clock = [0.0]
    cache = MemoryCache(clock=lambda: clock[0])
    first = fetch(fake_http(), tmp_path, cache=cache)
    first[-1].snapshots[0].positions.clear()
    unused = Mock()
    second = fetch(unused, tmp_path, cache=cache)
    unused.request.assert_not_called()
    unused.close.assert_not_called()
    assert len(second[-1].snapshots[0].positions) == 1
    assert any('Zwischenspeicher' in w for w in second[-1].warnings)
    clock[0] = 300
    fresh = fake_http()
    fetch(fresh, tmp_path, cache=cache)
    assert fresh.request.call_count > 0


def test_cache_refresh_and_errors(tmp_path):
    from portman.comdirect_cache import MemoryCache
    cache = MemoryCache()
    fetch(fake_http(), tmp_path, cache=cache)
    fresh = fake_http()
    fetch(fresh, tmp_path, cache=cache, refresh=True)
    assert fresh.request.call_count > 0
    cache.clear()
    bad = deepcopy(POSITION)
    bad['quantity'] = None
    assert fetch(fake_http(position=bad), tmp_path, cache=cache)[-1].errors
    fresh = fake_http()
    assert not fetch(fresh, tmp_path, cache=cache)[-1].errors
    assert fresh.request.call_count > 0


def test_cache_separates_credentials_and_date_ranges(tmp_path):
    from portman.comdirect_cache import MemoryCache
    cache = MemoryCache()
    fetch(fake_http(), tmp_path, cache=cache)
    other = fake_http()
    fetch_comdirect('another-user', 'pin-secret', 'client-secret-id', 'client-secret-value',
        source_root=tmp_path, today=TODAY, history_start=date(2026, 9, 1), cache=cache,
        client_factory=lambda cancelled, progress: ComdirectClient(cancelled, progress, session=other))
    assert other.request.call_count > 0
    another = fake_http()
    fetch(another, tmp_path, cache=cache, history_end=date(2026, 9, 24))
    assert another.request.call_count > 0
    with pytest.raises(Cancelled):
        fetch(Mock(), tmp_path, cache=cache, cancelled=lambda: True)


def test_cache_does_not_extend_age_for_slow_fetch():
    from portman.comdirect_cache import MemoryCache
    cache = MemoryCache(clock=lambda: 301)
    cache.put('old', ['value'], acquired_at=0)
    assert cache.get('old') is None


def test_429_backoff_is_bounded_and_shared(monkeypatch):
    from portman.comdirect_requests import RequestQueue
    clock, starts = [0.0], []
    def sleep(seconds):
        clock[0] += seconds
    queue = RequestQueue(clock=lambda: clock[0], sleep=sleep)
    http = Mock()
    def limited(*args, **kwargs):
        starts.append(clock[0])
        return response({}, 429)
    http.request.side_effect = limited
    client = ComdirectClient(session=http, request_queue=queue)
    with pytest.raises(BankingError, match='Abruflimit'):
        client.data('GET', '/api/test')
    assert len(starts) == 4
    assert starts[1] - starts[0] >= 6
    assert starts[2] - starts[1] == pytest.approx(10, abs=.11)
    assert starts[3] - starts[2] == pytest.approx(20, abs=.11)
    second = Mock(request=lambda *a, **kw: (starts.append(clock[0]), response({}))[1])
    ComdirectClient(session=second, request_queue=queue).data('GET', '/api/test')
    assert starts[-1] - starts[-2] >= 40


@pytest.mark.parametrize('header, expected', [('15', 15), ('invalid', 5), ('0', 0),
    ('Wed, 07 Oct 2026 12:00:30 GMT', 30), ('Wed, 07 Oct 2026 11:00:00 GMT', 0)])
def test_retry_after_seconds_and_http_date(header, expected):
    from datetime import datetime, timezone
    from portman.comdirect_requests import retry_delay
    assert retry_delay(header, 0, datetime(2026, 10, 7, 12, tzinfo=timezone.utc)) == expected


def test_retry_after_then_success_and_cancel_wait():
    from portman.comdirect_requests import RequestQueue
    clock = [0.0]
    def sleep(seconds):
        clock[0] += seconds
    queue = RequestQueue(clock=lambda: clock[0], sleep=sleep)
    http = Mock()
    http.request.side_effect = [response({}, 429, {'Retry-After': '15'}), response({'ok': True})]
    client = ComdirectClient(session=http, request_queue=queue)
    assert client.data('GET', '/api/test') == {'ok': True}
    assert clock[0] >= 15
    assert http.request.call_count == 2
    client.cancelled = lambda: True
    with pytest.raises(Cancelled):
        client.data('GET', '/api/test')
    assert http.request.call_count == 2


def test_requests_and_revoke_share_spacing():
    from portman.comdirect_requests import RequestQueue
    clock, starts = [0.0], []
    def sleep(seconds):
        clock[0] += seconds
    queue = RequestQueue(clock=lambda: clock[0], sleep=sleep)
    http = Mock(request=lambda *args, **kw: (starts.append(clock[0]), response({}))[1])
    one = ComdirectClient(session=http, request_queue=queue)
    two = ComdirectClient(session=http, request_queue=queue)
    for _ in range(6):
        one.data('GET', '/api/test')
        two.data('GET', '/api/test')
    one.token = 'token'
    one.close()
    assert len(starts) == 13
    assert all(b - a >= 6 for a, b in zip(starts, starts[1:]))
    assert all(sum(start <= t < start + 60 for t in starts) <= 10 for start in starts)


def test_queue_serializes_concurrent_requests():
    from concurrent.futures import ThreadPoolExecutor
    from time import monotonic
    from portman.comdirect_requests import RequestQueue
    queue = RequestQueue(interval=.02)
    starts = []
    def send():
        starts.append(monotonic())
        return response({})
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(queue.run, send, lambda: None, lambda message: None) for _ in range(8)]
        for future in futures:
            future.result(timeout=5)
    assert len(starts) == 8
    assert all(b - a >= .019 for a, b in zip(starts, starts[1:]))


def test_cancellation_interrupts_backoff_before_next_request():
    from portman.comdirect_requests import RequestQueue
    clock = [0.0]
    def sleep(seconds):
        clock[0] += seconds
    queue = RequestQueue(clock=lambda: clock[0], sleep=sleep)
    http = Mock(request=Mock(return_value=response({}, 429, {'Retry-After': '60'})))
    client = ComdirectClient(cancelled=lambda: clock[0] >= .5, session=http, request_queue=queue)
    with pytest.raises(Cancelled):
        client.data('GET', '/api/test')
    assert http.request.call_count == 1
    assert clock[0] < 1


def test_long_retry_after_does_not_loop_and_revoke_wait_is_bounded():
    from portman.comdirect_requests import RequestQueue
    clock = [0.0]
    def sleep(seconds):
        clock[0] += seconds
    queue = RequestQueue(clock=lambda: clock[0], sleep=sleep)
    http = Mock(request=Mock(return_value=response({}, 429, {'Retry-After': '600'})))
    client = ComdirectClient(session=http, request_queue=queue)
    client.token = 'secret'
    with pytest.raises(BankingError, match='Abruflimit'):
        client.data('GET', '/api/test')
    client.close()
    assert http.request.call_count == 1
    assert clock[0] < 11
    assert client.token == ''
    http.close.assert_called_once()


def test_continue_existing_comdirect_depot_and_preview(tmp_path):
    from PySide6.QtWidgets import QApplication, QTabWidget
    from portman.ing_dialog import INGDepotDialog
    from portman.import_preview import ImportPreviewDialog
    QApplication.instance() or QApplication([])
    repo = PortfolioRepository(tmp_path / 'test.sqlite')
    try:
        repo.commit_batches([ImportBatch('comdirect.csv', 'old', snapshots=[Snapshot('comdirect',
            '2026-09', '2026-09-01', 'CSV', parse_positions([POSITION], 'depot-api-id'))])])
        dialog = INGDepotDialog(repo, fetch(fake_http(), tmp_path), bank='comdirect')
        batch, combo = dialog.choices[0]
        combo.setCurrentIndex(combo.findData('comdirect'))
        dialog.accept()
        preview = ImportPreviewDialog(repo, dialog.batches)
        tabs = preview.findChild(QTabWidget)
        assert any(tabs.tabText(i) == 'comdirect · Abrufdetails' for i in range(tabs.count()))
        preview.reject()
        assert len(repo.imports()) == 1
        repo.commit_batches([batch])
        assert len(repo.holdings()) == 1
        assert repo.holdings()[0]['as_of'] == '2026-09-25'
        assert repo.previous_bank_depot(batch.path) == 'comdirect'
    finally:
        repo.close()
