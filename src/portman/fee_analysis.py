"""Auditable, bank-independent analysis of imported transaction fees."""
import csv
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path


FEE_LABELS = {
    'provision': 'Provision', 'orderentgelt': 'Orderentgelt',
    'handelsplatzgebuehr': 'Handelsplatzgebühr', 'handelsplatzentgelt': 'Handelsplatzgebühr',
    'fremdspesen': 'Fremdspesen', 'transaktionsentgelt': 'Transaktionsentgelt',
    'entgelt': 'Entgelt',
    'mindermengenzuschlag': 'Mindermengenzuschlag',
}


def _decimal(value):
    try:
        result = Decimal(str(value))
        return result if result.is_finite() else None
    except (InvalidOperation, TypeError, ValueError):
        return None


def _bank(repo, tx):
    account = tx.get('depot') or tx.get('account') or ''
    record = next((row for row in repo.account_records()
                   if row['name'] in (account, tx.get('cash_account'))), None)
    if record:
        import json
        details = json.loads(record['details'])
        if details.get('bank_name'): return details['bank_name']
    return account.split()[0] if account else 'Unbekannt'


def _security(repo, identifier):
    value = str(identifier or '').removeprefix('ISIN:')
    for key, record in repo.metadata().items():
        if value in (key, record.get('isin'), record.get('wkn')):
            return record.get('canonical_name') or value, record.get('isin') or '', record.get('wkn') or ''
    return value, value if len(value) == 12 else '', value if len(value) == 6 else ''


def fee_rows(repo):
    """One row per documented fee component; unknown and conflicts stay visible."""
    from .repository_v09 import reference
    fee_link_reader = getattr(repo, 'fee_links', None)
    linked = ({(row['aux_ref'], row['field']) for row in fee_link_reader()}
              if fee_link_reader else set())
    cash_matches = {}
    try:
        import json
        reconcile = getattr(repo, 'reconcile_depot_bookings', None)
        depot_keys = [record['account_key'] for record in repo.account_records()
                      if json.loads(record['details']).get('kind') == 'Depot']
        for depot_key in depot_keys if reconcile else ():
            for match in reconcile(depot_key, persist=False):
                cash_matches[reference(match['transaction'])] = match['status']
    except (AttributeError, ValueError):
        pass
    rows, seen = [], set()
    for tx in repo.transactions():
        if tx.get('kind') not in ('BUY', 'SELL'): continue
        identity = (tx.get('order_id') or tx.get('document_reference') or tx.get('transaction_reference'),
                    tx['date'], tx.get('security'), tx.get('amount'), tx.get('currency'), tx.get('depot') or tx.get('account'))
        if identity[0] and identity in seen:
            continue
        seen.add(identity)
        name, isin, wkn = _security(repo, tx.get('security'))
        gross, fees, taxes = map(_decimal, (tx.get('gross_amount'), tx.get('fees'), tx.get('taxes')))
        settlement = _decimal(tx.get('amount'))
        settlement = abs(settlement) if settlement is not None else None
        expected = None
        if None not in (gross, fees, settlement):
            tax = taxes or Decimal()
            expected = gross + fees + tax if tx['kind'] == 'BUY' else gross - fees - tax
        reconciliation = ('unbekannt' if expected is None else
                          'plausibel' if abs(expected - settlement) <= Decimal('0.01') else 'widersprüchlich')
        items = tx.get('fee_items') or []
        if not items and fees is not None:
            items = [{'kind': 'entgelt', 'amount': str(fees)}]
        status = ('unbekannt' if fees is None else 'nachgewiesen 0,00 €' if fees == 0
                  else 'widersprüchlich' if reconciliation == 'widersprüchlich' else 'nachgewiesen')
        if not items:
            items = [{'kind': '', 'amount': None}]
        for item in items:
            kind = item.get('kind', '') if isinstance(item, dict) else item.kind
            amount = item.get('amount') if isinstance(item, dict) else item.amount
            rows.append(dict(date=tx['date'], year=tx['date'][:4], bank=_bank(repo, tx),
                depot=tx.get('depot') or tx.get('account', ''), security=name, isin=isin, wkn=wkn,
                fee_type=FEE_LABELS.get(str(kind).casefold(), kind or 'Unbekannt'), amount=amount,
                currency=tx.get('currency', ''), status=status, reconciliation=reconciliation,
                market_value=str(gross) if gross is not None else None,
                taxes=str(taxes) if taxes is not None else None,
                settlement=str(settlement) if settlement is not None else None,
                transaction_id=tx.get('external_id', ''), import_id=tx.get('import_id'),
                cash_match=cash_matches.get(reference(tx), 'Nicht geprüft'),
                separate_fee_linked=(reference(tx), 'fees') in linked))
    return rows


def fee_summary(rows, fields=('year', 'bank', 'depot', 'security', 'fee_type')):
    result = defaultdict(lambda: {'amount': Decimal(), 'count': 0, 'unknown': 0, 'conflicts': 0})
    for row in rows:
        key = tuple(row[field] for field in fields)
        entry = result[key]; entry['count'] += 1
        amount = _decimal(row['amount'])
        if amount is None: entry['unknown'] += 1
        else: entry['amount'] += amount
        if row['status'] == 'widersprüchlich': entry['conflicts'] += 1
    return [{**dict(zip(fields, key)), **value, 'amount': str(value['amount'])}
            for key, value in sorted(result.items())]


EXPORT_COLUMNS = ('year','bank','depot','security','isin','wkn','fee_type','amount','currency','status','cash_match',
                  'reconciliation','market_value','taxes','settlement','date','transaction_id','import_id')


def export_fees(rows, path):
    path = Path(path)
    if path.suffix.casefold() == '.xlsx':
        from openpyxl import Workbook
        book = Workbook(); sheet = book.active; sheet.title = 'Gebühren'
        sheet.append(list(EXPORT_COLUMNS))
        for row in rows: sheet.append([row.get(column) for column in EXPORT_COLUMNS])
        sheet.freeze_panes = 'A2'; sheet.auto_filter.ref = sheet.dimensions
        book.save(path)
    else:
        with path.open('w', newline='', encoding='utf-8-sig') as handle:
            writer = csv.DictWriter(handle, fieldnames=EXPORT_COLUMNS, extrasaction='ignore', delimiter=';')
            writer.writeheader(); writer.writerows(rows)
