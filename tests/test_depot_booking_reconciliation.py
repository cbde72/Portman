from decimal import Decimal

from portfolio_v5.models import BankTransaction, ImportBatch
from portfolio_v5.settlement import performance_transactions
from portman.repository_v09 import RepositoryV09, reference


def repository(tmp_path):
    repo = RepositoryV09(tmp_path / 'reconciliation.sqlite', backups=False)
    repo.store.save_account('Settlement', {'kind': 'Verrechnungskonto'})
    repo.store.save_account('Giro', {'kind': 'Girokonto'})
    repo.store.save_account('Depot', {'kind': 'Depot', 'cash_account_key': 'settlement'})
    repo.save_depot_payment_accounts('depot', ['settlement', 'giro'], 'settlement')
    return repo


def test_multiple_payment_accounts_preserve_legacy_default(tmp_path):
    repo = repository(tmp_path)
    try:
        assert repo.depot_payment_accounts('depot') == [
            {'account_key': 'settlement', 'default': True},
            {'account_key': 'giro', 'default': False},
        ]
        details = next(row for row in repo.account_records() if row['account_key'] == 'depot')['details']
        assert '"cash_account_key": "settlement"' in details
    finally:
        repo.close()


def test_direct_giro_purchase_is_uniquely_reconciled_and_counted_once(tmp_path):
    repo = repository(tmp_path)
    try:
        notice = BankTransaction('Depot', 'order-1', '2026-03-02', 'BUY', '-100', 'EUR',
            security='US0378331005', quantity='1', affects_cash=False,
            performance_depot_key='depot', order_id='ABC-1')
        cash = BankTransaction('Giro', 'cash-1', '2026-03-03', 'BANK_BOOKING', '-100', 'EUR',
            bank_reference='ABC-1', purpose='SEPA Lastschrift Wertpapierkauf')
        repo.store.import_batch(ImportBatch('trade.pdf', 'trade', transactions=[notice]))
        repo.store.import_batch(ImportBatch('bank.csv', 'bank', transactions=[cash]))

        rows = repo.reconcile_depot_bookings('depot', persist=True)
        assert len(rows) == 1 and rows[0]['status'] == 'Abgeglichen'
        assert len(repo.booking_links()) == 1
        economic = performance_transactions(repo.store, repo.transactions(), 'Depot')
        assert [(row['kind'], Decimal(row['amount'])) for row in economic] == [('BUY', Decimal('-100'))]
    finally:
        repo.close()


def test_ambiguous_cash_bookings_remain_conflict_without_persistence(tmp_path):
    repo = repository(tmp_path)
    try:
        notice = BankTransaction('Depot', 'order-1', '2026-03-02', 'BUY', '-100', 'EUR',
            security='US0378331005', affects_cash=False, performance_depot_key='depot')
        candidates = [BankTransaction('Giro', f'cash-{day}', f'2026-03-0{day}', 'BANK_BOOKING', '-100', 'EUR')
                      for day in (2, 3)]
        repo.store.import_batch(ImportBatch('trade.pdf', 'trade', transactions=[notice]))
        repo.store.import_batch(ImportBatch('bank.csv', 'bank', transactions=candidates))

        rows = repo.reconcile_depot_bookings('depot', persist=True)
        assert rows[0]['status'] == 'Konflikt'
        assert len(rows[0]['candidates']) == 2
        assert repo.booking_links() == []
    finally:
        repo.close()


def test_manual_link_survives_duplicate_reimport(tmp_path):
    repo = repository(tmp_path)
    try:
        notice = BankTransaction('Depot', 'order-1', '2026-03-02', 'BUY', '-100', 'EUR',
            security='US0378331005', affects_cash=False, performance_depot_key='depot')
        cash = BankTransaction('Giro', 'cash-1', '2026-03-03', 'BANK_BOOKING', '-100', 'EUR')
        trade = ImportBatch('trade.pdf', 'trade', transactions=[notice])
        bank = ImportBatch('bank.csv', 'bank', transactions=[cash])
        repo.store.import_batch(trade); repo.store.import_batch(bank)
        txs = {row['external_id']: row for row in repo.transactions()}
        repo.confirm_booking_link(reference(txs['order-1']), reference(txs['cash-1']), 'Kontoauszug geprüft')
        assert repo.store.import_batch(bank)['status'] == 'duplicate'
        assert repo.reconcile_depot_bookings('depot')[0]['status'] == 'Manuell bestätigt'
    finally:
        repo.close()
