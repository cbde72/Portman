from decimal import Decimal

import pytest

from portfolio_v5.models import BankTransaction, ImportBatch, Position, Snapshot
from portfolio_v5.settlement import performance_transactions
from portman.performance_service import PerformanceService
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
        assert len(rows) == 1 and rows[0]['status'] == 'Vollständig abgeglichen'
        assert rows[0]['state'] == 'complete'
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
        assert repo.reconcile_depot_bookings('depot')[0]['status'] == 'Vollständig abgeglichen'
    finally:
        repo.close()


def test_one_cash_booking_is_not_automatically_used_for_two_equal_purchases(tmp_path):
    repo = repository(tmp_path)
    try:
        purchases = [BankTransaction('Depot', f'order-{number}', '2026-03-02', 'BUY', '-100', 'EUR',
            security=f'SEC-{number}', quantity='1', affects_cash=False, performance_depot_key='depot')
            for number in (1, 2)]
        cash = BankTransaction('Giro', 'cash-1', '2026-03-03', 'BANK_BOOKING', '-100', 'EUR')
        repo.store.import_batch(ImportBatch('trades.pdf', 'trades', transactions=purchases))
        repo.store.import_batch(ImportBatch('bank.csv', 'bank', transactions=[cash]))

        rows = repo.reconcile_depot_bookings('depot', persist=True)
        assert [row['status'] for row in rows] == ['Konflikt', 'Konflikt']
        assert repo.booking_links() == []
    finally:
        repo.close()


def test_shared_reference_wins_over_an_equal_weak_candidate(tmp_path):
    repo = repository(tmp_path)
    try:
        purchases = [BankTransaction('Depot', f'order-{number}', '2026-03-02', 'BUY', '-100', 'EUR',
            security=f'SEC-{number}', quantity='1', affects_cash=False, performance_depot_key='depot',
            order_id='MATCH-1' if number == 1 else '') for number in (1, 2)]
        cash = BankTransaction('Giro', 'cash-1', '2026-03-03', 'BANK_BOOKING', '-100', 'EUR',
            bank_reference='MATCH-1')
        repo.store.import_batch(ImportBatch('trades.pdf', 'trades', transactions=purchases))
        repo.store.import_batch(ImportBatch('bank.csv', 'bank', transactions=[cash]))

        rows = repo.reconcile_depot_bookings('depot', persist=True)
        assert [row['status'] for row in rows] == ['Vollständig abgeglichen', 'Konflikt']
        assert len(repo.booking_links()) == 1
        assert repo.booking_links()[0]['depot_ref'] == reference(
            next(tx for tx in repo.transactions() if tx['external_id'] == 'order-1'))
    finally:
        repo.close()


@pytest.mark.parametrize('kind,depot_amount,cash_amount', [
    ('BUY', '-100', '100'), ('SELL', '100', '-100'), ('DIVIDEND', '100', '-100'),
    ('TAX', '-100', '100'), ('FEE', '-100', '100'),
])
def test_automatic_reconciliation_rejects_opposite_payment_direction(
        tmp_path, kind, depot_amount, cash_amount):
    repo = repository(tmp_path)
    try:
        notice = BankTransaction('Depot', 'notice', '2026-03-02', kind, depot_amount, 'EUR',
            security='SEC', affects_cash=False, performance_depot_key='depot')
        cash = BankTransaction('Giro', 'cash', '2026-03-02', 'BANK_BOOKING', cash_amount, 'EUR')
        repo.store.import_batch(ImportBatch('notice.pdf', 'notice', transactions=[notice]))
        repo.store.import_batch(ImportBatch('bank.csv', 'bank', transactions=[cash]))
        assert repo.reconcile_depot_bookings('depot', persist=True)[0]['status'] == 'Offen'
        assert repo.booking_links() == []
    finally:
        repo.close()


