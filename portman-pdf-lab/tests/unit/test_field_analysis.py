"""Field-analysis rows, training context and status semantics."""

from __future__ import annotations

import os
from types import SimpleNamespace
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QApplication

from portman_pdf_lab.application.pdf_analysis import analyse_pdf
from portman_pdf_lab.field_catalog import CatalogStore
from portman_pdf_lab.storage import ReferenceRepository
from portman_pdf_lab.synthetic_pdf import create_demo_pdf
from portman_pdf_lab.training import SafeRuleEngine
from portman_pdf_lab.ui.field_analysis import (
    FieldAnalysisWidget, build_field_analysis_rows, training_context_for_row,
)
from portman_pdf_lab.ui.field_mapping import FieldMappingDialog
from portman_pdf_lab.ui.main_window import MainWindow
from portman_pdf_lab.ui.result_view import RecognitionStatus
from portman_pdf_lab.ui.training_widget import TrainingWidget


TEXT = """comdirect
Wertpapierkauf
Stk. 0,125 Beispiel ETF, WKN / ISIN: ABC123 / DE0008474511
Valuta 04.02.2026
Zu Ihren Lasten EUR 126,50"""

VENUE_PATH = "events[0].trades[0].gross_amount"


def app():
    return QApplication.instance() or QApplication([])


def stored_document(tmp_path):
    path = create_demo_pdf(tmp_path / "analysis.pdf", TEXT)
    report = analyse_pdf(path, "STANDARD")
    detection, result = report["detection"], report["result"]
    repository = ReferenceRepository(tmp_path / "analysis.sqlite")
    document_id = repository.register_document(
        report["document_id"], report["source_hash"], str(path),
        detection["plugin_id"], detection["document_type"])
    report["run_id"] = repository.save_run(
        document_id, detection["plugin_id"], detection["handler_id"],
        detection["plugin_version"], result["schema_version"], result,
        report.get("issues", []), report["timings"]["total_ns"])
    catalog = CatalogStore(tmp_path / "catalogs").catalog(
        "comdirect", result["plugin_id"], detection["document_type"],
        result.get("attributes", {}).get("layout_path", "*"))
    return path, report, repository, catalog, document_id


def row_for(rows, path):
    return next(row for row in rows if row.path == path)


def test_rows_cover_catalog_required_optional_and_empty_inputs(tmp_path):
    _path, report, _repo, catalog, _document_id = stored_document(tmp_path)
    rows = build_field_analysis_rows(report, catalog)
    paths = {row.path for row in rows}
    assert {definition.path for definition in catalog.visible_fields()} <= paths

    isin = row_for(rows, "events[0].trades[0].isin")
    assert isin.status == RecognitionStatus.RECOGNIZED
    assert isin.evidence and isin.page
    assert isin.parser_rule == ""  # no rule candidate, not the handler id

    venue = row_for(rows, VENUE_PATH)
    assert venue.requirement == "OPTIONAL"
    assert venue.status in {RecognitionStatus.NOT_APPLICABLE, RecognitionStatus.REVIEW, RecognitionStatus.RECOGNIZED}

    # The catalog-only required field has no parser value but is still visible.
    required = next(row for row in rows
                    if row.requirement == "REQUIRED" and not row.extracted)
    assert required.status == RecognitionStatus.MISSING
    assert required.status_text == "Fehlt / nicht extrahiert"

    assert build_field_analysis_rows(None, None) == []
    assert build_field_analysis_rows({"result": None}, None) == []
    fallback = build_field_analysis_rows({"result": {"amount": None, "zero": 0}}, None)
    assert {row.path for row in fallback} == {"amount", "zero"}
    assert row_for(fallback, "zero").status == RecognitionStatus.REVIEW
    assert row_for(fallback, "amount").status == RecognitionStatus.MISSING


def test_training_context_contains_document_parser_field_evidence_and_versions(tmp_path):
    path, report, _repo, catalog, document_id = stored_document(tmp_path)
    rows = build_field_analysis_rows(report, catalog)
    isin = row_for(rows, "events[0].trades[0].isin")
    context = training_context_for_row(isin, report, report["source_hash"],
                                       catalog.version, 7)
    assert context.document_id == document_id
    assert context.document_hash == report["source_hash"]
    assert context.parser_id == "user.comdirect-ertraege"
    assert context.handler_id == "wertpapierkauf"
    assert context.document_type == "comdirect Wertpapierkauf"
    assert context.bank == "comdirect"
    assert context.rule_mode == "STANDARD"
    assert context.field_path == isin.path and context.field_id == isin.field_id
    assert context.requirement == isin.requirement
    assert context.current_value == isin.value
    assert context.page_number == 1
    assert context.original_text == (isin.evidence or {}).get("excerpt")
    assert context.catalog_version == catalog.version
    assert context.rule_profile_version == 7
    assert context.report == report
    assert context.has_document

    selection = SimpleNamespace(page_number=1, text="Handelsplatz: XETRA",
                                coordinates={"coordinate_system": "PDF_POINTS", "quads": []})
    enriched = context.with_selection(selection)
    assert enriched.original_text == "Handelsplatz: XETRA"
    assert enriched.page_number == 1
    assert enriched.coordinates == selection.coordinates


