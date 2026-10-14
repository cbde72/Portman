"""Reuse holdings between position events within one read-only chart request."""
from bisect import bisect_right


def reuse_chart_holdings(repo):
    original = repo.holdings
    original_transactions = repo.transactions
    transactions = None
    event_days = None
    cache = {}

    def txns(account=None):
        nonlocal transactions
        if account is not None:
            return original_transactions(account)
        if transactions is None:
            transactions = original_transactions(None)
        return transactions

    def holdings(as_of='9999-12-31', account=None):
        nonlocal event_days
        if event_days is None:
            days = {s['effective_date'] for s in repo.store.snapshots(include_hidden=True)}
            days.update(t['date'] for t in txns()
                        if t['external_id'].startswith('baader-trade-') and t['kind'] in ('BUY', 'SELL'))
            event_days = sorted(days)
        index = bisect_right(event_days, as_of)
        effective = event_days[index - 1] if index else '0001-01-01'
        key = (effective, account)
        if key not in cache:
            result = original(effective, account)
            if len(cache) >= 8:
                cache.pop(next(iter(cache)))
            cache[key] = result
        return [dict(position) for position in cache[key]]

    # Security movements re-read the full transaction list once per event day.
    # Within a read-only chart request the list is immutable, so share it instead
    # of copying several thousand rows per holdings computation.
    repo.transactions = txns
    repo.holdings = holdings
