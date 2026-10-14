import os
import pytest
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from portfolio_v5.models import ImportBatch, Snapshot, Position, Balance, Transaction
from portfolio_v5.import_accounts import rule_scope
from portman.repository import PortfolioRepository

@pytest.fixture
def repo(tmp_path):
    r = PortfolioRepository(tmp_path / 'test.sqlite')
    r.create_accounts(['Ziel A', 'Ziel B'])
    yield r
    r.close()

def batch(path='export-2026-09-16.csv'):
    return ImportBatch(path, 'hash', snapshots=[Snapshot(source, '2026-09', '2026-09-16', 'Depot',
        [Position('DE0000000001', 'Aktie', quantity='6.847', value='100.12')]) for source in ['Quelle1', 'Quelle2']],
        balances=[Balance('2026-09', 'Liquidität', 'Quelle1', '42.00', 'Konto', 1)],
        transactions=[Transaction(source, 'same-id', '2026-09-16', 'DEPOSIT', '10.00', 'EUR') for source in ['Quelle1', 'Quelle2']],
        account_assignments={'quelle1': 'ziel a', 'quelle2': 'ziel b'}, remember_assignments=['quelle1', 'quelle2'])

def test_mapping_and_correction_preserve_sources(repo):
    b = batch()
    result = repo.commit_batches([b])[0]
    assert result['status'] == 'imported'
    assert {p['account'] for p in repo.holdings()} == {'Ziel A', 'Ziel B'}
    assert len(repo.holdings(account='Ziel A')) == 1
    assert repo.holdings(account='Ziel A')[0]['quantity'] == '6.847'
    assert len(repo.transactions()) == 2
    assert repo.balances()[0]['account'] == 'Ziel A'
    assert 'Quelle1' not in repo.accounts()
    repo.correct_import(result['id'], {})
    assert repo.holdings(account='Ziel A')[0]['quantity'] == '6.847'
    assert 'Quelle1' not in repo.accounts()
    raw = repo.store.db.execute('SELECT account FROM snapshots').fetchall()
    assert {r[0] for r in raw} == {'Quelle1', 'Quelle2'}

def test_suggestions_future_and_deleted(repo):
    repo.commit_batches([batch()])
    future = batch('export-2026-10-16.csv')
    suggestions = repo.import_account_suggestions(future)
    assert [s['target_key'] for s in suggestions] == ['ziel a', 'ziel b']
    assert all(s['remembered'] for s in suggestions)
    repo.set_account_active('Ziel A', False)
    assert repo.import_account_suggestions(future)[0]['target_key'] is None

def test_invalid_import_does_not_save_rule(repo):
    b = batch()
    b.account_assignments['quelle2'] = 'missing'
    assert repo.commit_batches([b])[0]['status'] == 'error'
    assert not repo.import_rules()
    assert not repo.imports()

def test_scope_dates_and_identifiers():
    assert rule_scope('ZERO-pos-16.09.2026.csv') == rule_scope('ZERO-pos-20.10.2026.csv')
    assert rule_scope('account-123-2026-09-16.csv') != rule_scope('account-456-2026-09-16.csv')
    assert rule_scope('one/export-2026-09-16.csv') != rule_scope('two/export-2026-10-16.csv')

def test_reassignment_and_restart(repo):
    original = batch()
    repo.commit_batches([original])
    newer = batch('export-2026-10-16.csv')
    newer.file_hash = 'new'
    for snap in newer.snapshots:
        snap.period = '2026-10'
        snap.as_of = '2026-10-16'
    newer.account_assignments = {'quelle1': 'ziel b', 'quelle2': 'ziel b'}
    repo.commit_batches([newer])
    assert len(repo.holdings(account='Ziel B')) == 2
    assert not repo.holdings(account='Ziel A')
    assert len(repo.holdings('2026-09-30', account='Ziel A')) == 1

def test_preview_cancel_and_selection(repo):
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import Qt
    from portman.import_preview import ImportPreviewDialog
    QApplication.instance() or QApplication([])
    original = batch()
    original.account_assignments = {}
    original.remember_assignments = []
    dialog = ImportPreviewDialog(repo, [original])
    for index, source, combo, remember in dialog.mapping_rows:
        combo.setCurrentIndex(combo.findData('ziel a'))
        remember.setCheckState(Qt.CheckState.Checked)
    selected = dialog.selected_batches()
    assert selected[0].account_assignments == {'quelle1': 'ziel a', 'quelle2': 'ziel a'}
    assert original.account_assignments == {}
    dialog.reject()
    assert not repo.import_rules()
    assert not repo.imports()
    repo.commit_batches(selected)
    assert len(repo.import_rules()) == 2
    assert len(repo.holdings(account='Ziel A')) == 2
    assert len(repo.transactions('Ziel A')) == 2
    dialog.close()

def test_multiple_balance_files_preserve_other_accounts(repo):
    for source, target in [('Quelle1', 'ziel a'), ('Quelle2', 'ziel b')]:
        b = ImportBatch(source+'.csv', source, balances=[Balance('2026-09','Liquidität',source,'42','Konto',1)], account_assignments={source.lower():target})
        repo.commit_batches([b])
    assert {b['account'] for b in repo.balances()} == {'Ziel A', 'Ziel B'}


def test_preview_create_depot_uses_own_account_and_survives_restart(tmp_path):
    from PySide6.QtWidgets import QApplication
    from portman.import_preview import ImportPreviewDialog
    QApplication.instance() or QApplication([])
    path = tmp_path / 'depot.sqlite'
    repo = PortfolioRepository(path)
    repo.create_accounts(['Deka'])
    original = ImportBatch('depot.csv', 'depot', snapshots=[
        Snapshot('Deka/123', '2026-09', '2026-09-16', 'Depot',
                 [Position('stock', 'Aktie', value='100')])])
    dialog = ImportPreviewDialog(repo, [original])
    combo = dialog.mapping_rows[0][2]
    combo.setCurrentIndex(combo.findData('__new__'))
    selected = dialog.selected_batches()
    assert selected[0].new_accounts == ['Deka/123']
    assert selected[0].account_assignments == {'deka/123': 'deka/123'}
    assert repo.accounts() == ['Deka']
    assert original.new_accounts == []
    assert repo.commit_batches(selected)[0]['status'] == 'imported'
    dialog.close()
    repo.close()
    repo = PortfolioRepository(path)
    try:
        assert 'Deka/123' in repo.accounts()
        assert repo.depots()[0]['account'] == 'Deka/123'
        assert repo.import_account_suggestions(original)[0]['target_key'] == 'deka/123'
    finally:
        repo.close()

def test_restart_keeps_mapping_without_phantom_source(tmp_path):
    path = tmp_path / 'restart.sqlite'
    r = PortfolioRepository(path)
    r.create_accounts(['Ziel A', 'Ziel B'])
    r.commit_batches([batch()])
    r.close()
    r = PortfolioRepository(path)
    try:
        assert set(r.accounts()) == {'Ziel A', 'Ziel B'}
        assert len(r.holdings()) == 2
        assert len(r.import_rules()) == 2
    finally:
        r.close()
