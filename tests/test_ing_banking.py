import os
from dataclasses import asdict
from datetime import date
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from fints.client import FinTSOperations as Op
from fints.exceptions import FinTSClientPINError
from fints.models import SEPAAccount
from mt940.models import Balance as BankBalance
from portman.ing_banking import BankingError, Cancelled, SOURCE, fetch_ing, parse_holdings, create_client
from portfolio_v5.models import ImportBatch, Balance
from portman.repository import PortfolioRepository


RAW = '''
:16R:FIN
:35B:ISIN DE0000000001
/DE/123456
TEST ETF
:90B::MRKT//ACTU/USD10,00
:98A::PRIC//20260923
:93B::AGGR//UNIT/6,847
:19A::HOLD//EUR61,62
:16S:FIN
-'''


def test_strict_holdings_uses_total_currency_and_exact_quantity():
    position, = parse_holdings(RAW)
    assert position.quantity == '6.847'
    assert position.value == '61.62'
    assert position.currency == 'EUR'
    assert position.name == 'TEST ETF'
    assert position.quote_date == '2026-09-23'
    assert position.cost is None


@pytest.mark.parametrize('raw', [
    RAW.replace(':19A::HOLD//EUR61,62', ''),
    RAW.replace('HOLD//EUR', 'HOLD//USD'),
    RAW.replace('UNIT/6,847', 'FAMT/6,847'),
    RAW.replace(':16S:FIN', ''), RAW + RAW, '',
    RAW.replace('DE0000000001', 'INVALID'),
])
def test_invalid_holdings_never_become_empty_snapshot(raw):
    with pytest.raises(BankingError):
        parse_holdings(raw)


def test_explicit_empty_depot():
    assert parse_holdings(':17B::ACTI//N\n-') == []


class FakeClient:
    def __init__(self):
        self.init_tan_response = None
        self.pin = 'secret'
        self.connection = SimpleNamespace(session=SimpleNamespace(close=Mock()))
        self.accounts = [SEPAAccount('DEFAKE', None, '1234567890', '', '50010517')]
        self.get_holdings = Mock(return_value=parse_holdings(RAW))
        self.get_balance = Mock(return_value=BankBalance('D', '12.34', date(2026, 9, 23), currency='EUR'))
        self.exited = False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.exited = True

    def get_sepa_accounts(self):
        return self.accounts

    def get_information(self):
        return {'accounts': [
            {'account_number': '1234567890', 'supported_operations': {Op.GET_BALANCE: True}},
            {'account_number': '9999999999', 'supported_operations': {Op.GET_HOLDINGS: True}},
        ]}


def fetch(fake, tmp_path, **kwargs):
    return fetch_ing('user', 'secret', 'product', source_root=tmp_path,
                     client_factory=lambda *args: fake, today=date(2026, 9, 24), **kwargs)


def test_fetch_depot_missing_from_sepa_and_signed_balance(tmp_path):
    fake = FakeClient()
    batches = fetch(fake, tmp_path)
    assert len(batches) == 2
    assert batches[0].balances[0].value == '-12.34'
    assert batches[0].balances[0].period == '2026-09'
    assert batches[1].snapshots[0].as_of == '2026-09-24'
    assert fake.get_holdings.call_args.args[0].accountnumber == '9999999999'
    assert fake.exited and fake.pin is None
    fake.connection.session.close.assert_called_once()
    assert 'secret' not in str([asdict(b) for b in batches])
    assert list(tmp_path.iterdir()) == []


def test_failed_depot_does_not_remove_positions_or_hide_success(tmp_path):
    fake = FakeClient()
    fake.get_holdings.side_effect = ValueError('secret raw bank data')
    batches = fetch(fake, tmp_path)
    assert batches[0].balances
    assert batches[1].errors and not batches[1].snapshots
    assert 'secret' not in str(batches)


