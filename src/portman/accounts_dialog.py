import json
from .account_editor import AccountEditor, BalanceDialog
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QPushButton, QTableWidget, QTableWidgetItem,
    QTextEdit, QVBoxLayout,
)

from portfolio_v5.accounts import account_key, discover_accounts


class AccountScan(QThread):
    result = Signal(object)
    progress = Signal(int, int)

    def __init__(self, folder, parent):
        super().__init__(parent)
        self.folder = folder

    def run(self):
        try:
            self.result.emit(discover_accounts(self.folder, self.progress.emit))
        except Exception as exc:
            self.result.emit({'accounts': [], 'files': 0, 'warnings': [str(exc)]})


class AccountImportPreview(QDialog):
    def __init__(self, result, repository, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Konten aus ETF / Spalte A')
        self.resize(850, 550)
        self.entries = result['accounts']
        records = {r['account_key']: r for r in repository.account_records()}
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"{result['files']} Excel-Dateien geprüft · {len(self.entries)} unterschiedliche Konten"))
        self.table = QTableWidget(len(self.entries), 4)
        self.table.setHorizontalHeaderLabels(['Anlegen', 'Konto', 'Status', 'Fundstellen'])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        for row, entry in enumerate(self.entries):
            old = records.get(account_key(entry['name']))
            status = 'Neu' if old is None else ('Vorhanden' if old['active'] else 'Entfernt – bleibt entfernt')
            for col, value in enumerate(['', entry['name'], status, f"{len(entry['sources'])} Dateien"]):
                self.table.setItem(row, col, QTableWidgetItem(value))
            check = self.table.item(row, 0)
            check.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable if old is None else Qt.ItemFlag.NoItemFlags)
            check.setCheckState(Qt.CheckState.Checked if old is None else Qt.CheckState.Unchecked)
            self.table.item(row, 3).setToolTip('\n'.join(entry['sources']))
        self.table.resizeColumnsToContents()
        layout.addWidget(self.table)
        if result['warnings']:
            notes = QTextEdit()
            notes.setReadOnly(True)
            notes.setPlainText('\n'.join(result['warnings']))
            notes.setMaximumHeight(120)
            layout.addWidget(notes)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText('Ausgewählte Konten anlegen')
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def selected_names(self):
        return [entry['name'] for row, entry in enumerate(self.entries)
                if self.table.item(row, 0).checkState() == Qt.CheckState.Checked]


