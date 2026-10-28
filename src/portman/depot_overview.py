"""Read-only per-security depot activity aggregation."""

from collections import defaultdict
from decimal import Decimal, InvalidOperation

from portfolio_v5.accounts import account_key
from portman.analysis_v09 import realized_profit

ZERO = Decimal('0')
ADVANCE_TYPES = {'vorabpauschale', 'vorabpauschale_ausland'}


def number(value):
    try:
        return Decimal(str(value or 0))
    except (InvalidOperation, ValueError):
        return ZERO


def security_identity(repo, value):
    raw = str(value or '').strip()
    if not raw:
        return '__unassigned__'
    row = repo.db.execute(
        'SELECT security_key,isin,wkn,canonical_name FROM security_master '
        'WHERE security_key=? OR isin=? OR wkn=?', (raw, raw, raw)).fetchone()
    return (row['isin'] or row['security_key']) if row else raw


def _tax_components(tx):
    total = abs(number(tx.get('taxes')))
    solidarity = abs(number(tx.get('solidarity_tax')))
    withholding = abs(number(tx.get('withholding_tax')))
    church = ZERO
    for item in tx.get('tax_items') or []:
        item = vars(item) if not isinstance(item, dict) else item
        kind = str(item.get('kind') or '').casefold()
        if 'kirch' in kind or 'church' in kind:
            church += abs(number(item.get('amount')))
    capital = max(ZERO, total - solidarity - withholding - church)
    return capital, solidarity, church, withholding, total


def _trade_value(tx):
    documented = tx.get('gross_amount')
    if documented not in (None, ''):
        return abs(number(documented))
    amount = abs(number(tx.get('amount')))
    fees, taxes = abs(number(tx.get('fees'))), abs(number(tx.get('taxes')))
    return max(ZERO, amount - fees - taxes) if tx.get('kind') == 'BUY' else amount + fees + taxes


