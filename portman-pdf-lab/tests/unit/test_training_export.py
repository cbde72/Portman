import csv
import hashlib
import json
import sqlite3

from portman_pdf_lab.application.pdf_analysis import export_batch_csv
from portman_pdf_lab.application.training_export import TrainingExportReader


def _database(path, document_id="doc-1", digest="hash-1"):
    db = sqlite3.connect(path)
    db.executescript("""
    CREATE TABLE documents(document_id TEXT PRIMARY KEY, sha256 TEXT NOT NULL, file_ref TEXT,
        bank TEXT, document_type TEXT, created_at TEXT NOT NULL);
    CREATE TABLE parser_runs(run_id INTEGER PRIMARY KEY, document_id TEXT NOT NULL,
        plugin_id TEXT NOT NULL, handler_id TEXT NOT NULL, parser_version TEXT NOT NULL,
        result_version TEXT NOT NULL, result_json TEXT NOT NULL, issues_json TEXT NOT NULL,
        runtime_ns INTEGER NOT NULL, created_at TEXT NOT NULL);
    CREATE TABLE reference_values(document_id TEXT, field_path TEXT, expected_json TEXT,
        severity TEXT, updated_at TEXT, updated_by TEXT);
    CREATE TABLE annotations(annotation_id INTEGER PRIMARY KEY, document_id TEXT,
        parser_id TEXT, handler_id TEXT, page_number INTEGER, original_text TEXT,
        field_path TEXT, reference_json TEXT, annotation_kind TEXT, decision TEXT,
        review_status TEXT, coordinates_json TEXT, created_at TEXT, created_by TEXT, active INTEGER);
    """)
    db.execute("INSERT INTO documents VALUES (?,?,?,?,?,?)", (document_id, digest, "x.pdf", "bank", "statement", "now"))
    db.execute("INSERT INTO parser_runs VALUES (?,?,?,?,?,?,?,?,?,?)",
               (1, document_id, "parser.a", "handler-a", "1", "1", "{}", "[]", 1, "now"))
    db.execute("INSERT INTO reference_values VALUES (?,?,?,?,?,?)",
               (document_id, "events[0].amount", json.dumps("100"), "ERROR", "now", "test"))
    db.execute("INSERT INTO annotations VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
               (1, document_id, "parser.a", "handler-a", 1, "100", "events[0].amount",
                json.dumps("125"), "AMOUNT", "CORRECTED", "APPROVED", None, "now", "test", 1))
    db.commit()
    db.close()


def test_reader_matches_document_hash_and_parser_without_writing(tmp_path):
    database = tmp_path / "references.sqlite"
    _database(database)
    before = hashlib.sha256(database.read_bytes()).hexdigest()
    with TrainingExportReader(database) as reader:
        rows = reader.for_report({"document_id": "doc-1", "source_hash": "hash-1",
                                  "detection": {"plugin_id": "parser.a", "handler_id": "handler-a"}})
        assert [row["source"] for row in rows] == ["reference_values", "annotations"]
        assert rows[1]["corrected_value"] == "125"
        assert reader.for_report({"document_id": "doc-1", "source_hash": "wrong",
                                  "detection": {"plugin_id": "parser.a", "handler_id": "handler-a"}}) == []
    assert hashlib.sha256(database.read_bytes()).hexdigest() == before


def test_csv_appends_indexed_training_columns_and_warns_for_missing_database(tmp_path):
    database = tmp_path / "references.sqlite"
    _database(database)
    output = tmp_path / "batch.csv"
    report = {"files": [
        {"source": "one.pdf", "source_hash": "hash-1", "document_id": "doc-1",
         "detection": {"plugin_id": "parser.a", "handler_id": "handler-a"},
         "timings": {"total_ns": 1}},
        {"source": "two.pdf", "source_hash": "none", "document_id": "none",
         "detection": {"plugin_id": "parser.a", "handler_id": "handler-a"},
         "timings": {"total_ns": 2}},
    ]}
    export_batch_csv(report, output, database)
    with output.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert rows[0]["training[0].field_path"] == "events[0].amount"
    assert rows[0]["training[1].corrected_value"] == "125"
    assert rows[1]["training[0].field_path"] == ""

    missing = {"files": [{"source": "one.pdf", "document_id": "doc-1"}]}
    export_batch_csv(missing, tmp_path / "missing.csv", tmp_path / "not-there.sqlite")
    assert missing["warnings"]
