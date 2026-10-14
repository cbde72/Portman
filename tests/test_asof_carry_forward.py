from decimal import Decimal
from portman.repository import PortfolioRepository
from portfolio_v5.models import ImportBatch, Balance


def test_all_accounts_keep_last_known_balance_without_future_values(tmp_path):
    repo = PortfolioRepository(tmp_path / 'db.sqlite')
    try:
        for name, day, value in [('A', '2026-08-05', '100'), ('B', '2026-09-10', '200'),
                                 ('A', '2026-09-20', '150'), ('B', '2026-09-25', '0')]:
            repo.commit_batches([ImportBatch(day + name, day + name, source_sheet='Online ING',
                balances=[Balance(day[:7], 'Liquidität', name, value, 'Online ING · ' + day, 1)])])
        rows = {r['name']: r for r in repo.account_overview('2026-09-15')}
        assert rows['A']['balance'] == Decimal('100')
        assert rows['A']['period'] == '2026-08-05'
        assert rows['B']['balance'] == Decimal('200')
        assert repo.wealth_summary('2026-09-15')['value'] == Decimal('300')
        assert repo.wealth_summary('2026-09-22')['value'] == Decimal('350')
        assert repo.wealth_summary('2026-09-26')['value'] == Decimal('150')
        assert repo.wealth_summary('2026-08-01')['value'] is None
        repo.add_balance('A', '80', '2026-08-01')
        assert repo.wealth_summary('2026-09-15')['value'] == Decimal('300')
    finally: repo.close()


def test_monthly_balance_carried_forward_and_omission_is_not_zero(tmp_path):
    repo = PortfolioRepository(tmp_path / 'db.sqlite')
    try:
        for month, name, value in [('2026-07', 'A', '100'), ('2026-08', 'B', '200')]:
            repo.commit_batches([ImportBatch(month, month, balances=[Balance(month, 'Liquidität', name, value, 'ETF', 1)])])
        assert repo.wealth_summary('2026-09-15')['value'] == Decimal('300')
        assert repo.wealth_summary('2026-08-15')['value'] == Decimal('300')
    finally: repo.close()
