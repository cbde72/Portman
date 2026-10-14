from portfolio_v5.models import ImportBatch, Snapshot, Position
from portman.repository import PortfolioRepository
from portman.automatic_bank_import import prepare_known_batches


def test_reuses_depot_link_and_deduplicates(tmp_path):
    repo = PortfolioRepository(tmp_path / 'sync.sqlite')
    try:
        previous = ImportBatch('online-depot', 'old', source_sheet='Online ING', snapshots=[
            Snapshot('Mein Depot', '2026-01', '2026-01-01', 'ING', [Position('A', 'Aktie', quantity='1', value='100')])])
        assert repo.commit_batches([previous])[0]['status'] == 'imported'
        incoming = ImportBatch('online-depot', 'new', source_sheet='Online ING', snapshots=[
            Snapshot('ING 123', '2026-02', '2026-02-01', 'ING', [Position('A', 'Aktie', quantity='2', value='200')])])
        batches, notes = prepare_known_batches(repo, [('ING', [incoming])])
        assert notes == [] and batches[0].snapshots[0].account == 'Mein Depot'
        assert incoming.snapshots[0].account == 'ING 123'
        assert repo.commit_batches(batches)[0]['status'] == 'imported'
        assert repo.commit_batches(batches)[0]['status'] == 'duplicate'
        assert repo.holdings()[0]['quantity'] == '2'
        assert len(repo.depots()) == 1
    finally:
        repo.store.db.close()


def test_unknown_sources_and_bad_batches_are_skipped(tmp_path):
    repo = PortfolioRepository(tmp_path / 'sync.sqlite')
    try:
        batches, notes = prepare_known_batches(repo, [('ING', [ImportBatch('new', 'a'),
            ImportBatch('bad', 'b', errors=['Fehler'])])])
        assert batches == [] and len(notes) == 2
    finally:
        repo.store.db.close()
