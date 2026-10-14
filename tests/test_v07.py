import json
import os
import sqlite3
from decimal import Decimal
from types import SimpleNamespace
import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from portfolio_v5.models import ImportBatch, Snapshot, Position, Transaction
try:
    from portman.repository_v07 import RepositoryV07
    from portman.persistence import atomic_json, read_json, inspect_database, restore_database, initialize_v07
    from portman.import_v07 import simulate, commit_atomic
    from portman.analysis_v07 import change_analysis
except ImportError:
    pytest.skip('Legacy: V07-Schemamodule wurden entfernt (repository_v07, import_v07, analysis_v07).', allow_module_level=True)


def batch(day='2026-01-01', value='100', quantity='1'):
    return ImportBatch(day, day, snapshots=[Snapshot('Depot', day[:7], day, 'Test',
        [Position('DE0000000001', 'Test', isin='DE0000000001', quantity=quantity, value=value)])])


@pytest.fixture
def repo(tmp_path):
    r = RepositoryV07(tmp_path / 'portfolio.sqlite')
    yield r
    r.close()


def job(repo):
    return SimpleNamespace(path=str(repo.store.path), progress=SimpleNamespace(emit=lambda *args: None),
                           isInterruptionRequested=lambda: False)


def test_atomic_settings_failure_preserves_original(tmp_path, monkeypatch):
    p = tmp_path / 'settings.json'
    atomic_json(p, {'a': 1})
    monkeypatch.setattr(os, 'replace', lambda *args: (_ for _ in ()).throw(OSError('disk error')))
    with pytest.raises(OSError): atomic_json(p, {'a': 2})
    assert json.loads(p.read_text()) == {'a': 1}


def test_manual_isin_correction_checks_checksum():
    from portfolio_v5.models import valid_isin
    assert valid_isin('US0378331005')
    assert valid_isin('DE000BASF111')
    assert not valid_isin('US0378331006')
    assert not valid_isin('invalid')


def test_settings_recover_last_good(tmp_path):
    p = tmp_path / 'settings.json'
    atomic_json(p, {'a': 1}); atomic_json(p, {'a': 2})
    p.write_text('{broken')
    assert read_json(p) == {'a': 1}


def test_migration_audit_backup_and_restore(repo):
    assert repo.db.execute('PRAGMA user_version').fetchone()[0] == 7
    repo.create_accounts(['Bank']); repo.add_balance('Bank', '100', '2026-01-01')
    backup = repo.backup()
    assert inspect_database(backup)['accounts'] == 1
    repo.add_balance('Bank', '200', '2026-02-01')
    assert repo.wealth_summary()['value'] == Decimal('200')
    assert repo.db.execute("SELECT count(*) FROM change_log WHERE entity='manual_balances'").fetchone()[0] == 2
    restore_database(repo.db, backup, repo.backup_folder)
    repo.store._read_revision = None
    assert repo.wealth_summary()['value'] == Decimal('100')
    assert repo.wealth_summary()['dates'] == ['2026-01-01']


def test_commit_atomic_rolls_back_all_files(repo):
    with pytest.raises(ValueError):
        commit_atomic(job(repo), [batch(), ImportBatch('bad', 'bad', errors=['broken'])])
    assert repo.imports() == []
    assert repo.holdings() == []
    result = commit_atomic(job(repo), [batch(), batch('2026-02-01', '200')])
    assert len(result) == 2
    assert repo.holdings()[0]['value'] == '200'
    assert list(repo.backup_folder.glob('*before-import.sqlite'))


def test_simulation_joint_effect_no_live_writes(repo):
    repo.commit_batches([batch()])
    before = repo.db.total_changes
    result = simulate(job(repo), [batch('2026-02-01', '300', '3'), batch('2026-03-01', '400', '4')])
    assert result['positions'][0][2:6] == ['1', '4', '100', '400']
    assert repo.db.total_changes == before
    assert repo.holdings()[0]['value'] == '100'


