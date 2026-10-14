import os
from decimal import Decimal

import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from portman.rebalancing import plan_rebalancing


@pytest.mark.parametrize('minimum,fee', [(0, 5), (600, 5), (0, 600)])
def test_sales_and_purchases_never_overspend(minimum, fee):
    result = plan_rebalancing({'A': 6000, 'B': 4000}, {'A': 50, 'B': 50},
                             cash=0, tolerance_pct=0, minimum_order=minimum,
                             fee=fee, buys_only=False)
    assert result['cash_used'] <= result['sales']
    assert all(row['after'] >= 0 for row in result['rows'])
    if fee == 5 and minimum == 0:
        assert result['sales'] == Decimal('1000')
        assert result['rows'][1]['action'] == Decimal('990')


@pytest.fixture
def window(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication
    from Gui import PortMan_V09 as gui
    from portman.gui import window_shell
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(window_shell, 'PROJECT_ROOT', tmp_path)
    monkeypatch.setattr(window_shell, 'HAS_WEBENGINE', False)
    monkeypatch.chdir(tmp_path)
    (tmp_path / 'data').mkdir()
    instance = gui.MainWindow()
    instance.show()
    app.processEvents()
    yield instance
    instance.close()
    app.processEvents()


def test_saved_workspace_restores_title_and_workspaces(window):
    window.show_workspace('accounts')
    window.save_settings()
    saved_state = window.settings['dock_state']
    window.setWindowTitle('stale')
    window.restore_dock_state()
    assert window.windowTitle() == 'PortMan · Konten und Depots'
    assert window.nav_buttons['accounts'].isChecked()
    assert window.restoreState(bytes.fromhex(saved_state), 2)
    assert window.scope_toolbar.isMovable()


def test_invalid_workspace_falls_back_to_visible_dashboard(window):
    window.show_workspace('accounts')
    window.settings.update(active_workspace='removed-page', dock_state='invalid')
    window.restore_dock_state()
    assert window.dock_dashboard.isVisible()
    assert window.nav_buttons['dashboard'].isChecked()
    assert window.settings['active_workspace'] == 'dashboard'


def test_empty_risk_view_uses_consistent_metric_names(window):
    window.update_risk_analysis()
    assert 'Gewichtete Einzelvolatilität' in window.lbl_vola.text()
    assert 'Hinterlegte Dividendenrendite' in window.lbl_div_total.text()


def test_report_does_not_invent_zero_return(window, tmp_path, monkeypatch):
    from portman.gui import portfolio_report as report_module
    target = tmp_path / 'report.html'
    monkeypatch.setattr(report_module.QFileDialog, 'getSaveFileName', lambda *a: (str(target), ''))
    monkeypatch.setattr(report_module.QMessageBox, 'information', lambda *a: None)
    window.export_portfolio_report()
    report = target.read_text(encoding='utf-8')
    assert '(–)' in report
    assert '(0.0 %)' not in report
