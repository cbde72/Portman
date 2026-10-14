import os
from decimal import Decimal
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from portman.repository import PortfolioRepository
from portman.repository_v09 import RepositoryV09
from portfolio_v5.models import ImportBatch, Transaction
import pytest

@pytest.mark.parametrize('repository', [PortfolioRepository, RepositoryV09])
def test_balances_follow_bookings_in_both_directions(tmp_path, repository):
    repo = repository(tmp_path / 'balance.sqlite')
    repo.save_account('Bank', {})
    repo.add_balance('Bank', '100', '2026-02-10')
    batch = ImportBatch('bookings', 'bookings', transactions=[
        Transaction('Bank', '1', '2026-02-05', 'DEPOSIT', '20', 'EUR'),
        Transaction('Bank', '2', '2026-02-10', 'WITHDRAWAL', '-10', 'EUR'),
        Transaction('Bank', '3', '2026-02-12', 'WITHDRAWAL', '-30', 'EUR'),
        Transaction('Bank', '4', '2026-02-13', 'DEPOSIT', '999', 'USD'),
    ])
    repo.commit_batches([batch])
    repo.commit_batches([batch])
    def balance(day): return repo.account_overview(day)[0]['balance']
    assert balance('2026-02-04') == Decimal('90')
    assert balance('2026-02-05') == Decimal('110')
    assert balance('2026-02-10') == Decimal('100')
    assert balance('2026-02-13') == Decimal('70')
    repo.close()

def test_unanchored_transactions_and_display(tmp_path):
    from portman.date_display import display_dates
    repo = PortfolioRepository(tmp_path / 'sum.sqlite')
    repo.commit_batches([ImportBatch('bookings', 'bookings', transactions=[
        Transaction('Bank', '1', '2026-02-05', 'DEPOSIT', '20', 'EUR'),
        Transaction('Bank', '2', '2026-03-01', 'WITHDRAWAL', '-5', 'EUR')])])
    assert repo.account_overview('2026-02-28')[0]['balance'] == Decimal('20')
    assert repo.account_overview('2026-03-01')[0]['balance'] == Decimal('15')
    assert 'Startsaldo 0' in repo.account_overview()[0]['categories']
    assert display_dates('2026-02-05 bis 2026-03-01') == '05.02.2026 bis 01.03.2026'
    repo.close()


def test_depot_cash_and_value_are_visible(tmp_path):
    from PySide6.QtWidgets import QApplication
    from portman.accounts_widget import AccountsWidget
    from portfolio_v5.models import Snapshot, Position
    QApplication.instance() or QApplication([])
    repo = PortfolioRepository(tmp_path / 'depot.sqlite')
    repo.commit_batches([ImportBatch('depot', 'depot',
        snapshots=[Snapshot('Depot', '2026-02', '2026-02-05', 'Depot',
                            [Position('s', 'Aktie', quantity='1', value='100')])],
        transactions=[Transaction('Depot', '1', '2026-02-05', 'DEPOSIT', '25', 'EUR')])])
    widget = AccountsWidget(repo, lambda: '2026-02-05')
    group = widget.tree.topLevelItem(0)
    assert group.text(6) == '125,00 €'
    assert group.child(0).text(2) == '25,00 €'
    assert group.child(0).text(4) == '05.02.2026'
    widget.close()
    repo.close()


def test_date_editor_keeps_iso_storage():
    from PySide6.QtWidgets import QApplication, QLineEdit
    from portman.date_edit import DateLineEdit
    QApplication.instance() or QApplication([])
    editor = DateLineEdit('2026-02-05')
    assert QLineEdit.text(editor) == '05.02.2026'
    assert editor.text() == '2026-02-05'
    editor.setText('09.03.2025')
    assert editor.text() == '2025-03-09'
    editor.close()
