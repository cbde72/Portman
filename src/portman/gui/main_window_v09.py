"""V09 main-window behaviour, extracted from the ``src/Gui/PortMan_V09.py`` entry point."""

from datetime import date, timedelta, datetime
from pathlib import Path
from PySide6.QtCore import Qt, QLockFile, QTimer, QThread
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMessageBox, QFileDialog, QLabel, QDialog, QVBoxLayout, QTableWidget, QDateEdit, QCheckBox
from portman.storage_v09 import initialize, recover_pending
from portman.persistence import atomic_json
from portman.formatting import euro
from portman.repository_v09 import RepositoryV09
from portman.settings_storage import StorageV07
from portman.widgets_v09 import DashboardV09, AnalysisDialog, EvidenceDialog, RecoveryDialog, CostDialog, ActionsDialog, populate
from portman.import_v09 import ImportSession
from portman.import_ui_v09 import ImportWizard, CsvProfileDialog
from portman.jobs_v09 import JobCenter, run_job
from portman.preferences_v09 import TablePreferences, enhance_chart
from portman.gui.position_tables import refresh_position_tables
from portman.gui.version_basics import install_version_basics
from portman.gui.quality_issues import open_quality_issue as handle_quality_issue
from portman.gui.change_log import show_change_log
from portman.gui.import_result import show_import_results
from portman.gui.window_compat import project_root


def DecimalSafe(value):
    from decimal import Decimal

    return Decimal(value)


