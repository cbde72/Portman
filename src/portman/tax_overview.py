"""Annual exemption orders, investment income and tax overview."""
import json
from collections import defaultdict
from decimal import Decimal, InvalidOperation

from PySide6.QtCore import Qt, QDate
from PySide6.QtWidgets import (QAbstractItemView, QDialog, QDialogButtonBox, QHBoxLayout,
                               QLabel, QMessageBox, QPushButton, QSpinBox, QTableWidget,
                               QTableWidgetItem, QVBoxLayout)

from portfolio_v5.accounts import account_key
from .institutions import account_institution


def _number(value):
    try:
        return Decimal(str(value or 0))
    except (InvalidOperation, ValueError):
        return Decimal()


def automatic_tax_values(repository, year):
    """Return booked gross investment income and taxes per account key."""
    records = {row['account_key']: row for row in repository.account_records()}
    name_keys = {account_key(row['name']): row['account_key'] for row in records.values()}
    linked = {row['fee_ref'] for row in repository.fee_links()} if hasattr(repository, 'fee_links') else set()
    values = defaultdict(lambda: {'interest': Decimal(), 'dividends': Decimal(), 'capital_income': Decimal(),
                                   'taxes': Decimal(), 'withholding_tax': Decimal(),
                                   'solidarity_surcharge': Decimal(), 'partial_exemption': Decimal(),
                                   'used_exemption': Decimal(), 'advance_tax_base': Decimal(),
                                   'advance_tax_taxable': Decimal(), 'advance_tax_count': 0})
    for tx in repository.transactions():
        if tx.get('date', '')[:4] != str(year):
            continue
        if (tx.get('gross_currency') or tx.get('currency') or 'EUR') != 'EUR':
            continue
        key = tx.get('performance_depot_key') or name_keys.get(
            account_key(tx.get('account', '')), account_key(tx.get('account', '')))
        if key not in records:
            continue
        from .interest_recognition import is_interest_transaction
        kind = 'INTEREST' if is_interest_transaction(tx) else tx.get('kind')
        tax_items = tx.get('tax_items') or []
        solidarity = sum((_number(item.get('amount') if isinstance(item, dict) else item.amount)
                          for item in tax_items
                          if (item.get('kind') if isinstance(item, dict) else item.kind)
                          in ('solidaritaetszuschlag', 'solidaritätszuschlag')), Decimal())
        if kind in ('DIVIDEND', 'DISTRIBUTION'):
            fees, taxes = abs(_number(tx.get('fees'))), abs(_number(tx.get('taxes')))
            gross = _number(tx.get('gross_income')) or (_number(tx.get('amount')) + fees + taxes)
            values[key]['capital_income'] += gross
            # The overview column shows cash actually received, matching the
            # net interest credits shown for bank accounts.
            values[key]['dividends'] += _number(tx.get('amount'))
            values[key]['taxes'] += taxes
            values[key]['withholding_tax'] += abs(_number(tx.get('withholding_tax')))
            values[key]['solidarity_surcharge'] += solidarity
        elif kind == 'INTEREST':
            interest = _number(tx.get('gross_income')) or _number(tx.get('amount'))
            values[key]['interest'] += interest
            values[key]['capital_income'] += interest
            values[key]['taxes'] += abs(_number(tx.get('taxes')))
            values[key]['withholding_tax'] += abs(_number(tx.get('withholding_tax')))
            values[key]['solidarity_surcharge'] += solidarity
        elif kind == 'TAX':
            try:
                from .repository_v09 import reference
                if reference(tx) in linked:
                    continue
            except KeyError:
                pass
            values[key]['taxes'] += abs(_number(tx.get('amount')))
            if 'solidaritätszuschlag' in (tx.get('purpose') or '').casefold():
                values[key]['solidarity_surcharge'] += abs(_number(tx.get('amount')))
    store = getattr(repository, 'store', None)
    if store is None or not hasattr(store, 'model_records'):
        return dict(values)
    links = store._import_links()
    mappings = store._depot_mappings()
    seen_events = set()
    for record in store.model_records(kind='tax_events'):
        event = record['payload']
        if event.get('type') != 'vorabpauschale_ausland' or str(event.get('tax_year') or event.get('date', '')[:4]) != str(year):
            continue
        identity = event.get('external_id') or (event.get('account'), event.get('date'), event.get('security_ref'))
        if identity in seen_events:
            continue
        seen_events.add(identity)
        source_key = account_key(event.get('account', ''))
        key = links.get((record['import_id'], source_key), mappings.get(source_key, source_key))
        if key not in records or (event.get('currency') or 'EUR') != 'EUR':
            continue
        base = abs(_number(event.get('advance_tax_base')))
        taxable = abs(_number(event.get('taxable_income')))
        values[key]['advance_tax_base'] += base
        values[key]['advance_tax_taxable'] += taxable
        values[key]['advance_tax_count'] += 1
        values[key]['capital_income'] += base
        partial = abs(_number(event.get('partial_exemption_amount')))
        values[key]['partial_exemption'] += partial if partial else max(Decimal(), base - taxable)
        values[key]['used_exemption'] += abs(_number(event.get('used_exemption')))
    return dict(values)


