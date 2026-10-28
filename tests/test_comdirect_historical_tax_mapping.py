"""Historical comdirect tax notices map through their documented cash IBAN."""

import os
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from portfolio_v5.accounts import account_key
from portfolio_v5.models import ImportBatch, TaxEvent
from portfolio_v5.pdf_importer import parse_pdf
from portman.import_v09 import ImportSession, transaction
from portman.import_preview import ImportPreviewDialog
from portman.repository_v09 import RepositoryV09

CASH = "IBAN DE71200411330476492440"
REAL_NOTICES = {
    "593399": Path(r"C:\Users\chris\Desktop\history\comdirect\Steuermitteilungen\Steuermitteilung_WKN_593399(ISH.S.EUROP.MID_200_U.ETF)_vom_27.04.2017_B8A274.pdf"),
    "A0D8QZ": Path(r"C:\Users\chris\Desktop\history\comdirect\Steuermitteilungen\Steuermitteilung_WKN_A0D8QZ(ISH.S.EUR.SMALL_200_U.ETF)_vom_27.04.2017_89EA7C.pdf"),
    "A0D8Q4": Path(r"C:\Users\chris\Desktop\history\comdirect\Steuermitteilungen\Steuermitteilung_WKN_A0D8Q4(IS.DJ_U.S.SELEC.DIV.U.ETF)_vom_27.04.2017_595FEB.pdf"),
}


def tax_batch(path="historical-tax.pdf", account="comdirect Depot", cash=CASH,
              external="tax-event", paid="0.00"):
    return ImportBatch(path, path + "-hash", source_sheet="PDF", pdf_text="comdirect bank AG",
        account_names=[account], tax_events=[TaxEvent(
            external, account, "investment_ausschuettung_inland", "2017-04-27",
            tax_year="2017", income_year="2017", security_ref="DE0005933998",
            taxable_income="0.00", paid_taxes=paid, cash_account=cash)])


def save_cash(repo, name=CASH):
    repo.save_account(name, {"kind": "Verrechnungskonto", "institution": "comdirect",
                            "iban": name.removeprefix("IBAN ")})
    return account_key(name)


def save_depot(repo, name, cash_key):
    repo.save_account(name, {"kind": "Depot", "institution": "comdirect",
                             "cash_account_key": cash_key})
    return account_key(name)


def suggestion(repo, batch):
    return next(item for item in repo.import_account_suggestions(batch)
                if item["name"] == "comdirect Depot")


def test_unique_cash_link_suggests_exactly_one_depot(tmp_path):
    repo = RepositoryV09(tmp_path / "unique.sqlite", backups=False)
    try:
        cash_key = save_cash(repo)
        depot_key = save_depot(repo, "Depot Ziel", cash_key)
        item = suggestion(repo, tax_batch())
        assert item["target_key"] == depot_key
        assert item["required_kind"] == "Depot"
        assert item["reason"] == "Depot über eindeutig erkanntes Verrechnungskonto vorgeschlagen"
    finally:
        repo.close()


def test_preview_has_only_depot_row_and_preselects_linked_target(tmp_path):
    QApplication.instance() or QApplication([])
    repo = RepositoryV09(tmp_path / "preview.sqlite", backups=False)
    try:
        cash_key = save_cash(repo)
        depot_key = save_depot(repo, "Depot Ziel", cash_key)
        dialog = ImportPreviewDialog(repo, [tax_batch()])
        assert len(dialog.mapping_rows) == 1
        _index, source, combo, _remember = dialog.mapping_rows[0]
        assert source["name"] == "comdirect Depot"
        assert source["kinds"] == {"Steuerereignisse"}
        assert combo.currentData() == depot_key
        dialog.close()
    finally:
        repo.close()


def test_shared_cash_link_requires_manual_depot_choice(tmp_path):
    repo = RepositoryV09(tmp_path / "ambiguous.sqlite", backups=False)
    try:
        cash_key = save_cash(repo)
        save_depot(repo, "Depot Eins", cash_key)
        save_depot(repo, "Depot Zwei", cash_key)
        item = suggestion(repo, tax_batch())
        assert item["target_key"] is None
        assert "Mehrere Depots" in item["reason"]
    finally:
        repo.close()


@pytest.mark.parametrize("setup, expected", [("no-cash", "Verrechnungskonto"),
                                               ("no-link", "Kein Depot")])
def test_missing_cash_or_depot_link_requires_manual_choice(tmp_path, setup, expected):
    repo = RepositoryV09(tmp_path / f"{setup}.sqlite", backups=False)
    try:
        if setup == "no-link":
            save_cash(repo)
        item = suggestion(repo, tax_batch())
        assert item["target_key"] is None
        assert expected in item["reason"]
    finally:
        repo.close()


