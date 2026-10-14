"""A single review screen for comdirect cash bookings and their own accounts."""
from copy import deepcopy
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QDialog, QDialogButtonBox,
    QApplication, QHeaderView, QLabel, QPushButton, QSplitter, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget)

from portfolio_v5.accounts import account_key
from .date_display import display_dates
from .import_combo_style import style_target_account_combo


def cash_batch(original):
    batch = deepcopy(original)
    if batch.document_type != 'comdirect Finanzreport':
        raise ValueError('Kein comdirect-Finanzreport erkannt.')
    if batch.errors:
        raise ValueError('\n'.join(batch.errors))
    owners = {t.account for t in batch.transactions} | {b.account for b in batch.balances} | {s.account for s in batch.snapshots}
    if not owners:
        raise ValueError('Keine Kontobuchungen oder Kontosalden erkannt.')
    batch.account_names = sorted(owners)
    batch.documents = [d for d in batch.documents if d.account in owners]
    batch.force_import = False
    batch.replace_bank_bookings = []
    batch.account_assignments = {}
    batch.new_accounts = []
    batch.remember_assignments = []
    return batch


class ComdirectPdfPreviewDialog(QDialog):
    def __init__(self, repository, batches, parent=None):
        super().__init__(parent)
        self.setWindowTitle('comdirect · Finanzreports importieren')
        self.resize(1100, 780)
        self.batches = []
        self.choices = {}
        self.sources = {}
        layout = QVBoxLayout(self)
        note = QLabel('Buchungen, Kontosalden und Depotwerte importieren. Konten werden anhand ihrer IBAN zugeordnet. '
                      'Zielkonto bei Bedarf ändern und auf „Importieren“ klicken.')
        note.setWordWrap(True)
        layout.addWidget(note)
        split = QSplitter(Qt.Orientation.Vertical)
        layout.addWidget(split, 1)
        self.files = self.table(['Import', 'Datei', 'Buchungen', 'Depotwert (EUR)', 'Status'])
        split.addWidget(self.files)
        self.files.setRowCount(len(batches))
        for row, original in enumerate(batches):
            try:
                batch = cash_batch(original)
                problem = ''
                for source in repository.import_account_suggestions(batch):
                    entry = self.sources.setdefault(source['key'], dict(source, targets=set()))
                    if source['target_key']:
                        entry['targets'].add(source['target_key'])
            except ValueError as error:
                batch, problem = None, str(error)
            self.batches.append(batch)
            for col, value in enumerate(['', Path(original.path).name,
                                         len(batch.transactions) if batch else '–',
                                         self.depot_value(batch) if batch else '–', problem or 'Bereit']):
                self.put(self.files, row, col, value)
            item = self.files.item(row, 0)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if batch else Qt.CheckState.Unchecked)
            if not batch:
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
            urgent = next((warning for warning in original.warnings
                           if warning.startswith('PRÜFUNG ERFORDERLICH:')), '')
            if urgent:
                status = self.files.item(row, 4)
                status.setText(urgent)
                status.setToolTip(urgent)
                status.setForeground(QColor('#DC2626'))
                font = status.font(); font.setBold(True); status.setFont(font)
        self.files.setColumnWidth(0, 60)
        self.files.setColumnWidth(1, 370)
        self.files.setColumnWidth(2, 90)
        self.files.setColumnWidth(3, 135)
        self.files.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)

        self.accounts = self.table(['Eigenes Konto / IBAN im Report', 'Zielkonto'])
        split.addWidget(self.accounts)
        all_records = repository.account_records()
        records = [r for r in all_records if r['active']]
        self.accounts.setRowCount(len(self.sources))
        for row, (key, source) in enumerate(self.sources.items()):
            self.put(self.accounts, row, 0, source['name'])
            combo = QComboBox()
            style_target_account_combo(combo)
            combo.addItem('Zielkonto wählen …', None)
            for record in records:
                combo.addItem(record['name'], record['account_key'])
            # New accounts are created only on Import, never while reviewing.
            if not any(r['account_key'] == key for r in all_records):
                combo.addItem('Neues Konto: ' + source['name'], '__new__')
            combo.addItem('Dieses Konto auslassen', '__skip__')
            targets = source['targets']
            if len(targets) == 1:
                combo.setCurrentIndex(max(0, combo.findData(next(iter(targets)))))
            elif not targets and source['name'].startswith(('IBAN ', 'Depot ')):
                # Ambiguous matches must still be chosen, never silently duplicated.
                if 'mehreren' not in source['reason'] and 'gelöscht' not in source['reason']:
                    combo.setCurrentIndex(max(0, combo.findData('__new__')))
            self.accounts.setCellWidget(row, 1, combo)
            self.choices[key] = combo
            combo.currentIndexChanged.connect(self.update_selection)
        self.accounts.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.accounts.verticalHeader().setDefaultSectionSize(52)

        detail = QWidget()
        details = QVBoxLayout(detail)
        details.setContentsMargins(0, 0, 0, 0)
        self.detail_note = QLabel('Buchungen der ausgewählten Datei')
        details.addWidget(self.detail_note)
        self.bookings = self.table(['Buchungstag', 'Valuta', 'Eigenes Konto / IBAN', 'Betrag (EUR)', 'Buchungstext'])
        details.addWidget(self.bookings)
        self.bookings.setColumnWidth(2, 245)
        self.bookings.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.positions = self.table(['WKN', 'Wertpapier', 'Stück', 'Kurswert (EUR)', 'Kaufwert (EUR)'])
        self.positions.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        details.addWidget(self.positions)
        split.addWidget(detail)
        split.setSizes([180, 170, 300])
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.status)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText('Importieren')
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('Abbrechen')
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        copy_status = QPushButton('Status kopieren')
        copy_status.clicked.connect(self.copy_status)
        self.buttons.addButton(copy_status, QDialogButtonBox.ButtonRole.ActionRole)
        layout.addWidget(self.buttons)
        self.files.itemSelectionChanged.connect(self.show_file)
        self.files.itemChanged.connect(self.update_selection)
        if batches:
            self.files.selectRow(0)
        self.update_selection()

    @staticmethod
    def depot_value(batch):
        from decimal import Decimal
        if not batch.snapshots:
            return '–'
        total = sum((Decimal(p.value) for s in batch.snapshots for p in s.positions), Decimal(0))
        return f'{total:,.2f}'.replace(',', '_').replace('.', ',').replace('_', '.')

    @staticmethod
    def table(headers):
        table = QTableWidget(0, len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        table.setAlternatingRowColors(True)
        table.setWordWrap(False)
        return table

    @staticmethod
    def put(table, row, col, value):
        text = display_dates(str(value))
        item = QTableWidgetItem(text)
        item.setToolTip(text)
        table.setItem(row, col, item)

    def selected_batches(self):
        result = []
        for row, original in enumerate(self.batches):
            if original is None or self.files.item(row, 0).checkState() != Qt.CheckState.Checked:
                continue
            batch = deepcopy(original)
            included = set()
            for name in batch.account_names:
                key = account_key(name)
                target = self.choices[key].currentData()
                if target is None:
                    raise ValueError('Zielkonto für ' + name + ' wählen.')
                if target == '__skip__':
                    continue
                included.add(name)
                if target == '__new__':
                    batch.new_accounts.append(name)
                    target = key
                batch.account_assignments[key] = target
                batch.remember_assignments.append(key)
            evidence = [(t, e) for t, e in zip(batch.transactions, batch.pdf_booking_evidence) if t.account in included]
            batch.transactions = [t for t in batch.transactions if t.account in included]
            batch.pdf_booking_evidence = [e for _, e in evidence]
            batch.balances = [b for b in batch.balances if b.account in included]
            batch.snapshots = [s for s in batch.snapshots if s.account in included]
            batch.documents = [d for d in batch.documents if d.account in included]
            batch.account_names = sorted(included)
            if included:
                result.append(batch)
        return result

    def update_selection(self, *args):
        try:
            files = count = positions = 0
            for row, batch in enumerate(self.batches):
                if batch is None or self.files.item(row, 0).checkState() != Qt.CheckState.Checked:
                    continue
                included = set()
                for name in batch.account_names:
                    target = self.choices[account_key(name)].currentData()
                    if target is None:
                        raise ValueError('Zielkonto für ' + name + ' wählen.')
                    if target != '__skip__':
                        included.add(name)
                files += bool(included)
                count += sum(t.account in included for t in batch.transactions)
                positions += sum(len(s.positions) for s in batch.snapshots if s.account in included)
            self.status.setText(f'{files} Dateien · {count} Buchungen · {positions} Depotpositionen. Bereits vorhandene Daten werden erkannt.')
            enabled = bool(files)
        except ValueError as error:
            self.status.setText(str(error))
            enabled = False
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(enabled)
        self.show_file()

    def show_file(self):
        row = self.files.currentRow()
        batch = self.batches[row] if row >= 0 else None
        transactions = [t for t in batch.transactions
                        if self.choices[account_key(t.account)].currentData() != '__skip__'] if batch else []
        self.bookings.setRowCount(len(transactions))
        for row, tx in enumerate(transactions):
            values = [tx.date, tx.value_date, tx.account, tx.amount.replace('.', ','), tx.purpose]
            for col, value in enumerate(values):
                self.put(self.bookings, row, col, value)
                if 'interest_reconciliation' in tx.field_sources:
                    item = self.bookings.item(row, col)
                    item.setForeground(QColor('#DC2626'))
                    font = item.font(); font.setBold(True); item.setFont(font)
                    item.setToolTip(tx.field_sources['interest_reconciliation'])
        positions = [p for s in batch.snapshots if self.choices[account_key(s.account)].currentData() != '__skip__'
                     for p in s.positions] if batch else []
        self.positions.setVisible(bool(batch and batch.snapshots))
        self.positions.setRowCount(len(positions))
        for row, position in enumerate(positions):
            values = [position.wkn, position.name, position.quantity, position.value, position.cost]
            for col, value in enumerate(values):
                self.put(self.positions, row, col, str(value).replace('.', ',') if col >= 2 and value is not None else value or '–')
        self.detail_note.setText(f'{len(transactions)} Buchungen · ' + Path(batch.path).name if batch else 'Datei nicht importierbar')

    def copy_status(self):
        lines = [self.status.text()]
        for row, original in enumerate(self.batches):
            name = self.files.item(row, 1).text()
            state = self.files.item(row, 4).text()
            lines.append(f'{name}: {state}')
            if original:
                lines.extend('Hinweis: ' + warning for warning in original.warnings)
                lines.extend('Fehler: ' + error for error in original.errors)
        QApplication.clipboard().setText('\n'.join(lines))
