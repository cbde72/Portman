"""Model-backed position tables shared by the V07 and V09 windows."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox, QDialog, QVBoxLayout, QListWidget, QListWidgetItem, QDialogButtonBox, QLabel, QInputDialog

from portman.positions_model import PositionFilter, PositionTable, PositionsModel


def build_position_table(window, category):
    if not hasattr(window, 'positions_model'):
        window.positions_model = PositionsModel(window)
    proxy = PositionFilter(category, window)
    proxy.setSourceModel(window.positions_model)
    table = PositionTable()
    table.setModel(proxy)
    table.setProperty('table_type', 'positions')
    table.setSortingEnabled(True)
    table.setAlternatingRowColors(True)
    table.setShowGrid(True)
    table.setGridStyle(Qt.PenStyle.SolidLine)
    table.setStyleSheet('QTableView { gridline-color: palette(midlight); }')
    table.verticalHeader().hide()
    table.horizontalHeader().setDefaultAlignment(Qt.AlignmentFlag.AlignCenter)
    table.horizontalHeader().sectionDoubleClicked.connect(lambda _section: configure_columns(window))
    return table


def refresh_position_tables(window):
    if not hasattr(window, 'positions_model') or not hasattr(window, 'position_search'):
        return
    from portman.price_history import historical_positions
    first = {p['key']: p['history_start'] for p in historical_positions(window.repository, window.dashboard_scope()[0])}
    window.positions_model.reset(window.holdings.values(), window.repository.market.records(), window.repository.market.mappings(), first)
    for table in window.tables.values():
        table.model().filters(window.combo_region.currentText(), window.combo_cap.currentText(),
                              window.position_search.text())


def open_position_editor(window, index=None):
    table = window.tables[window.get_current_category()]
    index = index if index is not None else table.currentIndex()
    if not index.isValid():
        QMessageBox.information(window, 'Position wählen', 'Bitte zuerst eine Position auswählen.')
        return
    from portman.classification_dialog import WertpapierEditDialog
    revision = window.repository.db.total_changes
    try:
        accepted = WertpapierEditDialog(
            window.repository, index.data(Qt.ItemDataRole.UserRole), window).exec()
    except ValueError as error:
        QMessageBox.warning(window, 'Wertpapier nicht verfügbar', str(error))
        return
    if accepted or window.repository.db.total_changes != revision:
        window.reload_portfolio()


def edit_wkn_cell(window, index):
    if index.model().headerData(index.column(), Qt.Orientation.Horizontal) == 'Erste Aktivität':
        from portman.price_history import save_first_activity
        value, accepted = QInputDialog.getText(window, 'Erste Aktivität ändern',
            'Datum (TT.MM.JJJJ oder JJJJ-MM-TT). Leer: automatisch aus Beständen.', text=index.data() if index.data() != '–' else '')
        if accepted:
            try:
                if '.' in value: value = '-'.join(reversed(value.strip().split('.')))
                save_first_activity(window.repository, window.dashboard_scope()[0], index.data(Qt.ItemDataRole.UserRole), value)
                window.reload_portfolio()
            except ValueError as error:
                QMessageBox.warning(window, 'Datum prüfen', str(error))
        return True

    if index.model().headerData(index.column(), Qt.Orientation.Horizontal) != 'WKN':
        return False
    key = index.data(Qt.ItemDataRole.UserRole)
    record = window.repository.metadata().get(key, {})
    value, accepted = QInputDialog.getText(window, 'WKN eintragen',
        f"{record.get('canonical_name', key)}\nWKN (6 Zeichen, gilt für alle Depots):", text=record.get('wkn') or '')
    if accepted:
        try:
            window.repository.save_wkn(key, value)
            window.reload_portfolio()
        except ValueError as error:
            QMessageBox.warning(window, 'WKN prüfen', str(error))
    return True


def install_edit_button(window):
    """Compatibility hook; editing is exposed through table double clicks only."""


def configure_columns(window):
    table = window.tables[window.get_current_category()]
    dialog = QDialog(window)
    dialog.setWindowTitle('Spalten auswählen · ' + window.get_current_category())
    layout = QVBoxLayout(dialog)
    layout.addWidget(QLabel('Spalten anhaken und durch Ziehen in die gewünschte Reihenfolge bringen.'))
    choices = QListWidget()
    choices.setDragDropMode(QListWidget.DragDropMode.InternalMove)
    choices.setDefaultDropAction(Qt.DropAction.MoveAction)
    layout.addWidget(choices)
    for visual in range(table.model().columnCount()):
        column = table.horizontalHeader().logicalIndex(visual)
        item = QListWidgetItem(str(table.model().headerData(column, Qt.Orientation.Horizontal)))
        item.setData(Qt.ItemDataRole.UserRole, column)
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(Qt.CheckState.Unchecked if table.isColumnHidden(column) else Qt.CheckState.Checked)
        choices.addItem(item)
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)
    dialog.resize(620, 520)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return
    for row in range(choices.count()):
        item = choices.item(row)
        column = item.data(Qt.ItemDataRole.UserRole)
        table.horizontalHeader().moveSection(table.horizontalHeader().visualIndex(column), row)
        table.setColumnHidden(column, item.checkState() != Qt.CheckState.Checked)
    window.save_settings()


class ModelTablesMixin:
    """V07/V09 defaults for the position-table factory hooks."""

    def create_position_table(self, category):
        return build_position_table(self, category)

    def refresh_tables(self):
        refresh_position_tables(self)

    def restore_column_widths(self):
        return None
