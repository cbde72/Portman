"""Dividend and cost analysis by depot and security position."""
from collections import defaultdict
from decimal import Decimal, InvalidOperation

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QDateEdit, QHBoxLayout,
                               QLabel, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from portfolio_v5.accounts import account_key
from portman.chart_style import PALETTE, create_figure, get_current_colors, style_axis
from portman.repository_v09 import reference
from portman.safe_canvas import SafeFigureCanvas


KINDS = {'DIVIDEND', 'FEE', 'TAX'}


def _decimal(value):
    try:
        return Decimal(str(value or 0))
    except (InvalidOperation, ValueError):
        return Decimal()


def income_cost_rows(repository, depot_key, security=None, as_of='9999-12-31', start_date='0001-01-01'):
    """Return attributed income/cost rows without counting linked fees twice."""
    records = {row['account_key']: row for row in repository.account_records()}
    depot = records.get(depot_key)
    if depot is None:
        return []
    depot_name = depot['name']
    linked_refs = {row['fee_ref'] for row in repository.fee_links()}
    result = []
    for tx in repository.transactions():
        if not start_date <= tx.get('date', '') <= as_of or tx.get('kind') not in KINDS:
            continue
        owner = tx.get('performance_depot_key')
        belongs = owner == depot_key or (not owner and account_key(tx.get('depot', '')) == account_key(depot_name))
        if not belongs or (security and tx.get('security') != security):
            continue
        ref = reference(tx)
        # A linked standalone FEE/TAX row only proves an amount already stored
        # on its primary booking and must not be counted a second time.
        if ref in linked_refs:
            continue
        kind = tx['kind']
        amount = _decimal(tx.get('amount'))
        fees = abs(_decimal(tx.get('fees')))
        taxes = abs(_decimal(tx.get('taxes')))
        if kind == 'FEE' and not fees:
            fees = abs(amount)
        if kind == 'TAX' and not taxes:
            taxes = abs(amount)
        gross = _decimal(tx.get('gross_income')) if kind == 'DIVIDEND' else Decimal()
        if kind == 'DIVIDEND' and not gross:
            gross = amount + fees + taxes
        result.append({
            'date': tx.get('date', ''), 'kind': kind, 'security': tx.get('security') or '',
            'description': tx.get('purpose') or tx.get('booking_text') or tx.get('counterparty') or '',
            'currency': tx.get('currency') or 'EUR',
            'net_dividend': amount if kind == 'DIVIDEND' else Decimal(),
            'gross_dividend': gross, 'fees': fees, 'taxes': taxes,
        })
    return sorted(result, key=lambda row: (row['date'], row['kind']), reverse=True)


def annual_dividends(rows):
    """Aggregate net dividends as currency -> year -> security -> amount."""
    result = defaultdict(lambda: defaultdict(lambda: defaultdict(Decimal)))
    for row in rows:
        if row.get('kind') != 'DIVIDEND' or not row.get('date'):
            continue
        result[row.get('currency') or 'EUR'][row['date'][:4]][row.get('security') or ''] += row['net_dividend']
    return {
        currency: {year: dict(positions) for year, positions in years.items()}
        for currency, years in result.items()
    }


def depot_years(repository, depot_key, as_of):
    """Return every selectable year from the depot's first data point onward."""
    records = {row['account_key']: row for row in repository.account_records()}
    depot = records.get(depot_key)
    if depot is None:
        return []
    dates = []
    store = getattr(repository, 'store', None)
    if store is not None and hasattr(store, 'snapshots'):
        dates.extend((row.get('effective_date') or row.get('as_of') or row.get('period') or '')
                     for row in store.snapshots(depot['name']))
    if not dates:
        for tx in repository.transactions():
            owner = tx.get('performance_depot_key')
            belongs = owner == depot_key or (
                not owner and account_key(tx.get('depot', '')) == account_key(depot['name'])
            )
            if belongs:
                dates.append(tx.get('date', ''))
    years = [int(value[:4]) for value in dates if value and value[:4].isdigit() and value <= as_of]
    if not years:
        return []
    current_year = QDate.currentDate().year()
    end_year = min(int(as_of[:4]), current_year) if as_of[:4].isdigit() else current_year
    return list(range(min(years), end_year + 1))


