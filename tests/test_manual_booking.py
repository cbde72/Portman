import pytest
from portman.repository_v09 import RepositoryV09
from portman.manual_booking import save_booking
from portfolio_v5.models import ImportBatch, Snapshot, Position


@pytest.fixture
def repo(tmp_path):
    repo = RepositoryV09(tmp_path / 'manual.sqlite', backups=False)
    repo.create_accounts(['Konto', 'Depot', 'Unterdepot'])
    yield repo
    repo.close()


def book(repo, **overrides):
    return save_booking(repo, **dict(account='Depot', day='2026-10-08', mode='security', direction='in',
        quantity='2,5', price='100', security='DE0008474511', name='AriDeka', note='Manueller Übertrag', **overrides))


def test_cash_balance_history_and_undo(repo):
    values = dict(account='Konto', day='2026-10-08', mode='cash', note='Einzahlung')
    save_booking(repo, **values, direction='in', amount='100,50')
    out = save_booking(repo, **values, direction='out', amount='20,25')
    assert next(r for r in repo.account_overview() if r['name'] == 'Konto')['balance'] == 80.25
    assert not repo.holdings()
    repo.undo_import(out['id'])
    assert next(r for r in repo.account_overview() if r['name'] == 'Konto')['balance'] == 100.5


def test_cash_same_day_anchor_and_later_balance_correction(repo):
    repo.add_balance('Konto', '100', '2026-10-08', 'Start')
    values = dict(account='Konto', day='2026-10-08', mode='cash', direction='in', note='Einzahlung')
    save_booking(repo, **values, amount='25')
    save_booking(repo, **values, amount='5')
    assert next(r for r in repo.account_overview() if r['name'] == 'Konto')['balance'] == 130
    repo.add_balance('Konto', '200', '2026-10-08', 'Neuer belegter Saldo')
    assert next(r for r in repo.account_overview() if r['name'] == 'Konto')['balance'] == 200
    save_booking(repo, **values, amount='10')
    assert next(r for r in repo.account_overview() if r['name'] == 'Konto')['balance'] == 210


def test_securities_same_day_partial_full_exit_and_other_positions(repo):
    book(repo)
    assert repo.holdings()[0]['quantity'] == '2.5'
    assert not repo.holdings('2026-10-07')
    assert repo.transactions()[0]['affects_cash'] is False
    values = dict(account='Depot', day='2026-10-08', mode='security', direction='out', security='DE0008474511', note='Auslieferung')
    save_booking(repo, **values, quantity='1')
    assert repo.holdings()[0]['quantity'] == '1.5'
    out = save_booking(repo, **values, quantity='1,5')
    assert repo.holdings() == []
    repo.undo_import(out['id'])
    assert repo.holdings()[0]['quantity'] == '1.5'


def test_invalid_inputs_do_not_write(repo):
    values = dict(account='Depot', day='2026-10-08', mode='security', direction='out', security='DE0008474511', name='AriDeka', note='Auslieferung')
    with pytest.raises(ValueError, match='übersteigt'): save_booking(repo, **values, quantity='1')
    with pytest.raises(ValueError): save_booking(repo, account='Konto', day='2026-10-08', mode='cash', direction='in', amount='NaN', note='Test')
    assert not repo.imports()


def test_existing_mapped_depot_and_preserve_other_security(repo):
    repo.commit_batches([ImportBatch('test', 'test', snapshots=[Snapshot('Quelle', '2026-10', '2026-10-01', 'Test', [
        Position('DE0008474511', 'AriDeka', isin='DE0008474511', quantity='10', value='1000', cost='800'),
        Position('OTHER', 'Other', quantity='1', value='50')])], account_assignments={'quelle': 'unterdepot'})])
    save_booking(repo, account='Unterdepot', depot='Quelle', day='2026-10-08', mode='security', direction='out',
        security='DE0008474511', quantity='2', note='Übertrag')
    positions = {p['key']: p for p in repo.holdings()}
    assert positions['DE0008474511']['quantity'] == '8'
    assert positions['DE0008474511']['cost'] == '640'
    assert positions['OTHER']['quantity'] == '1'
    assert {p['account'] for p in positions.values()} == {'Unterdepot'}


def test_dialog_save_and_cancel(repo, qapp):
    from portman.manual_booking_dialog import ManualBookingDialog
    dialog = ManualBookingDialog(repo, 'Konto')
    dialog.amount.setText('42,00')
    dialog.note.setText('Testeinzahlung')
    dialog.accept()
    assert dialog.result() == dialog.DialogCode.Accepted
    assert len(repo.transactions()) == 1
    cancelled = ManualBookingDialog(repo, 'Depot')
    cancelled.reject()
    assert len(repo.transactions()) == 1
