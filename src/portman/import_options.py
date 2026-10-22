"""Choose how to handle previously imported sources before the preview."""
from copy import deepcopy
import json

from PySide6.QtWidgets import QCheckBox, QDialog, QDialogButtonBox, QLabel, QVBoxLayout


def enrich_security_bookings(repository, batches):
    """Apply evidenced security assignments before the import preview is shown."""
    from dataclasses import asdict
    from portfolio_v5.settlement import infer_security_booking
    for batch in batches:
        for transaction in batch.transactions:
            inferred = infer_security_booking(repository.store, asdict(transaction))
            if not inferred:
                continue
            for field, value in inferred.items():
                if hasattr(transaction, field):
                    setattr(transaction, field, value)
    return batches


class ImportOptionsDialog(QDialog):
    def __init__(self, repository, batches, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Importoptionen')
        self.setMinimumWidth(480)
        self.batches = list(batches)
        existing = {}
        for record in repository.imports():
            if not record['active']:
                continue
            report = json.loads(record['report'])
            if report.get('source_sha256'):
                existing.setdefault((report['source_sha256'], report.get('source_sheet', '')), []).append(report)
        self.duplicates = [any(report.get('snapshots', 0) == len(batch.snapshots)
                              and (report.get('transactions', 0) == len(batch.transactions)
                                   or (batch.plugin_id == 'user.comdirect-ertraege'
                                       and batch.plugin_handler in ('wertpapierkauf', 'wertpapierverkauf')
                                       and report.get('booking_evidence', 0) == len(batch.transactions)))
                              and report.get('balances', 0) == len(batch.balances)
                              and (not batch.history_end or (
                                  report.get('history_end') == batch.history_end
                                  and report.get('path') == batch.path))
                              for report in existing.get((batch.file_hash, batch.source_sheet), []))
                           for batch in self.batches]
        layout = QVBoxLayout(self)
        note = QLabel(f'{len(self.batches)} Importquellen · {sum(self.duplicates)} bereits vorhanden.\n'
                      'Wähle vor der Vorschau, ob vorhandene Importe erneut eingelesen werden sollen.')
        note.setWordWrap(True)
        layout.addWidget(note)
        self.repeat = QCheckBox('Vorhandene Importe erneut importieren')
        layout.addWidget(self.repeat)
        hint = QLabel('Ohne Haken werden identische, bereits aktive Importquellen übersprungen. '
                      'Mit Haken werden sie erneut zur Prüfung angeboten. Gespeichert wird erst nach '
                      'Bestätigung im anschließenden Importdialog.')
        hint.setWordWrap(True)
        layout.addWidget(hint)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText('Weiter zur Importvorschau')
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def selected_batches(self):
        selected = []
        for original, duplicate in zip(self.batches, self.duplicates):
            if duplicate and not self.repeat.isChecked() and not original.errors:
                continue
            batch = deepcopy(original)
            if duplicate and self.repeat.isChecked():
                batch.force_import = True
            selected.append(batch)
        return selected


def choose_import_options(parent, repository, batches):
    dialog = ImportOptionsDialog(repository, batches, parent)
    if not any(dialog.duplicates) or (batches and all(b.source_sheet.startswith('Online ') for b in batches)):
        selected = dialog.selected_batches()
        dialog.deleteLater()
        if not selected and batches:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.information(parent, 'Synchronisierung', 'Alle Konten sind bereits auf dem aktuellen Stand.')
        return enrich_security_bookings(repository, selected)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return []
    selected = dialog.selected_batches()
    if not selected:
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.information(parent, 'Import', 'Alle ausgewählten Importquellen sind bereits vorhanden und wurden übersprungen.')
    return enrich_security_bookings(repository, selected)
