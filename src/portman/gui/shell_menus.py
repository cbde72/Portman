"""Menubar and toolbar construction for the V06 shell."""
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QLabel, QPushButton


class ShellMenusMixin:
    def create_menus_and_toolbar(self):
        menubar = self.menuBar()

        # --- MENÜ: Datei ---
        file_menu = menubar.addMenu("&Datei")
        self.import_menu = file_menu.addMenu('&Importieren')
        self.import_menu.setTitle('Importieren')
        self.online_menu = file_menu.addMenu('&Online')

        act_import = QAction("&Dateien importieren …", self)
        act_import.setShortcut(QKeySequence("Ctrl+O"))
        act_import.triggered.connect(self.import_csv)
        self.import_menu.addAction(act_import)
        self.import_files_action = act_import
        self.import_menu.addSeparator()
        act_renault_pdf = QAction('&Renault PDF importieren …', self)
        act_renault_pdf.triggered.connect(self.import_renault_pdf)
        self.import_menu.addAction(act_renault_pdf)
        self.register_expert_action(act_renault_pdf)
        act_baader_pdf = QAction('&Baader PDFs aus Ordner importieren (rekursiv) …', self)
        act_baader_pdf.triggered.connect(self.import_baader_pdf)
        self.import_menu.addAction(act_baader_pdf)
        self.register_expert_action(act_baader_pdf)
        act_comdirect_pdf = QAction('&comdirect Finanzreports (PDF) importieren …', self)
        act_comdirect_pdf.triggered.connect(self.import_comdirect_pdf)
        self.import_menu.addAction(act_comdirect_pdf)
        self.register_expert_action(act_comdirect_pdf)
        self.import_menu.addSeparator()

        act_history = QAction("&History: Blatt aus allen Excel-Dateien importieren …", self)
        act_history.triggered.connect(self.sync_history)
        self.import_menu.addAction(act_history)
        self.register_expert_action(act_history)
        act_savings = QAction("&History: Tagesgeld und Festgeld importieren …", self)
        act_savings.triggered.connect(lambda: self.sync_history(savings=True))
        self.import_menu.addAction(act_savings)
        self.register_expert_action(act_savings)

        act_accounts = QAction("&Konten verwalten …", self)
        act_accounts.triggered.connect(self.manage_accounts)
        file_menu.addAction(act_accounts)
        file_menu.addSeparator()

        act_sync_banks = QAction('&Alle Online-Konten synchronisieren …', self)
        act_sync_banks.triggered.connect(self.sync_online_accounts)
        self.online_menu.addAction(act_sync_banks)

        bank_connection = QAction('&Bankzugang einrichten …', self)
        bank_connection.triggered.connect(self.open_connection_proposal)
        self.online_menu.addAction(bank_connection)

        act_market = QAction('&Marktdaten aktualisieren', self)
        act_market.triggered.connect(lambda: (self.show_workspace('market'), self.market_widget.start()))
        self.online_menu.addAction(act_market)
        credentials = QAction("&Marktdaten-Zugänge …", self)
        credentials.triggered.connect(lambda: self.market_widget.configure_credentials())
        self.online_menu.addAction(credentials)
        self.register_expert_action(credentials)
        history = QAction('&Kursverläufe seit Besitzbeginn laden und speichern', self)
        history.triggered.connect(lambda: self.market_widget.open_history(auto_start=True))
        self.online_menu.addAction(history)
        self.register_expert_action(history)

        act_save = QAction("&Einstellungen und Metadaten speichern", self)
        act_save.setShortcut(QKeySequence("Ctrl+S"))
        act_save.triggered.connect(self.save_portfolio)
        file_menu.addAction(act_save)

        file_menu.addSeparator()

        act_fetch_etf = QAction("&ETF-Positionen aus Factsheets laden", self)
        act_fetch_etf.triggered.connect(self.fetch_etf_holdings_online)
        file_menu.addAction(act_fetch_etf)
        self.register_expert_action(act_fetch_etf)

        act_names = QAction("&Anzeigenamen aus ISIN ermitteln", self)
        act_names.triggered.connect(self.resolve_isin_names)
        file_menu.addAction(act_names)
        self.register_expert_action(act_names)

        # --- MENÜ: Ansicht ---
        view_menu = menubar.addMenu("&Ansicht")
        self.view_menu = view_menu

        dock_menu = view_menu.addMenu('&Bereiche und Fenster')
        self.register_expert_action(dock_menu.menuAction())
        for dock in self.docks:
            action = dock.toggleViewAction()
            action.setStatusTip(f"Fenster '{dock.windowTitle()}' ein- oder ausblenden")
            cleaned = action.text().replace('🔍 ', '')
            cleaned = cleaned.replace('Risiko & Kennzahlen-Analyse', 'Risiko & Kennzahlen-Analyse')  # no-op
            action.setText(cleaned)
            dock_menu.addAction(action)

        view_menu.addSeparator()
        show_all_action = QAction("&Alle Bereiche anzeigen", self)
        show_all_action.setShortcut(QKeySequence("Ctrl+Shift+A"))
        show_all_action.triggered.connect(self.show_all_docks)
        view_menu.addAction(show_all_action)

        focus_action = QAction("&Nur aktiven Bereich anzeigen", self)
        focus_action.setShortcut(QKeySequence("Ctrl+Shift+F"))
        focus_action.triggered.connect(self.focus_active_dock)
        view_menu.addAction(focus_action)

        reset_action = QAction("&Fenster-Layout zurücksetzen", self)
        reset_action.setShortcut(QKeySequence("Ctrl+Shift+0"))
        reset_action.triggered.connect(self.reset_dock_layout)
        view_menu.addAction(reset_action)

        preset_menu = view_menu.addMenu("&Layout-Presets")
        for title, preset, shortcut in (
            ("Übersicht", "overview", "Ctrl+1"),
            ("Analyse", "analysis", "Ctrl+2"),
            ("Historie", "history", "Ctrl+3"),
        ):
            action = QAction(title, self)
            action.setShortcut(QKeySequence(shortcut))
            action.triggered.connect(lambda checked=False, name=preset: self.apply_layout_preset(name))
            preset_menu.addAction(action)

        view_menu.addSeparator()
        save_layout_action = QAction("&Layout unter Namen speichern...", self)
        save_layout_action.triggered.connect(self.save_named_layout)
        view_menu.addAction(save_layout_action)
        self.named_layout_menu = view_menu.addMenu("&Gespeichertes Layout laden")
        self.named_layout_menu.aboutToShow.connect(self.populate_named_layout_menu)

        self.lock_docks_action = QAction("&Layout sperren", self)
        self.lock_docks_action.setCheckable(True)
        self.lock_docks_action.setShortcut(QKeySequence("Ctrl+Shift+L"))
        self.lock_docks_action.setChecked(self.lock_editable_checked())
        self.lock_docks_action.toggled.connect(self.on_lock_docks_toggled)
        dock_menu.addSeparator()
        dock_menu.addAction(self.lock_docks_action)

        view_menu.addSeparator()
        self.expert_mode_action = QAction('&Expertenfunktionen anzeigen', self)
        self.expert_mode_action.setCheckable(True)
        self.expert_mode_action.setChecked(bool(self.settings.get('expert_mode', False)))
        self.expert_mode_action.toggled.connect(self.set_expert_mode)
        view_menu.addAction(self.expert_mode_action)

        # --- MENÜ: Bearbeiten / Hilfe ---
        self.edit_menu = menubar.addMenu("&Bearbeiten")
        self.help_menu = menubar.addMenu("&Hilfe")

        # --- MENÜ: Werkzeuge (merged Extras) ---
        self.tools_menu = menubar.addMenu("&Werkzeuge")
        tools_menu = self.tools_menu

        report_action = QAction("&Portfolio-Bericht exportieren (HTML)", self)
        report_action.triggered.connect(self.export_portfolio_report)
        tools_menu.addAction(report_action)

        rebal_export_action = QAction("&Rebalancing-Orders exportieren", self)
        rebal_export_action.triggered.connect(self.export_rebalancing_plan)
        tools_menu.addAction(rebal_export_action)
        self.register_expert_action(rebal_export_action)

        from portman.gui.dockable_toolbar import DockableToolbar
        self.scope_toolbar = DockableToolbar(self, '&Konto und Datum', 'toolbar_scope')
        self.scope_toolbar.addWidget(QLabel('Konto'))
        self.combo_account.setMinimumWidth(150)
        self.scope_toolbar.addWidget(self.combo_account)
        if hasattr(self, 'account_checkbox_panel'):
            self.scope_toolbar.addWidget(QLabel('Mehrfachauswahl:'))
            self.scope_toolbar.addWidget(self.account_checkbox_panel)
        self.scope_toolbar.addWidget(QLabel('Datum'))
        for name, arrows, label, days, months in (
                ('btn_previous_month', '«', 'Einen Monat zurück', 0, -1),
                ('btn_previous_week', '‹', 'Eine Woche zurück', -7, 0)):
            button = QPushButton(arrows)
            button.setFixedWidth(28)
            button.setToolTip(label)
            button.setAccessibleName(label)
            button.clicked.connect(lambda checked=False, d=days, m=months: self.shift_date(d, m))
            setattr(self, name, button)
            self.scope_toolbar.addWidget(button)
            self.register_expert_widget(button)
        self.btn_previous_date = QPushButton('‹')
        self.btn_previous_date.setFixedWidth(24)
        self.btn_previous_date.setToolTip('Einen Tag zurück')
        self.btn_previous_date.setAccessibleName('Älteres Datum')
        self.btn_previous_date.clicked.connect(lambda: self.step_snapshot(1))
        self.scope_toolbar.addWidget(self.btn_previous_date)
        from PySide6.QtWidgets import QDateEdit
        from PySide6.QtCore import QDate
        self.date_selector = QDateEdit(QDate.currentDate())
        self.date_selector.setCalendarPopup(True)
        self.date_selector.setDisplayFormat('dd.MM.yyyy')
        self.date_selector.setAccessibleName('Datum für alle Konten und Depots')
        self.date_selector.setMinimumWidth(110)
        self.date_selector.dateChanged.connect(self.select_calendar_date)
        self.combo_snapshot.hide()
        self.scope_toolbar.addWidget(self.date_selector)
        today_button = QPushButton('Heute')
        today_button.setFixedWidth(50)
        today_button.clicked.connect(lambda: self.date_selector.setDate(QDate.currentDate()))
        self.scope_toolbar.addWidget(today_button)
        self.btn_next_date = QPushButton('›')
        self.btn_next_date.setFixedWidth(24)
        self.btn_next_date.setToolTip('Einen Tag vor')
        self.btn_next_date.setAccessibleName('Neueres Datum')
        self.btn_next_date.clicked.connect(lambda: self.step_snapshot(-1))
        self.scope_toolbar.addWidget(self.btn_next_date)
        for name, arrows, label, days, months in (
                ('btn_next_week', '›', 'Eine Woche vor', 7, 0),
                ('btn_next_month', '»', 'Einen Monat vor', 0, 1)):
            button = QPushButton(arrows)
            button.setFixedWidth(28)
            button.setToolTip(label)
            button.setAccessibleName(label)
            button.clicked.connect(lambda checked=False, d=days, m=months: self.shift_date(d, m))
            setattr(self, name, button)
            self.scope_toolbar.addWidget(button)
            self.register_expert_widget(button)
        self.combo_snapshot.currentIndexChanged.connect(self.update_date_navigation)
        self.update_date_navigation()
