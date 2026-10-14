import os
import pytest
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from portman.history_import import history_files, parse_history_file, previous_sheet_imports
from portman.repository import PortfolioRepository

@pytest.fixture
def setup(tmp_path):
    from openpyxl import Workbook
    folder=tmp_path/'history';folder.mkdir()
    path=folder/'finanzen2026-9.xlsx'
    book=Workbook()
    for index,name in enumerate(['Depot A','Depot B','Notizen']):
        sheet=book.active if index==0 else book.create_sheet()
        sheet.title=name
        if name!='Notizen':
            sheet.append(['Stichtag', '15.09.2026'])
            sheet.append(['ISIN','Name','Anzahl','Wert'])
            sheet.append(['DE0000000001','Beispiel','6,847','100,00'])
        else: sheet.append(['Freier Text'])
    book.save(path);book.close()
    repo=PortfolioRepository(tmp_path/'db.sqlite');repo.create_accounts(['Ziel'])
    yield folder,path,repo
    repo.close()


def test_scan_and_isolated_sheets(setup):
    folder,path,repo=setup
    (folder/'~$lock.xlsx').write_text('lock')
    (folder/'ignore.csv').write_text('csv')
    batches=parse_history_file(path)
    assert history_files(folder)==[path]
    assert [b.source_sheet for b in batches]==['Depot A','Depot B','Notizen']
    assert all(len(b.snapshots)==1 for b in batches[:2])
    assert batches[2].errors
    assert batches[0].snapshots[0].positions[0].quantity=='6.847'


def test_sheet_repeat_really_imports_and_preserves_quantity(setup):
    folder,path,repo=setup
    batch=parse_history_file(path)[0]
    batch.account_assignments={'depot a':'ziel'}
    first=repo.commit_batches([batch])[0]
    assert previous_sheet_imports(repo,batch)==[first['id']]
    assert not previous_sheet_imports(repo,parse_history_file(path)[1])
    assert repo.commit_batches([batch])[0]['status']=='duplicate'
    batch.force_import=True
    second=repo.commit_batches([batch])[0]
    assert second['status']=='imported' and second['snapshots']==1
    assert len(repo.holdings())==1
    assert repo.holdings()[0]['quantity']=='6.847'
    assert len(repo.imports())==2


def test_legacy_workbook_detection(setup):
    from portfolio_v5.importers import parse_file
    folder,path,repo=setup
    iid=repo.commit_batches([parse_file(path)])[0]['id']
    assert previous_sheet_imports(repo,parse_history_file(path)[0])==[iid]
    repo.undo_import(iid)
    assert previous_sheet_imports(repo,parse_history_file(path)[1])==[iid]


@pytest.mark.skip(reason='Legacy: portman.history_import_dialog wurde durch import_ui_v09/history_widget ersetzt.')
def test_wizard_collect_skip_cancel_and_repeat(setup):
    from PySide6.QtWidgets import QApplication
    from portman.history_import_dialog import HistoryImportDialog
    folder,path,repo=setup
    QApplication.instance() or QApplication([])
    batches=parse_history_file(path)
    dialog=HistoryImportDialog(repo,batches)
    assert 'Depot A' in dialog.title.text()
    dialog.target.setCurrentIndex(dialog.target.findData('ziel'))
    dialog.take_sheet()
    assert 'Depot B' in dialog.title.text()
    dialog.skip_sheet();dialog.skip_sheet()
    assert len(dialog.selected)==1 and dialog.skipped==2
    assert not repo.imports()
    dialog.reject()
    assert not repo.imports()
    repo.commit_batches(dialog.selected)
    repeated=HistoryImportDialog(repo,batches)
    assert 'bereits importiert' in repeated.message.text()
    repeated.target.setCurrentIndex(repeated.target.findData('ziel'))
    repeated.take_sheet()
    assert repeated.selected[0].force_import
    repeated.close();dialog.close()

@pytest.mark.skip(reason='Legacy: portman.history_import_dialog wurde durch import_ui_v09/history_widget ersetzt.')
def test_same_sheet_assigned_once_but_duplicates_and_errors_stop(setup):
    from copy import deepcopy
    from PySide6.QtWidgets import QApplication
    from portman.history_import_dialog import HistoryImportDialog
    folder,path,repo=setup
    QApplication.instance() or QApplication([])
    first=parse_history_file(path)[0]
    following=deepcopy(first);following.path=str(folder/'finanzen2026-10.xlsx');following.source_sheet=' depot a '
    duplicate=deepcopy(first)
    duplicate.account_assignments={'depot a':'ziel'}
    repo.commit_batches([duplicate])
    # Start with a new file, followed by another new file and a known sheet.
    start=deepcopy(first);start.path=str(folder/'finanzen2026-8.xlsx')
    broken=deepcopy(following);broken.errors=['Defektes Blatt']
    dialog=HistoryImportDialog(repo,[start,following,first,broken])
    dialog.target.setCurrentIndex(dialog.target.findData('ziel'))
    dialog.take_sheet()
    assert dialog.index==2
    assert len(dialog.selected)==2
    assert dialog.selected[1].account_assignments=={'depot a':'ziel'}
    assert not dialog.target.isEnabled()
    assert 'bereits importiert' in dialog.message.text()
    dialog.skip_sheet()
    assert dialog.index==3 and not dialog.next.isEnabled()
    dialog.skip_sheet()
    assert 'Batch bereit' in dialog.title.text()
    assert len(repo.imports())==1
    dialog.reject();dialog.close()

