from .date_display import display_dates
import json
from decimal import Decimal
from PySide6.QtCore import QDate, Qt, Signal
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
                              QComboBox, QTreeWidget, QTreeWidgetItem, QMessageBox, QCheckBox, QTreeWidgetItemIterator, QInputDialog)


from .formatting import euro
from .institutions import account_institution


class AccountsWidget(QWidget):
    changed = Signal()
    manage_requested = Signal()
    account_selected = Signal(str)

    def __init__(self, repository, date_getter, parent=None):
        super().__init__(parent)
        self.repo = repository
        self.date_getter = date_getter
        root = QVBoxLayout(self)
        bar = QHBoxLayout()
        self.summary = QLabel()
        bar.addWidget(self.summary)
        bar.addStretch()
        self.show_extra = QCheckBox('Weitere Spalten')
        self.show_extra.toggled.connect(self.toggle_columns)
        bar.addWidget(self.show_extra)
        self.rename_institute = QPushButton('Institut umbenennen …')
        self.rename_institute.setEnabled(False)
        self.rename_institute.clicked.connect(self.rename_institution)
        bar.addWidget(self.rename_institute)
        taxes = QPushButton('Steuern & Freistellung …')
        taxes.clicked.connect(self.show_tax_overview)
        bar.addWidget(taxes)
        manage = QPushButton('Konten verwalten …')
        manage.clicked.connect(self.manage_requested.emit)
        bar.addWidget(manage)
        root.addLayout(bar)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(['Institut / Konto oder Depot', 'Depotwert', 'Saldo zum Stichtag',
            'Depotstand', 'Saldo-Datum', 'Details', 'Gesamt inkl. Unterkonten', 'Datenstand',
            'Zinsen / Dividenden', 'Kapitalerträge', 'Steuern', 'Solidaritätszuschlag',
            'Freistellungsauftrag', 'Teilfreistellung',
            'Freistellung verbraucht', 'Freistellung verbleibend',
            'Performance (1J)', 'Performance (3J)', 'Max. Drawdown', 'Volatilität'])
        self.tree.setAlternatingRowColors(True)
        self.tree.header().setDefaultAlignment(Qt.AlignmentFlag.AlignCenter)
        self.tree.setStyleSheet('QTreeWidget::item { border-right: 1px solid palette(midlight); '
                                'border-bottom: 1px solid palette(midlight); padding: 2px; } '
                                'QTreeWidget::item:selected { background: palette(highlight); '
                                'color: palette(highlighted-text); }')
        self.tree.headerItem().setTextAlignment(0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.tree.header().setStretchLastSection(False)
        self.tree.header().setSectionsMovable(True)
        self.tree.header().moveSection(self.tree.header().visualIndex(6), 1)
        self.tree.header().moveSection(self.tree.header().visualIndex(7), 2)
        for col, width in [(0, 280), (6, 230), (7, 170), (1, 160), (2, 160), (3, 140), (4, 140), (5, 280)]:
            self.tree.setColumnWidth(col, width)
        for col in range(8, 16):
            self.tree.setColumnWidth(col, 145)
        for col in range(16, 20):
            self.tree.setColumnWidth(col, 130)
        for col in (8, 11, 12, 13, 14, 15):
            self.tree.setColumnHidden(col, True)
        self.toggle_columns(False)
        self.tree.itemDoubleClicked.connect(self.select_account)
        self.tree.itemSelectionChanged.connect(self.update_institution_action)
        root.addWidget(self.tree)
        hint = QLabel('Institut auswählen und über „Institut umbenennen“ den Namen für alle zugehörigen Konten ändern. '
                      'Gesamt summiert die zugehörigen Konten. Berechnete Umsatzsalden werden zum Depotwert addiert. Reine Depotbewertungen werden nur einmal gezählt. '
                      'Die Übersicht berücksichtigt das gewählte Datum. Doppelklick auf ein Konto öffnet alle Buchungen in einem neuen Fenster.')
        hint.setWordWrap(True)
        root.addWidget(hint)
        bar = QHBoxLayout()
        self.depot = QComboBox()
        self.account = QComboBox()
        self.depot.currentIndexChanged.connect(self.show_assignment)
        self.assign = QPushButton('Zuordnung speichern')
        self.assign.clicked.connect(self.assign_depot)
        for widget in (QLabel('Depot:'), self.depot, QLabel('Konto:'), self.account, self.assign):
            bar.addWidget(widget)
        root.addLayout(bar)
        self.refresh()

    def toggle_columns(self, visible):
        for col in (1, 2, 3, 4, 5):
            self.tree.setColumnHidden(col, not visible)
        for col in range(16, 20):
            self.tree.setColumnHidden(col, not visible)

    def refresh(self):
        if getattr(self.repo,'defer_initial_views',False): return
        expanded = set()
        current = self.tree.currentItem()
        current_key = current.data(0, Qt.ItemDataRole.UserRole + 2) if current else None
        scroll = self.tree.verticalScrollBar().value()
        iterator = QTreeWidgetItemIterator(self.tree)
        while iterator.value():
            item = iterator.value()
            if item.isExpanded():
                expanded.add(item.data(0, Qt.ItemDataRole.UserRole + 2))
            iterator += 1
        selected = self.depot.currentData()
        self.tree.clear()
        rows = self.repo.account_overview(self.date_getter())
        items = {}
        records = {r["name"]: r for r in self.repo.account_records()}
        records_by_key = {r['account_key']: r for r in records.values()}
        institutions = {r['account_key']: account_institution(r, records_by_key) for r in records.values()}
        from .tax_overview import tax_overview
        as_of = self.date_getter()
        current_year = QDate.currentDate().year()
        tax_year = min(int(as_of[:4]), current_year) if as_of[:4].isdigit() else current_year
        tax_accounts, tax_institutions = tax_overview(self.repo, tax_year)
        tax_by_key = {row['account_key']: row for row in tax_accounts}
        for column in range(8, 16):
            self.tree.headerItem().setToolTip(column, f'Steuerjahr {tax_year}')
        groups = {}
        for name in sorted({institutions[records[row['name']]['account_key']] for row in rows}, key=str.casefold):
            key = name.casefold()
            if key in groups:
                continue
            group = QTreeWidgetItem([name])
            for column in range(self.tree.columnCount()):
                group.setTextAlignment(column, Qt.AlignmentFlag.AlignCenter)
            group.setTextAlignment(0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            group.setData(0, Qt.ItemDataRole.UserRole + 2, ('institution', key))
            group.setData(0, Qt.ItemDataRole.UserRole + 1, (None, None, None))
            groups[key] = group
            self.tree.addTopLevelItem(group)
        from .performance_service import PerformanceService
        perf_service = PerformanceService(self.repo)
        perf_by_account = {}
        for account_name in self.repo.accounts():
            try:
                perf_1y = perf_service.analyze(account_name, *perf_service.preset_ranges(account_name).get('1 Jahr', ('9999-12-31', '9999-12-31')))
                perf_3y = perf_service.analyze(account_name, *perf_service.preset_ranges(account_name).get('3 Jahre', ('9999-12-31', '9999-12-31')))
                perf_by_account[account_name] = {
                    'twr_1y': perf_1y.get('twr_annualized'),
                    'twr_3y': perf_3y.get('twr_annualized'),
                    'max_drawdown': perf_1y.get('max_drawdown'),
                    'volatility': perf_1y.get('volatility_annualized'),
                }
            except Exception:
                perf_by_account[account_name] = {}
        for row in rows:
            item = QTreeWidgetItem([row['name'], euro(row['depot_value']), euro(row['balance']), '',
                                   display_dates(row['period']) or '–', row['categories'] or 'Kein Excel-Saldo zum Datum'])
            for column in range(self.tree.columnCount()):
                item.setTextAlignment(column, Qt.AlignmentFlag.AlignCenter)
            item.setTextAlignment(0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            item.setData(0, Qt.ItemDataRole.UserRole, row['name'])
            item.setData(0, Qt.ItemDataRole.UserRole + 2, ('account', records[row['name']]['account_key']))
            own_dates = {row['period']} if row['balance'] is not None and row['period'] else {d['date'] for d in row['depots'] if d['date']}
            if row.get('cash_from_transactions'):
                own_dates.update(d['date'] for d in row['depots'] if d['date'])
            item.setData(7, Qt.ItemDataRole.UserRole, sorted(own_dates))
            item.setData(0, Qt.ItemDataRole.UserRole + 1, (
                row['depot_value'], row['balance'],
                (row['balance'] + (row['depot_value'] or Decimal(0))) if row.get('cash_from_transactions')
                else (row['balance'] if row['balance'] is not None else row['depot_value'])))
            items[records[row["name"]]["account_key"]] = item
            tax = tax_by_key.get(records[row['name']]['account_key'])
            if tax:
                for column, value in zip(range(8, 16), (tax['interest_and_dividends'], tax['capital_income'], tax['taxes'],
                        tax['solidarity_surcharge'], tax['exemption'], tax['partial_exemption'], tax['used_exemption'],
                        tax['remaining_exemption'])):
                    item.setText(column, euro(value))
            perf = perf_by_account.get(row['name'], {})
            for col, key in ((16, 'twr_1y'), (17, 'twr_3y'), (18, 'max_drawdown'), (19, 'volatility')):
                value = perf.get(key)
                if value is not None:
                    item.setText(col, f'{float(value)*100:.2f} %')
                else:
                    item.setText(col, '–')
            dates = sorted({d['date'] for d in row['depots'] if d['date']})
            item.setText(3, display_dates(dates[0]) if len(dates) == 1 else ('Mehrere Stände' if dates else '–'))
            item.setToolTip(3, display_dates(', '.join(dates)))
            if row['depots']:
                item.setText(5, f"{sum(d['positions'] for d in row['depots'])} Positionen")
                item.setToolTip(5, 'Importierte Stände gehören zur Historie dieses Kontos/Depots.')
        for row in rows:
            record = records[row['name']]
            parent = items.get(record['parent_key'])
            institution = institutions[record['account_key']].casefold()
            if parent is None or row['depots'] or json.loads(record['details']).get('kind') == 'Depot' or institutions[record['parent_key']].casefold() != institution:
                parent = groups[institution]
            parent.addChild(items[record['account_key']])
        def rollup(item):
            own = item.data(0, Qt.ItemDataRole.UserRole + 1)
            if own is None:
                return None  # Depot detail rows are already included in their account.
            dates = set(item.data(7, Qt.ItemDataRole.UserRole) or [])
            values = [[value] if value is not None else [] for value in own]
            for index in range(item.childCount()):
                child = rollup(item.child(index))
                if child is not None:
                    dates.update(item.child(index).data(7, Qt.ItemDataRole.UserRole) or [])
                    for column, value in enumerate(child):
                        if value is not None:
                            values[column].append(value)
            item.setData(7, Qt.ItemDataRole.UserRole, sorted(dates))
            item.setText(7, display_dates(next(iter(dates))) if len(dates) == 1 else ('Mehrere Stände' if dates else '–'))
            item.setToolTip(7, display_dates(', '.join(sorted(dates))) or 'Kein Datenstand bekannt')
            totals = tuple(sum(group, Decimal(0)) if group else None for group in values)
            for column, value in zip((1, 2, 6), totals):
                item.setText(column, euro(value))
                item.setTextAlignment(column, Qt.AlignmentFlag.AlignCenter)
            item.setToolTip(6, 'Summe einschließlich Unterkonten. Umsatzsaldo zuzüglich Depotwert; reine Depotbewertungen zählen einmal. Umsatzsalden ohne Ausgangswert beginnen bei 0 €.')
            return totals
        for index in range(self.tree.topLevelItemCount()):
            rollup(self.tree.topLevelItem(index))
        for key, group in groups.items():
            tax = next((value for name, value in tax_institutions.items() if name.casefold() == key), None)
            if tax:
                for column, value in zip(range(8, 16), (tax['interest_and_dividends'], tax['capital_income'], tax['taxes'],
                        tax['solidarity_surcharge'], tax['exemption'], tax['partial_exemption'], tax['used_exemption'],
                        tax['remaining_exemption'])):
                    group.setText(column, euro(value))
                    group.setTextAlignment(column, Qt.AlignmentFlag.AlignCenter)
        iterator = QTreeWidgetItemIterator(self.tree)
        while iterator.value():
            item = iterator.value()
            key = item.data(0, Qt.ItemDataRole.UserRole + 2)
            item.setExpanded(key in expanded)
            if key == current_key:
                self.tree.setCurrentItem(item)
            iterator += 1
        self.tree.verticalScrollBar().setValue(scroll)
        self.summary.setText(f"{len(groups)} Institutsgruppen · {len(rows)} aktive Konten · {sum(len(r['depots']) for r in rows)} zugeordnete Depots")
        self.depot.blockSignals(True)
        self.depot.clear()
        self.account.clear()
        for name in self.repo.accounts():
            self.account.addItem(name, name)
        self.mappings = self.repo.depots()
        for depot in self.mappings:
            self.depot.addItem(depot['depot_name'], depot['depot_name'])
        self.depot.setCurrentIndex(max(0, self.depot.findData(selected)))
        self.depot.blockSignals(False)
        self.assign.setEnabled(bool(self.mappings and self.account.count()))
        self.show_assignment()

    def update_institution_action(self):
        item = self.tree.currentItem()
        key = item.data(0, Qt.ItemDataRole.UserRole + 2) if item else None
        self.rename_institute.setEnabled(bool(key and key[0] == 'institution'))

    def rename_institution(self):
        item = self.tree.currentItem()
        key = item.data(0, Qt.ItemDataRole.UserRole + 2) if item else None
        if not key or key[0] != 'institution':
            return
        name, accepted = QInputDialog.getText(self, 'Institut umbenennen', 'Neuer Institutsname:', text=item.text(0))
        if not accepted:
            return
        try:
            self.repo.rename_institution(item.text(0), name)
        except ValueError as error:
            QMessageBox.warning(self, 'Institut umbenennen', str(error))
            return
        self.refresh()
        for index in range(self.tree.topLevelItemCount()):
            group = self.tree.topLevelItem(index)
            if group.text(0) == ' '.join(name.split()):
                self.tree.setCurrentItem(group)
                group.setExpanded(True)
                break
        self.changed.emit()

    def show_tax_overview(self):
        from .tax_overview import TaxOverviewDialog
        TaxOverviewDialog(self.repo, self).exec()

    def show_assignment(self):
        current = next((d for d in getattr(self, 'mappings', []) if d['depot_name'] == self.depot.currentData()), None)
        if current:
            self.account.setCurrentIndex(self.account.findData(current['account']))

    def assign_depot(self):
        if not self.depot.currentData() or not self.account.currentData():
            return
        try:
            self.repo.assign_depot(self.depot.currentData(), self.account.currentData())
            self.refresh()
            self.changed.emit()
        except ValueError as exc:
            QMessageBox.warning(self, 'Depot zuordnen', str(exc))

    def select_account(self, item, column):
        account = item.data(0, Qt.ItemDataRole.UserRole)
        if account:
            self.account_selected.emit(account)
            from .account_bookings_dialog import AccountBookingsDialog
            dialog = AccountBookingsDialog(self.repo, account, self)
            dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
            dialog.show()
