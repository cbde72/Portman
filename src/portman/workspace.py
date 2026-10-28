from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
import re
from PySide6.QtWidgets import (QToolBar, QWidget, QVBoxLayout, QLabel, QPushButton,
                              QButtonGroup, QTableWidget, QTableView, QTreeWidget, QScrollArea, QFrame,
                              QMenu, QToolButton)
from .theme import apply_theme, TABLE_FONTS, row_height_for
from .chart_style import COLORS, style_figure, style_axis


class WorkspaceMixin:
    def setup_scope_refresh(self):
        """Refresh hidden views on demand instead of rebuilding every chart per date."""
        self._scope_dirty = set()
        self._scope_refreshers = {
            self.dock_dashboard: self.dashboard.refresh,
            self.dock_accounts: self.accounts_widget.refresh,
            self.dock_tables: self.refresh_tables,
            self.dock_chart: self.update_chart,
            self.dock_risk: self.update_risk_analysis,
            self.dock_rebalance: self.calculate_rebalancing,
            self.dock_lookthrough: self.update_lookthrough_analysis,
            self.dock_history: self.history_widget.refresh,
            self.dock_performance: self.performance_widget.refresh,
            self.dock_income_costs: self.income_costs_widget.refresh_depots,
            self.dock_quality: self.quality_widget.refresh,
            self.dock_visuals: self.visualizations_board.refresh,
            self.dock_grid: self.chart_grid_widget.refresh,
            self.dock_market: self.market_widget.refresh,
        }
        for dock in self._scope_refreshers:
            dock.visibilityChanged.connect(lambda visible, dock=dock: self.refresh_scope_dock(dock) if visible else None)

    def refresh_scope_dock(self, dock):
        if dock in self._scope_dirty:
            self._scope_dirty.remove(dock)
            try:
                self._scope_refreshers[dock]()
            except Exception:
                self._scope_dirty.add(dock)
                raise

    def refresh_visible_scope(self):
        self._scope_dirty = set(self._scope_refreshers)
        for dock in self._scope_refreshers:
            if dock.isVisible() or (hasattr(self, 'content_docks') and self.content_docks.visible_for(dock)):
                self.refresh_scope_dock(dock)

    def setup_navigation(self):
        self.pages = {
            'dashboard': ('Übersicht', [self.dock_dashboard]),
            'accounts': ('Konten und Depots', [self.dock_accounts]),
            'holdings': ('Depotpositionen', [self.dock_tables]),
            'analysis': ('Visualisierungen', [self.dock_visuals]),
            'grid': ('Diagramm-Raster', [self.dock_grid]),
            'performance': ('Performance', [self.dock_performance]),
            'income_costs': ('Dividenden & Kosten', [self.dock_income_costs]),
            'market': ('Marktdaten', [self.dock_market]),
            'history': ('Historie und Import', [self.dock_history, self.dock_quality]),
            'rebalance': ('Rebalancing', [self.dock_rebalance, self.dock_risk]),
            'etf': ('ETF-Durchrechnung', [self.dock_lookthrough]),
        }
        self.navigation = QToolBar('Navigation', self)
        self.navigation.setObjectName('navigation'); self.navigation.setMovable(False); self.navigation.setFloatable(False)
        self.navigation.setOrientation(Qt.Orientation.Vertical)
        self.addToolBar(Qt.ToolBarArea.LeftToolBarArea, self.navigation)
        panel = QWidget(); panel.setObjectName('navigationPanel'); panel.setMinimumWidth(152)
        layout = QVBoxLayout(panel); layout.setContentsMargins(10, 14, 10, 12); layout.setSpacing(6)
        brand = QLabel('PortMan'); brand.setObjectName('brand'); layout.addWidget(brand)
        subtitle = QLabel('Portfolio im Blick'); subtitle.setObjectName('navSubtitle'); layout.addWidget(subtitle)
        self.nav_buttons = {}; group = QButtonGroup(self); group.setExclusive(True)
        main_pages = (
            ('dashboard', 'Übersicht'),
            ('holdings', 'Depots'),
            ('accounts', 'Konten'),
            ('history', 'Transaktionen'),
            ('analysis', 'Auswertungen'),
        )
        for index, (key, title) in enumerate(main_pages, 1):
            button = QPushButton(title); button.setObjectName('navButton'); button.setCheckable(True)
            button.setShortcut(f'Alt+{index}')
            button.setToolTip(f'{title} (Alt+{index})')
            button.clicked.connect(lambda checked=False, p=key: self.show_workspace(p))
            group.addButton(button); layout.addWidget(button); self.nav_buttons[key] = button
        reports = QToolButton(panel)
        reports.setObjectName('secondaryNavigation')
        reports.setText('Weitere Auswertungen')
        reports.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        reports.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        reports_menu = QMenu(reports)
        for key in ('grid', 'performance', 'income_costs', 'market', 'rebalance', 'etf'):
            action = reports_menu.addAction(self.pages[key][0])
            action.triggered.connect(lambda checked=False, page=key: self.show_workspace(page))
        reports.setMenu(reports_menu)
        layout.addWidget(reports)
        layout.addStretch(1)
        import_button = QPushButton('Dateien importieren …', panel)
        import_button.setObjectName('primaryImportButton')
        import_button.setToolTip('PDF-, CSV- oder Excel-Dateien auswählen (Strg+O)')
        import_button.clicked.connect(lambda: self.import_files_action.trigger())
        layout.addWidget(import_button)
        scroll = QScrollArea(); scroll.setObjectName('navigationScroll'); scroll.setWidgetResizable(True); scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setFixedWidth(174); scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(panel); self.navigation.addWidget(scroll)
        self.dashboard.navigate.connect(self.show_workspace)
        self.modernize_tables()
        self.apply_table_fonts()

    def register_expert_action(self, action):
        self.expert_actions = getattr(self, 'expert_actions', [])
        if action not in self.expert_actions:
            self.expert_actions.append(action)
        action.setVisible(bool(self.settings.get('expert_mode', False)))
        return action

    def register_expert_widget(self, widget):
        self.expert_widgets = getattr(self, 'expert_widgets', [])
        if widget not in self.expert_widgets:
            self.expert_widgets.append(widget)
        widget.setVisible(bool(self.settings.get('expert_mode', False)))
        return widget

    def set_expert_mode(self, enabled):
        changed = bool(self.settings.get('expert_mode', False)) != bool(enabled)
        self.settings['expert_mode'] = bool(enabled)
        for action in getattr(self, 'expert_actions', []):
            action.setVisible(bool(enabled))
        for widget in getattr(self, 'expert_widgets', []):
            widget.setVisible(bool(enabled))
        if hasattr(self, 'expert_mode_action') and self.expert_mode_action.isChecked() != bool(enabled):
            self.expert_mode_action.blockSignals(True)
            self.expert_mode_action.setChecked(bool(enabled))
            self.expert_mode_action.blockSignals(False)
        if changed and getattr(self, '_v09_ready', False):
            self.save_settings()

    def apply_table_fonts(self):
        compact = bool(self.settings.get('compact_v09'))
        for table in self.findChildren(QTableView):
            table_type = table.property('table_type')
            if not table_type: continue
            size = (TABLE_FONTS.get(table_type) or {}).get('size') or 9
            table.verticalHeader().setDefaultSectionSize(row_height_for(size, compact and table_type == 'positions'))

    def modernize_tables(self):
        for action in self.findChildren(QAction):
            action.setText(re.sub(r'^[^\w]+', '', action.text()))
        for table in self.findChildren(QTableWidget):
            table.setAlternatingRowColors(True); table.verticalHeader().hide()
            table.verticalHeader().setDefaultSectionSize(30)
            table.setShowGrid(False)
            table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        for tree in self.findChildren(QTreeWidget):
            tree.setAlternatingRowColors(True); tree.setUniformRowHeights(True)

    def show_workspace(self, name):
        if name not in self.pages: return
        title, selected = self.pages[name]
        self.setUpdatesEnabled(False)
        try:
            for dock in self.docks: dock.hide()
            for dock in selected:
                if dock.isFloating(): dock.setFloating(False)
                self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)
                dock.show()
            for dock in selected[1:]: self.tabifyDockWidget(selected[0], dock)
            selected[0].raise_()
            main_name = {
                'grid': 'analysis', 'performance': 'analysis', 'income_costs': 'analysis',
                'market': 'analysis', 'rebalance': 'analysis', 'etf': 'analysis',
            }.get(name, name)
            if main_name in self.nav_buttons:
                self.nav_buttons[main_name].setChecked(True)
            self.setWindowTitle(f'PortMan · {title}')
            self.settings['active_workspace'] = name
        finally: self.setUpdatesEnabled(True)
        for dock in selected:
            if hasattr(self, '_scope_refreshers'):
                self.refresh_scope_dock(dock)
        self.statusBar().showMessage(f'{title} · Konto und Datum oben auswählen. Bereiche bleiben frei andockbar.', 5000)
        self.schedule_layout_save()

    def select_gui_style(self, name):
        self.settings['gui_style'] = name
        self.settings['dark_theme'] = name in ('dark', 'nord', 'contrast')
        apply_theme(name, self.settings.get('table_fonts_v10'))
        self.apply_table_fonts()
        for key, action in getattr(self, 'gui_style_actions', {}).items():
            action.setChecked(key == name)
        self.refresh_all_views(); self.dashboard.refresh(); self.visuals_widget.refresh()
        if hasattr(self, 'chart_grid_widget'): self.chart_grid_widget.refresh()
        self.market_widget.show_details(); self.performance_widget.draw_chart(); self.history_widget.refresh_wealth()
        # Also recolor legacy plots without changing their calculations.
        for widget in self.findChildren(QWidget):
            figure = getattr(widget, 'figure', None)
            if figure is not None and hasattr(figure, 'axes'):
                style_figure(figure)
                for axis in figure.axes:
                    style_axis(axis)
                    axis.title.set_color(COLORS['text'])
                    axis.xaxis.label.set_color(COLORS['text']); axis.yaxis.label.set_color(COLORS['text'])
                    for label in axis.texts: label.set_color(COLORS['text'])
                canvas = widget if hasattr(widget, 'draw_idle') else figure.canvas
                if hasattr(canvas, 'draw_idle'): canvas.draw_idle()
        self.save_settings()

    def refresh_charts_after_style(self):
        for widget in (getattr(self, 'visualizations_board', None), getattr(self, 'visuals_widget', None),
                       getattr(self, 'chart_grid_widget', None)):
            if widget is not None:
                widget.refresh()
        if hasattr(self, 'dashboard'):
            self.dashboard.refresh()
        market = getattr(self, 'market_widget', None)
        if market is not None:
            market.show_details()
        performance = getattr(self, 'performance_widget', None)
        if performance is not None:
            performance.draw_chart()
        history = getattr(self, 'history_widget', None)
        if history is not None:
            history.refresh_wealth()
