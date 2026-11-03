import os
import time
from copy import deepcopy

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from portman_pdf_lab.application.reference_service import analyse_and_store
from portman_pdf_lab.field_catalog import CatalogStore
from portman_pdf_lab.storage import ReferenceRepository
from portman_pdf_lab.synthetic_pdf import create_demo_pdf
from portman_pdf_lab.ui.direct_pdf_view import PdfCoordinateSelection
from portman_pdf_lab.ui.main_window import MainWindow


TEXT = """comdirect
Wertpapierkauf
Stk. 1 Beispiel ETF, WKN / ISIN: ABC123 / DE0008474511
Geschäftstag 04.02.2026
Zu Ihren Lasten EUR 126,50
Handelsplatz: XETRA"""


def app(): return QApplication.instance() or QApplication([])


def prepared(tmp_path):
    pdf = create_demo_pdf(tmp_path / "quick.pdf", TEXT); repository = ReferenceRepository(tmp_path / "quick.sqlite")
    report, _ = analyse_and_store(pdf, repository)
    window = MainWindow(repository.path, QSettings(str(tmp_path / "quick.ini"), QSettings.IniFormat))
    window.catalog_store = CatalogStore(tmp_path / "catalogs")
    window.documents[str(pdf)] = report; window.document_list.addItem(str(pdf)); window.document_list.setCurrentRow(0)
    deadline = time.monotonic() + 3
    while window.pdf_document.pageCount() < 1 and time.monotonic() < deadline: app().processEvents()
    window.refresh_field_analysis()
    return window, repository, pdf


def test_complete_quick_training_stays_in_field_analysis_and_separates_release(tmp_path, monkeypatch):
    application = app(); window, repository, pdf = prepared(tmp_path)
    try:
        assert window.ui_mode.currentText() == "Schnell"
        # A field the parser genuinely cannot extract: annotations must not
        # turn it into a recognised value on their own.
        venue = window.field_analysis.row_for_path("events[0].trades[0].gross_amount")
        assert venue.status.value != "ERKANNT"
        window._start_field_training(venue)
        assert window.tabs.currentWidget() is window.field_analysis and not window.quick_training.isHidden()
        assert window.quick_training.context.parser_id == "user.comdirect-ertraege"
        assert window.quick_training.context.field_path == venue.path

        start = window.page_texts[1].index("XETRA")
        selection = PdfCoordinateSelection(1, "XETRA", start, start + 5,
            {"coordinate_system":"PDF_POINTS", "quads":[[[10,10],[30,10],[30,20],[10,20]]],
             "page_width":612, "page_height":792, "rotation":0, "start_index":start, "end_index":start+5})
        window._pdf_selection_changed(selection)
        assert window.quick_training.pdf_text.text() == "XETRA" and window.quick_training.step == 2
        window.quick_training.confirm.click(); application.processEvents()

        run = repository.run(window.current_run_id); annotations = repository.annotations_for_document(run["document_id"])
        annotation = next(item for item in annotations if item["field_path"] == venue.path)
        assert annotation["reference_value"] == "XETRA" and annotation["coordinates"]["quads"]
        assert annotation["original_text"] == "Handelsplatz: XETRA"
        assert window.quick_candidate_id and window.quick_training.step == 3
        # A reference/annotation does not invent a successful parser value.
        window.refresh_field_analysis(); assert window.field_analysis.row_for_path(venue.path).status.value != "ERKANNT"

        window._quick_test_rule(); assert window.quick_training.step == 4
        window._quick_approve_rule(); assert window.quick_version_id and window.quick_training.step == 5
        assert not repository.profile_activations_for(run["plugin_id"], run["handler_id"])
        window._quick_activate_rule()
        assert any(item["active"] for item in repository.profile_activations_for(run["plugin_id"], run["handler_id"]))

        extended = deepcopy(window.field_analysis.report)
        extended["rule_mode_effective"] = "EXTENDED"
        extended["rule_decisions"] = [{"field_path":venue.path, "effective_value":"XETRA",
                                         "provenance":"rule-profile:test", "conflict":False}]
        window.field_analysis.bind_report(extended, window._catalog())
        assert window.field_analysis.row_for_path(venue.path).status.value == "ERKANNT"

        calls = []; monkeypatch.setattr(window, "analyse", lambda path, mode=None: calls.append((path, mode)))
        window._quick_recheck(); assert calls == [(pdf, "EXTENDED")]
        assert window.tabs.currentWidget() is window.field_analysis
    finally:
        window.close(); application.processEvents()


def test_quick_training_cancel_and_mode_switch_preserve_panel_state(tmp_path):
    application = app(); window, _repository, _pdf = prepared(tmp_path)
    try:
        venue = window.field_analysis.row_for_path("events[0].trades[0].security_name")
        window._start_field_training(venue); context = window.quick_training.context
        window.ui_mode.setCurrentText("Experte")
        assert window.quick_training.context is context and window.quick_training.isHidden()
        window.ui_mode.setCurrentText("Schnell")
        assert not window.quick_training.isHidden() and window.quick_training.context is context
        window._quick_cancel(); assert not window.quick_training.active and not window.quick_training.isVisible()
    finally:
        window.close(); application.processEvents()
