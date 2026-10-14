"""Shared application shell (docks, menus, workspace, positions) for the GUI."""
from pathlib import Path

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QTableWidget, QMessageBox,
    QHeaderView, QStatusBar,
)
from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices

HAS_WEBENGINE = False
try:
    from PySide6.QtWebEngineWidgets import QWebEngineView  # noqa: F401 - import probes availability
    HAS_WEBENGINE = True
except ImportError:
    HAS_WEBENGINE = False


PROJECT_ROOT = Path(__file__).resolve().parents[3]
from portman.repository import PortfolioRepository
from portman.dashboard_widget import DashboardWidget
from portman.busy_indicator import install_busy_indicator
from portman.theme import apply_theme
from portman.chart_style import apply_chart_style
from portman.workspace import WorkspaceMixin
from portman.visualizations import VisualizationsWidget
from portman.classification_dialog import ClassificationDialog
from portman.holding import Holding
from portman.portfolio_storage import PortfolioStorage
from portman.window_layout import WindowLayoutMixin
from portman.gui.date_scope import DateScopeMixin
from portman.gui.portfolio_views import PortfolioViewsMixin
from portman.gui.analysis import AnalysisMixin
from portman.gui.import_flow import ImportFlowMixin
from portman.gui.isin_enrichment import IsinEnrichmentMixin
from portman.gui.online_sync import OnlineSyncMixin
from portman.gui.portfolio_report import PortfolioReportMixin
from portman.gui.shell_docks import ShellDocksMixin
from portman.gui.shell_menus import ShellMenusMixin


POSITION_HEADERS = [
    "ISIN", "Name", "Typ", "Region", "Cap",
    "Anzahl", "Kaufwert (€)", "Marktwert (€)", "Gewinn/Verlust (€)", "Div.Rend(%)", "Dividende(€/J)", "Anteil (%)"
]


