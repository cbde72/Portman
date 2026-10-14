from PySide6.QtCore import Qt
from PySide6.QtWidgets import QToolBar


class DockableToolbar(QToolBar):
    def __init__(self, window, title, name):
        super().__init__(title, window)
        self.setObjectName(name)
        self.setMovable(True)
        self.setFloatable(True)
        self.setAllowedAreas(Qt.ToolBarArea.AllToolBarAreas)
        window.addToolBar(self)
        window.view_menu.addAction(self.toggleViewAction())
        self.topLevelChanged.connect(window.schedule_layout_save)
        self.visibilityChanged.connect(window.schedule_layout_save)
        self.orientationChanged.connect(window.schedule_layout_save)

    def moveEvent(self, event):
        super().moveEvent(event)
        self.parentWidget().schedule_layout_save()
