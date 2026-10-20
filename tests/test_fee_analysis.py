import csv

from openpyxl import load_workbook

from portfolio_v5.models import FeeItem, ImportBatch, Transaction
from portman.fee_analysis import export_fees, fee_rows, fee_summary
from portman.repository_v09 import RepositoryV09


def trade(identifier, *, kind='BUY', market='28.62', fees='0.43', taxes=None,
          total='29.05', fee_items=None, order='ORDER-1', day='2026-01-02'):
    return Transaction('Depot comdirect', identifier, day, kind,
        ('-' if kind == 'BUY' else '') + total, 'EUR', security='DE0007164600', quantity='1',
        gross_amount=market, fees=fees, taxes=taxes, order_id=order,
        fee_items=fee_items if fee_items is not None else
        ([] if fees is None else [FeeItem('provision', fees)]))


def repository(tmp_path, transactions):
    repo = RepositoryV09(tmp_path / 'fees.sqlite', backups=False)
    repo.commit_batches([ImportBatch('fees.pdf', 'fee-hash', transactions=transactions)])
    return repo


def test_fee_analysis_purchase_sale_zero_unknown_conflict_and_summary(tmp_path):
    repo = repository(tmp_path, [
        trade('buy'),
        trade('sell', kind='SELL', market='50.00', fees='0.50', total='49.50', order='ORDER-2'),
        trade('zero', market='49.82', fees='0.00', total='49.82', order='ORDER-3'),
        trade('unknown', market='10.00', fees=None, total='10.00', order='ORDER-4'),
        trade('conflict', market='20.00', fees='1.00', total='25.00', order='ORDER-5'),
    ])
    try:
        rows = fee_rows(repo)
        by_id = {row['transaction_id']: row for row in rows}
        assert {key: row['status'] for key, row in by_id.items()} == {
            'buy': 'nachgewiesen', 'sell': 'nachgewiesen', 'zero': 'nachgewiesen 0,00 €',
            'unknown': 'unbekannt', 'conflict': 'widersprüchlich'}
        assert {key: row['reconciliation'] for key, row in by_id.items()} == {
            'buy': 'plausibel', 'sell': 'plausibel', 'zero': 'plausibel',
            'unknown': 'unbekannt', 'conflict': 'widersprüchlich'}
        summary = fee_summary(rows, ('year', 'bank'))
        assert summary == [{'year': '2026', 'bank': 'Depot', 'amount': '1.93',
                            'count': 5, 'unknown': 1, 'conflicts': 1}]
    finally:
        repo.close()


def test_fee_analysis_deduplicates_overlapping_sources_and_exports(tmp_path):
    repo = repository(tmp_path, [trade('pdf', order='SAME')])
    try:
        # Simulate the already consolidated effective view returned by the repository.
        original = repo.transactions
        repo.transactions = lambda *args, **kwargs: original(*args, **kwargs) * 2
        rows = fee_rows(repo)
        assert len(rows) == 1 and rows[0]['amount'] == '0.43'
        csv_path, xlsx_path = tmp_path / 'fees.csv', tmp_path / 'fees.xlsx'
        export_fees(rows, csv_path); export_fees(rows, xlsx_path)
        with csv_path.open(encoding='utf-8-sig') as handle:
            exported = list(csv.DictReader(handle, delimiter=';'))
        assert exported[0]['fee_type'] == 'Provision'
        assert load_workbook(xlsx_path, read_only=True).active['H2'].value == '0.43'
    finally:
        repo.close()


def test_reference_comdirect_fee_amounts_are_plausible(tmp_path):
    cases = [('716460', '28.62', '0.43', '29.05'), ('A0D8Q4', '49.03', '0.74', '49.77'),
             ('A1JJTF', '36.49', '0.55', '37.04'), ('A2H57N', '49.82', '0.00', '49.82')]
    transactions = [trade(wkn, market=market, fees=fee, total=total, order='ORDER-' + wkn)
                    for wkn, market, fee, total in cases]
    repo = repository(tmp_path, transactions)
    try:
        rows = fee_rows(repo)
        assert [row['reconciliation'] for row in rows] == ['plausibel'] * 4
        assert next(row for row in rows if row['transaction_id'] == 'A2H57N')['status'] == 'nachgewiesen 0,00 €'
    finally:
        repo.close()
