import os
import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import QEvent, QItemSelection, QItemSelectionModel, QSortFilterProxyModel, Qt
from PySide6.QtGui import QKeyEvent, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import QApplication, QLabel, QLineEdit, QTableView, QTreeWidget, QTreeWidgetItem

from portman.gui_copy_support import install_global_copy_support

_APP = None

@pytest.fixture(autouse=True)
def copy_application(qapp):
    global _APP
    _APP = qapp
    _APP.setQuitOnLastWindowClosed(False)
    install_global_copy_support(_APP)
    yield _APP


def app():
    return _APP


def table_with(values):
    model = QStandardItemModel()
    for row in values:
        model.appendRow([QStandardItem(value) for value in row])
    table = QTableView()
    table.setModel(model)
    table.show()
    app().processEvents()
    table.setFocus()
    return table


def copy_shortcut(table):
    send_shortcut(table, Qt.Key.Key_C)
    app().processEvents()
    return QApplication.clipboard().text()


def send_shortcut(widget, key):
    QApplication.sendEvent(widget, QKeyEvent(QEvent.Type.KeyPress, key,
                           Qt.KeyboardModifier.ControlModifier))
    QApplication.sendEvent(widget, QKeyEvent(QEvent.Type.KeyRelease, key,
                           Qt.KeyboardModifier.ControlModifier))


def test_single_cell_and_multiple_cells_copy_displayed_values_without_headers():
    table = table_with([['15.09.2026', 'A0H074', '9,10'],
                        ['15.09.2026', 'A0D8QZ', '10,36']])
    selection = table.selectionModel()
    selection.select(table.model().index(0, 1), QItemSelectionModel.SelectionFlag.Select)
    assert copy_shortcut(table) == 'A0H074\n'

    selection.clearSelection()
    selection.select(QItemSelection(table.model().index(0, 0), table.model().index(1, 2)),
                     QItemSelectionModel.SelectionFlag.Select)
    assert copy_shortcut(table) == ('15.09.2026\tA0H074\t9,10\n'
                                    '15.09.2026\tA0D8QZ\t10,36\n')
    table.close()


def test_ctrl_a_copies_complete_visible_table_and_skips_hidden_columns():
    table = table_with([['A', 'hidden', '1'], ['B', 'hidden', '2']])
    table.setColumnHidden(1, True)
    send_shortcut(table, Qt.Key.Key_A)
    assert copy_shortcut(table) == 'A\t1\nB\t2\n'
    table.close()


def test_copy_uses_current_proxy_sort_filter_and_visual_column_order():
    source = QStandardItemModel()
    for row in [('B', '2', 'drop'), ('A', '1', 'keep'), ('C', '3', 'keep')]:
        source.appendRow([QStandardItem(value) for value in row])
    proxy = QSortFilterProxyModel()
    proxy.setSourceModel(source)
    proxy.setFilterKeyColumn(2)
    proxy.setFilterFixedString('keep')
    proxy.sort(0, Qt.SortOrder.DescendingOrder)
    table = QTableView()
    table.setModel(proxy)
    table.show()
    app().processEvents()
    table.horizontalHeader().moveSection(1, 0)
    table.setFocus()
    send_shortcut(table, Qt.Key.Key_A)
    assert copy_shortcut(table) == '3\tC\tkeep\n1\tA\tkeep\n'
    table.close()


def test_read_only_label_and_editable_text_field_keep_native_copy_shortcuts():
    application = app()
    label = QLabel('Auswählbarer Statustext')
    label.show()
    application.processEvents()
    assert label.textInteractionFlags() & Qt.TextInteractionFlag.TextSelectableByMouse
    label.setSelection(0, len('Auswählbarer'))
    label.setFocus()
    send_shortcut(label, Qt.Key.Key_C)
    assert QApplication.clipboard().text() == 'Auswählbarer'

    field = QLineEdit('Editierbarer Text')
    field.show()
    field.setFocus()
    send_shortcut(field, Qt.Key.Key_A)
    send_shortcut(field, Qt.Key.Key_C)
    assert QApplication.clipboard().text() == 'Editierbarer Text'
    assert field.text() == 'Editierbarer Text'
    label.close(); field.close()


def test_copy_does_not_change_model_data():
    table = table_with([['unverändert', '42']])
    before = [table.model().index(0, column).data() for column in range(2)]
    send_shortcut(table, Qt.Key.Key_A)
    copy_shortcut(table)
    assert [table.model().index(0, column).data() for column in range(2)] == before
    table.close()


def test_complete_rows_and_columns_can_be_selected_and_copied():
    table = table_with([['A1', 'B1'], ['A2', 'B2']])
    selection = table.selectionModel()
    selection.select(table.model().index(1, 0),
                     QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows)
    assert copy_shortcut(table) == 'A2\tB2\n'
    selection.clearSelection()
    selection.select(table.model().index(0, 1),
                     QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Columns)
    assert copy_shortcut(table) == 'B1\nB2\n'
    table.close()


def test_default_table_context_menu_contains_copy_and_select_all():
    table = table_with([['A', '1']])
    assert table.contextMenuPolicy() == Qt.ContextMenuPolicy.ActionsContextMenu
    assert [action.text() for action in table.actions()[-2:]] == ['Kopieren', 'Alles auswählen']
    table.close()


def test_tabular_tree_uses_the_same_global_copy_support():
    tree = QTreeWidget()
    tree.setColumnCount(2)
    tree.addTopLevelItem(QTreeWidgetItem(['Depot', '4764924']))
    tree.show(); app().processEvents(); tree.setFocus(); tree.selectAll()
    assert copy_shortcut(tree) == 'Depot\t4764924\n'
    tree.close()