def test_annotation_and_candidate_never_change_parser_recognition(tmp_path):
    _path, report, repository, catalog, document_id = stored_document(tmp_path)
    venue = row_for(build_field_analysis_rows(report, catalog), VENUE_PATH)
    assert venue.requirement == "OPTIONAL"

    annotation_id = repository.create_annotation(
        document_id, "user.comdirect-ertraege", "wertpapierkauf", 1,
        "Handelsplatz: XETRA", VENUE_PATH, "XETRA", "TEXT", "CONFIRMED",
        "APPROVED", "tester")
    rows = build_field_analysis_rows(
        report, catalog, repository.annotations_for_document(document_id))
    annotated = row_for(rows, VENUE_PATH)
    assert annotated.annotation_id == annotation_id
    assert annotated.reference_value == "XETRA"
    assert annotated.training_status == "Annotation"
    assert annotated.status == venue.status

    candidate = {"candidate_id": 41, "status": "APPROVED",
                 "rule": {"field_path": VENUE_PATH, "rule_id": "annotation-1"}}
    rows = build_field_analysis_rows(
        report, catalog, repository.annotations_for_document(document_id), [candidate])
    approved = row_for(rows, VENUE_PATH)
    assert approved.training_status == "Freigegeben"
    assert approved.candidate_id == 41
    assert approved.status == venue.status

    rows = build_field_analysis_rows(
        report, catalog, repository.annotations_for_document(document_id),
        [candidate], [{"active": 1, "profile_version": 3}])
    active = row_for(rows, VENUE_PATH)
    assert active.training_status == "Freigegeben · Profil aktiv"
    assert active.status == venue.status  # annotation does not rewrite the parser result

    absent = repository.create_annotation(
        document_id, "user.comdirect-ertraege", "wertpapierkauf", 1, "",
        "events[0].trades[0].security_name", None, "MISSING", "MISSING",
        "APPROVED", "tester")
    rows = build_field_analysis_rows(
        report, catalog, repository.annotations_for_document(document_id))
    missing = row_for(rows, "events[0].trades[0].security_name")
    assert missing.annotation_id == absent
    assert missing.status == RecognitionStatus.MISSING
    assert missing.status_text == "Nachweislich nicht im PDF vorhanden"


def test_venue_rule_is_label_based_not_hard_coded_to_xetra():
    engine = SafeRuleEngine()
    rule = engine.suggest({"annotation_id": 5, "field_path": VENUE_PATH,
                           "original_text": "Handelsplatz: XETRA",
                           "reference_value": "XETRA", "annotation_kind": "TEXT"})
    assert rule["rule_type"] == "REGEX_FIELD"
    assert "XETRA" not in rule["pattern"]
    assert engine.execute(rule, "Handelsplatz: Tradegate") == "Tradegate"
    assert engine.execute(rule, "Handelsplatz: Frankfurt") == "Frankfurt"


def test_field_analysis_table_and_training_widget_handoff(tmp_path):
    application = app()
    path, report, repository, catalog, document_id = stored_document(tmp_path)
    widget = FieldAnalysisWidget(tmp_path / "analysis.sqlite")
    widget.bind_report(report, catalog)
    assert widget.rows
    assert widget.document_id == document_id

    venue = row_for(widget.rows, VENUE_PATH)
    widget.table.sortItems(1, Qt.DescendingOrder)
    widget.filter.setCurrentText("Nur erkannte")
    application.processEvents()
    assert widget.table.rowCount() > 0
    assert widget.table.row_at(0) is not None

    widget.filter.setCurrentText("Alle Felder")
    assert widget.select_field_path(VENUE_PATH)
    assert widget.selected_row().path == VENUE_PATH

    context = widget.training_context(venue)
    assert context is not None and context.field_path == VENUE_PATH
    training = TrainingWidget(tmp_path / "analysis.sqlite")
    training.apply_training_context(context, catalog, path)
    assert training.context.field_path == VENUE_PATH
    assert training.field_path.text() == VENUE_PATH
    assert training.parser.currentText() == "user.comdirect-ertraege"
    assert training.context_label.text()
    assert training.reference_value.text() in {"", str(venue.value)}

    selection = SimpleNamespace(
        page_number=1, text="Handelsplatz: XETRA",
        coordinates={"coordinate_system": "PDF_POINTS",
                     "quads": [[[10, 20], [30, 20], [30, 40], [10, 40]]]})
    training.apply_pdf_selection(selection)
    assert training.reference_value.text() == "XETRA"
    training.assign_selection()
    annotation = repository.annotation(training.annotation_id)
    assert annotation["field_path"] == VENUE_PATH
    assert annotation["reference_value"] == "XETRA"
    assert annotation["original_text"] == "Handelsplatz: XETRA"
    assert annotation["page_number"] == 1
    assert annotation["coordinates"]["coordinate_system"] == "PDF_POINTS"
    assert annotation["decision"] == "CONFIRMED"

    # The annotation is visible in the analysis but never turns the row green.
    widget.refresh_from_repository()
    assert row_for(widget.rows, VENUE_PATH).status == venue.status