def test_bulk_simulation_rebuilds_security_master_once(repo, monkeypatch):
    from portman.repository import PortfolioRepository
    original = PortfolioRepository.sync_security_master
    calls = []

    def counted(target):
        calls.append(target.store.path)
        return original(target)

    monkeypatch.setattr(PortfolioRepository, 'sync_security_master', counted)
    incoming = [batch(f'2026-{month:02d}-01', str(100 + month), str(month))
                for month in range(1, 7)]
    result = simulate(job(repo), incoming)

    assert all(row['status'] == 'imported' for row in result['results'])
    # One initialization of the preview repository and one final rebuild,
    # independent of the number of files in the bulk import.
    assert len(calls) == 2


def test_reconciliation_and_unclassified_residual(repo):
    repo.commit_batches([batch(), batch('2026-02-01', '240', '2')])
    repo.commit_batches([ImportBatch('tx', 'tx', transactions=[
        Transaction('Depot', 'buy', '2026-01-15', 'BUY', '-110', 'EUR', 'DE0000000001', '1')])])
    repo.confirm_coverage('Depot', '2026-01-01', '2026-02-01')
    result = change_analysis(repo, '2026-01-01', '2026-02-01', 'Depot')
    row = result['positions'][0]
    assert row['difference'] == 0
    assert row['price_effect'] == 20
    assert row['status'] == 'Rechnerisch passend'


def test_saved_views_roundtrip_and_delete(repo):
    repo.save_view('Test', {'account': None, 'date': '2026-01-01'})
    assert repo.saved_views()['Test']['date'] == '2026-01-01'
    repo.delete_view('Test'); assert not repo.saved_views()


def test_initialization_copies_legacy_without_changing_it(tmp_path):
    from portman.repository import PortfolioRepository
    import hashlib
    source = tmp_path / 'data/portfolio_v05.sqlite'
    original = PortfolioRepository(source)
    original.commit_batches([batch()]); original.close()
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    folder = initialize_v07(tmp_path)
    migrated = RepositoryV07(folder / 'portfolio.sqlite')
    try:
        assert migrated.holdings()[0]['value'] == '100'
        migrated.create_accounts(['Neu'])
        assert hashlib.sha256(source.read_bytes()).hexdigest() == digest
        assert initialize_v07(tmp_path) == folder
        assert 'Neu' in migrated.accounts()
    finally: migrated.close()


def test_cancel_between_files_rolls_back(repo):
    task = job(repo); state = {'cancelled': False}
    task.progress.emit = lambda *args: state.update(cancelled=True)
    task.isInterruptionRequested = lambda: state['cancelled']
    with pytest.raises(ValueError, match='abgebrochen'):
        commit_atomic(task, [batch(), batch('2026-02-01')])
    assert repo.imports() == []


def test_closing_progress_requests_cancel_and_keeps_worker_alive(repo):
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import QTimer
    from portman.import_v07 import run_job
    import threading
    app = QApplication.instance() or QApplication([])
    def work(task):
        for _ in range(100):
            if task.isInterruptionRequested(): raise ValueError('abgebrochen')
            threading.Event().wait(.01)
        raise AssertionError('Abbruch wurde nicht angefordert')
    QTimer.singleShot(30, lambda: app.activeModalWidget().close())
    with pytest.raises(ValueError, match='abgebrochen'):
        run_job(None, repo.store.path, 'Test', work)


def test_recovery_rejects_corruption_before_mutation(repo, tmp_path):
    repo.commit_batches([batch()])
    corrupt = tmp_path / 'broken.sqlite'; corrupt.write_bytes(b'broken')
    with pytest.raises((ValueError, sqlite3.DatabaseError)):
        restore_database(repo.db, corrupt, repo.backup_folder)
    assert repo.holdings()[0]['value'] == '100'


