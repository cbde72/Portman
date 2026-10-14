import os
import sqlite3
from unittest.mock import patch
import pytest
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from portfolio_v5.models import ImportBatch, Snapshot, Position, Balance, Transaction
from portman.repository import PortfolioRepository

@pytest.fixture
def repo(tmp_path):
    r = PortfolioRepository(tmp_path / 'db.sqlite')
    r.create_accounts(['Ziel'])
    yield r
    r.close()

def add(repo, name):
    b = ImportBatch(name+'.csv', name,
        snapshots=[Snapshot(name,'2026-09','2026-09-20','Depot',[Position(name,name,quantity='1',value='100',cost='80')])],
        balances=[Balance('2026-09','Liquidität',name,'10','Konto',1)],
        transactions=[Transaction(name,'1','2026-09-20','DEPOSIT','10','EUR')],
        account_assignments={name.lower():'ziel'}, remember_assignments=[name.lower()])
    return repo.commit_batches([b])[0]['id'], b

def test_complete_delete_and_reimport(repo):
    first, batch = add(repo,'A')
    second, _ = add(repo,'B')
    keep, _ = add(repo,'C')
    sid = repo.db.execute('SELECT id FROM snapshots WHERE import_id=?',(first,)).fetchone()[0]
    repo.correct_cost(sid,'A','90','Beleg')
    with repo.db:
        repo.db.execute('INSERT INTO snapshot_exclusions(snapshot_id,reason) VALUES(?,?)',(sid,'test'))
    repo.undo_import(second)
    assert repo.delete_imports([first,second,first]) == 2
    assert [r['id'] for r in repo.imports()] == [keep]
    for table in ('snapshots','balances','transactions','import_account_links'):
        assert {r[0] for r in repo.db.execute(f'SELECT import_id FROM {table}')} == {keep}
    for table in ('snapshot_exclusions','cost_corrections'):
        assert repo.db.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0] == 0
    assert not repo.db.execute('PRAGMA foreign_key_check').fetchall()
    assert repo.accounts() == ['Ziel']
    assert len(repo.import_rules()) == 3
    assert len(repo.holdings()) == 1
    assert repo.commit_batches([batch])[0]['status'] == 'imported'

def test_delete_atomic_on_failure(repo):
    first, _ = add(repo,'A')
    second, _ = add(repo,'B')
    with repo.db:
        repo.db.execute(f"CREATE TRIGGER prevent_delete BEFORE DELETE ON imports WHEN OLD.id={second} BEGIN SELECT RAISE(ABORT, 'test failure'); END")
    with pytest.raises(sqlite3.IntegrityError):
        repo.delete_imports([first,second])
    assert len(repo.imports()) == 2
    assert len(repo.holdings()) == 2
    assert len(repo.transactions()) == 2
    with pytest.raises(ValueError):
        repo.delete_imports([first,99999])
    assert len(repo.imports()) == 2


@pytest.mark.parametrize('accounts', [False, True])
def test_reset_all_data_and_reopen(repo, accounts):
    first, batch = add(repo, 'A')
    second, _ = add(repo, 'B')
    repo.undo_import(second)
    repo.add_balance('Ziel', '25', '2026-09-20')
    repo.set_account_active('Ziel', False)
    reset = repo.delete_all_accounts if accounts else repo.delete_all_imports
    reset()
    for table in ('imports', 'snapshots', 'balances', 'transactions', 'bank_documents',
                  'import_account_links', 'import_account_rules', 'depot_accounts',
                  'snapshot_exclusions', 'cost_corrections', 'coverage'):
        assert repo.db.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0] == 0
    assert len(repo.account_records()) == (0 if accounts else 1)
    assert repo.db.execute('SELECT COUNT(*) FROM manual_balances').fetchone()[0] == (0 if accounts else 1)
    assert not repo.db.execute('PRAGMA foreign_key_check').fetchall()
    reopened = PortfolioRepository(repo.store.path)
    try:
        assert len(reopened.account_records()) == (0 if accounts else 1)
        reopened.create_accounts(['Ziel'])
        reopened.set_account_active('Ziel', True)
        assert reopened.commit_batches([batch])[0]['status'] == 'imported'
    finally:
        reopened.close()