def test_field_mapping_dialog_preselects_the_requested_field(tmp_path):
    application = app()
    _path, _report, _repository, catalog, _document_id = stored_document(tmp_path)
    store = CatalogStore(tmp_path / "catalogs")
    dialog = FieldMappingDialog(catalog, store, {"bank": "comdirect"}, "XETRA", 1,
                                preselect=VENUE_PATH)
    assert dialog.current_definition().path == VENUE_PATH
    dialog.close()
    application.processEvents()


def test_main_window_field_analysis_tab_and_training_navigation(tmp_path):
    application = app()
    path, report, _repository, _catalog, _document_id = stored_document(tmp_path)
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.IniFormat)
    window = MainWindow(tmp_path / "analysis.sqlite", settings)
    # Keep the test independent from catalogs a user may have created in the
    # real application data directory.
    window.catalog_store = CatalogStore(tmp_path / "ui-catalogs")
    try:
        names = [window.tabs.tabText(index) for index in range(window.tabs.count())]
        assert names == list(window.TAB_NAMES)
        assert names.index("Feldanalyse") + 1 == names.index("Parsertraining")
        window.documents[str(path)] = report
        window.document_list.addItem(str(path))
        window.document_list.setCurrentRow(0)
        deadline = time.monotonic() + 5
        while (time.monotonic() < deadline and
               (not window.pdf_document or window.pdf_document.pageCount() < 1)):
            application.processEvents()
        application.processEvents()
        window.refresh_pdf_markings()
        assert window.field_analysis.rows

        row = window.field_analysis.row_for_path("events[0].trades[0].isin")
        window.ui_mode.setCurrentText("Experte")
        window._start_field_training(row)
        application.processEvents()
        assert window.tabs.currentWidget() is window.training_widget
        assert window.training_widget.context.field_path == row.path
        assert window.training_widget.field_path.text() == row.path

        window.training_widget.return_to_analysis()
        application.processEvents()
        assert window.tabs.currentWidget() is window.field_analysis
        assert window.field_analysis.selected_row().path == row.path

        # A PDF green marker reveals the same row even after the table was sorted.
        window.field_analysis.table.sortItems(1, Qt.AscendingOrder)
        marker = next(item for item in window._current_markings
                      if item.field_path == "events[0].trades[0].isin")
        window._markings_activated([marker])
        application.processEvents()
        assert window.tabs.currentWidget() is window.field_analysis
        assert window.field_analysis.selected_row().path == marker.field_path
        assert window._navigating is False
    finally:
        window.close()
        application.processEvents()


def test_dividend_identity_fields_are_independent_and_visible_in_field_analysis(tmp_path):
    catalog = CatalogStore(tmp_path).catalog("comdirect", "user.comdirect-ertraege", "comdirect Dividendengutschrift", "*")
    result = {"events": [{"security_name": "Example-ETF Inhaber-Anteile o.N.",
                           "security_wkn": "A1B2C3", "security_isin": "DE000A1B2C35"}]}
    rows = {row.path: row for row in build_field_analysis_rows({"result": result}, catalog)}
    assert rows["events[0].security_name"].value == "Example-ETF Inhaber-Anteile o.N."
    assert rows["events[0].security_wkn"].value == "A1B2C3"
    assert rows["events[0].security_isin"].value == "DE000A1B2C35"


def stored_document(tmp_path):
    path = create_demo_pdf(tmp_path / "analysis.pdf", TEXT)
    report = analyse_pdf(path, "STANDARD")
    detection, result = report["detection"], report["result"]
    repository = ReferenceRepository(tmp_path / "analysis.sqlite")
    document_id = repository.register_document(
        report["document_id"], report["source_hash"], str(path),
        detection["plugin_id"], detection["document_type"])
    report["run_id"] = repository.save_run(
        document_id, detection["plugin_id"], detection["handler_id"],
        detection["plugin_version"], result["schema_version"], result,
        report.get("issues", []), report["timings"]["total_ns"])
    catalog = CatalogStore(tmp_path / "catalogs").catalog(
        "comdirect", result["plugin_id"], detection["document_type"],
        result.get("attributes", {}).get("layout_path", "*"))
    return path, report, repository, catalog, document_id


def row_for(rows, path):
    return next(row for row in rows if row.path == path)


