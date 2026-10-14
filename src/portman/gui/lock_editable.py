"""Editable dock-lock semantics shared by the version windows."""
from PySide6.QtWidgets import QWidget


class LockEditableMixin:
    def lock_editable_checked(self):
        return not self.settings.get('dock_layout_locked', True)

    def on_lock_docks_toggled(self, editable):
        self.set_docks_locked(not editable)

    def set_docks_locked(self, locked):
        super().set_docks_locked(locked)
        for dock in self.docks:
            if locked:
                if dock.titleBarWidget() is None: dock.setTitleBarWidget(QWidget(dock))
            else:
                old = dock.titleBarWidget(); dock.setTitleBarWidget(None)
                if old: old.deleteLater()
