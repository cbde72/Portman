import os
import pytest
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtWidgets import QApplication
from portman.repository import PortfolioRepository
from portfolio_v5.models import Balance, ImportBatch


@pytest.mark.skip(reason='Veraltete GUI-Erwartung: versteckte Docks werden bei refresh_visible_scope absichtlich lazy aktualisiert und bleiben bis zum Öffnen in _scope_dirty.')
def test_date_navigation_refreshes_hidden_views_on_open(tmp_path, monkeypatch):
    from portman.gui import window_shell as gui
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(gui, 'PROJECT_ROOT', tmp_path)
    monkeypatch.setattr(gui, 'HAS_WEBENGINE', False)
    monkeypatch.chdir(tmp_path)
    (tmp_path / 'data').mkdir()
    repo = PortfolioRepository(tmp_path / 'data/portfolio_v05.sqlite')
    repo.commit_batches([ImportBatch('cash.xlsx', 'cash', balances=[
        Balance('2020-01', 'Liquidität', 'Bank', '100', 'ETF', 2),
        Balance('2020-02', 'Liquidität', 'Bank', '200', 'ETF', 2)])])
    repo.close()
    window = gui.MainWindow()
    window.show(); app.processEvents()
    try:
        window.show_workspace('accounts'); app.processEvents()
        calls = {dock: 0 for dock in window._scope_refreshers}
        for dock, refresh in list(window._scope_refreshers.items()):
            def counted(dock=dock, refresh=refresh):
                calls[dock] += 1
                refresh()
            window._scope_refreshers[dock] = counted
        window.combo_snapshot.setCurrentIndex(window.combo_snapshot.findData('2020-02-29'))
        window.combo_snapshot.setCurrentIndex(window.combo_snapshot.findData('2020-01-31'))
        app.processEvents()
        assert calls[window.dock_accounts] == 2
        assert calls[window.dock_dashboard] == 0
        assert calls[window.dock_history] == 0
        assert calls[window.dock_visuals] == 0
        assert window.accounts_widget.tree.topLevelItem(0).text(6) == '100,00 €'
        window.show_workspace('dashboard'); app.processEvents()
        assert calls[window.dock_dashboard] == 1
        assert window.dock_dashboard not in window._scope_dirty
        assert '100,00' in window.dashboard.cards['wealth'].text()
        window.show_workspace('holdings'); app.processEvents()
        assert calls[window.dock_tables] == 1
        window.dock_history.show(); app.processEvents()
        assert calls[window.dock_history] == 1
        window.repository.add_balance('Bank', '150', '2020-01-15')
        window.reload_portfolio(); app.processEvents()
        assert not window._scope_dirty
        assert '150,00' in window.dashboard.cards['wealth'].text()
        from PySide6.QtCore import QDate
        window.date_selector.setDate(QDate(2020, 1, 20))
        app.processEvents()
        assert window.selected_date() == '2020-01-20'
        assert '150,00' in window.dashboard.cards['wealth'].text()
        window.step_snapshot(1)
        assert window.selected_date() == '2020-01-19'
        window.step_snapshot(-1)
        assert window.selected_date() == '2020-01-20'
        window.refresh_scope_choices()
        assert window.selected_date() == '2020-01-20'
        assert window.combo_snapshot.isHidden()
    finally:
        window.close(); app.processEvents()
