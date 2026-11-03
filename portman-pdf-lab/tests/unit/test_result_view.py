import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication, QFileDialog

from portman_pdf_lab.ui.main_window import MainWindow
from portman_pdf_lab.ui.result_view import RecognitionStatus, StructuredResultView, flatten_result


def app():
    return QApplication.instance() or QApplication([])


def test_flatten_nested_lists_is_lossless_and_preserves_zero_false_null():
    source = {"amount": "0.00", "zero": 0, "flag": False, "missing": None,
              "fees": [{"amount": "1.2300", "currency": "EUR"}], "empty": ""}
    rows = {row.path: row for row in flatten_result(source)}
    assert set(rows) == {"amount", "zero", "flag", "missing", "fees[0].amount", "fees[0].currency", "empty"}
    assert rows["zero"].value == 0 and rows["flag"].value is False
    assert rows["missing"].status == RecognitionStatus.MISSING
    assert rows["amount"].value == "0.00" and rows["fees[0].amount"].value == "1.2300"


def test_status_uses_evidence_conflict_and_not_applicable():
    evidence = {"ev": {"evidence_id": "ev", "page_number": 2, "excerpt": "Wert 0"}}
    rows = {row.path: row for row in flatten_result({
        "proven": {"value": 0, "evidence_ids": ["ev"]},
        "uncertain": {"value": False},
        "conflict": {"value": "A", "conflict": True, "evidence_ids": ["ev"]},
        "expected": {"status": "EXPECTED", "amount": "5.00", "currency": "EUR", "evidence_ids": ["ev"]},
        "na": {"status": "NOT_APPLICABLE"},
    }, evidence)}
    assert rows["proven.value"].status == RecognitionStatus.RECOGNIZED
    assert rows["uncertain.value"].status == RecognitionStatus.REVIEW
    assert rows["conflict.value"].status == RecognitionStatus.REVIEW
    assert rows["expected.amount"].status == RecognitionStatus.REVIEW
    assert rows["expected.amount"].unit == "EUR"
    assert rows["na"].status == RecognitionStatus.NOT_APPLICABLE


def test_table_json_switch_filter_sort_and_copy_all():
    application = app(); view = StructuredResultView()
    view.set_data({"b": None, "a": {"value": 0, "evidence_ids": ["ev"]}},
                  {"ev": {"evidence_id": "ev", "page_number": 1, "excerpt": "0"}})
    assert view.table.rowCount() == 2
    assert "\"b\": null" in view.json.toPlainText()
    view.mode.setCurrentText("JSON"); assert view.stack.currentWidget() is view.json
    view.filter.setCurrentText("Nur fehlende")
    assert sum(not view.table.isRowHidden(row) for row in range(view.table.rowCount())) == 1
    view.filter.setCurrentText("Alle Felder"); view.table.copy_selection(True)
    assert "a.value" in application.clipboard().text() and "b" in application.clipboard().text()


def test_splitter_geometry_and_headers_persist(tmp_path):
    application = app(); settings_file = tmp_path / "gui.ini"
    settings = QSettings(str(settings_file), QSettings.IniFormat)
    first = MainWindow(tmp_path / "one.sqlite", settings)
    first.resize(1100, 700); first.root_splitter.setSizes((180, 430, 490))
    first.training_widget.main_splitter.setSizes((260, 440))
    first.tables["Übersicht"].horizontalHeader().resizeSection(0, 321)
    first.showMaximized(); application.processEvents(); assert first.isMaximized()
    saved_main = first.root_splitter.sizes(); saved_training = first.training_widget.main_splitter.sizes()
    first.close(); application.processEvents()
    second = MainWindow(tmp_path / "two.sqlite", QSettings(str(settings_file), QSettings.IniFormat))
    second.showMaximized(); application.processEvents()
    assert second.root_splitter.sizes() == saved_main
    assert second.training_widget.main_splitter.sizes() == saved_training
    assert second.tables["Übersicht"].horizontalHeader().sectionSize(0) == 321
    second.resize(640, 480); application.processEvents()
    assert second.centralWidget().width() > 0
    second.close(); application.processEvents()


def test_file_dialog_remembers_last_successful_directory(tmp_path, monkeypatch):
    application = app(); settings = QSettings(str(tmp_path / "dialogs.ini"), QSettings.IniFormat)
    window = MainWindow(tmp_path / "repo.sqlite", settings); selected = tmp_path / "statements" / "one.pdf"
    selected.parent.mkdir()
    starts = []
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *args: (starts.append(args[2]) or str(selected), "PDF (*.pdf)"))
    analysed = []
    monkeypatch.setattr(window, "analyse", lambda path: analysed.append(path))
    window.open_pdf_dialog()
    assert analysed == [selected]
    assert settings.value("dialogs/last-directory") == str(selected.parent)
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *args: (starts.append(args[2]) or "", ""))
    window.open_pdf_dialog()
    assert starts[-1] == str(selected.parent)
    assert settings.value("dialogs/last-directory") == str(selected.parent)
    window.close(); application.processEvents()
