"""Background import review and atomic multi-file commit on independent connections."""
import logging
import sqlite3
import tempfile
from pathlib import Path
from contextlib import closing
from decimal import Decimal
from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QLabel, QProgressBar, QPushButton,
    QDialogButtonBox, QTabWidget, QTableWidget, QTableWidgetItem, QWidget, QMessageBox, QCheckBox)
from .repository import PortfolioRepository
from .import_preview import ImportPreviewDialog
from .persistence import backup_database
from portfolio_v5.accounts import account_key
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


def copied_repository(path, folder):
    target = Path(folder) / 'preview.sqlite'
    with closing(sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)) as src:
        with closing(sqlite3.connect(target)) as dst:
            src.backup(dst)
    return PortfolioRepository(target)


def prepare_summaries(job, batches):
    with tempfile.TemporaryDirectory() as folder:
        repo = copied_repository(job.path, folder)
        try:
            summaries = []
            for index, batch in enumerate(batches):
                if job.isInterruptionRequested(): raise ValueError('Vorschau abgebrochen.')
                summaries.append(repo.preview_summary(batch))
                job.progress.emit(index + 1, len(batches))
            return summaries
        finally:
            repo.close()


def simulate(job, batches):
    with tempfile.TemporaryDirectory() as folder:
        repo = copied_repository(job.path, folder)
        try:
            before = {(p['depot'], p['key']): p for p in repo.holdings()}
            old_balances = {r['name']: r['balance'] for r in repo.account_overview()}
            seen = list(repo.transactions())
            records = {r['account_key']: r['name'] for r in repo.account_records()}
            overlaps, results, dated = [], [], []
            # Build index for O(1) overlap lookup instead of O(n) linear scan
            from collections import defaultdict
            seen_index = defaultdict(list)
            for old in seen:
                key = (account_key(old['account']), old['date'], old['currency'], Decimal(old['amount']))
                seen_index[key].append(old)
            for i, batch in enumerate(batches):
                if job.isInterruptionRequested(): raise ValueError('Vorschau abgebrochen.')
                dates = {s.effective_date for s in batch.snapshots}
                dated_before = {day: {(p['depot'], p['key']): p for p in repo.holdings(day)} for day in dates}
                for j, tx in enumerate(batch.transactions):
                    target = batch.account_assignments.get(account_key(tx.account), account_key(tx.account))
                    effective = records.get(target, tx.account)
                    # O(1) lookup via index instead of O(n) linear scan
                    key = (account_key(effective), tx.date, tx.currency, Decimal(tx.amount))
                    for old in seen_index.get(key, []):
                        if (not old.get('security') or not tx.security or old['security'] == tx.security):
                            if old.get('external_id') != tx.external_id or old.get('source') != batch.path:
                                overlaps.append((i, j, tx.date, effective, tx.amount, batch.path, old.get('source', '')))
                                break
                    staged = {**vars(tx), 'account': effective, 'source': batch.path}
                    seen.append(staged)
                    seen_index[key].append(staged)
                # Holdings are stored independently of the derived security
                # master. Rebuilding that master after every file made a bulk
                # preview scan the complete import history N times. Stage each
                # batch directly and rebuild the derived indexes once below.
                if batch.errors:
                    result = {'path': batch.path, 'status': 'error', 'errors': batch.errors,
                              'warnings': batch.summary()['warnings']}
                else:
                    try:
                        result = repo.store.import_batch(batch)
                    except ValueError as error:
                        result = {'status': 'error', 'errors': [str(error)]}
                    result.update(path=batch.path, warnings=batch.summary()['warnings'])
                results.append(result)
                for day in sorted(dates):
                    a = dated_before[day]
                    b = {(p['depot'], p['key']): p for p in repo.holdings(day)}
                    for key in sorted(a.keys() | b.keys()):
                        old, new = a.get(key, {}), b.get(key, {})
                        if (old.get('value'), old.get('quantity'), old.get('account')) != (new.get('value'), new.get('quantity'), new.get('account')):
                            dated.append([day, batch.path, key[0], (new or old)['name'], old.get('quantity', '0'), new.get('quantity', '0'), old.get('value', '0'), new.get('value', '0')])
                job.progress.emit(i + 1, len(batches))
            if any(result['status'] == 'imported' for result in results):
                repo.sync_security_master()
            after = {(p['depot'], p['key']): p for p in repo.holdings()}
            diffs = []
            for key in sorted(before.keys() | after.keys()):
                a, b = before.get(key, {}), after.get(key, {})
                if (a.get('quantity'), a.get('value'), a.get('account')) != (b.get('quantity'), b.get('value'), b.get('account')):
                    diffs.append([key[0], (b or a)['name'], a.get('quantity', '0'), b.get('quantity', '0'),
                                  a.get('value', '0'), b.get('value', '0'), a.get('account', ''), b.get('account', '')])
            balances = []
            for row in repo.account_overview():
                if old_balances.get(row['name']) != row['balance']:
                    balances.append([row['name'], old_balances.get(row['name']), row['balance']])
            transactions = [[b.path, t.date, t.account, t.kind, t.security, t.quantity, t.amount, t.currency]
                            for b in batches for t in b.transactions]
            return {'results': results, 'positions': diffs, 'balances': balances, 'overlaps': overlaps,
                    'dated': dated, 'transactions': transactions}
        finally:
            repo.close()


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


