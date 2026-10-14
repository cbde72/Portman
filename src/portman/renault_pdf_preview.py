"""Read-only preview before the Renault statement replacement import."""
from .date_display import display_dates
from pathlib import Path
from copy import deepcopy
import re

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QDialog, QDialogButtonBox,
    QLabel, QLineEdit, QSplitter, QTableWidget, QTableWidgetItem, QTabWidget,
    QVBoxLayout, QPushButton, QMessageBox)

from .renault_pdf_import import prepare_renault_batch


class RenaultPdfPreviewDialog(QDialog):
    def __init__(self, repository, batches, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Renault PDF · Importvorschau')
        self.resize(1200, 760)
        self.repo = repository
        self.batches = deepcopy(list(batches))
        self.prepared = []
        self.problems = []
        self.existing = repository.transactions()
        accounts = {r['account_key']: r['name'] for r in repository.account_records()}
        layout = QVBoxLayout(self)
        note = QLabel('Konto automatisch zugeordnet. Datei auswählen, um die erkannten Buchungen zu sehen. '
                      'Beim Import werden vorhandene Kontobuchungen im Auszugszeitraum ersetzt. '
                      'Nicht gewünschte Dateien können abgewählt werden.')
        note.setWordWrap(True)
        layout.addWidget(note)
        split = QSplitter(Qt.Orientation.Vertical)
        layout.addWidget(split, 1)
        self.files = self.table(['Import', 'Datei', 'Dokumenttyp', 'Zielkonto',
                                'Anfangsstand vom', 'Endstand vom', 'Buchungen', 'Zu ersetzen', 'Status'])
        split.addWidget(self.files)
        self.files.setRowCount(len(self.batches))
        for row, batch in enumerate(self.batches):
            try:
                prepared = prepare_renault_batch(repository, batch)
                problem = ''
            except ValueError as error:
                prepared, problem = None, str(error)
            self.prepared.append(prepared)
            self.problems.append(problem)
            target = ', '.join(accounts[key] for key in prepared.account_assignments.values()) if prepared else 'Nicht importierbar'
            dates = [re.search(pattern + r'\s*(\d{2}\.\d{2}\.\d{4})', batch.pdf_text, re.I)
                     for pattern in ('alter Kontostand vom', 'neuer Kontostand vom')]
            values = ['', Path(batch.path).name, batch.document_type, target,
                      *[match[1] if match else 'Unbekannt' for match in dates],
                      len(batch.transactions), len(prepared.replace_bank_bookings) if prepared else '–',
                      problem or 'Bereit']
            for col, value in enumerate(values):
                self.put(self.files, row, col, value)
            item = self.files.item(row, 0)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if prepared else Qt.CheckState.Unchecked)
            if prepared is None:
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
        self.files.resizeColumnsToContents()
        self.files.setColumnWidth(1, 260)
        self.files.setColumnWidth(8, 300)
        self.tabs = QTabWidget()
        split.addWidget(self.tabs)
        columns = ['Buchungstag', 'Valuta', 'Konto', 'Betrag', 'Währung', 'Verwendungszweck']
        self.bookings = self.table(columns)
        self.replacements = self.table(columns)
        self.tabs.addTab(self.bookings, 'Erkannte Buchungen')
        self.tabs.addTab(self.replacements, 'Vorhandene Buchungen · werden ersetzt')
        self.search = QLineEdit()
        self.search.setPlaceholderText('Buchungen der ausgewählten Datei durchsuchen …')
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.filter_rows)
        layout.addWidget(self.search)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.status)
        self.correct_button = QPushButton('Ausgewählte Datei: Daten / Fehler anpassen …')
        self.correct_button.clicked.connect(self.correct_file)
        layout.addWidget(self.correct_button)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.files.itemSelectionChanged.connect(self.show_file)
        self.files.itemChanged.connect(self.update_selection)
        if self.batches:
            self.files.selectRow(0)
        self.update_selection()

    def correct_file(self):
        from .import_preview import ImportPreviewDialog
        row = self.files.currentRow()
        if row < 0:
            return
        original = self.batches[row]
        if original.errors:
            QMessageBox.warning(self, 'Datei nicht lesbar', '\n'.join(original.errors) +
                '\nBitte die Quelldatei korrigieren und erneut auswählen.')
            return
        editor = ImportPreviewDialog(self.repo, [deepcopy(original)], self)
        editor.setWindowTitle('Import korrigieren · Konto und PDF-Buchungen')
        if editor.exec() != QDialog.DialogCode.Accepted:
            return
        corrected = editor.selected_batches()[0]
        corrected.pdf_reviewed = True
        try:
            prepared = prepare_renault_batch(self.repo, corrected)
            problem = ''
        except ValueError as error:
            prepared, problem = None, str(error)
        # Keep the corrections in this preview even if a further fix is needed.
        self.batches[row] = corrected
        self.prepared[row] = prepared
        self.problems[row] = problem
        accounts = {r['account_key']: r['name'] for r in self.repo.account_records()}
        self.files.blockSignals(True)
        self.put(self.files, row, 3, ', '.join(accounts[key] for key in corrected.account_assignments.values()))
        self.put(self.files, row, 6, len(corrected.transactions))
        self.put(self.files, row, 7, len(prepared.replace_bank_bookings) if prepared else '–')
        self.put(self.files, row, 8, problem or 'Korrigiert · Bereit')
        item = self.files.item(row, 0)
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEnabled if prepared else item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
        item.setCheckState(Qt.CheckState.Checked if prepared else Qt.CheckState.Unchecked)
        self.files.blockSignals(False)
        self.show_file()
        self.update_selection()

    @staticmethod
    def table(headers):
        table = QTableWidget(0, len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        table.setAlternatingRowColors(True)
        table.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        return table

    @staticmethod
    def put(table, row, col, value):
        item = QTableWidgetItem(display_dates(str(value)))
        item.setToolTip(display_dates(str(value)))
        table.setItem(row, col, item)

    def selected_batches(self):
        # Re-prepare sequentially at commit so overlapping files replace each other.
        return [batch for row, batch in enumerate(self.batches)
                if self.prepared[row] is not None and self.files.item(row, 0).checkState() == Qt.CheckState.Checked]

    def update_selection(self, *args):
        count = len(self.selected_batches())
        button = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        button.setText(display_dates(f'{count} Auszüge importieren / aktualisieren'))
        button.setEnabled(count > 0)

    def show_file(self):
        row = self.files.currentRow()
        if row < 0:
            return
        batch, prepared = self.batches[row], self.prepared[row]
        incoming = [vars(tx) for tx in batch.transactions]
        refs = {(r['import_id'], r['depot'], r['external_id']) for r in prepared.replace_bank_bookings} if prepared else set()
        existing = [tx for tx in self.existing if (tx['import_id'], tx['depot'], tx['external_id']) in refs]
        for table, transactions in ((self.bookings, incoming), (self.replacements, existing)):
            table.setRowCount(len(transactions))
            for r, tx in enumerate(transactions):
                values = [tx.get(key, '') for key in ('date', 'value_date', 'account', 'amount', 'currency', 'purpose')]
                values[3] = str(values[3]).replace('.', ',')
                for col, value in enumerate(values):
                    self.put(table, r, col, value)
            table.resizeColumnsToContents()
            table.setColumnWidth(5, 520)
        self.status.setText(display_dates(self.problems[row] or f'{len(incoming)} erkannte Buchungen · {len(existing)} vorhandene Buchungen werden ersetzt. '
            'Überlappende ausgewählte Auszüge werden in Dateireihenfolge verarbeitet.'))
        self.filter_rows()

    def filter_rows(self, *args):
        query = self.search.text().strip().casefold()
        for table in (self.bookings, self.replacements):
            for row in range(table.rowCount()):
                text = ' '.join(table.item(row, col).text() for col in range(table.columnCount())).casefold()
                table.setRowHidden(row, bool(query and query not in text))
