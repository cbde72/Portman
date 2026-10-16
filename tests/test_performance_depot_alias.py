from portfolio_v5.accounts import account_key
from portfolio_v5.models import ImportBatch, Position, Snapshot
from portman.performance_service import PerformanceService
from portman.repository_v09 import RepositoryV09


def test_transferred_and_online_depot_alias_are_one_depot(tmp_path):
    repo = RepositoryV09(tmp_path / 'portfolio.sqlite', backups=False)
    try:
        repo.save_account('comdirect Depot', {'kind': 'Depot'})
        target = account_key('comdirect Depot')
        transferred = 'comdirect Depot / comdirect Depot / Depot 4764924'
        repo.commit_batches([ImportBatch('transfer', 'transfer',
            snapshots=[Snapshot(transferred, '2025-10', '2025-10-01', 'Transfer',
                [Position('TEST', 'Test', quantity='1', value='100')])],
            account_assignments={account_key(transferred): target})])
        repo.commit_batches([ImportBatch('online', 'online', source_sheet='Online comdirect',
            snapshots=[Snapshot('Depot 4764924', '2025-11', '2025-11-01', 'Online comdirect',
                [Position('TEST', 'Test', quantity='1', value='110')])],
            account_assignments={account_key('Depot 4764924'): target})])
        series = PerformanceService(repo).valuation_series('comdirect Depot')
        assert [row['depots'] for row in series] == [('Depot 4764924',), ('Depot 4764924',)]
        result = PerformanceService(repo).analyze('comdirect Depot', '2025-10-01', '2025-11-01')
        assert not result.get('error')
        assert result['valuation_confirmed']
        repo.confirm_coverage('comdirect Depot', '2025-10-01', '2025-11-01')
        period = PerformanceService(repo).period('comdirect Depot', '2025-10-01', '2025-11-01')
        assert not period.get('error')
        assert period['opening'] == 100
        assert period['closing'] == 110
    finally:
        repo.close()
