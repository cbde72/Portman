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
from portman_pdf_lab.ui.result_view import StructuredResultView
from portman_pdf_lab.ui.pdf_text_layer import PdfTextLayer
from portman_pdf_lab.ui.field_mapping import CatalogHelpDialog, FieldMappingDialog
from portman_pdf_lab.field_catalog import CatalogStore
from portman_pdf_lab.ui.pdf_markings import (
    ORIGIN_PARSER, PdfMarking, collect_marking_specs, resolve_marking_specs,
    text_layer_markers,
)

try:
    from PySide6.QtPdf import QPdfDocument
except ImportError:  # pragma: no cover - platform packaging fallback
    QPdfDocument = None

from portman_pdf_lab.ui.direct_pdf_view import DirectPdfView


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
                 "Gebühren & Kosten", "Steuern", "Referenzvergleich", "Issues", "Parsertraining")

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
        self._build_ui()
        self._restore_layout()

    def _build_ui(self):
        toolbar = QToolBar("Dokumente", self); self.addToolBar(toolbar)
        open_action = QAction("PDF öffnen", self); open_action.triggered.connect(self.open_pdf_dialog)
        toolbar.addAction(open_action)
        batch_action = QAction("Ordner analysieren", self); batch_action.triggered.connect(self.open_directory_dialog)
        toolbar.addAction(batch_action)
        cancel_action = QAction("Abbrechen", self); cancel_action.triggered.connect(self.cancel_batch); toolbar.addAction(cancel_action)
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
        self.page_label = QLabel("Keine PDF"); self.zoom_out = QPushButton("−"); self.zoom_in = QPushButton("+")
        self.markings_enabled = QCheckBox("Erkannte Werte markieren"); self.markings_enabled.setChecked(True)
        self.marking_scope = QComboBox()
        self.marking_scope.addItems(("Alle erkannten Felder", "Nur ausgewähltes Feld", "Markierungen ausblenden"))
        self.markings_enabled.setToolTip("Automatische, evidencebasierte PDF-Markierungen ein- oder ausblenden")
        nav.addWidget(self.previous); nav.addWidget(self.next); nav.addWidget(self.page_label); nav.addStretch()
        nav.addWidget(self.markings_enabled); nav.addWidget(self.marking_scope)
        nav.addWidget(self.zoom_out); nav.addWidget(self.zoom_in); middle_layout.addLayout(nav)
        if QPdfDocument:
            self.current_page_index = 0
            self.pdf_document = QPdfDocument(self); self.pdf_view = DirectPdfView(); self.pdf_view.setDocument(self.pdf_document)
            self.pdf_document.statusChanged.connect(self._pdf_status_changed)
            self.pdf_view.actionRequested.connect(self._pdf_text_action)
            self.pdf_view.markingActivated.connect(self._markings_activated)
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
        self.pdf_splitter = QSplitter(Qt.Vertical); self.pdf_splitter.setObjectName("pdf-splitter")
        self.pdf_splitter.addWidget(self.pdf_view); self.pdf_splitter.addWidget(self.pdf_text_layer); self.pdf_splitter.addWidget(self.evidence_excerpt)
        self.pdf_splitter.setStretchFactor(0, 5); self.pdf_splitter.setStretchFactor(1, 2); self.pdf_splitter.setStretchFactor(2, 1)
        middle_layout.addWidget(self.pdf_splitter)

        self.tabs = QTabWidget(); self.tables = {}; self.result_views = {}
        for name in self.TAB_NAMES[:-1]:
            view = StructuredResultView(); table = view.table
            table.fieldActivated.connect(self._field_activated)
            self.tables[name] = table; self.result_views[name] = view; self.tabs.addTab(view, name)
        self.tables["Referenzvergleich"].cellDoubleClicked.connect(self._edit_reference)
        self.training_widget = TrainingWidget(self.repository_path)
        self.training_widget.fieldActivated.connect(self._training_field_activated)
        self.training_widget.mode.currentTextChanged.connect(self._mode_changed)
        self.tabs.addTab(self.training_widget, "Parsertraining")
        root.addWidget(left); root.addWidget(middle); root.addWidget(self.tabs); root.setSizes((280, 720, 500))
        root.setChildrenCollapsible(False); root.setStretchFactor(1, 2); root.setStretchFactor(2, 2)
        left.setMinimumWidth(140); middle.setMinimumWidth(220); self.tabs.setMinimumWidth(260)
        self.markings_enabled.toggled.connect(self._marking_option_changed)
        self.marking_scope.currentTextChanged.connect(self._marking_option_changed)
        self.setCentralWidget(root); self.statusBar().showMessage("Bereit")

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
        self.markings_enabled.setChecked(self.settings.value("pdf/markings-enabled", True, type=bool))
        scope = self.settings.value("pdf/markings-scope", "Alle erkannten Felder", type=str)
        if scope in {self.marking_scope.itemText(index) for index in range(self.marking_scope.count())}:
            self.marking_scope.setCurrentText(scope)
        for name, view in self.result_views.items():
            state = self.settings.value(f"headers/{name}")
            if state: view.table.horizontalHeader().restoreState(state)

    def closeEvent(self, event):
        self.settings.setValue("window/geometry", self.saveGeometry())
        self.settings.setValue("window/maximized", self.isMaximized())
        self.settings.setValue("splitters/main", self.root_splitter.saveState())
        self.settings.setValue("splitters/pdf", self.pdf_splitter.saveState())
        self.training_widget.save_settings(self.settings)
        self.settings.setValue("pdf/markings-enabled", self.markings_enabled.isChecked())
        self.settings.setValue("pdf/markings-scope", self.marking_scope.currentText())
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

    def analyse(self, path: Path):
        self.statusBar().showMessage(f"Analysiere {path.name} …")
        worker = AnalysisWorker(path, self.repository_path, self.training_widget.mode.currentText()); self.workers.add(worker)
        worker.signals.result.connect(lambda result, p=path: self._analysis_ready(p, result))
        worker.signals.error.connect(lambda message: QMessageBox.warning(self, "Analysefehler", message))
        worker.signals.finished.connect(lambda w=worker: self._worker_finished(w)); self.thread_pool.start(worker)

    def _analysis_ready(self, path: Path, report: dict):
        if self.cancel_requested: return
        key = str(path); self.documents[key] = report
        if not self.document_list.findItems(key, Qt.MatchExactly): self.document_list.addItem(key)
        self.document_list.setCurrentRow(self.document_list.count() - 1)

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
        self.load_pdf(self.current_pdf); self.show_report(self.documents[key])
        self.training_widget.bind_report(self.documents[key], self.current_pdf, self._catalog())
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
        self.page_texts = {page.number: page.text for page in document.pages}
        self._pdf_text_cache.clear()
        self._marking_specs = []
        self._current_markings = []
        self._layer_markings = []
        self._selected_field_path = ""
        self.pdf_text_layer.set_pages(self.page_texts)
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
        if page_texts and self.pdf_document:
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
        finally:
            self._navigating = False

    def _select_field_in_tables(self, path):
        for table in tuple(self.tables.values()) + (self.training_widget.fields,):
            for row in range(table.rowCount()):
                item = table.item(row, 0)
                if item and (item.text() == path or item.text().endswith(path)):
                    table.selectRow(row); table.scrollToItem(item)
                    return True
        return False

    def go_to_page(self, page_index: int):
        if not self.pdf_document: return
        count = self.pdf_document.pageCount()
        if count and 0 <= page_index < count:
            self.current_page_index = page_index; self.pdf_view.setPage(page_index)
            self.page_label.setText(f"Seite {page_index + 1} / {count}")
            self.pdf_text_layer.show_page(page_index + 1)

    def show_report(self, report: dict):
        result = report.get("result", {})
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
        report = self.documents.get(str(self.current_pdf), {}) if self.current_pdf else {}
        if not report or not report.get("run_id"):
            QMessageBox.warning(self, "PDF-Textauswahl", "Bitte zuerst einen gespeicherten Parserlauf auswählen."); return
        detection = report.get("detection", {}); result = report.get("result", {})
        context = {"bank": detection.get("plugin_id", "").split(".")[0], "parser_id": result.get("plugin_id", ""),
                   "document_type": detection.get("document_type", ""), "original_text": self.pdf_text_layer.toPlainText(),
                   "rule_mode": report.get("rule_mode_effective", "STANDARD")}
        repository = ReferenceRepository(self.repository_path); run = repository.run(report["run_id"])
        matches = [item for item in repository.annotations_for_document(run["document_id"])
                   if item["page_number"] == selection.page_number and item["original_text"] == selection.text]
        if action == "remove":
            if not matches: QMessageBox.information(self, "PDF-Annotation", "Keine passende Annotation gefunden."); return
            repository.deactivate_annotation(matches[-1]["annotation_id"], "GUI user", "Removed from PDF context menu")
            self._load_annotation_highlights(run["document_id"]); return
        dialog = FieldMappingDialog(self._catalog(), self.catalog_store, context, selection.text,
                                    selection.page_number, selection.coordinates, action == "new", self)
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
        self.training_widget.field_path.setText(mapped.field.path); self.training_widget.reference_value.setText(mapped.normalized_value)
        self.training_widget.source_text.setPlainText(mapped.selected_text)
        self.training_widget.result.setPlainText(f"Annotation {annotation_id} aus PDF-Auswahl gespeichert")
        self._load_annotation_highlights(run["document_id"])
        self._highlight_field(mapped.field.path)

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
