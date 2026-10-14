from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication, QDockWidget, QInputDialog


class WindowLayoutMixin:
    def reset_dock_layout(self):
        self.apply_layout_preset("overview")

    def show_all_docks(self):
        for dock in self.docks:
            dock.show()
        self.statusBar().showMessage("Alle Arbeitsbereiche sind sichtbar.", 3000)

    def focus_active_dock(self):
        focused = QApplication.focusWidget()
        active = next(
            (dock for dock in self.docks
             if dock.isVisible() and focused is not None
             and (focused is dock.widget() or dock.widget().isAncestorOf(focused))),
            None,
        )
        if active is None:
            active = next((dock for dock in self.docks if dock.isVisible()), self.dock_dashboard)
        for dock in self.docks:
            dock.setVisible(dock is active)
        active.show()
        active.raise_()
        self.statusBar().showMessage(
            f"Fokusansicht: {active.windowTitle()}. Mit Strg+Umschalt+A alle anzeigen.", 5000
        )

    def _place_dock(self, dock, area):
        # addDockWidget darf ein bereits verwaltetes Dock direkt umplatzieren.
        # removeDockWidget() würde bei Matplotlib-Canvas kurz das native QWindow
        # zerstören und kann unter PySide6 einen veralteten Handle hinterlassen.
        if dock.isFloating():
            dock.hide()
            dock.setFloating(False)
        self.addDockWidget(area, dock)
        dock.show()

    def apply_layout_preset(self, preset="overview"):
        """Ordnet alle Arbeitsbereiche in einer brauchbaren Split-/Tab-Struktur an."""
        for dock in self.docks:
            dock.show()

        self._place_dock(self.dock_tables, Qt.DockWidgetArea.LeftDockWidgetArea)
        self._place_dock(self.dock_dashboard, Qt.DockWidgetArea.RightDockWidgetArea)
        self._place_dock(self.dock_chart, Qt.DockWidgetArea.RightDockWidgetArea)
        self.splitDockWidget(self.dock_dashboard, self.dock_chart, Qt.Orientation.Vertical)

        right_tabs = [self.dock_lookthrough, self.dock_risk, self.dock_rebalance, self.dock_browser]
        for dock in right_tabs:
            self._place_dock(dock, Qt.DockWidgetArea.RightDockWidgetArea)
            self.tabifyDockWidget(self.dock_chart, dock)

        self._place_dock(self.dock_history, Qt.DockWidgetArea.BottomDockWidgetArea)
        for dock in (self.dock_performance, self.dock_quality, self.dock_accounts):
            self._place_dock(dock, Qt.DockWidgetArea.BottomDockWidgetArea)
            self.tabifyDockWidget(self.dock_history, dock)

        self.resizeDocks([self.dock_tables, self.dock_dashboard], [420, 780], Qt.Orientation.Horizontal)
        self.resizeDocks([self.dock_dashboard, self.dock_chart, self.dock_history], [420, 340, 240], Qt.Orientation.Vertical)

        if preset == "analysis":
            self.dock_risk.raise_()
            self.dock_performance.raise_()
        elif preset == "history":
            self.dock_history.raise_()
        else:
            self.dock_dashboard.raise_()
        self.statusBar().showMessage("Fenster-Layout angewendet.", 3000)

    def set_docks_locked(self, locked):
        for dock in self.docks:
            features = QDockWidget.DockWidgetFeature.DockWidgetClosable
            if not locked:
                features |= (QDockWidget.DockWidgetFeature.DockWidgetMovable |
                             QDockWidget.DockWidgetFeature.DockWidgetFloatable)
            dock.setFeatures(features)
        self.settings["dock_layout_locked"] = bool(locked)
        self.schedule_layout_save()

    def connect_layout_autosave(self):
        self.layout_save_timer = QTimer(self)
        self.layout_save_timer.setSingleShot(True)
        self.layout_save_timer.setInterval(800)
        self.layout_save_timer.timeout.connect(self.save_layout_settings)
        for dock in self.docks:
            dock.dockLocationChanged.connect(self.schedule_layout_save)
            dock.topLevelChanged.connect(self.schedule_layout_save)
            dock.visibilityChanged.connect(self.schedule_layout_save)

    def schedule_layout_save(self, *args):
        if hasattr(self, "layout_save_timer"):
            self.layout_save_timer.start()

    def save_layout_settings(self):
        self.settings["window_geometry"] = self.saveGeometry().toHex().data().decode("ascii")
        self.settings["dock_state"] = self.saveState(2).toHex().data().decode("ascii")
        self.storage.save_settings(self.settings)

    def save_named_layout(self):
        name, accepted = QInputDialog.getText(self, "Layout speichern", "Name des Layouts:")
        name = name.strip()
        if not accepted or not name:
            return
        layouts = self.settings.setdefault("workspace_layouts", {})
        layouts[name] = bytes(self.saveState(2).toHex()).decode("ascii")
        self.save_settings()
        self.statusBar().showMessage(f"Layout '{name}' gespeichert.", 3000)

    def populate_named_layout_menu(self):
        self.named_layout_menu.clear()
        layouts = self.settings.get("workspace_layouts", {})
        if not layouts:
            empty = self.named_layout_menu.addAction("Keine gespeicherten Layouts")
            empty.setEnabled(False)
            return
        for name in sorted(layouts, key=str.casefold):
            action = self.named_layout_menu.addAction(name)
            action.triggered.connect(lambda checked=False, layout=name: self.load_named_layout(layout))

    def load_named_layout(self, name):
        state = self.settings.get("workspace_layouts", {}).get(name)
        if state and self.restoreState(bytes.fromhex(state), 2):
            self.statusBar().showMessage(f"Layout '{name}' geladen.", 3000)

    def restore_column_widths(self):
        col_widths = self.settings.get("column_widths", [])
        if col_widths:
            for table in self.tables.values():
                for col_idx, width in enumerate(col_widths):
                    if col_idx < table.columnCount():
                        table.setColumnWidth(col_idx, width)

    def restore_dock_state(self):
        geometry_hex = self.settings.get("window_geometry")
        if geometry_hex:
            try:
                self.restoreGeometry(bytes.fromhex(geometry_hex))
            except (ValueError, TypeError):
                pass
        dock_state_hex = self.settings.get("dock_state", None)
        if self.settings.get('design_version') != 2:
            if dock_state_hex:
                self.settings.setdefault('workspace_layouts', {}).setdefault('Vor dem Redesign', dock_state_hex)
            self.settings['design_version'] = 2
            self.show_workspace('dashboard')
            self.set_docks_locked(bool(self.settings.get('dock_layout_locked', False)))
            self.resize(1400, 900)
            self.setMinimumSize(1000, 750)
            return
        active = self.settings.get('active_workspace', 'dashboard')
        if active not in self.pages:
            active = 'dashboard'
        self.settings['active_workspace'] = active
        restored = False
        if dock_state_hex:
            try:
                restored = self.restoreState(bytes.fromhex(dock_state_hex), 2)
            except Exception as e:
                print(f"Dock state konnte nicht wiederhergestellt werden: {e}")
        if not restored:
            try:
                self.show_workspace(self.settings.get('active_workspace', 'dashboard'))
            except Exception:
                pass
        self.set_docks_locked(bool(self.settings.get("dock_layout_locked", False)))
        try:
            self.nav_buttons[active].setChecked(True)
        except Exception:
            pass
        try:
            self.setWindowTitle(f'PortMan · {self.pages[active][0]}')
        except Exception:
            pass
        self.scope_toolbar.setMovable(True)
        self.scope_toolbar.setFloatable(True)

    def save_settings(self):
        first_table = list(self.tables.values())[0]
        col_widths = [first_table.columnWidth(i) for i in range(first_table.columnCount())]
        
        self.settings["column_widths"] = col_widths
        w = max(self.width(), 900)
        h = max(self.height(), 650)
        self.settings["window_width"] = w
        self.settings["window_height"] = h
        self.save_layout_settings()