class MainWindowV09Mixin:
    def create_storage(self):
        folder = self.portfolio_folder or project_root() / "data/v09"
        folder.mkdir(parents=True, exist_ok=True)
        self.instance_lock = QLockFile(str(folder / "portman.lock"))
        self.instance_lock.setStaleLockTime(0)
        if not self.instance_lock.tryLock(0):
            raise RuntimeError("PortMan 09 ist für diesen Datenordner bereits geöffnet. Bitte die laufende Instanz verwenden.")
        self.data_folder = folder if self.portfolio_folder else initialize(project_root())
        from portman.portfolios import portfolio_name

        self.portfolio_label = portfolio_name(self.data_folder)
        recover_pending(self.data_folder)
        return StorageV07(self.data_folder)

    def create_repository(self):
        repo = RepositoryV09(self.data_folder / "portfolio.sqlite")
        repo.defer_initial_views = True
        return repo

    def create_dashboard(self):
        return DashboardV09(self.repository, self.dashboard_scope, self)

    def banking_directory(self):
        return self.data_folder / "banking"

    def __init__(self, portfolio_folder=None):
        from portman.gui_copy_support import install_global_copy_support
        install_global_copy_support()
        self.portfolio_folder = Path(portfolio_folder).resolve() if portfolio_folder else None
        if self.portfolio_folder and not (self.portfolio_folder / "portfolio.sqlite").is_file():
            raise ValueError("Portfolio-Datenbank wurde nicht gefunden.")
        self._navigation = []
        self._navigating = False
        self._v09_ready = False
        try:
            super().__init__()
        except Exception:
            if hasattr(self, "instance_lock"):
                self.instance_lock.unlock()
            raise
        install_version_basics(self, "PortMan 09")
        self.job_center = JobCenter(self)
        menu = self.create_v09_menus()
        from portman.portfolio_dialogs import install_portfolio_menu

        install_portfolio_menu(self)
        self.install_position_details()
        for chart in (self.visuals_widget, self.dashboard.visuals, self.performance_widget):
            enhance_chart(chart, self.repository)
        self.worker_timer = QTimer(self)
        self.worker_timer.timeout.connect(self.track_workers)
        self.worker_timer.start(500)
        self._v09_ready = True
        self.set_compact(self.compact_action.isChecked())
        self.update_totals()
        self.repository.defer_initial_views = False
        self.install_v09_workflows(menu)
        self._scope_dirty = set(self._scope_refreshers)
        self.show_workspace(self.settings.get("active_workspace", "dashboard"))
        self.setWindowTitle("PortMan 09 · " + self.portfolio_label + " · " + self.pages.get(self.settings.get("active_workspace"), ("Übersicht",))[0])
        from portman.gui.content_docks import ContentDocks

        self.content_docks = ContentDocks(self)
        if not self.settings.get("content_docks_enabled"):
            self.set_docks_locked(False)
            self.lock_docks_action.setChecked(True)
            self.settings["content_docks_enabled"] = True
        from portman.gui.appearance import install_appearance_menu

        install_appearance_menu(self)
        try:
            self.resize(max(self.width(), 1200), max(self.height(), 800))
            self.setMinimumSize(900, 650)
        except Exception:
            pass
        self.statusBar().showMessage(f"PortMan 09 · {self.portfolio_label} · Automatische Speicherung · {self.data_folder}", 12000)

    def create_v09_menus(self):
        excel_action = QAction("Excel-Assistent · Blätter und Unterdepots", self)
        excel_action.triggered.connect(self.excel_import)
        self.import_menu.addAction(excel_action)
        booking_action = QAction("Manuell ein- oder ausbuchen …", self)
        booking_action.triggered.connect(self.manual_booking)
        self.import_menu.addAction(booking_action)
        cost_split_action = QAction("&Kaufwert / Aktiensplit nachtragen …", self)
        cost_split_action.triggered.connect(self.adjust_cost_split)
        self.import_menu.addAction(cost_split_action)
        plugin_action = QAction("&PDF-Import-Plugins …", self)
        plugin_action.triggered.connect(self.open_pdf_plugins)
        self.import_menu.addAction(plugin_action)
        # The shared shell owns the top-level menus.  Reuse them so V09 does
        # not create duplicate Bearbeiten/Hilfe and Extras/Werkzeuge entries.
        tools_menu = getattr(self, "tools_menu", None)
        if tools_menu is None:
            tools_menu = self.menuBar().addMenu("&Werkzeuge")
            self.tools_menu = tools_menu
        for label, callback in [
            ("Aufgaben und Datenlücken", self.open_tasks),
            ("Aufträge / Fortschritt", self.job_center.show),
            ("Importsitzung fortsetzen", self.resume_import),
            ("CSV mit Profil importieren", self.profile_import),
            ("comdirect-Steuerdetails importieren", self.comdirect_tax_detail_import),
            ("Steuerliche Detailansicht", self.open_tax_detail_view),
            ("Steuerliche Jahresübersicht", self.open_tax_annual_summary),
            ("Umbuchungen / Kapitalmaßnahmen / Wechselkurse", self.open_actions),
            ("Zurück", self.go_back),
        ]:
            action = QAction(label, self)
            action.triggered.connect(callback)
            target = self.import_menu if label in ("Importsitzung fortsetzen", "CSV mit Profil importieren", "comdirect-Steuerdetails importieren") else tools_menu
            target.addAction(action)
        self.compact_action = QAction("&Kompakte Darstellung", self)
        self.compact_action.setCheckable(True)
        self.compact_action.setChecked(self.settings.get("compact_v09", False))
        tools_menu.addAction(self.compact_action)
        self.compact_action.toggled.connect(self.set_compact)
        return tools_menu

    def connect_position_details(self, table):
        table.doubleClicked.connect(self.open_position_details)

    def open_position_details(self, index):
        if index.column() == 0:
            from portman.gui.position_tables import open_position_editor

            open_position_editor(self, index)
            return
        EvidenceDialog(self.repository, index.data(Qt.ItemDataRole.UserRole), self.dashboard_scope(), self).exec()

    def install_position_details(self):
        self.totals = QLabel()
        self.totals.setObjectName("positionsFooter")
        self.totals.setTextFormat(Qt.TextFormat.RichText)
        self.totals.setStyleSheet(
            "QLabel#positionsFooter { font-weight: 700; padding: 10px 14px; border-top: 1px solid palette(mid); background: palette(alternateBase); }"
        )
        self.positions_layout.addWidget(self.totals)
        # Search updates are debounced through refresh_tables, which recomputes
        # the footer; only tab switches need the immediate hook here.
        self.tabs.currentChanged.connect(self.update_totals)

    def refresh_all_views(self):
        if getattr(self.repository, "defer_initial_views", False):
            return
        if hasattr(self, "_scope_refreshers"):
            self.refresh_visible_scope()
        else:
            super().refresh_all_views()

    def install_v09_workflows(self, menu):
        from portman.workflows_v09 import OperationsDialog, SessionDialog, SearchDialog

        edit_menu = getattr(self, "edit_menu", None)
        for label, callback, shortcut in [
            ("Globale Suche", lambda: self.run_edit_dialog(SearchDialog(self)), "Ctrl+K"),
            ("Buchungen, Gebühren und Regelmäßigkeit", lambda: self.run_edit_dialog(OperationsDialog(self.repository, self.dashboard_scope()[0], self)), ""),
            ("Importsitzungen verwalten", lambda: SessionDialog(self).exec(), ""),
        ]:
            action = QAction(label, self)
            action.triggered.connect(callback)
            if shortcut:
                action.setShortcut(shortcut)
            if label == "Globale Suche":
                if edit_menu is None:
                    edit_menu = self.menuBar().addMenu("&Bearbeiten")
                    self.edit_menu = edit_menu
                edit_menu.addAction(action)
            elif label == "Buchungen, Gebühren und Regelmäßigkeit":
                if edit_menu is None:
                    edit_menu = self.menuBar().addMenu("&Bearbeiten")
                    self.edit_menu = edit_menu
                edit_menu.addAction(action)
            elif label == "Importsitzungen verwalten":
                self.import_menu.addAction(action)
            else:
                menu.addAction(action)
        from portman.gui.dockable_toolbar import DockableToolbar

        self.period_toolbar = DockableToolbar(self, "&Analysezeitraum", "v09_period")
        self.period_toolbar.addWidget(QLabel("Analyse"))
        self.period_start = QDateEdit(self.performance_widget.start.date())
        self.period_end = QDateEdit(self.performance_widget.end.date())
        if self.period_start.date() >= self.period_end.date():
            self.period_start.setDate(self.period_end.date().addYears(-1))
        for editor in (self.period_start, self.period_end):
            editor.setCalendarPopup(True)
            editor.setDisplayFormat("dd.MM.yyyy")
            editor.setMinimumWidth(95)
            self.period_toolbar.addWidget(editor)
        self.period_note = QLabel("Bestände: Stichtag oben · Analysen: Zeitraum hier")
        self.period_note.setMinimumWidth(180)
        self.period_toolbar.addWidget(self.period_note)
        state = self.settings.get("dock_state")
        if state:
            try:
                self.restoreState(bytes.fromhex(state), 2)
            except ValueError:
                pass
        for toolbar in (self.scope_toolbar, self.period_toolbar):
            toolbar.setMovable(True)
            toolbar.setFloatable(True)
            try:
                toolbar.setIconSize(toolbar.iconSize())
            except Exception:
                pass
        self.period_start.dateChanged.connect(self.apply_period)
        self.period_end.dateChanged.connect(self.apply_period)
        self.performance_widget.start.dateChanged.connect(lambda day: self.sync_period_editor(self.period_start, day))
        self.performance_widget.end.dateChanged.connect(lambda day: self.sync_period_editor(self.period_end, day))
        # Add progress bar to status bar
        if hasattr(self, "progress_bar"):
            try:
                self.statusBar().removeWidget(self.progress_bar)
            except Exception:
                pass
            try:
                self.statusBar().removeWidget(self.progress_bar)
            except Exception:
                pass
            self.statusBar().addPermanentWidget(self.progress_bar)
            self.progress_bar.setVisible(False)
        self.saved_status = QLabel("Gespeichert")
        self.statusBar().addPermanentWidget(self.saved_status)
        self.status_timer = QTimer(self)
        self.status_timer.timeout.connect(self.update_save_status)
        self.status_timer.start(1500)
        self._last_revision = self.repository.revision()
        details = QCheckBox("Datenstand und Quellen ausführlich anzeigen")
        self.dashboard.wealth_box.layout().addWidget(details)
        details.toggled.connect(lambda visible: (self.dashboard.wealth_note.setVisible(visible), self.dashboard.estimate_note.setVisible(visible)))
        self.dashboard.wealth_note.hide()
        self.dashboard.estimate_note.hide()
        from portman.tables_v09 import DataTable

        for field in ("tx", "audit"):
            old = getattr(self.history_widget, field)
            headers = [old.horizontalHeaderItem(c).text() for c in range(old.columnCount())]
            panel = DataTable(headers)
            old.parentWidget().layout().replaceWidget(old, panel)
            old.hide()
            old.setParent(None)
            old.deleteLater()
            setattr(self.history_widget, field, panel.view)
            if field == "audit":
                panel.view.cellDoubleClicked.connect(self.history_widget.show_audit)
            if field == "tx":
                panel.search.hide()
                self.history_widget.install_transaction_details()
        self.preferences = TablePreferences(self)
        self.apply_table_fonts()
        self.setStyleSheet(
            self.styleSheet() + " QLineEdit:focus, QComboBox:focus, QDateEdit:focus, QTableView:focus { border: 2px solid #3b82f6; outline: none; }"
        )
        self.setTabOrder(self.combo_account, self.date_selector)
        self.setTabOrder(self.date_selector, self.period_start)
        self.setTabOrder(self.period_start, self.period_end)

    def run_edit_dialog(self, dialog):
        revision = self.repository.revision()
        try:
            return dialog.exec()
        finally:
            if self.repository.revision() != revision:
                self._scope_dirty.update(self._scope_refreshers)
                self.reload_portfolio()

    def sync_period_editor(self, editor, day):
        editor.blockSignals(True)
        editor.setDate(day)
        editor.blockSignals(False)

    def apply_period(self, *args):
        a, b = self.period_start.date(), self.period_end.date()
        if a >= b:
            self.period_note.setText("Ungültiger Zeitraum: Beginn muss vor Ende liegen.")
            return
        self.period_note.setText("Bestände: Stichtag · Analyse: " + a.toString("dd.MM.yyyy") + " – " + b.toString("dd.MM.yyyy"))
        self.performance_widget._setting_dates = True
        self.performance_widget.start.setDate(a)
        self.performance_widget.end.setDate(b)
        self.performance_widget._setting_dates = False
        self.performance_widget.range_combo.blockSignals(True)
        self.performance_widget.range_combo.setCurrentText("Benutzerdefiniert")
        self.performance_widget.range_combo.blockSignals(False)
        self.history_widget.start.setDate(a)
        self.history_widget.end.setDate(b)
        if self.settings.get("active_workspace") == "performance":
            self.performance_widget.calculate()
        else:
            self._scope_dirty.add(self.dock_performance)
        self.sync_chart_period()

    def sync_chart_period(self):
        if not hasattr(self, "period_start"):
            return
        if self.period_start.date() >= self.period_end.date():
            return
        from matplotlib.dates import date2num, DateFormatter, AutoDateFormatter, ConciseDateFormatter

        for chart in (self.visuals_widget, self.dashboard.visuals, self.performance_widget):
            for axis in chart.fig.axes:
                if isinstance(axis.xaxis.get_major_formatter(), (DateFormatter, AutoDateFormatter, ConciseDateFormatter)):
                    axis.set_xlim(date2num(self.period_start.date().toPython()), date2num(self.period_end.date().toPython()))
            if hasattr(chart, "_v09_chart"):
                chart._v09_chart[0].update()
                chart._v09_chart[0].push_current()
            chart.canvas.draw_idle()

    def update_save_status(self):
        running = any(r["end"] is None for r in self.job_center.records)
        if running:
            self.saved_status.setText("Verarbeitung läuft …")
            return
        revision = self.repository.poll_revision()
        if revision is None:
            self.saved_status.setText("Datenbank beschäftigt · Status wird erneut geprüft …")
            return
        if revision != self._last_revision:
            self.saved_status.setText("Gespeichert · " + datetime.now().strftime("%H:%M:%S"))
            self._last_revision = revision
        elif self.saved_status.text() in ("Verarbeitung läuft …", "Datenbank beschäftigt · Status wird erneut geprüft …"):
            self.saved_status.setText("Bereit · Keine ungespeicherten Datenänderungen")

    def save_settings(self):
        try:
            result = super().save_settings()
            if hasattr(self, "saved_status"):
                self.saved_status.setText("Gespeichert · " + datetime.now().strftime("%H:%M:%S"))
            return result
        except Exception:
            if hasattr(self, "saved_status"):
                self.saved_status.setText("Speichern fehlgeschlagen · Strg+S erneut versuchen")
            raise

    def track_workers(self):
        for title, worker in [
            ("Dateien lesen", getattr(self, "import_worker", None)),
            ("Marktdaten aktualisieren", getattr(self.market_widget, "worker", None)),
            ("Kurse aktualisieren", getattr(self, "fetcher", None)),
            ("ETF-Daten aktualisieren", getattr(self, "etf_fetcher", None)),
        ]:
            if worker and worker.isRunning():
                self.job_center.register(worker, title)
        for worker in self.findChildren(QThread):
            if worker.isRunning():
                self.job_center.register(worker, worker.objectName() or type(worker).__name__)

    def refresh_tables(self):
        refresh_position_tables(self)
        if hasattr(self, "totals"):
            self.update_totals()

    def update_totals(self, *args):
        table = self.tables.get(self.get_current_category())
        if table is None:
            return
        model = table.model()
        cost, market, profit, percent = model.totals()
        money = euro
        pct = "–" if percent is None else f"{percent:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") + " %"
        color = "#16803c" if profit > 0 else "#dc2626" if profit < 0 else "#6b7280"
        self.totals.setText(
            "<b>Gesamt Kaufwert: "
            + money(cost)
            + " &nbsp; | &nbsp; Gesamt Marktwert: "
            + money(market)
            + ' &nbsp; | &nbsp; <span style="color:'
            + color
            + '">Gesamt Gewinn: '
            + money(profit)
            + " ("
            + pct
            + ")</span></b>"
        )

    def set_compact(self, enabled):
        self.settings["compact_v09"] = enabled
        for key in ("cost", "pnl", "return"):
            self.dashboard.cards[key].parentWidget().setVisible(not enabled)
        self.scope_note.setVisible(not enabled)
        for action in self.scope_toolbar.actions():
            if self.scope_toolbar.widgetForAction(action) is self.scope_note:
                action.setVisible(not enabled)
        self.apply_table_fonts()

    def show_workspace(self, name):
        if getattr(self, "_v09_ready", False) and not self._navigating and self.settings.get("active_workspace") != name:
            current = self.tables.get(self.get_current_category())
            self._navigation.append(
                (
                    self.settings.get("active_workspace", "dashboard"),
                    self.combo_account.currentIndex(),
                    self.combo_snapshot.currentIndex(),
                    self.date_selector.date(),
                    self.position_search.text(),
                    self.combo_region.currentIndex(),
                    self.combo_cap.currentIndex(),
                    self.tabs.currentIndex(),
                    current.currentIndex().row() if current else -1,
                    current.verticalScrollBar().value() if current else 0,
                )
            )
            self._navigation = self._navigation[-30:]
        super().show_workspace(name)
        self.statusBar().showMessage("Konto und Bewertungsstichtag oben wählen. Layout über „Ansicht / Fenster → Layout bearbeiten“ anpassen.", 6000)
        self.setWindowTitle("PortMan 09 · " + self.portfolio_label + " · " + self.pages.get(name, (name,))[0])
        if hasattr(self, "period_start") and name in ("dashboard", "analysis", "performance"):
            self.sync_chart_period()

    def go_back(self):
        if not self._navigation:
            return
        page, account, snapshot, day, query, region, cap, tab, row, scroll = self._navigation.pop()
        self._navigating = True
        try:
            self.combo_account.setCurrentIndex(account)
            self.date_selector.setDate(day)
            self.combo_snapshot.setCurrentIndex(snapshot)
            self.combo_region.setCurrentIndex(region)
            self.combo_cap.setCurrentIndex(cap)
            self.position_search.setText(query)
            self.tabs.setCurrentIndex(tab)
            self.show_workspace(page)
            table = self.tables[self.get_current_category()]
            if row >= 0:
                table.selectRow(row)
            table.verticalScrollBar().setValue(scroll)
        finally:
            self._navigating = False

    def open_analysis(self):
        if hasattr(self, "period_start"):
            AnalysisDialog(
                self.repository, self.dashboard_scope()[0], self, self.period_start.date().toString("yyyy-MM-dd"), self.period_end.date().toString("yyyy-MM-dd")
            ).exec()
            return
        start = self.performance_widget.start.date().toString("yyyy-MM-dd")
        end = self.performance_widget.end.date().toString("yyyy-MM-dd")
        if self.settings.get("active_workspace") == "history":
            start = self.history_widget.start.date().toString("yyyy-MM-dd")
            end = self.history_widget.end.date().toString("yyyy-MM-dd")
        elif self.settings.get("active_workspace") != "performance" and self.selected_date() != "9999-12-31":
            end = self.selected_date()
            start = (date.fromisoformat(end) - timedelta(days=365)).isoformat()
        AnalysisDialog(self.repository, self.dashboard_scope()[0], self, start, end).exec()

    def open_evidence(self):
        EvidenceDialog(self.repository, None, self.dashboard_scope(), self).exec()

    def open_actions(self):
        ActionsDialog(self.repository, self).exec()
        self.reload_portfolio()

    def open_quality_issue(self, row, column):
        table = self.quality_widget.table
        if table.item(row, 1).text() != "Bewertung":
            return handle_quality_issue(self, row, column)
        candidates = [p for p in self.repository.holdings(self.dashboard_scope()[1], self.dashboard_scope()[0]) if p["key"] == table.item(row, 2).text()]
        if candidates and CostDialog(self.repository, candidates, self).exec():
            self.reload_portfolio()

    def open_tasks(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Aufgaben · Doppelklick zum Bearbeiten")
        dialog.resize(1000, 650)
        layout = QVBoxLayout(dialog)
        table = QTableWidget()
        layout.addWidget(table)
        tasks = []
        callbacks = []
        account, day = self.dashboard_scope()

        def open_account(name):
            dialog.accept()
            index = self.combo_account.findData(name)
            if index >= 0:
                self.combo_account.setCurrentIndex(index)
            self.show_workspace("accounts")

        for p in self.repository.holdings(day, account):
            if p.get("cost") is None or DecimalSafe(p["cost"]) <= 0:
                tasks.append(["Einstand ergänzen", p["name"], p["depot"], p.get("as_of") or p["period"]])
                callbacks.append(lambda p=p: CostDialog(self.repository, [p], dialog).exec())
        for r in self.repository.account_overview(day):
            if account and r["name"] != account:
                continue
            wealth = self.repository.wealth_summary(day, r["name"])
            dates = wealth.get("dates", [])
            stamp = max(dates) if dates else None
            stale = stamp and stamp < ((date.today() if day == "9999-12-31" else date.fromisoformat(day)) - timedelta(days=45)).isoformat()
            if r.get("balance") is None or stale:
                tasks.append(["Saldo fehlt" if r.get("balance") is None else "Saldo älter als 45 Tage", r["name"], "", stamp])
                callbacks.append(lambda name=r["name"]: open_account(name))
        self.quality_widget.refresh()
        quality = self.quality_widget.table

        def open_import(key):
            dialog.accept()
            for row in range(quality.rowCount()):
                if quality.item(row, 1).text() == "Import" and quality.item(row, 2).text() == key:
                    self.open_quality_issue(row, 0)
                    return

        for row in range(quality.rowCount()):
            if quality.item(row, 1).text() == "Import":
                key = quality.item(row, 2).text()
                tasks.append(["Importhinweis prüfen", quality.item(row, 3).text(), quality.item(row, 4).text(), ""])
                callbacks.append(lambda key=key: open_import(key))
        for path in (self.data_folder / "sessions").glob("*/session.json"):
            if not (path.parent / "completed.json").exists():
                tasks.append(["Importsitzung fortsetzen", path.parent.name, "", ""])
                callbacks.append(lambda p=path: self.resume_import(str(p)))
        populate(table, ["Aufgabe", "Betroffen", "Depot", "Stand"], tasks)
        table.cellDoubleClicked.connect(lambda row, col: callbacks[row]())
        dialog.exec()
        self.reload_portfolio()

    def preview_parsed_import(self, batches, history_sheets=False):
        if not history_sheets and batches and all(b.document_type == "comdirect Finanzreport" for b in batches):
            return self.finish_comdirect_pdf_import(batches)
        from portman.import_options import choose_import_options

        batches = choose_import_options(self, self.repository, batches)
        if not batches:
            return
        self.progress_bar.setVisible(False)
        try:
            if history_sheets:
                if history_sheets == "savings":
                    from portman.history_overview_dialog import HistoryOverviewDialog

                    selector = HistoryOverviewDialog(self.repository, batches, self, savings=True)
                else:
                    from portman.history_sheet_dialog import HistorySheetDialog

                    selector = HistorySheetDialog(self.repository, batches, self)
                if selector.exec() != 1:
                    return
                batches = selector.selected
                self.refresh_scope_choices()
            session = run_job(self, self.repository.store.path, "Konsistente Importkopie anlegen", lambda job: ImportSession(job.path, batches))
            self.run_session(session)
        except Exception as error:
            QMessageBox.warning(self, "Import nicht übernommen", str(error))

    def import_result(self, results):
        show_import_results(self, results)

    def run_session(self, session):
        session.save()
        summaries = run_job(self, self.repository.store.path, "Dateien vorbereiten", session.summaries)
        wizard = ImportWizard(self.repository, session, summaries, self)
        if wizard.exec() != 1:
            if not getattr(wizard, "session_saved", False):
                atomic_json(session.folder / "discarded.json", {"at": datetime.now().isoformat()})
            return
        batches = wizard.selected_batches()
        decisions = wizard.read_decisions()
        results = run_job(self, self.repository.store.path, "Import atomar speichern", lambda job: session.commit(job, batches, decisions))
        self.refresh_scope_choices()
        self.reload_portfolio()
        summary = session.summary(batches, decisions, results)
        QMessageBox.information(
            self,
            "Importabschluss",
            f"Dateien importiert: {summary['imported']}\nUnveränderte Dateien: {summary['unchanged']}\nBuchungen ausgewählt: {summary['selected_bookings']}\nÜbersprungen: {summary['skipped_bookings']}\nErsetzt: {summary['replaced_bookings']}\nFehler: {summary['errors']}",
        )
        self.import_result(results)

    def resume_import(self, path=None):
        if not isinstance(path, str):
            path, _ = QFileDialog.getOpenFileName(self, "Importsitzung fortsetzen", str(self.data_folder / "sessions"), "Sitzung (session.json)")
        if not path:
            return
        try:
            self.run_session(ImportSession.resume(self.repository.store.path, path))
        except Exception as error:
            QMessageBox.warning(self, "Importsitzung", str(error))

    def profile_import(self):
        path, _ = QFileDialog.getOpenFileName(self, "CSV mit Profil importieren", self.import_start_folder(), "CSV (*.csv *.tsv *.txt)")
        if path:
            self.remember_import_folder(path)
            try:
                dialog = CsvProfileDialog(self.repository, path, self)
                if dialog.exec() == 1:
                    self.preview_parsed_import([dialog.batch])
            except Exception as error:
                QMessageBox.warning(self, "CSV", str(error))

    def comdirect_tax_detail_import(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "comdirect-Steuerdetails importieren", self.import_start_folder(), "CSV (*.csv)")
        if not path:
            return
        self.remember_import_folder(path)
        try:
            from portfolio_v5.comdirect_tax_detail import parse_comdirect_tax_detail
            self.preview_parsed_import([parse_comdirect_tax_detail(path)])
        except Exception as error:
            QMessageBox.warning(self, "comdirect-Steuerdetails", str(error))

    def open_tax_detail_view(self):
        from portman.tax_detail_view import TaxDetailDialog
        TaxDetailDialog(self.repository, self).exec()

    def open_tax_annual_summary(self):
        from portman.tax_annual_summary import TaxAnnualSummaryDialog
        TaxAnnualSummaryDialog(self.repository, self).exec()

    def excel_import(self):
        from portman.excel_import_dialog import ExcelImportDialog

        path, _ = QFileDialog.getOpenFileName(self, "Excel importieren", self.import_start_folder(project_root() / "history"), "Excel (*.xlsx *.xls)")
        if not path:
            return
        self.remember_import_folder(path)
        try:
            dialog = ExcelImportDialog(self.repository, path, self)
            if dialog.exec() == 1:
                self.preview_parsed_import(dialog.batches)
        except Exception as error:
            QMessageBox.warning(self, "Excel", str(error))

    def manual_booking(self):
        from portman.manual_booking_dialog import ManualBookingDialog

        if ManualBookingDialog(self.repository, self.combo_account.currentData(), self).exec():
            self.refresh_scope_choices()
            self.reload_portfolio()

    def open_pdf_plugins(self):
        from portman.pdf_plugin_dialog import PdfPluginDialog

        PdfPluginDialog(self).exec()

    def adjust_cost_split(self):
        from portman.cost_split_dialog import CostSplitDialog

        if CostSplitDialog(self.repository, self).exec():
            self.refresh_scope_choices()
            self.reload_portfolio()

    def open_recovery(self):
        self.track_workers()
        if any(r["end"] is None for r in self.job_center.records):
            QMessageBox.information(self, "Auftrag läuft", "Laufende Aufträge vor Wiederherstellung beenden.")
            return
        dialog = RecoveryDialog(self.repository, self)
        dialog.exec()
        if dialog.restored:
            self.repository.store._read_revision = None
            self.repository._v8_cache_revision = None
            self.settings.update(self.storage.load_settings())
            self.restore_dock_state()
            self.preferences = TablePreferences(self)
            self.apply_table_fonts()
            self.compact_action.setChecked(self.settings.get("compact_v09", False))
            self.set_compact(self.compact_action.isChecked())
            from portman.theme import apply_theme

            apply_theme(self.settings.get("gui_style", self.settings.get("dark_theme", False)), self.settings.get("table_fonts_v10"))
            self.apply_table_fonts()
            self.refresh_scope_choices()
            self.reload_portfolio()

    def open_change_log(self):
        show_change_log(self)

    def closeEvent(self, event):
        if hasattr(self, "status_timer"):
            self.status_timer.stop()
        super().closeEvent(event)
        if event.isAccepted() and hasattr(self, "instance_lock"):
            self.instance_lock.unlock()
        elif hasattr(self, "status_timer"):
            self.status_timer.start()