def test_pin_error_stops_without_retry_and_cleans_up(tmp_path):
    fake = FakeClient()
    fake.get_balance.side_effect = FinTSClientPINError('secret')
    with pytest.raises(BankingError, match='Zugangsdaten abgelehnt'):
        fetch(fake, tmp_path)
    fake.get_balance.assert_called_once()
    fake.get_holdings.assert_not_called()
    assert fake.pin is None


def test_cancel_never_returns_batches(tmp_path):
    fake = FakeClient()
    with pytest.raises(Cancelled):
        fetch(fake, tmp_path, cancelled=lambda: True)
    fake.get_balance.assert_not_called()


def test_no_zero_for_missing_balance(tmp_path):
    fake = FakeClient()
    fake.get_balance.return_value = None
    batches = fetch(fake, tmp_path)
    assert batches[0].errors and not batches[0].balances


def test_transport_has_timeout_and_does_not_follow_redirects():
    client = create_client('user', 'secret', 'product', lambda: False)
    response = SimpleNamespace(status_code=302)
    client.connection.session.post = Mock(return_value=response)
    with pytest.raises(BankingError):
        client.connection.send(SimpleNamespace(render_bytes=lambda: b'test'))
    options = client.connection.session.post.call_args.kwargs
    assert options['timeout'] == (10, 30)
    assert options['allow_redirects'] is False
    client.connection.session.close()


def online_balance(amount, source='ING Konto 1234567890', target=None):
    from portfolio_v5.accounts import account_key
    return ImportBatch('ing-test.bank', str(amount), balances=[
        Balance('2026-09', 'Liquidität', source, str(amount), 'Online ING · 2026-09-24', 0)],
        source_sheet=SOURCE, account_assignments={account_key(source): target} if target else {})


def test_online_balance_preserves_other_banks_duplicate_undo(tmp_path):
    repo = PortfolioRepository(tmp_path / 'test.sqlite')
    original = ImportBatch('overview.xlsx', 'original', balances=[
        Balance('2026-09', 'Liquidität', 'ING Ziel', '100', 'Overview', 1),
        Balance('2026-09', 'Wertpapiere', 'ING Ziel', '500', 'Overview', 1),
        Balance('2026-09', 'Liquidität', 'Andere Bank', '700', 'Overview', 2)])
    repo.commit_batches([original])
    batch = online_balance('120', target='ing ziel')
    first = repo.commit_batches([batch])[0]
    assert first['status'] == 'imported'
    assert repo.commit_batches([batch])[0]['status'] == 'duplicate'
    values = {(b['account'], b['category']): b['value'] for b in repo.balances()}
    assert values == {('ING Ziel', 'Liquidität'): '120', ('ING Ziel', 'Wertpapiere'): '500',
                      ('Andere Bank', 'Liquidität'): '700'}
    repo.undo_import(first['id'])
    assert next(b for b in repo.balances() if b['account'] == 'ING Ziel' and b['category'] == 'Liquidität')['value'] == '100'
    repo.close()


def test_online_new_account_and_two_sources_are_independent(tmp_path):
    repo = PortfolioRepository(tmp_path / 'test.sqlite')
    repo.commit_batches([online_balance('100'), online_balance('200', 'ING Konto 9876543210')])
    repo.commit_batches([online_balance('110')])
    assert sorted(b['value'] for b in repo.balances()) == ['110', '200']
    repo.close()


def test_preview_details_cancel_does_not_persist(tmp_path):
    from PySide6.QtWidgets import QApplication, QTabWidget
    from portman.import_preview import ImportPreviewDialog
    QApplication.instance() or QApplication([])
    repo = PortfolioRepository(tmp_path / 'test.sqlite')
    batches = fetch(FakeClient(), tmp_path)
    dialog = ImportPreviewDialog(repo, batches)
    tabs = dialog.findChild(QTabWidget)
    assert any(tabs.tabText(i) == '4 · Validierung · ING' for i in range(tabs.count()))
    assert dialog.table.item(0, 3).text() == '09.2026'
    dialog.reject()
    assert not repo.imports()
    repo.close()


