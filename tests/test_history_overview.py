from copy import deepcopy
from portman.history_import import parse_history_file
from portman.history_overview_dialog import HistoryOverviewDialog
from PySide6.QtWidgets import QApplication, QDialog
from PySide6.QtCore import Qt
from test_history_batch import setup as setup


def test_one_row_per_name_and_batch_order(setup):
    folder,path,repo=setup
    QApplication.instance() or QApplication([])
    first,other,notes=parse_history_file(path)
    later=deepcopy(first);later.path=str(folder/'later.xlsx');later.source_sheet=' DEPOT A ';later.file_hash='later'
    dialog=HistoryOverviewDialog(repo,[first,other,notes,later])
    assert dialog.table.rowCount()==3
    dialog.groups['depot a']['target'].setCurrentIndex(dialog.groups['depot a']['target'].findData('ziel'))
    dialog.start.click()
    assert dialog.result()==QDialog.DialogCode.Accepted
    assert [b.path for b in dialog.selected]==[first.path,later.path]
    assert all(b.account_assignments=={'depot a':'ziel'} for b in dialog.selected)
    assert not repo.imports()
    assert all(r['status']=='imported' for r in repo.commit_batches(dialog.selected))
    dialog.close()


def test_global_duplicate_choice_and_cancel(setup):
    folder,path,repo=setup
    QApplication.instance() or QApplication([])
    batch=parse_history_file(path)[0]
    batch.account_assignments={'depot a':'ziel'}
    repo.commit_batches([batch])
    dialog=HistoryOverviewDialog(repo,[batch])
    combo=dialog.groups['depot a']['target'];combo.setCurrentIndex(combo.findData('ziel'))
    assert not dialog.planned_batches()
    dialog.duplicates.setCurrentIndex(1)
    assert dialog.planned_batches()[0].force_import
    dialog.groups['depot a']['skip'].setCheckState(Qt.CheckState.Checked)
    assert not dialog.planned_batches()
    dialog.reject()
    assert repo.history_skip_sheets()==[]
    assert len(repo.imports())==1
    dialog.close()


def test_skip_preferences_editable_in_overview(setup):
    folder,path,repo=setup
    QApplication.instance() or QApplication([])
    repo.set_history_skip_sheets(['depot a','not present'])
    dialog=HistoryOverviewDialog(repo,parse_history_file(path))
    group=dialog.groups['depot a']
    assert not group['target'].isEnabled()
    group['skip'].setCheckState(Qt.CheckState.Unchecked)
    assert group['target'].isEnabled()
    dialog.accept()
    assert repo.history_skip_sheets()==['not present']
    dialog.close()

def test_filters_keep_selection_and_show_rules(setup):
    folder, path, repo = setup
    QApplication.instance() or QApplication([])
    dialog = HistoryOverviewDialog(repo, parse_history_file(path))
    group = dialog.groups['depot a']
    group['target'].setCurrentIndex(group['target'].findData('ziel'))
    planned = dialog.planned_batches()
    dialog.filter.setCurrentIndex(1)
    assert dialog.table.isRowHidden(group['row'])
    assert dialog.planned_batches() == planned
    dialog.filter.setCurrentIndex(2)
    assert not dialog.table.isRowHidden(dialog.groups['notizen']['row'])
    dialog.filter.setCurrentIndex(0)
    dialog.search.setText('Depot A')
    assert not dialog.table.isRowHidden(group['row'])
    assert dialog.table.isRowHidden(dialog.groups['depot b']['row'])
    assert dialog.details_panel.isHidden()
    dialog.details_toggle.click()
    assert not dialog.details_panel.isHidden()
    assert dialog.skip_stack.currentWidget() is group['skip']
    group['skip'].setChecked(True)
    assert not dialog.planned_batches()
    assert not group['create'].isEnabled()
    group['skip'].setChecked(False)
    assert dialog.planned_batches() == planned
    dialog.search.setText('Kein Treffer')
    assert dialog.table.currentRow() == -1
    assert dialog.skip_stack.isHidden()
    assert dialog.planned_batches() == planned
    dialog.close()