class ImportWizard(ImportPreviewDialog):
    def __init__(self, repo, batches, summaries, parent=None):
        super().__init__(PreviewProxy(repo, batches, summaries), batches, parent)
        from PySide6.QtWidgets import QTabWidget
        self.actual_repo = repo
        self.tabs = self.findChild(QTabWidget)
        self.tabs.setTabText(0, '1 · Dateien und Erkennung')
        self.tabs.setTabText(1, '2 · Konten zuordnen')
        self.tabs.setCurrentIndex(0)
        self.setWindowTitle('PortMan 07 · Importassistent')
        self.summary = QLabel('1 Dateien / Erkennung → 2 Kontozuordnung → 3 Änderungen prüfen → 4 Übernehmen')
        self.summary.setWordWrap(True)
        self.layout().insertWidget(0, self.summary)
        note = QLabel('Vollständiger Bestand: fehlende Positionen werden im folgenden Bestand entfernt. '
                      'Teilbestand: nicht enthaltene Positionen bleiben erhalten. Alle Dateien werden gemeinsam geprüft.')
        note.setWordWrap(True); self.layout().insertWidget(1, note)
        self.buttons = self.findChild(QDialogButtonBox)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText('Änderungen gemeinsam prüfen')
        self._selected = None
        self._token = None
        self._review = None
        self.table.itemChanged.connect(self.invalidate)
        for _, _, combo, remember in self.mapping_rows:
            combo.currentIndexChanged.connect(self.invalidate)
        self.mapping_table.itemChanged.connect(self.invalidate)
        if hasattr(self, 'pdf_bookings_table'): self.pdf_bookings_table.itemChanged.connect(self.invalidate)

    def invalidate(self, *args):
        self._selected = None
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText('Änderungen gemeinsam prüfen')

    def selected_batches(self):
        return self._selected if self._selected is not None else super().selected_batches()

    def accept(self):
        token = (self.actual_repo.db.total_changes, self.actual_repo.db.execute('PRAGMA data_version').fetchone()[0])
        if self._selected is not None and token == self._token:
            if self.review_data['overlaps'] and not self.ack.isChecked():
                QMessageBox.warning(self, 'Überschneidungen prüfen', 'Bitte mögliche Buchungsüberschneidungen prüfen und bestätigen. Dateien oder PDF-Buchungen können vorher abgewählt werden.')
                return
            QDialog.accept(self); return
        try:
            batches = super().selected_batches()
            if not batches: raise ValueError('Bitte mindestens eine Datei auswählen.')
            data = run_job(self, self.actual_repo.store.path, 'Gemeinsame Importvorschau', lambda job: simulate(job, batches))
            if any(r['status'] == 'error' for r in data['results']):
                raise ValueError('\n'.join('; '.join(r.get('errors', [])) for r in data['results'] if r['status'] == 'error'))
            self.review_data = data
            if self._review is not None:
                self.tabs.removeTab(self.tabs.indexOf(self._review)); self._review.deleteLater()
            self._review = QWidget(); layout = QVBoxLayout(self._review)
            imported = sum(r['status'] == 'imported' for r in data['results'])
            duplicates = sum(r['status'] == 'duplicate' for r in data['results'])
            label = QLabel(f'{imported} Dateien neu · {duplicates} bereits vorhanden · {len(data["overlaps"])} mögliche Buchungsüberschneidungen. '
                           'Endbestand nach allen ausgewählten Dateien; historische Änderungen bleiben im Importprotokoll nachvollziehbar.')
            label.setWordWrap(True); layout.addWidget(label)
            detail_tabs = QTabWidget(); layout.addWidget(detail_tabs)
            for title, headers, rows in (
                ('Depotänderungen', ['Depot', 'Position', 'Stück vorher', 'Stück nachher', 'Wert vorher', 'Wert nachher', 'Konto vorher', 'Konto nachher'], data['positions']),
                ('Historische Änderungen in Importreihenfolge', ['Datum', 'Datei', 'Depot', 'Position', 'Stück vorher', 'Stück nachher', 'Wert vorher', 'Wert nachher'], data['dated']),
                ('Saldenänderungen', ['Konto', 'Vorher', 'Nachher'], data['balances']),
                ('Ausgewählte Buchungen', ['Datei', 'Datum', 'Quellkonto', 'Art', 'Wertpapier', 'Stück', 'Betrag', 'Währung'], data['transactions']),
                ('Mögliche Überschneidungen', ['Datei', 'Buchung', 'Datum', 'Konto', 'Betrag', 'Neue Quelle', 'Vorhandene Quelle'], data['overlaps'])):
                panel = QWidget(); panel_layout = QVBoxLayout(panel)
                panel_layout.addWidget(QLabel(f"{len(rows)} Einträge" if rows else "Keine Änderungen / Einträge in diesem Bereich."))
                table = QTableWidget(len(rows), len(headers)); table.setHorizontalHeaderLabels(headers)
                table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
                for i, row in enumerate(rows):
                    for j, value in enumerate(row): table.setItem(i, j, QTableWidgetItem('–' if value is None else str(value)))
                table.resizeColumnsToContents(); panel_layout.addWidget(table); detail_tabs.addTab(panel, title)
            self.ack = QCheckBox('Mögliche Überschneidungen geprüft; ausgewählte Buchungen sollen übernommen werden')
            self.ack.setVisible(bool(data['overlaps'])); layout.addWidget(self.ack)
            self.tabs.addTab(self._review, '3 · Gemeinsame Wirkung')
            self.tabs.setCurrentWidget(self._review)
            self._selected, self._token = batches, token
            self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText('4 · Auswahl verbindlich übernehmen')
        except Exception as error:
            QMessageBox.warning(self, 'Import prüfen', str(error))
