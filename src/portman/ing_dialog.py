import os
from copy import deepcopy
from pathlib import Path

from PySide6.QtCore import QDate, QThread, Signal, Qt
from PySide6.QtWidgets import (QCheckBox, QDateEdit, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLabel,
                              QLineEdit, QPushButton, QVBoxLayout)

from .ing_banking import BankingError, Cancelled, fetch_ing
from .ing_credentials import INGCredentialStore, CredentialError


class INGWorker(QThread):
    status = Signal(str)

    def __init__(self, user, pin, product_id, source_root, parent=None, *, history_start=None, history_end=None, fetch_documents=False):
        super().__init__(parent)
        self.credentials = (user, pin, product_id)
        self.source_root = source_root
        self.batches = None
        self.error = None
        self.options = dict(history_start=history_start, history_end=history_end, fetch_documents=fetch_documents)

    def run(self):
        try:
            self.batches = fetch_ing(*self.credentials, source_root=self.source_root,
                cancelled=self.isInterruptionRequested, progress=self.status.emit, **self.options)
        except Cancelled:
            pass
        except BankingError as error:
            self.error = str(error)
        except ImportError:
            self.error = ('Eine Python-Abhängigkeit für den ING-Abruf fehlt. In VS Code unter '
                          '„Terminal → Aufgabe ausführen“ die Aufgabe „Portman: Umgebung vorbereiten“ '
                          'ausführen und Portman anschließend über „Portman starten“ neu starten.')
        except Exception:
            self.error = 'Der ING-Abruf konnte nicht abgeschlossen werden. Es wurden keine Daten gespeichert.'
        finally:
            self.credentials = None


