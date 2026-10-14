import os
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from portfolio_v5.models import Balance, ImportBatch, Position, Snapshot
from portman.repository import PortfolioRepository


class DashboardWealthTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.repo = PortfolioRepository(Path(self.folder.name) / 'db.sqlite')
        self.repo.commit_batches([ImportBatch('jan', 'jan', balances=[
            Balance('2026-01', 'Liquidität', 'Bank', '100', 'ETF', 2),
            Balance('2026-01', 'Wertpapiere', 'Bank', '200', 'ETF', 2),
            Balance('2026-01', 'Altersvorsorge', 'Rente', '50', 'ETF', 3),
            Balance('2026-01', 'Schulden', 'Kredit', '30', 'ETF', 4),
            Balance('2026-01', 'Immobilie (Schätzung)', 'Archiv', '500000', 'verlauf', 2, 10)],
            snapshots=[Snapshot('Bank', '2026-01', '2026-01-31', 'Bank', [
                Position('DE0000000001', 'Titel', isin='DE0000000001', quantity='1', value='200')])])])

    def tearDown(self):
        self.repo.close()
        self.folder.cleanup()

    def test_net_wealth_includes_retirement_without_double_counting_depot(self):
        self.assertEqual(self.repo.wealth_summary()['value'], Decimal('320'))
        self.assertEqual(self.repo.wealth_summary(account='Bank')['value'], Decimal('300'))
        self.repo.set_account_active('Rente', False)
        self.assertEqual(self.repo.wealth_summary()['value'], Decimal('270'))

    def test_stichtag_missing_account_and_zero(self):
        self.assertIsNone(self.repo.wealth_summary('2025-12-31')['value'])
        self.repo.commit_batches([ImportBatch('feb', 'feb', balances=[
            Balance('2026-02', 'Liquidität', 'Bank', '0', 'ETF', 2)])])
        self.assertEqual(self.repo.wealth_summary()['value'], Decimal('220'))
        self.assertEqual(self.repo.wealth_summary(account='Rente')['value'], Decimal('50'))
        self.assertEqual(self.repo.wealth_summary('2026-01-31')['value'], Decimal('320'))

    def test_dashboard_card_follows_scope(self):
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        from PySide6.QtWidgets import QApplication
        from portman.dashboard_widget import DashboardWidget
        app = QApplication.instance() or QApplication([])
        scope = [None, '9999-12-31']
        widget = DashboardWidget(self.repo, lambda: tuple(scope))
        self.assertEqual(widget.cards['wealth'].text(), '320,00 €')
        self.assertIn('01.2026', widget.wealth_note.text())
        scope[0] = 'Rente'
        widget.refresh()
        self.assertEqual(widget.cards['wealth'].text(), '50,00 €')
        self.assertEqual(widget.wealth_box.title(), 'Kontovermögen · Rente')
        scope[1] = '2025-12-31'
        widget.refresh()
        self.assertEqual(widget.cards['wealth'].text(), '–')
        widget.visuals.chart_loader.shutdown()
        widget.close()
        app.processEvents()
