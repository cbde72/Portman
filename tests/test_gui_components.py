from portman.holding import Holding
from portman.portfolio_chart import PortfolioChartCanvas


def test_allocation_groups_small_positions_and_excludes_negative_groups(qtbot):
    canvas = PortfolioChartCanvas()
    qtbot.addWidget(canvas)
    holdings = [Holding(str(i), '', name, category, 1, 0, value)
                for i, (name, category, value) in enumerate([
                    ('A', 'Aktie', 600), ('B', 'Aktie', 300),
                    ('C', 'ETF', 100), ('D', 'Krypto', 10),
                    ('E', 'Schulden', -20)])]
    canvas.plot_pie_allocation(holdings)
    labels = [label.get_text() for label in canvas.axes.get_legend().get_texts()]
    assert labels == ['Aktie  89.1 %', 'ETF  9.9 %', 'Sonstige  1.0 %']
    canvas.plot_performance_heatmap(holdings)
    canvas.plot_benchmarking(holdings)
    canvas.close()


def test_v09_window_initializes_menus_preferences_and_layout(tmp_path, monkeypatch, qtbot):
    from Gui import PortMan_V09 as gui
    from portman.gui import window_shell
    monkeypatch.setattr(window_shell, 'PROJECT_ROOT', tmp_path)
    monkeypatch.setattr(window_shell, 'HAS_WEBENGINE', False)
    monkeypatch.chdir(tmp_path)
    window = gui.MainWindow()
    qtbot.addWidget(window)
    try:
        labels = [action.text() for action in window.import_menu.actions()]
        assert labels.count('Manuell ein- oder ausbuchen …') == 1
        assert labels.count('Excel-Assistent · Blätter und Unterdepots') == 1
        from PySide6.QtWidgets import QToolBar, QPushButton
        assert window.findChild(QToolBar, 'v07_saved_views') is None
        assert not hasattr(window, 'saved_combo')
        assert not any(button.text() in ('Spalten auswählen …', 'Wertpapier bearbeiten') for button in window.findChildren(QPushButton))
        assert not window.position_search.isVisible()
        assert window.totals.text().startswith('<b>Gesamt Kaufwert:')
        from unittest.mock import patch
        from PySide6.QtCore import Qt
        from portman.gui import position_tables
        positions = window.tables['Alle']
        assert positions.showGrid()
        assert positions.horizontalHeader().defaultAlignment() == Qt.AlignmentFlag.AlignCenter
        assert window.accounts_widget.tree.header().defaultAlignment() == Qt.AlignmentFlag.AlignCenter
        accounts_tree = window.accounts_widget.tree
        assert accounts_tree.headerItem().textAlignment(0) & Qt.AlignmentFlag.AlignLeft
        assert all(accounts_tree.isColumnHidden(column) for column in (8, 11, 12, 13, 14, 15))
        assert 'palette(highlighted-text)' in accounts_tree.styleSheet()
        if accounts_tree.topLevelItemCount():
            institution = accounts_tree.topLevelItem(0)
            assert institution.textAlignment(0) & Qt.AlignmentFlag.AlignLeft
            assert institution.textAlignment(1) == Qt.AlignmentFlag.AlignCenter
            if institution.childCount():
                account = institution.child(0)
                assert account.textAlignment(0) & Qt.AlignmentFlag.AlignLeft
                assert account.textAlignment(1) == Qt.AlignmentFlag.AlignCenter
        with patch.object(position_tables, 'configure_columns') as columns:
            positions.horizontalHeader().sectionDoubleClicked.emit(0)
            columns.assert_called_once_with(window)
        if positions.model().rowCount():
            with patch('portman.classification_dialog.WertpapierEditDialog') as editor:
                editor.return_value.exec.return_value = 0
                positions.doubleClicked.emit(positions.model().index(0, 0))
                editor.assert_called_once()
        assert window.positions_model.columnCount() == 16
        assert len(window.visualizations_board.charts) == 4
        assert window.visualizations_board.mode.currentData() == 4
        window.visualizations_board.mode.setCurrentIndex(1)
        assert sum(not chart.isHidden() for chart in window.visualizations_board.charts) == 2
        window.visualizations_board.mode.setCurrentIndex(2)
        assert 'grid' in window.pages
        assert window.chart_grid_widget.rows >= 1 and window.chart_grid_widget.cols >= 1
        assert len(window.chart_grid_widget.tiles) == window.chart_grid_widget.rows * window.chart_grid_widget.cols
        assert window.import_menu.title() == 'Imports'
        assert labels.count('Dateien importieren …') == 1
        assert labels.count('Renault PDF importieren …') == 1
        assert [a.text() for a in window.online_menu.actions()] == [
            'Alle Online-Konten synchronisieren …', 'Bankzugang einrichten …', 'Marktdaten aktualisieren',
            'Marktdaten-Zugänge …', 'Kursverläufe seit Besitzbeginn laden und speichern']
        assert window.findChild(QToolBar, 'toolbar_main') is None
        settings_labels = [action.text() for action in window.settings_menu.actions() if action.text()]
        assert settings_labels == ['Hell', 'Dunkel', 'Nord', 'Hoher Kontrast',
                                   'Tabellenschriften …', 'Diagramme …', 'Import-Erkennung …',
                                   'Online-Anbindung …']
        top_level = [action.text().replace('&', '') for action in window.menuBar().actions()]
        assert top_level.count('Bearbeiten') == 1
        assert top_level.count('Hilfe') == 1
        assert top_level.count('Werkzeuge') == 1
        assert 'Extras' not in top_level
        assert not hasattr(window, 'theme_button')
        assert window.settings_menu.title() == '⚙️ Einstellungen'
        from PySide6.QtCore import Qt
        for toolbar in (window.scope_toolbar, window.period_toolbar):
            assert toolbar.isMovable() and toolbar.isFloatable()
            assert toolbar.allowedAreas() == Qt.ToolBarArea.AllToolBarAreas
            assert toolbar.toggleViewAction() in window.view_menu.actions()
        window.addToolBar(Qt.ToolBarArea.BottomToolBarArea, window.period_toolbar)
        assert window.preferences.tables['history_widget.tx'] is window.history_widget.tx
        window.show_workspace('accounts')
        window.save_settings()
        assert window.settings['active_workspace'] == 'accounts'
        assert window.settings['dock_state']
        assert (tmp_path / 'data/v09/portfolio_settings.json').exists()
        saved_state = bytes.fromhex(window.settings['dock_state'])
        window.addToolBar(Qt.ToolBarArea.TopToolBarArea, window.period_toolbar)
        assert window.restoreState(saved_state, 2)
        assert window.toolBarArea(window.period_toolbar) == Qt.ToolBarArea.BottomToolBarArea
        assert window.scope_toolbar.isMovable() and window.period_toolbar.isMovable()
        from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
        entries = window.content_docks.entries
        assert entries and any(isinstance(e['view'], FigureCanvasQTAgg) for e in entries.values())
        for key, entry in entries.items():
            window.content_docks.detach(key)
            assert entry['dock'].widget() is entry['view']
            window.content_docks.attach(key)
            assert entry['view'].parentWidget() is entry['parent']
        window.select_gui_style('nord')
        assert window.settings['gui_style'] == 'nord'
        window.select_gui_style('light')
    finally:
        window.close()
