from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QComboBox, QFileDialog, QTableWidget, QTableWidgetItem, QAbstractItemView)
from .crypto_wallet_import import MODES, read_wallet_csv


class CryptoWalletPanel(QWidget):
    def __init__(self, changed, parent=None):
        super().__init__(parent)
        self.batch, self.path, self.error = None, '', ''
        self.changed = changed
        layout = QVBoxLayout(self)
        hint = QLabel('CSV mit vollständiger Kaufhistorie importieren. Beträge werden in EUR übernommen. '
            'Endbetrag ergibt den Einstandswert; Verkäufe reduzieren ihn nach FIFO. '
            'Die Zeitleiste bleibt im Depot erhalten: Für jeden Handelstag wird der Tagesendbestand gespeichert '
            'und ist über die Datumsauswahl abrufbar. '
            'Es entstehen keine Kontobelastungen. Marktwerte bleiben bis zur Kursbewertung offen.')
        hint.setWordWrap(True); layout.addWidget(hint)
        actions = QHBoxLayout(); layout.addLayout(actions)
        choose = QPushButton('CSV-Datei auswählen …'); choose.clicked.connect(self.choose)
        clear = QPushButton('Auswahl entfernen'); clear.clicked.connect(self.clear)
        actions.addWidget(choose); actions.addWidget(clear)
        self.mode = QComboBox()
        for title, value in MODES.items(): self.mode.addItem(title, value)
        self.mode.currentIndexChanged.connect(self.reload)
        layout.addWidget(self.mode)
        self.status = QLabel('Optional: CSV auswählen oder ein leeres Wallet anlegen.')
        self.status.setWordWrap(True); layout.addWidget(self.status)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(['Kryptowert', 'Stückzahl', 'Einstandswert (EUR)'])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        layout.addWidget(self.table)

    def choose(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Wallet-CSV auswählen', '', 'CSV-Dateien (*.csv);;Alle Dateien (*)')
        if path:
            self.path = path
            self.reload()

    def clear(self):
        self.path = ''
        self.reload()

    def reload(self, *args):
        self.batch, self.error = None, ''
        self.table.setRowCount(0)
        if self.path:
            try:
                from .import_jobs import run_job
                path, mode = self.path, self.mode.currentData()
                self.status.setText('Krypto-CSV wird eingelesen …')
                self.batch = run_job(self, path, 'Krypto-CSV einlesen',
                    lambda job: read_wallet_csv(path, 'Wallet-Vorschau', mode, job.isInterruptionRequested))
            except (ValueError, OSError, UnicodeError) as error:
                self.error = str(error)
                self.status.setText('Import nicht möglich: ' + self.error)
            else:
                positions = self.batch.snapshots[-1].positions
                self.status.setText(f'{self.path}\n{len(self.batch.transactions)} Buchungen · '
                    f'{len(positions)} Positionen · Stand {self.batch.snapshots[-1].as_of}\n'
                    f'Zeitleiste: {len(self.batch.snapshots)} Tagesstände von '
                    f'{self.batch.snapshots[0].as_of} bis {self.batch.snapshots[-1].as_of}.\n'
                    'Übernahme erst beim Speichern des Kontos.')
                self.table.setRowCount(len(positions))
                for i, position in enumerate(positions):
                    for j, value in enumerate((position.name, position.quantity, position.cost)):
                        self.table.setItem(i, j, QTableWidgetItem(value))
                self.table.resizeColumnsToContents()
        else:
            self.status.setText('Optional: CSV auswählen oder ein leeres Wallet anlegen.')
        self.changed()
