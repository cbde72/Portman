import os
from pathlib import Path
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QApplication, QSplitter

from portman_pdf_lab.application.pdf_analysis import analyse_pdf
from portman_pdf_lab.storage import ReferenceRepository
from portman_pdf_lab.synthetic_pdf import create_demo_pdf
from portman_pdf_lab.ui.main_window import MainWindow
from portman_pdf_lab.ui.result_view import RecognitionStatus


MARKING_TEXT = """comdirect
Wertpapierkauf
Stk. 0,125 Beispiel ETF, WKN / ISIN: ABC123 / DE0008474511
Valuta 04.02.2026
Zu Ihren Lasten EUR 126,50
Neues Layoutmerkmal TRAIN42"""


def app():
    return QApplication.instance() or QApplication([])


def stored_report(tmp_path):
    """Create a demo PDF plus a persisted parser run for the GUI."""
    path = create_demo_pdf(tmp_path / "markings.pdf", MARKING_TEXT)
    report = analyse_pdf(path, "STANDARD")
    detection = report["detection"]
    repository = ReferenceRepository(tmp_path / "markings.sqlite")
    document_id = repository.register_document(report["document_id"], report["source_hash"], str(path),
                                               detection["plugin_id"], detection["document_type"])
    report["run_id"] = repository.save_run(
        document_id, detection["plugin_id"], detection["handler_id"], detection["plugin_version"],
        report["result"]["schema_version"], report["result"], report.get("issues", []),
        report["timings"]["total_ns"])
    return path, report


def marking_window(tmp_path, settings=None):
    application = app()
    path, report = stored_report(tmp_path)
    if settings is None:
        settings = QSettings(str(tmp_path / "gui-settings.ini"), QSettings.IniFormat)
    window = MainWindow(tmp_path / "markings.sqlite", settings)
    window.documents[str(path)] = report
    window.document_list.addItem(str(path))
    window.document_list.setCurrentRow(0)
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and (not window.pdf_document or window.pdf_document.pageCount() < 1):
        application.processEvents()
    application.processEvents()
    window.refresh_pdf_markings()
    return window, path, report


def test_gui_smoke_has_three_panes_and_required_tabs():
    application = app(); window = MainWindow()
    assert isinstance(window.centralWidget(), QSplitter)
    assert window.centralWidget().count() == 3
    assert [window.tabs.tabText(i) for i in range(window.tabs.count())] == list(window.TAB_NAMES)
    window.close(); application.processEvents()


def test_parser_training_tab_has_four_areas_and_binds_fields(tmp_path):
    application = app(); window = MainWindow(tmp_path / "training.sqlite")
    assert window.tabs.tabText(window.tabs.count() - 1) == "Parsertraining"
    report = {"document_id":"doc", "source":"synthetic.pdf", "detection":{"plugin_id":"user.comdirect-ertraege","document_type":"Kauf"},
              "result":{"plugin_id":"user.comdirect-ertraege","plugin_version":"2.0","handler_id":"wertpapierkauf",
                        "attributes":{},"events":[{"event_id":"event","cash_movements":[]}],"evidence":[{"excerpt":"Zu Ihren Lasten EUR 10,00"}]}, "issues":[]}
    window.training_widget.bind_report(report, "synthetic.pdf")
    assert window.training_widget.documents.rowCount() == 1
    assert window.training_widget.fields.rowCount() > 0
    assert "Zu Ihren Lasten" in window.training_widget.source_text.toPlainText()
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


# -- evidence-driven markings ------------------------------------------------

def test_gui_marks_recognized_values_and_not_technical_null_links(tmp_path):
    application = app(); window, path, report = marking_window(tmp_path)
    try:
        assert window._current_markings
        assert any(item.status == RecognitionStatus.RECOGNIZED and item.quads
                   for item in window._current_markings)
        # A printed value is highlighted with coordinates; the text layer uses
        # the same span but is explicitly a fallback.
        isin = next(item for item in window._current_markings
                    if item.field_path == "events[0].trades[0].isin")
        assert isin.text == "DE0008474511" and isin.quads and not isin.fallback
        assert not any(item.field_path.endswith("linked_security_movement_id")
                       for item in window._current_markings)
        assert window._layer_markings and all(item.fallback for item in window._layer_markings)
        assert any(extra.format.underlineStyle() for extra in window.pdf_text_layer.extraSelections())
    finally:
        window.close(); application.processEvents()


