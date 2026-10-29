from decimal import Decimal

from portfolio_v5.models import BankTransaction, ImportBatch, Position, Snapshot
from portman.analysis_v09 import realized_profit
from portman.repository_v09 import RepositoryV09


SECURITY = 'DE000TEST001'


def empty_depots(repo):
    repo.commit_batches([ImportBatch('opening', 'opening', snapshots=[
        Snapshot('Depot A', '2025-12', '2025-12-31', 'Beleg A', []),
        Snapshot('Depot B', '2025-12', '2025-12-31', 'Beleg B', []),
    ])])


def confirm_coverage(repo):
    repo.confirm_coverage('Depot A', '0001-01-01', '2026-12-31')
    repo.confirm_coverage('Depot B', '0001-01-01', '2026-12-31')


def test_complete_fifo_chain_preserves_lots_across_transfer_and_split(tmp_path):
    repo = RepositoryV09(tmp_path / 'chain.sqlite', backups=False)
    try:
        empty_depots(repo)
        repo.commit_batches([ImportBatch('trades', 'trades', transactions=[
            BankTransaction('Depot A', 'buy-1', '2026-01-02', 'BUY', '-100', 'EUR',
                            security=SECURITY, quantity='10'),
            BankTransaction('Depot A', 'buy-2', '2026-01-03', 'BUY', '-100', 'EUR',
                            security=SECURITY, quantity='5'),
            BankTransaction('Depot A', 'sell-1', '2026-01-04', 'SELL', '180', 'EUR',
                            security=SECURITY, quantity='12'),
            BankTransaction('Depot B', 'sell-2', '2026-01-08', 'SELL', '45', 'EUR',
                            security=SECURITY, quantity='3'),
        ])])
        repo.add_action('2026-01-05', 'Depot A', SECURITY, 'TRANSFER', 'Übertragsbeleg',
                        target_depot='Depot B', units='2')
        repo.add_action('2026-01-06', 'Depot B', SECURITY, 'SPLIT', 'Splitbeleg', ratio='2')
        repo.commit_batches([ImportBatch('closing', 'closing', snapshots=[
            Snapshot('Depot A', '2026-01', '2026-01-31', 'Schlussbeleg A', [
                Position(SECURITY, 'Test', isin=SECURITY, quantity='1', value='25')]),
            Snapshot('Depot B', '2026-01', '2026-01-31', 'Schlussbeleg B', [
                Position(SECURITY, 'Test', isin=SECURITY, quantity='1', value='12')]),
        ])])
        confirm_coverage(repo)

        rows = realized_profit(repo, '2026-01-01', '2026-12-31')
        assert [(r['cost'], r['realized']) for r in rows] == [
            (Decimal('140'), Decimal('40')),
            (Decimal('30'), Decimal('15')),
        ]
        a = repo.holdings('2026-01-31', 'Depot A')[0]
        b = repo.holdings('2026-01-31', 'Depot B')[0]
        assert (a['quantity'], a['cost']) == ('1', '20.00')
        assert (b['quantity'], b['cost']) == ('1', '10.00')
        assert (Decimal(a['value']) - Decimal(a['cost']),
                Decimal(b['value']) - Decimal(b['cost'])) == (Decimal('5'), Decimal('2'))
    finally:
        repo.close()


def test_transfer_of_unknown_opening_cost_stays_unknown(tmp_path):
    repo = RepositoryV09(tmp_path / 'unknown.sqlite', backups=False)
    try:
        repo.commit_batches([ImportBatch('opening', 'opening', snapshots=[
            Snapshot('Depot A', '2025-12', '2025-12-31', 'Altbestand', [
                Position(SECURITY, 'Test', isin=SECURITY, quantity='2', value='50')]),
            Snapshot('Depot B', '2025-12', '2025-12-31', 'Leerbestand', []),
        ])])
        repo.add_action('2026-01-02', 'Depot A', SECURITY, 'TRANSFER', 'Übertragsbeleg',
                        target_depot='Depot B', units='1')
        target = repo.holdings('2026-01-03', 'Depot B')[0]
        assert target['quantity'] == '1'
        assert target['cost'] is None
        assert target.get('unknown_cost_quantity') == '1'
    finally:
        repo.close()


def test_transfer_merges_lots_by_original_acquisition_date(tmp_path):
    repo = RepositoryV09(tmp_path / 'lot-order.sqlite', backups=False)
    try:
        empty_depots(repo)
        repo.commit_batches([ImportBatch('trades', 'trades', transactions=[
            BankTransaction('Depot A', 'old-buy', '2026-01-01', 'BUY', '-10', 'EUR',
                            security=SECURITY, quantity='1'),
            BankTransaction('Depot B', 'new-buy', '2026-01-02', 'BUY', '-20', 'EUR',
                            security=SECURITY, quantity='1'),
            BankTransaction('Depot B', 'sell', '2026-01-04', 'SELL', '30', 'EUR',
                            security=SECURITY, quantity='1'),
        ])])
        repo.add_action('2026-01-03', 'Depot A', SECURITY, 'TRANSFER', 'Übertragsbeleg',
                        target_depot='Depot B', units='1')
        confirm_coverage(repo)
        row = realized_profit(repo, '2026-01-01', '2026-12-31')[0]
        assert (row['cost'], row['realized']) == (Decimal('10'), Decimal('20'))
        assert repo.holdings('2026-01-31', 'Depot B')[0]['cost'] == '20.00'
    finally:
        repo.close()


def test_merger_changes_identifier_without_changing_total_cost(tmp_path):
    repo = RepositoryV09(tmp_path / 'merger.sqlite', backups=False)
    try:
        empty_depots(repo)
        repo.commit_batches([ImportBatch('buy', 'buy', transactions=[
            BankTransaction('Depot A', 'buy', '2026-01-02', 'BUY', '-120', 'EUR',
                            security='OLD', quantity='3'),
            BankTransaction('Depot A', 'sell', '2026-01-04', 'SELL', '100', 'EUR',
                            security='NEW', quantity='1'),
        ])])
        repo.add_action('2026-01-03', 'Depot A', 'OLD', 'MERGER', 'Umtauschbeleg',
                        target='NEW', ratio='0.5')
        confirm_coverage(repo)
        row = realized_profit(repo, '2026-01-01', '2026-12-31')[0]
        assert (row['cost'], row['realized']) == (Decimal('80'), Decimal('20'))
        position = repo.holdings('2026-01-31', 'Depot A')[0]
        assert (position['key'], position['quantity'], position['cost']) == ('NEW', '0.5', '40.00')
    finally:
        repo.close()
