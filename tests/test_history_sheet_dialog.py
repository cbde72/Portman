import os

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtWidgets import QApplication
from portfolio_v5.models import ImportBatch, Balance
from portman.repository import PortfolioRepository
from portman.history_sheet_dialog import HistorySheetDialog


def test_exactly_one_sheet_existing_account_and_persistent_marker(tmp_path):
    QApplication.instance() or QApplication([])
    repo = PortfolioRepository(tmp_path / 'test.sqlite')
    repo.create_accounts(['Ziel'])
    batches = [ImportBatch(str(tmp_path / f'{i}.xlsx'), str(i),
        balances=[Balance('2026-09', 'Liquidität', 'Quelle', '100', 'Blatt', 1)],
        source_sheet='Blatt') for i in range(2)]
    dialog = HistorySheetDialog(repo, batches)
    reopened = None
    try:
        assert not dialog.start.isEnabled()
        dialog.table.selectRow(0)
        assert not dialog.start.isEnabled()
        dialog.target.setCurrentIndex(1)
        assert dialog.start.isEnabled()
        dialog.accept()
        assert len(dialog.selected) == 2
        assert [b.path for b in dialog.selected] == [b.path for b in batches]
        assert set(dialog.selected[0].account_assignments.values()) == {'ziel'}
        assert batches[1].account_assignments == {}
        # Accepting the preview does not mark an uncommitted import.
        assert repo.imports() == []
        assert repo.commit_batches(dialog.selected)[0]['status'] == 'imported'
        reopened = HistorySheetDialog(repo, batches)
        assert reopened.table.rowCount() == 1
        assert reopened.table.item(0, 2).text() == 'Importiert'
        assert repo.balances()[0]['account'] == 'Ziel'
        assert repo.commit_batches(dialog.selected)[0]['status'] == 'duplicate'
    finally:
        dialog.close()
        if reopened: reopened.close()
        repo.close()


def test_error_and_cancel_do_not_mark_sheet(tmp_path):
    QApplication.instance() or QApplication([])
    repo = PortfolioRepository(tmp_path / 'test.sqlite')
    repo.create_accounts(['Ziel'])
    dialog = HistorySheetDialog(repo, [ImportBatch('bad.xlsx', 'bad', source_sheet='Bad', errors=['Fehler'])])
    try:
        dialog.table.selectRow(0)
        dialog.target.setCurrentIndex(1)
        assert not dialog.start.isEnabled()
        dialog.accept()
        assert not dialog.selected
        dialog.reject()
        assert repo.imports() == []
    finally:
        dialog.close()
        repo.close()


def test_all_monthly_excel_states_for_ing_comdirect_zero(tmp_path):
    from openpyxl import Workbook
    from portman.history_import import parse_history_file
    QApplication.instance() or QApplication([])
    batches = []
    for month in (8, 9):
        path = tmp_path / f'finanzen2026-{month}.xlsx'
        book = Workbook()
        for index, bank in enumerate(('ING', 'comdirect', 'ZERO')):
            sheet = book.active if index == 0 else book.create_sheet()
            sheet.title = bank
            sheet.append(['Stichtag', f'15.{month:02d}.2026'])
            sheet.append(['ISIN', 'Name', 'Anzahl', 'Wert'])
            sheet.append(['DE0000000001', 'Beispiel', str(month), str(month * 100)])
        book.save(path)
        book.close()
        batches.extend(parse_history_file(path))
    repo = PortfolioRepository(tmp_path / 'all.sqlite')
    repo.create_accounts(['Ziel ING', 'Ziel comdirect', 'Ziel ZERO'])
    try:
        for bank in ('ING', 'comdirect', 'ZERO'):
            dialog = HistorySheetDialog(repo, batches)
            try:
                row = next(i for i in range(dialog.table.rowCount()) if dialog.table.item(i, 0).text() == bank)
                dialog.table.selectRow(row)
                dialog.target.setCurrentIndex(dialog.target.findText('Ziel ' + bank))
                dialog.accept()
                assert len(dialog.selected) == 2
                assert all(b.source_sheet == bank for b in dialog.selected)
                assert all(r['status'] == 'imported' for r in repo.commit_batches(dialog.selected))
                states = repo.state_history('Ziel ' + bank)
                assert len(states) == 2
                assert {r['value'] for r in states} == {'800.00', '900.00'}
                assert all(r['status'] == 'duplicate' for r in repo.commit_batches(dialog.selected))
            finally:
                dialog.close()
    finally:
        repo.close()



def test_historical_sheet_updates_existing_depot_stream(tmp_path):
    from portfolio_v5.models import Snapshot, Position
    from portman.accounts_widget import AccountsWidget
    QApplication.instance() or QApplication([])
    repo = PortfolioRepository(tmp_path / 'existing.sqlite')
    repo.create_accounts(['Mein Depot'])
    repo.commit_batches([ImportBatch('online', 'online', snapshots=[
        Snapshot('Online Depot 123', '2026-09', '2026-09-29', 'Online ING',
                 [Position('A', 'Aktie', value='200')])],
        account_assignments={'online depot 123': 'mein depot'})])
    historical = ImportBatch('old.xlsx', 'old', source_sheet='ING', snapshots=[
        Snapshot('ING', '2026-08', '2026-08-12', 'ING', [Position('A', 'Aktie', value='100')])])
    dialog = HistorySheetDialog(repo, [historical])
    widget = None
    try:
        dialog.table.selectRow(0)
        dialog.target.setCurrentIndex(dialog.target.findData('mein depot'))
        dialog.accept()
        repo.commit_batches(dialog.selected)
        assert len(repo.depots()) == 1
        assert repo.holdings(account='Mein Depot')[0]['value'] == '200'
        assert repo.holdings('2026-08-31', 'Mein Depot')[0]['value'] == '100'
        widget = AccountsWidget(repo, lambda: '9999-12-31')
        group = widget.tree.topLevelItem(0)
        depot = next(group.child(i) for i in range(group.childCount()) if group.child(i).text(0) == 'Mein Depot')
        assert depot.childCount() == 0
    finally:
        if widget: widget.close()
        dialog.close()
        repo.close()