def annual_interest_rows(repository, start_date='0001-01-01', as_of='9999-12-31'):
    """Aggregate received interest for every account, year and currency."""
    account_names = {row['account_key']: row['name'] for row in repository.account_records()}
    annual = defaultdict(lambda: {'count': 0, 'amount': Decimal()})
    for tx in repository.transactions():
        from .interest_recognition import is_interest_transaction
        if not is_interest_transaction(tx) or not start_date <= tx.get('date', '') <= as_of:
            continue
        account = account_names.get(account_key(tx.get('account', '')), tx.get('account') or 'Ohne Konto')
        key = (tx['date'][:4], account, tx.get('currency') or 'EUR')
        annual[key]['count'] += 1
        annual[key]['amount'] += _decimal(tx.get('amount'))
    return [(year, account, currency, values['count'], values['amount'])
            for (year, account, currency), values in sorted(
                annual.items(), key=lambda item: (item[0][0], item[0][1].casefold(), item[0][2]), reverse=True)]


class IncomeCostsWidget(QWidget):
    HEADERS = ('Datum', 'Art', 'Position', 'Beschreibung', 'Währung',
               'Dividende netto', 'Dividende brutto', 'Gebühren', 'Steuern')

    def __init__(self, repository, as_of, parent=None):
        super().__init__(parent)
        self.repository, self.as_of = repository, as_of
        layout = QVBoxLayout(self)
        controls = QHBoxLayout()
        controls.addWidget(QLabel('Depot'))
        self.depot = QComboBox(); controls.addWidget(self.depot, 1)
        controls.addWidget(QLabel('Depotposition'))
        self.security = QComboBox(); controls.addWidget(self.security, 2)
        layout.addLayout(controls)
        period = QHBoxLayout(); period.addWidget(QLabel('Zeitraum'))
        self.period = QComboBox()
        for label, value in (('Aktuelles Jahr', 'current'), ('Letzte 12 Monate', 'rolling'),
                             ('Gesamter Zeitraum', 'all'), ('Benutzerdefiniert', 'custom')):
            self.period.addItem(label, value)
        period.addWidget(self.period)
        self.start = QDateEdit(); self.end = QDateEdit()
        for editor in (self.start, self.end):
            editor.setCalendarPopup(True); editor.setDisplayFormat('dd.MM.yyyy')
            editor.setMinimumDate(QDate(1900, 1, 1)); editor.setMaximumDate(QDate(9999, 12, 31))
        period.addWidget(QLabel('von')); period.addWidget(self.start)
        period.addWidget(QLabel('bis')); period.addWidget(self.end); period.addStretch(1)
        layout.addLayout(period)
        self.summary = QLabel(); self.summary.setWordWrap(True)
        self.summary.setTextFormat(Qt.TextFormat.RichText); layout.addWidget(self.summary)
        layout.addWidget(QLabel('<b>Erhaltene Zinsen je Konto und Jahr</b>'))
        self.interest = QTableWidget(0, 5)
        self.interest.setHorizontalHeaderLabels(('Jahr', 'Konto', 'Währung', 'Zahlungen', 'Zinsen'))
        self.interest.setAlternatingRowColors(True)
        self.interest.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.interest.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.interest.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.interest, 1)
        layout.addWidget(QLabel('<b>Dividenden pro Jahr und Depotposition</b>'))
        self.annual_figure = create_figure(9, 3.2)
        self.annual_canvas = SafeFigureCanvas(self.annual_figure)
        self.annual_canvas.setMinimumHeight(260)
        layout.addWidget(self.annual_canvas, 2)
        layout.addWidget(QLabel('<b>Jahreswerte</b>'))
        self.annual = QTableWidget(0, 6)
        self.annual.setHorizontalHeaderLabels(('Jahr', 'Position', 'Währung', 'Zahlungen', 'Netto', 'Brutto'))
        self.annual.setAlternatingRowColors(True); self.annual.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.annual.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.annual.horizontalHeader().setStretchLastSection(True); layout.addWidget(self.annual, 1)
        layout.addWidget(QLabel('<b>Zeitleiste der Zahlungen und Kosten</b>'))
        self.table = QTableWidget(0, len(self.HEADERS)); self.table.setHorizontalHeaderLabels(self.HEADERS)
        self.table.setAlternatingRowColors(True); self.table.setSortingEnabled(True)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table, 1)
        self.depot.currentIndexChanged.connect(self._depot_changed)
        self.security.currentIndexChanged.connect(self.refresh)
        self.period.currentIndexChanged.connect(self._apply_period)
        self.start.dateChanged.connect(self._custom_period)
        self.end.dateChanged.connect(self._custom_period)
        self._apply_period(0)
        self.refresh_depots()

    def _apply_period(self, index):
        today = QDate.currentDate()
        end_limit = QDate.fromString(self.as_of(), 'yyyy-MM-dd')
        end = min(today, end_limit) if end_limit.isValid() else today
        selection = self.period.itemData(index)
        if selection == 'current': start = QDate(end.year(), 1, 1)
        elif selection == 'rolling': start = end.addYears(-1).addDays(1)
        elif selection == 'all': start = QDate(1900, 1, 1)
        elif isinstance(selection, int):
            start, end = QDate(selection, 1, 1), QDate(selection, 12, 31)
            if end_limit.isValid() and end > end_limit: end = end_limit
        else: return
        for editor, value in ((self.start, start), (self.end, end)):
            editor.blockSignals(True); editor.setDate(value); editor.blockSignals(False)
        self.refresh()

    def _custom_period(self, *_):
        self.period.blockSignals(True); self.period.setCurrentIndex(3); self.period.blockSignals(False)
        self.refresh()

    def _refresh_period_years(self, depot_key):
        selected = self.period.currentData()
        self.period.blockSignals(True)
        while self.period.count() > 4:
            self.period.removeItem(4)
        years = depot_years(self.repository, depot_key, self.as_of()) if depot_key else []
        if years:
            self.period.insertSeparator(4)
            for year in reversed(years):
                self.period.addItem(str(year), year)
        index = self.period.findData(selected)
        self.period.setCurrentIndex(index if index >= 0 else 0)
        self.period.blockSignals(False)
        if index < 0:
            self._apply_period(0)

    def refresh_depots(self):
        selected = self.depot.currentData()
        self.depot.blockSignals(True); self.depot.clear()
        for record in self.repository.account_records():
            import json
            if record['active'] and json.loads(record['details']).get('kind') == 'Depot':
                self.depot.addItem(record['name'], record['account_key'])
        index = self.depot.findData(selected)
        self.depot.setCurrentIndex(index if index >= 0 else 0)
        self.depot.blockSignals(False)
        self._depot_changed()

    def _depot_changed(self):
        selected = self.security.currentData()
        depot_key = self.depot.currentData()
        self.security.blockSignals(True); self.security.clear(); self.security.addItem('Alle Depotpositionen', None)
        if depot_key:
            records = {row['account_key']: row for row in self.repository.account_records()}
            depot = records.get(depot_key)
            positions = self.repository.holdings(self.as_of(), depot['name']) if depot else []
            choices = {}
            for position in positions:
                key = position.get('isin') or position.get('key') or position.get('wkn')
                if key: choices[key] = position.get('name') or key
            for row in income_cost_rows(self.repository, depot_key, as_of=self.as_of()):
                if row['security']: choices.setdefault(row['security'], row['security'])
            for key, name in sorted(choices.items(), key=lambda item: item[1].casefold()):
                self.security.addItem(f'{name} · {key}', key)
        index = self.security.findData(selected)
        self.security.setCurrentIndex(index if index >= 0 else 0)
        self.security.blockSignals(False)
        self._refresh_period_years(depot_key)
        self.refresh()

    def refresh(self, *_):
        depot_key = self.depot.currentData()
        start, end = self.start.date().toString('yyyy-MM-dd'), self.end.date().toString('yyyy-MM-dd')
        rows = income_cost_rows(self.repository, depot_key, self.security.currentData(), end, start) if depot_key else []
        totals = defaultdict(lambda: defaultdict(Decimal))
        for row in rows:
            for field in ('net_dividend', 'gross_dividend', 'fees', 'taxes'):
                totals[row['currency']][field] += row[field]
        if totals:
            parts = []
            for currency, values in sorted(totals.items()):
                parts.append(f"<b>{currency}</b>: Dividenden netto {values['net_dividend']:,.2f} · brutto {values['gross_dividend']:,.2f} · Gebühren {values['fees']:,.2f} · Steuern {values['taxes']:,.2f}")
            self.summary.setText('<br>'.join(parts))
        else:
            self.summary.setText('Für diese Auswahl sind keine Dividenden oder Kosten hinterlegt.')
        interest_rows = annual_interest_rows(self.repository, start, end)
        self.interest.setSortingEnabled(False); self.interest.setRowCount(len(interest_rows))
        for r, values in enumerate(interest_rows):
            for c, value in enumerate(values):
                item = QTableWidgetItem(f'{value:,.2f}' if isinstance(value, Decimal) else str(value))
                if isinstance(value, (Decimal, int)):
                    item.setData(Qt.ItemDataRole.UserRole, float(value))
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.interest.setItem(r, c, item)
        self.interest.setSortingEnabled(True); self.interest.resizeColumnsToContents()
        position_names = {self.security.itemData(i): self.security.itemText(i).rsplit(' · ', 1)[0]
                          for i in range(1, self.security.count())}
        annual = defaultdict(lambda: {'count': 0, 'net': Decimal(), 'gross': Decimal()})
        for row in rows:
            if row['kind'] == 'DIVIDEND':
                key = (row['date'][:4], row['security'], row['currency'])
                annual[key]['count'] += 1; annual[key]['net'] += row['net_dividend']; annual[key]['gross'] += row['gross_dividend']
        annual_rows = sorted(annual.items(), key=lambda item: (item[0][0], position_names.get(item[0][1], item[0][1])), reverse=True)
        self._draw_annual_chart(rows, position_names)
        self.annual.setSortingEnabled(False); self.annual.setRowCount(len(annual_rows))
        for r, ((year, security, currency), values) in enumerate(annual_rows):
            columns = (year, position_names.get(security, security or 'Ohne Zuordnung'), currency,
                       values['count'], values['net'], values['gross'])
            for c, value in enumerate(columns):
                item = QTableWidgetItem(f'{value:,.2f}' if isinstance(value, Decimal) else str(value))
                if isinstance(value, (Decimal, int)):
                    item.setData(Qt.ItemDataRole.UserRole, float(value)); item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.annual.setItem(r, c, item)
        self.annual.setSortingEnabled(True); self.annual.resizeColumnsToContents()
        self.table.setSortingEnabled(False); self.table.setRowCount(len(rows))
        labels = {'DIVIDEND': 'Dividende', 'FEE': 'Gebühr', 'TAX': 'Steuer'}
        for r, row in enumerate(rows):
            values = (row['date'], labels[row['kind']], row['security'], row['description'], row['currency'],
                      row['net_dividend'], row['gross_dividend'], row['fees'], row['taxes'])
            for c, value in enumerate(values):
                item = QTableWidgetItem(f'{value:,.2f}' if isinstance(value, Decimal) else str(value))
                if isinstance(value, Decimal):
                    item.setData(Qt.ItemDataRole.UserRole, float(value)); item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.table.setItem(r, c, item)
        self.table.setSortingEnabled(True); self.table.resizeColumnsToContents()

    def _draw_annual_chart(self, rows, position_names):
        data = annual_dividends(rows)
        figure = self.annual_figure
        figure.clear()
        colors = get_current_colors()
        if not data:
            axis = figure.add_subplot(111)
            style_axis(axis)
            axis.text(.5, .5, 'Keine Dividenden im gewählten Zeitraum', ha='center', va='center',
                      transform=axis.transAxes, color=colors['muted'])
            axis.set_axis_off()
            self.annual_canvas.draw_idle()
            return

        currencies = sorted(data)
        axes = figure.subplots(len(currencies), 1, squeeze=False)[:, 0]
        legend_handles = {}
        for axis, currency in zip(axes, currencies):
            years = sorted(data[currency])
            securities = sorted(
                {security for values in data[currency].values() for security in values},
                key=lambda security: (
                    -sum(abs(data[currency][year].get(security, Decimal())) for year in years),
                    position_names.get(security, security).casefold(),
                ),
            )
            positive_bottom = [0.0] * len(years)
            negative_bottom = [0.0] * len(years)
            for index, security in enumerate(securities):
                values = [float(data[currency][year].get(security, Decimal())) for year in years]
                bottoms = [positive_bottom[i] if value >= 0 else negative_bottom[i]
                           for i, value in enumerate(values)]
                label = position_names.get(security, security or 'Ohne Zuordnung')
                bars = axis.bar(years, values, bottom=bottoms, width=.65,
                                 color=PALETTE[index % len(PALETTE)], label=label)
                legend_handles.setdefault(label, bars[0])
                for i, value in enumerate(values):
                    if value >= 0: positive_bottom[i] += value
                    else: negative_bottom[i] += value
            for i, year in enumerate(years):
                total = sum(float(value) for value in data[currency][year].values())
                offset = 4 if total >= 0 else -10
                axis.annotate(f'{total:,.2f}'.replace(',', 'X').replace('.', ',').replace('X', '.'),
                              (i, total), xytext=(0, offset), textcoords='offset points',
                              ha='center', va='bottom' if total >= 0 else 'top', fontsize=7,
                              color=colors['text'])
            axis.axhline(0, color=colors['grid'], linewidth=.8)
            axis.set_ylabel(f'Netto ({currency})')
            style_axis(axis, grid_axis='y')
            axis.margins(x=.08, y=.16)

        if legend_handles:
            figure.legend(legend_handles.values(), legend_handles.keys(), loc='outside lower center',
                          ncol=min(4, len(legend_handles)), frameon=False, fontsize=7)
            figure.subplots_adjust(bottom=min(.34, .10 + .055 * ((len(legend_handles) - 1) // 4 + 1)))
        self.annual_canvas.draw_idle()
