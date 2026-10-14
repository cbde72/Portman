from portfolio_v5.models import ImportBatch, Balance, Snapshot, Position, BankTransaction
from portman.chart_reader import open_chart_reader
from portman.chart_data import prepare_chart
from portman.repository_v09 import RepositoryV09


def test_chart_matches_repository_across_balance_and_position_events(tmp_path):
    path = tmp_path / 'events.sqlite'
    repo = RepositoryV09(path, backups=False)
    reader = None
    try:
        repo.commit_batches([ImportBatch('events', 'events', balances=[
            Balance('2025-01', 'Liquidität', 'Cash', '100', 'Online ING · 2025-01-10', 1),
            Balance('2025-02', 'Liquidität', 'Cash', '300', 'Online ING · 2025-02-10', 2)],
            snapshots=[
                Snapshot('Depot', '2025-01', '2025-01-05', 'Test', [Position('A', 'A', quantity='2', value='40', cost='30')]),
                Snapshot('Depot', '2025-02', '2025-02-05', 'Test', [Position('A', 'A', quantity='3', value='60', cost='45')])],
            transactions=[
                BankTransaction('Cash', 'cash-1', '2025-01-11', 'DEPOSIT', '5', 'EUR'),
                BankTransaction('Depot', 'baader-trade-1', '2025-01-15', 'BUY', '10', 'EUR',
                                security='A', quantity='1', affects_cash=False)])])
        repo.add_balance('Cash', '180', '2025-01-20')
        reader = open_chart_reader(path, RepositoryV09, lambda: False)
        for account in (None, 'Cash', 'Depot'):
            for day in ('2024-12-31', '2025-01-05', '2025-01-09', '2025-01-10',
                        '2025-01-11', '2025-01-15', '2025-01-16', '2025-01-20',
                        '2025-02-06', '2025-02-10', '2025-02-20'):
                assert reader.holdings(day, account) == repo.holdings(day, account)
                assert reader.wealth_summary(day, account) == repo.wealth_summary(day, account)
            assert prepare_chart(reader, 0, '2025-02-20', account) == prepare_chart(repo, 0, '2025-02-20', account)
        # Rendering consumers must not change the cached records.
        reader.holdings('2025-02-20')[0]['value'] = '999'
        reader.wealth_summary('2025-02-20')['rows'][0]['value'] = '999'
        assert reader.holdings('2025-02-20') == repo.holdings('2025-02-20')
        assert reader.wealth_summary('2025-02-20') == repo.wealth_summary('2025-02-20')
    finally:
        if reader: reader.close()
        repo.close()


def test_cash_prefixes_preserve_anchors_and_external_invalidation(tmp_path):
    path = tmp_path / 'cash.sqlite'
    repo = RepositoryV09(path, backups=False)
    other = None
    try:
        repo.create_accounts(['Cash'])
        repo.add_balance('Cash', '100', '2025-01-10')
        repo.commit_batches([ImportBatch('cash', 'cash', transactions=[
            BankTransaction('Cash', 'before', '2025-01-05', 'DEPOSIT', '20', 'EUR'),
            BankTransaction('Cash', 'on', '2025-01-10', 'DEPOSIT', '9', 'EUR'),
            BankTransaction('Cash', 'after', '2025-01-11', 'WITHDRAWAL', '-7.25', 'EUR')])])
        def balance(day):
            return next(r['balance'] for r in repo.account_overview(day) if r['name'] == 'Cash')
        from decimal import Decimal
        assert balance('2025-01-04') == Decimal('71')
        assert balance('2025-01-05') == Decimal('91')
        assert balance('2025-01-10') == Decimal('100')
        assert balance('2025-01-11') == Decimal('92.75')
        other = RepositoryV09(path, backups=False)
        other.add_balance('Cash', '200', '2025-01-11')
        assert balance('2025-01-11') == Decimal('200')
    finally:
        if other: other.close()
        repo.close()
