"""One account choice per sheet name for the entire history folder."""
from collections import defaultdict
from copy import deepcopy
from pathlib import Path
import json
from portfolio_v5.accounts import account_key
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QDialog, QDialogButtonBox,
    QHeaderView, QLabel, QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QTextEdit, QVBoxLayout,
    QHBoxLayout, QWidget, QLineEdit, QCheckBox, QStackedWidget)
from portfolio_v5.import_accounts import import_sources
from .history_import import previous_sheet_imports
from .import_combo_style import style_target_account_combo


class HistoryOverviewDialog(QDialog):
    def __init__(self, repository, batches, parent=None, savings=False):
        super().__init__(parent)
        self.repo, self.savings, self.batches = repository, savings, batches
        self.selected = []
        self.accounts_created = False
        self.groups = {}
        self.setWindowTitle('History: Tagesgeld und Festgeld' if savings else 'History importieren')
        self.resize(1120, 740)
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        title = QLabel('Tagesgeld und Festgeld importieren' if savings else 'History importieren')
        title.setObjectName('pageTitle')
        layout.addWidget(title)
        note = QLabel('Quelle: Tabellenblatt ETF · Jede Bank und Anlageart einmal für alle Monatsdateien zuordnen.' if savings
                      else 'Jeden Blattnamen einmal für alle Dateien zuordnen.')
        note.setWordWrap(True)
        note.setObjectName('muted')
        layout.addWidget(note)
        self.overview = QLabel()
        layout.addWidget(self.overview)
        controls = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText('Bank oder Zielkonto suchen …' if savings else 'Blatt oder Zielkonto suchen …')
        self.search.setClearButtonEnabled(True)
        controls.addWidget(self.search, 1)
        self.filter = QComboBox()
        self.filter.addItems(['Alle', 'Nicht zugeordnet', 'Mit Hinweisen'])
        controls.addWidget(self.filter)
        self.duplicates = QComboBox()
        self.duplicates.addItem('Vorhandene überspringen', False)
        self.duplicates.addItem('Vorhandene erneut importieren', True)
        if any(batch.force_import for batch in batches):
            self.duplicates.setCurrentIndex(1)
        self.duplicates.setToolTip('Gilt für den gesamten Batch, auch für ausgefilterte Zeilen.')
        controls.addWidget(self.duplicates)
        layout.addLayout(controls)
        grouped = defaultdict(list)
        self.file_errors = []
        for batch in batches:
            if batch.source_sheet.strip():
                grouped[batch.source_sheet.strip().casefold()].append(batch)
            else:
                self.file_errors.append(f"{Path(batch.path).name}: {'; '.join(batch.errors)}")
        self.table = QTableWidget(len(grouped), 5)
        self.table.setHorizontalHeaderLabels(['Bank' if savings else 'Excel-Blatt', 'Anlageart',
            'Monatsstände' if savings else 'Blätter', 'Zielkonto', 'Status'])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(52)
        self.table.setWordWrap(False)
        layout.addWidget(self.table, 1)
        self.details_toggle = QPushButton('Details und Regeln anzeigen')
        self.details_toggle.setCheckable(True)
        layout.addWidget(self.details_toggle, 0, Qt.AlignmentFlag.AlignLeft)
        self.details_panel = QWidget()
        detail_layout = QVBoxLayout(self.details_panel)
        detail_layout.setContentsMargins(0, 0, 0, 0)
        self.skip_stack = QStackedWidget()
        self.skip_stack.setMaximumHeight(34)
        detail_layout.addWidget(self.skip_stack)
        self.details = QTextEdit()
        self.details.setReadOnly(True)
        self.details.setMaximumHeight(150)
        detail_layout.addWidget(self.details)
        layout.addWidget(self.details_panel)
        self.details_panel.hide()
        accounts = [r for r in repository.account_records() if r['active']]
        self.saved_skips = set(repository.history_skip_sheets())
        from .history_import import sheet_import_index
        known = sheet_import_index(repository)
        for row, (key, group) in enumerate(sorted(grouped.items())):
            valid = [b for b in group if not b.errors and import_sources(b)]
            old = {id(b): previous_sheet_imports(repository, b, index=known) for b in valid}
            name = group[0].source_sheet.strip()
            kind = '–'
            if savings and valid:
                balance = valid[0].balances[0]
                name = balance.account
                kind = 'Tagesgeld' if balance.category == 'Liquidität' else 'Festgeld'
            elif savings:
                from .history_import import SAVINGS_PREFIX
                name = name.removeprefix(SAVINGS_PREFIX)
            elif valid and any(b.snapshots for b in valid):
                kind = 'Depot'
            for col, value in enumerate([name, kind, f'{len(valid)} / {len(group)}']):
                item = QTableWidgetItem(value)
                item.setToolTip(value if col != 2 else f'{len(valid)} importierbar · {len(group)} insgesamt · {sum(bool(old[id(b)]) for b in valid)} bereits importiert')
                self.table.setItem(row, col, item)
            target = QComboBox()
            style_target_account_combo(target)
            target.setMinimumWidth(150)
            target.addItem('Zielkonto wählen …', None)
            for account in accounts:
                target.addItem(account['name'], account['account_key'])
            cell = QWidget()
            cell_layout = QHBoxLayout(cell)
            cell_layout.setContentsMargins(4, 3, 4, 3)
            cell_layout.setSpacing(4)
            cell_layout.addWidget(target, 1)
            create = QPushButton('+')
            create.setFixedWidth(34)
            create.setToolTip('Neues Konto anlegen und dieser Quelle zuordnen')
            create.setAccessibleName('Neues Konto anlegen')
            create.clicked.connect(lambda checked=False, key=key: self.create_account(key))
            cell_layout.addWidget(create)
            self.table.setCellWidget(row, 3, cell)
            skip = QCheckBox('Diese Quelle künftig überspringen')
            skip.setCheckState(Qt.CheckState.Checked if key in self.saved_skips else Qt.CheckState.Unchecked)
            self.skip_stack.addWidget(skip)
            status = QTableWidgetItem()
            self.table.setItem(row, 4, status)
            self.groups[key] = {'batches': group, 'valid': valid, 'old': old, 'target': target,
                'skip': skip, 'row': row, 'create': create, 'name': name, 'kind': kind, 'status': status}
            if key not in self.saved_skips and valid:
                suggested = {s['target_key'] for b in valid for s in repository.import_account_suggestions(b)}
                if len(suggested) == 1 and None not in suggested:
                    proposed = next(iter(suggested))
                    record = next((a for a in accounts if a['account_key'] == proposed), None)
                    if not savings or self.compatible_kind(record, kind):
                        target.setCurrentIndex(max(0, target.findData(proposed)))
                if savings and not target.currentData():
                    matching = [a for a in accounts if self.compatible_kind(a, kind)
                        and account_key(a['name']).split('/')[0].strip() == account_key(name)]
                    if len(matching) == 1:
                        target.setCurrentIndex(target.findData(matching[0]['account_key']))
            target.currentIndexChanged.connect(self.update_summary)
            skip.stateChanged.connect(self.update_summary)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        for col, width in [(1, 105), (2, 110), (4, 170)]:
            self.table.setColumnWidth(col, width)
        account_note = QLabel('+ Neues Konto anlegen · Gespeicherte Konten bleiben beim Abbrechen erhalten.')
        account_note.setObjectName('muted')
        account_note.setWordWrap(True)
        layout.addWidget(account_note)
        footer = QHBoxLayout()
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        footer.addWidget(self.summary, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.start = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.start.setObjectName('primary')
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('Abbrechen')
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        footer.addWidget(buttons)
        layout.addLayout(footer)
        self.table.itemSelectionChanged.connect(self.show_details)
        self.duplicates.currentIndexChanged.connect(self.update_summary)
        self.search.textChanged.connect(self.apply_filter)
        self.filter.currentIndexChanged.connect(self.apply_filter)
        self.details_toggle.toggled.connect(self.toggle_details)
        self.update_summary()
        if self.groups:
            self.table.selectRow(0)
        self.show_details()

    @staticmethod
    def compatible_kind(record, kind):
        if not record:
            return False
        configured = json.loads(record['details']).get('kind', '')
        if configured and configured != 'Sonstiges':
            return configured == kind
        name = record['name'].casefold()
        opposite = 'festgeld' if kind == 'Tagesgeld' else 'tagesgeld'
        return opposite not in name

    def toggle_details(self, visible):
        self.details_panel.setVisible(visible)
        self.details_toggle.setText('Details und Regeln ausblenden' if visible else 'Details und Regeln anzeigen')

    def apply_filter(self, *args):
        query = self.search.text().strip().casefold()
        mode = self.filter.currentIndex()
        for group in self.groups.values():
            skipped = group['skip'].isChecked()
            unassigned = bool(group['valid']) and not skipped and not group['target'].currentData()
            warning = self.group_has_notes(group)
            haystack = f"{group['name']} {group['kind']} {group['target'].currentText()}".casefold()
            visible = (not query or query in haystack) and (mode == 0 or mode == 1 and unassigned or mode == 2 and warning)
            self.table.setRowHidden(group['row'], not visible)
        current = self.table.currentRow()
        if current < 0 or self.table.isRowHidden(current):
            self.table.clearSelection()
            self.table.setCurrentCell(-1, -1)
            first = next((g['row'] for g in self.groups.values() if not self.table.isRowHidden(g['row'])), None)
            if first is not None:
                self.table.selectRow(first)
        self.show_details()

    def group_has_notes(self, group):
        mismatch = False
        if self.savings and group['target'].currentData():
            record = next((r for r in self.repo.account_records() if r['account_key'] == group['target'].currentData()), None)
            mismatch = not self.compatible_kind(record, group['kind'])
        return mismatch or any(b.errors or b.summary()['warnings'] for b in group['batches'])

    def create_account(self, key):
        from .account_editor import AccountEditor
        from portfolio_v5.accounts import account_key
        group = self.groups[key]
        if not group['target'].isEnabled():
            return
        editor = AccountEditor(self.repo, parent=self)
        batch = group['valid'][0]
        sources = import_sources(batch)
        name = sources[0]['name'] if len(sources) == 1 else batch.source_sheet.strip()
        if self.savings and batch.balances:
            kind = 'Tagesgeld' if batch.balances[0].category == 'Liquidität' else 'Festgeld'
            editor.kind.setCurrentText(kind)
            name = f'{name} / {kind}'
        elif batch.snapshots:
            editor.kind.setCurrentText('Depot')
        editor.fields['name'].setText(name)
        if editor.exec() != QDialog.DialogCode.Accepted:
            return
        self.accounts_created = True
        new_key = account_key(editor.fields['name'].text())
        accounts = [r for r in self.repo.account_records() if r['active']]
        for current_key, current in self.groups.items():
            target = current['target']
            selected = new_key if current_key == key else target.currentData()
            target.blockSignals(True)
            target.clear()
            target.addItem('Überspringen / nicht zugeordnet', None)
            for account in accounts:
                target.addItem(account['name'], account['account_key'])
            target.setCurrentIndex(max(0, target.findData(selected)))
            target.blockSignals(False)
        self.update_summary()

    def planned_batches(self):
        planned = []
        repeat = self.duplicates.currentData()
        for group in self.groups.values():
            target = group['target'].currentData()
            if not target or group['skip'].checkState() == Qt.CheckState.Checked:
                continue
            for original in group['valid']:
                duplicate = bool(group['old'][id(original)])
                if duplicate and not repeat:
                    continue
                batch = deepcopy(original)
                batch.account_assignments = {s['key']: target for s in import_sources(batch)}
                batch.force_import = duplicate and repeat
                planned.append(batch)
        # Retain workbook order, so grouped UI order cannot change revisions.
        # Original sequence is encoded by file and sheet, which are unique per scan.
        positions = {(b.path, b.source_sheet): i for i, b in enumerate(self.batches)}
        planned.sort(key=lambda b: positions[(b.path, b.source_sheet)])
        return planned

    def skip_names(self):
        names = set(self.saved_skips) - set(self.groups)
        names.update(key for key, group in self.groups.items() if group['skip'].checkState() == Qt.CheckState.Checked)
        return names

    def update_summary(self, *args):
        assigned = pending = skipped = known_count = 0
        for group in self.groups.values():
            excluded = group['skip'].isChecked()
            enabled = bool(group['valid']) and not excluded
            group['target'].setEnabled(enabled)
            group['create'].setEnabled(enabled)
            known_count += sum(bool(group['old'][id(b)]) for b in group['valid'])
            if excluded:
                skipped += 1
                status = 'Übersprungen'
            elif not group['valid']:
                status = 'Fehler'
            elif not group['target'].currentData():
                pending += 1
                status = 'Offen'
            else:
                assigned += 1
                status = 'Zugeordnet'
            if self.group_has_notes(group):
                status += ' · Hinweis'
            group['status'].setText(status)
            group['status'].setToolTip(status)
            font = group['status'].font()
            font.setBold(enabled and not group['target'].currentData())
            group['status'].setFont(font)
        count = sum(len(g['valid']) if self.duplicates.currentData() else
                    sum(not g['old'][id(b)] for b in g['valid'])
                    for g in self.groups.values() if g['target'].currentData() and not g['skip'].isChecked())
        self.overview.setText(f'{len(self.groups)} Quellen · {assigned} zugeordnet · {pending} offen · {skipped} dauerhaft übersprungen'
                             + (f' · {len(self.file_errors)} Dateifehler' if self.file_errors else ''))
        self.summary.setText(f'{len(self.batches) - count} ausgelassen · {known_count} bereits vorhanden\nFilter ändern nur die Anzeige, nicht die Importauswahl.')
        changed = self.skip_names() != self.saved_skips
        self.start.setEnabled(bool(count) or changed)
        unit = 'Monatsstände' if self.savings else 'Blätter'
        self.start.setText(f'{count} {unit} importieren' if count or not changed else 'Regeln speichern')
        self.apply_filter()

    def show_details(self):
        lines = list(self.file_errors)
        row = self.table.currentRow()
        group = next((g for g in self.groups.values() if g['row'] == row), None)
        self.skip_stack.setVisible(group is not None)
        if group:
            self.skip_stack.setCurrentWidget(group['skip'])
            if self.savings and group['target'].currentData():
                record = next((r for r in self.repo.account_records() if r['account_key'] == group['target'].currentData()), None)
                if not self.compatible_kind(record, group['kind']):
                    lines.append('Hinweis: Der Kontotyp des gewählten Zielkontos passt nicht zur Anlageart. Bitte Zuordnung prüfen.')
            for batch in group['batches']:
                notes = batch.errors + batch.summary()['warnings']
                state = 'Importierbar' if batch in group['valid'] else 'Nicht importierbar'
                lines.append(f"{Path(batch.path).name} · {batch.source_sheet}: {state}" + ('\n' + '\n'.join(notes) if notes else ''))
            lines.insert(0, 'Die Monatsstände dieser Bank und Anlageart werden dem gewählten Zielkonto zugeordnet.' if self.savings else 'Alle Quellkonten dieser Blätter werden dem gewählten Ziel zugeordnet.')
        self.details.setPlainText('\n\n'.join(lines) or 'Eine Zeile auswählen, um die zugehörigen Dateien und Hinweise zu sehen.')

    def accept(self):
        self.selected = self.planned_batches()
        active = {r['account_key'] for r in self.repo.account_records() if r['active']}
        if any(target not in active for b in self.selected for target in b.account_assignments.values()):
            QMessageBox.warning(self, 'Zielkonto fehlt', 'Ein Zielkonto wurde gelöscht. Bitte die Übersicht erneut öffnen.')
            return
        try:
            if self.skip_names() != self.saved_skips:
                self.repo.set_history_skip_sheets(self.skip_names())
        except Exception as error:
            QMessageBox.warning(self, 'Regeln nicht gespeichert', str(error))
            return
        super().accept()
