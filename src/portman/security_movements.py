from portfolio_v5.accounts import account_key
from portfolio_v5.models import Decimal


def security_movements(transactions, positions):
    aliases = {}
    for p in positions:
        for identifier in (p['key'], p.get('isin'), 'ISIN:' + p['isin'] if p.get('isin') else '',
                           'WKN:' + p['wkn'] if p.get('wkn') else ''):
            if identifier:
                aliases.setdefault((account_key(p['depot']), identifier), set()).add((p['key'], p['currency']))
    result = []
    for tx in transactions:
        if tx['kind'] not in ('BUY', 'SELL') or not tx.get('security') or not tx.get('quantity'):
            continue
        quantity = Decimal(tx['quantity'])
        if not quantity.is_finite() or quantity <= 0:
            continue
        matches = aliases.get((account_key(tx['depot']), tx['security']), set())
        if matches:
            if len(matches) != 1:
                continue
            security, currency = next(iter(matches))
            if currency != tx['currency']:
                continue
            tx = {**tx, 'security': security}
        result.append(tx)
    return result
