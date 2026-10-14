from .date_display import display_dates
import json
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QLabel, QTabWidget, QTableWidget,
    QTableWidgetItem, QDialogButtonBox, QMessageBox)

class ImportCorrectionDialog(QDialog):
    def __init__(self, repo, iid, parent=None):
        super().__init__(parent)
        self.repo, self.iid = repo, iid
        self.setWindowTitle(f'Import {iid} korrigieren'); self.resize(1050, 650)
        root = QVBoxLayout(self)
        note = QLabel('Zellen per Doppelklick bearbeiten. Speichern erstellt eine neue Importversion und nimmt die vorherige zurück. Zahlen ohne Tausendertrennzeichen: 1234,56 · Datum: TT.MM.JJJJ · Monat: JJJJ-MM')
        note.setWordWrap(True); root.addWidget(note)
        tabs = QTabWidget(); root.addWidget(tabs); self.tables = {}
        for table, title, fields, labels in [
            ('balances', 'Kontensalden', ['account','period','category','value'], ['Konto','Monat','Kategorie','Saldo']),
            ('snapshots', 'Depotstände', ['account','as_of'], ['Depot','Datum']),
            ('transactions', 'Transaktionen', ['account','date','amount','external_id'], ['Depot','Datum','Betrag','Buchungs-ID'])]:
            records = [dict(r) for r in repo.db.execute(f'SELECT * FROM {table} WHERE import_id=?', (iid,))]
            widget = QTableWidget(len(records), len(fields)); widget.setHorizontalHeaderLabels(labels); widget.setAlternatingRowColors(True)
            for i, row in enumerate(records):
                payload = json.loads(row['payload']) if 'payload' in row else row
                for j, field in enumerate(fields):
                    value = str(payload.get(field) or '')
                    if field in ('date', 'as_of'): value = display_dates(value)
                    if field in ('value', 'amount'): value = value.replace('.', ',')
                    widget.setItem(i, j, QTableWidgetItem(value))
            widget.resizeColumnsToContents(); tabs.addTab(widget, title)
            self.tables[table] = (widget, records, fields)
        self.positions = QTableWidget(0, 5); self.positions.setHorizontalHeaderLabels(['Depot / Wertpapier','Stück','Wert','Einstand','Name'])
        self.position_rows = []
        from PySide6.QtCore import Qt
        for record in self.tables['snapshots'][1]:
            for index, pos in enumerate(json.loads(record['payload'])['positions']):
                row = self.positions.rowCount(); self.positions.insertRow(row)
                for col, value in enumerate([record['account']+' / '+pos['key'],pos.get('quantity'),pos.get('value'),pos.get('cost'),pos['name']]):
                    display = '' if value is None else str(value)
                    if col in (1, 2, 3): display = display.replace('.', ',')
                    item = QTableWidgetItem(display)
                    if col == 0: item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    self.positions.setItem(row,col,item)
                self.position_rows.append((record['id'],index))
        self.positions.resizeColumnsToContents(); tabs.addTab(self.positions, 'Wertpapierpositionen')
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.save); buttons.rejected.connect(self.reject); root.addWidget(buttons)

    def save(self):
        edits = {}
        for table, (widget, records, fields) in self.tables.items():
            edits[table] = {r['id']: {field: widget.item(i,j).text().strip() for j,field in enumerate(fields)} for i,r in enumerate(records)}
        from portfolio_v5.models import parse_date
        for table in ('snapshots', 'transactions'):
            field = 'as_of' if table == 'snapshots' else 'date'
            for values in edits[table].values():
                if values[field]:
                    values[field] = parse_date(values[field]) or values[field]
        for record in self.tables['snapshots'][1]:
            edits['snapshots'][record['id']]['positions'] = json.loads(record['payload'])['positions']
        for row, (sid,index) in enumerate(self.position_rows):
            pos = edits['snapshots'][sid]['positions'][index]
            for col, field in enumerate(['quantity','value','cost','name'],1): pos[field] = self.positions.item(row,col).text().strip()
        try: self.repo.correct_import(self.iid, edits)
        except (ValueError, KeyError) as exc:
            QMessageBox.warning(self, 'Korrektur prüfen', str(exc)); return
        self.accept()
