"""Reuse balance summaries between observations in a chart worker."""
from bisect import bisect_right
from portfolio_v5.accounts import account_key


def _copy_summary(value):
    """Cheap structural copy of a wealth_summary result (deepcopy was the hotspot)."""
    return {**value, 'categories': dict(value['categories']),
            'rows': [dict(row) for row in value['rows']],
            'dates': list(value['dates']), 'sources': list(value['sources'])}


def reuse_chart_balances(repo):
    original = repo.wealth_summary
    events = None
    cache = {}

    def summary(as_of='9999-12-31', account=None):
        nonlocal events
        if events is None:
            events = {}
            for row in repo.store._balance_observations():
                events.setdefault(account_key(row['account']), set()).add(row['effective_date'])
            for row in repo.db.execute('SELECT account_key,effective_date FROM manual_balances'):
                events.setdefault(row['account_key'], set()).add(row['effective_date'])
            events[None] = {day for days in events.values() for day in days}
            events = {key: sorted(days) for key, days in events.items()}
        days = events.get(account_key(account) if account is not None else None, ())
        index = bisect_right(days, as_of)
        effective = days[index - 1] if index else '0001-01-01'
        key = (effective, account)
        if key not in cache:
            value = original(effective, account)
            if len(cache) >= 128:
                cache.pop(next(iter(cache)))
            cache[key] = value
        return _copy_summary(cache[key])

    repo.wealth_summary = summary


def reuse_chart_balances_at(repo):
    """balances_at(as_of) is piecewise constant between observation dates.

    Memoize the result for the last observation day <= as_of, so a chart that
    iterates every observed day does not rebuild the same selection repeatedly.
    """
    original = repo.store.balances_at
    events = None
    cache = {}

    def balances_at(as_of='9999-12-31'):
        nonlocal events
        if events is None:
            events = sorted({row['effective_date'] for row in repo.store._balance_observations()})
        index = bisect_right(events, as_of)
        effective = events[index - 1] if index else '0001-01-01'
        if effective not in cache:
            if len(cache) >= 1024:
                cache.pop(next(iter(cache)))
            cache[effective] = original(as_of=effective)
        return [dict(balance) for balance in cache[effective]]

    repo.store.balances_at = balances_at
