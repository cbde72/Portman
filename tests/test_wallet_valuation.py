from decimal import Decimal
from test_crypto_wallet_import import write_csv
from portman.crypto_wallet_import import read_wallet_csv, save_wallet
from portman.repository_v09 import RepositoryV09


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
