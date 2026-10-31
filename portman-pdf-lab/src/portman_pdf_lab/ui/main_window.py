"""Lean, independent PySide6 desktop interface for PDF analysis and review."""

import json
from pathlib import Path
import sys

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, Signal, Slot, QStandardPaths
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QListWidget, QInputDialog,
    QMainWindow, QMessageBox, QProgressBar, QPushButton, QSplitter, QTabWidget,
    QTableWidget, QTableWidgetItem, QTextEdit, QToolBar, QVBoxLayout, QWidget,
)

from portman_parsers.extraction import extract_pdf
from portman_pdf_lab.application.pdf_analysis import analyse_pdf
from portman_pdf_lab.application.reference_service import analyse_and_store
from portman_pdf_lab.reviews.models import ReviewStatus
from portman_pdf_lab.storage import ReferenceRepository

try:
    from PySide6.QtPdf import QPdfDocument
    from PySide6.QtPdfWidgets import QPdfView
except ImportError:  # pragma: no cover - platform packaging fallback
    QPdfDocument = QPdfView = None


class WorkerSignals(QObject):
    result = Signal(object)
    error = Signal(str)
    finished = Signal()


class AnalysisWorker(QRunnable):
    def __init__(self, path: Path, repository_path: Path):
        super().__init__(); self.path = path; self.repository_path = repository_path; self.signals = WorkerSignals()

    @Slot()
    def run(self):
        try:
            self.signals.result.emit(analyse_and_store(self.path, ReferenceRepository(self.repository_path))[0])
        except Exception as exc:  # defensive GUI boundary
            self.signals.error.emit(str(exc))
        finally:
            self.signals.finished.emit()


