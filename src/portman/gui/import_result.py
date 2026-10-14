"""Import completion dialog shared by the V07 and V09 windows."""
from PySide6.QtWidgets import QDialog, QLabel, QPushButton, QTableWidget, QVBoxLayout

from portman.widgets_shared import EvidenceDialog, populate


def show_import_results(window, results):
    dialog = QDialog(window); dialog.setWindowTitle('Import abgeschlossen'); dialog.resize(850, 440)
    layout = QVBoxLayout(dialog)
    layout.addWidget(QLabel('Auswahl gespeichert. Doppelklick auf eine Datei öffnet den lokalen Beleg.'))
    table = QTableWidget(); populate(table, ['Datei', 'Ergebnis', 'Import-ID'],
        [[r['path'], {'imported': 'Importiert', 'duplicate': 'Bereits vorhanden'}.get(r['status'], r['status']), r.get('id')] for r in results])
    table.cellDoubleClicked.connect(lambda row, column: EvidenceDialog.open_source(dialog, results[row]['path']))
    layout.addWidget(table)
    ids = [r['id'] for r in results if r['status'] == 'imported']
    undo = QPushButton('Diese neuen Importe zurücknehmen'); undo.setEnabled(bool(ids))

    def rollback():
        for iid in ids: window.repository.undo_import(iid)
        window.reload_portfolio(); window.refresh_scope_choices(); dialog.accept()

    undo.clicked.connect(rollback); layout.addWidget(undo)
    history = QPushButton('Importprotokoll ansehen')
    history.clicked.connect(lambda: (dialog.accept(), window.show_workspace('history'), window.history_widget.tabs.setCurrentIndex(3)))
    layout.addWidget(history); close = QPushButton('Schließen'); close.clicked.connect(dialog.accept); layout.addWidget(close)
    dialog.exec()