def test_overlap_detection_between_sources(repo):
    tx = Transaction('Depot', 'first', '2026-01-03', 'BUY', '-100', 'EUR', 'DE0000000001', '1')
    repo.commit_batches([ImportBatch('one.csv', 'one', transactions=[tx])])
    incoming = Transaction('Depot', 'other-id', '2026-01-03', 'BUY', '-100.00', 'EUR', 'DE0000000001', '1')
    result = simulate(job(repo), [ImportBatch('two.pdf', 'two', transactions=[incoming])])
    assert len(result['overlaps']) == 1
    assert len(repo.transactions()) == 1


def test_repository_cache_detects_other_connection(repo):
    repo.create_accounts(['Bank']); repo.add_balance('Bank', '100', '2026-01-01')
    assert repo.wealth_summary()['value'] == 100
    other = RepositoryV07(repo.store.path, backups=False)
    try: other.add_balance('Bank', '200', '2026-02-01')
    finally: other.close()
    assert repo.wealth_summary()['value'] == 200


def test_cost_correction_targets_selected_historical_snapshot(repo):
    repo.commit_batches([batch(), batch('2026-02-01', '200')])
    old = repo.holdings('2026-01-01')[0]
    repo.correct_cost(old['snapshot_id'], old['key'], '80', 'Historischer Beleg')
    assert repo.holdings('2026-01-01')[0]['cost'] == '80'
    assert repo.holdings('2026-02-01')[0]['cost'] == '80.00'


def test_position_model_numeric_sort_and_filter():
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import Qt
    from portman.positions_model import PositionsModel, PositionFilter, SORT_ROLE
    QApplication.instance() or QApplication([])
    rows = [SimpleNamespace(isin=str(i), wkn='', name='Test ' + str(i), asset_type='ETF', region='Europa',
                            cap_size='Large', amount=1, buy_value=0, market_value=v, profit_loss=v)
            for i, v in enumerate([2, 100, 10])]
    model = PositionsModel(); proxy = PositionFilter('Alle'); proxy.setSourceModel(model)
    model.reset(rows, {}); proxy.filters('Europa', 'Alle Cap-Größen', '')
    proxy.sort(7, Qt.SortOrder.AscendingOrder)
    assert [proxy.index(i, 7).data(SORT_ROLE) for i in range(3)] == [2, 10, 100]
    proxy.filters('Europa', 'Alle Cap-Größen', 'Test 1')
    assert proxy.rowCount() == 1
    assert proxy.index(0, 11).data() == '100,00'


def test_wizard_reviews_without_writing_and_invalidates_selection(repo, monkeypatch):
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import Qt
    from portman import import_v07
    QApplication.instance() or QApplication([])
    monkeypatch.setattr(import_v07, 'run_job', lambda parent, path, title, fn: fn(job(repo)))
    batches = [batch()]
    summaries = import_v07.prepare_summaries(job(repo), batches)
    wizard = import_v07.ImportWizard(repo, batches, summaries)
    try:
        wizard.accept()
        assert wizard._selected is not None
        assert repo.imports() == []
        wizard.table.item(0, 8).setCheckState(Qt.CheckState.Unchecked)
        assert wizard._selected is None
        wizard.accept(); wizard.accept()
        assert wizard.result() == 1
        assert repo.imports() == []
    finally: wizard.close()


