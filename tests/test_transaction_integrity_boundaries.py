"""Integrity contract for transaction collisions and validation severity.

Changed source rows may form a new revision in storage.  The guided V09 import
must nevertheless surface an identity collision before either revision becomes
active in the user's economic view.  Structural numeric errors are blocking;
historically plausible sign/content deviations remain explicit audit warnings.
"""

from copy import deepcopy

import pytest

from portfolio_v5.models import BankTransaction, ImportBatch, Transaction
from portman.import_v09 import ImportSession
from portman.repository_v09 import RepositoryV09


@pytest.fixture
def repo(tmp_path):
    repository = RepositoryV09(tmp_path / 'portfolio.sqlite', backups=False)
    yield repository
    repository.close()


def booking(**changes):
    values = dict(account='Bank', external_id='shared-id', date='2026-01-10',
                  kind='BANK_BOOKING', amount='100.00', currency='EUR', security='DE000BASE001')
    values.update(changes)
    return BankTransaction(**values)


@pytest.mark.parametrize(('field', 'value'), [
    ('amount', '101.00'),
    ('currency', 'USD'),
    ('kind', 'FEE'),
    ('security', 'DE000OTHER01'),
])
def test_guided_import_surfaces_same_identity_with_changed_economic_fact(repo, field, value):
    repo.commit_batches([ImportBatch('first.csv', 'first-source', transactions=[booking()])])
    changed = booking(**{field: value})
    batch = ImportBatch(f'changed-{field}.csv', f'changed-{field}', transactions=[changed])
    session = ImportSession(repo.store.path, [batch])
    conflicts = session.conflicts([batch])
    assert len(conflicts) == 1
    assert conflicts[0]['id_match'] is True
    assert conflicts[0]['old']['external_id'] == changed.external_id
    assert conflicts[0]['new'][field] == value
    with pytest.raises(ValueError, match='ausdrücklich'):
        session.resolve([batch], {})


def test_explicit_keep_renames_colliding_identity_and_preserves_both(repo):
    repo.commit_batches([ImportBatch('first.csv', 'first-source', transactions=[booking()])])
    batch = ImportBatch('changed.csv', 'changed-source', transactions=[booking(amount='101.00')])
    session = ImportSession(repo.store.path, [batch])
    conflicts = session.conflicts([batch])
    selected, replacements = session.resolve(
        [deepcopy(batch)], {conflicts[0]['key']: {'action': 'keep'}})
    assert replacements == []
    assert selected[0].transactions[0].external_id.startswith('shared-id:v09:')


@pytest.mark.parametrize(('transaction', 'warning'), [
    (Transaction('Depot', 'buy-positive', '2026-01-01', 'BUY', '100', 'EUR'),
     'Kauf mit positivem Betrag'),
    (Transaction('Depot', 'fee-positive', '2026-01-01', 'FEE', '5', 'EUR'),
     'Gebührenbuchung muss als negativer Geldbetrag'),
    (Transaction('Depot', 'tax-refund-negative', '2026-01-01', 'TAX_REFUND', '-5', 'EUR'),
     'Steuererstattung muss als positiver Geldbetrag'),
])
def test_economic_sign_deviations_are_persisted_only_with_audit_warning(repo, transaction, warning):
    result = repo.commit_batches([ImportBatch(transaction.external_id, transaction.external_id,
                                               transactions=[transaction])])[0]
    assert result['status'] == 'imported'
    assert any(warning in message for message in result['warnings'])
    assert len(repo.transactions()) == 1


@pytest.mark.parametrize('amount', ['NaN', 'Infinity', '1E+2'])
def test_noncanonical_or_nonfinite_amount_is_blocking_and_atomic(repo, amount):
    result = repo.commit_batches([ImportBatch('invalid.csv', 'invalid-source', transactions=[
        Transaction('Bank', 'invalid', '2026-01-01', 'BANK_BOOKING', amount, 'EUR')])])[0]
    assert result['status'] == 'error'
    assert repo.transactions() == []
    assert repo.db.execute('SELECT count(*) FROM imports').fetchone()[0] == 0
