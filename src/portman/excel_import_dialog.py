"""Excel assistant with sheet selection and original/parsed previews."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QCheckBox, QTabWidget, QTableWidget, QDialogButtonBox
from portfolio_v5.importers import read_sheets
from .excel_import import parse_excel_file, sheet_kind
from .widgets_shared import populate
from .jobs_v09 import run_job


class ExcelImportDialog(QDialog):
    def __init__(self, repo, path, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Excel-Assistent · Blätter und Unterdepots')
        self.resize(1150, 800)
        self.sheets = run_job(self, repo.store.path, 'Excel-Blätter lesen', lambda job: read_sheets(path))
        self.parsed = run_job(self, repo.store.path, 'Excel interpretieren', lambda job: parse_excel_file(path, self.sheets))
        self.batches = []
        layout = QVBoxLayout(self)
        note = QLabel('Blätter auswählen und Originalwerte prüfen. Deka-Unterdepots werden getrennt zugeordnet. '
            'Bestände enthalten Anfangs- und Endstände; Zusammenfassungen werden nicht zusätzlich gezählt. '
            'Ausschüttungen mit Anteilen werden als Ausschüttung und Wiederanlage erfasst. '
            'Danach folgen Kontenzuordnung und Importprüfung.')
        note.setWordWrap(True)
        layout.addWidget(note)
        self.choices = {}
        for batch in self.parsed:
            choice = QCheckBox(f'{batch.source_sheet} · {len(batch.snapshots)} Bestände · {len(batch.transactions)} Buchungen')
            choice.setChecked(not batch.errors)
            choice.setEnabled(not batch.errors)
            self.choices[batch.source_sheet] = choice
            layout.addWidget(choice)
        bar = QHBoxLayout()
        self.sheet = QComboBox()
        self.sheet.addItems(list(self.sheets))
        bar.addWidget(QLabel('Tabellenblatt'))
        bar.addWidget(self.sheet)
        layout.addLayout(bar)
        tabs = QTabWidget()
        self.original, self.preview = QTableWidget(), QTableWidget()
        tabs.addTab(self.original, 'Originalwerte')
        tabs.addTab(self.preview, 'Interpretation')
        layout.addWidget(tabs)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.status)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText('Weiter · Unterdepots zuordnen')
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.sheet.currentTextChanged.connect(self.show_sheet)
        self.show_sheet(self.sheet.currentText())

    def show_sheet(self, name):
        rows = self.sheets.get(name, [])
        populate(self.original, [str(v or '') for v in rows[0]] if rows else [], rows[1:])
        batch = next((b for b in self.parsed if b.source_sheet == name), None)
        interpreted = []
        if batch:
            for snapshot in batch.snapshots:
                for position in snapshot.positions:
                    interpreted.append([position.row, snapshot.account, snapshot.as_of, 'Bestand', position.isin, position.quantity, position.value])
            for t in batch.transactions:
                interpreted.append([t.row, t.account, t.date, t.kind, t.security, t.quantity, t.amount])
        populate(self.preview, ['Excel-Zeile', 'Unterdepot', 'Datum', 'Art', 'ISIN', 'Anteile', 'EUR'], interpreted)
        self.status.setText('\n'.join(batch.errors + batch.warnings) if batch and (batch.errors or batch.warnings) else sheet_kind(rows))

    def accept(self):
        self.batches = [b for b in self.parsed if self.choices[b.source_sheet].isChecked() and not b.errors]
        if not self.batches:
            self.status.setText('Bitte mindestens ein fehlerfreies Tabellenblatt auswählen.')
            return
        super().accept()
