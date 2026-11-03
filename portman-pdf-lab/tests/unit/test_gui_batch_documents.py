"""Regression tests for the PDF Lab document list and read-only batch runs.

The former crash ``AttributeError: 'str' object has no attribute 'get'`` came
from a signal-signature mismatch: the worker emitted ``(path, report)`` while
the connected lambda accepted one argument, so the path string was stored as
the report.  These tests pin down the ``dict[str, dict]`` contract and the
read-only batch/CSV flow.
"""

import csv
import hashlib
import os
from pathlib import Path
import sqlite3
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from portman_pdf_lab.application.pdf_analysis import analyse_pdf
from portman_pdf_lab.synthetic_pdf import create_demo_pdf
from portman_pdf_lab.ui.main_window import MainWindow


def app():
    return QApplication.instance() or QApplication([])


def window_for(tmp_path):
    settings = QSettings(str(tmp_path / "gui-settings.ini"), QSettings.IniFormat)
    return MainWindow(tmp_path / "references.sqlite", settings)


def wait_for(application, predicate, timeout=30.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        application.processEvents()
        if predicate():
            return True
        time.sleep(0.005)
    application.processEvents()
    return predicate()


def make_pdfs(tmp_path, count):
    return [create_demo_pdf(tmp_path / f"demo-{index:02d}.pdf") for index in range(count)]


def select_row(window, application, key):
    row = next(index for index in range(window.document_list.count())
               if window.document_list.item(index).text() == key)
    window.document_list.setCurrentRow(row)
    application.processEvents()
    return row


def test_single_pdf_signal_stores_report_dict_and_selection_works(tmp_path):
    application = app(); window = window_for(tmp_path)
    path = create_demo_pdf(tmp_path / "single.pdf")
    try:
        window.analyse(path)
        assert wait_for(application, lambda: str(path) in window.documents)
        wait_for(application, lambda: window.workers == set(), timeout=10)
        report = window.documents[str(path)]
        assert isinstance(report, dict)
        assert report["run_id"] > 0
        assert window.document_list.count() == 1
        select_row(window, application, str(path))
        assert window.current_pdf == path
        assert window.current_run_id == report["run_id"]
        assert window._selecting_document is False
    finally:
        window.thread_pool.waitForDone(); window.close(); application.processEvents()


def test_multiple_documents_select_sequentially(tmp_path):
    application = app(); window = window_for(tmp_path)
    paths = make_pdfs(tmp_path, 3)
    try:
        for path in paths:
            window.analyse(path, persist=False)
            assert wait_for(application, lambda p=path: str(p) in window.documents)
        wait_for(application, lambda: window.workers == set(), timeout=10)
        assert all(isinstance(value, dict) for value in window.documents.values())
        for path in reversed(paths):
            select_row(window, application, str(path))
            assert window.current_pdf == path
            assert window._selecting_document is False
        assert window.document_list.count() == len(paths)
    finally:
        window.thread_pool.waitForDone(); window.close(); application.processEvents()


def test_batch_analyses_20_pdfs_exports_csv_and_never_writes_sqlite(
        tmp_path, monkeypatch):
    application = app(); window = window_for(tmp_path)
    paths = make_pdfs(tmp_path, 20)
    csv_path = tmp_path / "batch.csv"
    database = tmp_path / "references.sqlite"

    import portman_pdf_lab.ui.main_window as main_window
    monkeypatch.setattr(main_window, "analyse_and_store",
                        lambda *_args, **_kwargs: (_ for _ in ()).throw(
                            AssertionError("analyse_and_store must not run in batch mode")))
    try:
        window.start_batch(paths, csv_path)
        assert wait_for(application, lambda: not window._batch_active, timeout=60)
        wait_for(application, lambda: window.workers == set(), timeout=10)

        assert window.document_list.count() == 20
        assert len(window.documents) == 20
        assert all(isinstance(value, dict) for value in window.documents.values())
        assert not database.exists(), "batch mode must not create/write SQLite"

        with csv_path.open(newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            rows = list(reader)
            fields = reader.fieldnames
        assert len(rows) == 20
        assert {Path(row["source"]).name for row in rows} == {path.name for path in paths}
        assert all(row["status"] == "OK" for row in rows)
        # Technical metadata first, then every PDF-detected value; at least one
        # real field must be exported from the parser result.
        assert fields[:7] == ["source", "source_hash", "plugin_id", "handler_id",
                              "document_type", "status", "runtime_ns"]
        assert len(fields) > 7
        assert all(any(row[field] for row in rows) for field in fields[7:])
        assert (tmp_path / "fields_description.csv").exists()
    finally:
        window.thread_pool.waitForDone(); window.close(); application.processEvents()


def test_run_on_folder_automatically_exports_versioned_excel(
        tmp_path, monkeypatch):
    """Run On Folder erzeugt automatisch einen versionierten Excel-Bericht.

    Der Export passiert nach Abschluss aller Worker im Ausgabeordner (Ordner der
    PDFs), berührt die CSV nicht und schreibt nie SQLite.  Ein gesperrter oder
    bereits existierender Name führt automatisch zur nächsten Version.
    """
    openpyxl = pytest.importorskip("openpyxl")
    application = app(); window = window_for(tmp_path)
    paths = make_pdfs(tmp_path, 3)
    csv_path = tmp_path / "batch.csv"
    database = tmp_path / "references.sqlite"

    import portman_pdf_lab.ui.main_window as main_window
    monkeypatch.setattr(main_window, "analyse_and_store",
                        lambda *_args, **_kwargs: (_ for _ in ()).throw(
                            AssertionError("analyse_and_store must not run in batch mode")))
    try:
        window.start_batch(paths, csv_path)
        assert wait_for(application, lambda: not window._batch_active, timeout=60)
        wait_for(application, lambda: window.workers == set(), timeout=10)

        excel_path = tmp_path / "Portman_Parser_Kompakt_v01.xlsx"
        assert excel_path.exists(), "Excel-Bericht fehlt im Ausgabeordner"

        workbook = openpyxl.load_workbook(excel_path, read_only=True)
        try:
            names = workbook.sheetnames
            # Die Demo-PDFs sind Kontoauszüge und gehören laut Blattzuordnung
            # zu „Finanzreport“; die fachliche Trennung deckt der Unit-Test
            # mit echten Wertpapierkauf-/Dividendenberichten ab.
            sheet = workbook["Finanzreport"]
            header = [cell for cell in next(sheet.iter_rows(values_only=True))]
        finally:
            workbook.close()
        assert "Finanzreport" in names
        assert header[0] == "Datei" and "Dokumenttyp" in header

        # Der CSV-Export bleibt unverändert erhalten.
        with csv_path.open(newline="", encoding="utf-8-sig") as handle:
            rows = list(csv.DictReader(handle))
        assert len(rows) == 3

        # Kein Schreibzugriff auf die Trainings-/Referenzdatenbank.
        assert not database.exists(), "batch mode must not create/write SQLite"

        # Ein zweiter Lauf überschreibt die bestehende Datei nie.
        window.start_batch(paths, csv_path)
        assert wait_for(application, lambda: not window._batch_active, timeout=60)
        wait_for(application, lambda: window.workers == set(), timeout=10)
        assert (tmp_path / "Portman_Parser_Kompakt_v02.xlsx").exists()
        assert excel_path.exists()
    finally:
        window.thread_pool.waitForDone(); window.close(); application.processEvents()


def test_batch_analyses_many_pdfium_fallback_pdfs_without_native_crash(
        tmp_path):
    """Parallel batch workers must serialise the non-thread-safe PDFium calls.

    The former Run On Folder crash was a native Windows heap corruption
    (0xc0000374) when several workers entered PDFium through the text fallback
    at the same time.  Every synthetic PDF here forces that fallback.
    """
    pytest.importorskip("pypdfium2")
    application = app(); window = window_for(tmp_path)
    fallback_text = "SP010000 SP010000\nSAP DE0007164600\nWert 1,00 EUR"
    paths = [create_demo_pdf(tmp_path / f"fallback-{index:02d}.pdf", fallback_text)
             for index in range(16)]
    csv_path = tmp_path / "fallback-batch.csv"
    try:
        window.start_batch(paths, csv_path)
        assert wait_for(application, lambda: not window._batch_active, timeout=120)
        wait_for(application, lambda: window.workers == set(), timeout=30)

        with csv_path.open(newline="", encoding="utf-8-sig") as handle:
            rows = list(csv.DictReader(handle))
        assert len(rows) == len(paths)
        assert all(row["status"] == "OK" for row in rows)
        assert all("pdfium" in report["text_preparation"]["extractors"]
                   for report in window.documents.values())
        assert window.windowTitle() == "Portman PDF Lab"
        assert not (tmp_path / "references.sqlite").exists()
    finally:
        window.thread_pool.waitForDone(); window.close(); application.processEvents()


def test_document_selection_while_batch_is_running(tmp_path, monkeypatch):
    application = app(); window = window_for(tmp_path)
    paths = make_pdfs(tmp_path, 12)
    csv_path = tmp_path / "batch-running.csv"

    import portman_pdf_lab.ui.main_window as main_window
    real_analyse = main_window.analyse_pdf

    def slow_analyse(*args, **kwargs):
        time.sleep(0.02)
        return real_analyse(*args, **kwargs)

    monkeypatch.setattr(main_window, "analyse_pdf", slow_analyse)
    try:
        window.start_batch(paths, csv_path)
        assert wait_for(application, lambda: bool(window.documents))
        assert window._batch_active
        first_key = next(iter(window.documents))
        select_row(window, application, first_key)
        assert window.current_pdf == Path(first_key)
        # Further completed workers must not steal the user's selection.
        application.processEvents(); time.sleep(0.05); application.processEvents()
        assert window.current_pdf == Path(first_key)
        assert wait_for(application, lambda: not window._batch_active, timeout=60)
        second_key = str(paths[-1])
        select_row(window, application, second_key)
        assert window.current_pdf == paths[-1]
        assert all(isinstance(value, dict) for value in window.documents.values())
        assert not (tmp_path / "references.sqlite").exists()
    finally:
        window.thread_pool.waitForDone(); window.close(); application.processEvents()


def test_cancelled_batch_still_exports_partial_csv_and_keeps_gui_alive(tmp_path, monkeypatch):
    application = app(); window = window_for(tmp_path)
    paths = make_pdfs(tmp_path, 10)
    csv_path = tmp_path / "cancelled.csv"

    import portman_pdf_lab.ui.main_window as main_window
    real_analyse = main_window.analyse_pdf

    def slow_analyse(*args, **kwargs):
        time.sleep(0.02)
        return real_analyse(*args, **kwargs)

    monkeypatch.setattr(main_window, "analyse_pdf", slow_analyse)
    try:
        window.start_batch(paths, csv_path)
        assert wait_for(application, lambda: bool(window.documents))
        window.cancel_batch()
        assert wait_for(application, lambda: not window._batch_active, timeout=60)
        wait_for(application, lambda: window.workers == set(), timeout=10)
        assert csv_path.exists()
        with csv_path.open(newline="", encoding="utf-8-sig") as handle:
            rows = list(csv.DictReader(handle))
        assert 1 <= len(rows) <= len(paths)
        assert all(isinstance(value, dict) for value in window.documents.values())
    finally:
        window.thread_pool.waitForDone(); window.close(); application.processEvents()


def test_csv_export_error_does_not_terminate_the_gui(tmp_path):
    application = app(); window = window_for(tmp_path)
    path = create_demo_pdf(tmp_path / "export-error.pdf")
    try:
        # A directory cannot be replaced by the atomic CSV file write.
        window.start_batch([path], tmp_path)
        assert wait_for(application, lambda: not window._batch_active, timeout=60)
        wait_for(application, lambda: window.workers == set(), timeout=10)
        assert "CSV-Export fehlgeschlagen" in window.statusBar().currentMessage()
        assert window.windowTitle() == "Portman PDF Lab"
        assert isinstance(window.documents[str(path)], dict)
    finally:
        window.thread_pool.waitForDone(); window.close(); application.processEvents()


def test_parser_error_document_can_be_selected_without_crashing(tmp_path):
    application = app(); window = window_for(tmp_path)
    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"this is not a PDF")
    try:
        window.analyse(broken, persist=False)
        assert wait_for(application, lambda: str(broken) in window.documents)
        wait_for(application, lambda: window.workers == set(), timeout=10)
        report = window.documents[str(broken)]
        assert isinstance(report, dict)
        assert report.get("error")
        select_row(window, application, str(broken))
        assert window.current_pdf == broken
        assert window.page_label.text() == "PDF nicht lesbar"
        assert window._selecting_document is False
        assert not (tmp_path / "references.sqlite").exists()
    finally:
        window.thread_pool.waitForDone(); window.close(); application.processEvents()


def test_selection_still_works_after_batch_and_reports_stay_dicts(tmp_path):
    application = app(); window = window_for(tmp_path)
    paths = make_pdfs(tmp_path, 4)
    csv_path = tmp_path / "after-batch.csv"
    try:
        window.start_batch(paths, csv_path)
        assert wait_for(application, lambda: not window._batch_active, timeout=60)
        wait_for(application, lambda: window.workers == set(), timeout=10)
        for path in paths:
            select_row(window, application, str(path))
            assert window.current_pdf == path
        # Selecting the same document repeatedly must not duplicate entries.
        before = window.document_list.count()
        select_row(window, application, str(paths[0]))
        select_row(window, application, str(paths[0]))
        assert window.document_list.count() == before
        assert all(isinstance(value, dict) for value in window.documents.values())
    finally:
        window.thread_pool.waitForDone(); window.close(); application.processEvents()


def test_string_report_is_rejected_and_never_stored(tmp_path):
    application = app(); window = window_for(tmp_path)
    path = create_demo_pdf(tmp_path / "invalid-report.pdf")
    try:
        # Exactly the historical failure mode: a path string arrives as report.
        window._analysis_ready(str(path), str(path))
        application.processEvents()
        report = window.documents[str(path)]
        assert isinstance(report, dict)
        assert report["error"] == "INVALID_REPORT"
        assert "Ungültiger Analysebericht" in report["message"]
        assert window.current_pdf == path

        # A legacy/injected string is repaired on access as well.
        window.documents[str(path)] = str(path)
        window._select_document(str(path))
        repaired = window.documents[str(path)]
        assert isinstance(repaired, dict)
        assert repaired["error"] == "INVALID_REPORT"
        assert window._selecting_document is False
    finally:
        window.close(); application.processEvents()


def test_selection_is_reentrancy_safe_and_list_entries_are_not_duplicated(tmp_path, monkeypatch):
    application = app(); window = window_for(tmp_path)
    first, second = make_pdfs(tmp_path, 2)
    try:
        for path in (first, second):
            window._analysis_ready(str(path), analyse_pdf(path))
        wait_for(application, lambda: window.workers == set(), timeout=10)

        calls = []
        original = window.load_pdf

        def recursive_load(path):
            calls.append(path)
            if len(calls) == 1:
                # Simulate a Qt signal fired again from inside the selection.
                window._select_document(str(first))
            original(path)

        monkeypatch.setattr(window, "load_pdf", recursive_load)
        window._select_document(str(second))
        assert calls == [second]
        assert window.current_pdf == second
        assert window._selecting_document is False

        before = window.document_list.count()
        for _ in range(3):
            window._analysis_ready(str(second), analyse_pdf(second))
        assert window.document_list.count() == before
    finally:
        window.close(); application.processEvents()


def _training_database(path, source):
    """Minimal real training DB; batch export must only read it."""
    database = sqlite3.connect(path)
    database.executescript("""
    CREATE TABLE documents(document_id TEXT PRIMARY KEY, sha256 TEXT NOT NULL, file_ref TEXT,
        bank TEXT, document_type TEXT, created_at TEXT NOT NULL);
    CREATE TABLE parser_runs(run_id INTEGER PRIMARY KEY, document_id TEXT NOT NULL,
        plugin_id TEXT NOT NULL, handler_id TEXT NOT NULL, parser_version TEXT NOT NULL,
        result_version TEXT NOT NULL, result_json TEXT NOT NULL, issues_json TEXT NOT NULL,
        runtime_ns INTEGER NOT NULL, created_at TEXT NOT NULL);
    CREATE TABLE reference_values(document_id TEXT, field_path TEXT, expected_json TEXT,
        severity TEXT, updated_at TEXT, updated_by TEXT);
    """)
    report = analyse_pdf(source)
    detection = report["detection"]
    database.execute("INSERT INTO documents VALUES (?,?,?,?,?,?)",
                     (report["document_id"], report["source_hash"], str(source),
                      detection["plugin_id"], detection["document_type"], "now"))
    database.execute("INSERT INTO parser_runs VALUES (?,?,?,?,?,?,?,?,?,?)",
                     (1, report["document_id"], detection["plugin_id"],
                      detection["handler_id"], detection["plugin_version"],
                      report["result"]["schema_version"], "{}", "[]", 1, "now"))
    database.execute("INSERT INTO reference_values VALUES (?,?,?,?,?,?)",
                     (report["document_id"], "accounts[0].iban", '"DE001234567890"',
                      "ERROR", "now", "test"))
    database.commit(); database.close()
    return Path(path)


def test_batch_csv_appends_optional_training_columns_and_keeps_sqlite_unchanged(tmp_path):
    application = app(); window = window_for(tmp_path)
    path = create_demo_pdf(tmp_path / "trained.pdf")
    database = _training_database(tmp_path / "training.sqlite", path)
    before = hashlib.sha256(database.read_bytes()).hexdigest()
    csv_path = tmp_path / "trained-batch.csv"
    try:
        window.start_batch([path], csv_path, training_database=database)
        assert wait_for(application, lambda: not window._batch_active, timeout=60)
        wait_for(application, lambda: window.workers == set(), timeout=10)
        assert hashlib.sha256(database.read_bytes()).hexdigest() == before

        with csv_path.open(newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            row = next(reader); fields = reader.fieldnames
        training = [field for field in fields if field.startswith("training[")]
        assert training
        assert fields[-len(training):] == training, "training columns must be last"
        assert row["training[0].field_path"] == "accounts[0].iban"
        assert row["training[0].reference_value"] == "DE001234567890"
        assert row["source"] == str(path)
    finally:
        window.thread_pool.waitForDone(); window.close(); application.processEvents()
