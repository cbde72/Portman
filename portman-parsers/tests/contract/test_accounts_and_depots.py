from datetime import date
from decimal import Decimal

import pytest

from portman_parsers.api import (
    Account,
    AccountBalance,
    CashMovement,
    CashStatus,
    Depot,
    DepotAccountLink,
    DepotPosition,
    DepotSnapshot,
    Evidence,
    FieldValue,
    FinancialEvent,
    MissingValue,
    ParsedDocument,
    ReviewStatus,
    SecurityMovement,
    ValueSource,
)
from portman_parsers.validation import validate_parsed_document


def pdf(value, evidence="e1", page=1):
    return FieldValue.from_pdf(value, page, evidence)


def evidence():
    return Evidence("e1", "doc", 1, "master_data", "synthetic")


def test_pdf_field_requires_page_and_evidence():
    with pytest.raises(ValueError, match="page and Evidence"):
        FieldValue("4711", ValueSource.PDF)


def test_unknown_property_is_not_guessed():
    account = Account("account-1")
    assert account.iban.value == MissingValue.UNKNOWN
    assert account.iban.source == ValueSource.NOT_PROVIDED


def test_pdf_and_manual_master_data_remain_distinguishable():
    depot = Depot("depot-1", depot_number=pdf("4711"), depot_name=FieldValue.manual("Langfristdepot"))
    assert depot.depot_number.source == ValueSource.PDF
    assert depot.depot_number.review_status == ReviewStatus.UNREVIEWED
    assert depot.depot_name.source == ValueSource.MANUAL
    assert depot.depot_name.review_status == ReviewStatus.VERIFIED


def test_account_and_depot_identity_are_independent():
    depot = Depot("same-bank-depot", bank_name=pdf("Bank"))
    account = Account("same-bank-account", bank_name=pdf("Bank"))
    result = ParsedDocument("result", "doc", "demo", "1", "handler",
                            evidence=(evidence(),), depots=(depot,), accounts=(account,))
    assert result.depots[0].depot_id != result.accounts[0].account_id


def test_multiple_depots_per_bank_are_supported():
    depots = (Depot("depot-1", bank_name=pdf("Bank")), Depot("depot-2", bank_name=pdf("Bank")))
    result = ParsedDocument("result", "doc", "demo", "1", "handler",
                            evidence=(evidence(),), depots=depots)
    assert len(result.depots) == 2


def test_multiple_settlement_accounts_per_depot_are_supported():
    depot = Depot("depot-1", depot_number=pdf("4711"))
    accounts = (Account("cash-1", iban=pdf("DE001")), Account("cash-2", iban=pdf("DE002")))
    links = (
        DepotAccountLink("link-1", depot.depot_id, accounts[0].account_id, pdf("PRIMARY_SETTLEMENT")),
        DepotAccountLink("link-2", depot.depot_id, accounts[1].account_id, pdf("TAX_SETTLEMENT")),
    )
    result = ParsedDocument("result", "doc", "demo", "1", "handler", evidence=(evidence(),),
                            depots=(depot,), accounts=accounts, depot_account_links=links)
    assert {link.account_id for link in result.depot_account_links} == {"cash-1", "cash-2"}


def test_account_balance_preserves_decimal_page_and_review_status():
    account = Account("cash-1")
    balance = AccountBalance("balance-1", account.account_id, pdf(date(2026, 10, 30)),
                             FieldValue.from_pdf(Decimal("123.45"), 1, "e1",
                                                 review_status=ReviewStatus.VERIFIED), pdf("EUR"))
    result = ParsedDocument("result", "doc", "demo", "1", "handler", evidence=(evidence(),),
                            accounts=(account,), account_balances=(balance,))
    assert result.account_balances[0].amount.value == Decimal("123.45")
    assert result.account_balances[0].amount.page_number == 1


def test_depot_snapshot_is_separate_from_events_and_uses_field_evidence():
    depot = Depot("depot-1")
    position = DepotPosition("position-1", pdf("SEC"), pdf(Decimal("2")),
                             market_value=pdf(Decimal("20.00")), currency=pdf("EUR"))
    snapshot = DepotSnapshot("snapshot-1", depot.depot_id, pdf(date(2026, 10, 30)),
                             (position,), pdf(Decimal("20.00")), pdf("EUR"))
    result = ParsedDocument("result", "doc", "demo", "1", "handler", evidence=(evidence(),),
                            depots=(depot,), depot_snapshots=(snapshot,))
    assert not result.events
    assert result.depot_snapshots[0].positions[0].quantity.value == Decimal("2")


def test_links_must_reference_known_depot_and_account():
    link = DepotAccountLink("link", "missing-depot", "missing-account", pdf("SETTLEMENT"))
    with pytest.raises(ValueError, match="known identities"):
        ParsedDocument("result", "doc", "demo", "1", "handler",
                       evidence=(evidence(),), depot_account_links=(link,))


def test_field_evidence_page_must_match():
    depot = Depot("depot", depot_number=FieldValue.from_pdf("4711", 2, "e1"))
    with pytest.raises(ValueError, match="page differs"):
        ParsedDocument("result", "doc", "demo", "1", "handler",
                       evidence=(evidence(),), depots=(depot,))


def test_cash_and_security_movements_link_account_and_depot_without_duplicate_effect():
    depot = Depot("depot")
    account = Account("account")
    cash = CashMovement("cash", "trade", Decimal("-10"), "EUR", CashStatus.ACTUAL,
                        account_id=account.account_id, linked_security_movement_id="security")
    security = SecurityMovement("security", "trade", "SEC", Decimal("1"),
                                depot_id=depot.depot_id, linked_cash_movement_id=cash.movement_id)
    event = FinancialEvent("trade", "doc", "BUY", cash_movements=(cash,),
                           security_movements=(security,))
    result = ParsedDocument("result", "doc", "demo", "1", "handler", events=(event,),
                            depots=(depot,), accounts=(account,))
    assert not validate_parsed_document(result)
    assert len(event.cash_movements) == len(event.security_movements) == 1


def test_broken_movement_link_is_reported():
    account = Account("account")
    cash = CashMovement("cash", "trade", Decimal("-10"), "EUR", CashStatus.ACTUAL,
                        account_id=account.account_id, linked_security_movement_id="missing")
    event = FinancialEvent("trade", "doc", "BUY", cash_movements=(cash,))
    result = ParsedDocument("result", "doc", "demo", "1", "handler",
                            events=(event,), accounts=(account,))
    assert {item.code for item in validate_parsed_document(result)} == {
        "SECURITY_MOVEMENT_REFERENCE_MISSING"}

