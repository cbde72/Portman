import base64
import os
import threading
import time
from pathlib import Path

from PySide6.QtCore import QDate, QThread, Signal, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QCheckBox, QDateEdit, QDialog, QDialogButtonBox,
    QFormLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout)

from .comdirect_banking import fetch_comdirect, BankingError, Cancelled
from .comdirect_credentials import ComdirectCredentialStore, CredentialError
from .worker_dialog import WorkerDialogMixin


class ComdirectWorker(QThread):
    status = Signal(str)
    challenge_requested = Signal(object)

    def __init__(self, credentials, source_root, parent=None, **options):
        super().__init__(parent)
        self.credentials, self.source_root, self.options = credentials, source_root, options
        self.batches = self.error = None
        self.tan = None
        self.answer = threading.Event()

    def challenge(self, auth):
        self.answer.clear()
        self.challenge_requested.emit(auth)
        deadline = time.monotonic() + 180
        while not self.answer.wait(.1):
            if self.isInterruptionRequested():
                raise Cancelled('Abruf abgebrochen.')
            if time.monotonic() >= deadline:
                raise BankingError('Die TAN-Eingabe ist abgelaufen. Bitte erneut abrufen.')
        tan, self.tan = self.tan, None
        return tan

    def run(self):
        try:
            self.batches = fetch_comdirect(*self.credentials, source_root=self.source_root,
                cancelled=self.isInterruptionRequested, progress=self.status.emit,
                challenge=self.challenge, **self.options)
        except Cancelled:
            self.error = 'Abruf abgebrochen. Es wurden keine Portfolio-Daten gespeichert.'
        except BankingError as error:
            self.error = str(error)
        except Exception:
            self.error = 'comdirect-Abruf fehlgeschlagen. Es wurden keine Portfolio-Daten gespeichert.'
        finally:
            self.credentials = self.tan = None