def test_explicit_depot_number_keeps_existing_matching_path(tmp_path):
    repo = RepositoryV09(tmp_path / "explicit.sqlite", backups=False)
    try:
        repo.save_account("Depot 4764924", {"kind": "Depot", "institution": "comdirect",
                                             "number": "4764924"})
        batch = tax_batch(account="Depot 476492400")
        item = repo.import_account_suggestions(batch)[0]
        assert item["target_key"] == "depot 4764924"
        assert "Unterkontokennung" in item["reason"]
    finally:
        repo.close()


def test_saved_import_rule_has_precedence(tmp_path):
    repo = RepositoryV09(tmp_path / "rule.sqlite", backups=False)
    try:
        cash_key = save_cash(repo)
        first_key = save_depot(repo, "Depot Regel", cash_key)
        save_depot(repo, "Depot Zweite Wahl", cash_key)
        first = tax_batch()
        first.account_assignments = {account_key("comdirect Depot"): first_key}
        first.remember_assignments = [account_key("comdirect Depot")]
        assert repo.commit_batches([first])[0]["status"] == "imported"
        item = suggestion(repo, tax_batch(external="another-event"))
        assert item["target_key"] == first_key
        assert item["reason"] == "Gespeicherte Importregel"
    finally:
        repo.close()


@pytest.mark.parametrize("wkn", tuple(REAL_NOTICES))
def test_real_historical_notice_is_cash_neutral_and_maps_to_linked_depot(tmp_path, wkn):
    path = REAL_NOTICES[wkn]
    if not path.exists():
        pytest.skip("private historical comdirect notice is not available")
    parsed = parse_pdf(path, allow_ocr=False)
    assert parsed.errors == []
    assert parsed.securities[0].wkn == wkn
    assert parsed.account_names == ["comdirect Depot"]
    assert len(parsed.tax_events) == 1 and parsed.transactions == []
    event = parsed.tax_events[0]
    assert event.account == "comdirect Depot"
    assert event.cash_account.startswith("IBAN DE")
    assert event.paid_taxes == "0.00"

    repo = RepositoryV09(tmp_path / f"real-{wkn}.sqlite", backups=False)
    try:
        cash_key = save_cash(repo, event.cash_account)
        depot_key = save_depot(repo, "Depot Historisch", cash_key)
        item = suggestion(repo, parsed)
        assert item["target_key"] == depot_key
        assert len(repo.import_account_suggestions(parsed)) == 1

        prepared = deepcopy(parsed)
        prepared.path = f"historical-{wkn}.pdf"
        prepared.documents = []
        prepared.account_assignments = {account_key("comdirect Depot"): depot_key}
        first = repo.commit_batches([prepared])[0]
        assert first["status"] == "imported"
        assert repo.transactions() == []
        repeated = repo.commit_batches([deepcopy(prepared)])[0]
        assert repeated["status"] == "duplicate"
        assert repo.transactions() == [] and len(repo.tax_events()) == 1
    finally:
        repo.close()


def test_apply_reports_real_repository_error_without_partial_commit(tmp_path):
    repo = RepositoryV09(tmp_path / "errors.sqlite", backups=False)
    job = SimpleNamespace(isInterruptionRequested=lambda: False,
                          progress=SimpleNamespace(emit=lambda *_: None))
    try:
        repo.save_account("Depot Test", {"kind": "Depot", "institution": "comdirect"})
        original = ImportBatch("first.pdf", "first", tax_events=[TaxEvent(
            "advance-first", "Depot Test", "vorabpauschale", "2021-01-04",
            income_year="2020", security_ref="IE00BKM4GZ66", taxable_income="10.00")])
        assert repo.commit_batches([original])[0]["status"] == "imported"
        changed = ImportBatch("changed.pdf", "changed", tax_events=[TaxEvent(
            "advance-changed", "Depot Test", "vorabpauschale", "2021-01-04",
            income_year="2020", security_ref="IE00BKM4GZ66", taxable_income="11.00")])
        direct = repo.commit_batches([deepcopy(changed)])[0]
        assert direct["status"] == "error"
        assert direct["errors"] == [
            "Für IE00BKM4GZ66 im Depot Depot Test ist für das Ertragsjahr 2020 bereits eine Vorabpauschale gespeichert."]
        with pytest.raises(ValueError, match="bereits eine Vorabpauschale"):
            with transaction(repo, commit=True):
                ImportSession.apply(None, repo, job, ([changed], []))
        assert len(repo.tax_events()) == 1
    finally:
        repo.close()
