import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from portman_pdf_lab.field_catalog import CatalogStore
from portman_pdf_lab.ui.main_window import MainWindow


def app():
    return QApplication.instance() or QApplication([])


def window(tmp_path, name="settings.ini"):
    return MainWindow(tmp_path / "repo.sqlite", QSettings(str(tmp_path / name), QSettings.IniFormat))


def test_fresh_install_starts_quick_and_expert_restores_all_tabs(tmp_path):
    application = app(); value = window(tmp_path)
    assert value.ui_mode.currentText() == "Schnell"
    visible = [value.tabs.isTabVisible(i) for i in range(value.tabs.count())]
    assert sum(visible) == 1 and value.tabs.currentWidget() is value.field_analysis
    value.ui_mode.setCurrentText("Experte")
    assert all(value.tabs.isTabVisible(i) for i in range(value.tabs.count()))
    assert [value.tabs.tabText(i) for i in range(value.tabs.count())] == list(value.TAB_NAMES)
    value.close(); application.processEvents()


def test_mode_switch_keeps_state_inputs_zoom_and_does_not_parse(tmp_path, monkeypatch):
    application = app(); value = window(tmp_path)
    value.search.setText("ungespeichert"); value.training_widget.reference_value.setText("12,34")
    if hasattr(value.pdf_view, "setZoomFactor"): value.pdf_view.setZoomFactor(1.7)
    calls = []; monkeypatch.setattr(value, "analyse", lambda path: calls.append(path))
    value.ui_mode.setCurrentText("Experte"); value.ui_mode.setCurrentText("Schnell")
    assert not calls and value.search.text() == "ungespeichert"
    assert value.training_widget.reference_value.text() == "12,34"
    assert abs(value.pdf_view.zoomFactor() - 1.7) < 0.01
    value.close(); application.processEvents()


def test_mode_persists_and_both_modes_share_repository(tmp_path):
    application = app(); first = window(tmp_path); first.ui_mode.setCurrentText("Experte")
    first.close(); application.processEvents()
    second = window(tmp_path)
    assert second.ui_mode.currentText() == "Experte"
    assert second.training_widget.repository_path == second.field_analysis.repository_path == second.repository_path
    second.close(); application.processEvents()


def test_quick_mode_hides_missing_optional_but_keeps_required(tmp_path):
    application = app(); value = window(tmp_path); value.catalog_store = CatalogStore(tmp_path / "catalogs")
    report = {"document_id":"doc", "detection":{"plugin_id":"user.comdirect-ertraege","document_type":"comdirect Wertpapierkauf"},
              "result":{"plugin_id":"user.comdirect-ertraege","plugin_version":"2.0","handler_id":"wertpapierkauf",
                        "events":[{"trades":[{"isin":"DE0008474511"}]}],"evidence":[]}}
    value.field_analysis.bind_report(report, value.catalog_store.catalog("comdirect", "user.comdirect-ertraege", "comdirect Wertpapierkauf", "*"))
    value.field_analysis.set_quick_mode(True)
    rows = [(value.field_analysis.table.row_at(i), value.field_analysis.table.isRowHidden(i))
            for i in range(value.field_analysis.table.rowCount())]
    quantity = next(hidden for row, hidden in rows if row.field_id == "trade.quantity")
    venue = next(hidden for row, hidden in rows if row.field_id == "trade.venue")
    assert quantity is False and venue is True
    value.field_analysis.show_all.setChecked(True)
    venue_row = next(i for i in range(value.field_analysis.table.rowCount())
                     if value.field_analysis.table.row_at(i).field_id == "trade.venue")
    assert not value.field_analysis.table.isRowHidden(venue_row)
    value.close(); application.processEvents()