class AccountsDialog(QDialog):
    changed = Signal()

    def __init__(self, repository, history_folder, parent=None):
        super().__init__(parent)
        self.repo = repository
        self.history_folder = Path(history_folder)
        self.worker = None
        self.setWindowTitle('Konten verwalten')
        self.resize(1100, 600)
        layout = QVBoxLayout(self)
        note = QLabel('Konten automatisch aus history / ETF / Spalte A übernehmen oder manuell anlegen. '
                      'Entfernte Konten werden aus Auswahl und Auswertungen ausgeblendet. Historische Daten bleiben erhalten.')
        note.setWordWrap(True)
        layout.addWidget(note)
        bar = QHBoxLayout()
        self.scan_button = QPushButton('Aus Excel erkennen …')
        self.scan_button.clicked.connect(self.scan)
        manual = QPushButton('Manuell anlegen …')
        manual.clicked.connect(self.create_manual)
        for button in (self.scan_button, manual):
            bar.addWidget(button)
        layout.addLayout(bar)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(['Konto', 'Kontotyp', 'Übergeordnetes Konto', 'Status', 'Herkunft'])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.itemSelectionChanged.connect(self.update_actions)
        self.table.cellDoubleClicked.connect(lambda *_: self.edit_account())
        self.table.setAlternatingRowColors(True)
        layout.addWidget(self.table)
        bar = QHBoxLayout()
        self.edit_button = QPushButton('Details bearbeiten …')
        self.edit_button.clicked.connect(self.edit_account)
        self.child_button = QPushButton('Unterkonto anlegen …')
        self.child_button.clicked.connect(lambda: self.edit_account(child=True))
        self.balance_button = QPushButton('Saldo & Historie …')
        self.balance_button.clicked.connect(self.edit_balance)
        self.booking_button = QPushButton('Ein- / Ausbuchen …')
        self.booking_button.clicked.connect(self.manual_booking)
        bar.addWidget(self.booking_button)
        for button in (self.edit_button, self.child_button, self.balance_button): bar.addWidget(button)
        self.remove_button = QPushButton('Konto löschen')
        self.remove_button.clicked.connect(lambda: self.set_active(False))
        self.restore_button = QPushButton('Wiederherstellen')
        self.restore_button.clicked.connect(lambda: self.set_active(True))
        bar.addWidget(self.remove_button)
        bar.addWidget(self.restore_button)
        layout.addLayout(bar)
        self.status = QLabel()
        layout.addWidget(self.status)
        reset = QPushButton('Alle Konten löschen …')
        reset.clicked.connect(self.delete_all_accounts)
        layout.addWidget(reset)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.refresh()

    def delete_all_accounts(self):
        from .reset_data import confirm_reset
        if self.worker is not None and self.worker.isRunning():
            self.status.setText('Die Dateiprüfung läuft noch. Bitte kurz warten.')
            return
        if confirm_reset(self, self.repo, accounts=True):
            self.refresh()
            self.status.setText('Alle Konten und Importe wurden gelöscht. Du kannst neu anfangen.')
            self.changed.emit()

    def refresh(self):
        self.records = self.repo.account_records()
        self.table.setRowCount(len(self.records))
        for row, record in enumerate(self.records):
            for col, value in enumerate([record['name'], json.loads(record['details']).get('kind', 'Sonstiges'), next((r['name'] for r in self.records if r['account_key'] == record['parent_key']), '–'), 'Aktiv' if record['active'] else 'Gelöscht', record['source']]):
                self.table.setItem(row, col, QTableWidgetItem(value))
        self.table.resizeColumnsToContents()
        self.update_actions()

    def update_actions(self):
        row = self.table.currentRow()
        record = self.records[row] if 0 <= row < len(self.records) else None
        for button in (self.edit_button, self.child_button, self.balance_button, self.booking_button): button.setEnabled(bool(record and record['active']))
        self.remove_button.setEnabled(bool(record and record['active']))
        self.restore_button.setEnabled(bool(record and not record['active']))

    def create_manual(self):
        dialog = AccountEditor(self.repo, parent=self)
        if dialog.exec():
            self.refresh(); self.changed.emit()

    def edit_account(self, checked=False, child=False):
        row = self.table.currentRow()
        if row < 0: return
        record = self.records[row]
        dialog = AccountEditor(self.repo, None if child else record,
                               record['account_key'] if child else None, self)
        if dialog.exec():
            self.refresh(); self.changed.emit()

    def edit_balance(self):
        row = self.table.currentRow()
        if row < 0: return
        if BalanceDialog(self.repo, self.records[row]['name'], self).exec():
            self.refresh(); self.changed.emit()

    def manual_booking(self):
        from .manual_booking_dialog import ManualBookingDialog
        row = self.table.currentRow()
        if row < 0: return
        if ManualBookingDialog(self.repo, self.records[row]['name'], self).exec():
            self.refresh(); self.changed.emit()

    def set_active(self, active):
        row = self.table.currentRow()
        if not 0 <= row < len(self.records):
            return
        name = self.records[row]['name']
        self.repo.set_account_active(name, active)
        self.refresh()
        self.status.setText(f'{name}: ' + ('wiederhergestellt.' if active else 'entfernt; historische Daten bleiben erhalten.'))
        self.changed.emit()

    def scan(self):
        self.scan_button.setEnabled(False)
        self.status.setText('Excel-Dateien werden geprüft …')
        self.worker = AccountScan(self.history_folder, self)
        self.worker.progress.connect(lambda i, total: self.status.setText(f'Prüfe Excel-Datei {i} von {total} …'))
        self.worker.result.connect(self.show_preview)
        self.worker.finished.connect(lambda: self.scan_button.setEnabled(True))
        self.worker.start()

    def show_preview(self, result):
        preview = AccountImportPreview(result, self.repo, self)
        if preview.exec() == QDialog.DialogCode.Accepted:
            count = self.repo.create_accounts(preview.selected_names(), 'Excel: ETF / Spalte A')
            self.refresh()
            self.changed.emit()
            self.status.setText(f'{count} Konten angelegt. Einzelne Konten können unten entfernt werden.')
        else:
            self.status.setText('Kontenimport abgebrochen.')

    def reject(self):
        if self.worker is not None and self.worker.isRunning():
            self.status.setText('Die Dateiprüfung läuft noch. Bitte kurz warten.')
            return
        super().reject()

    def closeEvent(self, event):
        if self.worker is not None and self.worker.isRunning():
            event.ignore()
        else:
            super().closeEvent(event)
