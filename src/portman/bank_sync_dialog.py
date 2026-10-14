"""Sequential refresh of all configured bank connections."""
from datetime import date
from .bank_history_range import last_history_date

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QProgressBar, QTextEdit, QVBoxLayout

from .ing_credentials import INGCredentialStore, CredentialError
from .comdirect_credentials import ComdirectCredentialStore
from .ing_dialog import INGWorker
from .comdirect_dialog import ComdirectWorker, TANDialog, BankingError
from .baader_credentials import BaaderCredentialStore
from .baader_dialog import BaaderWorker, BaaderTANDialog
from .renault_credentials import RenaultCredentialStore
from .renault_dialog import RenaultWorker, RenaultTANDialog


class BankSyncDialog(QDialog):
    status_message = Signal(str)

    def __init__(self, source_root, parent=None, *, auto_continue=False):
        super().__init__(parent)
        self.source_root = source_root
        self.auto_continue = auto_continue
        self.has_errors = False
        self.repository = getattr(parent, 'repository', None)
        self.pending = [('ING', INGCredentialStore), ('comdirect', ComdirectCredentialStore),
                        ('Baader', BaaderCredentialStore), ('Renault Bank direkt', RenaultCredentialStore)]
        self.results = []
        self.worker = self.tan_dialog = None
        self.cancel_requested = False
        self.bank = ''
        self.setWindowTitle('Alle Online-Konten synchronisieren')
        self.setMinimumWidth(580)
        layout = QVBoxLayout(self)
        note = QLabel('Deine gespeicherten Bankzugänge werden aktualisiert. Neue Umsätze werden seit dem letzten '
                      'erfolgreich übernommenen Abruf geladen. Vorhandene Kontoverknüpfungen werden automatisch übernommen.')
        note.setWordWrap(True)
        layout.addWidget(note)
        self.status = QLabel('Synchronisation wird vorbereitet …')
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.progress = QProgressBar()
        self.progress.setRange(0, len(self.pending))
        layout.addWidget(self.progress)
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        layout.addWidget(self.log)
        from .bank_status import add_copy_button
        self.copy_message = add_copy_button(layout, self.status,
            text_provider=lambda: self.status.text() + '\n\n' + self.log.toPlainText())
        self.copy_message.setText('Alle Meldungen kopieren')
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText('Weiter zur Importvorschau')
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('Abbrechen')
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        QTimer.singleShot(0, self.start_next)

    def record(self, message):
        self.log.insertPlainText(message + '\n')
        self.status_message.emit(message)

    def set_status(self, message):
        self.status.setText(message)
        self.status_message.emit(message)

    def start_next(self):
        if self.cancel_requested:
            return
        if not self.pending:
            self.set_status('Abruf abgeschlossen.' if self.results else
                            'Keine Daten abgerufen. Fehlende Zugänge unter „Online-Anbindung“ einrichten.')
            self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(bool(self.results))
            self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('Schließen')
            if self.auto_continue:
                self.accept()
            return
        self.bank, store_type = self.pending.pop(0)
        try:
            store = store_type(self.source_root)
            saved = store.load()
            if not saved or not all(saved.get(key) for key in store.fields):
                self.record(f'{self.bank}: Übersprungen – kein vollständiger gespeicherter Zugang.')
                self.advance()
                return
        except CredentialError as error:
            self.has_errors = True
            self.record(f'{self.bank}: {error}')
            self.advance()
            return
        options = dict(history_start=last_history_date(self.repository, self.bank), history_end=date.today())
        credentials = tuple(saved[key] for key in store.fields)
        if self.bank == 'ING':
            self.worker = INGWorker(*credentials, self.source_root, self, fetch_documents=True, **options)
        elif self.bank == 'Baader':
            self.worker = BaaderWorker(*credentials, self.source_root, self, **options)
            self.worker.challenge_requested.connect(self.show_challenge)
        elif self.bank == 'Renault Bank direkt':
            self.worker = RenaultWorker(*credentials, self.source_root, self, **options)
            self.worker.challenge_requested.connect(self.show_challenge)
        else:
            self.worker = ComdirectWorker(credentials, self.source_root, self, **options)
            self.worker.challenge_requested.connect(self.show_challenge)
        self.set_status(f'{self.bank}: Verbindung wird hergestellt …')
        self.worker.status.connect(self.set_status)
        self.worker.finished.connect(self.fetch_finished)
        owner = self.parent()
        while owner is not None and not hasattr(owner, 'job_center'):
            owner = owner.parent()
        if owner is not None:
            owner.job_center.register(self.worker, f'{self.bank} · Online-Abruf')
        self.worker.start()

    def advance(self):
        self.progress.setValue(self.progress.maximum() - len(self.pending))
        QTimer.singleShot(0, self.start_next)

    def show_challenge(self, auth):
        if self.cancel_requested or not self.worker.isRunning():
            self.worker.answer.set()
            return
        try:
            dialog_type = {'Baader': BaaderTANDialog, 'Renault Bank direkt': RenaultTANDialog}.get(self.bank, TANDialog)
            self.tan_dialog = dialog_type(auth, self)
            accepted = self.tan_dialog.exec() == QDialog.DialogCode.Accepted
            self.worker.tan = self.tan_dialog.tan.text() if accepted else None
            self.tan_dialog.tan.clear()
            self.tan_dialog.deleteLater()
        except BankingError as error:
            self.record(f'{self.bank}: {error}')
        finally:
            self.tan_dialog = None
            self.worker.answer.set()

    def fetch_finished(self):
        if self.tan_dialog:
            self.tan_dialog.reject()
        if self.cancel_requested:
            self.worker.batches = None
            self.results.clear()
            super().reject()
            return
        if self.worker.error:
            self.has_errors = True
            self.record(f'{self.bank}: {self.worker.error}')
        elif self.worker.batches:
            self.has_errors |= any(getattr(batch, 'errors', []) for batch in self.worker.batches)
            self.results.append((self.bank, self.worker.batches))
            self.record(f'{self.bank}: Abruf beendet – {len(self.worker.batches)} Datenpakete zur Prüfung.')
            for batch in self.worker.batches:
                for error in getattr(batch, 'errors', []):
                    self.record(f'{self.bank}: {error}')
        else:
            self.record(f'{self.bank}: Keine Daten erhalten.')
        self.worker.deleteLater()
        self.worker = None
        self.advance()

    def accept(self):
        if not self.pending and self.worker is None and (self.results or self.auto_continue) and not self.cancel_requested:
            super().accept()

    def reject(self):
        self.cancel_requested = True
        self.pending.clear()
        self.results.clear()
        if self.worker and self.worker.isRunning():
            self.worker.requestInterruption()
            if self.tan_dialog:
                self.tan_dialog.reject()
            self.set_status('Synchronisation wird abgebrochen. Die laufende Serverantwort wird abgewartet …')
            return
        super().reject()

    def closeEvent(self, event):
        self.reject()
        if self.worker and self.worker.isRunning():
            event.ignore()
        else:
            event.accept()
