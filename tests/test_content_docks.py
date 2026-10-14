import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMainWindow, QDockWidget, QWidget, QVBoxLayout, QTableWidget, QSplitter, QTabWidget
from portman.gui.content_docks import ContentDocks
from portman.theme import apply_theme, STYLES
from PySide6.QtGui import QPalette


@pytest.mark.parametrize('container', ['layout', 'splitter', 'tabs'])
def test_detach_and_restore_preserves_view_and_slot(qtbot, container):
    window = QMainWindow()
    qtbot.addWidget(window)
    window.settings = {}
    window.schedule_layout_save = lambda *args: None
    window.refresh_scope_dock = lambda dock: None
    window.view_menu = window.menuBar().addMenu('Ansicht')
    owner = QDockWidget('Bestände', window)
    owner.setObjectName('positions')
    table = QTableWidget(2, 2)
    table.setHorizontalHeaderLabels(['Name', 'Wert'])
    if container == 'layout':
        panel = QWidget(); QVBoxLayout(panel).addWidget(table)
    elif container == 'splitter':
        panel = QSplitter(); panel.addWidget(table); panel.addWidget(QWidget())
    else:
        panel = QTabWidget(); panel.addTab(table, 'Aktien'); panel.addTab(QWidget(), 'Andere')
    owner.setWidget(panel)
    window.docks = [owner]
    window.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, owner)
    window.show()
    manager = ContentDocks(window)
    key, entry = next(iter(manager.entries.items()))
    manager.detach(key)
    assert entry['dock'].widget() is table and entry['dock'].isFloating()
    assert window.settings['detached_views'] == [key]
    state = window.saveState(2)
    window.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, entry['dock'])
    assert window.restoreState(state, 2)
    entry['dock'].close()
    assert table.parentWidget() is entry['parent']
    assert table.rowCount() == 2 and window.settings['detached_views'] == []
    if container == 'tabs':
        assert panel.widget(0) is table and panel.tabText(0) == 'Aktien'
    manager.detach(key)
    manager.attach_all()
    assert table.parentWidget() is entry['parent']


def test_styles_have_distinct_palettes(qapp):
    backgrounds = set()
    try:
        for style in STYLES:
            apply_theme(style)
            backgrounds.add(qapp.palette().color(QPalette.ColorRole.Window).name())
        assert len(backgrounds) == len(STYLES)
    finally:
        apply_theme(False)
