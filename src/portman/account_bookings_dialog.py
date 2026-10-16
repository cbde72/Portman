from .date_display import display_dates
"""Browse an account's complete stored transaction history."""
from decimal import Decimal, InvalidOperation
from pathlib import Path

from PySide6.QtCore import Qt, QSortFilterProxyModel, QDate
from PySide6.QtGui import QColor, QStandardItem, QStandardItemModel, QKeySequence, QShortcut
from PySide6.QtWidgets import (QAbstractItemView, QDialog, QDialogButtonBox,
    QLabel, QLineEdit, QTableView, QVBoxLayout, QHBoxLayout, QPushButton,
    QMessageBox, QFormLayout, QComboBox, QDateEdit, QInputDialog, QCheckBox,
    QScrollArea, QWidget, QFrame)

from .busy_indicator import busy_cursor
from .repository_v09 import reference


class TransactionEditDialog(QDialog):
    def __init__(self, repository, tx, parent=None, dividend=False):
        super().__init__(parent)
        self.repository, self.tx = repository, tx
        self.setWindowTitle('Buchung bearbeiten')
        layout = QVBoxLayout(self)
        self.scroll = QScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget()
        form = QFormLayout(content); form.setSpacing(12)
        self.scroll.setWidget(content)
        layout.addWidget(self.scroll, 1)
        original = QLabel('Original bleibt erhalten · ' + Path(tx.get('source', '')).name)
        original.setWordWrap(True); form.addRow(original)
        self.day = QDateEdit(QDate.fromString(tx['date'], Qt.DateFormat.ISODate))
        self.day.setCalendarPopup(True); self.day.setDisplayFormat('dd.MM.yyyy'); form.addRow('Buchungstag', self.day)
        value = tx.get('value_date') or tx['date']
        self.value_day = QDateEdit(QDate.fromString(value, Qt.DateFormat.ISODate))
        self.value_day.setCalendarPopup(True); self.value_day.setDisplayFormat('dd.MM.yyyy'); form.addRow('Valuta', self.value_day)
        self.kind = QComboBox(); self.kind.addItems(['BANK_BOOKING','BUY','SELL','DIVIDEND','INTEREST','DEPOSIT','WITHDRAWAL','FEE','TAX','TRANSFER_IN','TRANSFER_OUT'])
        suggested_kind = tx['kind']
        if dividend:
            content = ' '.join(str(tx.get(key) or '') for key in ('purpose','booking_text','operation')).casefold()
            suggested_kind = ('TAX' if any(word in content for word in ('steuer','quellensteuer','kapitalertrag')) else
                              'FEE' if any(word in content for word in ('gebühr','gebuehr','kosten','provision')) else 'DIVIDEND')
        self.kind.setCurrentText(suggested_kind); form.addRow('Art', self.kind)
        self.amount = QLineEdit(str(tx['amount']).replace('.', ',')); form.addRow('Betrag', self.amount)
        self.currency = QLineEdit(tx['currency']); self.currency.setMaxLength(3); form.addRow('Währung', self.currency)
        self.gross_income = QLineEdit(str(tx.get('gross_income') or '').replace('.', ','))
        form.addRow('Bruttobetrag', self.gross_income)
        self.gross_currency = QLineEdit(tx.get('gross_currency') or tx['currency']); self.gross_currency.setMaxLength(3)
        form.addRow('Bruttowährung', self.gross_currency)
        self.fees = QLineEdit(str(tx.get('fees') or '').replace('.', ',')); form.addRow('Gebühren', self.fees)
        self.taxes = QLineEdit(str(tx.get('taxes') or '').replace('.', ',')); form.addRow('Steuern gesamt', self.taxes)
        self.tax_rate = QLineEdit(str(tx.get('tax_rate') or '').replace('.', ','))
        form.addRow('Effektiver Steuersatz (%)', self.tax_rate)
        self.withholding_tax = QLineEdit(str(tx.get('withholding_tax') or '').replace('.', ','))
        form.addRow('davon Quellensteuer', self.withholding_tax)
        self.withholding_country = QLineEdit(tx.get('withholding_country') or '')
        self.withholding_country.setMaxLength(2); form.addRow('Quellenstaat (ISO)', self.withholding_country)
        self.withholding_tax_rate = QLineEdit(str(tx.get('withholding_tax_rate') or '').replace('.', ','))
        form.addRow('Quellensteuersatz (%)', self.withholding_tax_rate)
        self.solidarity_tax = QLineEdit(str(tx.get('solidarity_tax') or '').replace('.', ','))
        form.addRow('davon Solidaritätszuschlag', self.solidarity_tax)
        self.transaction_reference = QLineEdit(tx.get('transaction_reference') or tx.get('bank_reference') or
                                               tx.get('document_reference') or '')
        form.addRow('Vorgang / Referenz', self.transaction_reference)
        self.counterparty = QLineEdit(tx.get('counterparty', '')); form.addRow('Gegenpartei', self.counterparty)
        self.purpose = QLineEdit(tx.get('purpose', '')); form.addRow('Verwendungszweck', self.purpose)
        self.security = QComboBox(); self.security.setEditable(True)
        self.security.addItem('Keine Depotposition', '')
        positions = repository.holdings(tx['date'])
        seen = set()
        for position in sorted(positions, key=lambda row: (row.get('name', ''), row.get('depot', ''))):
            key = position.get('isin') or position.get('key') or ''
            if not key or key in seen: continue
            seen.add(key); self.security.addItem(f"{position.get('name', key)} · {position.get('depot', '')} · {key}", key)
        current = tx.get('security') or ''
        index = self.security.findData(current)
        if current and index < 0: self.security.addItem(current, current); index = self.security.count() - 1
        self.security.setCurrentIndex(max(0, index)); form.addRow('Depotposition', self.security)
        self.depot = QComboBox(); self.depot.addItem('Kein Depot zugeordnet', '')
        records = {r['account_key']: r for r in repository.account_records() if r['active']}
        source_key = next((r['account_key'] for r in records.values() if r['name'].casefold() == tx['account'].casefold()), '')
        for record in records.values():
            import json
            details = json.loads(record['details'])
            if details.get('kind') == 'Depot' and details.get('cash_account_key') == source_key:
                self.depot.addItem(record['name'], record['account_key'])
        current_depot = tx.get('performance_depot_key') or ''
        self.depot.setCurrentIndex(max(0, self.depot.findData(current_depot)))
        form.addRow('Zugehöriges Depot', self.depot)
        self.quantity = QLineEdit(str(tx.get('quantity') or '').replace('.', ',')); form.addRow('Stückzahl', self.quantity)
        self.per_share_amount = QLineEdit(str(tx.get('per_share_amount') or '').replace('.', ','))
        form.addRow('Dividende / Kupon je Stück', self.per_share_amount)
        self.per_share_currency = QLineEdit(tx.get('per_share_currency') or '')
        self.per_share_currency.setMaxLength(3); form.addRow('Währung je Stück', self.per_share_currency)
        self.remember_rule = QCheckBox('Für gleichartige Buchungstexte künftig automatisch zuordnen')
        form.addRow(self.remember_rule)
        self.rule_text = QLineEdit(tx.get('purpose') or tx.get('booking_text') or '')
        self.rule_text.setPlaceholderText('Eindeutiger Text, z. B. APPLE DIVIDENDE')
        form.addRow('Regel enthält Text', self.rule_text)
        self.reason = QLineEdit(); self.reason.setPlaceholderText('z. B. anhand Kontoauszug geprüft'); form.addRow('Grund / Beleg', self.reason)
        hint = QLabel('Bei Dividenden ist der Betrag die Nettogutschrift. Bruttobetrag, Gebühren und Steuern bleiben für Auswertungen getrennt erhalten.')
        hint.setWordWrap(True); form.addRow(hint)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText('Änderung speichern')
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('Abbrechen')
        buttons.accepted.connect(self.save); buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.buttons = buttons
        available = self.screen().availableGeometry()
        self.resize(min(660, available.width() - 40), min(720, available.height() - 80))

    def save(self):
        from portfolio_v5.models import correction_number
        def optional_number(editor):
            return correction_number(editor.text()) if editor.text().strip() else None
        security = self.security.currentData()
        if self.security.currentIndex() < 0 or self.security.currentText() != self.security.itemText(self.security.currentIndex()):
            security = self.security.currentText().strip()
        if self.kind.currentText() == 'DIVIDEND' and not security:
            QMessageBox.warning(self, 'Depotposition fehlt', 'Bitte die Depotposition auswählen, zu der diese Dividende gehört.'); return
        try:
            values = {
                'date': self.day.date().toString(Qt.DateFormat.ISODate),
                'value_date': self.value_day.date().toString(Qt.DateFormat.ISODate),
                'kind': self.kind.currentText(), 'amount': correction_number(self.amount.text()),
                'currency': self.currency.text(), 'counterparty': self.counterparty.text().strip(),
                'purpose': self.purpose.text().strip(), 'security': security,
                'quantity': optional_number(self.quantity), 'gross_income': optional_number(self.gross_income),
                'per_share_amount': optional_number(self.per_share_amount),
                'per_share_currency': self.per_share_currency.text().strip(),
                'gross_currency': self.gross_currency.text().strip(), 'fees': optional_number(self.fees),
                'taxes': optional_number(self.taxes), 'withholding_tax': optional_number(self.withholding_tax),
                'tax_rate': optional_number(self.tax_rate),
                'solidarity_tax': optional_number(self.solidarity_tax),
                'withholding_country': self.withholding_country.text().strip(),
                'withholding_tax_rate': optional_number(self.withholding_tax_rate),
                'transaction_reference': self.transaction_reference.text().strip(),
                'income_basis': 'net', 'performance_depot_key': self.depot.currentData() or ''}
            self.repository.edit_transaction(reference(self.tx), values, self.reason.text())
            if self.kind.currentText() in ('DIVIDEND', 'TAX', 'FEE') and (security or self.depot.currentData()):
                self.repository.assign_portfolio_transaction(reference(self.tx), self.kind.currentText(), security,
                    self.depot.currentData() or '', self.reason.text(),
                    self.rule_text.text() if self.remember_rule.isChecked() else '')
        except Exception as error:
            QMessageBox.warning(self, 'Buchung prüfen', str(error)); return
        self.accept()


