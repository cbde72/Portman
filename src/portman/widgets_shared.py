"""V07 dashboard, evidence browser, recovery and change analysis."""
from .date_display import display_dates
from pathlib import Path
from decimal import Decimal
from PySide6.QtCore import Qt, QDate, QUrl, QByteArray
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
    QPushButton, QTableWidget, QTableWidgetItem, QTabWidget, QDateEdit, QMessageBox, QFileDialog,
    QMenu)
from .dashboard_widget import DashboardWidget
from .formatting import euro
from .analysis_shared import change_analysis
from .persistence import inspect_database, restore_database


amount = euro


def populate(table, headers, rows):
    if hasattr(table,'set_rows'):
        table.model().reset(headers,rows)
        return
    table.setSortingEnabled(False)
    table.setColumnCount(len(headers)); table.setHorizontalHeaderLabels(headers)
    table.setRowCount(len(rows)); table.setAlternatingRowColors(True)
    table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    for i, row in enumerate(rows):
        for j, value in enumerate(row):
            item = QTableWidgetItem(display_dates('–' if value is None else str(value)))
            item.setToolTip(display_dates(item.text())); table.setItem(i, j, item)
    table.resizeColumnsToContents()
    for j in range(table.columnCount()): table.setColumnWidth(j, min(340, table.columnWidth(j)))


