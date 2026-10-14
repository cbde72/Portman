"""Explain observed changes without inventing classifications for bank bookings."""
from collections import defaultdict
from decimal import Decimal

ZERO = Decimal(0)


def change_analysis(repo, start, end, account=None):
    if start >= end:
        raise ValueError('Der Beginn muss vor dem Ende liegen.')
    first = {(p['depot'], p['key']): p for p in repo.holdings(start, account)}
    last = {(p['depot'], p['key']): p for p in repo.holdings(end, account)}
    txs = [t for t in repo.transactions(account) if start < t['date'] <= end]
    movements = defaultdict(lambda: ZERO)
    cash = defaultdict(lambda: ZERO)
    unknown = []
    for tx in txs:
        if tx['kind'] in ('BUY', 'SELL', 'TRANSFER_IN', 'TRANSFER_OUT'):
            if tx.get('quantity') is None or not tx.get('security'):
                unknown.append(tx)
            else:
                sign = -1 if tx['kind'] in ('SELL', 'TRANSFER_OUT') else 1
                movements[(tx.get('depot', tx['account']), tx['security'])] += sign * abs(Decimal(tx['quantity']))
        if tx['currency'] != 'EUR':
            unknown.append(tx)
            continue
        cash[tx['kind']] += Decimal(tx['amount'])
    positions = []
    snapshots = list(repo.snapshots(account))
    snapshots_by_depot = defaultdict(list)
    for snapshot in snapshots:
        snapshots_by_depot[snapshot['depot']].append(snapshot)
    complete = bool(account and repo.has_coverage(account, start, end))
    for key in sorted(first.keys() | last.keys() | movements.keys()):
        a, b = first.get(key), last.get(key)
        qa = Decimal(a['quantity']) if a and a.get('quantity') is not None else (None if a else ZERO)
        qb = Decimal(b['quantity']) if b and b.get('quantity') is not None else (None if b else ZERO)
        va, vb = Decimal(a['value']) if a else ZERO, Decimal(b['value']) if b else ZERO
        difference = None if qa is None or qb is None else qb - qa - movements[key]
        # An absent position is a proven zero only if all relevant depot states are complete.
        depot_snaps = snapshots_by_depot.get(key[0], ())
        boundaries = []
        for day in (start, end):
            snaps = [s for s in depot_snaps if s['effective_date'] <= day]
            boundaries.append(bool(snaps and snaps[-1]['complete'] and snaps[-1]['as_of'] == day))
        verified = complete and all(boundaries) and not unknown
        status = ('Abweichung' if difference else 'Rechnerisch passend') if difference is not None else 'Stückzahl fehlt'
        if not verified:
            status += ' · Nachweise unvollständig'
        # Fixed opening units isolate the price effect; the remainder contains quantity changes.
        price_effect = qa * (vb / qb - va / qa) if qa and qb else None
        positions.append({'depot': key[0], 'key': key[1], 'name': (b or a or {}).get('name', key[1]),
                          'before': va, 'after': vb, 'change': vb - va,
                          'opening_units': qa, 'booked_units': movements[key], 'closing_units': qb,
                          'difference': difference, 'status': status, 'price_effect': price_effect,
                          'source_before': (a or {}).get('source', ''), 'source_after': (b or {}).get('source', '')})
    accounts = []
    for name in ([account] if account else repo.accounts()):
        a, b = repo.wealth_summary(start, name), repo.wealth_summary(end, name)
        accounts.append({'account': name, 'before': a['value'], 'after': b['value'],
                         'change': b['value'] - a['value'] if a['value'] is not None and b['value'] is not None else None})
    a, b = repo.wealth_summary(start, account), repo.wealth_summary(end, account)
    categories = [{'category': c, 'before': a['categories'].get(c, ZERO), 'after': b['categories'].get(c, ZERO)}
                  for c in sorted(a['categories'].keys() | b['categories'].keys())]
    delta = b['value'] - a['value'] if a['value'] is not None and b['value'] is not None else None
    # BUY/SELL are internal reallocations of total wealth; BANK_BOOKING is unclassified.
    explained = {k: cash[k] for k in ('DEPOSIT', 'WITHDRAWAL', 'DIVIDEND', 'INTEREST', 'FEE', 'TAX')}
    residual = delta - sum(explained.values(), ZERO) if delta is not None else None
    return {'positions': positions, 'accounts': accounts, 'categories': categories,
            'change': delta, 'explained': explained, 'residual': residual, 'transactions': txs,
            'unclassified': sum(t['kind'] == 'BANK_BOOKING' for t in txs), 'unknown': len(unknown)}
