"""SQL-order characterization for the phase-3 persistence refactoring."""
import hashlib
import re
import sqlite3

import pytest

from portfolio_v5.models import Balance, BankTransaction, ImportBatch, Position, Snapshot, TaxEvent
from portman.import_v09 import transaction
from portman.repository_v09 import RepositoryV09


_TIMESTAMP = re.compile(r"'\d{4}-\d\d-\d\dT[^']+\+00:00'")


class Trace:
    def __init__(self, connection):
        self.statements = []
        connection.set_trace_callback(self.statements.append)

    @property
    def normalized(self):
        return [_TIMESTAMP.sub("'<timestamp>'", ' '.join(sql.split())) for sql in self.statements]

    @property
    def operations(self):
        result = []
        for sql in self.normalized:
            verb = sql.split(' ', 1)[0].upper()
            if verb in {'SELECT', 'INSERT', 'UPDATE', 'DELETE', 'BEGIN', 'COMMIT', 'ROLLBACK'}:
                result.append(verb)
        return result

    @property
    def digest(self):
        return hashlib.sha256('\n'.join(self.normalized).encode()).hexdigest()


def rich_batch(path='trace.csv', amount='-100'):
    return ImportBatch(
        path, 'same-source-content',
        snapshots=[
            Snapshot('Depot A', '2026-01', '2026-01-31', 'A', [
                Position('US0378331005', 'Apple', isin='US0378331005', quantity='1', value='100')]),
            Snapshot('Depot B', '2026-01', '2026-01-31', 'B', [
                Position('US5949181045', 'Microsoft', isin='US5949181045', quantity='2', value='200')]),
        ],
        balances=[Balance('2026-01', 'Cash', 'Cash A', '50', 'Cash', 1)],
        transactions=[
            BankTransaction('Depot A', 'buy-1', '2026-01-10', 'BUY', amount, 'EUR',
                            security='US0378331005', quantity='1', fees='1',
                            affects_cash=False),
            BankTransaction('Depot B', 'sell-1', '2026-01-20', 'SELL', '150', 'EUR',
                            security='US5949181045', quantity='1', taxes='5',
                            affects_cash=False),
        ],
        tax_events=[TaxEvent('tax-1', 'Depot A', 'ausschuettung', '2026-01-25',
                             taxable_income='20', capital_gains_tax='5')],
        account_names=['Cash A'],
    )


def state(repo):
    tables = ('imports', 'snapshots', 'balances', 'transactions', 'import_model_records',
              'depot_accounts', 'accounts')
    return {table: repo.db.execute(f'SELECT count(*) FROM {table}').fetchone()[0] for table in tables}


def test_successful_rich_import_has_stable_sql_order_and_counts(tmp_path):
    repo = RepositoryV09(tmp_path / 'trace.sqlite', backups=False)
    try:
        trace = Trace(repo.db)
        result = repo.store.import_batch(rich_batch())
        assert result == {'status': 'imported', 'snapshots': 2, 'balances': 1,
                          'transactions': 2, 'unchanged': 0, 'id': 1,
                          'documents': 0, 'model_records': 1}
        assert state(repo) == {'imports': 1, 'snapshots': 2, 'balances': 1, 'transactions': 2,
                               'import_model_records': 1, 'depot_accounts': 2, 'accounts': 3}
        assert {verb: trace.operations.count(verb) for verb in set(trace.operations)} == {
            'SELECT': 18, 'BEGIN': 1, 'INSERT': 101, 'COMMIT': 1,
        }
        assert trace.digest == '57a54c2cadd1287e2ca779ac9e1bf61105872cc59e65aab54499b06e76a419bd'
    finally:
        repo.close()


def test_duplicate_content_other_name_and_changed_content(tmp_path):
    repo = RepositoryV09(tmp_path / 'duplicates.sqlite', backups=False)
    try:
        first = repo.store.import_batch(rich_batch())
        trace = Trace(repo.db)
        duplicate = repo.store.import_batch(rich_batch('renamed.csv'))
        assert duplicate == {'status': 'duplicate', 'path': 'renamed.csv', 'id': first['id']}
        assert trace.operations.count('INSERT') == 0
        changed = rich_batch('changed.csv', '-101')
        changed.file_hash = 'changed-source-content'
        assert repo.store.import_batch(changed)['status'] == 'imported'
        assert state(repo)['imports'] == 2
    finally:
        repo.close()


@pytest.mark.parametrize('failure', ['mapping', 'transaction', 'snapshot'])
def test_pre_persistence_validation_has_no_writes(tmp_path, failure):
    repo = RepositoryV09(tmp_path / f'{failure}.sqlite', backups=False)
    try:
        batch = rich_batch()
        if failure == 'mapping':
            batch.account_assignments = {'unknown-source': 'unknown-target'}
        elif failure == 'transaction':
            batch.transactions[0].amount = 'NaN'
        else:
            batch.snapshots[0].as_of = 'not-a-date'
        trace = Trace(repo.db)
        with pytest.raises(ValueError):
            repo.store.import_batch(batch)
        assert not ({'INSERT', 'UPDATE', 'DELETE'} & set(trace.operations))
        assert state(repo)['imports'] == 0
    finally:
        repo.close()


def test_mid_persistence_failure_rolls_back_every_table(tmp_path):
    repo = RepositoryV09(tmp_path / 'rollback.sqlite', backups=False)
    try:
        repo.db.execute("CREATE TRIGGER fail_transactions BEFORE INSERT ON transactions "
                        "BEGIN SELECT RAISE(ABORT, 'phase3 failure'); END")
        trace = Trace(repo.db)
        with pytest.raises(sqlite3.IntegrityError, match='phase3 failure'):
            repo.store.import_batch(rich_batch())
        assert trace.operations[-1] == 'ROLLBACK'
        assert all(count == 0 for count in state(repo).values())
    finally:
        repo.close()


def test_multiple_batches_share_outer_atomic_rollback(tmp_path):
    repo = RepositoryV09(tmp_path / 'multi.sqlite', backups=False)
    try:
        with pytest.raises(ValueError, match='stop'):
            with transaction(repo, commit=True):
                repo.store.import_batch(rich_batch('first.csv'))
                second = rich_batch('second.csv')
                second.file_hash = 'second-content'
                repo.store.import_batch(second)
                raise ValueError('stop')
        assert all(count == 0 for count in state(repo).values())
    finally:
        repo.close()
