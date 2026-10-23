"""Global, display-oriented clipboard support for PortMan's Qt widgets."""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QKeyEvent, QKeySequence
from PySide6.QtWidgets import QApplication, QLabel, QTableView, QTreeView, QWidget


def _table_for(widget):
    while widget is not None:
        if isinstance(widget, (QTableView, QTreeView)):
            return widget
        widget = widget.parentWidget() if isinstance(widget, QWidget) else None
    return None


def configure_copy_widget(widget):
    """Configure one widget without changing its data model or editability."""
    if isinstance(widget, (QTableView, QTreeView)):
        if widget.property("portmanCopyEnabled"):
            return
        widget.setProperty("portmanCopyEnabled", True)
        widget.setSelectionBehavior(widget.SelectionBehavior.SelectItems)
        widget.setSelectionMode(widget.SelectionMode.ExtendedSelection)
    elif isinstance(widget, QLabel):
        if widget.property("portmanTextSelectable"):
            return
        widget.setProperty("portmanTextSelectable", True)
        flags = widget.textInteractionFlags()
        flags |= (Qt.TextInteractionFlag.TextSelectableByMouse |
                  Qt.TextInteractionFlag.TextSelectableByKeyboard)
        widget.setTextInteractionFlags(flags)


def configure_copy_tree(root):
    """Configure an existing widget tree; later widgets are handled globally."""
    if isinstance(root, QWidget):
        configure_copy_widget(root)
        for widget in root.findChildren(QWidget):
            configure_copy_widget(widget)


class GlobalCopySupport(QObject):
    """Apply copy behaviour lazily and route table shortcuts by current focus."""

    def eventFilter(self, watched, event):
        if event.type() in (QEvent.Type.Polish, QEvent.Type.Show):
            if isinstance(watched, QWidget):
                configure_copy_widget(watched)
        if event.type() == QEvent.Type.KeyPress and isinstance(event, QKeyEvent):
            table = _table_for(QApplication.focusWidget())
            if table is not None and event.matches(QKeySequence.StandardKey.Copy):
                from .table_copy import copy_selected_cells
                copy_selected_cells(table)
                return True
            if table is not None and event.matches(QKeySequence.StandardKey.SelectAll):
                table.selectAll()
                return True
        return super().eventFilter(watched, event)


def install_global_copy_support(app=None):
    """Install the application-wide support once and return its event filter."""
    app = app or QApplication.instance()
    if app is None:
        raise RuntimeError("QApplication must exist before copy support is installed.")
    support = getattr(app, "_portman_global_copy_support", None)
    if support is None:
        support = GlobalCopySupport(app)
        app.installEventFilter(support)
        app._portman_global_copy_support = support
        for widget in app.topLevelWidgets():
            configure_copy_tree(widget)
    return support
