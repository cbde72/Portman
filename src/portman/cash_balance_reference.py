"""Identify the balance observation underlying a manual same-day cash movement."""
from portfolio_v5.models import digest


def cash_anchor(repo, account, day):
    manual = [dict(row) for row in repo.balance_history(account) if row['effective_date'] == day]
    imported = [dict(row) for row in repo.store.balances_at(day)
                if row['account'] == account and row['effective_date'] == day]
    return 'manual-anchor:' + digest([manual, imported])