class DashboardV07(DashboardWidget):
    def __init__(self, *args, **kwargs):
        self.mode = None
        super().__init__(*args, **kwargs)
        class DocumentedView:
            documented_only = True
            def __init__(self, repository): self.repository = repository
            def __getattr__(self, name): return getattr(self.repository, name)
        self.visuals.repo = DocumentedView(self.repo)
        self.mode = QComboBox()
        self.mode.addItems(['Dokumentierter Vermögensstand', 'Aktuelle Schätzung'])
        self.wealth_box.layout().insertWidget(0, self.mode)
        self.mode.currentIndexChanged.connect(self.refresh)
        self.actions = QHBoxLayout()
        self.empty_actions = []
        for title, action in [('Datei importieren', 'import_csv'), ('Konto anlegen', 'manage_accounts')]:
            button = QPushButton(title)
            button.clicked.connect(lambda checked=False, method=action: getattr(self.window(), method)())
            self.actions.addWidget(button)
            self.empty_actions.append(button)
        self.wealth_box.layout().addLayout(self.actions)
        self.top.cellDoubleClicked.connect(self.open_position)
        self.refresh()

    def refresh(self):
        super().refresh()
        account, as_of = self.scope()
        wealth = self.repo.wealth_summary(as_of, account)
        for button in getattr(self, 'empty_actions', []): button.setVisible(wealth['value'] is None)
        dates = wealth.get('dates', [])
        stamp = ' bis '.join(dict.fromkeys([dates[0], dates[-1]])) if dates else 'kein Datenstand'
        self.wealth_box.setTitle('Vermögen · ' + (account or 'Alle Konten'))
        available = len([r for r in self.repo.account_records() if r['active'] and (account is None or r['name'] == account)])
        self.wealth_note.setText(display_dates(f"Datenstand {stamp} · Salden für {wealth['accounts']}/{available} Konten · " + ', '.join(wealth.get('sources', []))
                                + ' · Altersvorsorge enthalten, Schulden abgezogen; ohne Immobilienschätzungen'))
        self.estimate_note.setText('Dokumentierte Salden; ältere Stände werden bis zum Bewertungsstichtag fortgeführt. Keine Rendite.')
        if self.mode is not None and self.mode.currentIndex() == 1:
            from .valuation import current_wealth
            data = current_wealth(self.repo, account)
            self.cards['wealth'].setText(display_dates(amount(data['value'])))
            dates = sorted({r['date'] for r in data['rows'] if r.get('date')})
            self.wealth_note.setText(display_dates('Aktuelle Schätzung · gemischte Datenstände: ' + (' / '.join(dates) or 'keine Daten')))
            self.estimate_note.setText(display_dates(f"{len(data['rows'])} Bewertungsbestandteile · {len(data['missing_accounts'])} Konten ohne Bewertung. "
                                      'Gespeicherte Kurse und Ersatzwerte; keine Live-Bewertung. Unabhängig vom historischen Stichtag.'))
        data = self.service.overview(as_of, account)
        for key in ('cost', 'pnl', 'return'):
            box = self.cards[key].parentWidget()
            base = {'cost': 'Einstandswert', 'pnl': 'Buchgewinn / Verlust', 'return': 'Buchrendite'}[key]
            box.setTitle(f"{base} · {data['known_cost_positions']}/{len(data['positions'])} Positionen")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        grid = self.layout().itemAt(2).layout()
        if grid is not None:
            cols = 2 if self.width() < 1050 else 4
            for i, key in enumerate(('value', 'cost', 'pnl', 'return')):
                box = self.cards[key].parentWidget()
                grid.removeWidget(box); grid.addWidget(box, i // cols, i % cols)

    def open_position(self, row, column):
        positions = sorted(self.service.overview(self.scope()[1], self.scope()[0])['positions'],
                           key=lambda p: Decimal(p['value'] or 0), reverse=True)[:8]
        if row < len(positions):
            EvidenceDialog(self.repo, positions[row]['key'], self.scope(), self).exec()


class EvidenceDialog(QDialog):
    def __init__(self, repo, key=None, scope=(None, '9999-12-31'), parent=None):
        super().__init__(parent); self.repo = repo
        self.setWindowTitle('Belege und Datenherkunft'); self.resize(1050, 650)
        layout = QVBoxLayout(self)
        note = QLabel('Doppelklick öffnet eine vorhandene lokale Quelldatei. Online-Importe werden über das Bankarchiv nachvollzogen.')
        note.setWordWrap(True); layout.addWidget(note)
        self.tabs = QTabWidget(); layout.addWidget(self.tabs)
        account, day = scope
        holdings = [p for p in repo.holdings(day, account) if key is None or p['key'] == key]
        txs = [t for t in repo.transactions(account) if t['date'] <= day and (key is None or t.get('security') == key)]
        table = QTableWidget(); self.tabs.addTab(table, 'Bestandsbelege')
        populate(table, ['Depot', 'Position', 'Stand', 'Wert', 'Einstand', 'Belegter Teileinstand', 'Stück ohne Einstand', 'Quelle'],
                 [[p['depot'], p['name'], p['as_of'] or p['period'], p['value'], p.get('cost'),
                   p.get('known_partial_cost'), p.get('unknown_cost_quantity'), p['source']] for p in holdings])
        table.cellDoubleClicked.connect(lambda row, col: self.open_source(holdings[row]['source']))
        table = QTableWidget(); self.tabs.addTab(table, 'Buchungsbelege')
        from .baader_holdings import purchase_value
        populate(table, ['Datum', 'Konto', 'Art', 'Stück', 'Kaufwert laut Baader-Abrechnung', 'Abrechnungsbetrag', 'Gebühren', 'Steuern', 'Währung', 'Quelle'],
                 [[t['date'], t['account'], t['kind'], t.get('quantity'),
                   purchase_value(t) if t['external_id'].startswith('baader-trade-') and t['kind'] == 'BUY' else None,
                   t['amount'], t.get('fees'), t.get('taxes'), t['currency'], t['source']] for t in txs])
        table.cellDoubleClicked.connect(lambda row, col: self.open_source(txs[row]['source']))
        balances = repo.wealth_summary(day, account).get('rows', [])
        if key is None:
            table = QTableWidget(); self.tabs.addTab(table, 'Saldenbelege')
            populate(table, ['Konto', 'Kategorie', 'Stand', 'Wert', 'Quelle'],
                     [[b['account'], b['category'], b.get('effective_date'), b['value'], b.get('source', '')] for b in balances])
            table.cellDoubleClicked.connect(lambda row, col: self.open_source(balances[row].get('source', '')))
        from .bank_archive import BankArchiveWidget
        self.tabs.addTab(BankArchiveWidget(repo, lambda: account, self), 'Bankarchiv · Originaldokumente')

    def open_source(self, path):
        if path and Path(path).is_file():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(path).resolve())))
        else:
            QMessageBox.information(self, 'Quelle', 'Die Quelldatei ist nicht lokal verfügbar. Originaldokumente aus Bankabrufen finden Sie im Bankarchiv.\n' + str(path))


