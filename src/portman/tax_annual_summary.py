"""Account- and institution-specific annual tax summary."""
from __future__ import annotations

import re
from collections import defaultdict
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QDialog, QDialogButtonBox, QHBoxLayout,
                               QLabel, QSpinBox, QTableWidget, QTableWidgetItem,
                               QVBoxLayout)

from portfolio_v5.accounts import account_key
from portfolio_v5.comdirect_tax_detail import date_value
from .institutions import account_institution
from .tax_overview import automatic_tax_values


METRICS = (
    ('stock_result', 'Gewinne/Verluste Aktien (Saldo)'),
    ('stock_loss_pot', 'Verlustverrechnungstopf Aktien'),
    ('other_result', 'Gewinne/Verluste Sonstige (Saldo)'),
    ('other_loss_pot', 'Verlustverrechnungstopf Sonstige'),
    ('used_exemption', 'In Anspruch genommener Freibetrag'),
    ('remaining_exemption', 'Verbleibender Freibetrag'),
    ('creditable_withholding', 'Anrechenbare ausländische Quellensteuer'),
    ('capital_gains_tax', 'Abgeführte Kapitalertragsteuern'),
    ('solidarity_surcharge', 'Abgeführter Solidaritätszuschlag'),
    ('church_tax', 'Abgeführte Kirchensteuer'),
    ('credited_withholding', 'Angerechnete ausländische Quellensteuer'),
)


def _number(value):
    if value in (None, ''):
        return None
    try:
        text = str(value).strip()
        return Decimal(text.replace('.', '').replace(',', '.')) if ',' in text else Decimal(text)
    except (InvalidOperation, ValueError):
        return None


def _sum(rows, column, *, invert=False):
    values = [_number(row.get(column)) for row in rows if row.get(column, '') != '']
    if not values:
        return None
    total = sum((value for value in values if value is not None), Decimal())
    return -total if invert else total


def _latest(rows, column):
    candidates = [(date_value(row, 'Steuerliches Datum') or date_value(row, 'Buchungstag'),
                   _number(row.get(column))) for row in rows if row.get(column, '') != '']
    candidates = [(day, value) for day, value in candidates if value is not None]
    return max(candidates, default=('', None), key=lambda item: item[0])[1]


def _source_date(detail_rows):
    direct = [row.get('source_date', '') for row in detail_rows if row.get('source_date')]
    if direct:
        return max(direct)
    for row in detail_rows:
        match = re.search(r'(20\d{6})[-_]?\d{4}', Path(row.get('source', '')).name)
        if match:
            raw = match.group(1)
            return f'{raw[:4]}-{raw[4:6]}-{raw[6:]}'
    days = [row.get('tax_date') or row.get('booking_date') for row in detail_rows]
    return max((day for day in days if day), default='')


def _bank_values(detail_rows, exemption=None):
    rows = [row.get('original_values') or {} for row in detail_rows]
    stock_balance = _latest(rows, 'Gewinn/Verlust Aktien (Saldo)')
    other_balance = _latest(rows, 'Gewinn/Verlust Sonstige (Saldo)')
    used = _sum(rows, 'Veränderung FSA', invert=True)
    after_fsa = _sum(rows, 'BMG nach FSA')
    remaining = None
    if exemption is not None and used is not None:
        remaining = max(Decimal(), exemption - used)
    elif used and after_fsa and after_fsa > 0:
        # A positive, bank-documented BMG after FSA together with prior FSA
        # consumption proves that the available order is exhausted.
        remaining = Decimal()
    return {
        'stock_result': stock_balance,
        'stock_loss_pot': max(Decimal(), -stock_balance) if stock_balance is not None else None,
        'other_result': other_balance,
        'other_loss_pot': max(Decimal(), -other_balance) if other_balance is not None else None,
        'used_exemption': used,
        'remaining_exemption': remaining,
        'creditable_withholding': _sum(rows, 'Umsatz anrechenbarer Quellensteuer'),
        'capital_gains_tax': _sum(rows, 'Kapitalertragssteuer', invert=True),
        'solidarity_surcharge': _sum(rows, 'Solidaritätszuschlag', invert=True),
        'church_tax': _sum(rows, 'Kirchensteuer', invert=True),
        'credited_withholding': _sum(rows, 'Veränderung Angerechnete Quellensteuer', invert=True),
    }


