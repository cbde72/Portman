from datetime import date
from decimal import Decimal

from portman_parsers.api import (
    Account, AccountFunction, AccountType, CashMovement, CashMovementType, CashStatus,
    Depot, DepotAccountLink, FieldValue,
)
from portman_parsers.validation import (
    deduplicate_cash_movements, resolve_depot_account, validate_internal_transfer,
)


def link(link_id, depot, account, *, default=False, start=None, end=None):
    return DepotAccountLink(link_id, depot, account, FieldValue.manual("SETTLEMENT"),
                            FieldValue.manual(start) if start else FieldValue.unknown(),
                            FieldValue.manual(end) if end else FieldValue.unknown(),
                            FieldValue.manual(default))


def test_account_types_and_multiple_functions():
    for kind in AccountType:
        account = Account(kind.value, account_type=FieldValue.manual(kind), functions=(
            FieldValue.manual(AccountFunction.PAYMENT), FieldValue.manual(AccountFunction.SETTLEMENT)))
        assert account.account_type.value == kind
        assert len(account.functions) == 2


def test_separate_settlement_account_and_giro_account_need_no_artificial_account():
    separate = link("l1", "depot", "settlement", default=True)
    giro = link("l2", "depot2", "giro", default=True)
    assert resolve_depot_account((separate,), "depot", date.today()).account_id == "settlement"
    assert resolve_depot_account((giro,), "depot2", date.today()).account_id == "giro"


def test_two_depots_can_share_one_giro_account():
    links = (link("l1", "d1", "giro", default=True), link("l2", "d2", "giro", default=True))
    assert {resolve_depot_account(links, depot, date.today()).account_id for depot in ("d1", "d2")} == {"giro"}


def test_one_depot_with_multiple_accounts_is_ambiguous_without_default():
    result = resolve_depot_account((link("l1", "d", "a1"), link("l2", "d", "a2")), "d", date.today())
    assert result.account_id is None
    assert result.issues[0].code == "ACCOUNT_ASSIGNMENT_AMBIGUOUS"


def test_time_bounded_settlement_account_change():
    links = (link("old", "d", "a1", start=date(2025, 1, 1), end=date(2025, 12, 31)),
             link("new", "d", "a2", start=date(2026, 1, 1)))
    assert resolve_depot_account(links, "d", date(2025, 6, 1)).account_id == "a1"
    assert resolve_depot_account(links, "d", date(2026, 6, 1)).account_id == "a2"


def test_missing_and_conflicting_account_assignment_require_review():
    missing = resolve_depot_account((), "d", date.today())
    conflict = resolve_depot_account((link("l", "d", "a1"),), "d", date.today(), explicit_account_id="a2")
    assert missing.issues[0].code == "ACCOUNT_ASSIGNMENT_MISSING"
    assert conflict.issues[0].code == "CONFLICTING_ACCOUNT_ASSIGNMENT"


def movement(identity, amount, account, transfer, status=CashStatus.ACTUAL):
    return CashMovement(identity, "event", Decimal(amount), "EUR", status, account_id=account,
                        movement_type=CashMovementType.INTERNAL_TRANSFER, transfer_id=transfer)


def test_internal_transfer_two_sides_cancel_and_one_side_is_not_invented():
    outgoing, incoming = movement("out", "-10", "a1", "transfer"), movement("in", "10", "a2", "transfer")
    assert not validate_internal_transfer((outgoing, incoming))
    partial = validate_internal_transfer((outgoing,))
    assert partial[0].code == "TRANSFER_COUNTERPART_MISSING"


def test_actual_account_booking_replaces_expected_trade_settlement_once():
    expected = movement("expected", "-10", "giro", "settlement", CashStatus.EXPECTED)
    actual = movement("actual", "-10", "giro", "settlement", CashStatus.ACTUAL)
    deduplicated = deduplicate_cash_movements((expected, actual))
    assert deduplicated == (actual,)
    assert sum((item.amount for item in deduplicated), Decimal()) == Decimal("-10")