class AnalysisDialog(QDialog):
    def __init__(self, repo, account=None, parent=None):
        super().__init__(parent); self.repo, self.account = repo, account
        self.setWindowTitle('Veränderungen und Bestandsabstimmung'); self.resize(1150, 780)
        layout = QVBoxLayout(self); bar = QHBoxLayout()
        self.start = QDateEdit(QDate.currentDate().addYears(-1)); self.end = QDateEdit(QDate.currentDate())
        for editor in (self.start, self.end): editor.setCalendarPopup(True); editor.setDisplayFormat('dd.MM.yyyy')
        go = QPushButton('Vergleichen'); go.clicked.connect(self.refresh)
        for widget in (QLabel(display_dates(account or 'Alle Konten')), self.start, self.end, go): bar.addWidget(widget)
        layout.addLayout(bar); self.note = QLabel(); self.note.setWordWrap(True); layout.addWidget(self.note)
        self.tabs = QTabWidget(); layout.addWidget(self.tabs)
        self.tables = []
        for title in ('Konten', 'Anlageklassen', 'Positionen / Kursanteil', 'Stückzahlabstimmung', 'Zahlungsströme'):
            table = QTableWidget(); self.tabs.addTab(table, title); self.tables.append(table)
        self.tables[2].cellDoubleClicked.connect(self.evidence)
        self.tables[3].cellDoubleClicked.connect(self.evidence)
        self.refresh()

    def refresh(self):
        try:
            self.data = change_analysis(self.repo, self.start.date().toString('yyyy-MM-dd'), self.end.date().toString('yyyy-MM-dd'), self.account)
        except ValueError as error:
            self.note.setText(display_dates(str(error))); return
        d = self.data
        self.note.setText(display_dates(f"Dokumentierte Vermögensänderung: {amount(d['change'])} · Nicht eindeutig erklärt: {amount(d['residual'])}. "
                          f"{d['unclassified']} unklassifizierte Kontobuchungen, {d['unknown']} nicht vollständig auswertbare Buchungen. "
                          'Käufe/Verkäufe sind interne Umschichtungen. Kursanteile beziehen sich auf die Anfangsstückzahl; '
                          'Korrekturen, Währungen, Kapitalmaßnahmen und fehlende Zahlungsströme bleiben im Restbetrag. Keine Rendite.'))
        populate(self.tables[0], ['Konto', 'Vorher', 'Nachher', 'Änderung'],
                 [[r['account'], amount(r['before']), amount(r['after']), amount(r['change'])] for r in d['accounts']])
        populate(self.tables[1], ['Anlageklasse', 'Vorher', 'Nachher', 'Änderung'],
                 [[r['category'], amount(r['before']), amount(r['after']), amount(r['after'] - r['before'])] for r in d['categories']])
        populate(self.tables[2], ['Depot', 'Position', 'Vorher', 'Nachher', 'Änderung', 'Rechnerischer Kursanteil'],
                 [[r['depot'], r['name'], amount(r['before']), amount(r['after']), amount(r['change']), amount(r['price_effect'])] for r in d['positions']])
        populate(self.tables[3], ['Depot', 'Position', 'Anfang', 'Gebuchte Bewegung', 'Ende', 'Differenz', 'Nachweisstatus'],
                 [[r['depot'], r['name'], r['opening_units'], r['booked_units'], r['closing_units'], r['difference'], r['status']] for r in d['positions']])
        labels = {'DEPOSIT': 'Einzahlungen', 'WITHDRAWAL': 'Entnahmen', 'DIVIDEND': 'Ausschüttungen', 'INTEREST': 'Zinsen', 'FEE': 'Gebühren', 'TAX': 'Steuern'}
        populate(self.tables[4], ['Klassifizierte Zahlungsströme (EUR)', 'Betrag'],
                 [[labels[k], amount(v)] for k, v in d['explained'].items()] + [['Nicht eindeutig erklärt', amount(d['residual'])]])

    def evidence(self, row, column):
        EvidenceDialog(self.repo, self.data['positions'][row]['key'],
                       (self.account, self.end.date().toString('yyyy-MM-dd')), self).exec()


