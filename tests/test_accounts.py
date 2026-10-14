import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from portfolio_v5.accounts import discover_accounts, overview_accounts
from portfolio_v5.models import Balance, ImportBatch, Position, Snapshot, Transaction
from portman.repository import PortfolioRepository


class AccountTests(unittest.TestCase):
    def test_only_account_block_and_empty_accounts(self):
        rows = [[2026, 'Festgeld'], [' ING '], [None, 10], ['ing diba'],
                ['Leeres Konto'], ['Gesamt'], ['Aktien'], ['Anleihen']]
        self.assertEqual([x['name'] for x in overview_accounts(rows)], ['Ing Diba', 'Leeres Konto'])
        with self.assertRaises(ValueError):
            overview_accounts([['Konto'], ['Aktien']])

    def test_discovery_continues_after_bad_file(self):
        with tempfile.TemporaryDirectory() as folder:
            for name in ['a.xls', 'b.xlsx', 'c.xlsx', '~$lock.xlsx']:
                Path(folder, name).touch()
            def read(path, sheet_name):
                if path.name == 'a.xls':
                    raise ValueError('defekt')
                return {'ETF': [[2026], ['Konto'], ['Sparen'], ['Gesamt']]}
            with patch('portfolio_v5.importers.read_sheets', side_effect=read):
                result = discover_accounts(folder)
            self.assertEqual(result['files'], 3)
            self.assertEqual(len(result['warnings']), 1)
            self.assertEqual(result['accounts'][0]['name'], 'Sparen')
            self.assertEqual(len(result['accounts'][0]['sources']), 2)

    def test_removal_filters_all_data_and_survives_reimport_and_restart(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'test.sqlite'
            repo = PortfolioRepository(path)
            batch = ImportBatch('x', 'hash',
                snapshots=[Snapshot('ING', '2026-01', '2026-01-31', 'ing',
                                    [Position('DE0000000001', 'Test', isin='DE0000000001', quantity='1', value='100')])],
                balances=[Balance('2026-01', 'Liquidität', 'Ing Diba', '50', 'ETF', 2),
                          Balance('2026-01', 'Liquidität', 'Andere Bank', '20', 'ETF', 3)],
                transactions=[Transaction('ING', '1', '2026-01-01', 'DEPOSIT', '100', 'EUR')],
                account_names=['Ing Diba', 'Ohne Guthaben'])
            repo.commit_batches([batch])
            self.assertEqual(repo.accounts().count('Ing Diba'), 1)
            self.assertIn('Ohne Guthaben', repo.accounts())
            self.assertEqual(len(repo.current(account='Ing Diba')), 1)
            self.assertEqual(len(repo.transactions('Ing Diba')), 1)
            repo.set_account_active('ING', False)
            self.assertFalse(repo.current())
            self.assertFalse(repo.transactions())
            self.assertEqual(repo.wealth_series()[0]['total'], 20)
            self.assertEqual(repo.commit_batches([batch])[0]['status'], 'duplicate')
            repo.close()
            repo = PortfolioRepository(path)
            self.assertNotIn('Ing Diba', repo.accounts())
            self.assertEqual(repo.create_accounts([' ing  diba ']), 0)
            self.assertNotIn('Ing Diba', repo.accounts())
            repo.set_account_active('Ing Diba', True)
            self.assertEqual(len(repo.current()), 1)
            self.assertEqual(repo.wealth_series(account='Ing Diba')[0]['total'], 50)
            self.assertEqual(len(repo.transactions()), 1)
            repo.close()

    def test_manual_account_validation_and_persistence(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'test.sqlite'
            repo = PortfolioRepository(path)
            with self.assertRaises(ValueError):
                repo.create_accounts([' '])
            self.assertEqual(repo.create_accounts(['Mein Konto', ' mein  konto ']), 1)
            repo.close()
            repo = PortfolioRepository(path)
            self.assertIn('Mein Konto', repo.accounts())
            repo.close()

    def test_alias_transaction_invalidates_confirmed_coverage(self):
        with tempfile.TemporaryDirectory() as folder:
            repo = PortfolioRepository(Path(folder) / 'test.sqlite')
            repo.confirm_coverage('Ing Diba', '2026-01-01', '2026-01-31')
            self.assertTrue(repo.has_coverage('ING', '2026-01-01', '2026-01-31'))
            repo.commit_batches([ImportBatch('tx', 'tx', transactions=[
                Transaction('ING', '1', '2026-01-10', 'DEPOSIT', '50', 'EUR')])])
            self.assertFalse(repo.has_coverage('Ing Diba', '2026-01-01', '2026-01-31'))
            repo.close()

    def test_preview_selection_and_management(self):
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QApplication
        from portman.accounts_dialog import AccountImportPreview, AccountsDialog
        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as folder:
            repo = PortfolioRepository(Path(folder) / 'test.sqlite')
            repo.create_accounts(['Entfernt'])
            repo.set_account_active('Entfernt', False)
            result = {'files': 1, 'warnings': [], 'accounts': [
                {'name': 'Entfernt', 'sources': ['x / ETF!A2']},
                {'name': 'Neu', 'sources': ['x / ETF!A3']}]}
            preview = AccountImportPreview(result, repo)
            self.assertEqual(preview.selected_names(), ['Neu'])
            preview.table.item(1, 0).setCheckState(Qt.CheckState.Unchecked)
            self.assertEqual(preview.selected_names(), [])
            dialog = AccountsDialog(repo, folder)
            dialog.table.selectRow(0)
            self.assertTrue(dialog.restore_button.isEnabled())
            dialog.set_active(True)
            self.assertIn('Entfernt', repo.accounts())
            dialog.table.selectRow(0)
            dialog.set_active(False)
            self.assertNotIn('Entfernt', repo.accounts())
            dialog.close()
            preview.close()
            app.processEvents()
            repo.close()