class TANDialog(QDialog):
    def __init__(self, auth, parent=None):
        super().__init__(parent)
        self.setWindowTitle('comdirect · TAN-Freigabe')
        layout = QVBoxLayout(self)
        label = QLabel('Bitte die photoTAN-Grafik scannen und die TAN eingeben.' if auth['typ'] == 'P_TAN'
                       else 'Bitte die von comdirect gesendete mobileTAN eingeben.')
        label.setWordWrap(True)
        layout.addWidget(label)
        if auth['typ'] == 'P_TAN':
            pixmap = QPixmap()
            try:
                raw = base64.b64decode(auth.get('challenge', ''), validate=True)
                if len(raw) > 2 * 1024 * 1024 or not pixmap.loadFromData(raw, 'PNG'):
                    raise ValueError
            except (ValueError, TypeError):
                raise BankingError('Die photoTAN-Grafik konnte nicht angezeigt werden.') from None
            graphic = QLabel()
            graphic.setPixmap(pixmap.scaled(300, 300, Qt.AspectRatioMode.KeepAspectRatio,
                                            Qt.TransformationMode.FastTransformation))
            graphic.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(graphic)
        self.tan = QLineEdit()
        self.tan.setEchoMode(QLineEdit.EchoMode.Password)
        self.tan.setMaxLength(6)
        self.tan.setPlaceholderText('Sechsstellige TAN')
        layout.addWidget(self.tan)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText('Freigeben')
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('Abbrechen')
        buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)
        self.tan.textChanged.connect(lambda value: buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(
            len(value) == 6 and value.isascii() and value.isdigit()))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class ComdirectDialog(WorkerDialogMixin, QDialog):
    def __init__(self, source_root, parent=None, *, credential_store=None):
        super().__init__(parent)
        self.source_root = Path(source_root)
        self.store = credential_store or ComdirectCredentialStore(source_root)
        self.worker = self.batches = self.tan_dialog = None
        self.cancel_requested = False
        self.setWindowTitle('comdirect · Online-Abruf')
        self.setMinimumWidth(590)
        layout = QVBoxLayout(self)
        note = QLabel('Kontosalden und Depotbestände abrufen, vorhandenen Konten zuordnen und in der Importvorschau prüfen. '
                      'Depotbestände werden bei jedem Import vollständig synchronisiert. '
                      'Für die Anmeldung wird das bei comdirect eingestellte TAN-Verfahren verwendet.')
        note.setWordWrap(True)
        layout.addWidget(note)
        link_color = '#93c5fd' if self.palette().window().color().lightness() < 128 else '#1d4ed8'
        link = QLabel(f'<a style="color:{link_color}" href="https://www.comdirect.de/cms/kontakt-zugaenge-api.html">comdirect REST-API einrichten und API-Zugangsdaten beziehen ↗</a>')
        link.setOpenExternalLinks(True)
        layout.addWidget(link)
        form = QFormLayout()
        self.user, self.pin, self.client_id, self.client_secret = (QLineEdit() for _ in range(4))
        self.fields = (self.user, self.pin, self.client_id, self.client_secret)
        for field in self.fields:
            field.setMaxLength(1024)
        for field in (self.pin, self.client_secret):
            field.setEchoMode(QLineEdit.EchoMode.Password)
        for title, field in zip(('Zugangsnummer', 'Online-Banking-PIN / Passwort', 'API Client-ID', 'API Client-Secret'), self.fields):
            form.addRow(title, field)
        self.remember = QCheckBox('Zugangsdaten beim Abruf im Windows-Anmeldeinformationsspeicher sichern')
        self.remember.setEnabled(os.name == 'nt')
        form.addRow(self.remember)
        self.save_login = QPushButton('Zugangsdaten speichern')
        self.save_login.setEnabled(os.name == 'nt')
        self.delete_login = QPushButton('Gespeicherten Zugang löschen')
        self.delete_login.setEnabled(os.name == 'nt')
        self.save_login.clicked.connect(self.save_credentials)
        self.delete_login.clicked.connect(self.delete_credentials)
        form.addRow(self.save_login, self.delete_login)
        self.history = QCheckBox('Gebuchte Kontoumsätze zusätzlich abrufen')
        self.history.setChecked(True)
        from .bank_history_range import history_start_editor
        self.history_start = history_start_editor(getattr(parent, 'repository', None), 'comdirect')
        self.history_end = QDateEdit(QDate.currentDate())
        for field in (self.history_start, self.history_end):
            field.setCalendarPopup(True)
            field.setDisplayFormat('dd.MM.yyyy')
            field.setMaximumDate(QDate.currentDate())
            self.history.toggled.connect(field.setEnabled)
        form.addRow(self.history)
        form.addRow('Umsätze von', self.history_start)
        form.addRow('Umsätze bis', self.history_end)
        self.force_refresh = QCheckBox('Frisch von der Bank abrufen (5-Minuten-Zwischenspeicher umgehen)')
        form.addRow(self.force_refresh)
        layout.addLayout(form)
        note = QLabel('Der Rückblick hängt von den bei comdirect verfügbaren Buchungen ab. '
                      'PDF-Postfach und Depottransaktionen sind nicht Teil dieses Abrufs. '
                      'TAN und Sitzungstoken werden nicht gespeichert.')
        note.setWordWrap(True)
        layout.addWidget(note)
        self.status = QLabel('Bereit. Portfolio-Daten werden erst nach Bestätigung der Importvorschau übernommen.')
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        from .bank_status import add_copy_button
        self.copy_message = add_copy_button(layout, self.status)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('Abbrechen')
        self.fetch_button = QPushButton('comdirect abrufen')
        buttons.addButton(self.fetch_button, QDialogButtonBox.ButtonRole.ActionRole)
        self.fetch_button.clicked.connect(self.start_fetch)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        if os.name == 'nt':
            try:
                saved = self.store.load()
                for key, field in zip(self.store.fields, self.fields):
                    field.setText(saved.get(key, ''))
                if saved:
                    self.remember.setChecked(True)
                    self.status.setText('Gespeicherten comdirect-Zugang geladen. Bereit zum Abruf.')
            except CredentialError as error:
                self.status.setText(str(error))

    def save_credentials(self):
        try:
            self.store.save(*(field.text() for field in self.fields))
        except CredentialError as error:
            self.status.setText(str(error))
            return False
        self.remember.setChecked(True)
        self.status.setText('comdirect-Zugangsdaten im Windows-Anmeldeinformationsspeicher gesichert.')
        return True

    def delete_credentials(self):
        try:
            self.store.delete()
        except CredentialError as error:
            self.status.setText(str(error))
            return
        for field in self.fields:
            field.clear()
        from .comdirect_cache import FETCH_CACHE
        FETCH_CACHE.clear()
        self.remember.setChecked(False)
        self.status.setText('Gespeicherter comdirect-Zugang gelöscht.')

    def set_busy(self, busy):
        for field in (*self.fields, self.history, self.fetch_button, self.force_refresh):
            field.setEnabled(not busy)
        for field in (self.remember, self.save_login, self.delete_login):
            field.setEnabled(not busy and os.name == 'nt')
        for field in (self.history_start, self.history_end):
            field.setEnabled(not busy and self.history.isChecked())

    def start_fetch(self):
        if self.worker and self.worker.isRunning():
            return
        if not all(field.text().strip() for field in self.fields):
            self.status.setText('Bitte alle vier Zugangsfelder ausfüllen.')
            return
        if self.history.isChecked() and self.history_start.date() > self.history_end.date():
            self.status.setText('Der Beginn des Umsatzzeitraums muss vor oder am Enddatum liegen.')
            return
        if self.remember.isChecked() and not self.save_credentials():
            return
        self.cancel_requested = False
        self.worker = ComdirectWorker(tuple(field.text() for field in self.fields), self.source_root, self,
            history_start=self.history_start.date().toPython() if self.history.isChecked() else None,
            history_end=self.history_end.date().toPython(), refresh=self.force_refresh.isChecked())
        self.set_busy(True)
        self.worker.status.connect(self.status.setText)
        self.worker.challenge_requested.connect(self.show_challenge)
        self.worker.finished.connect(self.fetch_finished)
        owner = self.parent()
        while owner is not None and not hasattr(owner, 'job_center'):
            owner = owner.parent()
        if owner is not None:
            owner.job_center.register(self.worker, 'comdirect · Online-Abruf')
        self.worker.start()

    def show_challenge(self, auth):
        if self.cancel_requested or not self.worker.isRunning():
            self.worker.answer.set()
            return
        try:
            self.tan_dialog = TANDialog(auth, self)
            accepted = self.tan_dialog.exec() == QDialog.DialogCode.Accepted
            self.worker.tan = self.tan_dialog.tan.text() if accepted else None
            self.tan_dialog.tan.clear()
            self.tan_dialog.deleteLater()
        except BankingError as error:
            self.status.setText(str(error))
        finally:
            self.tan_dialog = None
            self.worker.answer.set()

    def fetch_finished(self):
        if self.tan_dialog:
            self.tan_dialog.reject()
        if self.cancel_requested:
            self.worker.batches = None
            super().reject()
        elif self.worker.error:
            self.status.setText(self.worker.error)
            self.set_busy(False)
            self.pin.setFocus()
        elif self.worker.batches is not None:
            self.batches = self.worker.batches
            self.accept()

    def reject(self):
        if self.worker and self.worker.isRunning():
            self.cancel_requested = True
            self.worker.requestInterruption()
            if self.tan_dialog:
                self.tan_dialog.reject()
            self.status.setText('Abruf wird abgebrochen. Eine laufende Serverantwort wird noch abgewartet …')
            return
        super().reject()
