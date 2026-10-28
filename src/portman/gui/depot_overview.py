"""Interactive depot activity overview and exports."""

import csv
from decimal import Decimal
from pathlib import Path

from PySide6.QtCore import Qt, QDate, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDateEdit, QDialog,
    QDialogButtonBox, QFileDialog, QHBoxLayout, QLabel, QListWidget,
    QListWidgetItem, QMessageBox, QPushButton, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget)

from portman.depot_overview import aggregate_depot, depots
from portman.table_copy import copy_table


COLUMNS = (
    ('name', 'Wertpapiername', False), ('identifier', 'ISIN / WKN', False),
    ('quantity_end', 'Stückzahl Ende', False), ('buy_count', 'Käufe Anzahl', False),
    ('buy_total', 'Käufe Gesamtbetrag', False), ('sell_count', 'Verkäufe Anzahl', False),
    ('sell_total', 'Verkäufe Gesamtbetrag', False), ('dividend_gross', 'Dividenden brutto', False),
    ('dividend_net', 'Dividenden netto', False), ('buy_fees', 'Gebühren Kauf', True),
    ('sell_fees', 'Gebühren Verkauf', True), ('other_fees', 'Sonstige Gebühren', True),
    ('fees_total', 'Gebühren gesamt', False), ('capital_gains_tax', 'Kapitalertragsteuer', True),
    ('solidarity_tax', 'Solidaritätszuschlag', True), ('church_tax', 'Kirchensteuer', True),
    ('withholding_tax', 'Quellensteuer', True), ('tax_total', 'Steuern gesamt', False),
    ('realized_profit', 'Realisierte Gewinne / Verluste', False),
    ('net_cashflow', 'Netto-Cashflow', False),
)
MONEY_KEYS = {key for key, _label, _advanced in COLUMNS} - {
    'name', 'identifier', 'quantity_end', 'buy_count', 'sell_count'}


def display(value, key):
    if value is None:
        return '–'
    if isinstance(value, Decimal):
        digits = 6 if key == 'quantity_end' else 2
        return f'{value:.{digits}f}'.replace('.', ',')
    return str(value)


class PositionActivityDialog(QDialog):
    def __init__(self, row, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Vorgänge · ' + row['name'])
        self.resize(1100, 650)
        layout = QVBoxLayout(self)
        self.filter = QComboBox()
        self.filter.addItems(['Alle', 'Käufe', 'Verkäufe', 'Dividenden', 'Gebühren', 'Steuern'])
        layout.addWidget(self.filter)
        self.table = QTableWidget()
        self.table.setColumnCount(11)
        self.table.setHorizontalHeaderLabels([
            'Datum / Valuta', 'Art', 'Stückzahl', 'Kurs', 'Kurswert', 'Gebühren',
            'Steuern', 'Netto-Cashflow', 'Bank / Konto', 'Originalbeleg', 'Kennung'])
        self.table.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
        layout.addWidget(self.table)
        self.transactions = list(row['transactions'])
        self.filter.currentIndexChanged.connect(self.refresh)
        self.table.cellDoubleClicked.connect(self.open_source)
        self.refresh()

    def refresh(self):
        selected = self.filter.currentText()
        kinds = {'Käufe': {'BUY'}, 'Verkäufe': {'SELL'}, 'Dividenden': {'DIVIDEND', 'DISTRIBUTION'},
                 'Gebühren': {'FEE'}, 'Steuern': {'TAX', 'TAX_NOTICE', 'ADVANCE_TAX'}}
        rows = [tx for tx in self.transactions if selected == 'Alle' or tx.get('kind') in kinds[selected]
                or (selected == 'Gebühren' and Decimal(str(tx.get('fees') or 0)) != 0)
                or (selected == 'Steuern' and Decimal(str(tx.get('taxes') or 0)) != 0)]
        self.table.setRowCount(len(rows))
        self._visible = rows
        for r, tx in enumerate(rows):
            gross = tx.get('gross_amount') or ''
            values = [tx.get('value_date') or tx.get('date', ''), tx.get('kind', ''),
                tx.get('quantity', ''), tx.get('price', ''), gross,
                tx.get('fees', ''), tx.get('taxes', ''), tx.get('amount', ''),
                tx.get('account', ''), tx.get('source', ''), tx.get('external_id', '')]
            for c, value in enumerate(values):
                self.table.setItem(r, c, QTableWidgetItem(str(value or '')))
        self.table.resizeColumnsToContents()

    def open_source(self, row, _column):
        path = Path(self._visible[row].get('source') or '')
        if path.is_file():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.resolve())))