def tax_annual_summaries(repository, year):
    """Return documented bank values and calculated Portman values by account."""
    accounts = {row['account_key']: row for row in repository.account_records() if row['active']}
    by_name = {account_key(row['name']): row['account_key'] for row in accounts.values()}
    details = (repository._imported_tax_detail_records(tax_year=year)
               if hasattr(repository, '_imported_tax_detail_records') else [])
    grouped = defaultdict(list)
    for row in details:
        key = by_name.get(account_key(row.get('account', '')))
        if key:
            grouped[key].append(row)
    automatic = automatic_tax_values(repository, year)
    saved = {row['institution_key']: row for row in repository.institution_tax_records(year)} \
        if hasattr(repository, 'institution_tax_records') else {}
    result = []
    for key in sorted(set(grouped) | set(automatic)):
        record = accounts.get(key)
        if not record:
            continue
        institution = account_institution(record, accounts)
        saved_row = saved.get(institution.casefold(), {})
        exemption = _number(saved_row.get('exemption'))
        bank = _bank_values(grouped.get(key, []), exemption) if grouped.get(key) else {name: None for name, _ in METRICS}
        auto = automatic.get(key, {})
        taxes = auto.get('taxes')
        solidarity = auto.get('solidarity_surcharge')
        church = auto.get('church_tax')
        portman = {
            'stock_result': None, 'stock_loss_pot': None,
            'other_result': auto.get('capital_income'), 'other_loss_pot': None,
            'used_exemption': auto.get('used_exemption'),
            'remaining_exemption': (max(Decimal(), exemption - auto.get('used_exemption', Decimal()))
                                    if exemption is not None else bank.get('remaining_exemption')),
            'creditable_withholding': auto.get('creditable_withholding'),
            'capital_gains_tax': (taxes - (solidarity or Decimal()) - (church or Decimal())
                                  if taxes is not None else None),
            'solidarity_surcharge': solidarity,
            'church_tax': church,
            'credited_withholding': auto.get('credited_withholding'),
        }
        source_names = sorted({row.get('source_name') or Path(row.get('source', '')).name
                               for row in grouped.get(key, []) if row.get('source_name') or row.get('source')})
        result.append({'institution': institution, 'account_key': key, 'account': record['name'],
                       'year': int(year), 'as_of': _source_date(grouped.get(key, [])),
                       'source': ', '.join(source_names) or 'Automatisch aus Portman-Buchungen',
                       'bank': bank, 'portman': portman,
                       'reference_rows': len(grouped.get(key, []))})
    return result


def _money(value):
    if value is None:
        return 'n. v.'
    return f'{value:,.2f}'.replace(',', 'X').replace('.', ',').replace('X', '.')


class TaxAnnualSummaryDialog(QDialog):
    def __init__(self, repository, parent=None):
        super().__init__(parent)
        self.repository = repository
        self.setWindowTitle('Steuerliche Jahresübersicht')
        self.resize(980, 680)
        root = QVBoxLayout(self)
        bar = QHBoxLayout()
        bar.addWidget(QLabel('Steuerjahr'))
        self.year = QSpinBox(); self.year.setRange(1900, 9999); self.year.setValue(QDate.currentDate().year())
        bar.addWidget(self.year); bar.addWidget(QLabel('Bankinstitut'))
        self.institution = QComboBox(); bar.addWidget(self.institution)
        bar.addWidget(QLabel('Konto'))
        self.account = QComboBox(); bar.addWidget(self.account, 1)
        root.addLayout(bar)
        self.heading = QLabel(); self.heading.setTextFormat(Qt.TextFormat.RichText); root.addWidget(self.heading)
        self.source = QLabel(); self.source.setWordWrap(True); root.addWidget(self.source)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(('Steuerkennzahl', 'Bankwert EUR', 'Portman EUR', 'Differenz EUR'))
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True); root.addWidget(self.table, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject); root.addWidget(buttons)
        self.year.valueChanged.connect(self.reload)
        self.institution.currentTextChanged.connect(self._institutions_changed)
        self.account.currentIndexChanged.connect(self.refresh)
        self.reload()

    def reload(self, *_):
        self.rows = tax_annual_summaries(self.repository, self.year.value())
        current = self.institution.currentText()
        self.institution.blockSignals(True); self.institution.clear()
        self.institution.addItems(sorted({row['institution'] for row in self.rows}, key=str.casefold))
        if current: self.institution.setCurrentText(current)
        self.institution.blockSignals(False)
        self._institutions_changed()

    def _institutions_changed(self, *_):
        institution = self.institution.currentText(); self.account.blockSignals(True); self.account.clear()
        rows = [row for row in self.rows if row['institution'] == institution]
        if len(rows) > 1: self.account.addItem('Alle Konten des Instituts', '')
        for row in rows: self.account.addItem(row['account'], row['account_key'])
        self.account.blockSignals(False); self.refresh()

    def _selected(self):
        institution = self.institution.currentText(); key = self.account.currentData()
        return [row for row in self.rows if row['institution'] == institution
                and (not key or row['account_key'] == key)]

    def refresh(self, *_):
        rows = self._selected()
        if not rows:
            self.heading.setText(f'<b>Steuerliche Daten für das Jahr {self.year.value()}</b>')
            self.source.setText('Keine Daten verfügbar.'); self.table.setRowCount(0); return
        as_of = max((row['as_of'] for row in rows if row['as_of']), default='')
        shown_date = date.fromisoformat(as_of).strftime('%d.%m.%Y') if as_of else 'n. v.'
        self.heading.setText(f'<b>Steuerliche Daten für das Jahr {self.year.value()}</b><br>Stand: {shown_date}')
        sources = sorted({row['source'] for row in rows})
        self.source.setText(f"Quelle: {'; '.join(sources)} · Referenzzeilen: {sum(row['reference_rows'] for row in rows)}")
        self.table.setRowCount(len(METRICS))
        for r, (field, label) in enumerate(METRICS):
            bank_values = [row['bank'][field] for row in rows]
            portman_values = [row['portman'][field] for row in rows]
            bank = sum(bank_values, Decimal()) if bank_values and all(v is not None for v in bank_values) else None
            portman = sum(portman_values, Decimal()) if portman_values and all(v is not None for v in portman_values) else None
            difference = portman - bank if portman is not None and bank is not None else None
            for c, value in enumerate((label, _money(bank), _money(portman), _money(difference))):
                self.table.setItem(r, c, QTableWidgetItem(value))
        self.table.resizeColumnsToContents(); self.table.horizontalHeader().setStretchLastSection(True)
