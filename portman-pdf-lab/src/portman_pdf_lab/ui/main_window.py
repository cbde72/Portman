"""Lean, independent PySide6 desktop interface for PDF analysis and review."""

from collections.abc import Callable, Mapping
import json
import logging
import os.path
from pathlib import Path
import sys

from PySide6.QtCore import (
    QObject, QRunnable, Qt, QThreadPool, QSignalBlocker, Signal, Slot,
    QStandardPaths, QSettings,
)
from PySide6.QtGui import QAction, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QListWidget, QInputDialog,
    QMainWindow, QMessageBox, QProgressBar, QPushButton, QSplitter, QTabWidget,
    QTextEdit, QToolBar, QVBoxLayout, QWidget, QSizePolicy,
)

from portman_parsers.extraction import extract_pdf
from portman_parsers.registry import default_registry
from pypdf import PdfReader
from portman_pdf_lab.application.pdf_analysis import analyse_pdf, export_batch_csv
from portman_pdf_lab.application.batch_excel import export_batch_excel
from portman_pdf_lab.application.reference_service import analyse_and_store
from portman_pdf_lab.reviews.models import ReviewStatus
from portman_pdf_lab.storage import ReferenceRepository
from portman_pdf_lab.ui.training_widget import TrainingWidget
from portman_pdf_lab.ui.field_analysis import FieldAnalysisWidget, FieldHelpDialog
from portman_pdf_lab.ui.result_view import StructuredResultView
from portman_pdf_lab.ui.standard_values import StandardValuesDialog, build_standard_value_rows
from portman_pdf_lab.ui.pdf_text_layer import PdfTextLayer
from portman_pdf_lab.ui.field_mapping import CatalogHelpDialog, EditorFactory, FieldMappingDialog
from portman_pdf_lab.field_catalog import CatalogStore
from portman_pdf_lab.training import TrainingService
from portman_pdf_lab.ui.pdf_markings import (
    PdfMarking, collect_marking_specs, resolve_marking_specs,
    text_layer_markers,
)

try:
    from PySide6.QtPdf import QPdfDocument
except ImportError:  # pragma: no cover - platform packaging fallback
    QPdfDocument = None

from portman_pdf_lab.ui.direct_pdf_view import DirectPdfView
from portman_pdf_lab.ui.quick_training import QuickTrainingPanel


LOGGER = logging.getLogger(__name__)


def _positive_int(value) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError, OverflowError):
        return 0
    return number if number > 0 else 0


class WorkerSignals(QObject):
    result = Signal(str, object)   # (path, report)
    error = Signal(str, str)       # (path, message)
    finished = Signal(str)         # path


class AnalysisWorker(QRunnable):
    """One PDF analysis task.

    ``persist=False`` (batch / "Run On Folder") uses the pure, non-writing
    :func:`analyse_pdf` path and never touches SQLite, reference values, parser
    history, training data or field-catalog files.  ``persist=True`` keeps the
    original single-document behaviour via :func:`analyse_and_store`.

    ``autoDelete`` is disabled so the Qt thread pool never deletes the C++
    runnable while Python still holds it; lifetime is managed through
    ``MainWindow.workers``.
    """

    def __init__(self, path: Path, repository_path: Path, rule_mode="STANDARD",
                 plugin_id=None, persist: bool = True,
                 cancelled: Callable[[], bool] | None = None,
                 batch: bool = False):
        super().__init__()
        self.setAutoDelete(False)
        self.path = Path(path)
        self.repository_path = repository_path
        self.rule_mode = rule_mode
        self.plugin_id = plugin_id
        self.persist = persist
        self.cancelled = cancelled
        self.batch = batch
        self.signals = WorkerSignals()

    @Slot()
    def run(self):
        path_str = str(self.path)
        try:
            if self.cancelled is not None and self.cancelled():
                return
            if self.persist:
                report = analyse_and_store(self.path, ReferenceRepository(self.repository_path),
                                           self.rule_mode, plugin_id=self.plugin_id)[0]
            else:
                # Batch mode is strictly read-only: STANDARD, no profile store,
                # no repository, therefore no SQLite/catalog writes.
                report = analyse_pdf(self.path, "STANDARD", plugin_id=self.plugin_id)
            self.signals.result.emit(path_str, report)
        except Exception as exc:  # defensive GUI boundary; never crash a slot
            self.signals.error.emit(path_str, f"{type(exc).__name__}: {exc}")
        finally:
            self.signals.finished.emit(path_str)


