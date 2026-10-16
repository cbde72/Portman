import sqlite3
import json
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

from portfolio_v5.models import BankTransaction, ImportBatch, Kind, Position, Snapshot, Transaction
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

    def test_import_report_records_validation_warning_and_parser_provenance(self):
        batch = ImportBatch('audit.csv', 'audit-hash', transactions=[
            Transaction('Cash', 'bad-date', '2026-01-01', 'BUY', '-90', 'EUR',
                        gross_amount='100', fees='1')])
        batch.plugin_id = 'test.plugin'
        batch.plugin_version = '2.1'
        batch.plugin_handler = 'statement'
        batch.detection_confidence = .94
        result = self.repo.store.import_batch(batch)
        report = json.loads(self.repo.imports()[0]['report'])
        self.assertEqual(result['status'], 'imported')
        self.assertTrue(any('Brutto/Netto' in warning for warning in report['warnings']))
        self.assertEqual(report['parser_provenance'], {
            'plugin_id': 'test.plugin', 'plugin_version': '2.1',
            'handler': 'statement', 'detection_confidence': .94})

    def test_import_rejects_advance_lump_sum_with_cash_effect(self):
        batch = ImportBatch('advance.csv', 'advance-hash', transactions=[
            BankTransaction('Cash', 'advance', '2026-01-01', Kind.ADVANCE_LUMP_SUM,
                '-7.91', 'EUR', taxes='7.91', advance_tax_base='31.64',
                advance_tax_currency='EUR')])
        with self.assertRaisesRegex(ValueError, 'Vorabpauschale'):
            self.repo.store.import_batch(batch)
        self.assertEqual(self.repo.db.execute('SELECT count(*) FROM imports').fetchone()[0], 0)

    def test_import_rejects_noncanonical_or_nonfinite_transaction_numbers(self):
        for external_id, amount in (('comma', '1,23'), ('nonfinite', 'NaN'), ('exponent', '1E+3')):
            batch = ImportBatch(external_id + '.csv', external_id + '-hash', transactions=[
                Transaction('Cash', external_id, '2026-01-01', Kind.BANK_BOOKING, amount, 'EUR')])
            with self.subTest(external_id=external_id), self.assertRaises(ValueError):
                self.repo.store.import_batch(batch)


if __name__ == '__main__':
    unittest.main()
