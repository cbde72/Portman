"""Interactive fee ledger and CSV/XLSX export."""
from PySide6.QtWidgets import (QAbstractItemView, QFileDialog, QHBoxLayout, QLabel,
    QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from .fee_analysis import export_fees, fee_rows
from .widgets_v09 import table_tools


HEADERS = ('Jahr','Bank','Depot','Wertpapier','ISIN','WKN','Gebührenart','Betrag','Währung',
           'Nachweis','Kontoabgleich','Plausibilität','Kurswert','Steuern','Abrechnungsbetrag','Datum','Transaktion','Import-ID')
FIELDS = ('year','bank','depot','security','isin','wkn','fee_type','amount','currency','status','cash_match',
          'reconciliation','market_value','taxes','settlement','date','transaction_id','import_id')


class FeeAnalysisWidget(QWidget):
    def __init__(self, repository, parent=None):
        super().__init__(parent); self.repo = repository; self.rows = []
        layout = QVBoxLayout(self); bar = QHBoxLayout()
        self.summary = QLabel(); bar.addWidget(self.summary, 1)
        for label, suffix in [('CSV exportieren …', '.csv'), ('Excel exportieren …', '.xlsx')]:
            button = QPushButton(label); button.clicked.connect(lambda _=False,s=suffix:self.export(s)); bar.addWidget(button)
        layout.addLayout(bar)
        self.table = QTableWidget(0, len(HEADERS)); self.table.setHorizontalHeaderLabels(HEADERS)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setSortingEnabled(True); table_tools(self.table); layout.addWidget(self.table)
        self.refresh()

    def refresh(self):
        self.rows = fee_rows(self.repo); self.table.setSortingEnabled(False); self.table.setRowCount(len(self.rows))
        for row_index, row in enumerate(self.rows):
            for column, field in enumerate(FIELDS):
                value = row.get(field)
                self.table.setItem(row_index, column, QTableWidgetItem('–' if value is None or value == '' else str(value)))
        self.table.resizeColumnsToContents(); self.table.setSortingEnabled(True)
        known = sum(1 for row in self.rows if row['status'] != 'unbekannt')
        zero = sum(1 for row in self.rows if row['status'] == 'nachgewiesen 0,00 €')
        conflicts = sum(1 for row in self.rows if row['status'] == 'widersprüchlich')
        self.summary.setText(f'{len(self.rows)} Gebührennachweise · {known} bekannt · {zero} nachgewiesen null · {conflicts} widersprüchlich')

    def export(self, suffix):
        path, _ = QFileDialog.getSaveFileName(self, 'Gebührenauswertung exportieren',
            'gebuehrenauswertung' + suffix, 'Excel (*.xlsx)' if suffix == '.xlsx' else 'CSV (*.csv)')
        if path: export_fees(self.rows, path)
