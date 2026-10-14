"""Local bank archive; unclassified cash bookings and original PDF documents."""
from .date_display import display_dates
import hashlib
from decimal import Decimal
from pathlib import Path
import re

from PySide6.QtCore import QDate, Signal
from PySide6.QtWidgets import (QAbstractItemView, QDateEdit, QFileDialog, QHBoxLayout,
    QInputDialog, QLabel, QLineEdit, QMessageBox, QPushButton, QTabWidget, QCheckBox,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget, QPlainTextEdit)


def export_documents(repository, document_ids, directory):
    root = Path(directory).resolve(strict=True)
    if not root.is_dir():
        raise ValueError('Bitte einen vorhandenen Zielordner wählen.')
    available = {r['id']: r for r in repository.bank_documents()}
    paths = []
    for document_id in document_ids:
        if document_id not in available:
            raise ValueError('Ein Dokument ist nicht mehr aktiv. Ansicht aktualisieren.')
        row = available[document_id]
        title = re.sub(r'[^\w.-]+', '-', row['title'], flags=re.UNICODE).strip('.-')[:70] or 'Dokument'
        target = root / f'{title}-{row["content_hash"][:12]}.pdf'
        if target.resolve().parent != root:
            raise ValueError('Ungültiger Dokumentpfad.')
        data = repository.bank_document_content(document_id)
        if hashlib.sha256(data).hexdigest() != row['content_hash']:
            raise ValueError('Die Prüfsumme eines Dokuments stimmt nicht überein.')
        if target.exists():
            if target.read_bytes() != data:
                raise ValueError('Eine gleichnamige Datei mit anderem Inhalt existiert bereits. Bitte anderen Ordner wählen.')
        else:
            with target.open('xb') as output:
                output.write(data)
        paths.append(target)
    return paths


