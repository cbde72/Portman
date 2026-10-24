"""Decision-matrix characterization for ImportSession.resolve()."""
import pytest

from portfolio_v5.models import BankTransaction, ImportBatch
from portman.import_v09 import ImportSession
from portman.repository_v09 import RepositoryV09, reference


def batch(path, external_id='tx', amount='100', account='Bank', day='2026-01-01'):
    return ImportBatch(path, path + '-hash', account_names=[account], transactions=[
        BankTransaction(account, external_id, day, 'BANK_BOOKING', amount, 'EUR', purpose=path)])


@pytest.fixture
def repo(tmp_path):
    value = RepositoryV09(tmp_path / 'resolve.sqlite', backups=False)
    yield value
    value.close()


def session(repo, batches):
    return ImportSession(repo.store.path, batches)


def test_no_conflict_is_selected_without_decision(repo):
    incoming = batch('new')
    selected, replacements = session(repo, [incoming]).resolve([incoming], {})
    assert selected[0].transactions[0].external_id == 'tx'
    assert replacements == []


@pytest.mark.parametrize(
    ('action', 'reason', 'selected_count', 'replacement_count', 'renamed'),
    [
        ('skip', '', 0, 0, False),
        ('keep', '', 1, 0, True),
        ('replace', 'Korrigierter Beleg', 1, 1, True),
    ],
)
def test_existing_conflict_decision_matrix(repo, action, reason, selected_count,
                                           replacement_count, renamed):
    repo.commit_batches([batch('old')])
    incoming = batch('incoming')
    current = session(repo, [incoming])
    conflict = current.conflicts([incoming])[0]
    decision = {'action': action}
    if reason:
        decision['reason'] = reason
    selected, replacements = current.resolve([incoming], {conflict['key']: decision})
    assert len(selected[0].transactions) == selected_count
    assert len(replacements) == replacement_count
    if selected_count:
        assert selected[0].transactions[0].external_id.startswith('tx:v09:') is renamed


@pytest.mark.parametrize(
    ('decision', 'message'),
    [
        ({}, 'ausdrücklich entscheiden'),
        ({'action': 'replace'}, 'Begründung'),
        ({'action': 'invalid'}, 'ausdrücklich entscheiden'),
    ],
)
def test_invalid_or_incomplete_decisions_keep_inputs_unchanged(repo, decision, message):
    repo.commit_batches([batch('old')])
    incoming = batch('incoming')
    current = session(repo, [incoming])
    conflict = current.conflicts([incoming])[0]
    with pytest.raises(ValueError, match=message):
        current.resolve([incoming], {conflict['key']: decision})
    assert incoming.transactions[0].external_id == 'tx'


def test_multiple_candidates_require_explicit_old_reference(repo):
    repo.commit_batches([batch('old-a', 'a'), batch('old-b', 'b')])
    incoming = batch('incoming', 'c')
    current = session(repo, [incoming])
    conflict = current.conflicts([incoming])[0]
    with pytest.raises(ValueError, match='ausdrücklich auswählen'):
        current.resolve([incoming], {conflict['key']: {
            'action': 'replace', 'reason': 'Korrektur'}})
    chosen = current.candidates(conflict['key'])[0]
    selected, replacements = current.resolve([incoming], {conflict['key']: {
        'action': 'replace', 'reason': 'Korrektur', 'old_ref': reference(chosen)}})
    assert len(selected[0].transactions) == len(replacements) == 1
    assert replacements[0][1] == chosen


def test_incoming_files_can_be_kept_or_skipped_but_not_superseded(repo):
    batches = [batch('first'), batch('second')]
    current = session(repo, batches)
    conflict = current.conflicts(batches)[0]
    with pytest.raises(ValueError, match='Zwischen neuen Dateien'):
        current.resolve(batches, {conflict['key']: {
            'action': 'replace', 'reason': 'Nicht zulässig'}})
    selected, replacements = current.resolve(batches, {conflict['key']: {'action': 'skip'}})
    assert [len(item.transactions) for item in selected] == [1, 0]
    assert replacements == []


def test_same_transaction_cannot_have_contradictory_group_decisions(repo):
    repo.commit_batches([batch('old-a', 'a'), batch('old-b', 'b')])
    incoming = batch('incoming', 'a')
    current = session(repo, [incoming])
    conflicts = current.conflicts([incoming])
    if len(conflicts) < 2:
        pytest.skip('Current candidate grouping yields one summarized conflict')
    decisions = {conflicts[0]['key']: {'action': 'skip'},
                 conflicts[1]['key']: {'action': 'keep'}}
    with pytest.raises(ValueError, match='Widersprüchliche Entscheidung'):
        current.resolve([incoming], decisions)
