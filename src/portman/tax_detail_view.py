"""Auditable, lossless view of institution tax-detail exports."""
import csv
from pathlib import Path

from PySide6.QtCore import Qt, QSortFilterProxyModel
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QDialog, QFileDialog,
    QFormLayout, QHBoxLayout, QLabel, QLineEdit, QMenu, QMessageBox, QPushButton,
    QScrollArea, QTableView, QVBoxLayout, QWidget)

from portfolio_v5.comdirect_tax_detail import COLUMNS, GROUPS


GROUP_BY_COLUMN = {column: group for group, columns in GROUPS.items() for column in columns}


class TaxDetailProxy(QSortFilterProxyModel):
    def __init__(self, owner):
        super().__init__(owner); self.owner = owner

    def filterAcceptsRow(self, row, parent):
        record = self.sourceModel().item(row, 0).data(Qt.ItemDataRole.UserRole)
        values = record['original_values']
        selections = ((self.owner.institution, record.get('institution', '')),
                      (self.owner.account, record.get('account', '')),
                      (self.owner.year, values.get('Steuerjahr', '')),
                      (self.owner.kind, values.get('Vorgang', '')))
        if any(box.currentData() and box.currentData() != value for box, value in selections):
            return False
        needle = self.owner.search.text().strip().casefold()
        return not needle or needle in ' '.join(values.values()).casefold()


