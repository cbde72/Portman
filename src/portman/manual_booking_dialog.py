"""Manual cash or security entry for any active account."""
from PySide6.QtCore import QDate
from PySide6.QtWidgets import QDialog, QVBoxLayout, QFormLayout, QLabel, QComboBox, QDateEdit, QLineEdit, QDialogButtonBox
from .manual_booking import save_booking


class ManualBookingDialog(QDialog):
    def __init__(self, repo, account=None, parent=None):
        super().__init__(parent)
        self.repo = repo
        self.setWindowTitle('Manuell ein- oder ausbuchen')
        self.setMinimumWidth(580)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        layout.addLayout(form)
        self.account = QComboBox()
        self.account.addItems([r['name'] for r in repo.account_records() if r['active']])
        if account: self.account.setCurrentText(account)
        form.addRow('Konto', self.account)
        self.mode = QComboBox()
        self.mode.addItem('Geldbewegung', 'cash')
        self.mode.addItem('Wertpapierbewegung ohne Geldbewegung', 'security')
        form.addRow('Buchung', self.mode)
        self.direction = QComboBox()
        self.direction.addItem('Einbuchen', 'in')
        self.direction.addItem('Ausbuchen', 'out')
        form.addRow('Richtung', self.direction)
        self.day = QDateEdit(QDate.currentDate())
        self.day.setCalendarPopup(True)
        self.day.setDisplayFormat('dd.MM.yyyy')
        form.addRow('Buchungsdatum', self.day)
        self.amount = QLineEdit()
        self.amount.setPlaceholderText('Positiver Betrag, z. B. 100,00')
        form.addRow('Betrag in EUR', self.amount)
        self.depot = QComboBox()
        form.addRow('Depot / Unterdepot', self.depot)
        self.security = QComboBox()
        self.security.setEditable(True)
        form.addRow('Wertpapier / neue ISIN', self.security)
        self.name = QLineEdit()
        form.addRow('Name bei neuem Wertpapier', self.name)
        self.quantity = QLineEdit()
        form.addRow('Anteile (positiv)', self.quantity)
        self.price = QLineEdit()
        self.price.setPlaceholderText('Leer: vorhandenen Stückwert verwenden')
        form.addRow('Bewertungskurs in EUR', self.price)
        self.note = QLineEdit()
        form.addRow('Buchungstext', self.note)
        self.hint = QLabel('Geldbewegungen ändern den Kontosaldo. Wertpapierbewegungen ändern nur den Depotbestand. '
            'Einbuchungen sind keine Käufe; Anschaffungskosten bleiben unbekannt. '
            'Spätere Depotstände haben Vorrang vor rückdatierten Buchungen. '
            'Gespeicherte Buchungen sind in der Importhistorie nachvollziehbar und rückgängig machbar.')
        self.hint.setWordWrap(True)
        layout.addWidget(self.hint)
        self.error = QLabel()
        self.error.setWordWrap(True)
        layout.addWidget(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText('Buchung speichern')
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.form = form
        self.account.currentTextChanged.connect(self.refresh_depots)
        self.depot.currentIndexChanged.connect(self.refresh_securities)
        self.day.dateChanged.connect(self.refresh_securities)
        self.mode.currentIndexChanged.connect(self.update_mode)
        self.refresh_depots()
        self.update_mode()

    def refresh_depots(self):
        self.depot.clear()
        for depot in self.repo.depots():
            if depot['active'] and depot['account'] == self.account.currentText():
                self.depot.addItem(depot['depot_name'])
        if not self.depot.count(): self.depot.addItem(self.account.currentText())
        self.refresh_securities()

    def refresh_securities(self):
        self.security.clear()
        self.security.addItem('', '')
        for p in self.repo.holdings(self.day.date().toString('yyyy-MM-dd'), self.account.currentText()):
            if p['depot'] == self.depot.currentText():
                self.security.addItem(f"{p['name']} · {p['key']} · {p['quantity']} Anteile", p['key'])

    def update_mode(self):
        securities = self.mode.currentData() == 'security'
        self.form.setRowVisible(self.amount, not securities)
        for widget in (self.depot, self.security, self.name, self.quantity, self.price):
            self.form.setRowVisible(widget, securities)

    def accept(self):
        try:
            security = self.security.currentData() if self.security.currentText() == self.security.itemText(self.security.currentIndex()) else self.security.currentText().strip()
            self.result_record = save_booking(self.repo, account=self.account.currentText(),
                day=self.day.date().toString('yyyy-MM-dd'), mode=self.mode.currentData(), direction=self.direction.currentData(),
                amount=self.amount.text(), depot=self.depot.currentText(), security=security or '', name=self.name.text(),
                quantity=self.quantity.text(), price=self.price.text(), note=self.note.text())
        except (ValueError, TypeError) as error:
            self.error.setText(str(error))
            return
        super().accept()
