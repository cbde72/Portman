"""Chart observations using the same carried-forward values as account overview."""
from collections import defaultdict
from datetime import date
from decimal import Decimal
from portfolio_v5.accounts import account_key
from .chart_cache import (cached_series, _dump_series, _load_series,
                          load_series_cache, prepare_series_cache_entry, save_series_cache)


def wealth_at(repo, as_of, account=None):
    if getattr(repo, 'documented_only', False):
        data = repo.wealth_summary(as_of, account)
        return {'date': as_of, 'period': as_of[:7], 'categories': data['categories'], 'total': data['value']}
    categories = defaultdict(Decimal)
    by_account = defaultdict(list)
    for row in repo.wealth_summary(as_of)['rows']:
        by_account[account_key(row['account'])].append(row)
    known = False
    for row in repo.account_overview(as_of):
        if account and row['name'] != account:
            continue
        if row['balance'] is not None:
            parts = defaultdict(Decimal)
            for item in by_account[account_key(row['name'])]:
                parts[item['category']] += Decimal(item['value']) * (-1 if item['category'] == 'Schulden' else 1)
            if row['categories'].startswith('Wertpapiere ·'):
                parts = {'Wertpapiere': row['balance']}
            for category, value in parts.items():
                categories[category] += value
            known = True
        elif row['depot_value'] is not None:
            categories['Wertpapiere'] += row['depot_value']
            known = True
    return {'date': as_of, 'period': as_of[:7], 'categories': dict(categories),
            'total': sum(categories.values(), Decimal(0)) if known else None}


wealth_at_optimized = wealth_at


def wealth_history(repo, as_of, account=None):
    key = ('wealth', as_of, account, date.today().isoformat(), getattr(repo, 'documented_only', False))
    return cached_series(repo, key, lambda: _wealth_history(repo, as_of, account))


def _wealth_history(repo, as_of, account=None):
    latest = as_of == '9999-12-31'
    if latest: as_of = date.today().isoformat()
    entry = prepare_series_cache_entry(repo, as_of, account, getattr(repo, 'documented_only', False))
    if not repo.db.in_transaction and not getattr(repo, 'chart_cancelled', lambda: False)():
        for cached in load_series_cache(repo):
            if (cached.get('revision') == entry['revision'] and cached.get('as_of') == entry['as_of']
                    and cached.get('account') == entry['account'] and cached.get('documented') == entry['documented']
                    and cached.get('today') == entry['today']):
                rows = cached.get('series')
                if isinstance(rows, list):
                    return _load_series(rows)
    days = {as_of}
    observed = set()
    for row in repo.state_history(account):
        if row['active']:
            stamp = row['date'] + '-01' if len(row['date']) == 7 else row['date']
            days.add(stamp)
            observed.add(stamp)
    active = {r['account_key'] for r in repo.account_records() if r['active'] and (not account or r['name'] == account)}
    for row in repo._balance_observations():
        if not account or row['account'] == account:
            # Balance observations expose their booking date as
            # ``effective_date`` (snapshots and transactions use ``date``).
            # Using the latter here made a cold chart build fail at startup.
            balance_date = row['effective_date']
            days.add(balance_date)
            if account_key(row['account']) in active: observed.add(balance_date)
    for row in repo.transactions():
        if not account or row['account'] == account:
            days.add(row['date'])
            if account_key(row['account']) in active: observed.add(row['date'])
    for row in getattr(repo, 'import_links', lambda: ())():
        if not account or row['account'] == account:
            link_date = row['date']
            if link_date.startswith('SPLIT') or row['type'] in ('TRADE', 'DIV', 'FX', 'COST'):
                days.add(link_date)
    # Month-end boundaries make carried balances visible across gaps between
    # observations (e.g. a monthly cash balance that is not renewed every month).
    from calendar import monthrange
    starts = [value for value in days if value != as_of]
    if starts:
        first = min(starts)
        year, month = (int(part) for part in first[:7].split('-'))
        while True:
            boundary = f'{year:04d}-{month:02d}-{monthrange(year, month)[1]:02d}'
            if boundary > as_of:
                break
            if boundary >= first:
                days.add(boundary)
            month += 1
            if month > 12:
                year, month = year + 1, 1
    days = sorted(days)
    series = []
    if entry['revision'] == 0: return series
    repo._no_copy_reads = True
    try:
        for day in days:
            if day > as_of: continue
            if day not in observed and day != as_of and len(series) >= 1:
                # Month-end boundary between observations: no active account has
                # new data on this day, so the carried value is unchanged. Carry
                # directly instead of calling wealth_at again (monthly carry).
                series.append({'date': day, 'period': day[:7], 'categories': series[-1]['categories'].copy(), 'total': series[-1]['total']})
                continue
            point = wealth_at(repo, day, account)
            if point['total'] is None and day not in observed and len(series) >= 1:
                series.append({'date': day, 'period': point['period'], 'categories': series[-1]['categories'].copy(), 'total': series[-1]['total']})
                continue
            series.append(point)
    finally:
        repo._no_copy_reads = False
    if not repo.db.in_transaction and not getattr(repo, 'chart_cancelled', lambda: False)():
        save_series_cache(repo, {**entry, 'series': _dump_series(series)})
    return series