def test_gui_marking_toolbar_scopes_and_persists(tmp_path):
    application = app(); settings_file = tmp_path / "markings.ini"
    settings = QSettings(str(settings_file), QSettings.IniFormat)
    window, _path, _report = marking_window(tmp_path, settings)
    try:
        assert window.markings_enabled.isChecked()
        assert window.marking_scope.currentText() == "Alle erkannten Felder"

        window.markings_enabled.setChecked(False)
        assert window.pdf_view.canvas._visible_markings() == []
        assert window.pdf_text_layer.field_markings == []

        window.markings_enabled.setChecked(True)
        window.marking_scope.setCurrentText("Nur ausgewähltes Feld")
        path = window._current_markings[0].field_path
        window._selected_field_path = path
        window._apply_marking_visibility()
        assert window.pdf_view.canvas._visible_markings()
        assert all(item.field_path == path for item in window.pdf_view.canvas._visible_markings())
        assert all(item.field_path == path for item in window.pdf_text_layer.field_markings)

        window.marking_scope.setCurrentText("Markierungen ausblenden")
        assert window.pdf_view.canvas._visible_markings() == []
        assert window.pdf_text_layer.field_markings == []

        window.markings_enabled.setChecked(True)
        window.marking_scope.setCurrentText("Nur ausgewähltes Feld")
    finally:
        window.close(); application.processEvents()

    restored = QSettings(str(settings_file), QSettings.IniFormat)
    second = MainWindow(tmp_path / "markings.sqlite", restored)
    try:
        assert second.markings_enabled.isChecked()
        assert second.marking_scope.currentText() == "Nur ausgewähltes Feld"
    finally:
        second.close(); application.processEvents()


def test_gui_marker_click_and_sorted_table_row_navigate_without_recursion(tmp_path):
    application = app(); window, _path, _report = marking_window(tmp_path)
    try:
        marker = next(item for item in window._current_markings
                      if item.field_path == "events[0].trades[0].isin")
        window._markings_activated([marker])
        application.processEvents()
        assert window._selected_field_path == marker.field_path
        assert window.current_page_index == marker.page_number - 1
        assert any(table.currentRow() >= 0 and table.item(table.currentRow(), 0)
                   and table.item(table.currentRow(), 0).text() == marker.field_path
                   for table in tuple(window.tables.values()) + (window.training_widget.fields,))
        assert window._navigating is False

        table = window.tables["Buchungen"]
        assert table.rowCount() > 0
        table.sortItems(1, Qt.DescendingOrder)
        application.processEvents()
        row = next(row for row in range(table.rowCount())
                   if table.item(row, 0) and table.item(row, 0).data(Qt.UserRole))
        display = table.item(row, 0).data(Qt.UserRole)
        window._field_activated(display)
        application.processEvents()
        assert window._selected_field_path == display.path
        assert window._navigating is False
    finally:
        window.close(); application.processEvents()


def test_gui_training_table_always_has_all_cells_and_editable_reference(tmp_path):
    application = app(); window, path, report = marking_window(tmp_path)
    try:
        catalog = window._catalog()
        window.training_widget.bind_report(report, path, catalog)
        table = window.training_widget.fields
        assert table.rowCount() > 0
        for row in range(table.rowCount()):
            for column in range(9):
                assert table.item(row, column) is not None
            # Selecting every row, including catalog-only missing fields, must
            # never raise the former NoneType.text AttributeError.
            table.setCurrentCell(row, 0)
            application.processEvents()
        reference = table.item(0, 3)
        standard = table.item(0, 1)
        assert reference.flags() & Qt.ItemIsEditable
        assert not (standard.flags() & Qt.ItemIsEditable)
        assert any(display.evidence is None for display in window.training_widget._display_rows)

        missing_row = next(row for row in range(table.rowCount())
                           if window.training_widget._display_at(row) is not None
                           and window.training_widget._display_at(row).evidence is None)
        reference = table.item(missing_row, 3)
        reference.setText("Korrektur")
        application.processEvents()
        assert window.training_widget.reference_value.text() == "Korrektur"
    finally:
        window.close(); application.processEvents()


def test_marking_refresh_and_zoom_never_reparse_or_require_parser_run(tmp_path, monkeypatch):
    application = app(); window, _path, _report = marking_window(tmp_path)
    try:
        import portman_pdf_lab.ui.main_window as main_window
        monkeypatch.setattr(main_window, "extract_pdf",
                            lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("reparse")))
        before = len(window._current_markings)
        window.pdf_view.setZoomFactor(1.7)
        window.pdf_view.canvas.resize(900, 700)
        window.go_to_page(0)
        window.refresh_pdf_markings()
        application.processEvents()
        assert len(window._current_markings) == before
        assert window._pdf_text_cache
    finally:
        window.close(); application.processEvents()
