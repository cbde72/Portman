import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

from portfolio_v5.models import ImportBatch, Position, Snapshot
from portman.import_v09 import ImportSession, transaction
from portman.repository_v09 import RepositoryV09


class AtomicImportTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.path = Path(self.folder.name) / 'test.sqlite'
        self.repo = RepositoryV09(self.path, backups=False)
        self.job = SimpleNamespace(isInterruptionRequested=lambda: False,
                                   progress=SimpleNamespace(emit=lambda *args: None))
        self.batch = ImportBatch('test-import', 'test-hash', snapshots=[
            Snapshot('Depot', '2026-01', '2026-01-01', 'Test', [
                Position('US0378331005', 'Apple', isin='US0378331005', quantity='1', value='100')])])

    def tearDown(self):
        self.repo.close()
        self.folder.cleanup()

    def test_preview_does_not_commit_assets_or_imports(self):
        revision = self.repo.revision()
        with transaction(self.repo):
            ImportSession.apply(None, self.repo, self.job, ([self.batch], []))
            self.assertTrue(self.repo.db.in_transaction)
            self.assertEqual(self.repo.db.execute('SELECT count(*) FROM asset_positions').fetchone()[0], 1)
            with closing(sqlite3.connect(self.path, timeout=0)) as reader:
                self.assertEqual(reader.execute('SELECT count(*) FROM imports').fetchone()[0], 0)
        for table in ('imports', 'snapshots', 'security_master', 'asset_identity', 'asset_positions'):
            self.assertEqual(self.repo.db.execute(f'SELECT count(*) FROM {table}').fetchone()[0], 0)
        self.assertEqual(self.repo.revision(), revision)

    def test_failure_after_asset_sync_rolls_back_everything(self):
        with self.assertRaisesRegex(ValueError, 'cancelled'):
            with transaction(self.repo, commit=True):
                ImportSession.apply(None, self.repo, self.job, ([self.batch], []))
                raise ValueError('cancelled')
        self.assertEqual(self.repo.db.execute('SELECT count(*) FROM imports').fetchone()[0], 0)
        self.assertEqual(self.repo.db.execute('SELECT count(*) FROM asset_positions').fetchone()[0], 0)

    def test_commit_preserves_asset_identity_on_repeated_sync(self):
        with transaction(self.repo, commit=True):
            ImportSession.apply(None, self.repo, self.job, ([self.batch], []))
        uid = self.repo.assets.identity('US0378331005')
        with transaction(self.repo, commit=True):
            self.repo.assets.sync()
        self.assertEqual(self.repo.assets.identity('ISIN:US0378331005'), uid)
        self.assertEqual(self.repo.db.execute('SELECT count(*) FROM asset_positions').fetchone()[0], 1)
        self.assertEqual(self.repo.db.execute('SELECT count(*) FROM imports').fetchone()[0], 1)


if __name__ == '__main__':
    unittest.main()