class RecoveryDialog(QDialog):
    def __init__(self, repo, parent=None):
        super().__init__(parent); self.repo = repo; self.restored = False
        self.setWindowTitle('Datensicherung und Wiederherstellung'); self.resize(1000, 650)
        layout = QVBoxLayout(self)
        label = QLabel(display_dates(f'Datenordner: {repo.store.path.parent}\nVor jeder Wiederherstellung wird der aktuelle Stand gesichert. 12 automatische Sicherungen werden aufbewahrt.'))
        label.setWordWrap(True); label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse); layout.addWidget(label)
        self.table = QTableWidget(); layout.addWidget(self.table)
        bar = QHBoxLayout()
        for text, action in [('Jetzt sichern', self.backup), ('Sicherung prüfen / wiederherstellen', self.restore), ('Externe Sicherung wählen', self.external)]:
            button = QPushButton(text); button.clicked.connect(action); bar.addWidget(button)
        layout.addLayout(bar); self.refresh()

    def refresh(self):
        self.paths = sorted(self.repo.backup_folder.glob('portman-*.sqlite'), reverse=True)
        rows = []
        for path in self.paths:
            try: info = inspect_database(path); status = 'OK'; summary = ', '.join(f'{k}: {v}' for k, v in info.items())
            except Exception as error: status = 'Fehler'; summary = str(error)
            rows.append([path.name, status, summary])
        populate(self.table, ['Sicherung (UTC)', 'Integrität', 'Datenumfang'], rows)

    def backup(self):
        try: self.repo.backup(); self.refresh()
        except Exception as error: QMessageBox.warning(self, 'Sicherung fehlgeschlagen', str(error))

    def external(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Sicherung wählen', str(self.repo.backup_folder), 'SQLite (*.sqlite)')
        if path: self.restore_path(Path(path))

    def restore(self):
        if self.table.currentRow() >= 0: self.restore_path(self.paths[self.table.currentRow()])

    def restore_path(self, path):
        try:
            info = inspect_database(path)
            if QMessageBox.question(self, 'Datenstand wiederherstellen', f'{path.name}\n{info}\nDiesen Datenstand wiederherstellen?') != QMessageBox.StandardButton.Yes: return
            # Preserve the selected backup even when rotation removes the oldest file.
            import tempfile, shutil
            with tempfile.TemporaryDirectory() as folder:
                copy = Path(folder) / 'selected.sqlite'; shutil.copy2(path, copy)
                restore_database(self.repo.db, copy, self.repo.backup_folder, source_label=path.name)
            self.repo.store._read_revision = None
            self.restored = True; self.accept()
        except Exception as error: QMessageBox.warning(self, 'Wiederherstellung fehlgeschlagen', str(error))


class TablePreferences:
    def __init__(self, window):
        self.window = window
        self.tables = {}
        saved = window.settings.get('table_preferences', {})
        from .positions_model import PositionTable
        tables = window.findChildren(QTableWidget) + window.findChildren(PositionTable)
        for index, table in enumerate(tables):
            headers = '|'.join(table.horizontalHeaderItem(c).text() if table.horizontalHeaderItem(c) else str(c) for c in range(table.columnCount()))
            key = f'{index}:{headers}'
            self.tables[key] = table
            table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            table.customContextMenuRequested.connect(lambda point, t=table: self.menu(t, point))
            table.horizontalHeader().setSectionsMovable(True)
            if key in saved:
                table.horizontalHeader().restoreState(QByteArray.fromHex(saved[key].encode('ascii')))

    def menu(self, table, point):
        menu = QMenu(table)
        for i in range(table.columnCount()):
            item = table.horizontalHeaderItem(i)
            action = menu.addAction(item.text() if item else str(i)); action.setCheckable(True)
            action.setChecked(not table.isColumnHidden(i))
            action.toggled.connect(lambda checked, c=i: table.setColumnHidden(c, not checked))
        menu.exec(table.viewport().mapToGlobal(point))

    def save(self):
        self.window.settings['table_preferences'] = {key: table.horizontalHeader().saveState().toHex().data().decode('ascii')
                                                    for key, table in self.tables.items()}