@pytest.mark.skip(reason='Legacy: portman.history_import_dialog wurde durch import_ui_v09/history_widget ersetzt.')
def test_start_selected_before_all_questions_are_answered(setup):
    from copy import deepcopy
    from PySide6.QtWidgets import QApplication, QDialog
    from portman.history_import_dialog import HistoryImportDialog
    folder,path,repo=setup
    QApplication.instance() or QApplication([])
    first,unanswered,_=parse_history_file(path)
    later=deepcopy(first);later.path=str(folder/'later.xlsx');later.file_hash='later'
    duplicate=deepcopy(first);duplicate.path=str(folder/'old.xlsx');duplicate.file_hash='old'
    duplicate.account_assignments={'depot a':'ziel'}
    repo.commit_batches([duplicate])
    broken=deepcopy(later);broken.errors=['Defekt']
    dialog=HistoryImportDialog(repo,[first,unanswered,later,duplicate,broken])
    assert not dialog.start_selected.isEnabled()
    dialog.target.setCurrentIndex(dialog.target.findData('ziel'))
    dialog.take_sheet()
    assert dialog.index==1 and dialog.start_selected.isEnabled()
    dialog.start_selected.click()
    assert dialog.result()==QDialog.DialogCode.Accepted
    assert [b.path for b in dialog.selected]==[first.path,later.path]
    assert all(not b.force_import for b in dialog.selected)
    assert len(repo.imports())==1  # Dialog only prepares; caller saves.
    assert all(r['status']=='imported' for r in repo.commit_batches(dialog.selected))
    dialog.close()

@pytest.mark.skip(reason='Legacy: portman.history_import_dialog wurde durch import_ui_v09/history_widget ersetzt.')
def test_future_skip_persists_only_when_saved_and_can_be_removed(setup):
    from copy import deepcopy
    from unittest.mock import patch
    from PySide6.QtWidgets import QApplication, QInputDialog
    from portman.history_import_dialog import HistoryImportDialog
    from portman.repository import PortfolioRepository
    folder,path,repo=setup
    QApplication.instance() or QApplication([])
    original=parse_history_file(path)[0]
    following=deepcopy(original);following.source_sheet=' DEPOT A '
    dialog=HistoryImportDialog(repo,[original,following])
    dialog.skip_future.click()
    assert dialog.index==2 and dialog.skipped==2 and not dialog.selected
    assert repo.history_skip_sheets()==[]
    dialog.reject()
    assert repo.history_skip_sheets()==[]
    dialog=HistoryImportDialog(repo,[original,following])
    dialog.skip_future.click();dialog.next.click()
    assert repo.history_skip_sheets()==['depot a']
    reopened=PortfolioRepository(repo.store.path)
    try:
        later=HistoryImportDialog(reopened,[original,following])
        assert later.index==2 and not later.selected
        with patch.object(QInputDialog,'getItem',return_value=('depot a',True)):
            later.restore_skip.click()
        later.next.click()
        assert reopened.history_skip_sheets()==[]
        again=HistoryImportDialog(reopened,[original])
        assert again.index==0
        again.close();later.close()
    finally:
        reopened.close()
    dialog.close()

def test_processing_failure_retains_sheet_names_and_other_sheets(setup):
    from unittest.mock import patch
    from portfolio_v5.importers import parse_file
    folder,path,repo=setup
    def parse(path, **kwargs):
        if 'Depot A' in kwargs['sheets']:
            raise TypeError('Beispielfehler im Importer')
        return parse_file(path, **kwargs)
    with patch('portman.history_import.parse_file',side_effect=parse):
        batches=parse_history_file(path)
    assert [b.source_sheet for b in batches]==['Depot A','Depot B','Notizen']
    assert 'TypeError' in batches[0].errors[0]
    assert 'Beispielfehler im Importer' in batches[0].errors[0]
    assert len(batches[1].snapshots)==1


def test_read_failure_reports_actual_error(setup):
    from unittest.mock import patch
    folder,path,repo=setup
    with patch('portman.history_import.read_sheets',side_effect=PermissionError('Datei gesperrt')):
        batches=parse_history_file(path)
    assert len(batches)==1
    assert 'PermissionError' in batches[0].errors[0]
    assert 'Datei gesperrt' in batches[0].errors[0]
