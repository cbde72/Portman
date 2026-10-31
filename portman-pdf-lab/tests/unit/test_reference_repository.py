import sqlite3

import pytest

from portman_pdf_lab.reviews.models import ReviewStatus
from portman_pdf_lab.storage import ReferenceRepository


def repository(tmp_path):
    repo = ReferenceRepository(tmp_path / "reference.sqlite")
    repo.register_document("doc-1", "a" * 64, "outside/reference.pdf", "FNZ", "Depotauszug")
    return repo


def test_reimport_keeps_distinct_immutable_versioned_runs(tmp_path):
    repo = repository(tmp_path)
    one = repo.save_run("doc-1", "fnz.finvesto", "depotauszug", "2.0", "1.5.0",
                        {"events": [], "value": 10}, [], 100)
    two = repo.save_run("doc-1", "fnz.finvesto", "depotauszug", "2.1", "1.5.0",
                        {"events": [], "value": 11}, [], 120)
    assert one != two
    assert [run["parser_version"] for run in repo.runs_for_document("doc-1")] == ["2.0", "2.1"]


def test_reference_is_never_overwritten_by_parser_run(tmp_path):
    repo = repository(tmp_path)
    repo.set_reference("doc-1", "value", 10, "reviewer", "confirmed")
    run = repo.save_run("doc-1", "fnz.finvesto", "depotauszug", "2.0", "1.5.0",
                        {"value": 99}, [], 1)
    comparison = repo.reference_comparison(run)
    assert comparison == ({"field": "value", "expected": 10, "actual": 99,
                           "severity": "ERROR", "matches": False},)


def test_reference_correction_has_complete_history(tmp_path):
    repo = repository(tmp_path)
    repo.set_reference("doc-1", "value", 10, "alice", "initial")
    repo.set_reference("doc-1", "value", 11, "bob", "evidence correction")
    history = repo.reference_history("doc-1", "value")
    assert len(history) == 2
    assert history[1]["old_json"] == "10"
    assert history[1]["new_json"] == "11"


def test_review_status_and_history_persist(tmp_path):
    repo = repository(tmp_path)
    run = repo.save_run("doc-1", "fnz.finvesto", "depotauszug", "2.0", "1.5.0", {}, [], 1)
    repo.review(run, "cashflow", ReviewStatus.IN_REVIEW, "alice", "checking")
    repo.review(run, "cashflow", ReviewStatus.APPROVED, "alice", "verified")
    with sqlite3.connect(repo.path) as db:
        statuses = [row[0] for row in db.execute("SELECT status FROM reviews ORDER BY review_id")]
    assert statuses == ["IN_REVIEW", "APPROVED"]


def test_run_comparison_flags_critical_cash_changes_and_runtime(tmp_path):
    repo = repository(tmp_path)
    left = repo.save_run("doc-1", "fnz.finvesto", "umsatzabrechnung", "2.0", "1.5.0",
                         {"events": [{"event_id": "trade", "cash_movements": [{"movement_id": "cash", "amount": "-10"}]}]}, [], 100)
    right = repo.save_run("doc-1", "fnz.finvesto", "umsatzabrechnung", "2.1", "1.5.0",
                          {"events": [{"event_id": "trade", "cash_movements": [{"movement_id": "cash", "amount": "-11"}]}]}, [], 140)
    comparison = repo.compare_runs(left, right)
    assert comparison.changed
    assert comparison.critical_cashflow_changes
    assert comparison.runtime_delta_ns == 40


def test_document_hash_deduplicates_identity(tmp_path):
    repo = repository(tmp_path)
    found = repo.register_document("other", "a" * 64, "second.pdf", "FNZ", "Depotauszug")
    assert found == "doc-1"


def test_failed_transaction_rolls_back(tmp_path):
    repo = repository(tmp_path)
    with pytest.raises(RuntimeError):
        with repo.transaction() as db:
            db.execute("INSERT INTO reference_history(document_id,field_path,new_json,changed_at,changed_by,reason) VALUES('doc-1','x','1','now','a','r')")
            raise RuntimeError("stop")
    with sqlite3.connect(repo.path) as db:
        assert db.execute("SELECT count(*) FROM reference_history").fetchone()[0] == 0


def test_export_contains_metadata_without_copying_pdf(tmp_path):
    repo = repository(tmp_path); target = repo.export(tmp_path / "backup.json")
    content = target.read_text(encoding="utf-8")
    assert "outside/reference.pdf" in content
    assert not (tmp_path / "reference.pdf").exists()
