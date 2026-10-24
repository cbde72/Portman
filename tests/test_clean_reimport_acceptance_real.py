"""Opt-in clean-reimport acceptance test against the unchanged local PDFs."""
from copy import deepcopy
from decimal import Decimal
from hashlib import sha256
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from portfolio_v5.accounts import account_key
from portfolio_v5.import_accounts import import_sources, required_target_kind
from portfolio_v5.models import BankTransaction, ImportBatch
from portfolio_v5.pdf_importer import parse_pdf
from portman.comdirect_import import commit_reports
from portman.import_v09 import ImportSession, transaction
from portman.repository_v09 import RepositoryV09
from portman.tax_annual_summary import aggregate_tax_annual_rows, tax_annual_summaries


DOCUMENT_ROOT = Path(r"C:\Users\chris\Desktop\history\comdirect\2026")
DEPOT = "Depot 4764924"
PRIMARY_CASH = "Verrechnungskonto DE71200411330476492440"
ADDITIONAL_CASH = "Giro DE84200411330476492400"
SAVINGS = "Tagesgeld DE46200411330476492405"


def _seed(path):
    repo = RepositoryV09(path, backups=False)
    for source, name, details in (
            ("IBAN DE71200411330476492440", PRIMARY_CASH, {
        "kind": "Verrechnungskonto", "institution": "Comdirect",
        "iban": "DE71200411330476492440"}),
            ("IBAN DE84200411330476492400", ADDITIONAL_CASH, {
        "kind": "Girokonto", "institution": "Comdirect",
        "iban": "DE84200411330476492400"}),
            ("IBAN DE46200411330476492405", SAVINGS, {
        "kind": "Sonstiges", "institution": "Comdirect",
        "iban": "DE46200411330476492405"})):
        repo.save_account(source, details)
        repo.save_account(name, details, original=source)
    repo.save_account(DEPOT, {
        "kind": "Depot", "institution": "Comdirect",
        "cash_account_key": "iban de71200411330476492440",
        "cash_account_keys": ["iban de84200411330476492400"]})
    repo.save_institution_tax_record("Comdirect", 2026, exemption="411.00")
    manual = ImportBatch("Manuell: Akzeptanz-Platzhalter", "acceptance-manual-seed",
                         transactions=[BankTransaction(
                             ADDITIONAL_CASH, "manual-seed", "2025-12-31",
                             "BANK_BOOKING", "1.00", "EUR", purpose="Akzeptanz-Platzhalter")])
    assert repo.commit_batches([manual])[0]["status"] == "imported"
    repo.db.execute("INSERT INTO saved_views(name,payload) VALUES(?,?)",
                    ("Akzeptanz", '{"kept":true}'))
    repo.db.commit()
    repo.close()


def _assign_accounts(batches):
    for batch in batches:
        # Depot-bearing records (notably MiFID cost reports) are not all part
        # of account_names, but the GUI preview still persists this selection.
        sources = import_sources(batch)
        for source in sources:
            if required_target_kind(source) == "Depot":
                batch.account_assignments[source["key"]] = account_key(DEPOT)
        for source in list(batch.account_names):
            key = account_key(source)
            if key == "depot 476492400":
                batch.account_assignments[key] = account_key(DEPOT)


def _apply_guided(path, batches):
    job = SimpleNamespace(path=str(path), isInterruptionRequested=lambda: False,
                          progress=SimpleNamespace(emit=lambda *_args: None))
    repo = RepositoryV09(path, backups=False)
    try:
        with transaction(repo, commit=True):
            return ImportSession.apply(None, repo, job, (deepcopy(batches), []))
    finally:
        repo.close()


@pytest.fixture(scope="module")
def real_batches():
    if os.environ.get("PORTMAN_REAL_COMDIRECT_ACCEPTANCE") != "1":
        pytest.skip("set PORTMAN_REAL_COMDIRECT_ACCEPTANCE=1 for the private PDF acceptance run")
    if not DOCUMENT_ROOT.exists():
        pytest.skip("private comdirect PDF folder is not available")
    paths = sorted(DOCUMENT_ROOT.rglob("*.pdf"))
    unique = {}
    for path in paths:
        unique.setdefault(sha256(path.read_bytes()).hexdigest(), path)
    batches = [parse_pdf(path) for path in unique.values()]
    assert all(not batch.errors for batch in batches)
    _assign_accounts(batches)
    return paths, batches


