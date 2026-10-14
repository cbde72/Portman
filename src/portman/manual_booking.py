"""Prepare auditable manual cash and security movements as one import batch."""
from PySide6.QtCore import QUuid
from portfolio_v5.accounts import account_key
from portfolio_v5.models import BankTransaction, ImportBatch, Position, Snapshot, Decimal, correction_number, parse_date, valid_isin
from .cash_balance_reference import cash_anchor


def positive(value, label):
    parsed = correction_number(value)
    if parsed is None or Decimal(parsed) <= 0:
        raise ValueError(label + ' muss größer als null sein.')
    return Decimal(parsed)


def cash_transaction(repo, account, day, incoming, amount, note, external_id):
    value = positive(amount, 'Betrag')
    if value != value.quantize(Decimal('.01')):
        raise ValueError('Geldbeträge mit höchstens zwei Nachkommastellen angeben.')
    return BankTransaction(account, external_id, day, 'DEPOSIT' if incoming else 'WITHDRAWAL',
        str(value if incoming else -value), 'EUR', purpose=note,
        bank_reference=cash_anchor(repo, account, day))


def depot_positions(repo, account, source, day):
    selected = next((depot for depot in repo.depots()
                     if account_key(depot['depot_name']) == account_key(source)), None)
    if selected and (not selected['active'] or selected['account'] != account):
        raise ValueError('Das Depot gehört nicht zum ausgewählten Konto.')
    if selected is None and source != account:
        raise ValueError('Bitte ein vorhandenes Depot auswählen.')
    return [position for position in repo.holdings(day, account)
            if account_key(position['depot']) == account_key(source)]


def copy_position(position):
    return Position(**{field: position[field] for field in Position.__dataclass_fields__ if field in position})


def change_security_position(positions, security, name, units, price, day, incoming):
    old = next((p for p in positions if p['key'] == security or p.get('isin') == security), None)
    if old and old['currency'] != 'EUR':
        raise ValueError('Manuelle Wertpapierbuchungen unterstützen derzeit nur EUR-Bestände.')
    if old is None and not valid_isin(security):
        raise ValueError('Für ein neues Wertpapier bitte eine gültige ISIN angeben.')
    if old is None and not name.strip():
        raise ValueError('Bitte den Wertpapiernamen angeben.')
    if old and old['quantity'] is None:
        raise ValueError('Der bisherige Stückbestand ist unbekannt.')
    previous = Decimal(old['quantity']) if old else Decimal(0)
    remaining = previous + units if incoming else previous - units
    if remaining < 0:
        raise ValueError(f'Ausbuchung übersteigt den verfügbaren Bestand ({previous} Anteile).')
    unit_price = positive(price, 'Kurs') if price.strip() else (
        Decimal(old['value']) / previous if old and old.get('value') is not None and previous else None)
    if incoming and unit_price is None:
        raise ValueError('Bitte einen Bewertungskurs in EUR angeben.')
    key = old['key'] if old else security
    updated = [copy_position(p) for p in positions if p['key'] != key]
    if remaining:
        position = copy_position(old) if old else Position(key, name.strip(), isin=security)
        position.quantity = str(remaining)
        position.value = str((unit_price * remaining).quantize(Decimal('.01'))) if unit_price is not None else None
        position.cost = None
        if not incoming and old.get('cost') is not None:
            position.cost = str(Decimal(old['cost']) * remaining / previous)
        if price.strip():
            position.quote_date = day
        updated.append(position)
    value = (units * unit_price).quantize(Decimal('.01')) if unit_price is not None else Decimal(0)
    return updated, key, value


def prepare_booking(repo, account, day, mode, direction, amount='', depot='', security='', name='', quantity='', price='', note=''):
    record = next((r for r in repo.account_records() if r['active'] and r['name'] == account), None)
    if record is None:
        raise ValueError('Bitte ein aktives Konto auswählen.')
    if not parse_date(day) or parse_date(day) != day:
        raise ValueError('Bitte ein gültiges Buchungsdatum angeben.')
    if direction not in ('in', 'out') or mode not in ('cash', 'security'):
        raise ValueError('Ungültige Buchungsart.')
    if not note.strip():
        raise ValueError('Bitte einen Buchungstext angeben.')
    token = QUuid.createUuid().toString(QUuid.StringFormat.WithoutBraces)
    batch = ImportBatch('Manuelle Buchung · ' + token, token, source_sheet='Manuelle Buchung', document_type='Manuelle Buchung')
    incoming = direction == 'in'
    if mode == 'cash':
        batch.transactions.append(cash_transaction(repo, account, day, incoming, amount, note.strip(), 'manual:' + token))
        source = account
    else:
        source = depot or account
        positions = depot_positions(repo, account, source, day)
        units = positive(quantity, 'Anteile')
        updated, key, value = change_security_position(positions, security, name, units, price, day, incoming)
        batch.snapshots.append(Snapshot(source, day[:7], day, 'Manuelle Buchung', updated, complete=True))
        batch.transactions.append(BankTransaction(source, 'manual:' + token, day,
            'TRANSFER_IN' if incoming else 'TRANSFER_OUT', str(value if incoming else -value), 'EUR',
            security=key, quantity=str(units), purpose=note.strip(), affects_cash=False))
    batch.account_assignments[account_key(source)] = record['account_key']
    return batch


def save_booking(repo, **values):
    batch = prepare_booking(repo, **values)
    result = repo.commit_batches([batch])[0]
    if result['status'] != 'imported':
        raise ValueError('; '.join(result.get('errors', ['Buchung konnte nicht gespeichert werden.'])))
    return result
