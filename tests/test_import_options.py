import os

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtWidgets import QApplication
from portfolio_v5.models import ImportBatch, BankTransaction, Snapshot, Position
from portman.repository import PortfolioRepository
from portman.import_options import ImportOptionsDialog


def test_repeat_choice_skips_or_forces_existing_without_writing(tmp_path):
    QApplication.instance() or QApplication([])
    repo = PortfolioRepository(tmp_path / 'test.sqlite')
    old = ImportBatch('old.csv', 'oldhash', source_sheet='CSV', transactions=[
        BankTransaction('A', '1', '2026-01-01', 'BANK_BOOKING', '1', 'EUR')])
    repo.commit_batches([old])
    new = ImportBatch('new.csv', 'newhash', source_sheet='CSV')
    dialog = ImportOptionsDialog(repo, [old, new])
    assert [b.file_hash for b in dialog.selected_batches()] == ['newhash']
    dialog.repeat.setChecked(True)
    selected = dialog.selected_batches()
    assert selected[0].force_import
    assert not selected[1].force_import
    assert not old.force_import
    dialog.reject()
    assert len(repo.imports()) == 1
    assert repo.commit_batches([selected[0]])[0]['status'] == 'imported'
    assert len(repo.transactions()) == 1
    dialog.close()
    repo.close()


def test_undone_imports_and_other_sheets_are_not_skipped(tmp_path):
    QApplication.instance() or QApplication([])
    repo = PortfolioRepository(tmp_path / 'test.sqlite')
    old = ImportBatch('old.xlsx', 'hash', source_sheet='A')
    result = repo.commit_batches([old])[0]
    other = ImportBatch('old.xlsx', 'hash', source_sheet='B')
    dialog = ImportOptionsDialog(repo, [other])
    assert len(dialog.selected_batches()) == 1
    dialog.close()
    repo.undo_import(result['id'])
    dialog = ImportOptionsDialog(repo, [old])
    assert len(dialog.selected_batches()) == 1
    dialog.close()
    repo.close()


def test_new_history_checkpoint_is_not_skipped(tmp_path):
    QApplication.instance() or QApplication([])
    repo = PortfolioRepository(tmp_path / 'checkpoint.sqlite')
    try:
        old = ImportBatch('online.bank', 'same', source_sheet='Online ING', history_end='2026-09-23')
        repo.commit_batches([old])
        new = ImportBatch('online.bank', 'same', source_sheet='Online ING', history_end='2026-09-24')
        dialog = ImportOptionsDialog(repo, [old, new])
        assert [b.history_end for b in dialog.selected_batches()] == ['2026-09-24']
        dialog.close()
    finally:
        repo.close()


def test_online_duplicates_skip_options_dialog(tmp_path, monkeypatch):
    from portman.import_options import choose_import_options
    QApplication.instance() or QApplication([])
    repo = PortfolioRepository(tmp_path / 'online.sqlite')
    try:
        old = ImportBatch('online.bank', 'old', source_sheet='Online ING')
        new = ImportBatch('online.bank', 'new', source_sheet='Online ING')
        repo.commit_batches([old])
        monkeypatch.setattr(ImportOptionsDialog, 'exec', lambda self: (_ for _ in ()).throw(AssertionError('Unexpected dialog')))
        assert [b.file_hash for b in choose_import_options(None, repo, [old, new])] == ['new']
    finally:
        repo.close()


def test_security_booking_is_enriched_before_preview(tmp_path):
    from portman.import_options import enrich_security_bookings
    from portman.repository_v09 import RepositoryV09
    repo = RepositoryV09(tmp_path / 'security-preview.sqlite', backups=False)
    try:
        repo.save_account('Cash', {'kind': 'Verrechnungskonto'})
        repo.save_account('Depot', {'kind': 'Depot', 'cash_account_key': 'cash'})
        repo.commit_batches([ImportBatch('holding', 'holding', snapshots=[Snapshot(
            'Depot', '2026-01', '2026-01-01', 'Test', [Position(
                'WKN:A111X9', 'IS C.MSCI EMIMI U.ETF DLA', wkn='A111X9', quantity='1', value='100')])])])
        batch = ImportBatch('booking', 'booking', transactions=[BankTransaction(
            'Noch nicht zugeordnetes Bankkonto', 'buy', '2026-01-02', 'BANK_BOOKING', '-50', 'EUR',
            purpose='IS C.MSCI EMIMI U.ETF DLA WPKNR: A111X9 ISIN: IE00BKM4GZ66 2MDJ/2',
            operation='Wertpapiere')])
        enrich_security_bookings(repo, [batch])
        tx = batch.transactions[0]
        assert (tx.kind, tx.security, tx.performance_depot_key) == ('BUY', 'IE00BKM4GZ66', 'depot')
    finally:
        repo.close()