def tax_overview(repository, year):
    """Combine booked account facts with one editable annual record per institution."""
    records = [row for row in repository.account_records() if row['active']]
    by_key = {row['account_key']: row for row in records}
    automatic = automatic_tax_values(repository, year)
    legacy_saved = {row['account_key']: row for row in repository.account_tax_records(year)}
    institution_saved = ({row['institution_key']: row for row in repository.institution_tax_records(year)}
                         if hasattr(repository, 'institution_tax_records') else {})
    accounts = []
    institutions = defaultdict(lambda: {'interest': Decimal(), 'dividends': Decimal(),
        'interest_and_dividends': Decimal(), 'exemption': Decimal(),
        'capital_income': Decimal(), 'taxes': Decimal(), 'withholding_tax': Decimal(),
        'solidarity_surcharge': Decimal(),
        'partial_exemption': Decimal(),
        'used_exemption': Decimal(), 'remaining_exemption': Decimal(),
        'advance_tax_base': Decimal(), 'advance_tax_taxable': Decimal(),
        'advance_tax_count': 0, 'accounts': 0})
    legacy = defaultdict(lambda: {'exemption': Decimal(), 'capital_income': Decimal(),
        'taxes': Decimal(), 'partial_exemption': Decimal(), 'used_exemption': Decimal(),
        'solidarity_surcharge': Decimal(), 'notes': []})
    for record in records:
        key = record['account_key']; manual = legacy_saved.get(key, {}); booked = automatic.get(key, {})
        details = json.loads(record['details'])
        institution = account_institution(record, by_key)
        row = dict(account_key=key, account=record['name'], institution=institution,
                   interest=booked.get('interest', Decimal()), exemption=Decimal(),
                   dividends=booked.get('dividends', Decimal()),
                   interest_and_dividends=(booked.get('interest', Decimal()) +
                                           booked.get('dividends', Decimal())),
                   capital_income=booked.get('capital_income', Decimal()),
                   taxes=booked.get('taxes', Decimal()),
                   solidarity_surcharge=booked.get('solidarity_surcharge', Decimal()),
                   withholding_tax=booked.get('withholding_tax', Decimal()),
                   advance_tax_base=booked.get('advance_tax_base', Decimal()),
                   advance_tax_taxable=booked.get('advance_tax_taxable', Decimal()),
                   advance_tax_count=booked.get('advance_tax_count', 0),
                   partial_exemption=booked.get('partial_exemption', Decimal()),
                   used_exemption=booked.get('used_exemption', Decimal()), remaining_exemption=Decimal(),
                   booked_capital_income=booked.get('capital_income', Decimal()),
                   booked_taxes=booked.get('taxes', Decimal()),
                   booked_solidarity_surcharge=booked.get('solidarity_surcharge', Decimal()),
                   manual_capital_income='', manual_taxes='', manual_solidarity_surcharge='',
                   manual_used_exemption='', note='')
        accounts.append(row)
        total = institutions[institution]
        total['accounts'] += 1; total['interest'] += row['interest']; total['dividends'] += row['dividends']
        total['interest_and_dividends'] += row['interest_and_dividends']
        total['capital_income'] += row['capital_income']; total['taxes'] += row['taxes']
        total['withholding_tax'] += row['withholding_tax']
        total['solidarity_surcharge'] += row['solidarity_surcharge']
        total['advance_tax_base'] += row['advance_tax_base']
        total['advance_tax_taxable'] += row['advance_tax_taxable']
        total['advance_tax_count'] += row['advance_tax_count']
        total['partial_exemption'] += row['partial_exemption']
        total['used_exemption'] += row['used_exemption']
        old = legacy[institution]
        old['exemption'] += _number(manual.get('exemption') if manual.get('exemption') not in (None, '')
                                    else details.get('exemption'))
        old['capital_income'] += (_number(manual['capital_income']) if manual.get('capital_income') not in (None, '')
                                  else row['capital_income'])
        old['taxes'] += (_number(manual['taxes']) if manual.get('taxes') not in (None, '') else row['taxes'])
        old['solidarity_surcharge'] += (_number(manual['solidarity_surcharge'])
            if manual.get('solidarity_surcharge') not in (None, '') else row['solidarity_surcharge'])
        old['partial_exemption'] += (_number(manual['partial_exemption'])
            if manual.get('partial_exemption') not in (None, '') else row['partial_exemption'])
        old['used_exemption'] += (_number(manual['used_exemption'])
            if manual.get('used_exemption') not in (None, '') else row['used_exemption'])
        if manual.get('note'): old['notes'].append(manual['note'])
    for institution, total in institutions.items():
        saved = institution_saved.get(institution.casefold())
        fallback = legacy[institution]
        def selected(field, automatic_value=Decimal()):
            if saved is not None:
                return (_number(saved[field]) if saved.get(field) not in (None, '') else automatic_value)
            return fallback[field]
        booked_capital, booked_taxes = total['capital_income'], total['taxes']
        booked_solidarity = total['solidarity_surcharge']
        total['exemption'] = selected('exemption')
        total['capital_income'] = selected('capital_income', booked_capital)
        total['taxes'] = selected('taxes', booked_taxes)
        total['solidarity_surcharge'] = selected('solidarity_surcharge', booked_solidarity)
        booked_partial = total['partial_exemption']
        booked_used = total['used_exemption']
        total['partial_exemption'] = selected('partial_exemption', booked_partial)
        calculated_used = min(total['exemption'], max(Decimal(), total['capital_income'] - total['partial_exemption']))
        total['used_exemption'] = selected('used_exemption', booked_used or calculated_used)
        total['remaining_exemption'] = max(Decimal(), total['exemption'] - total['used_exemption'])
        total.update(booked_capital_income=booked_capital, booked_taxes=booked_taxes,
                     booked_solidarity_surcharge=booked_solidarity,
                     manual_capital_income=saved.get('capital_income', '') if saved else '',
                     manual_taxes=saved.get('taxes', '') if saved else '',
                     manual_solidarity_surcharge=saved.get('solidarity_surcharge', '') if saved else '',
                     manual_used_exemption=saved.get('used_exemption', '') if saved else '',
                     note=saved.get('note', '') if saved else ' · '.join(fallback['notes']))
    return sorted(accounts, key=lambda row: (row['institution'].casefold(), row['account'].casefold())), dict(institutions)