def test_v09_gui_offscreen(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication
    from Gui import PortMan_V09 as gui
    from portman.gui import window_shell
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(window_shell, 'HAS_WEBENGINE', False)
    monkeypatch.setattr(window_shell, 'PROJECT_ROOT', tmp_path)
    window = gui.MainWindow()
    try:
        window.show(); window.resize(1200, 800); app.processEvents()
        assert '09' in window.windowTitle()
        assert window.repository.db.execute('PRAGMA user_version').fetchone()[0] == 9
        window.repository.create_accounts(['Manuell'])
        window.repository.add_balance('Manuell', '100', '2026-01-01')
        window.refresh_scope_choices(); window.reload_portfolio()
        window.dashboard.refresh()
        assert 'None' not in window.dashboard.wealth_note.text()
        assert '01.01.2026' in window.dashboard.wealth_note.text()
        window.select_gui_style('dark'); window.select_gui_style('light'); app.processEvents()
        window.tables['Alle'].setColumnHidden(4, True)
        window.save_settings()
        assert (tmp_path / 'data/v09/portfolio_settings.json').exists()
    finally:
        window.close(); app.processEvents()


def test_positions_profit_color_percentage_alignment_and_symbol():
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor
    from PySide6.QtWidgets import QApplication
    from portman.positions_model import PositionsModel, PositionFilter, SORT_ROLE, HEADERS
    QApplication.instance() or QApplication([])
    rows = [SimpleNamespace(isin='US0378331005', wkn='865985', name='Apple', asset_type='Aktie',
        region='USA', cap_size='Large', amount=2, buy_value=100, market_value=125, profit_loss=25),
        SimpleNamespace(isin='unknown', wkn='', name='Unbekannt', asset_type='Aktie', region='',
        cap_size='', amount=1, buy_value=0, market_value=50, profit_loss=50)]
    model = PositionsModel()
    model.reset(rows, {}, {'US0378331005': {'symbol': 'AAPL'}})
    percent = HEADERS.index('Gewinn/Verlust (%)')
    symbol = HEADERS.index('Symbol')
    assert model.index(0, percent).data(SORT_ROLE) == 25
    assert model.index(0, percent).data() == '25,00'
    assert model.index(1, percent).data() == '–'
    assert model.index(0, symbol).data() == 'AAPL'
    assert model.index(0, HEADERS.index('WKN')).data() == '865985'
    assert model.index(0, 0).data(Qt.ItemDataRole.ForegroundRole) is None
    assert model.index(0, 8).data(Qt.ItemDataRole.ForegroundRole) == QColor('#16803c')
    assert model.index(0, percent).data(Qt.ItemDataRole.ForegroundRole) == QColor('#16803c')
    rows[0].profit_loss = -25
    assert model.index(0, 8).data(Qt.ItemDataRole.ForegroundRole) == QColor('#dc2626')
    assert model.index(0, percent).data(Qt.ItemDataRole.ForegroundRole) == QColor('#dc2626')
    assert model.index(1, 0).data(Qt.ItemDataRole.ForegroundRole) is None
    assert all(model.index(0, col).data(Qt.ItemDataRole.TextAlignmentRole) == Qt.AlignmentFlag.AlignCenter for col in range(model.columnCount()))
    proxy = PositionFilter('Alle'); proxy.setSourceModel(model)
    proxy.filters('', '', 'aapl')
    assert proxy.rowCount() == 1


def test_position_column_preferences_survive_restart():
    from PySide6.QtWidgets import QApplication
    from portman.preferences_v09 import TablePreferences, POSITION_COLUMNS
    from portman.positions_model import PositionTable, PositionsModel
    QApplication.instance() or QApplication([])
    def make(settings):
        table = PositionTable(); table.setModel(PositionsModel(table))
        window = SimpleNamespace(settings=settings, tables={'Alle':table},
            history_widget=SimpleNamespace(bank_archive=SimpleNamespace(),state_history=SimpleNamespace()))
        return window, table, TablePreferences(window)
    window, table, preferences = make({})
    symbol = POSITION_COLUMNS.index('symbol')
    profit = POSITION_COLUMNS.index('profit_percent')
    assert table.horizontalHeader().visualIndex(symbol) == 1
    table.setColumnHidden(3, True)
    table.setColumnWidth(symbol, 180)
    table.horizontalHeader().moveSection(table.horizontalHeader().visualIndex(profit), 2)
    preferences.save()
    restored, copy, _ = make(window.settings)
    assert copy.isColumnHidden(3)
    assert copy.columnWidth(symbol) == 180
    assert copy.horizontalHeader().visualIndex(profit) == 2
    assert not copy.isColumnHidden(symbol)
    table.close(); copy.close()
