import json
from test_import_assignments import batch, repo as repo
import pytest
from portfolio_v5.models import ImportBatch, TaxEvent


def test_reassign_all_data_and_persist(repo):
    iid = repo.commit_batches([batch()])[0]['id']
    before = [tuple(r) for r in repo.db.execute('SELECT * FROM snapshots')]
    repo.reassign_imports([{'import_id':iid,'source_key':'quelle1','target_key':'ziel b','remember':True}])
    assert not repo.holdings(account='Ziel A')
    assert len(repo.holdings(account='Ziel B')) == 2
    assert len(repo.transactions('Ziel B')) == 2
    assert repo.balances()[0]['account'] == 'Ziel B'
    assert before == [tuple(r) for r in repo.db.execute('SELECT * FROM snapshots')]
    assert repo.import_account_suggestions(batch('export-2026-10-16.csv'))[0]['target_key'] == 'ziel b'
    assert json.loads(repo.imports()[0]['report'])['assignment_history'][0]['changes'][0]['before'] == 'ziel a'
    from portman.repository import PortfolioRepository
    reopened = PortfolioRepository(repo.store.path)
    try:
        assert len(reopened.holdings(account='Ziel B')) == 2
    finally:
        reopened.close()


def test_reassign_atomic_invalid_and_conflicting_rules(repo):
    first = repo.commit_batches([batch()])[0]['id']
    other = batch('export-2026-10-16.csv')
    other.file_hash = 'other'
    other.snapshots[0].positions[0].quantity = '7'
    second = repo.commit_batches([other])[0]['id']
    with pytest.raises(ValueError):
        repo.reassign_imports([{'import_id':first,'source_key':'quelle1','target_key':'ziel b'},
            {'import_id':second,'source_key':'quelle1','target_key':'missing'}])
    assert repo.import_assignment_rows([first])[0]['target_key'] == 'ziel a'
    with pytest.raises(ValueError):
        repo.reassign_imports([{'import_id':first,'source_key':'quelle1','target_key':'ziel b','remember':True},
            {'import_id':second,'source_key':'quelle1','target_key':'ziel a','remember':True}])
    assert repo.import_assignment_rows([first])[0]['target_key'] == 'ziel a'


def test_inactive_import_stays_inactive_and_rule_unchanged(repo):
    iid = repo.commit_batches([batch()])[0]['id']
    repo.undo_import(iid)
    rules = repo.import_rules()
    repo.reassign_imports([{'import_id':iid,'source_key':'quelle1','target_key':'ziel b'}])
    assert not repo.holdings()
    assert repo.imports()[0]['active'] == 0
    assert repo.import_rules() == rules


def test_tax_event_reassignment_is_previewed_and_restricted_to_depots(repo):
    repo.save_account('Steuerdepot', {'kind': 'Depot'})
    repo.save_account('Girokonto', {'kind': 'Girokonto'})
    batch = ImportBatch('tax.pdf', 'tax-source', account_names=['Depot 476492400'],
        tax_events=[TaxEvent('tax-1', 'Depot 476492400', 'vorabpauschale_ausland',
            '2026-01-02', income_year='2025', security_ref='IE00BKM4GZ66')], source_sheet='PDF')
    batch.account_assignments = {'depot 476492400': 'steuerdepot'}
    iid = repo.commit_batches([batch])[0]['id']
    row = repo.import_assignment_rows([iid])[0]
    assert row['source_name'] == 'Depot 476492400'
    assert row['required_kind'] == 'Depot'
    with pytest.raises(ValueError, match='nur einem aktiven Depot'):
        repo.reassign_imports([{'import_id': iid, 'source_key': row['source_key'],
                                'target_key': 'girokonto'}])


def test_assignment_dialog_cancel_then_save(repo):
    from PySide6.QtWidgets import QApplication
    from portman.import_assignment import ImportAssignmentDialog
    QApplication.instance() or QApplication([])
    iid = repo.commit_batches([batch()])[0]['id']
    dialog = ImportAssignmentDialog(repo,[iid])
    dialog.rows[0][1].setCurrentIndex(dialog.rows[0][1].findData('ziel b'))
    dialog.reject()
    assert repo.import_assignment_rows([iid])[0]['target_key'] == 'ziel a'
    dialog.accept()
    assert repo.import_assignment_rows([iid])[0]['target_key'] == 'ziel b'
    assert repo.import_assignment_rows([iid])[1]['target_key'] == 'ziel b'
    dialog.close()