def aggregate_depot(repo, depot, start, end):
    """Aggregate all facts with one read per source collection, never per position."""
    records = {r['account_key']: r for r in repo.account_records() if r['active']}
    selected_key = account_key(depot) if depot else None
    aliases = {account_key(r['name']): key for key, r in records.items()}

    def belongs(tx):
        if selected_key is None:
            return True
        keys = {account_key(tx.get('performance_depot_key') or ''),
                account_key(tx.get('depot') or ''), account_key(tx.get('account') or '')}
        keys |= {aliases.get(key, key) for key in tuple(keys)}
        return selected_key in keys

    transactions = [dict(tx) for tx in repo.transactions()
                    if start <= tx.get('date', '') <= end and belongs(tx)]
    holdings = repo.holdings(end, depot) if depot else repo.holdings(end)
    fifo = realized_profit(repo, '0001-01-01', end, depot)
    fifo_period = [row for row in fifo if start <= row['date'] <= end]
    metadata = repo.metadata()
    security_aliases = {}
    for record in repo.db.execute(
            'SELECT security_key,isin,wkn,canonical_name FROM security_master'):
        canonical = record['isin'] or record['security_key']
        for alias in (record['security_key'], record['isin'], record['wkn']):
            if alias:
                security_aliases[str(alias)] = canonical
    buckets = defaultdict(lambda: {
        'name': '', 'identifier': '', 'quantity_end': ZERO,
        'buy_count': 0, 'buy_total': ZERO, 'sell_count': 0, 'sell_total': ZERO,
        'dividend_gross': ZERO, 'dividend_net': ZERO,
        'buy_fees': ZERO, 'sell_fees': ZERO, 'other_fees': ZERO,
        'capital_gains_tax': ZERO, 'solidarity_tax': ZERO, 'church_tax': ZERO,
        'withholding_tax': ZERO, 'tax_total': ZERO, 'realized_profit': ZERO,
        'realized_complete': True, 'net_cashflow': ZERO, 'transactions': [],
    })

    def bucket_for(value):
        raw = str(value or '').strip()
        identity = security_aliases.get(raw, raw or '__unassigned__')
        bucket = buckets[identity]
        bucket['identifier'] = '' if identity == '__unassigned__' else identity
        record = metadata.get(identity, {})
        bucket['name'] = (record.get('canonical_name') or record.get('name') or
                          ('Nicht zugeordnet' if identity == '__unassigned__' else value or identity))
        return identity, bucket

    for position in holdings:
        identity, bucket = bucket_for(position.get('isin') or position.get('key'))
        bucket['quantity_end'] += number(position.get('quantity'))
        if not bucket['name']:
            bucket['name'] = position.get('name') or identity

    for tx in transactions:
        identity, bucket = bucket_for(tx.get('security'))
        kind = tx.get('kind', '')
        amount, fees = number(tx.get('amount')), abs(number(tx.get('fees')))
        if kind == 'BUY':
            bucket['buy_count'] += 1; bucket['buy_total'] += _trade_value(tx)
            bucket['buy_fees'] += fees
        elif kind == 'SELL':
            bucket['sell_count'] += 1; bucket['sell_total'] += _trade_value(tx)
            bucket['sell_fees'] += fees
        elif fees:
            bucket['other_fees'] += fees
        if kind in ('DIVIDEND', 'DISTRIBUTION'):
            bucket['dividend_net'] += amount
            gross = tx.get('gross_income') or tx.get('gross_amount')
            bucket['dividend_gross'] += (abs(number(gross)) if gross not in (None, '')
                                          else amount + abs(number(tx.get('taxes'))) + fees)
        capital, solidarity, church, withholding, total = _tax_components(tx)
        bucket['capital_gains_tax'] += capital
        bucket['solidarity_tax'] += solidarity
        bucket['church_tax'] += church
        bucket['withholding_tax'] += withholding
        bucket['tax_total'] += total
        # Transaction.amount is the documented signed settlement total and
        # already contains fees/taxes where applicable. Never subtract twice.
        if tx.get('affects_cash', True):
            bucket['net_cashflow'] += amount
        tx['_security_identity'] = identity
        bucket['transactions'].append(tx)

    for row in fifo_period:
        _identity, bucket = bucket_for(row.get('security'))
        if row.get('realized') is None:
            bucket['realized_complete'] = False
        else:
            bucket['realized_profit'] += number(row['realized'])

    # Tax notices enrich component evidence only when they have no linked cash
    # booking. Exemptions and advance-tax bases are never cash outflows.
    transaction_ids = {tx.get('external_id') for tx in transactions}
    for event in repo.tax_events(depot):
        if not (start <= event.get('date', '') <= end):
            continue
        if event.get('related_transaction_id') in transaction_ids:
            continue
        paid = abs(number(event.get('paid_taxes')))
        if not paid:
            continue
        _identity, bucket = bucket_for(event.get('security_ref'))
        bucket['capital_gains_tax'] += paid
        bucket['tax_total'] += paid
        bucket['transactions'].append({
            'date': event.get('date', ''), 'kind': 'ADVANCE_TAX' if event.get('type') in ADVANCE_TYPES else 'TAX_NOTICE',
            'security': event.get('security_ref', ''), 'amount': '0', 'taxes': str(paid),
            'account': event.get('account', ''), 'source': event.get('source', ''),
            'external_id': event.get('external_id', ''), 'affects_cash': False,
        })

    rows = []
    for identity, bucket in buckets.items():
        bucket['fees_total'] = bucket['buy_fees'] + bucket['sell_fees'] + bucket['other_fees']
        bucket['active'] = bucket['quantity_end'] != 0
        bucket['key'] = identity
        rows.append(bucket)
    return sorted(rows, key=lambda row: (row['name'].casefold(), row['identifier']))


def depots(repo):
    result = []
    for record in repo.account_records():
        import json
        if record['active'] and json.loads(record.get('details') or '{}').get('kind') == 'Depot':
            result.append(record['name'])
    return sorted(result, key=str.casefold)