@pytest.mark.parametrize("order", ("finance-first", "notices-first"))
def test_real_clean_reimport_through_gui_storage_paths(tmp_path, real_batches, order):
    paths, batches = real_batches
    finance = [batch for batch in batches if batch.document_type == "comdirect Finanzreport"]
    notices = [batch for batch in batches if batch.document_type != "comdirect Finanzreport"]
    database = tmp_path / f"{order}.sqlite"
    settings = tmp_path / "portfolio_settings.json"
    settings.write_text('{"acceptance":"keep"}', encoding="utf-8")
    settings_before = settings.read_bytes()
    _seed(database)

    job = SimpleNamespace(path=str(database), isInterruptionRequested=lambda: False,
                          progress=SimpleNamespace(emit=lambda *_args: None))
    if order == "finance-first":
        results = commit_reports(job, deepcopy(finance), RepositoryV09)
        results += _apply_guided(database, notices)
    else:
        results = _apply_guided(database, notices)
        results += commit_reports(job, deepcopy(finance), RepositoryV09)
    assert all(result["status"] == "imported" for result in results)

    repo = RepositoryV09(database, backups=False)
    try:
        evidence = repo.store.model_records(kind="booking_evidence")
        details = [dict(row) for row in repo.db.execute(
            "SELECT transaction_id,payload FROM booking_details")]
        assert len(paths) == 126
        assert len(batches) == 117
        assert len(evidence) == 38
        assert len(details) == 37
        assert sum(account_key(__import__("json").loads(row["payload"]).get(
            "performance_depot_key", "")) == account_key(DEPOT) for row in details) == 37
        assert len(repo.fee_links()) == 4
        linked_events = [event for event in repo.tax_events()
                         if event.get("related_transaction_id")]
        assert len(linked_events) == 7
        assert repo.db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert repo.db.execute("PRAGMA foreign_key_check").fetchall() == []
        duplicates = repo.db.execute(
            "SELECT account,external_id,COUNT(*) n FROM transactions "
            "GROUP BY account,external_id HAVING n>1").fetchall()
        assert duplicates == []
        assert repo.db.execute(
            "SELECT COUNT(*) FROM imports WHERE path='Manuell: Akzeptanz-Platzhalter' AND active=1"
        ).fetchone()[0] == 1
        assert repo.db.execute(
            "SELECT payload FROM saved_views WHERE name='Akzeptanz'").fetchone()[0] == '{"kept":true}'
        assert repo.institution_tax_records(2026)[0]["exemption"] == "411.00"
        summaries = [row for row in tax_annual_summaries(repo, 2026)
                     if row["institution"].casefold() == "comdirect"]
        _bank, calculated = aggregate_tax_annual_rows(summaries)
        assert calculated["other_result"] == Decimal("523.07")
        assert calculated["used_exemption"] == Decimal("411.00")
        assert calculated["remaining_exemption"] == Decimal("0.00")
        assert calculated["capital_gains_tax"] == Decimal("28.02")
        assert calculated["solidarity_surcharge"] == Decimal("1.51")
        calculation = summaries[0]["fsa_calculation"]
        assert calculation["taxable_after_fsa"] == Decimal("112.07")

        counts_before = tuple(repo.db.execute(query).fetchone()[0] for query in (
            "SELECT COUNT(*) FROM imports WHERE active=1",
            "SELECT COUNT(*) FROM transactions",
            "SELECT COUNT(*) FROM booking_details",
            "SELECT COUNT(*) FROM fee_links"))
    finally:
        repo.close()

    repeated = commit_reports(job, deepcopy(finance), RepositoryV09)
    repeated += _apply_guided(database, notices)
    assert all(result["status"] == "duplicate" for result in repeated)
    repo = RepositoryV09(database, backups=False)
    try:
        counts_after = tuple(repo.db.execute(query).fetchone()[0] for query in (
            "SELECT COUNT(*) FROM imports WHERE active=1",
            "SELECT COUNT(*) FROM transactions",
            "SELECT COUNT(*) FROM booking_details",
            "SELECT COUNT(*) FROM fee_links"))
        assert counts_after == counts_before
    finally:
        repo.close()
    assert settings.read_bytes() == settings_before
