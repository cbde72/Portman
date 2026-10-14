import os

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import QDate
from PySide6.QtWidgets import QApplication
from portfolio_v5.models import ImportBatch, Snapshot, Position, BankTransaction
from portman.repository_v09 import RepositoryV09
from portman.cost_split_dialog import CostSplitDialog

KEY = 'US67066G1040'


def opening(repo):
    repo.commit_batches([ImportBatch('opening', 'opening', snapshots=[
        Snapshot('Depot', '2023-09', '2023-09-30', 'Beleg', [
            Position(KEY, 'Nvidia', isin=KEY, quantity='2', value='100')])])])


def test_cost_and_split_survive_later_online_snapshot_and_undo(tmp_path):
    repo = RepositoryV09(tmp_path / 'test.sqlite', backups=False)
    try:
        opening(repo)
        p = repo.holdings()[0]
        repo.correct_cost(p['snapshot_id'], KEY, '80', 'Kaufbeleg')
        repo.commit_batches([ImportBatch('buy', 'buy', transactions=[
            BankTransaction('Depot', 'buy', '2024-01-01', 'BUY', '-30', 'EUR', security=KEY, quantity='1')])])
        repo.add_action('2024-06-10', 'Depot', KEY, 'SPLIT', 'Splitbeleg', ratio='10')
        assert repo.holdings('2024-06-09')[0]['quantity'] == '3'
        p = repo.holdings('2024-06-10')[0]
        assert (p['quantity'], p['cost']) == ('30', '110.00')
        repo.commit_batches([ImportBatch('online', 'online', snapshots=[
            Snapshot('Depot', '2024-06', '2024-06-30', 'Online', [
                Position(KEY, 'Nvidia', isin=KEY, quantity='30', value='500')])])])
        assert repo.holdings()[0]['cost'] == '110.00'
        assert repo.holdings()[0]['quantity'] == '30'
        repo.add_action('2024-07-01', 'Depot', KEY, 'SPLIT', 'Zusammenlegung', ratio='0.1')
        p = repo.holdings()[0]
        assert p['quantity'] == '3.0' and p['cost'] == '110.00'
        repo.revoke_action(repo.actions('2024-06-30', '2024-07-01')[0]['id'], 'Test')
        assert repo.holdings()[0]['quantity'] == '30'
    finally:
        repo.close()


def test_dialog_saves_historical_cost_and_split(tmp_path):
    QApplication.instance() or QApplication([])
    repo = RepositoryV09(tmp_path / 'dialog.sqlite', backups=False)
    try:
        opening(repo)
        dialog = CostSplitDialog(repo)
        dialog.day.setDate(QDate(2023, 9, 30))
        dialog.cost.setText('80,00')
        dialog.source.setText('Alter Kaufbeleg')
        dialog.accept()
        assert dialog.result() == 1
        assert repo.holdings()[0]['cost'] == '80.00'
        split = CostSplitDialog(repo)
        split.day.setDate(QDate(2024, 6, 10))
        split.mode.setCurrentIndex(1)
        split.source.setText('Splitmitteilung')
        split.accept()
        assert split.result() == 1
        p = repo.holdings()[0]
        assert p['quantity'] == '20' and p['cost'] == '80.00'
        duplicate = CostSplitDialog(repo)
        duplicate.day.setDate(QDate(2024, 6, 10))
        duplicate.mode.setCurrentIndex(1)
        duplicate.source.setText('Doppelt')
        duplicate.accept()
        assert duplicate.result() == 0 and 'bereits' in duplicate.error.text()
    finally:
        repo.close()
