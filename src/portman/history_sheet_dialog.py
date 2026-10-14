"""Select one sheet name across all workbooks and an existing account."""
from copy import deepcopy

from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QDialog,
    QDialogButtonBox, QLabel, QMessageBox, QTableWidget, QTableWidgetItem,
    QTextEdit, QVBoxLayout)

from portfolio_v5.import_accounts import import_sources
from .history_import import previous_sheet_imports, sheet_import_index
from .import_combo_style import style_target_account_combo


class HistorySheetDialog(QDialog):
    def __init__(self, repository, batches, parent=None):
        super().__init__(parent)
        self.repo, self.batches, self.selected = repository, batches, []
        self.groups = []
        grouped = {}
        for batch in batches:
            key = batch.source_sheet.strip().casefold()
            grouped.setdefault(key, []).append(batch)
        self.groups = list(grouped.values())
        self.setWindowTitle('History: Blatt aus allen Excel-Dateien importieren')
        self.resize(950, 650)
        layout = QVBoxLayout(self)
        note = QLabel('Einen Blattnamen auswählen: Alle zugehörigen Stände aus allen Excel-Dateien werden dem Zielkonto hinzugefügt. '
                      'Nach erfolgreichem Import erscheint hier „Importiert“. Die Excel-Datei bleibt unverändert.')
        note.setWordWrap(True)
        layout.addWidget(note)
        known = sheet_import_index(repository)
        active = {r['id'] for r in repository.imports() if r['active']}
        self.table = QTableWidget(len(self.groups), 3)
        self.table.setHorizontalHeaderLabels(['Tabellenblatt', 'Dateien', 'Status'])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setStretchLastSection(True)
        for row, group in enumerate(self.groups):
            count = sum(bool(active.intersection(previous_sheet_imports(repository, batch, known))) for batch in group)
            errors = sum(bool(batch.errors) for batch in group)
            status = 'Importiert' if count == len(group) else f'{count} / {len(group)} importiert'
            if errors: status += f' · {errors} Fehler'
            for column, value in enumerate((group[0].source_sheet.strip() or '–', str(len(group)), status)):
                item = QTableWidgetItem(value)
                item.setToolTip('\n'.join(batch.path for batch in group))
                self.table.setItem(row, column, item)
        self.table.resizeColumnsToContents()
        layout.addWidget(self.table)
        layout.addWidget(QLabel('Vorhandenes Zielkonto'))
        self.target = QComboBox()
        style_target_account_combo(self.target)
        self.target.addItem('Konto auswählen …', None)
        for record in repository.account_records():
            if record['active']: self.target.addItem(record['name'], record['account_key'])
        layout.addWidget(self.target)
        self.details = QTextEdit()
        self.details.setReadOnly(True)
        layout.addWidget(self.details)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.start = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.start.setText('Ausgewähltes Blatt importieren')
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('Abbrechen')
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.table.itemSelectionChanged.connect(self.update_selection)
        self.target.currentIndexChanged.connect(self.update_selection)
        self.update_selection()

    def current_group(self):
        rows = self.table.selectionModel().selectedRows()
        return self.groups[rows[0].row()] if len(rows) == 1 else []

    def update_selection(self):
        group = self.current_group()
        valid = any(not batch.errors and import_sources(batch) for batch in group)
        self.start.setEnabled(valid and bool(self.target.currentData()))
        self.start.setText(f'Blatt aus {len(group)} Dateien importieren')
        lines = []
        for batch in group:
            summary = batch.summary()
            lines.append(f'{batch.path}\n{batch.source_sheet}\n'
                f"{summary['snapshots']} Depotstände · {summary['balances']} Salden · {summary['transactions']} Buchungen\n"
                + '\n'.join(batch.errors + summary['warnings']))
        self.details.setPlainText('\n\n'.join(lines) or 'Bitte einen Blattnamen auswählen.')

    def accept(self):
        group, target = self.current_group(), self.target.currentData()
        if not group or not target or not any(not b.errors and import_sources(b) for b in group): return
        if target not in {r['account_key'] for r in self.repo.account_records() if r['active']}:
            QMessageBox.warning(self, 'Zielkonto fehlt', 'Bitte ein vorhandenes aktives Konto auswählen.')
            return
        self.selected = []
        # A workbook is a historical observation of the selected depot, not a
        # second position stream to add to its online/current holdings.
        existing = [d for d in self.repo.depots() if d['account_key'] == target]
        sources = {s.account for b in group for s in b.snapshots}
        single_depot = len(sources) == 1 and bool(sources)
        if single_depot and len(existing) > 1:
            QMessageBox.warning(self, 'Depotzuordnung prüfen',
                'Diesem Konto sind mehrere Depotquellen zugeordnet. Bitte diese zuerst '
                'den jeweiligen vorhandenen Depots zuordnen, damit historische Stände nicht doppelt gezählt werden.')
            return
        destination = existing[0]['depot_name'] if single_depot and existing else self.target.currentText()
        for batch in group:
            selected = deepcopy(batch)
            if single_depot:
                for snapshot in selected.snapshots:
                    snapshot.account = destination
            selected.account_assignments = {source['key']: target for source in import_sources(selected)}
            selected.new_accounts = []
            selected.force_import = batch.force_import
            self.selected.append(selected)
        # Keep failed sheets in the result so the caller reports incomplete imports.
        super().accept()
