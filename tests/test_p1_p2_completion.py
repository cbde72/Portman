from decimal import Decimal

from portfolio_v5.models import BankTransaction, ImportBatch
from portman.analysis_v09 import realized_profit
from portman.repository_v09 import RepositoryV09
from portman.repository_v09 import reference


def test_documented_execution_time_resolves_same_day_fifo(tmp_path):
    repo = RepositoryV09(tmp_path / 'execution.sqlite', backups=False)
    try:
        repo.commit_batches([ImportBatch('executions.pdf', 'executions', transactions=[
            BankTransaction('Depot', 'sell', '2026-02-02', 'SELL', '150', 'EUR',
                            security='TEST', quantity='1', executed_at='2026-02-02T10:00:00+01:00'),
            BankTransaction('Depot', 'buy', '2026-02-02', 'BUY', '-100', 'EUR',
                            security='TEST', quantity='1', executed_at='2026-02-02T09:00:00+01:00'),
        ])])
        repo.confirm_coverage('Depot', '0001-01-01', '2026-12-31')
        row = realized_profit(repo, '2026-01-01', '2026-12-31')[0]
        assert (row['cost'], row['realized']) == (Decimal('100'), Decimal('50'))
    finally:
        repo.close()


def test_exact_sourced_fx_rates_produce_eur_fifo_without_estimation(tmp_path):
    repo = RepositoryV09(tmp_path / 'fx.sqlite', backups=False)
    try:
        repo.commit_batches([ImportBatch('fx-trades.pdf', 'fx trades', transactions=[
            BankTransaction('Depot', 'buy', '2026-02-02', 'BUY', '-100', 'USD', security='TEST', quantity='1'),
            BankTransaction('Depot', 'sell', '2026-02-03', 'SELL', '150', 'USD', security='TEST', quantity='1'),
        ])])
        repo.save_fx('2026-02-02', 'USD', '0.90', 'Kaufabrechnung Seite 1')
        repo.save_fx('2026-02-03', 'USD', '0.80', 'Verkaufsabrechnung Seite 1')
        repo.confirm_coverage('Depot', '0001-01-01', '2026-12-31')
        row = realized_profit(repo, '2026-01-01', '2026-12-31')[0]
        assert (row['realized'], row['cost_eur'], row['proceeds_eur'], row['realized_eur']) == (
            Decimal('50'), Decimal('90.00'), Decimal('120.00'), Decimal('30.00'))
        assert row['fx_status'] == 'belegt'
    finally:
        repo.close()


def test_previous_day_fx_rate_is_not_used_as_documented_cost_rate(tmp_path):
    repo = RepositoryV09(tmp_path / 'missing-fx.sqlite', backups=False)
    try:
        repo.save_fx('2026-02-01', 'GBP', '1.15', 'Vortagesbeleg')
        repo.commit_batches([ImportBatch('trades.pdf', 'trades', transactions=[
            BankTransaction('Depot', 'buy', '2026-02-02', 'BUY', '-100', 'GBP', security='TEST', quantity='1'),
            BankTransaction('Depot', 'sell', '2026-02-03', 'SELL', '120', 'GBP', security='TEST', quantity='1'),
        ])])
        repo.confirm_coverage('Depot', '0001-01-01', '2026-12-31')
        row = realized_profit(repo, '2026-01-01', '2026-12-31')[0]
        assert row['realized'] == Decimal('20')
        assert row['cost_eur'] is None and row['realized_eur'] is None
        assert row['fx_status'] == 'unbekannter EUR-Kurs'
    finally:
        repo.close()


def test_confirmed_imported_security_transfer_preserves_fifo_lot(tmp_path):
    repo = RepositoryV09(tmp_path / 'transfer.sqlite', backups=False)
    try:
        repo.commit_batches([ImportBatch('transfer-chain.pdf', 'transfer chain', transactions=[
            BankTransaction('Depot A', 'buy', '2026-01-02', 'BUY', '-200', 'EUR', security='TEST', quantity='2'),
            BankTransaction('Depot A', 'out', '2026-01-03', 'TRANSFER_OUT', '0', 'EUR', security='TEST', quantity='2'),
            BankTransaction('Depot B', 'in', '2026-01-04', 'TRANSFER_IN', '0', 'EUR', security='TEST', quantity='2'),
            BankTransaction('Depot B', 'sell', '2026-01-05', 'SELL', '260', 'EUR', security='TEST', quantity='2'),
        ])])
        transactions = {tx['external_id']: tx for tx in repo.transactions()}
        repo.confirm_security_transfer(reference(transactions['out']), reference(transactions['in']),
                                       'Depotübertragsbeleg 2026-01-04')
        repo.confirm_coverage('Depot A', '0001-01-01', '2026-12-31')
        repo.confirm_coverage('Depot B', '0001-01-01', '2026-12-31')
        row = realized_profit(repo, '2026-01-01', '2026-12-31')[0]
        assert (row['cost'], row['realized']) == (Decimal('200'), Decimal('60'))
        assert len(repo.security_transfer_pairs()) == 1
    finally:
        repo.close()
