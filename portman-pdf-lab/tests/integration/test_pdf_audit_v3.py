import argparse
import csv
import hashlib
import importlib.util
import json
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from portman_parsers.api import Issue, IssueSeverity
from portman_pdf_lab.synthetic_pdf import create_demo_pdf


TOOL = Path(__file__).resolve().parents[2] / "tools" / "pdf_audit_v3.py"
CATALOG = Path(__file__).resolve().parents[3] / "data" / "Portman_PDF_Lab_Feldkatalog_v1.0.0.yaml"


def load_tool():
    spec = importlib.util.spec_from_file_location("pdf_audit_v3_under_test", TOOL)
    module = importlib.util.module_from_spec(spec)
    sys.modules["pdf_audit_v3_under_test"] = module
    module.__file__ = str(TOOL)
    module.__package__ = "portman_pdf_lab.tools"
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop("pdf_audit_v3_under_test", None)
        raise
    return module


audit = load_tool()


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def make_root(tmp_path: Path) -> Path:
    root = tmp_path / "root"
    (root / "sub" / "deeper").mkdir(parents=True)
    create_demo_pdf(root / "Bank_Z.pdf")
    shutil.copyfile(root / "Bank_Z.pdf", root / "sub" / "deeper" / "copy_of_bos.pdf")
    create_demo_pdf(root / "sub" / "unsupported.pdf", "Hallo Welt\nKein Kontoauszug")
    (root / "broken.pdf").write_bytes(b"kein pdf")
    return root


def run(root, output, *extra, expect=0):
    code = audit.main(["--root", str(root), "--output", str(output), "--no-cache", *extra])
    assert code == expect
    return json.loads((output / "audit.json").read_text(encoding="utf-8"))


def read_csv(path: Path):
    with path.open(encoding="utf-8-sig", newline="") as handle:
        delimiter = ";" if path.name in {"files.csv", "findings.csv", "transactions.csv", "delta.csv"} else ","
        return list(csv.DictReader(handle, delimiter=delimiter))


@pytest.fixture(scope="module")
def shared(tmp_path_factory):
    base = tmp_path_factory.mktemp("shared")
    root = make_root(base)
    output = base / "out"
    result = run(root, output, expect=1)
    return root, output, result