class AccountBookingsDialog(QDialog):
    def __init__(self, repository, account, parent=None):
        super().__init__(parent)
        self.repository, self.account = repository, account
        record = next((row for row in repository.account_records() if row['name'] == account), None)
        import json
        self.depot_key = (record['account_key'] if record and
                          json.loads(record['details']).get('kind') == 'Depot' else '')
        self.setWindowTitle(f"{'Depotbuchungen' if self.depot_key else 'Alle Buchungen'} · {account}")
        self.resize(1200, 720)
        layout = QVBoxLayout(self)
        note = QLabel(f"{account} · " + ('wirtschaftlich zugehörige Depotbuchungen unabhängig vom Zahlungskonto'
            if self.depot_key else 'Alle gespeicherten Buchungen über den gesamten Zeitraum'))
        note.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(note)
        start_bar = QHBoxLayout()
        start_bar.addWidget(QLabel('Startbetrag (EUR):'))
        self.start_amount = QLineEdit('0,00')
        self.start_amount.setMaximumWidth(180)
        self.start_amount.setPlaceholderText('z. B. 1.000,00')
        start_bar.addWidget(self.start_amount)
        self.sum_note = QLabel('')
        start_bar.addWidget(self.sum_note, 1)
        layout.addLayout(start_bar)
        self.search = QLineEdit()
        self.search.setPlaceholderText('Buchungen durchsuchen: Datum, Betrag, Verwendungszweck, Gegenpartei …')
        self.search.setClearButtonEnabled(True)
        layout.addWidget(self.search)
        self.model = QStandardItemModel(self)
        self.model.setHorizontalHeaderLabels(['Buchungstag', 'Valuta', 'Art', 'Netto / Kontowirkung', 'Währung',
            'Summe (EUR)', 'Gegenpartei', 'Verwendungszweck', 'Wertpapier', 'Quelle', 'Buchungs-ID',
            'Bruttoertrag', 'Gebühren', 'Steuern gesamt', 'Effektiver Steuersatz', 'Quellensteuer', 'Solidaritätszuschlag',
            'Quellenstaat', 'Quellensteuersatz', 'Vorgang / Referenz',
            'Verknüpfte Belege / Dublettenstatus'])
        self.wallet = False
        self.load_transactions()
        self.proxy = QSortFilterProxyModel(self)
        self.proxy.setSourceModel(self.model)
        self.proxy.setSortRole(Qt.ItemDataRole.UserRole)
        self.proxy.setFilterKeyColumn(-1)
        self.proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setSortingEnabled(True)
        self.table.sortByColumn(0, Qt.SortOrder.AscendingOrder)
        self.table.doubleClicked.connect(lambda index: self.edit_selected())
        from .table_copy import copy_selected_rows
        self.copy_shortcut = QShortcut(QKeySequence.StandardKey.Copy, self.table)
        self.copy_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.copy_shortcut.activated.connect(lambda: copy_selected_rows(self.table))
        self.table.setAlternatingRowColors(True)
        self.table.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.table.verticalHeader().setDefaultSectionSize(28)
        for column, width in enumerate((110, 110, 140, 100, 75, 130, 180, 420, 130, 200, 230)):
            self.table.setColumnWidth(column, width)
        self.update_optional_columns()
        layout.addWidget(self.table, 1)
        action_bar = QHBoxLayout()
        self.edit_button = QPushButton('Buchung bearbeiten')
        self.dividend_button = QPushButton('Depotposition zuordnen')
        self.duplicate_button = QPushButton('Dubletten auflösen')
        self.delete_button = QPushButton('Buchung löschen')
        self.reconcile_button = QPushButton('Geldbuchung zuordnen')
        self.delete_button.setProperty('destructive', True)
        for button, callback in ((self.edit_button, self.edit_selected), (self.dividend_button, self.assign_dividend),
                                 (self.duplicate_button, self.resolve_duplicate),
                                 (self.reconcile_button, self.reconcile_selected),
                                 (self.delete_button, self.delete_selected)):
            button.clicked.connect(callback); action_bar.addWidget(button)
        self.reconcile_button.setVisible(bool(self.depot_key))
        action_bar.addStretch(1); layout.addLayout(action_bar)
        editable = hasattr(repository, 'edit_transaction')
        for button in (self.edit_button, self.dividend_button, self.duplicate_button, self.delete_button):
            button.setEnabled(editable)
        self.count = QLabel()
        layout.addWidget(self.count)
        self.search.textChanged.connect(self.filter_bookings)
        self.start_amount.textChanged.connect(self.update_sums)
        self.update_sums()
        self.filter_bookings('')
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.close)
        layout.addWidget(buttons)

    def load_transactions(self):
        with busy_cursor():
            self.model.removeRows(0, self.model.rowCount())
            reconciliation = (self.repository.reconcile_depot_bookings(self.depot_key)
                              if self.depot_key and hasattr(self.repository, 'reconcile_depot_bookings') else [])
            self.reconciliation_rows = {reference(row['transaction']): row for row in reconciliation}
            reconciliation_status = {reference(row['transaction']): row['status'] for row in reconciliation}
            source = ([row['transaction'] for row in reconciliation] if reconciliation
                      else self.repository.transactions(self.account))
            self.transactions = sorted(source, key=lambda tx: tx['date'])
            reviewed = self.repository.reviewed_duplicates() if hasattr(self.repository, 'reviewed_duplicates') else set()
            self.wallet = any(p.get('asset_type') == 'Krypto' for p in self.repository.holdings(account=self.account)) or any(
                tx.get('external_id', '').startswith('crypto-csv-') for tx in self.transactions)
            if self.wallet: self.model.setHeaderData(5, Qt.Orientation.Horizontal, 'Käufe − Verkäufe (EUR)')
            for tx in self.transactions:
                sources = tx.get('booking_sources', [])
                duplicate = len(sources) > 1
                status = reconciliation_status.get(reference(tx), '')
                duplicate_status = ('DUBLETTE · geprüft und zusammengeführt' if reference(tx) in reviewed else
                          f'DUBLETTE · {len(sources)} Quellen zusammengeführt') if duplicate else ('Bearbeitet' if tx.get('edited') else '')
                status = ' · '.join(value for value in (status, duplicate_status) if value)
                values = [tx['date'], tx.get('value_date', ''), tx['kind'] if tx.get('affects_cash', True) else tx['kind'] + ' · nur Depot',
                    format(Decimal(tx['amount']), '.2f').replace('.', ','), tx['currency'], '', tx.get('counterparty', ''),
                    tx.get('purpose', ''), tx.get('security') or '', Path(tx.get('source', '')).name, tx['external_id'],
                    (str(tx['gross_income']) + ' ' + tx.get('gross_currency', '')) if tx.get('gross_income') is not None else '',
                    (str(tx['fees']) + ' ' + tx['currency']) if tx.get('fees') is not None else '',
                    (str(tx['taxes']) + ' ' + tx['currency']) if tx.get('taxes') is not None else '',
                    (str(tx['tax_rate']) + ' %') if tx.get('tax_rate') is not None else '',
                    (str(tx['withholding_tax']) + ' ' + tx['currency']) if tx.get('withholding_tax') is not None else '',
                    (str(tx['solidarity_tax']) + ' ' + tx['currency']) if tx.get('solidarity_tax') is not None else '',
                    tx.get('withholding_country') or '',
                    (str(tx['withholding_tax_rate']) + ' %') if tx.get('withholding_tax_rate') is not None else '',
                    tx.get('transaction_reference') or tx.get('bank_reference') or tx.get('document_reference') or '',
                    '\n'.join(([status] if status else []) + [Path(s.get('source', '')).name for s in sources])]
                items = [QStandardItem(display_dates(str(value))) for value in values]
                for item in items:
                    item.setToolTip(item.text()); item.setData(item.text().casefold(), Qt.ItemDataRole.UserRole)
                for column in (0, 1): items[column].setData(values[column], Qt.ItemDataRole.UserRole)
                items[3].setData(float(Decimal(tx['amount'])), Qt.ItemDataRole.UserRole)
                items[0].setData(tx, Qt.ItemDataRole.UserRole + 1)
                if duplicate:
                    for item in items:
                        item.setBackground(Qt.GlobalColor.yellow)
                    items[-1].setToolTip('Mehrere Importquellen beschreiben dieselbe Zahlung. Sie wird im Saldo nur einmal gezählt.')
                if tx.get('fees') not in (None, ''):
                    for item in items:
                        item.setBackground(QColor('#d9eeff'))
                        item.setForeground(QColor('#102a43'))
                self.model.appendRow(items)
            if hasattr(self, 'table'): self.update_optional_columns()

    def update_optional_columns(self):
        """Keep the wide table calm; reveal detail columns only when populated."""
        for column in range(11, self.model.columnCount()):
            self.table.setColumnHidden(column, not any(self.model.item(row, column).text().strip()
                                                       for row in range(self.model.rowCount())))

    def selected_transaction(self):
        index = self.table.currentIndex()
        if not index.isValid(): raise ValueError('Bitte zuerst eine Buchung auswählen.')
        source = self.proxy.mapToSource(index)
        return self.model.item(source.row(), 0).data(Qt.ItemDataRole.UserRole + 1)

    def refresh_after_change(self):
        self.load_transactions(); self.update_sums(); self.filter_bookings(self.search.text())

    def edit_selected(self):
        try: tx = self.selected_transaction()
        except ValueError as error: QMessageBox.information(self, 'Buchung auswählen', str(error)); return
        if TransactionEditDialog(self.repository, tx, self).exec(): self.refresh_after_change()

    def assign_dividend(self):
        try: tx = self.selected_transaction()
        except ValueError as error: QMessageBox.information(self, 'Buchung auswählen', str(error)); return
        if TransactionEditDialog(self.repository, tx, self, dividend=True).exec(): self.refresh_after_change()

    def resolve_duplicate(self):
        try: tx = self.selected_transaction()
        except ValueError as error: QMessageBox.information(self, 'Buchung auswählen', str(error)); return
        if len(tx.get('booking_sources', ())) < 2:
            QMessageBox.information(self, 'Keine Dublette', 'Diese Buchung hat keine doppelte Importquelle.'); return
        reason, ok = QInputDialog.getText(self, 'Dubletten auflösen', 'Prüfergebnis / Beleg:')
        if not ok: return
        try: self.repository.resolve_duplicate(reference(tx), reason)
        except ValueError as error: QMessageBox.warning(self, 'Dubletten prüfen', str(error)); return
        self.refresh_after_change()

    def reconcile_selected(self):
        try: tx = self.selected_transaction()
        except ValueError as error: QMessageBox.information(self, 'Buchung auswählen', str(error)); return
        row = getattr(self, 'reconciliation_rows', {}).get(reference(tx), {})
        candidates = row.get('candidates') or []
        if not candidates:
            QMessageBox.information(self, 'Kein Gegenbeleg',
                'Für diese Depotbuchung wurde keine passende Geldbuchung gefunden.'); return
        transactions = {reference(item): item for item in self.repository.transactions()}
        labels = []
        refs = []
        for candidate_ref in candidates:
            candidate = transactions.get(candidate_ref)
            if not candidate: continue
            labels.append(f"{candidate['date']} · {candidate['account']} · {candidate['amount']} {candidate['currency']} · "
                          f"{candidate.get('purpose') or candidate.get('bank_reference') or candidate['external_id']}")
            refs.append(candidate_ref)
        if not labels:
            return
        selected, ok = QInputDialog.getItem(self, 'Geldbuchung zuordnen', 'Gegenbeleg:', labels, 0, False)
        if not ok: return
        reason, ok = QInputDialog.getText(self, 'Zuordnung bestätigen', 'Prüfgrund / Beleg:')
        if not ok: return
        try:
            self.repository.confirm_booking_link(reference(tx), refs[labels.index(selected)], reason)
        except ValueError as error:
            QMessageBox.warning(self, 'Zuordnung prüfen', str(error)); return
        self.refresh_after_change()

    def delete_selected(self):
        try: tx = self.selected_transaction()
        except ValueError as error: QMessageBox.information(self, 'Buchung auswählen', str(error)); return
        answer = QMessageBox.question(self, 'Buchung löschen',
            'Diese Buchung aus allen Berechnungen entfernen?\nDie unveränderte Importquelle bleibt zur Nachvollziehbarkeit gespeichert.',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Cancel)
        if answer != QMessageBox.StandardButton.Yes: return
        reason, ok = QInputDialog.getText(self, 'Löschung begründen', 'Grund / Beleg:')
        if not ok: return
        try: self.repository.exclude_transactions([reference(tx)], reason)
        except ValueError as error: QMessageBox.warning(self, 'Buchung löschen', str(error)); return
        self.refresh_after_change()

    def filter_bookings(self, text):
        self.proxy.setFilterFixedString(display_dates(text.strip()))
        self.count.setText(f'{self.proxy.rowCount()} von {self.model.rowCount()} Buchungen · Spaltenkopf: sortieren · Strg+C: ausgewählte Zeilen kopieren')

    def update_sums(self, *args):
        from portfolio_v5.models import money
        try:
            value = money(self.start_amount.text().strip())
            total = Decimal(value) if value is not None else None
            if total is None or not total.is_finite():
                raise ValueError('Ungültiger Startbetrag')
        except (ValueError, InvalidOperation):
            self.sum_note.setText('Bitte einen gültigen Startbetrag eingeben, z. B. 1.000,00.')
            for row in range(self.model.rowCount()):
                self.model.item(row, 5).setText('–')
                self.model.item(row, 5).setData(None, Qt.ItemDataRole.UserRole)
            self.filter_bookings(self.search.text())
            return
        for row, tx in enumerate(self.transactions):
            item = self.model.item(row, 5)
            wallet_trade = self.wallet and not tx.get('affects_cash', True) and tx['kind'] in ('BUY', 'SELL')
            if tx['currency'] == 'EUR' and (tx.get('affects_cash', True) or wallet_trade):
                amount = Decimal(tx['amount'])
                total += (abs(amount) * (1 if tx['kind'] == 'BUY' else -1)) if wallet_trade else amount
                text = f'{total:,.2f}'.replace(',', 'X').replace('.', ',').replace('X', '.') + ' €'
                item.setText(text)
                item.setData(float(total), Qt.ItemDataRole.UserRole)
                item.setToolTip('Startbetrag plus Käufe minus Verkäufe; kein Marktwert oder FIFO-Einstand.' if self.wallet else
                    'Startbetrag plus alle bisherigen EUR-Buchungen, einschließlich ausgeblendeter Suchtreffer.')
            else:
                item.setText('–')
                item.setData(None, Qt.ItemDataRole.UserRole)
                item.setToolTip('Nur Depotstückzahl/Einstand: keine Kontobuchung.' if not tx.get('affects_cash', True)
                                else 'Fremdwährungsbuchung: nicht in der EUR-Summe enthalten.')
            item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        formatted = f'{total:,.2f}'.replace(',', 'X').replace('.', ',').replace('X', '.')
        self.sum_note.setText(('Käufe minus Verkäufe' if self.wallet else 'Laufende EUR-Summe')
            + f': {formatted} € · Suche verändert die Berechnung nicht.')
        self.filter_bookings(self.search.text())