@pytest.mark.parametrize('kind,depot_amount,cash_amount', [
    ('BUY', '-100', '100'), ('SELL', '100', '-100'), ('DIVIDEND', '100', '-100'),
    ('TAX', '-100', '100'), ('FEE', '-100', '100'),
])
def test_manual_reconciliation_rejects_opposite_payment_direction(
        tmp_path, kind, depot_amount, cash_amount):
    repo = repository(tmp_path)
    try:
        notice = BankTransaction('Depot', 'notice', '2026-03-02', kind, depot_amount, 'EUR',
            security='SEC', affects_cash=False, performance_depot_key='depot')
        cash = BankTransaction('Giro', 'cash', '2026-03-02', 'BANK_BOOKING', cash_amount, 'EUR')
        repo.store.import_batch(ImportBatch('notice.pdf', 'notice', transactions=[notice]))
        repo.store.import_batch(ImportBatch('bank.csv', 'bank', transactions=[cash]))
        txs = {row['external_id']: reference(row) for row in repo.transactions()}

        with pytest.raises(ValueError, match='Zahlungsrichtung'):
            repo.confirm_booking_link(txs['notice'], txs['cash'], 'Manuell geprüft')
        assert repo.booking_links() == []
    finally:
        repo.close()


@pytest.mark.parametrize('kind,amount', [
    ('BUY', '-100'), ('SELL', '100'), ('DIVIDEND', '100'), ('TAX', '-100'), ('FEE', '-100'),
])
def test_manual_reconciliation_accepts_matching_payment_direction(tmp_path, kind, amount):
    repo = repository(tmp_path)
    try:
        notice = BankTransaction('Depot', 'notice', '2026-03-02', kind, amount, 'EUR',
            security='SEC', affects_cash=False, performance_depot_key='depot')
        cash = BankTransaction('Giro', 'cash', '2026-03-02', 'BANK_BOOKING', amount, 'EUR')
        repo.store.import_batch(ImportBatch('notice.pdf', 'notice', transactions=[notice]))
        repo.store.import_batch(ImportBatch('bank.csv', 'bank', transactions=[cash]))
        txs = {row['external_id']: reference(row) for row in repo.transactions()}

        repo.confirm_booking_link(txs['notice'], txs['cash'], 'Manuell geprüft')
        assert len(repo.booking_links()) == 1
    finally:
        repo.close()


def test_manual_partial_allocations_respect_both_available_amounts(tmp_path):
    repo = repository(tmp_path)
    try:
        notices = [BankTransaction('Depot', f'order-{number}', '2026-03-02', 'BUY', amount, 'EUR',
            security=f'SEC-{number}', affects_cash=False, performance_depot_key='depot')
            for number, amount in ((1, '-100'), (2, '-80'), (3, '-200'))]
        cash = BankTransaction('Giro', 'cash', '2026-03-03', 'BANK_BOOKING', '-150', 'EUR')
        second_cash = BankTransaction('Giro', 'cash-2', '2026-03-03', 'BANK_BOOKING', '-50', 'EUR')
        repo.store.import_batch(ImportBatch('trades.pdf', 'trades', transactions=notices))
        repo.store.import_batch(ImportBatch('bank.csv', 'bank', transactions=[cash, second_cash]))
        txs = {row['external_id']: reference(row) for row in repo.transactions()}

        repo.confirm_booking_link(txs['order-1'], txs['cash'], 'Teilzahlung laut Beleg', '70')
        repo.confirm_booking_link(txs['order-2'], txs['cash'], 'Teilzahlung laut Beleg', '80')
        assert [Decimal(row['allocated_amount']) for row in repo.booking_links()] == [Decimal('70'), Decimal('80')]
        states = {row['transaction']['external_id']: row for row in repo.reconcile_depot_bookings('depot')}
        assert states['order-1']['state'] == 'partial'
        assert states['order-1']['status'] == 'Teilweise zugeordnet'
        assert Decimal(states['order-1']['remaining_amount']) == Decimal('30')
        assert states['order-2']['state'] == 'complete'
        repo.confirm_booking_link(txs['order-1'], txs['cash-2'], 'Zweite Teilzahlung', '30')
        assert {row['transaction']['external_id']: row['state']
                for row in repo.reconcile_depot_bookings('depot')}['order-1'] == 'complete'
        with pytest.raises(ValueError, match='Depotbuchung'):
            repo.confirm_booking_link(txs['order-1'], txs['cash-2'], 'Zu viel im Depot', '31')
        with pytest.raises(ValueError, match='Geldkontobuchung'):
            repo.confirm_booking_link(txs['order-3'], txs['cash'], 'Zu viel auf Konto', '0.01')
    finally:
        repo.close()