class TaxDetailDialog(QDialog):
    def __init__(self, repository, parent=None):
        super().__init__(parent); self.repository = repository
        self.setWindowTitle('Steuerliche Detailansicht'); self.resize(1500, 820)
        layout = QVBoxLayout(self); filters = QHBoxLayout()
        self.institution, self.account, self.year, self.kind = (QComboBox() for _ in range(4))
        for label, box in (('Institut', self.institution), ('Konto / Depot', self.account),
                           ('Steuerjahr', self.year), ('Vorgangsart', self.kind)):
            filters.addWidget(QLabel(label)); filters.addWidget(box)
        self.search = QLineEdit(); self.search.setClearButtonEnabled(True)
        self.search.setPlaceholderText('Suchen …'); filters.addWidget(self.search, 1)
        layout.addLayout(filters)
        self.records = repository.tax_detail_records()
        for box, values in ((self.institution, sorted({r['institution'] for r in self.records})),
                            (self.account, sorted({r['account'] for r in self.records})),
                            (self.year, sorted({r['tax_year'] for r in self.records}, reverse=True)),
                            (self.kind, sorted({r['original_values']['Vorgang'] for r in self.records}))):
            box.addItem('Alle', '')
            for value in values: box.addItem(value, value)
        self.model = QStandardItemModel(self)
        self.model.setHorizontalHeaderLabels([f'{GROUP_BY_COLUMN[c]}\n{c}' for c in COLUMNS])
        for record in self.records:
            items = []
            for index, column in enumerate(COLUMNS):
                item = QStandardItem(record['original_values'].get(column, ''))
                if index == 0: item.setData(record, Qt.ItemDataRole.UserRole)
                items.append(item)
            self.model.appendRow(items)
        self.proxy = TaxDetailProxy(self); self.proxy.setSourceModel(self.model)
        self.proxy.setSortCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.table = QTableView(); self.table.setModel(self.proxy); self.table.setSortingEnabled(True)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(True); self.table.doubleClicked.connect(self.open_detail)
        self.table.horizontalHeader().setSectionsMovable(True)
        layout.addWidget(self.table, 1)
        actions = QHBoxLayout(); self.count = QLabel(); actions.addWidget(self.count); actions.addStretch(1)
        columns = QPushButton('Spalten auswählen'); columns.clicked.connect(self.choose_columns); actions.addWidget(columns)
        export_csv = QPushButton('CSV exportieren'); export_csv.clicked.connect(self.export_csv); actions.addWidget(export_csv)
        export_xlsx = QPushButton('Excel exportieren'); export_xlsx.clicked.connect(self.export_xlsx); actions.addWidget(export_xlsx)
        layout.addLayout(actions)
        for box in (self.institution, self.account, self.year, self.kind): box.currentIndexChanged.connect(self.refilter)
        self.search.textChanged.connect(self.refilter); self.refilter()

    def refilter(self):
        self.proxy.invalidateFilter(); self.count.setText(f'{self.proxy.rowCount()} Vorgänge')

    def choose_columns(self):
        menu = QMenu(self)
        for group, columns in GROUPS.items():
            submenu = menu.addMenu(group)
            for column in columns:
                index = COLUMNS.index(column); action = submenu.addAction(column)
                action.setCheckable(True); action.setChecked(not self.table.isColumnHidden(index))
                action.toggled.connect(lambda checked, i=index: self.table.setColumnHidden(i, not checked))
        menu.exec(self.mapToGlobal(self.rect().center()))

    def visible_rows(self):
        columns = [i for i in range(len(COLUMNS)) if not self.table.isColumnHidden(i)]
        rows = [[self.proxy.index(r, c).data() or '' for c in columns] for r in range(self.proxy.rowCount())]
        return columns, rows

    def export_csv(self):
        path, _ = QFileDialog.getSaveFileName(self, 'Steuerdetails exportieren', 'steuerdetails.csv', 'CSV (*.csv)')
        if not path: return
        columns, rows = self.visible_rows()
        with open(path, 'w', encoding='utf-8-sig', newline='') as stream:
            writer = csv.writer(stream, delimiter=';'); writer.writerow([COLUMNS[i] for i in columns]); writer.writerows(rows)

    def export_xlsx(self):
        path, _ = QFileDialog.getSaveFileName(self, 'Steuerdetails exportieren', 'steuerdetails.xlsx', 'Excel (*.xlsx)')
        if not path: return
        try:
            from openpyxl import Workbook
            book = Workbook(); sheet = book.active; sheet.title = 'Steuerdetails'
            columns, rows = self.visible_rows(); sheet.append([COLUMNS[i] for i in columns])
            for row in rows: sheet.append(row)
            sheet.freeze_panes = 'A2'; sheet.auto_filter.ref = sheet.dimensions; book.save(path)
        except Exception as error:
            QMessageBox.warning(self, 'Excel-Export', str(error))

    def open_detail(self, index):
        source = self.proxy.mapToSource(index).row()
        record = self.model.item(source, 0).data(Qt.ItemDataRole.UserRole)
        dialog = QDialog(self); dialog.setWindowTitle('Steuerlicher Einzelvorgang'); dialog.resize(760, 760)
        outer = QVBoxLayout(dialog); scroll = QScrollArea(); scroll.setWidgetResizable(True)
        content = QWidget(); form = QFormLayout(content)
        for column in COLUMNS: form.addRow(column, QLabel(record['original_values'].get(column, '')))
        form.addRow('Belegdatum (verknüpftes PDF)', QLabel(record.get('document_date') or 'nicht im CSV enthalten'))
        form.addRow('Ertragsjahr (verknüpftes PDF)', QLabel(record.get('income_year') or 'nicht im CSV enthalten'))
        form.addRow('Originalbeleg / Quelle', QLabel(record.get('source', '')))
        form.addRow('Stabile Buchungsidentität', QLabel(record.get('external_id', '')))
        form.addRow('PDF-Steuermitteilung', QLabel(record.get('linked_tax_event_id') or 'nicht eindeutig verknüpft'))
        form.addRow('Zugehörige Geldbuchung', QLabel(record.get('linked_transaction_id') or 'keine / nicht eindeutig'))
        form.addRow('Zuordnungsstatus', QLabel(record.get('match_status', 'unmatched')))
        scroll.setWidget(content); outer.addWidget(scroll); dialog.exec()