class BankArchiveWidget(QWidget):
    changed = Signal()

    def __init__(self, repository, account_getter, parent=None):
        super().__init__(parent)
        self.repo = repository
        self.account_getter = account_getter
        layout = QVBoxLayout(self)
        note = QLabel('Kontobuchungen sind noch keine klassifizierten Wertpapiertransaktionen. '
                      'Der gespeicherte Zeitraum kann Lücken enthalten. PDF-Dokumente werden als Originale archiviert.')
        note.setWordWrap(True)
        layout.addWidget(note)
        bar = QHBoxLayout()
        self.start = QDateEdit(QDate(1900, 1, 1))
        self.end = QDateEdit(QDate.currentDate())
        for editor in (self.start, self.end):
            editor.setCalendarPopup(True)
            editor.setDisplayFormat('dd.MM.yyyy')
            editor.dateChanged.connect(self.refresh)
        self.search = QLineEdit()
        self.search.setPlaceholderText('Alle Buchungen durchsuchen: Konto, Datum, Betrag, Verwendungszweck …')
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.refresh)
        self.all_accounts = QCheckBox('Alle Konten')
        self.all_accounts.setChecked(True)
        self.all_dates = QCheckBox('Gesamter Zeitraum')
        self.all_dates.setChecked(True)
        self.all_accounts.toggled.connect(self.refresh)
        self.all_dates.toggled.connect(self.refresh)
        bar.addWidget(self.all_accounts)
        bar.addWidget(self.all_dates)
        for widget in (QLabel('Von'), self.start, QLabel('Bis'), self.end, self.search):
            bar.addWidget(widget)
        layout.addLayout(bar)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)
        self.bookings = self.table(['Buchungstag', 'Valuta', 'Konto', 'Betrag', 'Währung', 'Auftraggeber/Empfänger', 'Verwendungszweck',
                                    'Vorgang', 'Referenz', 'Buchungstext', 'IBAN', 'BIC', 'Vollständiger Originaltext'])
        self.tabs.addTab(self.bookings, 'Kontoumsätze')
        copy = QPushButton('Gesamte Tabelle kopieren')
        from .table_copy import copy_table
        copy.clicked.connect(lambda: copy_table(self.bookings if self.tabs.currentIndex() == 0 else self.documents))
        layout.addWidget(copy)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setMaximumHeight(210)
        layout.addWidget(self.details)
        self.bookings.currentCellChanged.connect(self.show_booking)
        page = QWidget()
        documents_layout = QVBoxLayout(page)
        buttons = QHBoxLayout()
        add = QPushButton('PDFs aus Post-Box hinzufügen …')
        add.clicked.connect(self.add_documents)
        save = QPushButton('Ausgewählte PDFs speichern …')
        save.clicked.connect(self.save_documents)
        buttons.addWidget(add)
        buttons.addWidget(save)
        buttons.addStretch()
        documents_layout.addLayout(buttons)
        self.documents = self.table(['ID', 'Datum', 'Konto', 'Dokument', 'Größe (KB)'])
        documents_layout.addWidget(self.documents)
        self.tabs.addTab(page, 'Dokumente')
        self.status = QLabel()
        layout.addWidget(self.status)
        self.refresh()

    def show_booking(self, row, column, previous_row, previous_column):
        self.details.setPlainText('\n\n'.join(
            f'{self.bookings.horizontalHeaderItem(c).text()}:\n{self.bookings.item(row,c).text()}'
            for c in range(self.bookings.columnCount()) if row >= 0 and self.bookings.item(row,c)))

    @staticmethod
    def table(headers):
        widget = QTableWidget(0, len(headers))
        widget.setHorizontalHeaderLabels(headers)
        widget.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        widget.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        widget.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        widget.setAlternatingRowColors(True)
        widget.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        widget.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        return widget

    @staticmethod
    def fill(widget, rows):
        widget.setSortingEnabled(False)
        widget.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, value in enumerate(row):
                item = QTableWidgetItem(display_dates(str(value)))
                item.setToolTip(display_dates(str(value)))
                widget.setItem(r, c, item)
        widget.resizeColumnsToContents()
        widget.setSortingEnabled(True)

    def refresh(self, *args):
        from portfolio_v5.booking_details import full_booking_text
        if getattr(self.repo,'defer_initial_views',False): return
        start, end = self.start.date().toString('yyyy-MM-dd'), self.end.date().toString('yyyy-MM-dd')
        self.start.setEnabled(not self.all_dates.isChecked())
        self.end.setEnabled(not self.all_dates.isChecked())
        if self.all_dates.isChecked():
            start, end = '', '9999-12-31'
        account = None if self.all_accounts.isChecked() else self.account_getter()
        query = self.search.text().casefold().strip()
        transactions = [t for t in self.repo.transactions(account) if t['kind'] == 'BANK_BOOKING'
                        and start <= t['date'] <= end]
        transactions = [t for t in transactions if not query or query in ' '.join(
            str(t.get(k, '')) for k in ('account', 'date', 'amount', 'currency', 'purpose', 'counterparty', 'bank_reference',
                                      'counterparty_iban', 'counterparty_bic', 'operation', 'booking_text', 'raw_text')).casefold()
            or query in str(t['amount']).replace('.', ',') or query in full_booking_text(t).casefold()]
        self.fill(self.bookings, [[t['date'], t.get('value_date', ''), t['account'], format(Decimal(t['amount']), '.2f').replace('.', ','),
            t['currency'], t.get('counterparty', ''), t.get('purpose', ''),
            *[t.get(k, '') for k in ('operation','bank_reference','booking_text','counterparty_iban','counterparty_bic')],full_booking_text(t)] for t in transactions])
        self.details.clear()
        for column in (6,9,12): self.bookings.setColumnWidth(column, 260)
        documents = [d for d in self.repo.bank_documents(account)
                     if (not d['date'] or start <= d['date'] <= end)
                     and (not query or query in (d['title'] + ' ' + d['account']).casefold())]
        self.fill(self.documents, [[d['id'], d['date'] or 'Unbekannt', d['account'], d['title'],
                                   (d['size'] + 1023) // 1024] for d in documents])
        self.status.setText(display_dates(f'{len(transactions)} Kontobuchungen · {len(documents)} Dokumente in der aktuellen Auswahl. '
                            'Dokumente ohne Datum bleiben im Zeitraumfilter sichtbar.'))

    def add_documents(self):
        from .ing_history import local_document_batch
        from .ing_banking import BankingError
        from .import_preview import ImportPreviewDialog
        from portfolio_v5.models import ImportBatch
        accounts = [r['name'] for r in self.repo.account_records() if r['active']]
        if not accounts:
            QMessageBox.information(self, 'Konto anlegen', 'Bitte zuerst ein Konto für die Dokumente anlegen.')
            return
        paths, _ = QFileDialog.getOpenFileNames(self, 'ING-Unterlagen auswählen', '', 'PDF-Dokumente (*.pdf)')
        if not paths:
            return
        account, accepted = QInputDialog.getItem(self, 'Dokumente zuordnen', 'Konto', accounts,
            max(0, accounts.index(self.account_getter()) if self.account_getter() in accounts else 0), False)
        if not accepted:
            return
        host = self.parentWidget()
        while host is not None and not hasattr(host, 'guided_import'):
            host = host.parentWidget()
        if host is not None:
            from .import_jobs import run_job
            def parse(job):
                batches = []
                for index, path in enumerate(paths):
                    if job.isInterruptionRequested(): raise ValueError('Dokumentimport abgebrochen.')
                    try: batches.append(local_document_batch(path, account))
                    except (OSError, BankingError):
                        batches.append(ImportBatch(path, '', errors=['Datei konnte nicht als vollständiges PDF eingelesen werden.']))
                    job.progress.emit(index + 1, len(paths))
                return batches
            try:
                batches = run_job(self, self.repo.store.path, 'Dokumente einlesen', parse)
                host.preview_parsed_import(batches)
                self.refresh(); self.changed.emit()
            except Exception as error:
                QMessageBox.warning(self, 'Dokumentimport', str(error))
            return
        batches = []
        for path in paths:
            try:
                batches.append(local_document_batch(path, account))
            except (OSError, BankingError):
                batches.append(ImportBatch(path, '', errors=['Datei konnte nicht als vollständiges PDF eingelesen werden.']))
        preview = ImportPreviewDialog(self.repo, batches, self)
        if preview.exec() != 1:
            return
        results = self.repo.commit_batches(preview.selected_batches())
        self.refresh()
        self.changed.emit()
        errors = [r for r in results if r['status'] == 'error']
        if errors:
            QMessageBox.warning(self, 'Dokumentimport', '\n'.join('; '.join(r['errors']) for r in errors))

    def save_documents(self):
        ids = [int(self.documents.item(index.row(), 0).text()) for index in self.documents.selectionModel().selectedRows()]
        if not ids:
            QMessageBox.information(self, 'Dokumente auswählen', 'Bitte Dokumente markieren (Strg+A für alle angezeigten Dokumente).')
            return
        directory = QFileDialog.getExistingDirectory(self, 'PDF-Zielordner auswählen')
        if not directory:
            return
        try:
            paths = export_documents(self.repo, ids, directory)
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, 'PDF-Export', str(error))
            return
        self.status.setText(display_dates(f'{len(paths)} PDF-Dateien im gewählten Ordner gespeichert oder bereits identisch vorhanden.'))
