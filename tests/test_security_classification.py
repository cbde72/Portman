import os
from types import SimpleNamespace
from unittest.mock import patch

import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from portfolio_v5.models import ImportBatch, Snapshot, Position
from portman.repository import PortfolioRepository


def batch(version='1', asset_type='ETF', isin='DE0000000001', wkn=''):
    key = isin or 'WKN:' + wkn
    return ImportBatch('source', version, snapshots=[Snapshot('Depot', '2026-09', '2026-09-01', 'Test',
        [Position(key, 'Testfonds', isin=isin, wkn=wkn, quantity='10', value=str(100 + int(version)), asset_type=asset_type)])])


def test_overrides_survive_import_restart_and_broad_metadata_saves(tmp_path):
    path = tmp_path / 'db.sqlite'
    repo = PortfolioRepository(path); repo.commit_batches([batch()])
    key = 'DE0000000001'
    original = repo.security_classification(key)['base']
    repo.save_security_classification(key, {'asset_type': 'Anleihe', 'region': 'Europa', 'cap_size': 'Nicht zutreffend'})
    current = repo.current()[0]
    assert [current[f] for f in original] == ['Anleihe', 'Europa', 'Nicht zutreffend']
    repo.save_metadata([SimpleNamespace(**{**current, 'beta': 1.2, 'volatility': 10, 'dividend_yield': 3})])
    assert repo.security_classification(key)['base'] == original
    assert repo.metadata()[key]['beta'] == 1.2
    repo.commit_batches([batch('2')]); repo.close()
    repo = PortfolioRepository(path)
    assert repo.current()[0]['asset_type'] == 'Anleihe'
    assert repo.current()[0]['region'] == 'Europa'
    repo.save_security_classification(key, {'region': None})
    assert repo.current()[0]['region'] == original['region']
    assert repo.current()[0]['asset_type'] == 'Anleihe'
    repo.save_security_classification(key, {field: None for field in original})
    repo.close(); repo = PortfolioRepository(path)
    assert {field: repo.current()[0][field] for field in original} == original
    assert repo.metadata()[key]['beta'] == 1.2
    repo.close()


def test_wkn_identity_and_validation(tmp_path):
    repo = PortfolioRepository(tmp_path / 'db.sqlite')
    repo.commit_batches([batch(isin='', wkn='123456')])
    repo.save_security_classification('WKN:123456', {'asset_type': 'Fonds', 'cap_size': 'All Cap'})
    assert repo.current()[0]['asset_type'] == 'Fonds'
    assert repo.current()[0]['cap_size'] == 'All Cap'
    for key, values in [('WKN:123456', {'region': 'invalid'}), ('WKN:123456', {'typo': 'ETF'}), ('missing', {'region': 'Europa'})]:
        with pytest.raises(ValueError): repo.save_security_classification(key, values)
    assert repo.current()[0]['asset_type'] == 'Fonds'
    repo.close()


def test_later_isin_resolves_to_stable_wkn_master_key(tmp_path):
    repo = PortfolioRepository(tmp_path / 'alias.sqlite')
    repo.commit_batches([batch(isin='', wkn='123456')])
    repo.commit_batches([batch('2', isin='DE0000000001', wkn='123456')])
    assert repo.db.execute(
        'SELECT security_key FROM security_master WHERE isin=?', ('DE0000000001',)).fetchone()[0] == 'WKN:123456'

    state = repo.security_classification('DE0000000001')
    assert state['name'] == 'Testfonds'
    repo.save_security_classification('DE0000000001', {'region': 'Europa'})
    assert repo.security_classification('WKN:123456')['overrides']['region'] == 'Europa'
    repo.close()


def test_position_editor_handles_a_genuinely_stale_row(qtbot):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QTableWidget, QTableWidgetItem
    from portman.gui.position_tables import open_position_editor

    table = QTableWidget(1, 1)
    item = QTableWidgetItem('missing')
    item.setData(Qt.ItemDataRole.UserRole, 'missing')
    table.setItem(0, 0, item)
    qtbot.addWidget(table)
    window = SimpleNamespace(
        tables={'Alle': table}, get_current_category=lambda: 'Alle',
        repository=SimpleNamespace(db=SimpleNamespace(total_changes=0)), reload_portfolio=lambda: None)
    with patch('portman.classification_dialog.WertpapierEditDialog',
               side_effect=ValueError('Wertpapier nicht gefunden')), \
         patch('portman.gui.position_tables.QMessageBox.warning') as warning:
        open_position_editor(window, table.model().index(0, 0))
    warning.assert_called_once()


def test_dialog_reset_cancel_and_save(tmp_path, qtbot):
    from PySide6.QtWidgets import QApplication
    from portman.classification_dialog import ClassificationDialog
    app = QApplication.instance() or QApplication([])
    repo = PortfolioRepository(tmp_path / 'db.sqlite'); repo.commit_batches([batch()])
    key = 'DE0000000001'
    dialog = ClassificationDialog(repo, key)
    for field, value in [('asset_type', 'Fonds'), ('region', 'USA'), ('cap_size', 'Small')]:
        dialog.fields[field].setCurrentIndex(dialog.fields[field].findData(value))
    dialog.save()
    assert repo.current()[0]['region'] == 'USA'
    canceled = ClassificationDialog(repo, key)
    canceled.reset_fields(); canceled.reject()
    assert repo.current()[0]['region'] == 'USA'
    reset = ClassificationDialog(repo, key)
    reset.reset_fields(); reset.save()
    assert repo.current()[0]['region'] == 'Unbekannt'
    assert repo.current()[0]['asset_type'] == 'ETF'
    for d in [dialog, canceled, reset]:
        qtbot.addWidget(d)
        d.close()
    app.processEvents(); repo.close()


def test_name_double_click_uses_sorted_row_identity(tmp_path, qtbot):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QMainWindow, QTableWidget, QTableWidgetItem
    from portman.gui.window_shell import MainWindow
    app = QApplication.instance() or QApplication([])
    class Harness(QMainWindow):
        on_cell_double_clicked = MainWindow.on_cell_double_clicked
        def reload_portfolio(self): self.reloaded = True
    window = Harness(); window.repository = object(); window.status_bar = window.statusBar(); window.reloaded = False
    qtbot.addWidget(window)
    table = QTableWidget(2, 2, window)
    for row, (key, name) in enumerate([('KEY-Z', 'Zeta'), ('KEY-A', 'Alpha')]):
        item = QTableWidgetItem(key); item.setData(Qt.ItemDataRole.UserRole, key)
        table.setItem(row, 0, item); table.setItem(row, 1, QTableWidgetItem(name))
    table.setSortingEnabled(True); table.sortItems(1, Qt.SortOrder.AscendingOrder)
    table.cellDoubleClicked.connect(window.on_cell_double_clicked)
    with patch('portman.gui.window_shell.ClassificationDialog') as dialog:
        dialog.return_value.exec.return_value = 1
        table.cellDoubleClicked.emit(0, 1)
        assert dialog.call_args.args[1] == 'KEY-A'
        assert window.reloaded
    window.close(); app.processEvents()
