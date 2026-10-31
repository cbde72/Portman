import os
from pathlib import Path
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QSplitter

from portman_pdf_lab.synthetic_pdf import create_demo_pdf
from portman_pdf_lab.ui.main_window import MainWindow


def app():
    return QApplication.instance() or QApplication([])


def test_gui_smoke_has_three_panes_and_required_tabs():
    application = app(); window = MainWindow()
    assert isinstance(window.centralWidget(), QSplitter)
    assert window.centralWidget().count() == 3
    assert [window.tabs.tabText(i) for i in range(window.tabs.count())] == list(window.TAB_NAMES)
    window.close(); application.processEvents()


def test_pdf_navigation_loads_document_and_evidence_page(tmp_path):
    application = app(); path = create_demo_pdf(tmp_path / "demo.pdf")
    window = MainWindow(); window.load_pdf(path)
    deadline = time.monotonic() + 2
    while window.pdf_document and window.pdf_document.pageCount() < 1 and time.monotonic() < deadline:
        application.processEvents()
    if window.pdf_document:
        assert window.pdf_document.pageCount() == 1
        window.go_to_page(0)
    else:
        assert "Bank of Scotland" in window.pdf_view.toPlainText()
    window.close(); application.processEvents()


def test_report_field_evidence_is_available_for_page_jump():
    application = app(); window = MainWindow()
    report = {"document_id": "doc", "result": {"plugin_id": "fnz.finvesto", "handler_id": "depotauszug",
              "evidence": [{"evidence_id": "ev", "page_number": 1, "excerpt": "Depot-Nr. 1"}],
              "events": [{"event_id": "event", "evidence_ids": ["ev"]}], "accounts": [], "depots": [],
              "depot_snapshots": []}, "issues": []}
    window.show_report(report)
    item = window.tables["Buchungen"].item(0, 1)
    assert item.data(0x0100)["excerpt"] == "Depot-Nr. 1"
    window.close(); application.processEvents()


def test_gui_analysis_runs_in_worker_and_persists_result(tmp_path):
    application = app(); path = create_demo_pdf(tmp_path / "demo.pdf")
    window = MainWindow(tmp_path / "gui.sqlite"); window.analyse(path)
    deadline = time.monotonic() + 5
    while not window.documents and time.monotonic() < deadline:
        application.processEvents(); time.sleep(0.01)
    assert str(path) in window.documents
    assert window.documents[str(path)]["run_id"] > 0
    assert (tmp_path / "gui.sqlite").exists()
    window.thread_pool.waitForDone(); window.close(); application.processEvents()
