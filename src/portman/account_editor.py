from .date_display import display_dates
from .date_edit import DateLineEdit
import json
from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QVBoxLayout, QFormLayout,
    QLineEdit, QComboBox, QTabWidget, QWidget, QLabel, QDateEdit, QTableWidget,
    QTableWidgetItem, QAbstractItemView, QMessageBox, QListWidget, QListWidgetItem)

TYPES = ['Girokonto', 'Tagesgeld', 'Festgeld', 'Sparkonto', 'Riester', 'Direktversicherung',
         'Depot', 'Krypto Wallet', 'Verrechnungskonto', 'Bausparvertrag', 'Kreditkonto', 'Sonstiges']

class AccountEditor(QDialog):
    def __init__(self, repo, record=None, parent_account=None, parent=None):
        super().__init__(parent)
        self.repo, self.record = repo, record
        self.setWindowTitle('Kontodetails' if record else 'Konto anlegen')
        self.resize(640, 650)
        root = QVBoxLayout(self)
        root.addWidget(QLabel('Kontodetails und Zuordnung jederzeit ändern.'))
        tabs = QTabWidget(); root.addWidget(tabs)
        self.fields = {}
        details = json.loads(record['details']) if record else {}
        self.original_details = details
        for title, fields in [
            ('Allgemein', [('name','Name'), ('owner','Kontoinhaber'), ('institution','Institut'),
                          ('iban','IBAN'), ('bic','BIC'), ('number','Konto- / Vertragsnummer')]),
            ('Konditionen', [('interest','Guthabenzins (% p. a.)'), ('overdraft_interest','Überziehungszins (% p. a.)'),
                            ('credit_limit','Disporahmen (€)'),
                            ('fee','Kontoführung (€ / Monat)'), ('start','Laufzeitbeginn (TT.MM.JJJJ)'),
                            ('end','Laufzeitende (TT.MM.JJJJ)'), ('term','Laufzeit / Kündigungsfrist'),
                            ('interest_interval','Zinsgutschrift'), ('notes','Notizen')])]:
            page = QWidget(); form = QFormLayout(page); form.setSpacing(14)
            tabs.addTab(page, title)
            if title == 'Allgemein':
                self.kind = QComboBox(); self.kind.addItems(TYPES)
                self.kind.setCurrentText(details.get('kind', 'Sonstiges'))
                form.addRow('Kontotyp', self.kind)
                self.parent_account = QComboBox(); self.parent_account.addItem('Kein übergeordnetes Konto', None)
                for r in repo.account_records():
                    if r['active'] and (not record or r['account_key'] != record['account_key']):
                        self.parent_account.addItem(r['name'], r['account_key'])
                self.parent_account.setCurrentIndex(max(0, self.parent_account.findData(
                    record['parent_key'] if record else parent_account)))
                form.addRow('Übergeordnetes Konto', self.parent_account)
                self.cash_account = QComboBox()
                self.cash_account.addItem('Kein Verrechnungskonto zugeordnet', '')
                for r in repo.account_records():
                    if r['active'] and json.loads(r['details']).get('kind') in ('Girokonto', 'Verrechnungskonto') and (not record or r['account_key'] != record['account_key']):
                        self.cash_account.addItem(r['name'], r['account_key'])
                self.cash_account.setCurrentIndex(max(0, self.cash_account.findData(details.get('cash_account_key', ''))))
                self.cash_account.setEnabled(self.kind.currentText() == 'Depot')
                self.kind.currentTextChanged.connect(lambda kind: self.cash_account.setEnabled(kind == 'Depot'))
                form.addRow('Standard-Verrechnungskonto', self.cash_account)
                self.payment_accounts = QListWidget(); self.payment_accounts.setMaximumHeight(110)
                selected_payment = set(details.get('cash_account_keys') or [])
                for index in range(1, self.cash_account.count()):
                    item = QListWidgetItem(self.cash_account.itemText(index))
                    item.setData(Qt.ItemDataRole.UserRole, self.cash_account.itemData(index))
                    item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                    item.setCheckState(Qt.CheckState.Checked if item.data(Qt.ItemDataRole.UserRole) in selected_payment
                                       else Qt.CheckState.Unchecked)
                    self.payment_accounts.addItem(item)
                self.payment_accounts.setEnabled(self.kind.currentText() == 'Depot')
                self.kind.currentTextChanged.connect(lambda kind: self.payment_accounts.setEnabled(kind == 'Depot'))
                form.addRow('Weitere Zahlungskonten', self.payment_accounts)
            for key, label in fields:
                edit = (DateLineEdit if key in ('start', 'end') else QLineEdit)(record['name'] if key == 'name' and record else details.get(key, ''))
                self.fields[key] = edit; form.addRow(label, edit)
        from .crypto_wallet_panel import CryptoWalletPanel
        self.crypto_import = CryptoWalletPanel(self.validate_name)
        wallet_tab = tabs.addTab(self.crypto_import, 'Wallet-Import')
        def update_wallet_tab():
            tabs.setTabVisible(wallet_tab, not self.record and self.kind.currentText() == 'Krypto Wallet')
            self.validate_name()
        self.kind.currentTextChanged.connect(update_wallet_tab)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        self.name_status = QLabel()
        self.name_status.setWordWrap(True)
        root.addWidget(self.name_status)
        self.save_button = buttons.button(QDialogButtonBox.StandardButton.Save)
        buttons.accepted.connect(self.save); buttons.rejected.connect(self.reject); root.addWidget(buttons)
        self.fields['name'].textChanged.connect(self.validate_name)
        update_wallet_tab()

    def validate_name(self, *args):
        try:
            if self.kind.currentText() == 'Krypto Wallet' and not self.record and self.crypto_import.error:
                raise ValueError(self.crypto_import.error)
            self.repo.validate_account_name(self.fields['name'].text(),
                                           self.record['name'] if self.record else None)
        except ValueError as error:
            self.name_status.setText(str(error))
            self.save_button.setEnabled(False)
        else:
            self.name_status.setText('Kontoname verfügbar.' if not self.record else '')
            self.save_button.setEnabled(True)

    def save(self):
        values = {k: w.text().strip() for k, w in self.fields.items()}
        name = values.pop('name'); values['kind'] = self.kind.currentText()
        values = {**self.original_details, **values}
        values['cash_account_key'] = self.cash_account.currentData() if values['kind'] == 'Depot' else ''
        values['cash_account_keys'] = ([self.payment_accounts.item(index).data(Qt.ItemDataRole.UserRole)
            for index in range(self.payment_accounts.count())
            if self.payment_accounts.item(index).checkState() == Qt.CheckState.Checked
            and self.payment_accounts.item(index).data(Qt.ItemDataRole.UserRole) != values['cash_account_key']]
            if values['kind'] == 'Depot' else [])
        try:
            if values['kind'] == 'Depot' and not values['cash_account_key']:
                raise ValueError('Jedes Depot benötigt ein Standard-Giro- oder Verrechnungskonto.')
            if values['kind'] == 'Krypto Wallet' and not self.record and self.crypto_import.path:
                if self.crypto_import.error or not self.crypto_import.batch:
                    raise ValueError(self.crypto_import.error or 'Bitte eine gültige CSV auswählen.')
                from .crypto_wallet_import import save_wallet
                from .import_jobs import run_job
                factory, path = type(self.repo), self.repo.store.path
                options = {'backups': self.repo.backups_enabled} if hasattr(self.repo, 'backups_enabled') else {}
                parent, batch = self.parent_account.currentData(), self.crypto_import.batch
                def import_wallet(job):
                    worker_repo = factory(path, **options)
                    try:
                        save_wallet(worker_repo, name, values, parent, batch, job.isInterruptionRequested)
                        return True
                    finally:
                        worker_repo.close()
                run_job(self, path, 'Krypto-Wallet und Zeitleiste speichern', import_wallet)
            else:
                self.repo.save_account(name, values, self.parent_account.currentData(),
                                       self.record['name'] if self.record else None)
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, 'Kontodetails prüfen', str(exc)); return
        self.accept()

