from decimal import Decimal
import pytest
from portman.repository import PortfolioRepository
from portfolio_v5.models import ImportBatch, Snapshot, Position, Balance


@pytest.mark.parametrize('category,complete,expected', [
    ('Wertpapiere', True, '200'), ('Wertpapiere', False, '100'), ('Liquidität', True, '100')])
def test_latest_sync_supersedes_only_complete_securities_balance(tmp_path, category, complete, expected):
    repo = PortfolioRepository(tmp_path / 'test.sqlite')
    try:
        repo.commit_batches([ImportBatch('excel', 'excel',
            balances=[Balance('2026-09', category, 'Depot', '100', 'ETF', 1)],
            snapshots=[Snapshot('Depot', '2026-09', '2026-09-01', 'ING', [Position('A', 'A', value='100')])])])
        repo.commit_batches([ImportBatch('online', 'online', source_sheet='Online ING',
            snapshots=[Snapshot('Depot', '2026-09', '2026-09-29', 'Online ING',
                [Position('A', 'A', value='200')], complete=complete)])])
        current = repo.account_overview()[0]
        assert current['balance'] == Decimal(expected)
        assert repo.account_overview('2026-09-15')[0]['balance'] == Decimal('100')
        assert repo.account_overview('2026-09-15')[0]['depot_value'] == Decimal('100')
        assert len(repo.state_history('Depot')) == 3
    finally:
        repo.close()
