"""Stable public behavior captured before the phase-2 import refactoring."""
import json
import sqlite3

import pytest

from portfolio_v5.accounts import account_key
from portfolio_v5.models import BankTransaction, ImportBatch, Position, Snapshot, Transaction
from portman.repository_v09 import RepositoryV09


def _batch(label, *, account='Source'):
    return ImportBatch(
        f'{label}.csv',
        f'{label}-source-hash',
        snapshots=[Snapshot(account, '2026-01', '2026-01-31', label, [
            Position('US0378331005', 'Apple', isin='US0378331005', quantity='2', cost='180', value='200'),
        ])],
        transactions=[
            Transaction(account, f'{label}-buy', '2026-01-10', 'BUY', '-90', 'EUR',
                        security='US0378331005', quantity='1', fees='1'),
            Transaction(account, f'{label}-dividend', '2026-01-20', 'DIVIDEND', '5', 'EUR',
                        security='US0378331005', taxes='1'),
        ],
    )


def _semantic_state(repo):
    snapshots = []
    for row in repo.db.execute('SELECT payload FROM snapshots'):
        payload = json.loads(row['payload'])
        payload.pop('sheet', None)
        snapshots.append(payload)
    return {
        'snapshots': snapshots,
        'transactions': sorted((row['external_id'], json.loads(row['payload']))
                               for row in repo.db.execute('SELECT external_id,payload FROM transactions')),
        'accounts': sorted((row['account_key'], row['name'], row['active'])
                           for row in repo.store.account_records()),
    }


def test_success_duplicate_and_repeat_result_contract(tmp_path):
    repo = RepositoryV09(tmp_path / 'result.sqlite', backups=False)
    try:
        first = repo.store.import_batch(_batch('one'))
        duplicate = repo.store.import_batch(_batch('one'))
        repeated = _batch('one')
        repeated.force_import = True
        repeat = repo.store.import_batch(repeated)

        assert first == {'status': 'imported', 'snapshots': 1, 'balances': 0,
                         'transactions': 2, 'unchanged': 0, 'id': 1,
                         'documents': 0, 'model_records': 0}
        assert duplicate == {'status': 'duplicate', 'path': 'one.csv', 'id': 1}
        assert repeat['status'] == 'imported'
        assert (repeat['snapshots'], repeat['transactions'], repeat['unchanged']) == (1, 2, 0)
    finally:
        repo.close()


def test_validation_and_persistence_failure_leave_no_partial_import(tmp_path):
    repo = RepositoryV09(tmp_path / 'rollback.sqlite', backups=False)
    try:
        invalid = ImportBatch('bad.csv', 'bad', transactions=[
            Transaction('Cash', 'bad', '2026-01-01', 'BUY', 'NaN', 'EUR')])
        with pytest.raises(ValueError):
            repo.store.import_batch(invalid)

        repo.db.execute("CREATE TRIGGER fail_transaction BEFORE INSERT ON transactions "
                        "BEGIN SELECT RAISE(ABORT, 'characterized failure'); END")
        with pytest.raises(sqlite3.IntegrityError, match='characterized failure'):
            repo.store.import_batch(_batch('fails'))
        assert repo.db.execute('SELECT count(*) FROM imports').fetchone()[0] == 0
        assert repo.db.execute('SELECT count(*) FROM snapshots').fetchone()[0] == 0
        assert repo.db.execute('SELECT count(*) FROM accounts').fetchone()[0] == 0
    finally:
        repo.close()


def test_account_and_performance_depot_mapping_contract(tmp_path):
    repo = RepositoryV09(tmp_path / 'mapping.sqlite', backups=False)
    try:
        repo.store.save_account('Depot', {'kind': 'Depot'})
        batch = _batch('mapped')
        batch.account_assignments = {account_key('Source'): account_key('Depot')}
        batch.transactions = [BankTransaction(
            transaction.account, transaction.external_id, transaction.date, transaction.kind,
            transaction.amount, transaction.currency, security=transaction.security,
            quantity=transaction.quantity, fees=transaction.fees, taxes=transaction.taxes,
            performance_depot_key=account_key('Source'))
            for transaction in batch.transactions]
        repo.store.import_batch(batch)

        payloads = [json.loads(row['payload']) for row in repo.db.execute('SELECT payload FROM transactions')]
        assert {row['performance_depot_key'] for row in payloads} == {'depot'}
        assert repo.store.import_assignment_rows([1])[0]['target_key'] == 'depot'
    finally:
        repo.close()


@pytest.mark.parametrize('order', [('alpha', 'beta'), ('beta', 'alpha')])
def test_independent_batches_converge_to_the_same_semantic_state(tmp_path, order):
    actual = RepositoryV09(tmp_path / ('-'.join(order) + '.sqlite'), backups=False)
    expected = RepositoryV09(tmp_path / 'expected.sqlite', backups=False)
    try:
        for label in order:
            actual.store.import_batch(_batch(label, account='Depot'))
        for label in ('alpha', 'beta'):
            expected.store.import_batch(_batch(label, account='Depot'))
        assert _semantic_state(actual) == _semantic_state(expected)
    finally:
        actual.close()
        expected.close()
