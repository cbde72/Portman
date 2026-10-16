"""Money-weighted return on the SECURITY portfolio, excluding settlement cash.

Trade amounts are signed NET cash movements incl. fees/taxes. BUY is an
investor payment; SELL/dividends are receipts. Deposits/withdrawals between
bank and settlement account do not enter this security-only return.
"""
import math
from datetime import date
from decimal import Decimal

from .accounts import canonical_depot


def xirr(flows):
    combined = {}
    for d, amount in flows:
        combined[d] = combined.get(d, 0.0) + float(amount)
    ordered = sorted((date.fromisoformat(d), a) for d, a in combined.items() if a)
    if len(ordered) < 2 or ordered[0][0] == ordered[-1][0]:
        return None, 'Zu wenige datierte Zahlungsströme.'
    if not any(a < 0 for _, a in ordered) or not any(a > 0 for _, a in ordered):
        return None, 'Positive und negative Zahlungsströme erforderlich.'
    t0 = ordered[0][0]
    times = [((d - t0).days / 365.0, a) for d, a in ordered]
    scale = max(abs(a) for _, a in times)
    def npv(log_rate):
        try:
            return sum(a / scale * math.exp(-log_rate * t) for t, a in times)
        except OverflowError:
            return math.copysign(float('inf'), times[-1][1])
    roots = []
    # Search in log(1+r); multiple roots are rejected rather than silently chosen.
    grid = [-12 + i * .025 for i in range(961)]
    left, fl = grid[0], npv(grid[0])
    for right in grid[1:]:
        fr = npv(right)
        if fl == 0:
            roots.append(left)
        elif fl * fr < 0:
            lo, hi, flo = left, right, fl
            for _ in range(80):
                mid = (lo + hi) / 2
                fm = npv(mid)
                if flo * fm <= 0:
                    hi = mid
                else:
                    lo, flo = mid, fm
            roots.append((lo + hi) / 2)
        left, fl = right, fr
    unique = []
    for root in roots:
        if not any(abs(root - old) < 1e-7 for old in unique):
            unique.append(root)
    if len(unique) != 1:
        return None, 'Keine eindeutige Rendite im Suchbereich (-99,9994 % bis ca. 16 Mio. %).' 
    return math.expm1(unique[0]), None


def security_performance(store, account, start, end, after_taxes=False):
    if not account:
        return {'error': 'Für die Rendite ein einzelnes Depot wählen.'}
    if start >= end:
        return {'error': 'Beginn muss vor Ende liegen.'}
    if not store.has_coverage(account, start, end):
        return {'error': 'Vollständigkeit der Transaktionen für dieses Depot und diesen Zeitraum noch nicht bestätigt.'}
    snapshots = store.snapshots(account)
    depots = {canonical_depot(s.get('depot', s['account']))
              for s in snapshots if s['effective_date'] <= end}
    for boundary in (start, end):
        candidates = [s for s in snapshots if s['as_of'] == boundary and s['complete']]
        if not candidates or {canonical_depot(s.get('depot', s['account']))
                              for s in candidates} != depots:
            return {'error': f'Vollständiger, tagesgenauer Depotbestand am {boundary} fehlt.'}
    opening = sum(Decimal(p['value']) for p in store.holdings(start, account))
    closing = sum(Decimal(p['value']) for p in store.holdings(end, account))
    from .settlement import performance_transactions
    try:
        txs = performance_transactions(store, [t for t in store.transactions() if start < t['date'] <= end], account)
    except ValueError as error:
        return {'error': str(error)}
    if any(t['kind'] in ('TRANSFER_IN', 'TRANSFER_OUT') for t in txs):
        return {'error': 'Überträge im Zeitraum: Rendite gesperrt, bis Übertragswerte und Depotgrenzen abgestimmt sind.'}
    relevant = [t for t in txs if t['kind'] in ('BUY', 'SELL', 'DIVIDEND', 'INTEREST', 'FEE', 'TAX')]
    if any(t['currency'] != 'EUR' for t in relevant):
        return {'error': 'Zahlungsströme benötigen historische EUR-Werte.'}
    def security_amount(tx):
        amount = Decimal(tx['amount'])
        if after_taxes:
            return amount
        # PP treats investor-specific taxes as neutral for a security while
        # fees remain an intrinsic cost of buying, holding or selling it.
        if tx['kind'] == 'TAX':
            return Decimal(0)
        return amount + Decimal(tx.get('taxes') or 0)
    effective = [(t, security_amount(t)) for t in relevant]
    flows = [(start, -opening), *[(t['date'], amount) for t, amount in effective if amount], (end, closing)]
    rate, error = xirr(flows)
    receipts = sum((amount for _, amount in effective), Decimal(0))
    return {'opening': opening, 'closing': closing, 'net_cash_receipts': receipts,
            'profit': closing - opening + receipts,
            'xirr': rate, 'error': error, 'flows': flows,
            'after_taxes': after_taxes,
            'taxes_excluded': (Decimal(0) if after_taxes else
                sum((Decimal(t.get('taxes') or 0) for t in relevant), Decimal(0))
                + sum((-Decimal(t['amount']) for t in relevant if t['kind'] == 'TAX'), Decimal(0))),
            'dividends': sum((amount for t, amount in effective if t['kind'] == 'DIVIDEND'), Decimal(0))}
