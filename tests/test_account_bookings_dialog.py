import os

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QTreeWidgetItem, QScrollArea
from portfolio_v5.models import ImportBatch, BankTransaction
from portman.repository import PortfolioRepository
from portman.accounts_widget import AccountsWidget
from portman.account_bookings_dialog import AccountBookingsDialog, TransactionEditDialog


def test_transaction_editor_scrolls_and_keeps_buttons_outside_scroll_area(tmp_path):
    app = QApplication.instance() or QApplication([])
    repo = PortfolioRepository(tmp_path / 'editor.sqlite')
    repo.commit_batches([ImportBatch('source', 'hash', transactions=[
        BankTransaction('A', 'booking', '2020-01-01', 'BANK_BOOKING', '1', 'EUR')])])
    dialog = TransactionEditDialog(repo, repo.transactions('A')[0])
    dialog.resize(620, 360)
    dialog.show()
    app.processEvents()
    assert dialog.findChild(QScrollArea) is dialog.scroll
    assert dialog.scroll.verticalScrollBar().maximum() > 0
    assert not dialog.scroll.isAncestorOf(dialog.buttons)
    assert dialog.height() <= dialog.screen().availableGeometry().height()
    dialog.close()
    repo.close()


def test_double_click_opens_all_account_bookings_without_date_limit(tmp_path):
    app = QApplication.instance() or QApplication([])
    repo = PortfolioRepository(tmp_path / 'test.sqlite')
    repo.commit_batches([ImportBatch('source', 'hash', transactions=[
        BankTransaction('A', str(i), '2020-01-01', 'BANK_BOOKING', '1', 'EUR', purpose=f'Buchung {i}')
        for i in range(500)] + [BankTransaction('B', 'other', '2020-01-01', 'BANK_BOOKING', '9', 'EUR')])])
    widget = AccountsWidget(repo, lambda: '2010-01-01')
    item = QTreeWidgetItem(['A'])
    item.setData(0, Qt.ItemDataRole.UserRole, 'A')
    widget.select_account(item, 0)
    dialog = widget.findChild(AccountBookingsDialog)
    assert dialog.isVisible()
    assert dialog.model.rowCount() == 500
    app.processEvents()
    assert dialog.table.verticalScrollBar().maximum() > 0
    dialog.table.scrollToBottom()
    assert dialog.table.verticalScrollBar().value() == dialog.table.verticalScrollBar().maximum()
    dialog.search.setText('Buchung 499')
    assert dialog.proxy.rowCount() == 1
    dialog.search.clear()
    assert dialog.proxy.rowCount() == 500
    dialog.close()
    widget.close()
    repo.close()


def test_running_sum_start_amount_search_and_invalid_input(tmp_path):
    QApplication.instance() or QApplication([])
    repo = PortfolioRepository(tmp_path / 'sums.sqlite')
    repo.commit_batches([ImportBatch('source', 'hash', transactions=[
        BankTransaction('A', 'credit', '2020-01-01', 'BANK_BOOKING', '100.10', 'EUR'),
        BankTransaction('A', 'debit', '2020-01-02', 'BANK_BOOKING', '-20.05', 'EUR'),
        BankTransaction('A', 'foreign', '2020-01-03', 'BANK_BOOKING', '900', 'USD'),
        BankTransaction('A', 'last', '2020-01-04', 'BANK_BOOKING', '0.01', 'EUR')])])
    dialog = AccountBookingsDialog(repo, 'A')
    assert [dialog.model.item(row, 5).text() for row in range(4)] == ['100,10 €', '80,05 €', '–', '80,06 €']
    dialog.start_amount.setText('1.000,00')
    assert dialog.model.item(3, 5).text() == '1.080,06 €'
    dialog.search.setText('2020-01-04')
    assert dialog.proxy.rowCount() == 1
    assert dialog.proxy.index(0, 5).data() == '1.080,06 €'
    dialog.start_amount.setText('ungültig')
    assert dialog.model.item(3, 5).text() == '–'
    dialog.start_amount.setText('-100,00')
    assert dialog.model.item(3, 5).text() == '-19,94 €'
    assert len(repo.imports()) == 1
    dialog.close()
    repo.close()


def test_booking_with_fee_has_light_blue_row(tmp_path):
    from PySide6.QtGui import QColor
    QApplication.instance() or QApplication([])
    repo = PortfolioRepository(tmp_path / 'fee-color.sqlite')
    repo.commit_batches([ImportBatch('source', 'hash', transactions=[
        BankTransaction('A', 'without-fee', '2020-01-01', 'BANK_BOOKING', '-10', 'EUR'),
        BankTransaction('A', 'with-fee', '2020-01-02', 'BANK_BOOKING', '-20', 'EUR', fees='0.62')])])
    dialog = AccountBookingsDialog(repo, 'A')

    assert dialog.model.item(0, 0).background().color() != QColor('#d9eeff')
    for column in range(dialog.model.columnCount()):
        assert dialog.model.item(1, column).background().color() == QColor('#d9eeff')
        assert dialog.model.item(1, column).foreground().color() == QColor('#102a43')

    dialog.close()
    repo.close()


def test_numeric_date_sort_and_selected_rows_copy(tmp_path):
    from PySide6.QtCore import QItemSelectionModel
    from portman.table_copy import copy_selected_rows
    QApplication.instance() or QApplication([])
    repo = PortfolioRepository(tmp_path / 'copy.sqlite')
    repo.commit_batches([ImportBatch('source', 'hash', transactions=[
        BankTransaction('A', 'first', '2020-01-31', 'BANK_BOOKING', '100', 'EUR'),
        BankTransaction('A', 'second', '2020-02-01', 'BANK_BOOKING', '9', 'EUR'),
        BankTransaction('A', 'third', '2021-01-01', 'BANK_BOOKING', '-20', 'EUR')])])
    dialog = AccountBookingsDialog(repo, 'A')
    dialog.table.sortByColumn(0, Qt.SortOrder.AscendingOrder)
    assert [dialog.proxy.index(i, 10).data() for i in range(3)] == ['first', 'second', 'third']
    dialog.table.sortByColumn(3, Qt.SortOrder.AscendingOrder)
    assert [dialog.proxy.index(i, 10).data() for i in range(3)] == ['third', 'second', 'first']
    selection = dialog.table.selectionModel()
    for row in (0, 2):
        selection.select(dialog.proxy.index(row, 0), QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows)
    copy_selected_rows(dialog.table)
    copied = QApplication.clipboard().text().splitlines()
    assert len(copied) == 3
    assert copied[1].endswith('third') and copied[2].endswith('first')
    assert dialog.model.item(1, 5).text() == '109,00 €'
    selection.clearSelection()
    copy_selected_rows(dialog.table)
    assert QApplication.clipboard().text().splitlines() == copied
    dialog.close()
    repo.close()
