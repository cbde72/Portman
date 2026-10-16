"""Background import review and atomic multi-file commit on independent connections."""
import logging
from pathlib import Path
from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QProgressBar, QPushButton
from .persistence import backup_database
from .busy_indicator import busy_operation

logger = logging.getLogger(__name__)


class DatabaseJob(QThread):
    result = Signal(object)
    failed = Signal(str)
    progress = Signal(int, int)
    phase = Signal(str)

    def __init__(self, path, function, parent=None):
        super().__init__(parent)
        self.path, self.function = str(path), function

    def run(self):
        try:
            value = self.function(self)
            self.result.emit(value)
        except Exception as error:
            logger.exception('Datenbank-Job fehlgeschlagen')
            self.failed.emit(str(error))


@busy_operation
def run_job(parent, path, title, function):
    class ProgressDialog(QDialog):
        def reject(self):
            if hasattr(self, 'cancel_callback'): self.cancel_callback()
        def closeEvent(self, event):
            event.ignore()
            self.reject()
    dialog = ProgressDialog(parent)
    dialog.setWindowTitle(title)
    layout = QVBoxLayout(dialog)
    note = QLabel(title + ' …'); layout.addWidget(note)
    progress = QProgressBar(); progress.setRange(0, 0); layout.addWidget(progress)
    job = DatabaseJob(path, function, dialog)
    job.phase.connect(note.setText)
    cancel = QPushButton('Abbrechen'); layout.addWidget(cancel)
    def cancel_job():
        job.requestInterruption(); cancel.setEnabled(False)
        note.setText('Abbruch angefordert; laufende Datei wird beendet. Ein bereits abgeschlossener Speichervorgang bleibt erhalten.')
    cancel.clicked.connect(cancel_job)
    dialog.cancel_callback = cancel_job
    result, errors = [], []
    job.result.connect(result.append)
    job.failed.connect(errors.append)
    def update(current, total):
        progress.setRange(0, total); progress.setValue(current)
        note.setText(f'{title} · {current} / {total}')
    job.progress.connect(update)
    job.finished.connect(dialog.accept)
    # Never destroy a running QThread or allow concurrent edits while committing.
    job.start(); dialog.exec(); job.wait()
    if errors:
        raise ValueError(errors[0])
    if job.isInterruptionRequested() and not result:
        raise ValueError('Vorgang abgebrochen.')
    return result[0] if result else None


def commit_atomic(job, batches, *, create_backup=True):
    # Construct and use the entire connection in this worker thread.
    from .repository_base import RepositoryV07
    repo = RepositoryV07(job.path, backups=False)
    try:
        if create_backup:
            job.phase.emit('Sicherung vor dem Import wird erstellt …')
            backup_database(repo.db, Path(job.path).parent / 'backups', 'before-import')
        repo.db.execute('BEGIN IMMEDIATE')
        # Store.import_batch uses `with db`; wrap its commits in nested savepoints
        # through a small connection proxy to preserve all-or-nothing semantics.
        original = repo.store.db
        class TransactionConnection:
            def __getattr__(self, name): return getattr(original, name)
            def __enter__(self):
                original.execute('SAVEPOINT batch'); return self
            def __exit__(self, kind, value, trace):
                if kind: original.execute('ROLLBACK TO batch')
                original.execute('RELEASE batch')
                return False
        repo.store.db = TransactionConnection()
        results = []
        try:
            for index, batch in enumerate(batches):
                if job.isInterruptionRequested(): raise ValueError('Import abgebrochen; keine Änderungen gespeichert.')
                if batch.errors: raise ValueError('; '.join(batch.errors))
                result = repo.store.import_batch(batch)
                result['path'] = batch.path
                results.append(result)
                job.progress.emit(index + 1, len(batches))
            repo.sync_security_master()
            if job.isInterruptionRequested(): raise ValueError('Import abgebrochen; keine Änderungen gespeichert.')
            original.commit()
        except Exception:
            original.rollback()
            raise
        finally:
            repo.store.db = original
        return results
    finally:
        repo.close()


class PreviewProxy:
    def __init__(self, repo, batches, summaries):
        self.repo = repo
        self.summaries = {id(b): s for b, s in zip(batches, summaries)}
    def __getattr__(self, name): return getattr(self.repo, name)
    def preview_summary(self, batch): return self.summaries[id(batch)]
