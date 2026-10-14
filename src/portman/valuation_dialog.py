from .date_display import display_dates
from decimal import Decimal
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QTabWidget, QInputDialog, QMessageBox)
from .valuation import current_wealth
from .formatting import euro as amount


class ValuationDialog(QDialog):
    def __init__(self, repo, account=None, parent=None):
        super().__init__(parent); self.repo, self.account = repo, account
        self.setWindowTitle('Vermögensbewertung und Daten bereinigen'); self.resize(1200, 760)
        layout = QVBoxLayout(self); self.summary = QLabel(); self.summary.setWordWrap(True); layout.addWidget(self.summary)
        self.tabs = QTabWidget(); layout.addWidget(self.tabs)
        self.tables = []
        for title, headers in [
            ('Zusammensetzung', ['Konto', 'Kategorie', 'Excel EUR', 'Angesetzt EUR', 'Quelle', 'Stand', 'Hinweis']),
            ('Bewertete Positionen', ['Depot', 'Wertpapier', 'Stückzahl', 'Bestandsdatum', 'Kurswährung', 'Wert EUR', 'Kursstand', 'Quelle / Hinweis']),
            ('Bestände bereinigen', ['Depot', 'Wertpapier', 'Stückzahl', 'Bestandsdatum', 'Gesamteinstand', 'Quelle'])]:
            table = QTableWidget(0, len(headers)); table.setHorizontalHeaderLabels(headers)
            table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers); table.setAlternatingRowColors(True)
            table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
            table.horizontalHeader().setStretchLastSection(True); self.tabs.addTab(table, title); self.tables.append(table)
        bar = QHBoxLayout()
        for title, callback in [('Einstand zum gewählten Bestand ergänzen', self.correct_cost),
                                ('Neu berechnen', self.refresh), ('Schließen', self.accept)]:
            button = QPushButton(title); button.clicked.connect(callback); bar.addWidget(button)
        layout.addLayout(bar); self.refresh()

    def refresh(self):
        data = current_wealth(self.repo, self.account)
        self.summary.setText(display_dates(f"Vermögensschätzung: {amount(data['value'])} · Excel-Ausgangswert {amount(data['baseline'])} ({data['period'] or 'kein Stand'})\n"
            f"EZB-Referenzkurse: {data['fx_date'] or 'nicht vorhanden'} · Gemischte Datenstände, kein Live-Bankvermögen. "
            'Wertpapier-Kontosalden werden ersetzt, nicht zusätzlich addiert. '
            + ('Ohne Bewertung: ' + ', '.join(data['missing_accounts']) if data['missing_accounts'] else '')
            + '\nFür neue Stückzahlen/Depotstände den Dateiimport verwenden. Einstand nur anhand eines Belegs ergänzen; der Kurs ist kein Einstand.'))
        self.holdings = self.repo.holdings(account=self.account)
        rows = [
            [[r['account'], r['category'], amount(r['original']), amount(r['value']), r['source'], r['date'], r['note']] for r in data['rows']],
            [[p['depot'], p['name'], p['quantity'], p['as_of'], p['quote_currency'], amount(p['estimated_value']), p['valuation_date'],
              p['valuation_source'] + ' · ' + p['valuation_note']] for p in data['positions']],
            [[p['depot'], p['name'], p['quantity'], p['as_of'] or p['period'], amount(Decimal(p['cost'])) if p.get('cost') else 'Fehlt',
              p.get('cost_source', p['source'])] for p in self.holdings]]
        for table, content in zip(self.tables, rows):
            table.setRowCount(len(content))
            for i, row in enumerate(content):
                for j, value in enumerate(row):
                    item = QTableWidgetItem(display_dates(str(value or '–'))); item.setToolTip(display_dates(str(value or '–'))); table.setItem(i, j, item)
            table.resizeColumnsToContents()
            for col in range(table.columnCount()): table.setColumnWidth(col, min(300, table.columnWidth(col)))

    def correct_cost(self):
        table = self.tables[2]; self.tabs.setCurrentIndex(2); row = table.currentRow()
        if row < 0:
            QMessageBox.information(self, 'Bestand auswählen', 'Zuerst eine Position in „Bestände bereinigen“ auswählen.'); return
        p = self.holdings[row]
        value, ok = QInputDialog.getText(self, 'Einstand ergänzen', f"{p['depot']} · {p['name']}\nGesamteinstand für diese Stückzahl in EUR (kein Stückpreis):")
        if not ok: return
        source, ok = QInputDialog.getText(self, 'Belegquelle', 'Belegname und Belegdatum:')
        if not ok: return
        try:
            from portfolio_v5.models import number
            self.repo.correct_cost(p['snapshot_id'], p['key'], number(value), source)
        except (ValueError, ArithmeticError) as exc:
            QMessageBox.warning(self, 'Ungültige Eingabe', str(exc)); return
        self.refresh()