def test_partial_link_neutralizes_only_allocated_cash_share_and_respects_boundaries(tmp_path):
    repo = repository(tmp_path)
    try:
        notice = BankTransaction('Depot', 'order', '2026-03-02', 'BUY', '-100', 'EUR',
            security='SEC', affects_cash=False, performance_depot_key='depot')
        cash = BankTransaction('Giro', 'cash', '2026-03-03', 'BUY', '-150', 'EUR',
            affects_cash=True, performance_depot_key='depot')
        repo.store.import_batch(ImportBatch('trade.pdf', 'trade', transactions=[notice]))
        repo.store.import_batch(ImportBatch('bank.csv', 'bank', transactions=[cash]))
        txs = {row['external_id']: row for row in repo.transactions()}
        repo.confirm_booking_link(reference(txs['order']), reference(txs['cash']),
                                  'Nur ein Teil der Sammelzahlung gehört zum Beleg', '70')

        economic = performance_transactions(repo.store, repo.transactions(), 'Depot')
        assert [(row['external_id'], Decimal(row['amount'])) for row in economic] == [
            ('order', Decimal('-100')), ('cash', Decimal('-80'))]
        assert economic[1]['reconciliation_allocated'] == '70'
        assert Decimal(next(row for row in repo.transactions()
                            if row['external_id'] == 'cash')['amount']) == Decimal('-150')

        # A link is neutralized only if both records are inside the selected
        # performance interval.  Crossing the boundary must retain the source flow.
        cash_only = performance_transactions(repo.store, [txs['cash']], 'Depot')
        notice_only = performance_transactions(repo.store, [txs['order']], 'Depot')
        assert Decimal(cash_only[0]['amount']) == Decimal('-150')
        assert Decimal(notice_only[0]['amount']) == Decimal('-100')
    finally:
        repo.close()


def test_aggregate_cash_payment_is_fully_consumed_by_multiple_trades(tmp_path):
    repo = repository(tmp_path)
    try:
        notices = [BankTransaction('Depot', f'order-{number}', '2026-03-02', 'BUY', f'-{amount}', 'EUR',
            security=f'SEC-{number}', affects_cash=False, performance_depot_key='depot')
            for number, amount in ((1, 70), (2, 80))]
        cash = BankTransaction('Giro', 'cash', '2026-03-03', 'BUY', '-150', 'EUR',
            affects_cash=True, performance_depot_key='depot')
        repo.store.import_batch(ImportBatch('trades.pdf', 'trades', transactions=notices))
        repo.store.import_batch(ImportBatch('bank.csv', 'bank', transactions=[cash]))
        refs = {row['external_id']: reference(row) for row in repo.transactions()}
        repo.confirm_booking_link(refs['order-1'], refs['cash'], 'Sammelzahlung Teil 1', '70')
        repo.confirm_booking_link(refs['order-2'], refs['cash'], 'Sammelzahlung Teil 2', '80')

        economic = performance_transactions(repo.store, repo.transactions(), 'Depot')
        assert [(row['external_id'], Decimal(row['amount'])) for row in economic] == [
            ('order-1', Decimal('-70')), ('order-2', Decimal('-80'))]
    finally:
        repo.close()


@pytest.mark.parametrize('kind,amount', [('DIVIDEND', '25'), ('TAX', '-5')])
def test_income_or_tax_notice_and_cash_evidence_count_once(tmp_path, kind, amount):
    repo = repository(tmp_path)
    try:
        notice = BankTransaction('Depot', 'notice', '2026-03-02', kind, amount, 'EUR',
            security='SEC', affects_cash=False, performance_depot_key='depot')
        cash = BankTransaction('Giro', 'cash', '2026-03-02', kind, amount, 'EUR',
            security='SEC', affects_cash=True, performance_depot_key='depot')
        repo.store.import_batch(ImportBatch('notice.pdf', 'notice', transactions=[notice]))
        repo.store.import_batch(ImportBatch('bank.csv', 'bank', transactions=[cash]))
        refs = {row['external_id']: reference(row) for row in repo.transactions()}
        repo.confirm_booking_link(refs['notice'], refs['cash'], 'Beleg und Kontoumsatz identisch')

        economic = performance_transactions(repo.store, repo.transactions(), 'Depot')
        assert [(row['external_id'], row['kind'], Decimal(row['amount'])) for row in economic] == [
            ('notice', kind, Decimal(amount))]
    finally:
        repo.close()


