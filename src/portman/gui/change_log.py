"""Change history dialog shared by the V07 and V09 windows."""
from PySide6.QtWidgets import QDialog, QTableWidget, QVBoxLayout

from portman.widgets_shared import populate


def show_change_log(window):
    dialog = QDialog(window)
    dialog.setWindowTitle('Änderungshistorie · letzte 2.000 Änderungen'); dialog.resize(1100, 650)
    layout = QVBoxLayout(dialog); table = QTableWidget(); layout.addWidget(table)
    rows = window.repository.db.execute(
        'SELECT changed_at,entity,operation,old_data,new_data FROM change_log ORDER BY id DESC LIMIT 2000').fetchall()
    populate(table, ['Zeit (UTC)', 'Bereich', 'Aktion', 'Vorher', 'Nachher'], rows)
    dialog.exec()
