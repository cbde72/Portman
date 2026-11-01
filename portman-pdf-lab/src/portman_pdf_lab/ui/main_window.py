"""Lean, independent PySide6 desktop interface for PDF analysis and review."""

import json
from pathlib import Path
import sys

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, Signal, Slot, QStandardPaths, QSettings
from PySide6.QtGui import QAction, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QListWidget, QInputDialog,
    QMainWindow, QMessageBox, QProgressBar, QPushButton, QSplitter, QTabWidget,
    QTableWidget, QTableWidgetItem, QTextEdit, QToolBar, QVBoxLayout, QWidget, QSizePolicy,
)

from portman_parsers.extraction import extract_pdf
from pypdf import PdfReader
from portman_pdf_lab.application.pdf_analysis import analyse_pdf
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
    ORIGIN_PARSER, PdfMarking, collect_marking_specs, resolve_marking_specs,
    text_layer_markers,
)

try:
    from PySide6.QtPdf import QPdfDocument
except ImportError:  # pragma: no cover - platform packaging fallback
    QPdfDocument = None

from portman_pdf_lab.ui.direct_pdf_view import DirectPdfView
from portman_pdf_lab.ui.quick_training import QuickTrainingPanel


def _positive_int(value) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError, OverflowError):
        return 0
    return number if number > 0 else 0


class WorkerSignals(QObject):
    result = Signal(object)
    error = Signal(str)
    finished = Signal()


class AnalysisWorker(QRunnable):
    def __init__(self, path: Path, repository_path: Path, rule_mode="STANDARD"):
        super().__init__(); self.path = path; self.repository_path = repository_path; self.rule_mode = rule_mode; self.signals = WorkerSignals()

    @Slot()
    def run(self):
        try:
            self.signals.result.emit(analyse_and_store(self.path, ReferenceRepository(self.repository_path), self.rule_mode)[0])
        except Exception as exc:  # defensive GUI boundary
            self.signals.error.emit(str(exc))
        finally:
            self.signals.finished.emit()


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
        files = sorted(Path(path).rglob("*.pdf")); self.cancel_requested = False
        self.progress.setRange(0, len(files)); self.progress.setValue(0); self.progress.setVisible(True)
        for item in files: self.analyse(item)

    def cancel_batch(self):
        self.cancel_requested = True; self.thread_pool.clear(); self.progress.setVisible(False)
        self.statusBar().showMessage("Batchanalyse abgebrochen", 3000)

    def analyse(self, path: Path, rule_mode=None):
        self.statusBar().showMessage(f"Analysiere {path.name} …")
        worker = AnalysisWorker(path, self.repository_path, rule_mode or self.training_widget.mode.currentText()); self.workers.add(worker)
        worker.signals.result.connect(lambda result, p=path: self._analysis_ready(p, result))
        worker.signals.error.connect(lambda message: QMessageBox.warning(self, "Analysefehler", message))
        worker.signals.finished.connect(lambda w=worker: self._worker_finished(w)); self.thread_pool.start(worker)

    def _analysis_ready(self, path: Path, report: dict):
        if self.cancel_requested: return
        key = str(path); self.documents[key] = report
        if not self.document_list.findItems(key, Qt.MatchExactly): self.document_list.addItem(key)
        self.document_list.setCurrentRow(self.document_list.count() - 1)
        if self.current_pdf == path:
            self.show_report(report); self.refresh_field_analysis(); self.refresh_pdf_markings()
        if self.quick_training.active and report.get("rule_mode_effective") == "EXTENDED":
            context = self.quick_training.context; reference = EditorFactory.text(self.quick_training.editor)
            decision = next((item for item in report.get("rule_decisions", ())
                             if item.get("field_path") == context.field_path), {})
            extended = decision.get("effective_value")
            status = "ERKANNT" if str(extended) == str(reference) and extended is not None else "PRÜFEN"
            self.quick_training.rechecked(context.current_value, extended, reference, status)

    def _worker_finished(self, worker=None):
        if worker is not None:
            self.workers.discard(worker)
        if self.progress.isVisible():
            self.progress.setValue(self.progress.value() + 1)
            if self.progress.value() >= self.progress.maximum(): self.progress.setVisible(False)
        self.statusBar().showMessage("Analyse abgeschlossen", 3000)

    def _filter_documents(self, text: str):
        needle = text.casefold()
        for index in range(self.document_list.count()):
            item = self.document_list.item(index); item.setHidden(needle not in item.text().casefold())

    def _select_document(self, key: str):
        if not key or key not in self.documents: return
        self.current_pdf = Path(key); self.current_run_id = self.documents[key].get("run_id")
        self._selected_field_path = ""
        self._pending_pdf_selection = None
        self.load_pdf(self.current_pdf); self.show_report(self.documents[key])
        catalog = self._catalog()
        self.training_widget.bind_report(self.documents[key], self.current_pdf, catalog)
        self.field_analysis.bind_report(self.documents[key], catalog)
        if self.current_run_id:
            self._load_annotation_highlights(ReferenceRepository(self.repository_path).run(self.current_run_id)["document_id"])
        else:
            self.refresh_pdf_markings()

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
        report = self.documents.get(str(self.current_pdf), {}) if self.current_pdf else {}
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
        return self.documents.get(str(self.current_pdf), {}) if self.current_pdf else {}

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

    def _show_standard_values(self):
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
        rows = build_standard_value_rows(report, self._catalog())
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
        result = report.get("result", {})
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
        report = self.documents.get(str(self.current_pdf), {}) if self.current_pdf else {}
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
                                    selection.page_number, selection.coordinates, action == "new", self,
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