class MainWindow(DateScopeMixin, PortfolioViewsMixin, AnalysisMixin, ImportFlowMixin,
                 IsinEnrichmentMixin, OnlineSyncMixin, PortfolioReportMixin,
                 ShellDocksMixin, ShellMenusMixin, WorkspaceMixin, WindowLayoutMixin,
                 QMainWindow):
    def create_storage(self):
        return PortfolioStorage()

    def create_repository(self):
        return PortfolioRepository(PROJECT_ROOT / "data" / "portfolio_v05.sqlite")

    def banking_directory(self):
        return PROJECT_ROOT / 'data' / 'banking'

    def create_dashboard(self):
        return DashboardWidget(self.repository, self.dashboard_scope, self)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("PortMan V06 – Portfolio, Historie & Performance")
        install_busy_indicator()
        self.setDockOptions(
            QMainWindow.DockOption.AnimatedDocks
            | QMainWindow.DockOption.AllowNestedDocks
            | QMainWindow.DockOption.AllowTabbedDocks
            | QMainWindow.DockOption.GroupedDragging
        )
        self.setDockNestingEnabled(True)
        self.setCorner(Qt.Corner.TopLeftCorner, Qt.DockWidgetArea.LeftDockWidgetArea)
        self.setCorner(Qt.Corner.BottomLeftCorner, Qt.DockWidgetArea.LeftDockWidgetArea)
        self.setCorner(Qt.Corner.TopRightCorner, Qt.DockWidgetArea.RightDockWidgetArea)
        self.setCorner(Qt.Corner.BottomRightCorner, Qt.DockWidgetArea.RightDockWidgetArea)

        self.storage = self.create_storage()
        self.repository = self.create_repository()
        if not getattr(self, 'portfolio_folder', None):
            self.repository.migrate_legacy_metadata(Path(__file__).resolve().parents[3] / 'Gui' / 'portfolio_db.json')
        self.holdings: dict[str, Holding] = {}
        self.settings: dict = self.storage.load_settings()
        apply_chart_style(self.settings.get('chart_v10'))
        apply_theme(self.settings.get('gui_style', self.settings.get('dark_theme', False)),
                    self.settings.get('table_fonts_v10'))
        self.etf_cache: dict = self.storage.load_etf_cache()
        self.reload_portfolio(refresh=False)

        width = self.settings.get("window_width", 1400)
        height = self.settings.get("window_height", 900)
        self.resize(max(width, 1000), max(height, 750))
        self.setMinimumSize(900, 650)

        self.init_widgets()
        self.dashboard = self.create_dashboard()
        central = QWidget()
        central.setMinimumSize(1, 1)
        central.setMaximumSize(0, 0)
        self.setCentralWidget(central)
        self.init_docks()
        self.create_menus_and_toolbar()
        self.setup_navigation()
        self.setup_scope_refresh()

        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        # Add progress bar to status bar as permanent widget
        if hasattr(self, 'progress_bar'):
            try:
                self.status_bar.removeWidget(self.progress_bar)
            except Exception:
                pass
            self.status_bar.addPermanentWidget(self.progress_bar)
        self.status_bar.showMessage("Bereit. Portfolio geladen.")

        try:
            self.resize(1200, 800)
            self.setMinimumSize(900, 650)
        except Exception:
            pass

        self.restore_column_widths()
        self.restore_dock_state()
        self.connect_layout_autosave()
        self.refresh_all_views()

    def lock_editable_checked(self):
        return bool(self.settings.get("dock_layout_locked", False))

    def on_lock_docks_toggled(self, locked):
        self.set_docks_locked(locked)

    def create_position_table(self, category):
        table = QTableWidget()
        table.setColumnCount(len(POSITION_HEADERS))
        table.setHorizontalHeaderLabels(POSITION_HEADERS)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSortingEnabled(True)
        return table

    def connect_position_details(self, table):
        table.cellDoubleClicked.connect(self.on_cell_double_clicked)

    def on_cell_double_clicked(self, row: int, column: int):
        if column in (1, 2, 3, 4):
            current_table = self.sender()
            item = current_table.item(row, 0) if current_table else None
            if item is None:
                return
            key = item.data(Qt.ItemDataRole.UserRole) or item.text().strip()
            try:
                dialog = ClassificationDialog(self.repository, key, self)
            except ValueError as exc:
                QMessageBox.warning(self, 'Wertpapier einordnen', str(exc))
                return
            if dialog.exec():
                self.reload_portfolio()
                self.status_bar.showMessage('Anlageklasse, Region und Cap dauerhaft gespeichert.', 5000)
            return
        if column == 0:
            current_table = self.sender()
            isin_item = current_table.item(row, 0)
            if isin_item:
                isin = isin_item.text().strip()
                if isin:
                    self.current_isin_loaded = isin
                    self.label_browser_isin.setText(f"<b>ISIN: {isin}</b>")
                    self.dock_browser.show()
                    self.dock_browser.raise_()
                    self.load_finanzen()

    def load_finanzen(self):
        if not self.current_isin_loaded: return
        url = f"https://www.finanzen.net/suchergebnis.asp?frmAktiensucheTextfeld={self.current_isin_loaded}"
        if HAS_WEBENGINE: self.web_view.setUrl(QUrl(url))
        else: QDesktopServices.openUrl(QUrl(url))

    def load_yahoo(self):
        if not self.current_isin_loaded: return
        url = f"https://finance.yahoo.com/quote/{self.current_isin_loaded}"
        if HAS_WEBENGINE: self.web_view.setUrl(QUrl(url))
        else: QDesktopServices.openUrl(QUrl(url))

    def update_progress(self, current, total):
        self.progress_bar.setValue(int((current / total) * 100))

    def save_portfolio(self):
        try:
            self.repository.save_metadata(self.holdings.values())
            self.save_settings()
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, "Speichern fehlgeschlagen", f"Einstellungen konnten nicht gespeichert werden: {error}\nBitte mit Strg+S erneut versuchen.")
            return
        self.status_bar.showMessage("Metadaten und Einstellungen gespeichert. Buchungen werden automatisch gespeichert.", 6000)

    def closeEvent(self, event):
        from portman.chart_worker import ChartWorker
        for widget in self.findChildren(VisualizationsWidget):
            widget.refresh_timer.stop()
            widget.chart_loader.cancel()
        charts = [job for job in QApplication.instance().findChildren(ChartWorker) if job.isRunning()]
        if charts:
            for job in charts: job.requestInterruption()
            self.statusBar().showMessage('Diagrammberechnung wird beendet. Bitte danach das Fenster schließen.', 3000)
            event.ignore()
            return
        for name in ('import_worker', 'fetcher', 'etf_fetcher'):
            worker = getattr(self, name, None)
            if worker and worker.isRunning():
                worker.requestInterruption()
                self.statusBar().showMessage('Hintergrundauftrag wird beendet. Bitte danach das Fenster schließen.', 5000)
                event.ignore()
                return
        if self.market_widget.worker and self.market_widget.worker.isRunning():
            self.market_widget.cancel()
            self.statusBar().showMessage('Marktdatenabruf wird beendet. Bitte danach das Fenster schließen.', 5000)
            event.ignore()
            return
        self.save_settings()
        self.repository.save_metadata(self.holdings.values())
        self.repository.close()
        event.accept()