def test_dialog_masks_pin_and_requires_credentials(tmp_path):
    from PySide6.QtWidgets import QApplication, QLineEdit
    from portman.ing_dialog import INGDialog
    QApplication.instance() or QApplication([])
    dialog = INGDialog(tmp_path)
    assert dialog.pin.echoMode() == QLineEdit.EchoMode.Password
    dialog.start_fetch()
    assert dialog.worker is None
    dialog.pin.setText('secret')
    dialog.reject()
    assert dialog.pin.text() == ''


def test_existing_depot_is_continued_without_double_counting(tmp_path):
    from PySide6.QtWidgets import QApplication
    from portfolio_v5.models import Snapshot
    from portman.ing_dialog import INGDepotDialog
    QApplication.instance() or QApplication([])
    repo = PortfolioRepository(tmp_path / 'test.sqlite')
    old = ImportBatch('ing.csv', 'old', snapshots=[Snapshot('ING', '2026-09', '2026-09-01', 'ING', parse_holdings(RAW))])
    repo.commit_batches([old])
    batches = fetch(FakeClient(), tmp_path)
    dialog = INGDepotDialog(repo, batches)
    assert not dialog.known_choices
    batch, combo = dialog.choices[0]
    combo.setCurrentIndex(combo.findData('ING'))
    dialog.accept()
    repo.commit_batches([batch])
    assert len(repo.holdings()) == 1
    assert repo.holdings()[0]['as_of'] == '2026-09-24'
    assert repo.previous_bank_depot(batch.path) == 'ING'
    repeat = INGDepotDialog(repo, fetch(FakeClient(), tmp_path))
    assert repeat.choices[0][1].currentData() == 'ING'
    assert repeat.exec_if_needed() == 1
    assert repeat.choices[0][0].snapshots[0].account == 'ING'
    repo.close()


def test_worker_completion_and_cancellation_clear_credentials(tmp_path, monkeypatch):
    from PySide6.QtCore import QEventLoop, QTimer
    from PySide6.QtWidgets import QApplication
    import portman.ing_dialog as ui
    app = QApplication.instance() or QApplication([])
    def fake_fetch(*args, **kwargs):
        while not kwargs['cancelled']():
            QThread.msleep(5)
        raise Cancelled('Abbruch')
    from PySide6.QtCore import QThread
    monkeypatch.setattr(ui, 'fetch_ing', fake_fetch)
    dialog = ui.INGDialog(tmp_path)
    dialog.remember.setChecked(False)
    dialog.user.setText('user')
    dialog.pin.setText('secret')
    dialog.product.setText('product')
    dialog.start_fetch()
    assert dialog.pin.text() == ''
    dialog.reject()
    loop = QEventLoop()
    dialog.worker.finished.connect(loop.quit)
    QTimer.singleShot(5000, loop.quit)
    loop.exec()
    assert dialog.worker.wait(1000)
    app.processEvents()
    assert dialog.worker.credentials is None
    assert dialog.batches is None


def test_newer_overview_can_replace_bank_value(tmp_path):
    repo = PortfolioRepository(tmp_path / 'test.sqlite')
    repo.create_accounts(['Ziel'])
    repo.commit_batches([online_balance('120', target='ziel')])
    repo.commit_batches([ImportBatch('overview.xlsx', 'new', balances=[
        Balance('2026-09', 'Liquidität', 'Ziel', '130', 'Overview', 1)])])
    assert [b['value'] for b in repo.balances()] == ['120']
    repo.commit_batches([ImportBatch('overview-october.xlsx', 'newer', balances=[
        Balance('2026-10', 'Liquidität', 'Ziel', '130', 'Overview', 1)])])
    assert {b['period']: b['value'] for b in repo.balances()} == {'2026-09': '120', '2026-10': '130'}
    assert repo.account_overview('2026-10-01')[0]['balance'] == 130
    repo.close()