def test_existing_link_reserves_cash_and_does_not_change_balances_holdings_or_performance(tmp_path):
    repo = repository(tmp_path)
    try:
        snapshots = [Snapshot('Depot', day[:7], day, 'Depot', [
            Position('SEC', 'Security', quantity=quantity, value=value)])
            for day, quantity, value in (('2026-03-01', '1', '100'), ('2026-03-10', '2', '210'))]
        purchases = [BankTransaction('Depot', f'order-{number}', '2026-03-05', 'BUY', '-100', 'EUR',
            security='SEC', quantity='1', affects_cash=False, performance_depot_key='depot')
            for number in (1, 2)]
        cash = BankTransaction('Giro', 'cash', '2026-03-05', 'BANK_BOOKING', '-100', 'EUR')
        repo.store.import_batch(ImportBatch('data', 'data', snapshots=snapshots, transactions=[*purchases, cash]))
        refs = {row['external_id']: reference(row) for row in repo.transactions()}
        repo.confirm_booking_link(refs['order-1'], refs['cash'], 'Erster Kauf belegt')
        balances_before = repo.account_overview()
        holdings_before = repo.holdings()
        performance_before = PerformanceService(repo).analyze('Depot', '2026-03-01', '2026-03-10')

        rows = repo.reconcile_depot_bookings('depot', persist=True)
        assert next(row for row in rows if row['transaction']['external_id'] == 'order-2')['status'] == 'Offen'
        assert len(repo.booking_links()) == 1
        performance_after = PerformanceService(repo).analyze('Depot', '2026-03-01', '2026-03-10')
        assert repo.account_overview() == balances_before
        assert repo.holdings() == holdings_before
        assert performance_after['twr'] == performance_before['twr']
        assert performance_after['xirr'] == performance_before['xirr']
        assert [row['external_id'] for row in performance_after['transactions']].count('cash') == 0
    finally:
        repo.close()


def test_partial_settlement_matches_reference_twr_dietz_and_xirr(tmp_path):
    actual_folder, reference_folder = tmp_path / 'actual', tmp_path / 'reference'
    actual_folder.mkdir(); reference_folder.mkdir()
    actual = repository(actual_folder)
    expected = repository(reference_folder)
    try:
        snapshots = [Snapshot('Depot', day[:7], day, 'Depot', [
            Position('SEC', 'Security', quantity=quantity, value=value)])
            for day, quantity, value in (('2026-03-01', '1', '100'), ('2026-03-10', '3', '300'))]
        notice = BankTransaction('Depot', 'order', '2026-03-02', 'BUY', '-100', 'EUR',
            security='SEC', quantity='1', affects_cash=False, performance_depot_key='depot')
        cash = BankTransaction('Giro', 'cash', '2026-03-03', 'BUY', '-150', 'EUR',
            affects_cash=True, performance_depot_key='depot')
        actual.store.import_batch(ImportBatch('actual', 'actual', snapshots=snapshots,
                                               transactions=[notice, cash]))
        refs = {row['external_id']: reference(row) for row in actual.transactions()}
        balances_before, holdings_before = actual.account_overview(), actual.holdings()
        actual.confirm_booking_link(refs['order'], refs['cash'], '70 EUR gehören zum Kaufbeleg', '70')

        expected_transactions = [
            BankTransaction('Depot', 'order', '2026-03-02', 'BUY', '-100', 'EUR',
                            security='SEC', quantity='1'),
            BankTransaction('Depot', 'remaining-payment', '2026-03-03', 'BUY', '-80', 'EUR',
                            security='OTHER', quantity='1'),
        ]
        expected.store.import_batch(ImportBatch('expected', 'expected', snapshots=snapshots,
                                                 transactions=expected_transactions))
        actual_result = PerformanceService(actual).analyze('Depot', '2026-03-01', '2026-03-10')
        expected_result = PerformanceService(expected).analyze('Depot', '2026-03-01', '2026-03-10')

        assert actual.account_overview() == balances_before
        assert actual.holdings() == holdings_before
        for metric in ('twr', 'ttwror', 'xirr', 'profit', 'net_contributions'):
            assert actual_result[metric] == expected_result[metric]
        assert actual_result['net_contributions'] == Decimal('180')
    finally:
        actual.close(); expected.close()