class BalanceDialog(QDialog):
    def __init__(self, repo, account, parent=None):
        super().__init__(parent)
        self.repo, self.account = repo, account
        self.setWindowTitle('Saldo · ' + account); self.resize(720, 500)
        root = QVBoxLayout(self)
        hint = QLabel('Jeder gespeicherte Saldo bleibt in der Historie erhalten. Zum Datum gilt der neueste Eintrag; bei gleichem Datum die zuletzt gespeicherte Version.')
        hint.setWordWrap(True); root.addWidget(hint)
        form = QFormLayout(); root.addLayout(form)
        self.amount = QLineEdit(); self.amount.setPlaceholderText('z. B. 12.345,67 oder -250,00')
        self.date = QDateEdit(QDate.currentDate()); self.date.setCalendarPopup(True); self.date.setDisplayFormat('dd.MM.yyyy')
        self.note = QLineEdit(); self.note.setPlaceholderText('z. B. Kontoauszug oder Korrektur')
        form.addRow('Neuer Saldo (€)', self.amount); form.addRow('Gültig ab', self.date); form.addRow('Notiz', self.note)
        table = QTableWidget(0, 4); table.setHorizontalHeaderLabels(['Datum', 'Saldo (€)', 'Quelle / Notiz', 'Erfasst'])
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers); table.setAlternatingRowColors(True)
        rows = [(r['effective_date'], r['value'], r['note'], r['created_at']) for r in repo.balance_history(account)]
        record = next(r for r in repo.account_records() if r['name'] == account)
        from portfolio_v5.accounts import account_key
        for r in repo.db.execute('SELECT b.*,i.path,i.active FROM balances b JOIN imports i ON i.id=b.import_id ORDER BY b.period DESC,b.id DESC'):
            if account_key(r['account']) == record['account_key']:
                rows.append((r['period'], r['value'], ('Import: ' if r['active'] else 'Zurückgenommen: ') + r['category'] + ' · ' + r['path'], ''))
        table.setRowCount(len(rows))
        for i, row in enumerate(rows):
            for j, value in enumerate(row): table.setItem(i, j, QTableWidgetItem(display_dates(value)))
        table.resizeColumnsToContents(); root.addWidget(table)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.save); buttons.rejected.connect(self.reject); root.addWidget(buttons)

    def save(self):
        try: self.repo.add_balance(self.account, self.amount.text(), self.date.date().toString('yyyy-MM-dd'), self.note.text())
        except ValueError as exc:
            QMessageBox.warning(self, 'Saldo prüfen', str(exc)); return
        self.accept()
