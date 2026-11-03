from datetime import date
from decimal import Decimal

import pytest

from portman_parsers.api import (
    AllocationStatus,
    CostEvent,
    CostInformationType,
    FeeAllocation,
    FeeEffect,
    FeeEvent,
    FinancialEvent,
)
from portman_parsers.validation import (
    aggregate_fees,
    deduplicate_fees,
    validate_event,
    validate_fee,
    validate_trade_settlement,
)


DAY = date(2026, 10, 30)


def fee(fee_id="fee", amount="2.00", effect=FeeEffect.INCLUDED_IN_SETTLEMENT,
        currency="EUR", document="doc-1", reference="order-1", bank="bank-a", **kwargs):
    return FeeEvent(fee_id, "trading", kwargs.pop("subcategory", "commission"), Decimal(amount),
                    currency, DAY, effect, document, bank, external_reference=reference,
                    evidence_ids=(f"evidence-{fee_id}",), **kwargs)


def codes(issues):
    return {item.code for item in issues}


def test_buy_and_sell_with_multiple_fee_components_reconcile():
    fees = (fee("commission", "2.00", subcategory="commission"),
            fee("venue", "1.00", subcategory="venue", reference="order-1-venue"))
    assert not validate_trade_settlement(
        transaction_id="buy", side="BUY", market_value=Decimal("100"), fees=fees,
        taxes=Decimal("1"), net_settlement=Decimal("-104"), currency="EUR")
    assert not validate_trade_settlement(
        transaction_id="sell", side="SELL", market_value=Decimal("100"), fees=fees,
        taxes=Decimal("1"), net_settlement=Decimal("96"), currency="EUR")


def test_trade_settlement_contradiction_is_mathematical_issue():
    issues = validate_trade_settlement(
        transaction_id="buy", side="BUY", market_value=Decimal("100"), fees=(fee(),),
        taxes=Decimal("1"), net_settlement=Decimal("-99"), currency="EUR")
    assert codes(issues) == {"TRADE_SETTLEMENT_MISMATCH"}
    assert issues[0].nature.value == "MATHEMATICAL_INCONSISTENCY"


@pytest.mark.parametrize("information_type", [
    CostInformationType.MIFID_EX_ANTE, CostInformationType.MIFID_EX_POST])
def test_mifid_cost_information_is_cash_neutral(information_type):
    cost = CostEvent("cost", "event", "projected", Decimal("20"), "EUR",
                     informational=True, information_type=information_type,
                     evidence_ids=("evidence",), document_id="doc")
    event = FinancialEvent("event", "doc", "MIFID_COST_INFORMATION", cost_events=(cost,))
    assert not validate_event(event)


def test_same_fee_in_trade_and_account_statement_is_counted_once():
    trade = fee("trade-fee", effect=FeeEffect.INCLUDED_IN_SETTLEMENT, document="trade-doc")
    booked = fee("account-fee", effect=FeeEffect.ACTUAL_BOOKED, document="statement-doc")
    result = deduplicate_fees((trade, booked))
    assert [item.fee_id for item in result.fees] == ["account-fee"]
    assert result.duplicate_fee_ids == (("account-fee", "trade-fee"),)
    assert codes(result.issues) == {"DUPLICATE_FEE"}


def test_fee_refund_and_reversal_reduce_cost_without_negative_source_amount():
    original = fee("original", "10", FeeEffect.ACTUAL_BOOKED, reference="original")
    refund = fee("refund", "3", FeeEffect.REFUND, reference="refund")
    reversal = fee("reversal", "10", FeeEffect.REVERSAL, reference="reversal",
                   reverses_fee_id=original.fee_id)
    aggregate = aggregate_fees((original, refund, reversal))[0]
    assert aggregate.amount == Decimal("-3")
    assert original.amount > 0 and refund.economic_amount < 0 and reversal.economic_amount < 0


def test_foreign_currency_fees_are_not_added_without_conversion():
    aggregates = aggregate_fees((fee("eur", currency="EUR", reference="eur"),
                                 fee("usd", currency="USD", reference="usd")))
    assert {(item.currency, item.amount) for item in aggregates} == {
        ("EUR", Decimal("2.00")), ("USD", Decimal("2.00"))}
    issues = validate_trade_settlement(
        transaction_id="trade", side="BUY", market_value=Decimal("100"),
        fees=(fee("usd", currency="USD"),), taxes=Decimal("0"),
        net_settlement=Decimal("-102"), currency="EUR")
    assert codes(issues) == {"FEE_CURRENCY_CONVERSION_MISSING"}


def test_missing_bank_and_unsecured_assignment_have_distinct_quality_natures():
    allocation = FeeAllocation("DEPOT", "depot", AllocationStatus.UNSECURED, ("evidence",))
    item = fee(bank="", allocations=(allocation,))
    issues = validate_fee(item)
    assert codes(issues) == {"FEE_BANK_MISSING", "FEE_ASSIGNMENT_UNSECURED"}
    assert {issue.nature.value for issue in issues} == {"MISSING_INFORMATION", "UNSECURED_ASSIGNMENT"}


def test_one_fee_can_target_transaction_depot_account_and_security_without_multiplication():
    allocations = (
        FeeAllocation("TRANSACTION", "tx", AllocationStatus.VERIFIED),
        FeeAllocation("DEPOT", "depot", AllocationStatus.VERIFIED),
        FeeAllocation("ACCOUNT", "account", AllocationStatus.VERIFIED),
        FeeAllocation("SECURITY", "security", AllocationStatus.VERIFIED),
    )
    item = fee(depot_id="depot", account_id="account", security_id="security",
               transaction_id="tx", allocations=allocations)
    aggregate = aggregate_fees((item,), group_by=("bank_id",))[0]
    assert len(item.allocations) == 4
    assert aggregate.amount == item.amount
    assert aggregate.fee_ids == (item.fee_id,)


def test_aggregation_supports_bank_depot_account_security_category_and_period():
    fees = (
        fee("a", "2", bank="bank-a", depot_id="d1", account_id="a1", security_id="s1",
            transaction_id="t1", reference="a"),
        fee("b", "3", bank="bank-b", depot_id="d2", account_id="a2", security_id="s2",
            transaction_id="t2", reference="b"),
    )
    result = aggregate_fees(
        fees, group_by=("bank_id", "depot_id", "account_id", "security_id", "category"),
        date_from=DAY, date_to=DAY)
    assert len(result) == 2
    assert {item.amount for item in result} == {Decimal("2"), Decimal("3")}


def test_informational_and_estimated_costs_are_excluded_from_economic_default():
    info = fee("info", effect=FeeEffect.INFORMATIONAL, reference="info")
    estimate = fee("estimate", effect=FeeEffect.ESTIMATED, reference="estimate")
    assert aggregate_fees((info, estimate)) == ()
    assert len(aggregate_fees((info, estimate), include_non_actual=True)) == 1