class MainWindow(QMainWindow):
    TAB_NAMES = ("Übersicht", "Konto", "Depot", "Buchungen", "Geldflüsse",
                 "Gebühren & Kosten", "Steuern", "Referenzvergleich", "Issues",
                 "Feldanalyse", "Parsertraining")

    def __init__(self, repository_path: str | Path | None = None, settings: QSettings | None = None):
        super().__init__()
        self.setWindowTitle("Portman PDF Lab")
        self.resize(1500, 900)
        self.thread_pool = QThreadPool.globalInstance()
        self.workers: set[AnalysisWorker] = set()
        # Single source of truth: every path maps to exactly one report dict.
        # No other type is ever stored here; see ``_normalise_report`` / ``_report_for``.
        self.documents: dict[str, dict] = {}
        self.current_pdf: Path | None = None
        data_dir = Path(QStandardPaths.writableLocation(QStandardPaths.AppLocalDataLocation))
        self.repository_path = Path(repository_path) if repository_path else data_dir / "reference.sqlite"
        self.catalog_store = CatalogStore(data_dir / "field-catalogs")
        # The supplied YAML is a curated description source, not a runtime
        # parser profile.  Import it once into the central description store;
        # verified user/catalog definitions remain authoritative.
        factual_catalog = Path(__file__).resolve().parents[4] / "data" / "Portman_PDF_Lab_Feldkatalog_v1.0.0.yaml"
        if factual_catalog.exists():
            self.catalog_store.import_factual_catalog(
                factual_catalog,
                factual_catalog.with_suffix(factual_catalog.suffix + ".audit.json"),
            )
        self.current_run_id: int | None = None
        self.cancel_requested = False
        self._batch_active = False
        self._batch_cancel_requested = False
        self._batch_total = 0
        self._batch_completed = 0
        self._batch_order: list[str] = []
        self._batch_reports: dict[str, dict] = {}
        self._batch_csv_path: Path | None = None
        self._batch_training_database: Path | None = None
        self._batch_folder: Path | None = None
        self._selecting_document = False
        self.settings = settings or QSettings("Portman", "PDFLab")
        self.page_texts: dict[int, str] = {}
        self._pdf_text_cache: dict[int, str] = {}
        self._marking_specs = []
        self._current_markings: list[PdfMarking] = []
        self._layer_markings: list[PdfMarking] = []
        self._selected_field_path = ""
        self._navigating = False
        self._pending_pdf_selection = None
        self._standard_values_dialog = None
        self._text_variants: dict[int, dict[str, str]] = {}
        self._build_ui()
        self._restore_layout()

    def _build_ui(self):
        toolbar = QToolBar("Dokumente", self); self.addToolBar(toolbar)
        open_action = QAction("PDF öffnen", self); open_action.triggered.connect(self.open_pdf_dialog)
        toolbar.addAction(open_action)
        batch_action = QAction("Ordner analysieren", self); batch_action.triggered.connect(self.open_directory_dialog)
        toolbar.addAction(batch_action)
        cancel_action = QAction("Abbrechen", self); cancel_action.triggered.connect(self.cancel_batch); toolbar.addAction(cancel_action)
        toolbar.addSeparator(); toolbar.addWidget(QLabel("Modus:"))
        self.ui_mode = QComboBox(); self.ui_mode.addItems(("Schnell", "Experte")); toolbar.addWidget(self.ui_mode)
        toolbar.addWidget(QLabel("Plugin:"))
        self.parser_choice = QComboBox()
        self.parser_choice.addItem("Automatisch erkennen", None)
        for item in default_registry().metadata():
            readiness = tuple(sorted({handler.readiness for handler in item.handlers}))
            if any(status in {"IMPLEMENTED", "PARTIAL"} for status in readiness):
                index = self.parser_choice.count()
                self.parser_choice.addItem(f"{item.group} – {item.plugin_id}", item.plugin_id)
                self.parser_choice.setItemData(index, ", ".join(readiness), Qt.ToolTipRole)
        toolbar.addWidget(self.parser_choice)
        reparse_action = QAction("Neu parsen", self)
        reparse_action.triggered.connect(self.reparse_current)
        toolbar.addAction(reparse_action)
        quick_values_action = QAction("Erkannte Werte", self)
        quick_values_action.triggered.connect(self.show_quick_values)
        toolbar.addAction(quick_values_action)
        approve_action = QAction("Freigeben", self); approve_action.triggered.connect(lambda: self.review_current(ReviewStatus.APPROVED)); toolbar.addAction(approve_action)
        reject_action = QAction("Korrektur nötig", self); reject_action.triggered.connect(lambda: self.review_current(ReviewStatus.NEEDS_CORRECTION)); toolbar.addAction(reject_action)
        help_action = QAction("Feldhilfe", self); help_action.triggered.connect(self.show_field_help); toolbar.addAction(help_action)
        self.help_shortcut = QShortcut(QKeySequence.HelpContents, self); self.help_shortcut.activated.connect(self.show_field_help)
        self.progress = QProgressBar(); self.progress.setVisible(False); toolbar.addWidget(self.progress)

        root = self.root_splitter = QSplitter(Qt.Horizontal); root.setObjectName("main-splitter")
        left = QWidget(); left_layout = QVBoxLayout(left)
        self.search = QLineEdit(); self.search.setPlaceholderText("Dokumente filtern …")
        self.search.textChanged.connect(self._filter_documents)
        self.document_list = QListWidget(); self.document_list.currentTextChanged.connect(self._select_document)
        left_layout.addWidget(self.search); left_layout.addWidget(self.document_list)

        middle = QWidget(); middle_layout = QVBoxLayout(middle)
        nav = QHBoxLayout(); self.previous = QPushButton("◀"); self.next = QPushButton("▶")
        self.page_label = QLabel("Keine PDF"); self.text_quality = QLabel("Textqualität: —")
        self.zoom_out = QPushButton("−"); self.zoom_in = QPushButton("+")
        self.markings_enabled = QCheckBox("Erkannte Werte markieren"); self.markings_enabled.setChecked(True)
        self.marking_scope = QComboBox()
        self.marking_scope.addItems(("Alle erkannten Felder", "Nur ausgewähltes Feld", "Markierungen ausblenden"))
        self.markings_enabled.setToolTip("Automatische, evidencebasierte PDF-Markierungen ein- oder ausblenden")
        nav.addWidget(self.previous); nav.addWidget(self.next); nav.addWidget(self.page_label)
        nav.addWidget(self.text_quality); nav.addStretch()
        nav.addWidget(self.markings_enabled); nav.addWidget(self.marking_scope)
        nav.addWidget(self.zoom_out); nav.addWidget(self.zoom_in); middle_layout.addLayout(nav)
        if QPdfDocument:
            self.current_page_index = 0
            self.pdf_document = QPdfDocument(self); self.pdf_view = DirectPdfView(); self.pdf_view.setDocument(self.pdf_document)
            self.pdf_document.statusChanged.connect(self._pdf_status_changed)
            self.pdf_view.actionRequested.connect(self._pdf_text_action)
            self.pdf_view.markingActivated.connect(self._markings_activated)
            self.pdf_view.selectionChanged.connect(self._pdf_selection_changed)
            self.previous.clicked.connect(lambda: self.go_to_page(self.current_page_index - 1))
            self.next.clicked.connect(lambda: self.go_to_page(self.current_page_index + 1))
            self.zoom_in.clicked.connect(lambda: self.pdf_view.setZoomFactor(self.pdf_view.zoomFactor() * 1.2))
            self.zoom_out.clicked.connect(lambda: self.pdf_view.setZoomFactor(self.pdf_view.zoomFactor() / 1.2))
        else:
            self.pdf_document = None; self.pdf_view = QTextEdit(); self.pdf_view.setReadOnly(True)
        self.pdf_view.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.evidence_excerpt = QTextEdit(); self.evidence_excerpt.setReadOnly(True)
        self.evidence_excerpt.setPlaceholderText("Textfundstelle")
        self.pdf_text_layer = PdfTextLayer(); self.pdf_text_layer.actionRequested.connect(self._pdf_text_action)
        self.pdf_text_layer.markingActivated.connect(self._markings_activated)
        text_panel = QWidget(); text_layout = QVBoxLayout(text_panel); text_layout.setContentsMargins(0, 0, 0, 0)
        text_toolbar = QHBoxLayout(); text_toolbar.addWidget(QLabel("Textansicht:"))
        self.text_view_mode = QComboBox(); self.text_view_mode.addItems(("Bereinigt", "Layout", "Original"))
        self.text_view_mode.setToolTip("Bereinigt, räumliches Layout oder unveränderter Extraktoroutput")
        text_toolbar.addWidget(self.text_view_mode); text_toolbar.addStretch()
        text_layout.addLayout(text_toolbar); text_layout.addWidget(self.pdf_text_layer)
        self.text_view_mode.currentTextChanged.connect(self._text_view_changed)
        self.pdf_splitter = QSplitter(Qt.Vertical); self.pdf_splitter.setObjectName("pdf-splitter")
        self.pdf_splitter.addWidget(self.pdf_view); self.pdf_splitter.addWidget(text_panel); self.pdf_splitter.addWidget(self.evidence_excerpt)
        self.pdf_splitter.setStretchFactor(0, 5); self.pdf_splitter.setStretchFactor(1, 2); self.pdf_splitter.setStretchFactor(2, 1)
        middle_layout.addWidget(self.pdf_splitter)

        self.tabs = QTabWidget(); self.tables = {}; self.result_views = {}
        for name in self.TAB_NAMES[:-2]:
            view = StructuredResultView(); table = view.table
            table.fieldActivated.connect(self._field_activated)
            self.tables[name] = table; self.result_views[name] = view; self.tabs.addTab(view, name)
        self.tables["Referenzvergleich"].cellDoubleClicked.connect(self._edit_reference)
        self.field_analysis = FieldAnalysisWidget(self.repository_path)
        self.field_analysis.trainingRequested.connect(self._start_field_training)
        self.field_analysis.fieldActivated.connect(self._field_analysis_activated)
        self.field_analysis.helpRequested.connect(self._show_field_analysis_help)
        self.field_analysis.standardValuesRequested.connect(self._show_standard_values)
        self.field_analysis.testRuleRequested.connect(self._quick_test_rule)
        self.field_analysis.approveRuleRequested.connect(self._quick_approve_rule)
        self.field_analysis.activateRuleRequested.connect(self._quick_activate_rule)
        self.tabs.addTab(self.field_analysis, "Feldanalyse")
        self.training_widget = TrainingWidget(self.repository_path)
        self.training_widget.fieldActivated.connect(self._training_field_activated)
        self.training_widget.mode.currentTextChanged.connect(self._mode_changed)
        self.training_widget.trainingChanged.connect(self._training_changed)
        self.training_widget.returnRequested.connect(self._return_to_field_analysis)
        self.tabs.addTab(self.training_widget, "Parsertraining")
        self.quick_training = QuickTrainingPanel(); self.quick_training.hide()
        self.quick_training.confirmRequested.connect(self._quick_confirm)
        self.quick_training.missingRequested.connect(self._quick_missing)
        self.quick_training.cancelRequested.connect(self._quick_cancel)
        self.quick_training.testRequested.connect(self._quick_test_rule)
        self.quick_training.approveRequested.connect(self._quick_approve_rule)
        self.quick_training.activateRequested.connect(self._quick_activate_rule)
        self.quick_training.recheckRequested.connect(self._quick_recheck)
        root.addWidget(left); root.addWidget(middle); root.addWidget(self.tabs); root.addWidget(self.quick_training)
        root.setSizes((250, 650, 480, 0))
        root.setChildrenCollapsible(False); root.setStretchFactor(1, 2); root.setStretchFactor(2, 2)
        left.setMinimumWidth(140); middle.setMinimumWidth(220); self.tabs.setMinimumWidth(260)
        self.markings_enabled.toggled.connect(self._marking_option_changed)
        self.marking_scope.currentTextChanged.connect(self._marking_option_changed)
        self.setCentralWidget(root); self.statusBar().showMessage("Bereit")
        self.quick_candidate_id = None; self.quick_version_id = None
        self.ui_mode.currentTextChanged.connect(self._apply_ui_mode)

    def _restore_layout(self):
        geometry = self.settings.value("window/geometry")
        if geometry:
            self.restoreGeometry(geometry)
            frame = self.frameGeometry()
            if not any(frame.intersects(screen.availableGeometry()) for screen in QApplication.screens()):
                self.resize(1500, 900); self.move(QApplication.primaryScreen().availableGeometry().topLeft())
        for key, splitter in (("main", self.root_splitter), ("pdf", self.pdf_splitter)):
            state = self.settings.value(f"splitters/{key}")
            if state: splitter.restoreState(state)
        self.training_widget.restore_settings(self.settings)
        self.field_analysis.restore_settings(self.settings)
        self.markings_enabled.setChecked(self.settings.value("pdf/markings-enabled", True, type=bool))
        scope = self.settings.value("pdf/markings-scope", "Alle erkannten Felder", type=str)
        if scope in {self.marking_scope.itemText(index) for index in range(self.marking_scope.count())}:
            self.marking_scope.setCurrentText(scope)
        for name, view in self.result_views.items():
            state = self.settings.value(f"headers/{name}")
            if state: view.table.horizontalHeader().restoreState(state)
        mode = self.settings.value("ui/mode", "Schnell", type=str)
        self.ui_mode.setCurrentText(mode if mode in {"Schnell", "Experte"} else "Schnell")
        text_mode = self.settings.value("pdf/text-view", "Bereinigt", type=str)
        self.text_view_mode.setCurrentText(text_mode if text_mode in {"Bereinigt", "Layout", "Original"} else "Bereinigt")
        self._apply_ui_mode(self.ui_mode.currentText())

    def _apply_ui_mode(self, mode):
        quick = mode != "Experte"; self.settings.setValue("ui/mode", "Schnell" if quick else "Experte")
        field_index = self.tabs.indexOf(self.field_analysis)
        for index in range(self.tabs.count()): self.tabs.setTabVisible(index, not quick or index == field_index)
        self.field_analysis.set_quick_mode(quick)
        self.quick_training.setVisible(quick and self.quick_training.active)
        if quick: self.tabs.setCurrentWidget(self.field_analysis)
        self.statusBar().showMessage("Schnellmodus" if quick else "Expertenmodus", 2000)

    def closeEvent(self, event):
        self.settings.setValue("window/geometry", self.saveGeometry())
        self.settings.setValue("window/maximized", self.isMaximized())
        self.settings.setValue("splitters/main", self.root_splitter.saveState())
        self.settings.setValue("splitters/pdf", self.pdf_splitter.saveState())
        self.training_widget.save_settings(self.settings)
        self.field_analysis.save_settings(self.settings)
        self.settings.setValue("pdf/markings-enabled", self.markings_enabled.isChecked())
        self.settings.setValue("pdf/markings-scope", self.marking_scope.currentText())
        self.settings.setValue("pdf/text-view", self.text_view_mode.currentText())
        for name, view in self.result_views.items():
            self.settings.setValue(f"headers/{name}", view.table.horizontalHeader().saveState())
        self.settings.sync(); super().closeEvent(event)

    @Slot()
    def open_pdf_dialog(self):
        start = self.settings.value("dialogs/last-directory", "", type=str)
        path, _ = QFileDialog.getOpenFileName(self, "PDF öffnen", start, "PDF (*.pdf)")
        if path:
            self.settings.setValue("dialogs/last-directory", str(Path(path).parent))
            self.analyse(Path(path))

    @Slot()
    def open_directory_dialog(self):
        start = self.settings.value("dialogs/last-directory", "", type=str)
        path = QFileDialog.getExistingDirectory(self, "PDF-Ordner wählen", start)
        if not path: return
        self.settings.setValue("dialogs/last-directory", str(Path(path)))
        files = sorted(Path(path).rglob("*.pdf"))
        if not files:
            QMessageBox.information(self, "Ordner analysieren", "Im gewählten Ordner wurden keine PDF-Dateien gefunden.")
            return
        export_training = QMessageBox.question(
            self, "Parser-Trainingsdaten",
            "Vorhandene Parser-Trainingsdaten lesend an die CSV anhängen?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        ) == QMessageBox.StandardButton.Yes
        # The CSV is always written, even when no training columns are requested.
        default_csv = Path(path) / "parser-batch.csv"
        csv_path, _ = QFileDialog.getSaveFileName(
            self, "Batch-CSV speichern", str(default_csv), "CSV (*.csv)"
        )
        if not csv_path:
            csv_path = str(default_csv)
            self.statusBar().showMessage("Kein CSV-Ziel gewählt – Standardpfad wird verwendet.", 5000)
        self.start_batch(files, Path(csv_path),
                         self.repository_path if export_training else None)

    def start_batch(self, files, csv_path: str | Path,
                    training_database: str | Path | None = None):
        """Start a read-only batch analysis with one CSV row per PDF.

        Batch workers use ``persist=False`` and never call
        :func:`analyse_and_store`; SQLite, reference values, training data and
        parser history are not written.  The CSV is exported when all workers
        have finished, including after a cancel request (partial result).
        """
        order: list[str] = []
        seen: set[str] = set()
        for item in files:
            key = str(Path(item))
            if key not in seen:
                seen.add(key); order.append(key)
        if self._batch_active:
            self.statusBar().showMessage("Eine Batchanalyse läuft bereits.", 5000)
            return
        self.cancel_requested = False
        self._batch_cancel_requested = False
        self._batch_active = True
        self._batch_total = len(order)
        self._batch_completed = 0
        self._batch_order = order
        self._batch_reports = {}
        self._batch_csv_path = Path(csv_path)
        self._batch_training_database = Path(training_database) if training_database else None
        self._batch_folder = self._batch_output_folder(order)
        self.progress.setRange(0, len(order)); self.progress.setValue(0)
        self.progress.setVisible(bool(order))
        if not order:
            self._finish_batch()
            return
        for key in order:
            self.analyse(Path(key), persist=False, batch=True)

    @Slot()
    def cancel_batch(self):
        if not self._batch_active:
            return
        self.cancel_requested = True
        self._batch_cancel_requested = True
        # Do not clear the thread pool: queued workers still emit ``finished``
        # and thereby let the batch export its partial CSV deterministically.
        self.statusBar().showMessage("Batchanalyse wird abgebrochen …", 5000)

    def analyse(self, path: Path, rule_mode=None, persist: bool = True, batch: bool = False):
        path = Path(path)
        self.statusBar().showMessage(f"Analysiere {path.name} …")
        worker = AnalysisWorker(
            path, self.repository_path,
            rule_mode or self.training_widget.mode.currentText(),
            self.parser_choice.currentData(), persist=persist,
            cancelled=(lambda: self._batch_cancel_requested) if batch else None,
            batch=batch,
        )
        self.workers.add(worker)
        worker.signals.result.connect(
            lambda result_path, result, w=worker: self._analysis_ready(result_path, result, w))
        worker.signals.error.connect(
            lambda error_path, message, w=worker: self._analysis_failed(error_path, message, w))
        worker.signals.finished.connect(
            lambda _finished_path, w=worker: self._worker_finished(w))
        self.thread_pool.start(worker)

    @staticmethod
    def _error_report(path: str, code: str, message: str) -> dict:
        return {"source": path, "error": code, "message": message,
                "issues": [{"code": code, "message": message}]}

    def _normalise_report(self, path: str, report) -> dict:
        """Enforce the ``dict[str, dict]`` contract for ``self.documents``."""
        if isinstance(report, Mapping):
            value = dict(report)
            value.setdefault("source", path)
            return value
        message = (f"Ungültiger Analysebericht für {path}: "
                   f"{type(report).__name__} statt Dictionary.")
        LOGGER.error(message)
        return self._error_report(path, "INVALID_REPORT", message)

    def _analysis_ready(self, path, report, worker=None):
        key = str(Path(path))
        value = self._normalise_report(key, report)
        self.documents[key] = value
        is_batch = bool(worker is not None and getattr(worker, "batch", False))
        if is_batch:
            self._batch_reports[key] = value
        # During a batch run the user's current selection must stay stable;
        # single-document analyses still reveal their result immediately.
        self._show_document_item(key, select=not is_batch)
        try:
            if self.current_pdf == Path(key):
                self.show_report(value); self.refresh_field_analysis(); self.refresh_pdf_markings()
            if (self.quick_training.active and self.quick_training.context is not None
                    and value.get("rule_mode_effective") == "EXTENDED"):
                context = self.quick_training.context; reference = EditorFactory.text(self.quick_training.editor)
                decision = next((item for item in value.get("rule_decisions", ())
                                 if item.get("field_path") == context.field_path), {})
                extended = decision.get("effective_value")
                status = "ERKANNT" if str(extended) == str(reference) and extended is not None else "PRÜFEN"
                self.quick_training.rechecked(context.current_value, extended, reference, status)
        except Exception as exc:  # a malformed report must not abort the GUI
            LOGGER.exception("Report konnte nicht angezeigt werden: %s", key)
            self.statusBar().showMessage(
                f"Report konnte nicht angezeigt werden: {Path(key).name} – {exc}", 8000)

    def _analysis_failed(self, path, message, worker=None):
        key = str(Path(path))
        text = str(message or "Unbekannter Analysefehler")
        LOGGER.error("Analyse fehlgeschlagen für %s: %s", key, text)
        value = self._error_report(key, "ANALYSIS_FAILED", text)
        self.documents[key] = value
        is_batch = bool(worker is not None and getattr(worker, "batch", False))
        if is_batch:
            self._batch_reports[key] = value
        self._show_document_item(key, select=not is_batch)
        self.statusBar().showMessage(f"Analysefehler: {Path(key).name} – {text}", 8000)

    def _show_document_item(self, key: str, select: bool = True):
        """Add a document once and keep its list entry tied to ``key``."""
        items = self.document_list.findItems(key, Qt.MatchExactly)
        if items:
            item = items[0]
        else:
            blocker = QSignalBlocker(self.document_list)
            try:
                self.document_list.addItem(key)
                item = self.document_list.item(self.document_list.count() - 1)
            finally:
                del blocker
        item.setData(Qt.UserRole, key)
        if not select:
            return
        row = self.document_list.row(item)
        if self.document_list.currentRow() != row:
            self.document_list.setCurrentRow(row)
        else:
            self._select_document(key)

    @staticmethod
    def _batch_output_folder(order: list[str]) -> Path | None:
        """Gemeinsamer Ausgabeordner des Batch-Laufs (Ordner der PDFs)."""
        if not order:
            return None
        try:
            return Path(os.path.commonpath([str(Path(key).resolve()) for key in order]))
        except ValueError:
            return Path(order[0]).resolve().parent

    def _worker_finished(self, worker=None):
        if worker is not None:
            self.workers.discard(worker)
        if worker is not None and getattr(worker, "batch", False):
            self._batch_completed += 1
            if self._batch_active:
                self.progress.setValue(min(self._batch_completed, self._batch_total))
                if self._batch_completed >= self._batch_total:
                    self._finish_batch()
                    return
            return
        self.statusBar().showMessage("Analyse abgeschlossen", 3000)

    def _finish_batch(self):
        if not self._batch_active:
            return
        self._batch_active = False
        self.progress.setVisible(False)
        target = self._batch_csv_path
        training_database = self._batch_training_database
        excel_folder = self._batch_folder
        self._batch_csv_path = None
        self._batch_training_database = None
        self._batch_folder = None
        reports = [self._batch_reports[key] for key in self._batch_order
                   if key in self._batch_reports]
        messages: list[str] = []
        if target is not None:
            batch = {"files": reports}
            try:
                export_batch_csv(batch, target, training_database)
                messages.append(f"CSV exportiert: {target} ({len(reports)} Dokumente)")
                if batch.get("warnings"):
                    messages.append("Hinweis: " + " | ".join(batch["warnings"]))
            except Exception as exc:  # a failed export must never terminate the GUI
                LOGGER.exception("CSV-Export fehlgeschlagen: %s", target)
                messages.append(f"CSV-Export fehlgeschlagen: {exc}")
        if excel_folder is not None and reports:
            try:
                excel = export_batch_excel(reports, excel_folder)
                if excel.get("path"):
                    messages.append(f"Excel exportiert: {excel['path']} "
                                    f"({len(excel['sheets'])} Tabellenblätter)")
                for error in excel.get("errors", ()):
                    messages.append(f"Excel: {error}")
                if not excel.get("path") and not excel.get("errors"):
                    messages.append("Excel-Export nicht verfügbar")
            except Exception as exc:  # auch der Excel-Export darf den Batch nie beenden
                LOGGER.exception("Excel-Export fehlgeschlagen: %s", excel_folder)
                messages.append(f"Excel-Export fehlgeschlagen: {exc}")
        self.statusBar().showMessage(" | ".join(messages) or "Batchanalyse abgeschlossen", 10000)

    def _filter_documents(self, text: str):
        needle = text.casefold()
        for index in range(self.document_list.count()):
            item = self.document_list.item(index); item.setHidden(needle not in item.text().casefold())

    def _report_for(self, key: str) -> dict:
        report = self.documents.get(key)
        if isinstance(report, dict):
            return report
        if key in self.documents:
            message = (f"Ungültiger Report in self.documents für {key}: "
                       f"{type(report).__name__} statt Dictionary.")
            LOGGER.error(message)
            # Self-heal the contract instead of leaving an unusable value.
            report = self._error_report(key, "INVALID_REPORT", message)
            self.documents[key] = report
            return report
        return {}

    def _select_document(self, key: str):
        if self._selecting_document or not key:
            return
        if key not in self.documents:
            return
        report = self._report_for(key)
        self._selecting_document = True
        try:
            self.current_pdf = Path(key)
            run_id = report.get("run_id")
            self.current_run_id = run_id if isinstance(run_id, int) else None
            self._selected_field_path = ""
            self._pending_pdf_selection = None
            try:
                self.load_pdf(self.current_pdf)
            except Exception as exc:  # broken/removed PDF must not break selection
                LOGGER.exception("PDF konnte nicht geladen werden: %s", key)
                self.page_label.setText("PDF nicht lesbar")
                self.statusBar().showMessage(
                    f"PDF konnte nicht geladen werden: {Path(key).name} – {exc}", 8000)
            self.show_report(report)
            catalog = self._catalog()
            self.training_widget.bind_report(report, self.current_pdf, catalog)
            self.field_analysis.bind_report(report, catalog)
            if self.current_run_id:
                try:
                    self._load_annotation_highlights(
                        ReferenceRepository(self.repository_path).run(self.current_run_id)["document_id"])
                except Exception as exc:  # missing run/repository is a data issue, not a crash
                    LOGGER.warning("Annotationen konnten nicht geladen werden (%s): %s",
                                   self.current_run_id, exc)
                    self.refresh_pdf_markings()
            else:
                self.refresh_pdf_markings()
        except Exception as exc:  # a broken report must never abort the Qt slot
            LOGGER.exception("Dokument konnte nicht ausgewählt werden: %s", key)
            self.statusBar().showMessage(
                f"Dokument konnte nicht angezeigt werden: {Path(key).name} – {exc}", 8000)
        finally:
            self._selecting_document = False

    def review_current(self, status: ReviewStatus):
        if self.current_run_id is None:
            self.statusBar().showMessage("Kein gespeicherter Parserlauf ausgewählt", 3000); return
        ReferenceRepository(self.repository_path).review(self.current_run_id, "overall", status,
                                                         "GUI user", "Manual GUI decision")
        self.statusBar().showMessage(f"Reviewstatus: {status.value}", 3000)

    def load_pdf(self, path: Path):
        document = extract_pdf(path)
        self._text_variants = {}
        try:
            preparation = json.loads(document.metadata.get("text_preparation_json", ""))
        except (TypeError, ValueError):
            preparation = {}
        for item in preparation.get("pages", ()) if isinstance(preparation, dict) else ():
            if not isinstance(item, dict):
                continue
            number = int(item.get("page_number") or 0)
            if number < 1:
                continue
            blocks = item.get("blocks") or ()
            layout = str(item.get("layout_text") or "")
            if not layout:
                layout = "\n".join(str(block.get("text") or "") for block in blocks if isinstance(block, dict))
            self._text_variants[number] = {
                "Bereinigt": str(item.get("normalized_text") or ""),
                "Layout": layout or str(item.get("normalized_text") or ""),
                "Original": str(item.get("original_text") or ""),
            }
        if not self._text_variants:
            self._text_variants = {page.number: {"Bereinigt": page.text, "Layout": page.text, "Original": page.text}
                                   for page in document.pages}
        self.page_texts = {number: values.get("Bereinigt", "") for number, values in self._text_variants.items()}
        self._pdf_text_cache.clear()
        self._marking_specs = []
        self._current_markings = []
        self._layer_markings = []
        self._selected_field_path = ""
        self._pending_pdf_selection = None
        self.pdf_text_layer.set_page_variants(self._text_variants)
        if self.pdf_document:
            reader = PdfReader(str(path)); self.pdf_view.setPageRotations({index + 1: int(page.get("/Rotate", 0) or 0)
                                                                           for index, page in enumerate(reader.pages)})
            self.pdf_view.setMarkings([])
            self.pdf_document.load(str(path)); self.go_to_page(0)
            self._pdf_status_changed(self.pdf_document.status())
        else:
            self.pdf_view.setPlainText("\n\n".join(page.text for page in document.pages))
            self.page_label.setText(f"{len(document.pages)} Seite(n)")
            self.pdf_text_layer.set_field_markings([])

    def _text_view_changed(self, mode: str):
        self.pdf_text_layer.set_view_mode(mode)
        # Clean/layout text shares the prepared text-layer coordinates. The
        # untouched extractor output does not, so its offsets must not receive
        # automatic parser markers.
        self.pdf_text_layer.set_field_markings([] if mode == "Original" else self._layer_markings)


    # -- evidence-driven PDF markings -------------------------------------

    def _pdf_status_changed(self, status=None):
        """Refresh markings once Qt PDF has finished loading the document."""
        if not self.pdf_document:
            return
        try:
            ready = getattr(QPdfDocument, "Status", None) is not None and status == QPdfDocument.Status.Ready
        except (RuntimeError, AttributeError):  # teardown race
            return
        if not ready:
            return
        try:
            count = self.pdf_document.pageCount()
        except RuntimeError:
            return
        if count <= 0:
            return
        self.page_label.setText(f"Seite {self.current_page_index + 1} / {count}")
        self._pdf_text_cache.clear()
        self.refresh_pdf_markings()

    def _pdf_page_texts(self) -> dict[int, str]:
        """Cached text from Qt PDF; its indices are valid for selections."""
        if not self.pdf_document:
            return {}
        if self._pdf_text_cache:
            return dict(self._pdf_text_cache)
        try:
            if self.pdf_document.status() != QPdfDocument.Status.Ready:
                return {}
            for index in range(self.pdf_document.pageCount()):
                selection = self.pdf_document.getAllText(index)
                self._pdf_text_cache[index + 1] = selection.text() if selection.isValid() else ""
        except (RuntimeError, AttributeError):
            self._pdf_text_cache.clear()
        return dict(self._pdf_text_cache)

    def _annotations(self):
        if not self.current_run_id:
            return []
        try:
            run = ReferenceRepository(self.repository_path).run(self.current_run_id)
            return ReferenceRepository(self.repository_path).annotations_for_document(run["document_id"])
        except Exception:
            return []

    def _marking_visibility(self):
        if not self.markings_enabled.isChecked() or self.marking_scope.currentText() == "Markierungen ausblenden":
            return False, "off"
        if self.marking_scope.currentText() == "Nur ausgewähltes Feld":
            return True, "selected"
        return True, "all"

    def refresh_pdf_markings(self):
        """Recompute highlights from the current report without reparsing PDFs."""
        report = self._report_for(str(self.current_pdf)) if self.current_pdf else {}
        if not report:
            self._marking_specs = []; self._current_markings = []; self._layer_markings = []
            if hasattr(self.pdf_view, "setMarkings"):
                self.pdf_view.setMarkings([])
            self.pdf_text_layer.set_field_markings([])
            return
        specs = collect_marking_specs(report, self._catalog(), self.training_widget.mode.currentText(),
                                      self._annotations())
        self._marking_specs = specs
        page_texts = self._pdf_page_texts()
        preparation = report.get("text_preparation") if isinstance(report, dict) else {}
        preparation = preparation if isinstance(preparation, dict) else {}
        # Qt character offsets belong to Qt's own text layer.  When PDFium was
        # selected, its text may not share those offsets; do not invent a
        # green PDF overlay from an unsafe cross-extractor offset.
        qt_mapping_safe = "pdfium" not in str(preparation.get("extractors") or "").casefold()
        if page_texts and self.pdf_document and qt_mapping_safe:
            def quads(page_number, start, end):
                return self.pdf_document.getSelectionAtIndex(page_number - 1, start, max(1, end - start))
            self._current_markings = resolve_marking_specs(specs, page_texts, quads)
        else:
            self._current_markings = []
        self._layer_markings = text_layer_markers(specs, self.page_texts)
        if hasattr(self.pdf_view, "setMarkings"):
            self.pdf_view.setMarkings(self._current_markings)
        self._apply_marking_visibility()

    def _apply_marking_visibility(self):
        enabled, scope = self._marking_visibility()
        if hasattr(self.pdf_view, "setMarkingOptions"):
            self.pdf_view.setMarkingOptions(enabled, scope, self._selected_field_path)
        if enabled and scope == "selected":
            markers = [item for item in self._layer_markings if item.field_path == self._selected_field_path]
        elif enabled:
            markers = list(self._layer_markings)
        else:
            markers = []
        self.pdf_text_layer.set_field_markings(markers)

    @Slot()
    def _marking_option_changed(self, *_):
        self._apply_marking_visibility()

    def _mode_changed(self, mode):
        if mode:
            self.refresh_field_analysis()
            self.refresh_pdf_markings()

    def _markings_activated(self, markers):
        """A PDF/text-layer highlight was clicked: reveal the matching table row."""
        if not markers:
            return
        first = markers[0]
        self._navigating = True
        try:
            self._selected_field_path = first.field_path
            self.go_to_page(int(first.page_number) - 1)
            self.evidence_excerpt.setPlainText(first.text or first.value)
            self._apply_marking_visibility()
            self._select_field_in_tables(first.field_path)
            if hasattr(self.pdf_view, "focusMarking"):
                self.pdf_view.focusMarking(first.field_path)
            self.pdf_text_layer.focus_field(first.field_path)
            # Clicking a PDF highlight is the reverse direction of the field
            # analysis: reveal the exact same row, even after sorting/filtering.
            if self.field_analysis.select_field_path(first.field_path):
                self.tabs.setCurrentWidget(self.field_analysis)
        finally:
            self._navigating = False

    def _training_field_activated(self, display):
        if self._navigating or display is None:
            return
        self._navigating = True
        try:
            self._selected_field_path = display.path
            marker = next((item for item in self._current_markings
                           if item.field_path == display.path), None)
            page = marker.page_number if marker else display.page
            if page not in (None, ""):
                self.go_to_page(int(page) - 1)
            self._apply_marking_visibility()
            if hasattr(self.pdf_view, "focusMarking"):
                self.pdf_view.focusMarking(display.path)
            self.pdf_text_layer.focus_field(display.path)
            evidence = display.evidence or {}
            if evidence.get("excerpt"):
                self.evidence_excerpt.setPlainText(evidence.get("excerpt", ""))
            self.field_analysis.select_field_path(display.path)
        finally:
            self._navigating = False

    def _select_field_in_tables(self, path):
        if not path:
            return False
        for table in tuple(self.tables.values()) + (self.training_widget.fields,):
            for row in range(table.rowCount()):
                item = table.item(row, 0)
                if item and (item.text() == path or item.text().endswith(path)):
                    table.selectRow(row); table.scrollToItem(item)
                    break
        if hasattr(self, "field_analysis") and self.field_analysis.select_field_path(path):
            return True
        return any(table.currentRow() >= 0 for table in self.tables.values())

    def _current_report(self):
        return self._report_for(str(self.current_pdf)) if self.current_pdf else {}

    def _start_field_training(self, row):
        """Open the existing training tab fully preselected from field analysis."""
        if row is None:
            return
        context = self.field_analysis.training_context(row)
        if context is None:
            return
        self.training_widget.apply_training_context(context, self._catalog(), self.current_pdf)
        if self.ui_mode.currentText() == "Experte":
            self.tabs.setCurrentWidget(self.training_widget)
        else:
            self.tabs.setCurrentWidget(self.field_analysis)
            existing = None
            if self.current_run_id:
                run = ReferenceRepository(self.repository_path).run(self.current_run_id)
                existing = next((item for item in reversed(ReferenceRepository(self.repository_path).annotations_for_document(run["document_id"]))
                                 if item["field_path"] == context.field_path), None)
            definition = self._catalog().field(context.field_path)
            if definition:
                self.quick_training.begin(context, definition, existing, self._catalog()); self.quick_training.show()
                self.root_splitter.setSizes((220, 560, 430, 330))
        if context.page_number:
            self.go_to_page(int(context.page_number) - 1)
            evidence = context.evidence if isinstance(context.evidence, dict) else {}
            if evidence.get("excerpt"):
                self.evidence_excerpt.setPlainText(evidence.get("excerpt", ""))
        self._selected_field_path = context.field_path
        self._apply_marking_visibility()
        if hasattr(self.pdf_view, "focusMarking"):
            self.pdf_view.focusMarking(context.field_path)
        self.pdf_text_layer.focus_field(context.field_path)
        self.statusBar().showMessage("Wert direkt im PDF markieren; Feld und Dokumentkontext sind bereits vorbelegt.", 6000)

    def _field_analysis_activated(self, row):
        if row is None or self._navigating:
            return
        self._navigating = True
        try:
            self._selected_field_path = row.path
            page = _positive_int(row.page)
            if page:
                self.go_to_page(page - 1)
            evidence = row.evidence if isinstance(row.evidence, dict) else {}
            if evidence.get("excerpt"):
                self.evidence_excerpt.setPlainText(str(evidence.get("excerpt")))
                self.pdf_text_layer.highlight_text(str(evidence.get("excerpt")))
            self._apply_marking_visibility()
            if hasattr(self.pdf_view, "focusMarking"):
                self.pdf_view.focusMarking(row.path)
            self.pdf_text_layer.focus_field(row.path)
            self._select_field_in_tables(row.path)
        finally:
            self._navigating = False

    def _show_field_analysis_help(self, row):
        if row is not None:
            FieldHelpDialog(row, self).exec()

    def reparse_current(self):
        """Run the active plugin and mode again for the selected PDF."""
        if self.current_pdf is None:
            QMessageBox.information(self, "Neu parsen", "Bitte zuerst ein PDF auswählen.")
            return
        if not self.current_pdf.is_file():
            QMessageBox.warning(self, "Neu parsen", "Die PDF-Datei ist nicht mehr vorhanden.")
            return
        self.analyse(self.current_pdf)

    def show_quick_values(self):
        """Display only financial values actually emitted by the base parser."""
        self._show_standard_values(financial_only=True)

    def _show_standard_values(self, financial_only=False):
        """Show only values from the stored base STANDARD result.

        An EXTENDED/COMPARE report still contains the unchanged base result in
        ``result``.  No rule decisions, annotations or catalog-only rows enter
        this view.
        """
        report = self._current_report()
        if not isinstance(report.get("result"), dict):
            if not self.current_pdf:
                QMessageBox.information(self, "Alle gefundenen Werte",
                                         "Bitte zuerst ein Dokument auswählen.")
                return
            answer = QMessageBox.question(
                self, "STANDARD-Lauf erforderlich",
                "Für dieses Dokument liegt noch kein STANDARD-Ergebnis vor. Jetzt STANDARD ausführen?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
            if answer == QMessageBox.Yes:
                self.analyse(self.current_pdf, "STANDARD")
            return
        rows = build_standard_value_rows(report, self._catalog(), financial_only=financial_only)
        dialog = StandardValuesDialog(rows, report, self)
        dialog.fieldActivated.connect(self._standard_value_activated)
        self._standard_values_dialog = dialog
        dialog.show(); dialog.raise_(); dialog.activateWindow()

    def _standard_value_activated(self, row):
        display = getattr(row, "display_row", None)
        if display is None:
            return
        self._selected_field_path = display.path
        self._field_activated(display)
        self.field_analysis.select_field_path(display.path)
        self.tabs.setCurrentWidget(self.field_analysis)

    def refresh_field_analysis(self):
        if not hasattr(self, "field_analysis"):
            return
        report = self._current_report()
        selected = self.field_analysis.selected_row()
        path = selected.path if selected is not None else ""
        self.field_analysis.bind_report(report or None, self._catalog() if report else None)
        if path:
            self.field_analysis.select_field_path(path)

    def _training_changed(self, payload):
        """A training action must never invent a parser result, only refresh views."""
        self.refresh_field_analysis()
        if self.current_run_id:
            try:
                run = ReferenceRepository(self.repository_path).run(self.current_run_id)
                self._load_annotation_highlights(run["document_id"])
            except (KeyError, ValueError):
                self.refresh_pdf_markings()
        else:
            self.refresh_pdf_markings()
        path = (payload or {}).get("field_path") if isinstance(payload, dict) else ""
        if path:
            self.field_analysis.select_field_path(path)
        self.statusBar().showMessage("Trainingsstand aktualisiert", 3000)

    def _return_to_field_analysis(self):
        context = self.training_widget.context
        self.refresh_field_analysis()
        if context is not None and context.field_path:
            self.field_analysis.select_field_path(context.field_path)
        self.tabs.setCurrentWidget(self.field_analysis)

    def _pdf_selection_changed(self, selection):
        if selection is None:
            return
        self._pending_pdf_selection = selection
        page = _positive_int(getattr(selection, "page_number", 0))
        if page:
            self.pdf_text_layer.show_page(page)
        text = str(getattr(selection, "text", "") or "")
        self.evidence_excerpt.setPlainText(f"Seite {page or '—'}\n{text}")
        if self.training_widget.context is not None or self.tabs.currentWidget() is self.training_widget:
            self.training_widget.apply_pdf_selection(selection)
        if self.ui_mode.currentText() == "Schnell" and self.quick_training.active:
            self.quick_training.set_selection(selection)

    def go_to_page(self, page_index: int):
        if not self.pdf_document: return
        count = self.pdf_document.pageCount()
        if count and 0 <= page_index < count:
            self.current_page_index = page_index; self.pdf_view.setPage(page_index)
            self.page_label.setText(f"Seite {page_index + 1} / {count}")
            self.pdf_text_layer.show_page(page_index + 1)

    def show_report(self, report: dict):
        if not isinstance(report, Mapping):
            LOGGER.error("show_report erwartet ein Dictionary, erhalten: %s", type(report).__name__)
            return
        result = report.get("result", {})
        result = result if isinstance(result, Mapping) else {}
        preparation = report.get("text_preparation") if isinstance(report, dict) else {}
        preparation = preparation if isinstance(preparation, dict) else {}
        quality = str(preparation.get("quality") or "")
        self.text_quality.setText({
            "ok": "Textqualität: OK",
            "suspicious": "Textqualität: prüfen",
            "unreliable": "Textqualität: nicht zuverlässig",
        }.get(quality.casefold(), "Textqualität: —"))
        self.text_quality.setToolTip(
            f"Aufbereitung {preparation.get('version', '—')} · "
            f"Extraktor {preparation.get('extractors', '—')}")
        mapping = {
            "Übersicht": result,
            "Konto": result.get("accounts", []), "Depot": result.get("depots", []) + result.get("depot_snapshots", []),
            "Buchungen": result.get("events", []), "Geldflüsse": [m for e in result.get("events", []) for m in e.get("cash_movements", [])],
            "Gebühren & Kosten": [f for e in result.get("events", []) for f in e.get("fee_events", [])],
            "Steuern": [t for e in result.get("events", []) for t in e.get("tax_events", [])],
            "Referenzvergleich": report.get("parser_comparison", {}).get("rows", []) + report.get("reference_comparison", []), "Issues": report.get("issues", []),
        }
        evidence = {item["evidence_id"]: item for item in result.get("evidence", [])}
        for name, data in mapping.items():
            self.result_views[name].set_data(data, evidence, self._catalog() if name == "Übersicht" else None)

    def _field_activated(self, row):
        if row is None:
            return
        evidence = row.evidence if row else None
        self._navigating = True
        try:
            self._selected_field_path = row.path
            marker = next((item for item in self._current_markings if item.field_path == row.path), None)
            if evidence:
                self.go_to_page(int(evidence["page_number"]) - 1)
                self.evidence_excerpt.setPlainText(evidence.get("excerpt", ""))
                self.pdf_text_layer.highlight_text(evidence.get("excerpt", ""))
            elif marker is not None:
                self.go_to_page(marker.page_number - 1)
            self._apply_marking_visibility()
            if hasattr(self.pdf_view, "focusMarking"):
                self.pdf_view.focusMarking(row.path)
            self.pdf_text_layer.focus_field(row.path)
            self._select_field_in_tables(row.path)
        finally:
            self._navigating = False

    def _catalog(self):
        report = self._current_report()
        detection = report.get("detection", {}); result = report.get("result", {})
        detected_id = detection.get("plugin_id", "")
        bank = "comdirect" if "comdirect" in detected_id.casefold() else (detected_id.split(".")[0] or "generic")
        return self.catalog_store.catalog(bank,
                                          result.get("plugin_id", "user.comdirect-ertraege"),
                                          detection.get("document_type", "*"),
                                          result.get("attributes", {}).get("layout_path", "*"))

    def show_field_help(self):
        CatalogHelpDialog(self._catalog(), self).exec()

    def _pdf_text_action(self, action, selection):
        if action == "new":
            return  # New user-defined field creation has been removed.
        if action in {"edit", "remove"} and selection is None:
            QMessageBox.information(self, "PDF-Annotation", "Bitte zuerst die zu bearbeitende Fundstelle markieren."); return
        if action == "locate":
            self.evidence_excerpt.setPlainText(f"Seite {selection.page_number}\n{selection.text}"); return
        report = self._current_report()
        if not report or not report.get("run_id"):
            QMessageBox.warning(self, "PDF-Textauswahl", "Bitte zuerst einen gespeicherten Parserlauf auswählen."); return
        detection = report.get("detection", {}); result = report.get("result", {})
        training_context = self.training_widget.context
        context = {"bank": detection.get("plugin_id", "").split(".")[0], "parser_id": result.get("plugin_id", ""),
                   "handler_id": result.get("handler_id", ""),
                   "document_type": detection.get("document_type", ""),
                   "original_text": selection.text if selection is not None else self.pdf_text_layer.toPlainText(),
                   "rule_mode": report.get("rule_mode_effective", "STANDARD"),
                   "document_hash": report.get("source_hash", "")}
        repository = ReferenceRepository(self.repository_path); run = repository.run(report["run_id"])
        matches = [item for item in repository.annotations_for_document(run["document_id"])
                   if item["page_number"] == selection.page_number and item["original_text"] == selection.text]
        if action == "remove":
            if not matches: QMessageBox.information(self, "PDF-Annotation", "Keine passende Annotation gefunden."); return
            repository.deactivate_annotation(matches[-1]["annotation_id"], "GUI user", "Removed from PDF context menu")
            self._load_annotation_highlights(run["document_id"]); return
        preselect = training_context.field_path if training_context is not None else ""
        quick = self.ui_mode.currentText() == "Schnell" and bool(preselect)
        dialog = FieldMappingDialog(self._catalog(), self.catalog_store, context, selection.text,
                                    selection.page_number, selection.coordinates, False, self,
                                    preselect=preselect, quick=quick)
        if not dialog.exec() or not dialog.mapping_result: return
        mapped = dialog.mapping_result
        kind = {"DECIMAL": "AMOUNT", "DATE": "DATE", "ISIN": "SECURITY_ID", "WKN": "SECURITY_ID",
                "MULTILINE": "MULTILINE"}.get(mapped.field.data_type, "TEXT")
        coordinates = dict(mapped.coordinates or {})
        document = repository.document(run["document_id"])
        coordinates.update({"document_id": run["document_id"], "document_hash": document["sha256"],
                            "field_path": mapped.field.path})
        if action == "edit" and matches:
            repository.deactivate_annotation(matches[-1]["annotation_id"], "GUI user", "Superseded from PDF context menu")
        annotation_id = repository.create_annotation(
            run["document_id"], run["plugin_id"], run["handler_id"], mapped.page_number, mapped.selected_text,
            mapped.field.path, mapped.normalized_value, kind, "CONFIRMED", "IN_REVIEW", "GUI user", coordinates)
        if action == "reference":
            repository.set_reference(run["document_id"], mapped.field.path, mapped.normalized_value, "GUI user", "PDF selection")
        self.training_widget.annotation_id = annotation_id
        self.training_widget.pending_selection = selection
        self.training_widget.field_path.setText(mapped.field.path); self.training_widget.reference_value.setText(mapped.normalized_value)
        self.training_widget.source_text.setPlainText(mapped.selected_text)
        self.training_widget.result.setPlainText(f"Annotation {annotation_id} aus PDF-Auswahl gespeichert")
        self._load_annotation_highlights(run["document_id"])
        self._highlight_field(mapped.field.path)
        self.refresh_field_analysis()
        self.field_analysis.select_field_path(mapped.field.path)
        if quick:
            self.quick_candidate_id = TrainingService(repository).suggest_rule(annotation_id, "GUI quick mode")
            self.training_widget.candidate_id = self.quick_candidate_id
            self.training_widget.context = None
            message = ("Regelkandidat vorgeschlagen. Bitte mit „Regel prüfen“ testen; weitere Beispiele können erforderlich sein."
                       if self.quick_candidate_id else "Kein sicherer Kandidat möglich; bitte ein weiteres Beispiel hinzufügen.")
            QMessageBox.information(self, "Feldtraining", message)

    def _quick_confirm(self, selection, raw_value):
        context = self.quick_training.context; definition = self.quick_training.definition
        if not context or not self.current_run_id: return
        try:
            normalizer = definition.normalizers[0] if definition.normalizers else "TEXT"
            _original, normalized = EditorFactory.normalize(raw_value, definition, normalizer)
            repository = ReferenceRepository(self.repository_path); run = repository.run(self.current_run_id)
            document = repository.document(run["document_id"]); coordinates = dict(selection.coordinates or {})
            coordinates.update({"document_id": run["document_id"], "document_hash": document["sha256"],
                                "field_path": context.field_path})
            kind = {"DECIMAL":"AMOUNT", "DATE":"DATE", "ISIN":"SECURITY_ID", "WKN":"SECURITY_ID",
                    "MULTILINE":"MULTILINE"}.get(definition.data_type, "TEXT")
            page_text = self.page_texts.get(selection.page_number, "")
            start = max(0, int(getattr(selection, "start_index", 0))); end = max(start, int(getattr(selection, "end_index", start)))
            line_start = max(page_text.rfind("\n", 0, start), page_text.rfind("\r", 0, start)) + 1
            candidates = [position for position in (page_text.find("\n", end), page_text.find("\r", end)) if position >= 0]
            line_end = min(candidates) if candidates else len(page_text)
            source_text = page_text[line_start:line_end].strip() or selection.text
            annotation = repository.create_annotation(run["document_id"], run["plugin_id"], run["handler_id"],
                selection.page_number, source_text, context.field_path, normalized, kind, "CONFIRMED", "APPROVED",
                "GUI quick mode", coordinates)
            repository.set_reference(run["document_id"], context.field_path, normalized, "GUI quick mode", "Quick training confirmation")
            self.training_widget.annotation_id = annotation; self.training_widget.reference_value.setText(normalized)
            self.quick_candidate_id = TrainingService(repository).suggest_rule(annotation, "GUI quick mode")
            self.training_widget.candidate_id = self.quick_candidate_id
            self.quick_training.candidate_created(self.quick_candidate_id)
            self._load_annotation_highlights(run["document_id"]); self.refresh_field_analysis()
            self.field_analysis.select_field_path(context.field_path)
        except ValueError as exc:
            self.quick_training.result.setText(str(exc))

    def _quick_missing(self):
        context = self.quick_training.context
        if not context or not self.current_run_id: return
        repository = ReferenceRepository(self.repository_path); run = repository.run(self.current_run_id)
        annotation = repository.create_annotation(run["document_id"], run["plugin_id"], run["handler_id"], 1, "",
            context.field_path, None, "MISSING", "MISSING", "APPROVED", "GUI quick mode")
        repository.set_reference(run["document_id"], context.field_path, None, "GUI quick mode", "Confirmed absent in PDF")
        self.training_widget.annotation_id = annotation; self.quick_training.result.setText("Abwesenheit dauerhaft bestätigt; keine Extraktionsregel erzeugt.")
        self.refresh_field_analysis(); self.field_analysis.select_field_path(context.field_path)

    def _quick_cancel(self):
        self.quick_training.reset(); self.quick_training.hide(); self.training_widget.context = None
        self.root_splitter.setSizes((250, 650, 480, 0))

    def _quick_test_rule(self):
        candidate = self.quick_candidate_id or self.training_widget.candidate_id
        if not candidate: self.quick_training.result.setText("Zuerst einen Wert bestätigen und einen Kandidaten erzeugen."); return
        result = TrainingService(ReferenceRepository(self.repository_path)).test_candidate(candidate, "GUI quick mode")
        if result["regressions"]: message = f"Fehler oder Konflikte gefunden: {result['regressions']}"
        elif result["improved"] < 2: message = "Erfolgreich geprüft. Für sichere Generalisierung sind weitere Beispiele empfohlen."
        else: message = "Erfolgreich geprüft. Keine Regressionen gefunden."
        self.quick_training.tested(message, not result["regressions"])

    def _quick_approve_rule(self):
        candidate = self.quick_candidate_id or self.training_widget.candidate_id
        if not candidate: self.quick_training.result.setText("Keine geprüfte Regel vorhanden."); return
        try:
            self.quick_version_id = TrainingService(ReferenceRepository(self.repository_path)).approve(candidate, "GUI quick mode", "Explicit quick-mode approval")
            self.training_widget.version_id = self.quick_version_id
            self.quick_training.approved()
        except ValueError as exc: self.quick_training.result.setText(str(exc))

    def _quick_activate_rule(self):
        version = self.quick_version_id or self.training_widget.version_id
        if not version: self.quick_training.result.setText("Zuerst eine Regel ausdrücklich freigeben."); return
        TrainingService(ReferenceRepository(self.repository_path)).activate(version)
        self.quick_training.activated()

    def _quick_recheck(self):
        if self.current_pdf:
            self.quick_training.result.setText("EXTENDED wird erneut ausgeführt …")
            self.analyse(self.current_pdf, "EXTENDED")

    def _load_annotation_highlights(self, document_id):
        self.pdf_view.clearSavedCoordinates()
        for annotation in ReferenceRepository(self.repository_path).annotations_for_document(document_id):
            if annotation.get("coordinates"):
                self.pdf_view.addSavedCoordinates(annotation["page_number"], annotation["coordinates"])
        self.refresh_pdf_markings()

    def _highlight_field(self, path):
        if not path:
            return
        self._navigating = True
        try:
            self._selected_field_path = path
            marker = next((item for item in self._current_markings if item.field_path == path), None)
            if marker is not None:
                self.go_to_page(marker.page_number - 1)
            self._apply_marking_visibility()
            if hasattr(self.pdf_view, "focusMarking"):
                self.pdf_view.focusMarking(path)
            self.pdf_text_layer.focus_field(path)
            self._select_field_in_tables(path)
        finally:
            self._navigating = False

    def _edit_reference(self, row: int, column: int):
        """Store an explicit field-level target; parser output never overwrites it."""
        if self.current_run_id is None:
            return
        table = self.tables["Referenzvergleich"]
        field_item = table.item(row, 0); value_item = table.item(row, 1)
        if not field_item:
            return
        value, ok = QInputDialog.getMultiLineText(self, "Sollwert bearbeiten", field_item.text(), value_item.text() if value_item else "null")
        if not ok:
            return
        try:
            expected = json.loads(value)
        except json.JSONDecodeError:
            expected = value
        run = ReferenceRepository(self.repository_path).run(self.current_run_id)
        ReferenceRepository(self.repository_path).set_reference(run["document_id"], field_item.text(), expected, "GUI user", "Field-level manual review")
        self.statusBar().showMessage("Sollwert mit Historie gespeichert", 3000)


def main(argv=None) -> int:
    app = QApplication(list(sys.argv if argv is None else argv)); window = MainWindow(); window.showMaximized()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
