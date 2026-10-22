from .date_display import display_dates
from copy import deepcopy
from pathlib import Path
import json
import re
from .import_combo_style import style_target_account_combo
from .security_names import preferred_security_name
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QDialog, QDialogButtonBox,
 QHeaderView, QLabel, QMessageBox, QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout,
 QApplication, QPushButton, QTextEdit, QWidget, QHBoxLayout, QLineEdit, QCheckBox)


def security_display_names(repository, batches):
    """Resolve identifiers for preview display without changing source records."""
    names = {}

    def remember(record, name):
        valid = preferred_security_name(name, fallback='')
        if not valid:
            return
        for value in (record.get('key'), record.get('security_key'), record.get('isin'), record.get('wkn')):
            value = str(value or '').strip().upper()
            if value:
                names.setdefault(value, valid)
                if len(value) == 6:
                    names.setdefault('WKN:' + value, valid)

    for record in repository.metadata().values():
        remember(record, record.get('canonical_name'))
    for batch in batches:
        for security in batch.securities:
            remember(vars(security), security.name)
    return names


class ImportPreviewDialog(QDialog):
    def __init__(self, repository, batches, parent=None):
        super().__init__(parent)
        self.repo = repository
        self.batches = batches
        self.security_display_names = security_display_names(repository, batches)
        self.mapping_rows = []
        self.pdf_booking_rows = []
        self.setWindowTitle('Import prüfen und Konten / Depots zuordnen')
        self.resize(1250, 820 if any(b.source_sheet == 'PDF' for b in batches) else 700)
        layout = QVBoxLayout(self)
        note = QLabel('1. Konten zuordnen → 2. Buchungen und Bestände prüfen → 3. Importieren. Gleiche Kontokennungen werden gemeinsam zugeordnet.')
        if any(batch.source_sheet == 'PDF' for batch in batches):
            note.setText(display_dates(note.text() + ' PDF-Buchungen bitte im gleichnamigen Reiter prüfen; OCR-Buchungen müssen dort ausdrücklich ausgewählt werden.'))
        note.setWordWrap(True)
        layout.addWidget(note)

        if any(self.always_sync_depot(batch) for batch in batches):
            depot_note = QLabel('comdirect-Depotbestände werden bei diesem Import immer vollständig synchronisiert.')
            depot_note.setWordWrap(True)
            layout.addWidget(depot_note)
        errors = [f"{', '.join(batch.account_names) or Path(batch.path).name}: {error}"
                  for batch in batches for error in batch.errors]
        if errors:
            error_note = QLabel(display_dates('Nicht importierbar:\n' + '\n'.join(errors)))
            error_note.setWordWrap(True)
            error_note.setTextFormat(Qt.TextFormat.PlainText)
            error_note.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            layout.addWidget(error_note)
        self.import_summary = QLabel()
        self.import_summary.setWordWrap(True)
        layout.addWidget(self.import_summary)
        tabs = QTabWidget()
        layout.addWidget(tabs)
        headers = ['Import', 'Datei', 'Depot', 'Datum', 'Positionen', 'Neu', 'Geändert', 'Fehlend', 'Vollständig', 'Vermögenswerte', 'Transaktionen', 'Hinweise/Fehler', 'Dokumente']
        headers.append('Dokumenttyp')
        self.table = QTableWidget(len(batches), len(headers))
        self.table.setHorizontalHeaderLabels(headers)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        tabs.addTab(self.table, 'Dateien')
        for row, batch in enumerate(batches):
            s = repository.preview_summary(batch)
            values = ['', Path(batch.path).name, s['accounts'], s['dates'], s['positions'], s['new'], s['changed'], s['missing'], '', s['balances'], s['transactions'], len(s['warnings']) + len(s['errors']), s['documents']]
            for col, value in enumerate(values):
                item = QTableWidgetItem(display_dates(str(value)))
                item.setToolTip(display_dates('\n'.join(batch.errors or s['warnings'])))
                self.table.setItem(row, col, item)
            self.table.setItem(row, len(headers) - 1, QTableWidgetItem(display_dates(batch.document_type or '–')))
            for col, checked in [(0, not batch.errors), (8, all(snap.complete for snap in batch.snapshots))]:
                item = self.table.item(row, col)
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
                if batch.errors:
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
                elif self.always_sync_depot(batch):
                    item.setCheckState(Qt.CheckState.Checked)
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsUserCheckable)
                    item.setToolTip('Der comdirect-Depotbestand wird immer vollständig synchronisiert.')
        self.table.resizeColumnsToContents()
        self.table.setColumnWidth(1, 240)
        self.table.setColumnWidth(2, 220)
        for column in (5, 6, 7, 8): self.table.setColumnHidden(column, True)
        self.show_technical = QCheckBox('Details zu Bestandsänderungen anzeigen')
        self.show_technical.toggled.connect(lambda visible: [self.table.setColumnHidden(c, not visible) for c in (5, 6, 7, 8)])
        layout.insertWidget(3, self.show_technical)
        self.mapping_table = QTableWidget(0, 6)
        self.mapping_table.setHorizontalHeaderLabels(['Dateien', 'Erkanntes Konto / Depot', 'Inhalt', 'Vorhandenes Zielkonto', 'Zuordnung', 'Merken'])
        self.mapping_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.mapping_table.setAlternatingRowColors(True)
        mapping_panel = QWidget()
        mapping_layout = QVBoxLayout(mapping_panel)
        filters = QHBoxLayout()
        self.mapping_search = QLineEdit()
        self.mapping_search.setPlaceholderText('Konto, IBAN, Zielkonto oder Datei suchen …')
        self.mapping_search.setClearButtonEnabled(True)
        self.only_unassigned = QCheckBox('Nur offene Zuordnungen')
        filters.addWidget(self.mapping_search); filters.addWidget(self.only_unassigned)
        mapping_layout.addLayout(filters); mapping_layout.addWidget(self.mapping_table)
        tabs.addTab(mapping_panel, '1 · Konten zuordnen')
        self.mapping_groups = {}
        accounts = [r for r in repository.account_records() if r['active']]
        self.target_account_names = {r['account_key']: r['name'] for r in accounts}
        target_identifiers = {}
        for record in accounts:
            details = json.loads(record['details'])
            target_identifiers[record['account_key']] = details.get('iban') or details.get('number') or ''
        for batch_index, batch in enumerate(batches):
            if batch.errors:
                continue
            for suggestion in repository.import_account_suggestions(batch):
                group_key = self.mapping_group_key(batch, suggestion)
                if group_key in self.mapping_groups:
                    group = self.mapping_groups[group_key]
                    group['files'].append((batch_index, batch.path))
                    group['kinds'].update(suggestion['kinds'])
                    self.mapping_rows.append((batch_index, suggestion, group['combo'], group['remember']))
                    continue
                row = self.mapping_table.rowCount()
                self.mapping_table.insertRow(row)
                for col, text in [(0, Path(batch.path).name), (1, suggestion['name']), (2, ', '.join(sorted(suggestion['kinds']))), (4, suggestion['reason'])]:
                    self.mapping_table.setItem(row, col, QTableWidgetItem(display_dates(text)))
                    self.mapping_table.item(row, col).setToolTip(display_dates(text))
                combo = QComboBox()
                style_target_account_combo(combo)
                combo.addItem('Bitte Zielkonto auswählen', None)
                if batch.source_sheet == 'PDF':
                    combo.addItem('Diese Kennung nicht zuordnen', '__skip__')
                if suggestion['new_name']:
                    combo.addItem('Neu anlegen: ' + suggestion['new_name'], '__new__')
                for account in accounts:
                    if suggestion.get('required_kind') and json.loads(account['details']).get('kind') != suggestion['required_kind']:
                        continue
                    identifier = target_identifiers.get(account['account_key'], '')
                    combo.addItem(account['name'] + (' · ' + identifier if identifier else ''), account['account_key'])
                target = suggestion['target_key']
                if target:
                    combo.setCurrentIndex(combo.findData(target))
                elif suggestion['new_name'] and not suggestion['remembered'] and batch.source_sheet != 'PDF':
                    combo.setCurrentIndex(combo.findData('__new__'))
                combo.setMinimumWidth(230)
                self.mapping_table.setCellWidget(row, 3, combo)
                remember = QTableWidgetItem('')
                remember.setFlags(remember.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                remember.setCheckState(Qt.CheckState.Unchecked)
                remember.setToolTip('Speichert die gewählte Zuordnung erst beim Import. Bestehende Regeln werden dadurch aktualisiert. Neue Konten werden künftig anhand ihres Namens erkannt.')
                self.mapping_table.setItem(row, 5, remember)
                def update_remember(index, combo=combo, item=remember):
                    enabled = combo.currentData() not in (None, '__new__', '__skip__')
                    item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEnabled if enabled else item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
                    if not enabled:
                        item.setCheckState(Qt.CheckState.Unchecked)
                combo.currentIndexChanged.connect(update_remember)
                update_remember(0)
                self.mapping_rows.append((batch_index, suggestion, combo, remember))
                self.mapping_groups[group_key] = dict(row=row, combo=combo, remember=remember,
                    files=[(batch_index, batch.path)], kinds=set(suggestion['kinds']),
                    proposed=target, reason=suggestion['reason'])
        for column, width in [(0, 85), (1, 235), (2, 110), (3, 370), (5, 75)]:
            self.mapping_table.setColumnWidth(column, width)
        self.mapping_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.mapping_table.verticalHeader().setDefaultSectionSize(52)
        if self.mapping_rows:
            tabs.setCurrentIndex(1)
        if any(batch.source_sheet == 'PDF' and batch.transactions for batch in batches):
            self.add_pdf_bookings(tabs)
        pdfs = [b for b in batches if b.source_sheet == 'PDF']
        if pdfs:
            panel = QWidget(); pdf_layout = QVBoxLayout(panel)
            self.pdf_file_choice = QComboBox()
            for b in pdfs:
                self.pdf_file_choice.addItem(Path(b.path).name)
                self.pdf_file_choice.setItemData(self.pdf_file_choice.count() - 1, b.path, Qt.ItemDataRole.ToolTipRole)
            details = QTextEdit(); details.setReadOnly(True)
            def show_pdf(index):
                b = pdfs[index]
                details.setPlainText('\n\n'.join(b.errors + b.warnings) + '\n\n' + b.pdf_text)
            self.pdf_file_choice.currentIndexChanged.connect(show_pdf)
            pdf_layout.addWidget(self.pdf_file_choice); pdf_layout.addWidget(details)
            show_pdf(0); tabs.addTab(panel, 'Originaltexte und Hinweise')
        if any(batch.document_type == 'comdirect Finanzreport' or batch.source_sheet in ('Online ING', 'Online comdirect', 'Online Baader', 'Online Renault Bank direkt') for batch in batches):
            self.add_bank_details(tabs)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText('Auswahl importieren')
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('Abbrechen')
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self.copy_messages = QPushButton('Meldungen kopieren')
        self.copy_messages.setAutoDefault(False)
        self.copy_messages.clicked.connect(self.copy_import_messages)
        buttons.addButton(self.copy_messages, QDialogButtonBox.ButtonRole.ActionRole)
        layout.addWidget(buttons)
        for group in self.mapping_groups.values():
            group['combo'].currentIndexChanged.connect(self.refresh_import_summary)
        self.mapping_search.textChanged.connect(self.refresh_import_summary)
        self.only_unassigned.toggled.connect(self.refresh_import_summary)
        self.table.itemChanged.connect(self.refresh_import_summary)
        if hasattr(self, 'pdf_bookings_table'):
            self.pdf_bookings_table.itemChanged.connect(self.refresh_import_summary)
        self.refresh_import_summary()

    @staticmethod
    def always_sync_depot(batch):
        return batch.source_sheet == 'Online comdirect' and bool(batch.snapshots) and not batch.errors

    @staticmethod
    def mapping_group_key(batch, source):
        # Bank-local account numbers are never grouped across different banks.
        name = source['name']
        if batch.source_sheet == 'PDF' and re.fullmatch(r'IBAN [A-Z]{2}[A-Z0-9]+', name):
            scope = 'IBAN'
        elif batch.source_sheet == 'PDF' and re.fullmatch(r'(Konto|Depot) [0-9 /-]+', name):
            banks = tuple(bank for bank in ('comdirect', 'renault', 'baader', 'ing')
                          if re.search(r'\b' + bank + r'\b', batch.pdf_text, re.I))
            scope = ('PDF', banks) if len(banks) == 1 else batch.path
        else:
            scope = source['scope']
        return (scope, source['key'], source['target_key'], source['new_name'], source['remembered'],
                batch.account_assignments.get(source['key']), batch.source_sheet == 'PDF')

    def refresh_import_summary(self, *args):
        selected = {i for i, b in enumerate(self.batches) if not b.errors and
                    (self.always_sync_depot(b) or self.table.item(i, 0).checkState() == Qt.CheckState.Checked)}
        unresolved = active = 0
        query = self.mapping_search.text().strip().casefold()
        for group in self.mapping_groups.values():
            row, combo = group['row'], group['combo']
            files = [path for i, path in group['files'] if i in selected]
            paths = list(dict.fromkeys(files))
            self.mapping_table.item(row, 0).setText(f'{len(paths)} Datei(en)')
            self.mapping_table.item(row, 0).setToolTip('\n'.join(paths))
            self.mapping_table.item(row, 2).setText(', '.join(sorted(group['kinds'])))
            combo.setToolTip(combo.currentText())
            combo.view().setMinimumWidth(560)
            target = combo.currentData()
            missing = target is None
            status = ('Bitte Zielkonto wählen' if missing else 'Wird ausgelassen' if target == '__skip__'
                      else 'Wird neu angelegt' if target == '__new__' else group['reason']
                      if target == group['proposed'] else 'Manuell zugeordnet')
            self.mapping_table.item(row, 4).setText(status)
            self.mapping_table.item(row, 4).setToolTip(status)
            if paths:
                active += 1
                unresolved += missing
            haystack = ' '.join([self.mapping_table.item(row, 1).text(), combo.currentText(), *paths]).casefold()
            self.mapping_table.setRowHidden(row, not paths or (self.only_unassigned.isChecked() and not missing)
                                           or bool(query and query not in haystack))
        from portfolio_v5.accounts import account_key
        skipped = {(i, source['key']) for i, source, combo, _ in self.mapping_rows if combo.currentData() == '__skip__'}
        bookings = sum(sum((i, account_key(t.account)) not in skipped for t in self.batches[i].transactions)
                       for i in selected if self.batches[i].source_sheet != 'PDF')
        bookings += sum(i in selected and (i, account_key(self.batches[i].transactions[tx_index].account)) not in skipped
                        and self.pdf_bookings_table.item(row, 0).checkState() == Qt.CheckState.Checked
                        for i, tx_index, row in self.pdf_booking_rows)
        positions = sum(len(s.positions) for i in selected for s in self.batches[i].snapshots
                        if (i, account_key(s.account)) not in skipped)
        self.import_summary.setText(f'{len(selected)} Dateien ausgewählt · {bookings} Buchungen · {positions} Positionen\n'
                                    f'{active - unresolved} von {active} Kontozuordnungen erledigt · {unresolved} offen')
        if hasattr(self, 'pdf_booking_search'): self.refresh_pdf_bookings()

    def security_display_name(self, identifier):
        value = str(identifier or '').strip()
        return self.security_display_names.get(value.upper(), value)

    def copy_import_messages(self):
        messages = []
        for batch in self.batches:
            if batch.errors or batch.warnings:
                messages.append(batch.source_sheet + ' · ' + Path(batch.path).name)
                messages.extend('Fehler: ' + message for message in batch.errors)
                messages.extend('Hinweis: ' + message for message in batch.warnings)
        QApplication.clipboard().setText(display_dates('\n'.join(messages)))

    def add_pdf_bookings(self, tabs):
        from PySide6.QtWidgets import QWidget
        panel = QWidget()
        layout = QVBoxLayout(panel)
        note = QLabel('Buchungen prüfen und einzeln auswählen. Datum (TT.MM.JJJJ), Valuta, Betrag und Buchungstext sind korrigierbar. '
                      'OCR-Buchungen und Buchungen mit Analysehinweisen sind zunächst abgewählt. Doppelklick auf Datei/Seite öffnet das Original. '
                      'Geldbewegungen werden als Kontobuchungen gespeichert, nicht als Wertpapierkäufe.')
        note.setWordWrap(True)
        layout.addWidget(note)
        self.pdf_bookings_table = table = QTableWidget(0, 13)
        table.setHorizontalHeaderLabels(['Auswahl', 'Datei / Seite', 'Quellkonto', 'Buchungstag', 'Valuta', 'Betrag EUR', 'Buchungstext', 'Erkennung', 'Prüfung', 'Zielkonto', 'Eigene IBAN aus PDF', 'Gegenkonto-IBAN im Buchungstext', 'Depot für Wertpapierbuchung'])
        table.setAlternatingRowColors(True)
        filters = QHBoxLayout()
        self.pdf_booking_search = QLineEdit()
        self.pdf_booking_search.setPlaceholderText('Buchungstext, IBAN, Betrag oder Datum suchen …')
        self.pdf_booking_search.setClearButtonEnabled(True)
        self.pdf_account_filter = QComboBox(); self.pdf_account_filter.addItem('Alle Quellkonten', None)
        self.pdf_review_only = QCheckBox('Nur zu prüfen')
        filters.addWidget(self.pdf_booking_search, 1); filters.addWidget(self.pdf_account_filter); filters.addWidget(self.pdf_review_only)
        layout.addLayout(filters)
        self.pdf_booking_totals = QLabel(); layout.addWidget(self.pdf_booking_totals)
        from portfolio_v5.settlement import kind_of
        depot_names = {s['account'] for s in self.repo.snapshots()}
        depot_records = [r for r in self.repo.account_records() if r['active']
                         and (r['name'] in depot_names or json.loads(r['details']).get('kind') == 'Depot')]
        for batch_index, batch in enumerate(self.batches):
            if batch.source_sheet != 'PDF' or batch.errors:
                continue
            for tx_index, tx in enumerate(batch.transactions):
                evidence = batch.pdf_booking_evidence[tx_index] if tx_index < len(batch.pdf_booking_evidence) else {}
                purpose = getattr(tx, 'purpose', '') or ' · '.join(filter(None, (tx.kind, tx.security)))
                row = table.rowCount()
                table.insertRow(row)
                values = ['', f'{Path(batch.path).name} · Seite {evidence.get("page", "?")}', tx.account,
                          tx.date, getattr(tx, 'value_date', ''), tx.amount.replace('.', ','), purpose,
                          'OCR' if evidence.get('ocr') else 'PDF-Text',
                          'Bitte einzeln prüfen' if evidence.get('review_required') else 'Erkannt', '',
                          self.pretty_iban(tx.account[5:]) if tx.account.startswith('IBAN ') else 'Nicht im PDF erkannt',
                          ', '.join(self.counterparty_ibans(purpose, tx.account)), '']
                for column, value in enumerate(values):
                    item = QTableWidgetItem(display_dates(value))
                    if column not in (3, 4, 5, 6):
                        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    item.setToolTip(display_dates(value))
                    table.setItem(row, column, item)
                check = table.item(row, 0)
                check.setFlags(check.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                check.setCheckState(Qt.CheckState.Unchecked if evidence.get('review_required') else Qt.CheckState.Checked)
                self.pdf_booking_rows.append((batch_index, tx_index, row))
                if kind_of(vars(tx)) in ('DIVIDEND', 'TAX', 'FEE'):
                    choice = QComboBox()
                    choice.addItem('Automatisch über Verrechnungskonto', '')
                    for record in depot_records:
                        choice.addItem(record['name'], record['account_key'])
                    choice.setCurrentIndex(max(0, choice.findData(getattr(tx, 'performance_depot_key', ''))))
                    table.setCellWidget(row, 12, choice)
        def open_document(row, column):
            if column != 1:
                return
            from PySide6.QtCore import QUrl
            from PySide6.QtGui import QDesktopServices
            batch_index = next(b for b, _, r in self.pdf_booking_rows if r == row)
            QDesktopServices.openUrl(QUrl.fromLocalFile(self.batches[batch_index].path))
        table.cellDoubleClicked.connect(open_document)
        table.resizeColumnsToContents()
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        for column, width in [(0, 90), (1, 200), (2, 190), (3, 100), (4, 100),
                              (5, 100), (6, 310), (7, 90), (8, 140)]:
            table.setColumnWidth(column, width)
        table.setWordWrap(False)
        for column in (1, 2, 7, 11): table.setColumnHidden(column, True)
        for column, width in ((0, 70), (8, 110), (9, 175), (10, 235), (6, 270)): table.setColumnWidth(column, width)
        header = table.horizontalHeader()
        header.setSectionResizeMode(6, QHeaderView.ResizeMode.Stretch)
        for visual, logical in enumerate((0, 3, 4, 5, 9, 10, 6, 8, 1, 2, 7, 11)):
            header.moveSection(header.visualIndex(logical), visual)
        layout.addWidget(table, 1)
        self.pdf_booking_detail = QTextEdit(); self.pdf_booking_detail.setReadOnly(True)
        self.pdf_booking_detail.setMaximumHeight(150)
        self.pdf_booking_detail.setPlaceholderText('Buchung auswählen: vollständiger Text, Konto, IBAN und Quelle erscheinen hier.')
        layout.addWidget(self.pdf_booking_detail)
        more = QCheckBox('Quelle, Erkennung und Gegenkonto als Spalten anzeigen')
        more.toggled.connect(lambda visible: [table.setColumnHidden(c, not visible) for c in (1, 2, 7, 11)])
        layout.addWidget(more)
        for owner in sorted({self.batches[i].transactions[t].account for i, t, _ in self.pdf_booking_rows}):
            self.pdf_account_filter.addItem(owner, owner)
        self.pdf_booking_search.textChanged.connect(self.refresh_pdf_bookings)
        self.pdf_account_filter.currentIndexChanged.connect(self.refresh_pdf_bookings)
        self.pdf_review_only.toggled.connect(self.refresh_pdf_bookings)
        table.itemSelectionChanged.connect(self.show_pdf_booking)
        actions = QHBoxLayout()
        for label, state in [('Sichtbare Buchungen auswählen', Qt.CheckState.Checked),
                             ('Sichtbare Buchungen abwählen', Qt.CheckState.Unchecked)]:
            button = QPushButton(label)
            button.setAutoDefault(False)
            def select_rows(checked=False, state=state):
                for row in range(table.rowCount()):
                    if not table.isRowHidden(row): table.item(row, 0).setCheckState(state)
            button.clicked.connect(select_rows)
            actions.addWidget(button)
        layout.addLayout(actions)
        tabs.addTab(panel, 'PDF-Buchungen')
        self.refresh_pdf_bookings()

    @staticmethod
    def pretty_iban(value):
        compact = re.sub(r'\s+', '', value)
        return ' '.join(compact[i:i + 4] for i in range(0, len(compact), 4))

    @classmethod
    def counterparty_ibans(cls, purpose, owner):
        result = []
        for raw in re.findall(r'\bDE(?: ?\d){20}', purpose):
            iban = raw.replace(' ', '')
            if owner == 'IBAN ' + iban or int(iban[4:] + '1314' + iban[2:4]) % 97 != 1:
                continue
            formatted = cls.pretty_iban(iban)
            if formatted not in result: result.append(formatted)
        return result

    def refresh_pdf_bookings(self, *args):
        from decimal import Decimal, InvalidOperation
        from portfolio_v5.accounts import account_key
        table = self.pdf_bookings_table
        query = self.pdf_booking_search.text().strip().casefold()
        chosen_account = self.pdf_account_filter.currentData()
        choices = {(i, source['key']): combo for i, source, combo, _ in self.mapping_rows}
        incoming = outgoing = Decimal(0)
        visible = selected = 0
        invalid = 0
        previous = table.blockSignals(True)
        candidate_cache = {}
        try:
            for i, tx_index, row in self.pdf_booking_rows:
                tx = self.batches[i].transactions[tx_index]
                combo = choices.get((i, account_key(tx.account)))
                target = combo.currentData() if combo else None
                label = ('Nicht zugeordnet' if target is None else 'Wird ausgelassen' if target == '__skip__'
                         else self.target_account_names.get(target, combo.currentText()))
                table.item(row, 9).setText(label); table.item(row, 9).setToolTip(combo.currentText() if combo else label)
                choice = table.cellWidget(row, 12)
                if choice:
                    from portfolio_v5.settlement import depot_candidates
                    cache_key = (label, tx.security, tx.date)
                    candidates = candidate_cache.get(cache_key)
                    if candidates is None:
                        candidates = depot_candidates(self.repo.store, {**vars(tx), 'account': label})
                        candidate_cache[cache_key] = candidates
                    suggestion = candidates[0]['name'] if len(candidates) == 1 else 'Depot auswählen'
                    choice.setItemText(0, 'Automatisch: ' + suggestion)
                table.item(row, 11).setText(', '.join(self.counterparty_ibans(table.item(row, 6).text(), tx.account)))
                evidence = self.batches[i].pdf_booking_evidence
                needs_review = target is None or (tx_index < len(evidence) and evidence[tx_index].get('review_required'))
                haystack = ' '.join(table.item(row, c).text() for c in range(table.columnCount())).casefold()
                matches_query = not query or query in haystack or query.replace(' ', '') in haystack.replace(' ', '')
                show = (self.table.item(i, 0).checkState() == Qt.CheckState.Checked
                        and (not chosen_account or tx.account == chosen_account) and matches_query
                        and (not self.pdf_review_only.isChecked() or needs_review))
                table.setRowHidden(row, not show)
                if not show: continue
                visible += 1
                if target == '__skip__' or table.item(row, 0).checkState() != Qt.CheckState.Checked: continue
                selected += 1
                try:
                    amount = Decimal(table.item(row, 5).text().replace('.', '').replace(',', '.'))
                    if not amount.is_finite(): raise InvalidOperation
                    if amount >= 0: incoming += amount
                    else: outgoing += amount
                except InvalidOperation:
                    invalid += 1
        finally:
            table.blockSignals(previous)
        from .formatting import euro
        self.pdf_booking_totals.setText(f'{visible} Buchungen sichtbar · {selected} ausgewählt · '
            f'Eingänge {euro(incoming)} · Ausgänge {euro(outgoing)} · Summe {euro(incoming + outgoing)}'
            + (f' · {invalid} ungültige Beträge' if invalid else ''))
        self.show_pdf_booking()

    def show_pdf_booking(self):
        table = self.pdf_bookings_table
        row = table.currentRow()
        if row < 0 or table.isRowHidden(row):
            self.pdf_booking_detail.clear()
            return
        self.pdf_booking_detail.setPlainText('\n'.join(
            f'{table.horizontalHeaderItem(c).text()}: {table.item(row, c).text()}'
            for c in (9, 10, 2, 3, 4, 5, 11, 6, 1, 8)))

    def add_bank_details(self, tabs):
        from decimal import Decimal
        def formatted(value, money=False):
            if value is None:
                return ''
            return format(Decimal(value), '.2f' if money else 'f').replace('.', ',')
        details = QTableWidget(0, 7)
        details.setHorizontalHeaderLabels(['Quellkonto', 'Datenstand', 'ISIN / Inhalt', 'Bezeichnung', 'Stück', 'Wert / Betrag', 'Hinweise'])
        details.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        details.setAlternatingRowColors(True)
        for batch in self.batches:
            rows = []
            for snapshot in batch.snapshots:
                rows.extend([snapshot.account, snapshot.as_of or snapshot.period, p.isin or p.wkn, p.name,
                             formatted(p.quantity), formatted(p.value, True), 'Kursdatum: ' + (p.quote_date or 'unbekannt')]
                            for p in snapshot.positions)
                if not snapshot.positions:
                    rows.append([snapshot.account, snapshot.as_of, 'Leeres Depot', '', '', '0', 'Bank meldet keine Positionen'])
            for balance in batch.balances:
                rows.append([balance.account, balance.sheet, 'Kontosaldo', '', '', formatted(balance.value, True), 'Monatswert ' + balance.period])
            for transaction in batch.transactions:
                rows.append([transaction.account, transaction.date, 'Kontobuchung', getattr(transaction, 'counterparty', ''), '',
                    formatted(transaction.amount, True) + ' ' + transaction.currency, getattr(transaction, 'purpose', '')])
            for document in batch.documents:
                rows.append([document.account, document.date or 'Datum unbekannt', 'PDF-Dokument', document.title,
                             '', '', 'Originaldokument'])
            rows.extend([', '.join(batch.account_names), '', 'Fehler', '', '', '', message]
                        for message in batch.errors)
            rows.extend([', '.join(batch.account_names), '', 'Hinweis', '', '', '', message]
                        for message in batch.warnings)
            for values in rows:
                row = details.rowCount()
                details.insertRow(row)
                for col, value in enumerate(values):
                    item = QTableWidgetItem(display_dates('' if value is None else str(value)))
                    item.setToolTip(display_dates(item.text()))
                    details.setItem(row, col, item)
        details.resizeColumnsToContents()
        banks = {batch.source_sheet.removeprefix('Online ') for batch in self.batches
                 if batch.source_sheet in ('Online ING', 'Online comdirect', 'Online Baader', 'Online Renault Bank direkt')}
        tabs.addTab(details, 'comdirect · Importdetails' if any(b.document_type == 'comdirect Finanzreport' for b in self.batches)
                    else f'{next(iter(banks)) if len(banks) == 1 else "Bank"} · Abrufdetails')

    def selected_batches(self):
        result = []
        remembered = {}
        from portfolio_v5.accounts import account_key
        from portfolio_v5.settlement import portfolio_cash_kind, depot_candidates
        records = {r['account_key']: r for r in self.repo.account_records() if r['active']}
        depot_names = {s['account'] for s in self.repo.snapshots()}
        candidate_cache = {}
        for row, original in enumerate(self.batches):
            always_sync = self.always_sync_depot(original)
            if original.errors or (not always_sync and self.table.item(row, 0).checkState() != Qt.CheckState.Checked):
                continue
            batch = deepcopy(original)
            # The checkbox controls creation of cash transactions.  A comdirect
            # trade confirmation is non-cash evidence for an existing statement
            # row and must survive even when that checkbox remains cleared.
            if (batch.plugin_id == 'user.comdirect-ertraege'
                    and batch.plugin_handler in ('wertpapierkauf', 'wertpapierverkauf')):
                batch.booking_evidence = deepcopy(original.transactions)
            batch.account_assignments = {}
            batch.remember_assignments = []
            batch.new_accounts = []
            if batch.source_sheet == 'PDF':
                from portfolio_v5.models import money, parse_date
                selected_transactions = []
                for batch_index, tx_index, table_row in self.pdf_booking_rows:
                    if batch_index != row or self.pdf_bookings_table.item(table_row, 0).checkState() != Qt.CheckState.Checked:
                        continue
                    tx = batch.transactions[tx_index]
                    # Persist edited optional fields through asdict/session reload too.
                    # Plain Transaction instances have no bank-detail dataclass fields.
                    from dataclasses import asdict
                    from portfolio_v5.models import BankTransaction
                    if not isinstance(tx, BankTransaction):
                        tx = BankTransaction(**asdict(tx))
                    choice = self.pdf_bookings_table.cellWidget(table_row, 12)
                    if choice:
                        tx.performance_depot_key = choice.currentData()
                    for column, attribute in ((3, 'date'), (4, 'value_date')):
                        value = self.pdf_bookings_table.item(table_row, column).text().strip()
                        if column == 4 and not value:
                            tx.value_date = ''
                            continue
                        if not parse_date(value) or value not in (parse_date(value), display_dates(parse_date(value))):
                            raise ValueError('PDF-Buchung: gültiges Datum im Format TT.MM.JJJJ eingeben.')
                        setattr(tx, attribute, parse_date(value))
                    amount = money(self.pdf_bookings_table.item(table_row, 5).text())
                    if amount is None:
                        raise ValueError('PDF-Buchung: Betrag fehlt.')
                    tx.amount = amount
                    tx.purpose = self.pdf_bookings_table.item(table_row, 6).text().strip()
                    if not tx.purpose:
                        raise ValueError('PDF-Buchung: Buchungstext fehlt.')
                    selected_transactions.append(tx)
                batch.transactions = selected_transactions
            for index, source, combo, remember in self.mapping_rows:
                if index != row:
                    continue
                target = combo.currentData()
                if target is None:
                    raise ValueError('Bitte ein Zielkonto für „' + source['name'] + '“ auswählen.')
                if target == '__skip__':
                    from portfolio_v5.accounts import account_key
                    batch.documents = [d for d in batch.documents if account_key(d.account) != source['key']]
                    batch.transactions = [t for t in batch.transactions if account_key(t.account) != source['key']]
                    batch.snapshots = [s for s in batch.snapshots if account_key(s.account) != source['key']]
                    batch.balances = [b for b in batch.balances if account_key(b.account) != source['key']]
                    batch.account_names = [n for n in batch.account_names if account_key(n) != source['key']]
                    continue
                if target == '__new__':
                    batch.new_accounts.append(source['new_name'])
                    target = source['key']
                batch.account_assignments[source['key']] = target
                if remember.checkState() == Qt.CheckState.Checked:
                    rule = (source['scope'], source['key'])
                    if rule in remembered and remembered[rule] != target:
                        raise ValueError('Für dieselbe Dateifamilie und dasselbe Quellkonto wurden verschiedene Ziele zum Merken gewählt.')
                    remembered[rule] = target
                    batch.remember_assignments.append(source['key'])
            complete = always_sync or self.table.item(row, 8).checkState() == Qt.CheckState.Checked
            for tx in batch.transactions:
                transaction_kind = portfolio_cash_kind(vars(tx))
                if batch.source_sheet != 'PDF' or transaction_kind not in ('DIVIDEND', 'TAX', 'FEE'):
                    continue
                tx.kind = transaction_kind
                # A cash event without an instrument identifier remains
                # classifiable, but cannot be attached to a position safely.
                if not tx.security:
                    continue
                cash_key = batch.account_assignments.get(account_key(tx.account), account_key(tx.account))
                cash_name = records[cash_key]['name'] if cash_key in records else tx.account
                if not tx.performance_depot_key:
                    cache_key = (cash_name, tx.security, tx.date)
                    candidates = candidate_cache.get(cache_key)
                    if candidates is None:
                        candidates = depot_candidates(self.repo.store, {**vars(tx), 'account': cash_name})
                        candidate_cache[cache_key] = candidates
                    if len(candidates) == 1:
                        tx.performance_depot_key = candidates[0]['account_key']
                    elif cash_name in depot_names or (cash_key in records and json.loads(records[cash_key]['details']).get('kind') == 'Depot'):
                        tx.performance_depot_key = cash_key
                    else:
                        label = {'DIVIDEND': 'Dividende', 'TAX': 'Steuer', 'FEE': 'Gebühr'}[transaction_kind]
                        raise ValueError(label + ': Bitte im Reiter PDF-Buchungen das zugehörige Depot auswählen.')
                depot_record = records.get(tx.performance_depot_key)
                linked_cash = json.loads(depot_record['details']).get('cash_account_key') if depot_record else None
                if linked_cash and linked_cash != cash_key:
                    raise ValueError('Das Zielkonto stimmt nicht mit dem Verrechnungskonto des gewählten Depots überein.')
            if batch.source_sheet == 'PDF' and not batch.documents:
                raise ValueError('Bitte für mindestens eine PDF-Kennung ein Konto wählen oder die Datei abwählen.')
            for snapshot in batch.snapshots:
                snapshot.complete = complete
            result.append(batch)
        return result

    def accept(self):
        try:
            if not self.selected_batches():
                raise ValueError('Bitte mindestens eine fehlerfreie Datei auswählen.')
        except ValueError as error:
            QMessageBox.warning(self, 'Kontozuordnung prüfen', str(error))
            return
        super().accept()