class INGDialog(QDialog):
    bank = 'ING'
    user_label = 'Benutzername / Zugangsnummer'
    pin_label = 'Passwort / Internetbanking-PIN'
    store_type = INGCredentialStore
    worker_type = INGWorker
    introduction = ('Salden, Depotbestände und die gewählten historischen Daten abrufen und anschließend in der Importvorschau prüfen. '
                    'Gespeicherte Zugangsdaten liegen geschützt im Windows-Anmeldeinformationsspeicher.\n\n'
                    'ING benötigt eine erfolgreiche Anmeldung im Online-Banking innerhalb der letzten 90 Tage. '
                    'Girokontoumsätze sind über FinTS laut ING bis zu 90 Tage rückwirkend verfügbar.')

    def __init__(self, source_root, parent=None, *, credential_store=None):
        super().__init__(parent)
        self.source_root = Path(source_root)
        self.credential_store = credential_store or self.store_type(self.source_root)
        self.worker = None
        self.batches = None
        self.cancel_requested = False
        self.credentials_persisted = False
        self.setWindowTitle(f'{self.bank} · Online-Abruf')
        self.setMinimumWidth(560)
        layout = QVBoxLayout(self)
        note = QLabel(self.introduction)
        note.setWordWrap(True)
        layout.addWidget(note)
        form = QFormLayout()
        self.user = QLineEdit()
        self.pin = QLineEdit()
        self.pin.setEchoMode(QLineEdit.EchoMode.Password)
        self.product = QLineEdit(os.environ.get('FINTS_PRODUCT_ID', ''))
        self.product.setPlaceholderText('Registrierte FinTS-Produkt-ID')
        form.addRow(self.user_label, self.user)
        form.addRow(self.pin_label, self.pin)
        form.addRow('FinTS-Produkt-ID', self.product)
        self.remember = QCheckBox('Benutzername, PIN und FinTS-Produkt-ID beim Abruf speichern')
        self.remember.setChecked(True)
        form.addRow(self.remember)
        self.save_login = QPushButton('Zugangsdaten jetzt speichern')
        self.delete_login = QPushButton('Gespeicherte Zugangsdaten löschen')
        self.save_login.clicked.connect(self.save_credentials)
        self.delete_login.clicked.connect(self.delete_credentials)
        form.addRow(self.save_login, self.delete_login)
        self.history = QCheckBox('Gebuchte Kontoumsätze abrufen')
        self.history.setChecked(True)
        from .bank_history_range import history_start_editor
        self.history_start = history_start_editor(getattr(parent, 'repository', None), self.bank)
        self.history_end = QDateEdit(QDate.currentDate())
        for editor in (self.history_start, self.history_end):
            editor.setCalendarPopup(True)
            editor.setDisplayFormat('dd.MM.yyyy')
            editor.setMaximumDate(QDate.currentDate())
            self.history.toggled.connect(editor.setEnabled)
        self.documents = QCheckBox('Alle über FinTS verfügbaren PDF-Kontoauszüge abrufen')
        self.documents.setChecked(self.bank == 'ING')
        self.documents.setVisible(self.bank == 'ING')
        form.addRow(self.history)
        form.addRow('Umsätze von', self.history_start)
        form.addRow('Umsätze bis', self.history_end)
        form.addRow(self.documents)
        layout.addLayout(form)
        document_note = QLabel('Das ist kein vollständiger Post-Box-Abruf. Weitere Dokumente und ältere Unterlagen '
                               'können nach dem Download aus der ING-Post-Box unter Historie → Bankarchiv hinzugefügt werden.')
        document_note.setWordWrap(True)
        document_note.setVisible(self.bank == 'ING')
        layout.addWidget(document_note)
        product_note = QLabel('Die Produkt-ID gehört zur Bankingsoftware und ist keine Konto- oder Depotnummer. '
                              'Verwende eine für deine Anwendung registrierte ID (auch über FINTS_PRODUCT_ID möglich).')
        product_note.setWordWrap(True)
        layout.addWidget(product_note)
        self.status = QLabel('Bereit. Der Abruf speichert noch keine Portfolio-Daten.')
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        from .bank_status import add_copy_button
        self.copy_message = add_copy_button(layout, self.status)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.fetch_button = QPushButton(f'{self.bank} abrufen')
        self.buttons.addButton(self.fetch_button, QDialogButtonBox.ButtonRole.ActionRole)
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('Abbrechen')
        self.fetch_button.clicked.connect(self.start_fetch)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        try:
            saved = self.credential_store.load()
            if saved:
                self.user.setText(saved['user'])
                self.pin.setText(saved['pin'])
                self.product.setText(saved['product_id'])
                self.credentials_persisted = True
                self.status.setText(f'Gespeicherte {self.bank}-Zugangsdaten geladen. Bereit zum Abruf.')
        except CredentialError as error:
            self.status.setText(str(error))

    def save_credentials(self):
        try:
            self.credential_store.save(self.user.text(), self.pin.text(), self.product.text())
        except CredentialError as error:
            self.status.setText(str(error))
            return False
        self.remember.setChecked(True)
        self.credentials_persisted = True
        self.status.setText('Benutzername, PIN und FinTS-Produkt-ID im Windows-Anmeldeinformationsspeicher gespeichert.')
        return True

    def delete_credentials(self):
        try:
            self.credential_store.delete()
        except CredentialError as error:
            self.status.setText(str(error))
            return
        self.user.clear()
        self.pin.clear()
        self.product.clear()
        self.credentials_persisted = False
        self.status.setText(f'Gespeicherte {self.bank}-Zugangsdaten gelöscht.')

    def start_fetch(self):
        if self.worker and self.worker.isRunning():
            return
        if not self.user.text().strip() or not self.pin.text() or not self.product.text().strip():
            self.status.setText('Bitte alle drei Felder ausfüllen.')
            return
        if self.history.isChecked() and self.history_start.date() > self.history_end.date():
            self.status.setText('Der Beginn des Umsatzzeitraums muss vor oder am Enddatum liegen.')
            return
        if self.remember.isChecked() and not self.save_credentials():
            return
        self.cancel_requested = False
        self.worker = self.worker_type(self.user.text(), self.pin.text(), self.product.text(), self.source_root, self,
            history_start=self.history_start.date().toPython() if self.history.isChecked() else None,
            history_end=self.history_end.date().toPython(), fetch_documents=self.documents.isChecked())
        if not self.remember.isChecked():
            # The worker owns its private credential tuple from here on.  Do not
            # leave an unsaved PIN in the dialog widget or Qt object tree.
            self.pin.clear()
        for field in (self.user, self.pin, self.product, self.fetch_button, self.history, self.history_start, self.history_end, self.documents,
                      self.remember, self.save_login, self.delete_login):
            field.setEnabled(False)
        self.worker.status.connect(self.status.setText)
        self.worker.finished.connect(self.fetch_finished)
        self.connect_worker()
        owner = self.parent()
        while owner is not None and not hasattr(owner, 'job_center'):
            owner = owner.parent()
        if owner is not None:
            owner.job_center.register(self.worker, f'{self.bank} · Online-Abruf')
        self.status.setText('Verbindung wird hergestellt …')
        self.worker.start()

    def connect_worker(self):
        """Hook for banks that support interactive TAN challenges."""

    def fetch_finished(self):
        if self.cancel_requested:
            self.worker.batches = None
            super().reject()
            return
        if self.worker.error:
            self.status.setText(self.worker.error)
            for field in (self.user, self.pin, self.product, self.fetch_button, self.history, self.documents,
                          self.remember, self.save_login, self.delete_login):
                field.setEnabled(True)
            self.history_start.setEnabled(self.history.isChecked())
            self.history_end.setEnabled(self.history.isChecked())
            self.pin.setFocus()
            return
        self.batches = self.worker.batches
        if self.batches is not None:
            self.accept()

    def reject(self):
        if self.worker and self.worker.isRunning():
            self.cancel_requested = True
            self.worker.requestInterruption()
            self.status.setText('Abruf wird abgebrochen. Eine laufende Serverantwort wird noch abgewartet …')
            return
        if not self.credentials_persisted:
            self.pin.clear()
        super().reject()

    def closeEvent(self, event):
        if self.worker and self.worker.isRunning():
            self.reject()
            event.ignore()
        else:
            super().closeEvent(event)


