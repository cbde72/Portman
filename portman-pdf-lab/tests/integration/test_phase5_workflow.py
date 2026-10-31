from pathlib import Path

from portman_pdf_lab.application.pdf_analysis import analyse_directory, export_batch_csv
from portman_pdf_lab.application.reference_service import analyse_and_store
from portman_pdf_lab.storage import ReferenceRepository
from portman_pdf_lab.synthetic_pdf import create_demo_pdf

FIXTURES = Path(__file__).parents[2].parent / "portman-parsers" / "tests" / "fixtures" / "fnz"


def test_analysis_persists_and_reloads_versioned_result(tmp_path):
    pdf = create_demo_pdf(tmp_path / "statement.pdf")
    repo = ReferenceRepository(tmp_path / "references.sqlite")
    report, run_id = analyse_and_store(pdf, repo)
    assert report["result"]["plugin_id"] == "user.bank-of-scotland-kontoauszug"
    assert repo.run(run_id)["result"]["document_id"] == report["document_id"]


def test_fnz_turnover_and_depot_statement_run_end_to_end(tmp_path):
    turnover = create_demo_pdf(tmp_path / "turnover.pdf", (FIXTURES / "turnover.txt").read_text(encoding="utf-8"))
    statement = create_demo_pdf(tmp_path / "depot.pdf", (FIXTURES / "depot_statement.txt").read_text(encoding="utf-8"))
    from portman_pdf_lab.application.pdf_analysis import analyse_pdf
    turnover_report, statement_report = analyse_pdf(turnover), analyse_pdf(statement)
    assert turnover_report["detection"]["handler_id"] == "umsatzabrechnung"
    assert [event["kind"] for event in turnover_report["result"]["events"]] == ["DIVIDEND", "REINVESTMENT", "BUY"]
    assert statement_report["detection"]["handler_id"] == "depotauszug"
    assert not statement_report["result"]["events"]


def test_batch_hash_deduplication_progress_and_csv(tmp_path):
    first = create_demo_pdf(tmp_path / "first.pdf")
    (tmp_path / "copy.pdf").write_bytes(first.read_bytes())
    (tmp_path / "broken.pdf").write_bytes(b"not a pdf")
    progress = []
    report = analyse_directory(tmp_path, lambda current, total, path: progress.append((current, total)))
    assert report["count"] == 3
    assert len([item for item in report["files"] if item.get("duplicate_of")]) == 1
    assert any(item.get("error") for item in report["files"])
    assert progress[-1] == (3, 3)
    csv_path = export_batch_csv(report, tmp_path / "batch.csv")
    assert "DUPLICATE" in csv_path.read_text(encoding="utf-8")


def test_batch_can_be_cancelled_between_documents(tmp_path):
    create_demo_pdf(tmp_path / "one.pdf"); create_demo_pdf(tmp_path / "two.pdf", "Other")
    calls = []
    report = analyse_directory(tmp_path, lambda *args: calls.append(args), lambda: bool(calls))
    assert report["cancelled"] is True
    assert report["count"] == 1
