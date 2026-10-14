"""Central widgets and dock construction for the V06 shell."""
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QComboBox, QDockWidget, QDoubleSpinBox, QFormLayout, QGroupBox, QHBoxLayout,
    QLabel, QLineEdit, QProgressBar, QPushButton, QScrollArea, QSpinBox,
    QTabWidget, QTableWidget, QTreeWidget, QVBoxLayout, QWidget,
)

try:
    from PySide6.QtWebEngineWidgets import QWebEngineView
except ImportError:
    QWebEngineView = None

from portman.accounts_widget import AccountsWidget
from portman.data_quality_widget import DataQualityWidget
from portman.date_display import display_dates
from portman.history_widget import HistoryWidget
from portman.market_widget import MarketWidget
from portman.performance_widget import PerformanceWidget
from portman.portfolio_chart import PortfolioChartCanvas
from portman.security_classification import ASSET_TYPES, CAP_SIZES, REGIONS

from portman.gui.window_compat import webengine_available


class ShellDocksMixin:
    def init_widgets(self):
        """Initialisiert zentrale Steuerelemente wie Comboboxen und den Fortschrittsbalken."""
        self.combo_region = QComboBox()
        self.combo_region.addItems(["Alle Regionen", *REGIONS])
        self.combo_region.currentIndexChanged.connect(self.apply_filters)

        self.combo_cap = QComboBox()
        self.combo_cap.addItems(["Alle Cap-Größen", *CAP_SIZES])
        self.combo_cap.currentIndexChanged.connect(self.apply_filters)

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setMaximumWidth(150)

        from portman.gui.checkable_combo import CheckableComboBox
        self.combo_account = CheckableComboBox()
        self.combo_account.checked_items_changed.connect(self.on_portfolio_scope_changed)
        self.rebuild_account_combo()

        self.combo_snapshot = QComboBox()
        self.combo_snapshot.addItem("Aktuell", "9999-12-31")
        for label, value in self.repository.scope_dates():
            self.combo_snapshot.addItem(display_dates(label), value)
        self.combo_snapshot.currentIndexChanged.connect(self.on_portfolio_scope_changed)

    def rebuild_account_combo(self):
        """Baut die Konten-Checkbox-Liste neu auf (z. B. nach Kontoänderungen)."""
        if not hasattr(self, 'combo_account') or not isinstance(self.combo_account,
                                                                __import__('portman.gui.checkable_combo', fromlist=['CheckableComboBox']).CheckableComboBox):
            return
        checked = self.combo_account.checked_data()
        self.combo_account.set_items('Alle Konten',
                                      [(account, account) for account in self.repository.accounts()])
        if checked:
            self.combo_account.restore_checked(checked)

    def init_docks(self):
        self.dock_dashboard = QDockWidget("Dashboard", self)
        self.dock_dashboard.setObjectName("dock_dashboard")
        self.dock_dashboard.setWidget(self.dashboard)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.dock_dashboard)

        # 1. DOCK: Portfolio Tabellen (Inklusive Dividenden-Tab)
        self.dock_tables = QDockWidget("Portfolio Übersicht", self)
        self.dock_tables.setObjectName("dock_tables")

        self.tabs = QTabWidget()
        self.tables: dict[str, QTableWidget] = {}

        for category in ["Alle", *ASSET_TYPES]:
            table = self.create_position_table(category)
            self.connect_position_details(table)
            self.tables[category] = table
            self.tabs.addTab(table, category)

        self.tabs.currentChanged.connect(self.on_tab_changed)
        positions_widget = QWidget(); positions_layout = QVBoxLayout(positions_widget)
        self.positions_layout = positions_layout
        positions_layout.setContentsMargins(0, 0, 0, 0)
        self.position_search = QLineEdit(); self.position_search.setPlaceholderText('Name oder ISIN suchen …')
        self.search_timer = QTimer(self)
        self.search_timer.setSingleShot(True)
        self.search_timer.setInterval(200)
        self.search_timer.timeout.connect(self.refresh_tables)
        self.position_search.textChanged.connect(lambda: self.search_timer.start())
        # These controls remain as internal defaults for older view code, but are no
        # longer part of the positions UI. The table is the primary view.
        for control in (self.position_search, self.combo_region, self.combo_cap): control.hide()
        positions_layout.addWidget(self.tabs)
        self.dock_tables.setWidget(positions_widget)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.dock_tables)

        # 2. DOCK: ETF Look-Through
        self.dock_lookthrough = QDockWidget("Versteckte Einzeltitel (ETF-Durchrechnung)", self)
        self.dock_lookthrough.setObjectName("dock_lookthrough")

        lt_widget = QWidget()
        lt_layout = QVBoxLayout(lt_widget)

        lt_layout.addWidget(QLabel("<b>Echte Kumulierte Exposition (Direktaktien + ETF-Anteile):</b>"))
        self.tree_lookthrough = QTreeWidget()
        self.tree_lookthrough.setHeaderLabels(["Position / Ursprung", "Typ", "Direkt (€)", "via ETF (€)", "Gesamtwert (€)"])
        lt_layout.addWidget(self.tree_lookthrough)

        self.dock_lookthrough.setWidget(lt_widget)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.dock_lookthrough)

        # 3. DOCK: Risiko, Volatilität & Dividenden-KPIs
        self.dock_risk = QDockWidget("Risiko & Kennzahlen-Analyse", self)
        self.dock_risk.setObjectName("dock_risk")

        risk_widget = QWidget()
        risk_layout = QVBoxLayout(risk_widget)

        metrics_group = QGroupBox("Risiko & Ertrags-Kennzahlen")
        metrics_layout = QVBoxLayout(metrics_group)

        self.lbl_hhi = QLabel("<b>Diversifikations-Score (HHI):</b> -")
        self.lbl_beta = QLabel("<b>Gewichtetes Markt-Beta:</b> -")
        self.lbl_vola = QLabel("<b>Gewichtete Einzelvolatilität:</b> -")
        self.lbl_div_total = QLabel("<b>Hinterlegte Dividendenrendite:</b> -")

        metrics_layout.addWidget(self.lbl_hhi)
        metrics_layout.addWidget(self.lbl_beta)
        metrics_layout.addWidget(self.lbl_vola)
        metrics_layout.addWidget(self.lbl_div_total)
        risk_layout.addWidget(metrics_group)

        warn_group = QGroupBox("Klumpenrisiko-Warnung")
        warn_layout = QVBoxLayout(warn_group)

        thresh_bar = QHBoxLayout()
        thresh_bar.addWidget(QLabel("Warnschwelle (%):"))
        self.spin_threshold = QSpinBox()
        self.spin_threshold.setRange(1, 50)
        self.spin_threshold.setValue(10)
        self.spin_threshold.valueChanged.connect(self.update_risk_analysis)
        thresh_bar.addWidget(self.spin_threshold)
        thresh_bar.addStretch()
        warn_layout.addLayout(thresh_bar)

        self.tree_warnings = QTreeWidget()
        self.tree_warnings.setHeaderLabels(["Position / Name", "ISIN", "Anteil (%)", "Wert (€)"])
        warn_layout.addWidget(self.tree_warnings)

        risk_layout.addWidget(warn_group)
        self.dock_risk.setWidget(risk_widget)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.dock_risk)

        # 4. DOCK: Rebalancing-Rechner (Dynamisch)
        self.dock_rebalance = QDockWidget("Rebalancing-Rechner", self)
        self.dock_rebalance.setObjectName("dock_rebalance")

        self.rebalance_widget = QWidget()
        self.rebalance_layout = QVBoxLayout(self.rebalance_widget)

        self.target_group = QGroupBox("Ziel-Allokation (%)")
        self.target_form = QFormLayout(self.target_group)
        self.spin_targets: dict[str, QSpinBox] = {}

        self.rebalance_layout.addWidget(self.target_group)

        options_group = QGroupBox("Orderbedingungen")
        options = QFormLayout(options_group)
        self.combo_rebalance_mode = QComboBox(); self.combo_rebalance_mode.addItems(["Nur kaufen", "Kaufen und verkaufen"])
        self.spin_rebalance_cash = QDoubleSpinBox(); self.spin_rebalance_cash.setRange(0, 10000000); self.spin_rebalance_cash.setDecimals(2); self.spin_rebalance_cash.setSuffix(" €")
        self.spin_rebalance_tolerance = QDoubleSpinBox(); self.spin_rebalance_tolerance.setRange(0, 25); self.spin_rebalance_tolerance.setValue(1); self.spin_rebalance_tolerance.setSingleStep(.5); self.spin_rebalance_tolerance.setSuffix(" %-Punkte")
        self.spin_rebalance_minimum = QDoubleSpinBox(); self.spin_rebalance_minimum.setRange(0, 1000000); self.spin_rebalance_minimum.setValue(100); self.spin_rebalance_minimum.setSuffix(" €")
        self.spin_rebalance_fee = QDoubleSpinBox(); self.spin_rebalance_fee.setRange(0, 1000); self.spin_rebalance_fee.setDecimals(2); self.spin_rebalance_fee.setSuffix(" € je Order")
        options.addRow("Modus:",self.combo_rebalance_mode);options.addRow("Verfügbares Bargeld:",self.spin_rebalance_cash);options.addRow("Toleranzband:",self.spin_rebalance_tolerance);options.addRow("Mindestorder:",self.spin_rebalance_minimum);options.addRow("Gebühr:",self.spin_rebalance_fee)
        for widget in (self.combo_rebalance_mode,self.spin_rebalance_cash,self.spin_rebalance_tolerance,self.spin_rebalance_minimum,self.spin_rebalance_fee):
            (widget.currentIndexChanged if isinstance(widget,QComboBox) else widget.valueChanged).connect(self.calculate_rebalancing)
        self.rebalance_layout.addWidget(options_group)
        self.lbl_rebalance_summary = QLabel(); self.rebalance_layout.addWidget(self.lbl_rebalance_summary)

        self.tree_rebalance = QTreeWidget()
        self.tree_rebalance.setHeaderLabels(["Kategorie / Region", "Ist (%)", "Ziel (%)", "Ist (€)", "Soll (€)", "Order (€)", "Gebühr (€)", "Nachher (%)"])
        self.rebalance_layout.addWidget(self.tree_rebalance)

        self.dock_rebalance.setWidget(self.rebalance_widget)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.dock_rebalance)

        # 5. DOCK: Visualisierungen & Benchmarking
        self.dock_chart = QDockWidget("Visualisierung & Benchmarking", self)
        self.dock_chart.setObjectName("dock_chart")

        chart_widget = QWidget()
        chart_layout = QVBoxLayout(chart_widget)
        chart_control_layout = QHBoxLayout()

        self.combo_chart_type = QComboBox()
        self.combo_chart_type.addItems(["Pie: Asset/Region Allokation", "Heatmap: Performance Top/Flop", "Benchmarking vs. Indizes"])
        self.combo_chart_type.currentIndexChanged.connect(self.update_chart)

        chart_control_layout.addWidget(QLabel("Ansicht:"))
        chart_control_layout.addWidget(self.combo_chart_type)
        chart_control_layout.addStretch()

        self.chart_canvas = PortfolioChartCanvas()
        chart_layout.addLayout(chart_control_layout)
        chart_layout.addWidget(self.chart_canvas)

        self.dock_chart.setWidget(chart_widget)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.dock_chart)

        # 6. DOCK: ISIN Browser
        self.dock_browser = QDockWidget("ISIN Online-Analyse", self)
        self.dock_browser.setObjectName("dock_browser")

        browser_widget = QWidget()
        browser_layout = QVBoxLayout(browser_widget)
        top_browser_bar = QHBoxLayout()

        self.label_browser_isin = QLabel("<b>Keine ISIN ausgewählt</b>")
        btn_finanzen = QPushButton("Finanzen.net")
        btn_finanzen.clicked.connect(self.load_finanzen)
        btn_yahoo = QPushButton("Yahoo Finance")
        btn_yahoo.clicked.connect(self.load_yahoo)

        top_browser_bar.addWidget(self.label_browser_isin)
        top_browser_bar.addStretch()
        top_browser_bar.addWidget(btn_finanzen)
        top_browser_bar.addWidget(btn_yahoo)
        browser_layout.addLayout(top_browser_bar)

        self.current_isin_loaded = None
        if webengine_available():
            self.web_view = QWebEngineView()
            browser_layout.addWidget(self.web_view)
        else:
            self.fallback_label = QLabel("<i>QtWebEngine nicht verfügbar. Links werden im externen Browser geöffnet.</i>")
            self.fallback_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            browser_layout.addWidget(self.fallback_label)

        self.dock_browser.setWidget(browser_widget)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.dock_browser)

        self.dock_history = QDockWidget("Historie & Performance", self)
        self.dock_history.setObjectName("dock_history")
        self.history_widget = HistoryWidget(self.repository, self.selected_account, self)
        self.dock_history.setWidget(self.history_widget)
        self.history_widget.data_changed.connect(self.accounts_changed)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.dock_history)

        self.dock_performance = QDockWidget("Performance", self)
        self.dock_performance.setObjectName("dock_performance")
        self.performance_widget = PerformanceWidget(self.repository, self.selected_account, self)
        self.dock_performance.setWidget(self.performance_widget)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.dock_performance)

        self.dock_income_costs = QDockWidget("Dividenden & Kosten", self)
        self.dock_income_costs.setObjectName("dock_income_costs")
        from portman.income_costs_widget import IncomeCostsWidget
        self.income_costs_widget = IncomeCostsWidget(self.repository, self.selected_date, self)
        self.dock_income_costs.setWidget(self.income_costs_widget)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.dock_income_costs)

        self.dock_quality = QDockWidget("Datenqualität", self)
        self.dock_quality.setObjectName("dock_quality")
        self.quality_widget = DataQualityWidget(self.repository, self.dashboard_scope, self)
        self.dock_quality.setWidget(self.quality_widget)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.dock_quality)

        self.dock_accounts = QDockWidget("Kontenübersicht", self)
        self.dock_accounts.setObjectName("dock_accounts")
        self.accounts_widget = AccountsWidget(self.repository, self.selected_date, self)
        self.accounts_widget.changed.connect(self.accounts_changed)
        self.accounts_widget.manage_requested.connect(self.manage_accounts)
        self.accounts_widget.account_selected.connect(self.select_overview_account)
        self.dock_accounts.setWidget(self.accounts_widget)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.dock_accounts)

        self.dock_visuals = QDockWidget('Visualisierungen', self); self.dock_visuals.setObjectName('dock_visuals')
        from portman.visualization_board import VisualizationBoard
        self.visualizations_board = VisualizationBoard(self.repository, self.dashboard_scope, self.settings, self.save_settings, self)
        self.visuals_widget = self.visualizations_board.primary
        self.dock_visuals.setWidget(self.visualizations_board); self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.dock_visuals)
        self.dock_grid = QDockWidget('Diagramm-Raster', self); self.dock_grid.setObjectName('dock_grid')
        from portman.chart_grid import ChartGridWidget
        self.chart_grid_widget = ChartGridWidget(self.repository, self.dashboard_scope, self.settings, self.save_settings, self)
        self.dock_grid.setWidget(self.chart_grid_widget); self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.dock_grid)
        self.dock_market = QDockWidget('Marktdaten', self); self.dock_market.setObjectName('dock_market')
        self.market_widget = MarketWidget(self.repository, self.dashboard_scope, self)
        self.market_widget.changed.connect(self.reload_portfolio)
        self.dock_market.setWidget(self.market_widget); self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.dock_market)

        # Rechten Stapel als Tabs gruppieren
        self.tabifyDockWidget(self.dock_lookthrough, self.dock_risk)
        self.tabifyDockWidget(self.dock_risk, self.dock_rebalance)
        self.tabifyDockWidget(self.dock_rebalance, self.dock_chart)
        self.tabifyDockWidget(self.dock_chart, self.dock_browser)
        self.tabifyDockWidget(self.dock_browser, self.dock_history)
        self.tabifyDockWidget(self.dock_history, self.dock_performance)
        self.tabifyDockWidget(self.dock_performance, self.dock_income_costs)
        self.tabifyDockWidget(self.dock_income_costs, self.dock_quality)
        self.tabifyDockWidget(self.dock_quality, self.dock_dashboard)
        self.tabifyDockWidget(self.dock_visuals, self.dock_grid)
        self.docks = [
            self.dock_dashboard, self.dock_tables, self.dock_lookthrough,
            self.dock_risk, self.dock_rebalance, self.dock_chart,
            self.dock_browser, self.dock_history, self.dock_performance, self.dock_income_costs,
            self.dock_quality, self.dock_accounts, self.dock_visuals, self.dock_grid, self.dock_market,
        ]
        for dock in self.docks:
            content = dock.widget()
            scroll = QScrollArea(); scroll.setWidgetResizable(True)
            scroll.setFrameShape(QScrollArea.Shape.NoFrame); scroll.setWidget(content)
            dock.setWidget(scroll)
            dock.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
            dock.setFeatures(
                QDockWidget.DockWidgetFeature.DockWidgetClosable
                | QDockWidget.DockWidgetFeature.DockWidgetMovable
                | QDockWidget.DockWidgetFeature.DockWidgetFloatable
            )
            dock.setMinimumSize(220, 140)
        # The navigation already names these primary pages. Keep their dock
        # title bars usable for dragging, but omit the repeated headings.
        for dock, action_label in ((self.dock_dashboard, 'Dashboard'),
                                   (self.dock_accounts, 'Kontenübersicht'),
                                   (self.dock_tables, 'Depotpositionen')):
            dock.setWindowTitle('')
            dock.toggleViewAction().setText(action_label)
        self.setup_rebalancing_ui()
        self.dock_dashboard.raise_()
