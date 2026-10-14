from PySide6.QtCore import Qt

from portman.gui.checkable_combo import ALL_ROLE, CheckableComboBox


def test_all_accounts_has_checkmark_and_individual_selection_replaces_it(qtbot):
    combo = CheckableComboBox()
    qtbot.addWidget(combo)
    combo.set_items('Alle Konten', [('Girokonto', 'giro'), ('Depot', 'depot')])

    assert combo.model().item(0).data(ALL_ROLE)
    assert combo.model().item(0).checkState() == Qt.CheckState.Checked
    assert combo.checked_data() == []

    combo._handle_item_pressed(combo.model().index(1, 0))
    assert combo.model().item(0).checkState() == Qt.CheckState.Unchecked
    assert combo.checked_data() == ['giro']

    combo._handle_item_pressed(combo.model().index(0, 0))
    assert combo.model().item(0).checkState() == Qt.CheckState.Checked
    assert combo.checked_data() == []


def test_restoring_empty_scope_checks_all_accounts(qtbot):
    combo = CheckableComboBox()
    qtbot.addWidget(combo)
    combo.set_items('Alle Konten', [('Girokonto', 'giro')])
    combo.restore_checked(['giro'])
    assert combo.model().item(0).checkState() == Qt.CheckState.Unchecked
    combo.restore_checked([])
    assert combo.model().item(0).checkState() == Qt.CheckState.Checked
