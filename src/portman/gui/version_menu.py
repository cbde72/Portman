"""Version helper menu shared by the V07 and V09 windows."""
from PySide6.QtCore import QUrl
from PySide6.QtGui import QAction, QDesktopServices


def install_version_menu(window, title):
    menu = window.menuBar().addMenu(title)
    for item, action in [('Veränderungen und Bestände abstimmen', window.open_analysis),
                         ('Belege und Datenherkunft', window.open_evidence),
                         ('Datensicherung / Wiederherstellung', window.open_recovery),
                         ('Änderungshistorie', window.open_change_log),
                         ('Datenordner öffnen',
                          lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(window.data_folder))))]:
        entry = QAction(item, window); entry.triggered.connect(action); menu.addAction(entry)
    return menu