class INGDepotDialog(QDialog):
    """Explicitly continue an existing depot instead of counting its holdings twice."""
    def __init__(self, repository, batches, parent=None, *, bank='ING'):
        super().__init__(parent)
        self.batches = deepcopy(batches)
        self.choices = []
        self.known_choices = True
        self.bank = bank
        self.setWindowTitle(f'{bank} · Bestehende Depots weiterführen')
        self.setMinimumWidth(600)
        layout = QVBoxLayout(self)
        label = QLabel(f'Wähle für jedes {bank}-Depot den bisherigen Depotbestand in Portman. '
                       'So wird der neue Stand in derselben Historie geführt. '
                       '„Separates Depot“ ist für Depots gedacht, die noch nicht importiert wurden.')
        label.setWordWrap(True)
        layout.addWidget(label)
        form = QFormLayout()
        depots = [d for d in repository.depots() if d['active']]
        if bank.startswith('Baader'):
            # ZERO crypto exports are a separate history, never a replacement target.
            crypto_depots = {p['depot'] for p in repository.holdings() if p['asset_type'] == 'Krypto'}
            depots = [d for d in depots if d['depot_name'] not in crypto_depots
                      and 'krypto' not in d['depot_name'].casefold()]
        for batch in self.batches:
            if batch.errors or not batch.snapshots:
                continue
            combo = QComboBox()
            combo.addItem('Bitte Depot auswählen', None)
            combo.addItem('Separates Depot anlegen', batch.snapshots[0].account)
            for depot in depots:
                combo.addItem(f"{depot['depot_name']} → {depot['account']}", depot['depot_name'])
            previous = repository.previous_bank_depot(batch.path)
            if previous and combo.findData(previous) >= 0:
                combo.setCurrentIndex(combo.findData(previous))
            else:
                self.known_choices = False
                if not depots:
                    combo.setCurrentIndex(1)
            form.addRow(batch.snapshots[0].account, combo)
            self.choices.append((batch, combo))
        layout.addLayout(form)
        self.status = QLabel('Die endgültige Übernahme erfolgt erst in der anschließenden Importvorschau.')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText('Weiter zur Importvorschau')
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('Abbrechen')
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def exec_if_needed(self):
        if self.known_choices:
            self.accept()
            if self.result() == QDialog.DialogCode.Accepted:
                return self.result()
        return self.exec()

    def accept(self):
        from portfolio_v5.accounts import account_key
        targets = [combo.currentData() for batch, combo in self.choices]
        if any(target is None for target in targets):
            self.status.setText(f'Bitte für jedes {self.bank}-Depot eine Auswahl treffen.')
            return
        if len({account_key(target) for target in targets}) != len(targets):
            self.status.setText(f'Zwei {self.bank}-Depots dürfen nicht denselben bisherigen Depotbestand ersetzen.')
            return
        for batch, combo in self.choices:
            source = batch.snapshots[0].account
            target = combo.currentData()
            batch.snapshots[0].account = target
            batch.account_names = [target]
            batch.warnings.append(f'Bankquelle: {source}; Depot-Historie: {target}.')
        super().accept()