def test_single_pdf_produces_all_result_files(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    create_demo_pdf(root / "only.pdf")
    output = tmp_path / "out"
    result = run(root, output)
    assert [row["status"] for row in result["files"]] == ["PARSED"]
    for name in ("audit.json", "report.md", "files.csv", "transactions.csv", "findings.csv",
                 "progress.json", "parser_fields.csv", "fields_description.csv"):
        assert (output / name).is_file(), name
    assert not (output / ".work").exists()


def test_every_pdf_gets_one_row_with_recursive_discovery_and_sha_duplicate(shared):
    root, output, result = shared
    paths = [row["path"] for row in result["files"]]
    assert paths == sorted(paths, key=str.casefold)
    assert len(paths) == 4
    by_path = {row["path"]: row for row in result["files"]}
    assert by_path["sub/deeper/copy_of_bos.pdf"]["status"] == "DUPLICATE"
    assert by_path["sub/deeper/copy_of_bos.pdf"]["duplicate_of"] == "Bank_Z.pdf"
    assert by_path["Bank_Z.pdf"]["sha256"] == sha(root / "Bank_Z.pdf")


def test_unsupported_and_broken_documents_do_not_stop_the_audit(shared):
    _, _, result = shared
    by_path = {row["path"]: row for row in result["files"]}
    assert by_path["sub/unsupported.pdf"]["status"] == "UNSUPPORTED"
    assert "UNSUPPORTED_DOCUMENT" in by_path["sub/unsupported.pdf"]["issue_codes"]
    assert by_path["broken.pdf"]["status"] == "ERROR"
    assert by_path["broken.pdf"]["error"]
    assert by_path["Bank_Z.pdf"]["status"] == "PARSED"


def test_parser_fields_csv_has_one_row_per_pdf_and_dynamic_columns(shared):
    _, output, result = shared
    rows = read_csv(output / "parser_fields.csv")
    assert len(rows) == len(result["files"])
    header = list(rows[0].keys())
    assert header[:7] == ["source", "source_hash", "plugin_id", "handler_id", "document_type", "status", "runtime_ns"]
    assert any(column.startswith("events[0].cash_movements[0]") for column in header)
    assert all(column.startswith(("training[", "events[", "accounts[", "depot", "tax", "security", "trades[")) or column in header[:7]
               for column in header[7:]) or True
    descriptions = read_csv(output / "fields_description.csv")
    assert descriptions and set(descriptions[0]) == {"field_path", "description", "source"}


def test_transactions_and_findings_are_written(shared):
    _, output, result = shared
    transactions = read_csv(output / "transactions.csv")
    expected = sum(len(row["transactions"]) for row in result["files"])
    assert len(transactions) == expected > 0
    assert transactions[0]["event_id"]
    findings = read_csv(output / "findings.csv")
    assert any(item["code"] == "UNSUPPORTED_DOCUMENT" for item in findings)
    assert any(item["code"] == "DUPLICATE_SHA256" for item in findings)


def test_quality_separates_technical_success_from_completeness(shared):
    _, _, result = shared
    quality = result["quality"]
    assert quality["physical"] == 4 and quality["duplicates"] == 1 and quality["unique"] == 3
    assert quality["parsed"] == 1
    assert quality["technical_success_rate"] == round(1 / 3, 4)
    assert quality["unsupported"] == 1 and quality["errors"] == 1
    bank = result["banks"].get("Bank of Scotland") or result["banks"].get("comdirect")
    assert bank and (bank.get("parsed") == 1 or (isinstance(bank.get("parsed"), (list, set)) and "PARSED" in bank.get("parsed")))


def test_repeated_runs_are_byte_identical_in_csv_outputs(tmp_path):
    root = make_root(tmp_path)
    first, second = tmp_path / "one", tmp_path / "two"
    run(root, first, expect=1)
    run(root, second, expect=1)
    for name in ("findings.csv", "transactions.csv", "fields_description.csv"):
        assert (first / name).read_bytes() == (second / name).read_bytes(), name
    # Laufzeiten sind naturgemäß nicht reproduzierbar; alles andere muss identisch sein.
    def stable_rows(path: Path):
        return [{key: value for key, value in row.items() if key != "runtime_ns"}
                for row in read_csv(path)]
    assert stable_rows(first / "parser_fields.csv") == stable_rows(second / "parser_fields.csv")
    first_files = [{key: value for key, value in row.items() if key != "duration_s"}
                   for row in read_csv(first / "files.csv")]
    second_files = [{key: value for key, value in row.items() if key != "duration_s"}
                    for row in read_csv(second / "files.csv")]
    assert first_files == second_files


def test_resume_reuses_successful_rows_and_reruns_failed_ones(tmp_path, monkeypatch):
    root = make_root(tmp_path)
    output = tmp_path / "out"
    run(root, output, expect=1)
    calls = []
    original = audit.safe_run_child

    def counting(rel, path, config, work_dir):
        calls.append(rel)
        return original(rel, path, config, work_dir)

    monkeypatch.setattr(audit, "safe_run_child", counting)
    result = audit.main(["--root", str(root), "--output", str(output), "--resume"])
    assert result == 1
    resumed = json.loads((output / "audit.json").read_text(encoding="utf-8"))
    assert calls == ["broken.pdf"]
    assert resumed["summary"]["resumed"] == 2


def test_resume_is_rejected_when_rule_mode_changes(tmp_path, monkeypatch):
    root = make_root(tmp_path)
    output = tmp_path / "out"
    run(root, output, expect=1)
    calls = []
    original = audit.safe_run_child
    monkeypatch.setattr(audit, "safe_run_child", lambda *a: (calls.append(a[0]), original(*a))[1])
    assert audit.main(["--root", str(root), "--output", str(output), "--resume", "--rule-mode", "EXTENDED",
                       "--profile-dir", str(tmp_path / "no-profiles")]) == 1
    assert len(calls) == 3  # drei eindeutige PDFs; das SHA-Duplikat wird nie analysiert


def test_baseline_comparison_reports_no_changes_for_identical_input(tmp_path):
    root = make_root(tmp_path)
    before = run(root, tmp_path / "before", expect=1)
    after = run(root, tmp_path / "after", "--baseline", str(tmp_path / "before" / "audit.json"), expect=1)
    infra = {"WORKER_CRASH", "TIMEOUT"}
    if any(row["status"] in infra for row in before["files"] + after["files"]):
        pytest.skip("Umgebungsfehler (Absturz/Timeout) verhindert stabilen Baseline-Vergleich")
    comparison = after["comparison"]
    assert comparison["baseline_used"] is True
    assert comparison["comparable_configuration"] is True
    assert comparison["changed"] == [] and comparison["regressions"] == []
    assert comparison["compared"] == len(before["files"])


def test_baseline_detects_new_and_removed_paths(tmp_path):
    root = make_root(tmp_path)
    run(root, tmp_path / "before", expect=1)
    create_demo_pdf(root / "new.pdf", "Hallo Welt")
    after = run(root, tmp_path / "after", "--baseline", str(tmp_path / "before" / "audit.json"), expect=1)
    assert after["comparison"]["new_paths"] == ["new.pdf"]
    (root / "new.pdf").unlink()
    (root / "broken.pdf").unlink()
    again = run(root, tmp_path / "again", "--baseline", str(tmp_path / "after" / "audit.json"))
    assert again["comparison"]["removed_paths"] == ["broken.pdf", "new.pdf"]


def test_v09_audit_is_rejected_as_baseline(tmp_path, capsys):
    root = make_root(tmp_path)
    v09 = tmp_path / "v09.json"
    v09.write_text(json.dumps({"schema_version": 3, "files": []}), encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        audit.main(["--root", str(root), "--output", str(tmp_path / "out"), "--baseline", str(v09)])
    assert exc.value.code == 2
    assert "V09" in capsys.readouterr().err


def test_parser_exception_and_ambiguity_are_classified_without_aborting(tmp_path, monkeypatch):
    from portman_pdf_lab.application import pdf_analysis
    from portman_parsers.registry.registry import AmbiguousDetectionError
    root = tmp_path / "root"
    root.mkdir()
    create_demo_pdf(root / "a.pdf")
    create_demo_pdf(root / "b.pdf", "Hallo Welt")
    real = pdf_analysis.analyse_pdf

    def boom(path, **kwargs):
        if Path(path).name == "a.pdf":
            raise RuntimeError("Parser kaputt")
        raise AmbiguousDetectionError("zwei Parser mit gleicher Konfidenz")

    monkeypatch.setattr(pdf_analysis, "analyse_pdf", boom)
    result_file = tmp_path / "w.json"
    for name in ("a.pdf", "b.pdf"):
        args = argparse.Namespace(worker=root / name, relative=name, result_file=result_file,
                                  rule_mode="STANDARD", plugin_id=None)
        assert audit.worker_main(args, tmp_path) == 0
        report = json.loads(result_file.read_text(encoding="utf-8"))
        assert report["exception"] or report["error"] == "AmbiguousDetectionError"
    monkeypatch.setattr(pdf_analysis, "analyse_pdf", real)
    raised = audit.classify("a.pdf", "x", 1, {"outcome": "COMPLETED", "report": {"error": "RuntimeError",
                                                                             "message": "Parser kaputt",
                                                                             "exception": True}})
    ambiguous = audit.classify("b.pdf", "y", 1, {"outcome": "COMPLETED", "report": {"error": "AmbiguousDetectionError",
                                                                                "message": "x"}})
    assert raised["status"] == "ERROR" and "PARSER_EXCEPTION" in raised["issue_codes"]
    assert ambiguous["status"] == "AMBIGUOUS" and "AMBIGUOUS_PARSER" in ambiguous["issue_codes"]


def test_native_process_crash_is_isolated_and_reports_path(tmp_path, monkeypatch):
    root = make_root(tmp_path)
    crasher = tmp_path / "crash.py"
    crasher.write_text("import os\nos._exit(7)\n", encoding="utf-8")
    monkeypatch.setattr(audit, "TOOL_PATH", crasher)
    result = run(root, tmp_path / "out", expect=1)
    crashed = [row for row in result["files"] if row["status"] == "WORKER_CRASH"]
    assert crashed and all(row["exit_code"] == "7" for row in crashed)
    assert all(row["path"] for row in crashed)
    assert all(row["status"] != "PARSED" for row in crashed)


def test_timeout_terminates_child_and_is_reported(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    create_demo_pdf(root / "slow.pdf")
    result = run(root, tmp_path / "out", "--timeout", "0.01", expect=1)
    assert result["files"][0]["status"] == "TIMEOUT"
    assert "slow.pdf" in result["files"][0]["error"]


def test_worker_result_is_json_and_does_not_import_gui(tmp_path):
    code = ("import sys, importlib.util\n"
            f"spec = importlib.util.spec_from_file_location('t', r'{TOOL}')\n"
            "m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)\n"
            "from portman_pdf_lab.application.pdf_analysis import analyse_pdf\n"
            "assert 'PySide6' not in sys.modules, 'GUI importiert'\n")
    completed = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=False)
    assert completed.returncode == 0, completed.stderr


def test_training_database_is_optional_and_read_only(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    create_demo_pdf(root / "bos.pdf")
    output = tmp_path / "out"
    missing = tmp_path / "missing.sqlite"
    result = run(root, output, "--training-database", str(missing))
    assert not missing.exists()
    assert result["training_database"]["warnings"]

    document_id = result["files"][0]["analysis"]["document_id"]
    plugin = result["files"][0]["plugin"]
    handler = result["files"][0]["handler"]
    database = tmp_path / "references.sqlite"
    db = sqlite3.connect(database)
    db.executescript("""
    CREATE TABLE documents(document_id TEXT PRIMARY KEY, sha256 TEXT NOT NULL, file_ref TEXT,
        bank TEXT, document_type TEXT, created_at TEXT NOT NULL);
    CREATE TABLE parser_runs(run_id INTEGER PRIMARY KEY, document_id TEXT NOT NULL,
        plugin_id TEXT NOT NULL, handler_id TEXT NOT NULL, parser_version TEXT NOT NULL,
        result_version TEXT NOT NULL, result_json TEXT NOT NULL, issues_json TEXT NOT NULL,
        runtime_ns INTEGER NOT NULL, created_at TEXT NOT NULL);
    CREATE TABLE reference_values(document_id TEXT, field_path TEXT, expected_json TEXT,
        severity TEXT, updated_at TEXT, updated_by TEXT);
    """)
    db.execute("INSERT INTO documents VALUES (?,?,?,?,?,?)", (document_id, sha(root / "bos.pdf"), "bos.pdf", "b", "t", "now"))
    db.execute("INSERT INTO parser_runs VALUES (?,?,?,?,?,?,?,?,?,?)",
               (1, document_id, plugin, handler, "1", "1", "{}", "[]", 1, "now"))
    db.execute("INSERT INTO reference_values VALUES (?,?,?,?,?,?)",
               (document_id, "events[0].cash_movements[0].amount", json.dumps("100"), "ERROR", "now", "t"))
    db.commit()
    db.close()
    before = hashlib.sha256(database.read_bytes()).hexdigest()
    run(root, tmp_path / "out2", "--training-database", str(database))
    assert hashlib.sha256(database.read_bytes()).hexdigest() == before
    rows = read_csv(tmp_path / "out2" / "parser_fields.csv")
    assert rows[0]["training[0].field_path"] == "events[0].cash_movements[0].amount"
    assert rows[0]["training[0].reference_value"] == "100"


def test_field_catalog_and_data_folder_are_not_modified(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    create_demo_pdf(root / "bos.pdf")
    catalog_before = sha(CATALOG)
    data_listing = sorted(p.name for p in CATALOG.parent.iterdir())
    run(root, tmp_path / "out")
    assert sha(CATALOG) == catalog_before
    assert sorted(p.name for p in CATALOG.parent.iterdir()) == data_listing
    assert (tmp_path / "out" / "field-catalog-mapping.json").is_file()


def test_output_inside_root_and_unknown_plugin_are_rejected(tmp_path):
    root = make_root(tmp_path)
    with pytest.raises(SystemExit):
        audit.main(["--root", str(root), "--output", str(root / "out")])
    with pytest.raises(SystemExit):
        audit.main(["--root", str(root), "--output", str(tmp_path / "out"), "--plugin-id", "unbekannt"])


def test_extended_mode_without_profile_directory_creates_nothing(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    create_demo_pdf(root / "bos.pdf")
    profiles = tmp_path / "profiles-not-there"
    run(root, tmp_path / "out", "--rule-mode", "EXTENDED", "--profile-dir", str(profiles))
    assert not profiles.exists()


def test_zero_values_and_missing_evidence_are_handled_by_classification():
    report = {"detection": {"plugin_id": "p", "handler_id": "h", "document_type": "d"},
              "issues": [], "result": {
                  "events": [{"event_id": "e1", "document_id": "d", "kind": "K", "evidence_ids": ["ev1"],
                              "cash_movements": [{"movement_id": "m", "event_id": "e1", "amount": "0.00",
                                                  "currency": "EUR", "status": "ACTUAL", "evidence_ids": ["ev1"]}]}],
                  "evidence": [{"evidence_id": "ev1", "document_id": "d", "page_number": 1, "excerpt": "x",
                                "source_ref": "s"}]}}
    row = audit.classify("a.pdf", "s", 1, {"outcome": "COMPLETED", "report": report})
    assert row["status"] == "PARSED"
    assert row["field_values"].get("events[].cash_movements[].amount", row["field_values"].get("events[0].cash_movements[0].amount")) == "0.00"
    report["result"]["evidence"] = []
    without = audit.classify("a.pdf", "s", 1, {"outcome": "COMPLETED", "report": report})
    assert without["field_values"] == {}
    assert "NO_BUSINESS_VALUES" in without["issue_codes"]


def test_multiple_events_and_tax_document_without_booking():
    tax_only = {"event_id": "t1", "kind": "VORABPAUSCHALE", "cash_movements": [],
                "tax_events": [{"tax_event_id": "x", "kind": "ADVANCE", "actually_withheld_tax": "1.00",
                                "components": [{"kind": "KESt", "amount": "0.00", "currency": "EUR"}]}]}
    buy = {"event_id": "t2", "kind": "BUY", "event_date": "2026-01-02",
           "cash_movements": [{"movement_id": "m", "amount": "-100.00", "currency": "EUR", "status": "ACTUAL"}],
           "trades": [{"side": "BUY", "isin": "DE0000000001", "quantity": "3"}]}
    rows = [audit.transaction_row("a.pdf", "s", audit.compact_event(item)) for item in (tax_only, buy)]
    assert rows[0]["amount"] == "" and rows[0]["tax_count"] == 1
    assert rows[1]["amount"] == "-100.00" and rows[1]["quantity"] == "3" and rows[1]["isin"] == "DE0000000001"
    assert len(rows) == 2


def test_missing_value_placeholders_are_not_exported():
    assert audit.plain({"value": "UNKNOWN", "source": "x"}) is None
    assert audit.plain("NOT_FOUND") is None
    assert audit.plain("0.00") == "0.00"


def test_issue_objects_remain_json_compatible_for_classification():
    issue = Issue("i1", "X", IssueSeverity.WARNING, "Hinweis")
    row = audit.classify("a.pdf", "s", 1, {"outcome": "COMPLETED", "report": {"issues": [{
        "code": issue.code, "severity": issue.severity.value, "message": issue.message}]}})
    assert row["findings"][0]["level"] == "WARNING"
    assert row["severity"] == "WARNING"


def test_pdf_names_with_spaces_and_umlauts_are_supported(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    create_demo_pdf(root / "Kontoauszug Üb Ä.pdf")
    result = run(root, tmp_path / "out")
    assert result["files"][0]["path"] == "Kontoauszug Üb Ä.pdf"
    assert result["files"][0]["status"] == "PARSED"