def _money(value):
    return f'{value:,.2f}'.replace(',', 'X').replace('.', ',').replace('X', '.')


class TaxOverviewDialog(QDialog):
    def __init__(self, repository, parent=None):
        super().__init__(parent)
        self.repository = repository
        self.setWindowTitle('Freistellungsaufträge, Kapitalerträge und Steuern')
        self.resize(1150, 720)
        root = QVBoxLayout(self)
        bar = QHBoxLayout(); bar.addWidget(QLabel('Steuerjahr'))
        self.year = QSpinBox(); self.year.setRange(1900, 9999); self.year.setValue(QDate.currentDate().year())
        self.year.valueChanged.connect(self.refresh); bar.addWidget(self.year); bar.addStretch()
        root.addLayout(bar)
        hint = QLabel('Freistellungsauftrag und manuelle Jahreswerte werden je Institut erfasst. Leere Felder für '
                      'Kapitalerträge und Steuern verwenden automatisch die Buchungen aller zugehörigen Konten. '
                      'Vorabpauschalen werden separat aus Steuermitteilungen ausgewiesen; nur der belegte '
                      'steuerpflichtige Verbrauch mindert den Freistellungsauftrag.')
        hint.setWordWrap(True); root.addWidget(hint)
        root.addWidget(QLabel('<b>Erfassung je Institut</b>'))
        self.institutions = QTableWidget(0, 17)
        self.institutions.setHorizontalHeaderLabels(('Institut', 'Konten', 'Freistellungsauftrag',
            'Zinsen / Dividenden gebucht', 'Vorabpauschale', 'davon steuerpflichtig',
            'Kapitalerträge gebucht', 'Kapitalerträge manuell', 'Steuern gebucht', 'Steuern manuell',
            'Soli gebucht', 'Soli manuell', 'Teilfreistellung', 'Verbraucht manuell',
            'Verbraucht', 'Verbleibend', 'Notiz'))
        self.institutions.setAlternatingRowColors(True); root.addWidget(self.institutions, 1)
        root.addWidget(QLabel('<b>Herkunft der automatisch ermittelten Werte</b>'))
        self.accounts = QTableWidget(0, 10)
        self.accounts.setHorizontalHeaderLabels(('Institut', 'Konto', 'Zinsen', 'Dividenden netto',
            'Vorabpauschale', 'davon steuerpflichtig', 'Kapitalerträge brutto', 'Steuern',
            'Quellensteuer', 'Solidaritätszuschlag'))
        self.accounts.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.accounts.setAlternatingRowColors(True); self.accounts.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        root.addWidget(self.accounts, 3)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        save = QPushButton('Eingaben speichern'); save.clicked.connect(self.save)
        buttons.addButton(save, QDialogButtonBox.ButtonRole.ActionRole); buttons.rejected.connect(self.reject)
        root.addWidget(buttons)
        self.refresh()

    def refresh(self, *_):
        self.rows, institutions = tax_overview(self.repository, self.year.value())
        self.institution_rows = sorted(institutions.items(), key=lambda item: item[0].casefold())
        self.institutions.setRowCount(len(institutions))
        for r, (name, values) in enumerate(self.institution_rows):
            row_values = (name, values['accounts'], _money(values['exemption']),
                _money(values['interest_and_dividends']), _money(values['advance_tax_base']),
                _money(values['advance_tax_taxable']), _money(values['booked_capital_income']),
                values['manual_capital_income'], _money(values['booked_taxes']), values['manual_taxes'],
                _money(values['booked_solidarity_surcharge']), values['manual_solidarity_surcharge'],
                _money(values['partial_exemption']), values['manual_used_exemption'],
                _money(values['used_exemption']), _money(values['remaining_exemption']), values['note'])
            for c, value in enumerate(row_values):
                item = QTableWidgetItem(str(value))
                if c not in (2, 7, 9, 11, 12, 13, 16):
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                if c == 2:
                    item.setText('' if not values['exemption'] else _money(values['exemption']))
                if c in (4, 5) and values['advance_tax_count']:
                    item.setToolTip(f"Aus {values['advance_tax_count']} importierten Steuermitteilung(en)")
                self.institutions.setItem(r, c, item)
            self.institutions.item(r, 0).setData(Qt.ItemDataRole.UserRole, name)
        self.accounts.setRowCount(len(self.rows))
        for r, row in enumerate(self.rows):
            values = (row['institution'], row['account'], _money(row['interest']), _money(row['dividends']),
                      _money(row['advance_tax_base']), _money(row['advance_tax_taxable']),
                      _money(row['booked_capital_income']), _money(row['booked_taxes']),
                      _money(row['withholding_tax']), _money(row['booked_solidarity_surcharge']))
            for c, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                self.accounts.setItem(r, c, item)
        self.institutions.resizeColumnsToContents(); self.accounts.resizeColumnsToContents()
        self.accounts.horizontalHeader().setStretchLastSection(True)

    def save(self):
        try:
            for r in range(self.institutions.rowCount()):
                self.repository.save_institution_tax_record(
                    self.institutions.item(r, 0).data(Qt.ItemDataRole.UserRole), self.year.value(),
                    self.institutions.item(r, 2).text(), self.institutions.item(r, 7).text(),
                    self.institutions.item(r, 9).text(), self.institutions.item(r, 12).text(),
                    self.institutions.item(r, 13).text(), self.institutions.item(r, 11).text(),
                    self.institutions.item(r, 16).text())
        except ValueError as error:
            QMessageBox.warning(self, 'Steuerdaten prüfen', str(error)); return
        self.refresh()
