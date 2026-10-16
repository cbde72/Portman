from decimal import Decimal
from datetime import date, timedelta
import json
from test_crypto_wallet_import import write_csv
from portman.crypto_wallet_import import read_wallet_csv, save_wallet
from portman.repository_v09 import RepositoryV09


def test_daily_value_lookup_only_returns_requested_snapshots():
    import sqlite3
    from portman.wallet_valuation import daily_values_for_snapshots
    db = sqlite3.connect(':memory:')
    db.row_factory = sqlite3.Row
    db.execute('CREATE TABLE wallet_daily_values(snapshot_id INTEGER, security_key TEXT, value TEXT)')
    db.executemany('INSERT INTO wallet_daily_values VALUES(?,?,?)',
                   [(1, 'A', '10'), (2, 'A', '20'), (1000, 'B', '30')])
    values = daily_values_for_snapshots(db, [1, None, 2])
    assert set(values) == {(1, 'A'), (2, 'A')}


def test_selective_wallet_lookup_matches_legacy_results_for_all_edge_cases(monkeypatch):
    import sqlite3
    from portman import wallet_valuation
    from portman.performance_service import PerformanceService

    db = sqlite3.connect(':memory:')
    db.row_factory = sqlite3.Row
    db.execute('''CREATE TABLE wallet_daily_values(
        snapshot_id INTEGER, security_key TEXT, day TEXT, price TEXT, quantity TEXT,
        value TEXT, currency TEXT, source TEXT, recorded_at TEXT,
        PRIMARY KEY(snapshot_id,security_key))''')
    total = 12_000
    db.executemany('INSERT INTO wallet_daily_values VALUES(?,?,?,?,?,?,?,?,?)', (
        (index, 'ASSET', '2026-01-01', '1', '1', str(index), 'EUR', 'test', '2026-01-02')
        for index in range(total)))

    payload = json.dumps({'positions': [
        {'key': 'ASSET', 'quantity': '1', 'value': '0', 'currency': 'EUR'}]})
    snapshots = []
    for index, account in ((1, 'Depot A'), (2, 'Depot B'), (3, 'Depot A')):
        day = (date(2026, 1, 1) + timedelta(days=index)).isoformat()
        snapshots.append(dict(id=index, as_of=day, effective_date=day, payload=payload,
                              depot=account, account=account, complete=1))

    class Repo:
        def __init__(self): self.db = db
        def snapshots(self, account=None):
            return [row for row in snapshots if account is None or row['account'] == account]

    def legacy_loader(connection, _snapshot_ids):
        return {(row['snapshot_id'], row['security_key']): dict(row)
                for row in connection.execute('SELECT * FROM wallet_daily_values')}

    repo = Repo()
    service = PerformanceService(repo)
    selective_loader = wallet_valuation.daily_values_for_snapshots
    for account in (None, 'Depot A', 'Depot B', 'Nicht vorhanden'):
        monkeypatch.setattr(wallet_valuation, 'daily_values_for_snapshots', legacy_loader)
        before = service._valuation_series(account)
        monkeypatch.setattr(wallet_valuation, 'daily_values_for_snapshots', selective_loader)
        after = service._valuation_series(account)
        assert after == before

    selective = selective_loader
    assert selective(db, []) == {}
    assert selective(db, [1, 1, 2, None, 2]) == {
        key: value for key, value in legacy_loader(db, []).items() if key[0] in {1, 2}}
    requested = list(range(0, 2_500)) + list(range(0, 2_500))
    assert selective(db, requested) == {
        key: value for key, value in legacy_loader(db, []).items() if key[0] < 2_500}


def test_daily_values_are_historical_persistent_and_immutable(tmp_path):
    path = tmp_path / 'test.sqlite'
    repo = RepositoryV09(path, backups=False)
    batch = read_wallet_csv(write_csv(tmp_path, [
        {'Handelsdatum': '01.10.2026', 'Nominale_num': '2'},
        {'Handelsdatum': '02.10.2026', 'Nominale_num': '1'},
        {'Handelsdatum': '03.10.2026', 'Nominale_num': '1'}]), 'Wallet')
    save_wallet(repo, 'Wallet', {'kind': 'Krypto Wallet'}, None, batch)
    key = repo.holdings()[0]['key']
    result = dict(security_key=key, status='ok', currency='EUR', provider='Test',
        attempted_at='2026-10-03T12:00:00+00:00', symbol='BTC-EUR', message='ok',
        prices=[dict(date='2026-10-01', close=10), dict(date='2026-10-02', close=20),
                dict(date='2026-10-03', close=30)])
    repo.market.save_result(result)
    assert repo.holdings('2026-10-01')[0]['value'] == '20.00'
    assert repo.account_overview('2026-10-02')[0]['depot_value'] == Decimal('60.00')
    assert repo.holdings('2026-10-03')[0]['value'] is None
    result['prices'][0]['close'] = 999
    repo.market.save_result(result)
    assert repo.holdings('2026-10-01')[0]['value'] == '20.00'
    repo.close()
    repo = RepositoryV09(path, backups=False)
    assert repo.holdings('2026-10-02')[0]['value'] == '60.00'
    assert repo.holdings('2026-09-30') == []
    repo.close()


def test_wallet_booking_sum_includes_buys_and_sales(tmp_path):
    from PySide6.QtWidgets import QApplication
    from portman.account_bookings_dialog import AccountBookingsDialog
    QApplication.instance() or QApplication([])
    repo = RepositoryV09(tmp_path / 'test.sqlite', backups=False)
    batch = read_wallet_csv(write_csv(tmp_path, [
        {'Handelsdatum': '01.10.2026', 'Nominale_num': '2', 'Endbetrag_num': '100'},
        {'Handelsdatum': '02.10.2026', 'Nominale_num': '-1', 'Endbetrag_num': '70'}]), 'Wallet', 'signed')
    save_wallet(repo, 'Wallet', {'kind': 'Krypto Wallet'}, None, batch)
    dialog = AccountBookingsDialog(repo, 'Wallet')
    assert dialog.model.item(0, 5).text() == '100,00 €'
    assert dialog.model.item(1, 5).text() == '30,00 €'
    dialog.search.setText('02.10.2026')
    assert '30,00 €' in dialog.sum_note.text()
    assert not repo.balances()
    dialog.close()
    repo.close()
