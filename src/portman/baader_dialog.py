import threading
import time
import re

from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QLineEdit, QVBoxLayout

from .baader_banking import fetch_baader, BankingError, Cancelled
from .baader_credentials import BaaderCredentialStore
from .ing_dialog import INGDialog, INGWorker


class BaaderWorker(INGWorker):
    challenge_requested = Signal(object)
    bank = 'Baader'

    def fetch_data(self, *args, **kwargs):
        return fetch_baader(*args, **kwargs)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.answer = threading.Event()
        self.tan = None

    def challenge(self, message):
        self.answer.clear()
        self.challenge_requested.emit(message)
        deadline = time.monotonic() + 180
        while not self.answer.wait(.1):
            if self.isInterruptionRequested():
                raise Cancelled('Abruf abgebrochen.')
            if time.monotonic() >= deadline:
                raise BankingError('Die TAN-Eingabe ist abgelaufen. Bitte erneut abrufen.')
        tan, self.tan = self.tan, None
        if self.isInterruptionRequested() or tan is None:
            raise Cancelled('Abruf abgebrochen.')
        return tan

    def run(self):
        try:
            self.batches = self.fetch_data(*self.credentials, source_root=self.source_root,
                cancelled=self.isInterruptionRequested, progress=self.status.emit,
                challenge=self.challenge, **self.options)
        except Cancelled:
            self.error = 'Abruf abgebrochen. Es wurden keine Portfolio-Daten gespeichert.'
        except BankingError as error:
            self.error = str(error)
        except Exception:
            self.error = f'{self.bank}-Abruf fehlgeschlagen. Es wurden keine Portfolio-Daten gespeichert.'
        finally:
            self.credentials = self.tan = None


class BaaderTANDialog(QDialog):
    title = 'Baader · SMS-TAN'
    placeholder = 'SMS-TAN eingeben'
    def __init__(self, message, parent=None):
        super().__init__(parent)
        self.setWindowTitle(self.title)
        self.setMinimumWidth(440)
        layout = QVBoxLayout(self)
        note = QLabel(str(message))
        note.setTextFormat(Qt.TextFormat.PlainText)
        note.setWordWrap(True)
        layout.addWidget(note)
        self.tan = QLineEdit()
        self.tan.setEchoMode(QLineEdit.EchoMode.Password)
        self.tan.setMaxLength(12)
        self.tan.setPlaceholderText(self.placeholder)
        layout.addWidget(self.tan)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText('Freigeben')
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('Abbrechen')
        buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)
        self.tan.textChanged.connect(lambda value: buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(
            bool(value) and value.isascii() and value.isdigit()))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class BaaderDialog(INGDialog):
    bank = 'Baader / finanzen.net ZERO'
    user_label = 'Baader-Stammnummer / Benutzerkennung'
    pin_label = 'PIN des Baader-Kundenportals'
    store_type = BaaderCredentialStore
    worker_type = BaaderWorker
    tan_dialog_type = BaaderTANDialog
    login_site = 'konto.baaderbank.de'
    user_hint = ('Baader nennt die siebenstellige Stammnummer als Benutzerkennung. '
                 'Verwende den Zugang, mit dem die Anmeldung im Baader-Kundenportal funktioniert.')
    introduction = ('Kontosalden, Wertpapierbestände und verfügbare Kontoumsätze über die Baader Bank abrufen. '
                    'Verwende Stammnummer / Benutzerkennung und PIN des Baader-Kundenportals (konto.baaderbank.de). '
                    'Die IBAN des Verrechnungskontos ersetzt diese Benutzerkennung nicht. '
                    'Die Anmeldung kann eine SMS-TAN verlangen.\n\n'
                    'Zugangsdaten werden auf Wunsch im Windows-Anmeldeinformationsspeicher gesichert. '
                    'Anschließend das bestehende ZERO-Wertpapierdepot zuordnen und die Importvorschau prüfen. '
                    'Kryptobestände und das PDF-Postfach sind nicht Bestandteil dieses Abrufs.')

    def __init__(self, *args, **kwargs):
        self.tan_dialog = None
        super().__init__(*args, **kwargs)
        self.user.setPlaceholderText(f'Benutzerkennung von {self.login_site}')
        self.user.setToolTip(self.user_hint)

    def start_fetch(self):
        if self.worker and self.worker.isRunning():
            return
        if not self.user.text().strip():
            self.status.setText(f'Bitte die Benutzerkennung für {self.bank} eingeben.')
            return
        if re.fullmatch(r'DE\d{20}', ''.join(self.user.text().split()).upper()):
            self.status.setText(f'Hier wird die Benutzerkennung für {self.bank} benötigt. Die IBAN ist keine Benutzerkennung.')
            return
        if not self.pin.text():
            self.status.setText(f'Bitte die Online-Banking-PIN für {self.bank} eingeben.')
            return
        if not self.product.text().strip():
            self.status.setText('Die registrierte FinTS-Produkt-ID für Portman fehlt. Sie gehört zur Software '
                                'und wird von der FinTS-Leitstelle vergeben; IBAN oder Depotnummer sind hier nicht gültig. '
                                'Ohne diese Einrichtung kann noch kein Abruf starten.')
            return
        super().start_fetch()

    def connect_worker(self):
        self.worker.challenge_requested.connect(self.show_challenge)

    def show_challenge(self, message):
        if self.cancel_requested or not self.worker.isRunning():
            self.worker.answer.set()
            return
        try:
            self.tan_dialog = self.tan_dialog_type(message, self)
            accepted = self.tan_dialog.exec() == QDialog.DialogCode.Accepted
            self.worker.tan = self.tan_dialog.tan.text() if accepted else None
            self.tan_dialog.tan.clear()
            self.tan_dialog.deleteLater()
        finally:
            self.tan_dialog = None
            self.worker.answer.set()

    def fetch_finished(self):
        if self.tan_dialog:
            self.tan_dialog.reject()
        super().fetch_finished()

    def reject(self):
        if self.tan_dialog:
            self.tan_dialog.reject()
        super().reject()