class DepotOverviewWidget(QWidget):
    def __init__(self, repository, parent=None):
        super().__init__(parent)
        self.repository, self.rows = repository, []
        layout = QVBoxLayout(self)
        controls = QHBoxLayout()
        self.depot = QComboBox(); self.depot.addItem('Alle Depots', None)
        for name in depots(repository): self.depot.addItem(name, name)
        self.start = QDateEdit(); self.end = QDateEdit(); self.start.setCalendarPopup(True); self.end.setCalendarPopup(True)
        self.end.setDate(QDate.currentDate()); self.start.setDate(QDate.currentDate().addYears(-1))
        self.preset = QComboBox(); self.preset.addItems(['Aktuelles Jahr', 'Letztes Jahr', '3 Jahre', 'Gesamt', 'Benutzerdefiniert'])
        self.positions = QComboBox(); self.positions.addItems(['Alle Positionen', 'Aktive Positionen', 'Geschlossene Positionen'])
        refresh = QPushButton('Aktualisieren'); export = QPushButton('Exportieren')
        columns = QPushButton('Spalten …')
        for label, widget in [('Depot', self.depot), ('Von', self.start), ('Bis', self.end), ('Zeitraum', self.preset), ('Positionen', self.positions)]:
            controls.addWidget(QLabel(label)); controls.addWidget(widget)
        controls.addWidget(refresh); controls.addWidget(columns); controls.addWidget(export)
        layout.addLayout(controls)
        self.note = QLabel('Käufe sind negativ, Verkäufe und Dividenden positiv. Netto-Cashflow verwendet den gebuchten Settlementbetrag; Gebühren und Steuern werden nicht doppelt abgezogen.')
        self.note.setWordWrap(True); layout.addWidget(self.note)
        self.table = QTableWidget(); self.table.setColumnCount(len(COLUMNS)); self.table.setHorizontalHeaderLabels([label for _key, label, _advanced in COLUMNS])
        self.table.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectItems)
        self.table.setSortingEnabled(True); layout.addWidget(self.table)
        self.show_all_export = QCheckBox('Export enthält auch ausgeblendete Spalten'); self.show_all_export.setChecked(True)
        layout.addWidget(self.show_all_export)
        for index, (_key, _label, advanced) in enumerate(COLUMNS): self.table.setColumnHidden(index, advanced)
        self.timer = QTimer(self); self.timer.setSingleShot(True); self.timer.setInterval(80); self.timer.timeout.connect(self.refresh)
        self.depot.currentIndexChanged.connect(self.schedule_refresh)
        self.start.dateChanged.connect(self.custom_range); self.end.dateChanged.connect(self.custom_range)
        self.positions.currentIndexChanged.connect(self.populate)
        self.preset.currentTextChanged.connect(self.apply_preset)
        refresh.clicked.connect(self.refresh); export.clicked.connect(self.export); columns.clicked.connect(self.choose_columns)
        self.table.cellDoubleClicked.connect(self.open_details)
        self.apply_preset('Aktuelles Jahr')
        # The tab starts hidden. Avoid touching the repository asynchronously
        # after a short-lived window test already closed its database.
        self.timer.stop()

    def closeEvent(self, event):
        self.timer.stop()
        super().closeEvent(event)

    def schedule_refresh(self, *_args): self.timer.start()

    def custom_range(self, *_args):
        if not self.start.hasFocus() and not self.end.hasFocus(): return
        self.preset.blockSignals(True); self.preset.setCurrentText('Benutzerdefiniert'); self.preset.blockSignals(False)
        self.schedule_refresh()

    def apply_preset(self, value):
        today = QDate.currentDate()
        if value == 'Aktuelles Jahr': start, end = QDate(today.year(), 1, 1), today
        elif value == 'Letztes Jahr': start, end = QDate(today.year() - 1, 1, 1), QDate(today.year() - 1, 12, 31)
        elif value == '3 Jahre': start, end = today.addYears(-3), today
        elif value == 'Gesamt': start, end = QDate(1900, 1, 1), today
        else: return
        for editor, day in ((self.start, start), (self.end, end)):
            editor.blockSignals(True); editor.setDate(day); editor.blockSignals(False)
        self.schedule_refresh()

    def refresh(self):
        start, end = self.start.date().toString('yyyy-MM-dd'), self.end.date().toString('yyyy-MM-dd')
        if start > end:
            self.note.setText('Der Beginn muss vor dem Ende liegen.'); return
        self.rows = aggregate_depot(self.repository, self.depot.currentData(), start, end)
        self.populate()

    def filtered_rows(self):
        mode = self.positions.currentText()
        return [row for row in self.rows if mode == 'Alle Positionen'
                or (mode == 'Aktive Positionen' and row['active'])
                or (mode == 'Geschlossene Positionen' and not row['active'])]

    def populate(self, *_args):
        rows = self.filtered_rows()
        self.table.setSortingEnabled(False); self.table.setRowCount(len(rows) + (1 if rows else 0))
        for r, row in enumerate(rows):
            for c, (key, _label, _advanced) in enumerate(COLUMNS):
                value = row[key]
                item = QTableWidgetItem(display(value, key))
                item.setData(Qt.ItemDataRole.UserRole, row['key'])
                if isinstance(value, (Decimal, int)): item.setData(Qt.ItemDataRole.UserRole + 1, value)
                self.table.setItem(r, c, item)
        if rows:
            r = len(rows)
            for c, (key, _label, _advanced) in enumerate(COLUMNS):
                value = 'Summe' if key == 'name' else '' if key == 'identifier' else sum((row[key] for row in rows), Decimal()) if key in MONEY_KEYS or key == 'quantity_end' else sum(row[key] for row in rows) if key in ('buy_count', 'sell_count') else ''
                item = QTableWidgetItem(display(value, key)); item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable); self.table.setItem(r, c, item)
        self.table.setSortingEnabled(True); self.table.resizeColumnsToContents()
        self.note.setText(f'{len(rows)} Positionen · Zeitraum {self.start.date().toString("dd.MM.yyyy")} bis {self.end.date().toString("dd.MM.yyyy")} · Settlement-Cashflows ohne doppelten Gebühren-/Steuerabzug.')

    def open_details(self, row, _column):
        rows = self.filtered_rows()
        if row < len(rows): PositionActivityDialog(rows[row], self).exec()

    def choose_columns(self):
        dialog = QDialog(self); dialog.setWindowTitle('Spalten auswählen'); layout = QVBoxLayout(dialog); choices = QListWidget(); layout.addWidget(choices)
        for index, (_key, label, _advanced) in enumerate(COLUMNS):
            item = QListWidgetItem(label); item.setData(Qt.ItemDataRole.UserRole, index); item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable); item.setCheckState(Qt.CheckState.Unchecked if self.table.isColumnHidden(index) else Qt.CheckState.Checked); choices.addItem(item)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel); buttons.accepted.connect(dialog.accept); buttons.rejected.connect(dialog.reject); layout.addWidget(buttons)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            for row in range(choices.count()):
                item = choices.item(row); self.table.setColumnHidden(item.data(Qt.ItemDataRole.UserRole), item.checkState() != Qt.CheckState.Checked)

    def export(self):
        path, selected = QFileDialog.getSaveFileName(self, 'Depotübersicht exportieren', 'depotuebersicht.csv', 'CSV (*.csv);;Excel (*.xlsx)')
        if not path: return
        columns = list(range(len(COLUMNS))) if self.show_all_export.isChecked() else [c for c in range(len(COLUMNS)) if not self.table.isColumnHidden(c)]
        headers = [COLUMNS[c][1] for c in columns]; rows = [[display(row[COLUMNS[c][0]], COLUMNS[c][0]) for c in columns] for row in self.filtered_rows()]
        if path.casefold().endswith('.xlsx') or 'Excel' in selected:
            from openpyxl import Workbook
            book = Workbook(); sheet = book.active; sheet.title = 'Depotübersicht'; sheet.append(headers)
            for row in rows: sheet.append(row)
            book.save(path)
        else:
            with open(path, 'w', encoding='utf-8-sig', newline='') as stream: csv.writer(stream, delimiter=';').writerows([headers, *rows])
        QMessageBox.information(self, 'Export', f'Depotübersicht gespeichert:\n{path}')

    def copy_all(self): copy_table(self.table)
