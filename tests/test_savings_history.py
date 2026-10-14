import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from openpyxl import Workbook
from PySide6.QtWidgets import QApplication
from portfolio_v5.importers import parse_file
from portman.history_import import parse_savings_history_file, previous_sheet_imports
from portman.history_overview_dialog import HistoryOverviewDialog
from portman.repository import PortfolioRepository


def workbook(path):
    book = Workbook()
    sheet = book.active
    sheet.title = 'ETF'
    sheet.append([2026, 'Festgeld', 'Tagesgeld', 'Aktien'])
    sheet.append(['Bank', '1000,25', 200, 300])
    sheet.append(['Andere Bank', None, 0, None])
    sheet.append(['Gesamt', '1000,25', 200, 300])
    book.save(path)
    book.close()


def test_savings_separate_targets_repeat_and_undo(tmp_path):
    QApplication.instance() or QApplication([])
    path = tmp_path / 'finanzen2026-09.xlsx'
    workbook(path)
    repo = PortfolioRepository(tmp_path / 'db.sqlite')
    repo.create_accounts(['Tageskonto', 'Festkonto'])
    legacy = repo.commit_batches([parse_file(path)])[0]['id']
    batches = parse_savings_history_file(path)
    assert len(batches) == 3
    assert all(not b.snapshots and not b.account_names and not b.errors for b in batches)
    assert all(previous_sheet_imports(repo, b) == [legacy] for b in batches)
    dialog = HistoryOverviewDialog(repo, batches, savings=True)
    for group in dialog.groups.values():
        b = group['valid'][0]
        group['target'].setCurrentIndex(0)
        if b.balances[0].account == 'Bank':
            target = 'tageskonto' if b.balances[0].category == 'Liquidität' else 'festkonto'
            group['target'].setCurrentIndex(group['target'].findData(target))
    assert dialog.planned_batches() == []
    dialog.duplicates.setCurrentIndex(1)
    planned = dialog.planned_batches()
    assert len(planned) == 2
    results = repo.commit_batches(planned)
    balances = repo.store.balances()
    assert {(b['account'], b['category'], b['value']) for b in balances} == {
        ('Tageskonto', 'Liquidität', '200.00'), ('Festkonto', 'Festgeld', '1000.25'),
        ('Bank', 'Wertpapiere', '300.00'), ('Andere Bank', 'Liquidität', '0.00')}
    for result in results:
        repo.undo_import(result['id'])
    assert {b['account'] for b in repo.store.balances()} == {'Bank', 'Andere Bank'}
    dialog.close()
    repo.close()


def test_month_groups_cancel_and_missing_month(tmp_path):
    QApplication.instance() or QApplication([])
    repo = PortfolioRepository(tmp_path / 'db.sqlite')
    repo.create_accounts(['Ziel'])
    batches = []
    for month in ('08', '09'):
        path = tmp_path / f'finanzen2026-{month}.xlsx'
        workbook(path)
        batches.extend(parse_savings_history_file(path))
    dialog = HistoryOverviewDialog(repo, batches, savings=True)
    assert len(dialog.groups) == 3
    assert all(len(g['valid']) == 2 for g in dialog.groups.values())
    assert any(b.balances[0].value == '0.00' for b in batches)
    dialog.reject()
    assert not repo.imports()
    path = tmp_path / 'finanzen2026.xlsx'
    workbook(path)
    assert all(b.errors and not b.balances for b in parse_savings_history_file(path))
    dialog.close()
    repo.close()

