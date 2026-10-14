import os
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from portfolio_v5.models import ImportBatch, Snapshot, Position, Transaction, Balance
from portman.repository import PortfolioRepository
from portman.performance_service import PerformanceService


class DepotAccountTests(unittest.TestCase):
    def make_batch(self):
        return ImportBatch('depots', 'depots', snapshots=[
            Snapshot(name, '2026-01', '2026-01-31', 'DEKA', [
                Position('DE0000000001', 'Titel', isin='DE0000000001', quantity='1', value=value)])
            for name, value in [('Deka/1', '100'), ('Deka/2', '200')]],
            transactions=[Transaction(name, 'same-id', '2026-01-01', 'DEPOSIT', '100', 'EUR')
                          for name in ['Deka/1', 'Deka/2']],
            balances=[Balance('2026-01', 'Wertpapiere', 'Deka', '300', 'ETF', 2)])

    def test_grouping_keeps_depot_snapshots_and_transactions_separate(self):
        with tempfile.TemporaryDirectory() as folder:
            repo = PortfolioRepository(Path(folder) / 'db.sqlite')
            repo.commit_batches([self.make_batch()])
            self.assertEqual(repo.accounts(), ['Deka'])
            self.assertEqual(len(repo.snapshots('Deka')), 2)
            self.assertEqual(len(repo.transactions('Deka')), 2)
            self.assertEqual(repo.current(account='Deka')[0]['value'], '300')
            self.assertEqual(PerformanceService(repo).valuation_series('Deka')[0]['value'], Decimal('300'))
            overview = repo.account_overview()[0]
            self.assertEqual(overview['depot_value'], Decimal('300'))
            self.assertEqual(overview['balance'], Decimal('200'))
            self.assertTrue(overview['cash_from_transactions'])
            self.assertEqual(len(overview['depots']), 2)
            repo.commit_batches([ImportBatch('new', 'new', snapshots=[
                Snapshot('Deka/1', '2026-02', '2026-02-28', 'DEKA', [
                    Position('DE0000000001', 'Titel', isin='DE0000000001', quantity='1', value='110')])])])
            self.assertEqual(repo.current(account='Deka')[0]['value'], '310')
            self.assertEqual(repo.account_overview('2026-01-31')[0]['depot_value'], Decimal('300'))
            self.assertIsNone(repo.account_overview('2025-12-31')[0]['depot_value'])
            repo.close()

    def test_manual_mapping_survives_import_and_restart_and_filters(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'db.sqlite'
            repo = PortfolioRepository(path)
            repo.commit_batches([self.make_batch()])
            repo.create_accounts(['Zielkonto'])
            repo.assign_depot('Deka/1', 'Zielkonto')
            repo.confirm_coverage('Zielkonto', '2026-01-01', '2026-01-31')
            repo.commit_batches([ImportBatch('tx', 'tx', transactions=[
                Transaction('Deka/1', 'new-id', '2026-01-10', 'DEPOSIT', '50', 'EUR')])])
            self.assertFalse(repo.has_coverage('Zielkonto', '2026-01-01', '2026-01-31'))
            repo.commit_batches([self.make_batch()])
            repo.close()
            repo = PortfolioRepository(path)
            self.assertEqual(repo.current(account='Zielkonto')[0]['value'], '100')
            self.assertEqual(repo.current(account='Deka')[0]['value'], '200')
            self.assertEqual(len(repo.transactions('Zielkonto')), 2)
            repo.set_account_active('Zielkonto', False)
            self.assertEqual(repo.current()[0]['value'], '200')
            self.assertEqual(len(repo.transactions()), 1)
            with self.assertRaises(ValueError):
                repo.assign_depot('Deka/2', 'Zielkonto')
            repo.close()

    def test_overview_widget_assignment(self):
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        from PySide6.QtWidgets import QApplication
        from portman.accounts_widget import AccountsWidget
        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as folder:
            repo = PortfolioRepository(Path(folder) / 'db.sqlite')
            repo.commit_batches([self.make_batch()])
            repo.create_accounts(['Zielkonto'])
            widget = AccountsWidget(repo, lambda: '9999-12-31')
            self.assertEqual(widget.tree.topLevelItemCount(), 2)
            self.assertEqual(widget.tree.topLevelItem(0).childCount(), 1)
            self.assertEqual(widget.tree.topLevelItem(0).child(0).childCount(), 0)
            widget.depot.setCurrentIndex(widget.depot.findData('Deka/1'))
            widget.account.setCurrentIndex(widget.account.findData('Zielkonto'))
            widget.assign.click()
            self.assertEqual(repo.current(account='Zielkonto')[0]['value'], '100')
            self.assertEqual(widget.tree.topLevelItem(0).childCount(), 1)
            widget.close()
            app.processEvents()
            repo.close()