class MainWindow(QMainWindow):
    TAB_NAMES = ("Übersicht", "Konto", "Depot", "Buchungen", "Geldflüsse",
                 "Gebühren & Kosten", "Steuern", "Referenzvergleich", "Issues")

    def __init__(self, repository_path: str | Path | None = None):
        super().__init__()
        self.setWindowTitle("Portman PDF Lab")
        self.resize(1500, 900)
        self.thread_pool = QThreadPool.globalInstance()
        self.workers: set[AnalysisWorker] = set()
        self.documents: dict[str, dict] = {}
        self.current_pdf: Path | None = None
        data_dir = Path(QStandardPaths.writableLocation(QStandardPaths.AppLocalDataLocation))
        self.repository_path = Path(repository_path) if repository_path else data_dir / "reference.sqlite"
        self.current_run_id: int | None = None
        self.cancel_requested = False
        self._build_ui()

    def _build_ui(self):
        toolbar = QToolBar("Dokumente", self); self.addToolBar(toolbar)
        open_action = QAction("PDF öffnen", self); open_action.triggered.connect(self.open_pdf_dialog)
        toolbar.addAction(open_action)
        batch_action = QAction("Ordner analysieren", self); batch_action.triggered.connect(self.open_directory_dialog)
        toolbar.addAction(batch_action)
        cancel_action = QAction("Abbrechen", self); cancel_action.triggered.connect(self.cancel_batch); toolbar.addAction(cancel_action)
        approve_action = QAction("Freigeben", self); approve_action.triggered.connect(lambda: self.review_current(ReviewStatus.APPROVED)); toolbar.addAction(approve_action)
        reject_action = QAction("Korrektur nötig", self); reject_action.triggered.connect(lambda: self.review_current(ReviewStatus.NEEDS_CORRECTION)); toolbar.addAction(reject_action)
        self.progress = QProgressBar(); self.progress.setVisible(False); toolbar.addWidget(self.progress)

        root = QSplitter(Qt.Horizontal)
        left = QWidget(); left_layout = QVBoxLayout(left)
        self.search = QLineEdit(); self.search.setPlaceholderText("Dokumente filtern …")
        self.search.textChanged.connect(self._filter_documents)
        self.document_list = QListWidget(); self.document_list.currentTextChanged.connect(self._select_document)
        left_layout.addWidget(self.search); left_layout.addWidget(self.document_list)

        middle = QWidget(); middle_layout = QVBoxLayout(middle)
        nav = QHBoxLayout(); self.previous = QPushButton("◀"); self.next = QPushButton("▶")
        self.page_label = QLabel("Keine PDF"); self.zoom_out = QPushButton("−"); self.zoom_in = QPushButton("+")
        nav.addWidget(self.previous); nav.addWidget(self.next); nav.addWidget(self.page_label); nav.addStretch()
        nav.addWidget(self.zoom_out); nav.addWidget(self.zoom_in); middle_layout.addLayout(nav)
        if QPdfView:
            self.pdf_document = QPdfDocument(self); self.pdf_view = QPdfView(); self.pdf_view.setDocument(self.pdf_document)
            middle_layout.addWidget(self.pdf_view)
            self.previous.clicked.connect(lambda: self.go_to_page(self.pdf_view.pageNavigator().currentPage() - 1))
            self.next.clicked.connect(lambda: self.go_to_page(self.pdf_view.pageNavigator().currentPage() + 1))
            self.zoom_in.clicked.connect(lambda: self.pdf_view.setZoomFactor(self.pdf_view.zoomFactor() * 1.2))
            self.zoom_out.clicked.connect(lambda: self.pdf_view.setZoomFactor(self.pdf_view.zoomFactor() / 1.2))
        else:
            self.pdf_document = None; self.pdf_view = QTextEdit(); self.pdf_view.setReadOnly(True)
            middle_layout.addWidget(self.pdf_view)
        self.evidence_excerpt = QTextEdit(); self.evidence_excerpt.setReadOnly(True); self.evidence_excerpt.setMaximumHeight(100)
        self.evidence_excerpt.setPlaceholderText("Textfundstelle"); middle_layout.addWidget(self.evidence_excerpt)

        self.tabs = QTabWidget(); self.tables = {}
        for name in self.TAB_NAMES:
            table = QTableWidget(0, 2); table.setHorizontalHeaderLabels(("Feld", "Wert"))
            table.cellClicked.connect(self._field_clicked); self.tables[name] = table; self.tabs.addTab(table, name)
            table.setSelectionMode(QTableWidget.ExtendedSelection)
        self.tables["Referenzvergleich"].cellDoubleClicked.connect(self._edit_reference)
        root.addWidget(left); root.addWidget(middle); root.addWidget(self.tabs); root.setSizes((280, 720, 500))
        self.setCentralWidget(root); self.statusBar().showMessage("Bereit")

    @Slot()
    def open_pdf_dialog(self):
        path, _ = QFileDialog.getOpenFileName(self, "PDF öffnen", "", "PDF (*.pdf)")
        if path: self.analyse(Path(path))

    @Slot()
    def open_directory_dialog(self):
        path = QFileDialog.getExistingDirectory(self, "PDF-Ordner wählen")
        if not path: return
        files = sorted(Path(path).rglob("*.pdf")); self.cancel_requested = False
        self.progress.setRange(0, len(files)); self.progress.setValue(0); self.progress.setVisible(True)
        for item in files: self.analyse(item)

    def cancel_batch(self):
        self.cancel_requested = True; self.thread_pool.clear(); self.progress.setVisible(False)
        self.statusBar().showMessage("Batchanalyse abgebrochen", 3000)

    def analyse(self, path: Path):
        self.statusBar().showMessage(f"Analysiere {path.name} …")
        worker = AnalysisWorker(path, self.repository_path); self.workers.add(worker)
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
        self.load_pdf(self.current_pdf); self.show_report(self.documents[key])

    def review_current(self, status: ReviewStatus):
        if self.current_run_id is None:
            self.statusBar().showMessage("Kein gespeicherter Parserlauf ausgewählt", 3000); return
        ReferenceRepository(self.repository_path).review(self.current_run_id, "overall", status,
                                                         "GUI user", "Manual GUI decision")
        self.statusBar().showMessage(f"Reviewstatus: {status.value}", 3000)

    def load_pdf(self, path: Path):
        if self.pdf_document:
            self.pdf_document.load(str(path)); self.go_to_page(0)
        else:
            document = extract_pdf(path); self.pdf_view.setPlainText("\n\n".join(page.text for page in document.pages))
            self.page_label.setText(f"{len(document.pages)} Seite(n)")

    def go_to_page(self, page_index: int):
        if not self.pdf_document: return
        count = self.pdf_document.pageCount()
        if count and 0 <= page_index < count:
            self.pdf_view.pageNavigator().jump(page_index, self.pdf_view.pageNavigator().currentLocation(), 0)
            self.page_label.setText(f"Seite {page_index + 1} / {count}")

    def show_report(self, report: dict):
        result = report.get("result", {})
        mapping = {
            "Übersicht": {"Dokument": report.get("document_id"), "Parser": result.get("plugin_id"), "Handler": result.get("handler_id")},
            "Konto": result.get("accounts", []), "Depot": result.get("depots", []) + result.get("depot_snapshots", []),
            "Buchungen": result.get("events", []), "Geldflüsse": [m for e in result.get("events", []) for m in e.get("cash_movements", [])],
            "Gebühren & Kosten": [f for e in result.get("events", []) for f in e.get("fee_events", [])],
            "Steuern": [t for e in result.get("events", []) for t in e.get("tax_events", [])],
            "Referenzvergleich": report.get("parser_comparison", {}).get("rows", []) + report.get("reference_comparison", []), "Issues": report.get("issues", []),
        }
        evidence = {item["evidence_id"]: item for item in result.get("evidence", [])}
        for name, data in mapping.items():
            table = self.tables[name]; rows = list(data.items()) if isinstance(data, dict) else [(str(i + 1), item) for i, item in enumerate(data)]
            table.setRowCount(len(rows))
            for row, (field, value) in enumerate(rows):
                field_item = QTableWidgetItem(str(field)); value_item = QTableWidgetItem(json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else str(value or ""))
                ids = value.get("evidence_ids", []) if isinstance(value, dict) else []
                if ids and ids[0] in evidence:
                    value_item.setData(Qt.UserRole, evidence[ids[0]])
                table.setItem(row, 0, field_item); table.setItem(row, 1, value_item)
            table.resizeColumnsToContents()

    def _field_clicked(self, row: int, column: int):
        table = self.sender(); item = table.item(row, 1) if table else None
        evidence = item.data(Qt.UserRole) if item else None
        if evidence:
            self.go_to_page(int(evidence["page_number"]) - 1)
            self.evidence_excerpt.setPlainText(evidence.get("excerpt", ""))

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
