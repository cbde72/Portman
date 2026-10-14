from portman.repository import PortfolioRepository
from portfolio_v5.models import Balance, ImportBatch, Snapshot, Position


def test_scope_dates_include_cash_years_and_manual_balances(tmp_path):
    repo = PortfolioRepository(tmp_path / 'db.sqlite')
    repo.create_accounts(['Bank'])
    batch = ImportBatch('cash.xlsx', 'cash', balances=[
        Balance(f'{year}-02', 'Liquidität', 'Bank', '100.00', 'ETF', 2)
        for year in range(2016, 2024)])
    iid = repo.commit_batches([batch])[0]['id']
    repo.add_balance('Bank', '120', '2025-03-15')
    repo.commit_batches([ImportBatch('depot.xlsx', 'depot', snapshots=[
        Snapshot('Depot', '2026-09', '2026-09-20', 'Depot',
                 [Position('security', 'Aktie', quantity='1', value='200')])])])
    choices = repo.scope_dates()
    assert ('2020-02 (Monatsstand)', '2020-02-29') in choices
    assert ('2019-02 (Monatsstand)', '2019-02-28') in choices
    assert ('2025-03-15', '2025-03-15') in choices
    assert ('2026-09-20', '2026-09-20') in choices
    assert {value[:4] for _, value in choices} >= {str(year) for year in range(2016, 2024)}
    assert [value for _, value in choices] == sorted({value for _, value in choices}, reverse=True)
    repo.undo_import(iid)
    assert not any('2017' in value for _, value in repo.scope_dates())
    repo.close()