def test_account_reset_rolls_back_import_deletion(repo):
    add(repo, 'A')
    repo.add_balance('Ziel', '25', '2026-09-20')
    with repo.db:
        repo.db.execute("CREATE TRIGGER prevent_reset BEFORE DELETE ON accounts BEGIN SELECT RAISE(ABORT, 'test failure'); END")
    with pytest.raises(sqlite3.IntegrityError):
        repo.delete_all_accounts()
    assert len(repo.imports()) == 1
    assert len(repo.holdings()) == 1
    assert len(repo.balance_history('Ziel')) == 1
    assert len(repo.import_rules()) == 1


@pytest.mark.parametrize('accounts', [False, True])
def test_reset_ui_cancel_and_confirm(repo, accounts):
    from PySide6.QtWidgets import QApplication, QMessageBox
    from portman.accounts_dialog import AccountsDialog
    from portman.history_widget import HistoryWidget
    app = QApplication.instance() or QApplication([])
    add(repo, 'A')
    widget = AccountsDialog(repo, '.') if accounts else HistoryWidget(repo, lambda: None)
    action = widget.delete_all_accounts if accounts else widget.delete_all_imports
    changes = []
    (widget.changed if accounts else widget.data_changed).connect(lambda: changes.append(True))
    with patch.object(QMessageBox, 'exec', return_value=0):
        action()
    assert len(repo.imports()) == 1
    assert changes == []
    def confirm(box):
        assert box.defaultButton().text() == 'Abbrechen'
        for button in box.buttons():
            if box.buttonRole(button) == QMessageBox.ButtonRole.DestructiveRole:
                button.click()
        return 0
    with patch.object(QMessageBox, 'exec', confirm):
        action()
    assert repo.imports() == []
    assert changes == [True]
    app.processEvents()
    widget.close()

def test_ui_sorted_multiselect_cancel_and_confirm(repo):
    from PySide6.QtWidgets import QApplication, QMessageBox
    from PySide6.QtCore import Qt, QItemSelectionModel
    from portman.history_widget import HistoryWidget
    app = QApplication.instance() or QApplication([])
    ids = [add(repo,n)[0] for n in ['A','B','C']]
    widget = HistoryWidget(repo,lambda:None)
    widget.audit.sortItems(0,Qt.SortOrder.DescendingOrder)
    for row in (0,2):
        widget.audit.selectionModel().select(widget.audit.model().index(row,0), QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows)
    with patch.object(QMessageBox,'exec',return_value=0):
        widget.delete_selected_imports()
    assert len(repo.imports()) == 3
    changes=[]
    widget.data_changed.connect(lambda:changes.append(True))
    def confirm(box):
        for button in box.buttons():
            if box.buttonRole(button) == QMessageBox.ButtonRole.DestructiveRole:
                button.click()
        return 0
    with patch.object(QMessageBox,'exec',confirm):
        widget.delete_selected_imports()
    assert [r['id'] for r in repo.imports()] == [ids[1]]
    assert changes == [True]
    app.processEvents()
    widget.close()


def test_import_report_dialog_displays_nested_json_as_tree(qtbot):
    from portman.history_widget import JsonReportDialog
    report = {
        'source_sheet': 'Online comdirect',
        'warnings': ['Erster Hinweis', 'Zweiter Hinweis'],
        'account_assignments': {'Tagesgeld': 'Konto 1'},
        'valid': True,
        'optional': None,
    }
    dialog = JsonReportDialog(42, report)
    qtbot.addWidget(dialog)

    assert dialog.windowTitle() == 'Import 42 · Details'
    assert dialog.tree.topLevelItemCount() == len(report)
    labels = [dialog.tree.topLevelItem(row).text(0) for row in range(dialog.tree.topLevelItemCount())]
    assert labels == list(report)
    warnings = dialog.tree.topLevelItem(1)
    assert warnings.text(1) == '2 Einträge'
    assert warnings.child(0).text(0) == '[0]'
    assert warnings.child(0).text(1) == 'Erster Hinweis'
    assert '"Tagesgeld": "Konto 1"' in dialog.raw.toPlainText()
    assert dialog.raw.isReadOnly()
