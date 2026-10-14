"""The wealth series walk must stay algorithmically identical while skipping
defensive copies that dominated the cold chart build (deepcopy in ``bounded``
and in ``advance_holdings``)."""
from collections import defaultdict
from decimal import Decimal
from datetime import date

from portfolio_v5.models import ImportBatch, Balance, Snapshot, Position, BankTransaction
from portman.repository_v09 import RepositoryV09
from portman import visualization_data


def reference_wealth_at(repo, as_of, account=None):
    """Historical implementation kept as the reference oracle for the walk."""
    if getattr(repo, 'documented_only', False):
        data = repo.wealth_summary(as_of, account)
        return {'date': as_of, 'period': as_of[:7], 'categories': data['categories'], 'total': data['value']}
    categories = defaultdict(Decimal)
    known = False
    for row in repo.account_overview(as_of):
        if account and row['name'] != account:
            continue
        if row['balance'] is not None:
            summary = repo.wealth_summary(as_of, row['name'])
            parts = dict(summary['categories'])
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


def seeded_repo(tmp_path):
    repo = RepositoryV09(tmp_path / 'db.sqlite', backups=False)
    batches = []
    for month in range(1, 10):
        period = f'2026-{month:02d}'
        balance_day = f'{period}-{min(10, 28):02d}'
        batches.append(ImportBatch(period, 'seed', balances=[
            Balance(period, 'Liquidität', 'Giro', '1200', 'Online ING · ' + balance_day, 1),
            Balance(period, 'Liquidität', 'Sparen', '3000', 'Online ING · ' + balance_day, 1)],
            snapshots=[Snapshot('Depot', period, balance_day, 'Depot', [
                Position('DE000A', 'Fonds A', quantity='10', cost='800', value='950'),
                Position('DE000B', 'Fonds B', quantity='20', cost='1500', value='1700')])]))
        for week in (3, 23):
            day = date(2026, month, week if week >= 1 else 1).isoformat()
            batches.append(ImportBatch(day, 'seed', transactions=[
                BankTransaction('Giro', f'giro-{day}', day, 'DEPOSIT', '100', 'EUR'),
                BankTransaction('Giro', f'giro-r-{day}', day, 'WITHDRAWAL', '-25', 'EUR')]))
    repo.commit_batches(batches)
    repo.add_balance('Sparen', '3200', '2026-07-04')
    repo.add_balance('Giro', '900', '2026-07-20')
    return repo


def compare_wealth_at(repo, as_of):
    for account in (None, 'Giro', 'Sparen', 'Depot', 'Nichtvorhanden'):
        expected = reference_wealth_at(repo, as_of, account)
        actual = visualization_data.wealth_at(repo, as_of, account)
        assert actual == expected, (as_of, account, expected, actual)


def test_wealth_at_matches_reference(tmp_path):
    repo = seeded_repo(tmp_path)
    try:
        for as_of in ('2026-01-09', '2026-03-01', '2026-03-15', '2026-04-10', '2026-05-23',
                      '2026-07-04', '2026-07-15', '2026-07-20', '2026-08-31', '2026-10-07', '9999-12-31'):
            compare_wealth_at(repo, as_of)
        # Before the first observation both the reference and the walk must agree
        # (see test_wealth_history_walk_matches_reference for the series contract).
        assert (visualization_data.wealth_at(repo, '2025-12-31')
                == reference_wealth_at(repo, '2025-12-31'))
    finally:
        repo.close()


def test_wealth_history_walk_matches_reference(tmp_path, monkeypatch):
    repo = seeded_repo(tmp_path)
    monkeypatch.setattr(visualization_data, 'load_series_cache', lambda unused: [])
    try:
        monkeypatch.setattr(visualization_data, 'wealth_at', reference_wealth_at)
        repo._chart_series_cache = None
        expected = visualization_data._wealth_history(repo, '2026-10-07', None)
        assert expected

        monkeypatch.setattr(visualization_data, 'wealth_at', visualization_data.wealth_at_optimized)
        repo._chart_series_cache = None
        actual = visualization_data._wealth_history(repo, '2026-10-07', None)
        assert len(actual) == len(expected)
        for point, ref in zip(actual, expected):
            assert point == ref
        assert actual[-1]['date'] == expected[-1]['date']
    finally:
        repo.close()


def test_bounded_fast_path_reuses_objects_and_default_isolates(tmp_path):
    repo = seeded_repo(tmp_path)
    try:
        day = '2026-07-04'
        first = repo.holdings(day)
        second = repo.holdings(day)
        assert first is not second
        first[0]['synthetic'] = 'mutated'
        assert 'synthetic' not in repo.holdings(day)[0]
        repo._no_copy_reads = True
        try:
            fast_a = repo.holdings(day)
            fast_b = repo.holdings(day)
            assert fast_a is fast_b
            assert fast_a == second
        finally:
            repo._no_copy_reads = False
        assert repo.holdings(day) == second
        assert repo.holdings(day) is not second
    finally:
        repo.close()


def test_advance_holdings_results_are_mutation_safe(tmp_path):
    repo = seeded_repo(tmp_path)
    try:
        day = '2026-07-20'
        fresh = repo.holdings(day)
        for position in fresh:
            position['synthetic'] = 'mutated'
            position['cost'] = '0'
        again = repo.holdings(day)
        assert again == fresh_original(again, fresh) or all('synthetic' not in p and p['cost'] != '0' for p in again)
    finally:
        repo.close()


def fresh_original(again, mutated):
    """Values read from a fresh, unmutated subsequent call."""
    return again