def test_new_overview_revision_supersedes_partial_import(tmp_path):
    path = tmp_path / 'finanzen2026-09.xlsx'
    workbook(path)
    repo = PortfolioRepository(tmp_path / 'db.sqlite')
    repo.create_accounts(['Ziel'])
    batch = next(b for b in parse_savings_history_file(path)
                 if b.balances[0].category == 'Festgeld')
    batch.account_assignments = {'bank': 'ziel'}
    repo.commit_batches([batch])
    assert len(repo.store.balances()) == 1
    overview = parse_file(path)
    overview.balances = [b for b in overview.balances if b.category != 'Festgeld']
    overview.account_assignments = {'bank': 'ziel'}
    latest = repo.commit_batches([overview])[0]['id']
    assert not any(b['category'] == 'Festgeld' for b in repo.store.balances())
    repo.undo_import(latest)
    assert [b['category'] for b in repo.store.balances()] == ['Festgeld']
    repo.close()

def test_create_account_in_import_preserves_other_assignments(tmp_path, monkeypatch):
    from portman.account_editor import AccountEditor
    from PySide6.QtWidgets import QDialog
    QApplication.instance() or QApplication([])
    path = tmp_path / 'finanzen2026-09.xlsx'
    workbook(path)
    repo = PortfolioRepository(tmp_path / 'db.sqlite')
    repo.create_accounts(['Bestehend'])
    dialog = HistoryOverviewDialog(repo, parse_savings_history_file(path), savings=True)
    groups = list(dialog.groups.items())
    key, chosen = next((k, g) for k, g in groups if g['valid'][0].balances[0].category == 'Festgeld')
    other = next(g for k, g in groups if k != key)
    other['target'].setCurrentIndex(other['target'].findData('bestehend'))

    def save_editor(editor):
        assert editor.kind.currentText() == 'Festgeld'
        editor.fields['name'].setText('Neues Festgeld')
        editor.save()
        return editor.result()

    monkeypatch.setattr(AccountEditor, 'exec', save_editor)
    chosen['create'].click()
    assert dialog.accounts_created
    new_key = chosen['target'].currentData()
    assert chosen['target'].currentText() == 'Neues Festgeld'
    assert other['target'].currentData() == 'bestehend'
    assert all(g['target'].findData(new_key) > 0 for g in dialog.groups.values())
    selected = next(b for b in dialog.planned_batches() if b.balances[0].category == 'Festgeld')
    assert selected.account_assignments == {'bank': new_key}
    assert repo.commit_batches([selected])[0]['status'] == 'imported'
    assert repo.store.balances()[0]['account'] == 'Neues Festgeld'
    monkeypatch.setattr(AccountEditor, 'exec', lambda editor: QDialog.DialogCode.Rejected)
    before = repo.account_records()
    chosen['create'].click()
    assert repo.account_records() == before
    assert chosen['target'].currentData() == new_key
    dialog.reject()
    assert any(r['name'] == 'Neues Festgeld' for r in repo.account_records())
    dialog.close()
    repo.close()

def test_savings_suggestions_respect_account_kind(tmp_path):
    QApplication.instance() or QApplication([])
    path = tmp_path / 'finanzen2026-09.xlsx'
    workbook(path)
    repo = PortfolioRepository(tmp_path / 'db.sqlite')
    repo.save_account('Bank', {'kind': 'Tagesgeld'})
    dialog = HistoryOverviewDialog(repo, parse_savings_history_file(path), savings=True)
    fixed = next(g for g in dialog.groups.values() if g['kind'] == 'Festgeld')
    daily = next(g for g in dialog.groups.values() if g['name'] == 'Bank' and g['kind'] == 'Tagesgeld')
    assert fixed['target'].currentData() is None
    assert daily['target'].currentData() == 'bank'
    fixed['target'].setCurrentIndex(fixed['target'].findData('bank'))
    dialog.table.selectRow(fixed['row'])
    assert 'Kontotyp' in dialog.details.toPlainText()
    assert dialog.group_has_notes(fixed)
    repo.save_account('Bank / Festgeld', {'kind': 'Festgeld'})
    dialog.close()
    dialog = HistoryOverviewDialog(repo, parse_savings_history_file(path), savings=True)
    fixed = next(g for g in dialog.groups.values() if g['kind'] == 'Festgeld')
    assert fixed['target'].currentText() == 'Bank / Festgeld'
    dialog.close(); repo.close()
