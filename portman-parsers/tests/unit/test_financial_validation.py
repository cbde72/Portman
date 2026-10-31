from datetime import date
from decimal import Decimal

from portman_parsers.api import (
    CashMovement,
    CashStatus,
    CostEvent,
    FinancialEvent,
    Position,
    PositionSnapshot,
    SecurityMovement,
    TaxComponent,
    TaxEvent,
)
from portman_parsers.validation.cashflows import validate_event, validate_gross_net, validate_reversal


def cash(event_id, value, movement_id="cash"):
    return CashMovement(movement_id, event_id, Decimal(value), "EUR", CashStatus.ACTUAL)


def codes(issues):
    return {item.code for item in issues}


def test_cash_sign_convention_for_buy_and_sell():
    good_buy = FinancialEvent("buy", "doc", "BUY", cash_movements=(cash("buy", "-10"),))
    bad_buy = FinancialEvent("bad", "doc", "BUY", cash_movements=(cash("bad", "10"),))
    good_sell = FinancialEvent("sell", "doc", "SELL", cash_movements=(cash("sell", "10"),))
    assert not validate_event(good_buy)
    assert "BUY_CASH_SIGN" in codes(validate_event(bad_buy))
    assert not validate_event(good_sell)


def test_dividend_net_reconciles_gross_taxes_and_costs():
    event = FinancialEvent("div", "doc", "DIVIDEND", cash_movements=(cash("div", "72"),))
    assert not validate_gross_net(event, Decimal("100"), Decimal("72"),
                                  Decimal("25"), Decimal("3"))
    assert "GROSS_NET_MISMATCH" in codes(validate_gross_net(
        event, Decimal("100"), Decimal("71"), Decimal("25"), Decimal("3")))


def test_advance_tax_basis_does_not_create_cash():
    tax = TaxEvent("tax", "advance", "advance_tax", taxable_basis=Decimal("100"))
    event = FinancialEvent("advance", "doc", "ADVANCE_TAX", tax_events=(tax,))
    assert not validate_event(event)


def test_advance_tax_requires_explicit_link_for_actual_payment():
    movement = cash("advance", "-5")
    tax = TaxEvent("tax", "advance", "advance_tax",
                   (TaxComponent("capital_gains_tax", Decimal("5"), "EUR"),))
    event = FinancialEvent("advance", "doc", "ADVANCE_TAX",
                           cash_movements=(movement,), tax_events=(tax,))
    assert "ADVANCE_TAX_UNLINKED_CASH" in codes(validate_event(event))


def test_mifid_cost_information_has_no_cash_effect():
    cost = CostEvent("cost", "mifid", "projected", Decimal("9"), "EUR",
                     informational=True)
    event = FinancialEvent("mifid", "doc", "MIFID_COST_INFORMATION", cost_events=(cost,))
    assert not validate_event(event)


def test_informational_cost_linked_to_cash_is_critical():
    movement = cash("mifid", "-9")
    cost = CostEvent("cost", "mifid", "projected", Decimal("9"), "EUR",
                     movement.movement_id, informational=True)
    event = FinancialEvent("mifid", "doc", "MIFID_COST_INFORMATION",
                           cash_movements=(movement,), cost_events=(cost,))
    assert {"INFORMATIONAL_COST_HAS_CASH", "MIFID_COST_INFORMATION_UNEXPECTED_CASH"} <= codes(validate_event(event))


def test_position_snapshot_does_not_imply_trade():
    snapshot = PositionSnapshot("snapshot", "doc", "depot", date(2026, 1, 1),
                                (Position("DE0000000001", Decimal("2"), Decimal("20"), "EUR"),))
    assert snapshot.positions[0].quantity == Decimal("2")


def test_reversal_cancels_cash_and_security_effects():
    original = FinancialEvent(
        "original", "doc-1", "BUY", cash_movements=(cash("original", "-10", "c1"),),
        security_movements=(SecurityMovement("s1", "original", "SEC", Decimal("1")),))
    reversal = FinancialEvent(
        "reversal", "doc-2", "REVERSAL", cash_movements=(cash("reversal", "10", "c2"),),
        security_movements=(SecurityMovement("s2", "reversal", "SEC", Decimal("-1")),),
        reversal_of_event_id="original")
    assert not validate_reversal(original, reversal)


def test_non_neutral_reversal_is_critical():
    original = FinancialEvent("original", "doc-1", "DIVIDEND",
                              cash_movements=(cash("original", "10", "c1"),))
    reversal = FinancialEvent("reversal", "doc-2", "REVERSAL",
                              cash_movements=(cash("reversal", "-9", "c2"),),
                              reversal_of_event_id="original")
    assert "REVERSAL_NOT_NEUTRAL" in codes(validate_reversal(original, reversal))

