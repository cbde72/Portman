"""Cumulative cash movements for repeated valuation dates."""
from bisect import bisect_right
from decimal import Decimal


def cash_timeline(transactions):
    days = sorted({tx['date'] for tx in transactions})
    amounts = dict.fromkeys(days, Decimal(0))
    manual = {}
    for tx in transactions:
        amounts[tx['date']] += Decimal(tx['amount'])
        if tx['external_id'].startswith('manual:'):
            manual.setdefault(tx['date'], []).append(tx)
    totals = [Decimal(0)]
    for day in days:
        totals.append(totals[-1] + amounts[day])
    return {'days': days, 'totals': totals, 'manual': manual}


def cash_through(timeline, day):
    index = bisect_right(timeline['days'], day)
    return timeline['totals'][index], timeline['days'][index - 1] if index else None
