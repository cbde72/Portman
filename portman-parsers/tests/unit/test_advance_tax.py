from datetime import date
from decimal import Decimal

import pytest

from portman_parsers.api import (
    CashMovement, CashMovementType, CashStatus, MissingValue, StatutoryBaseRate,
    TaxApprovalStatus, TaxEvent, TaxRuleSet,
)
from portman_parsers.validation import deduplicate_tax_events, validate_advance_tax


def rules(*, church=MissingValue.UNKNOWN, bank=None):
    rate = StatutoryBaseRate(2025, Decimal("0.02"), "BMF-2025", date(2025, 1, 2))
    return TaxRuleSet(2025, rate, church_tax_rate=church, bank_id=bank,
                      source_reference="BMF-Schreiben-2025")


def event(**changes):
    values = dict(
        tax_event_id="tax-1", event_id="event-1", kind="ADVANCE_TAX",
        depot_id="depot-1", isin="DE000TEST001", tax_year=2025,
        accrual_date=date(2026, 1, 2), bank_id="bank-1", evidence_ids=("ev-1",),
        start_value=Decimal("10000"), end_value=Decimal("11000"),
        distributions=Decimal("0"), partial_exemption_rate=Decimal("0.30"),
        exemption_order_used=Decimal("0"), loss_offset_used=Decimal("0"),
        acquisition_date=date(2024, 6, 1), approval_status=TaxApprovalStatus.SYNTHETIC_ONLY,
    )
    values.update(changes)
    return TaxEvent(**values)


def test_calculates_basis_partial_exemption_and_separate_components():
    result = validate_advance_tax(event(), rules())
    assert result.calculation.base_yield == Decimal("140.0000")
    assert result.calculation.assessment_basis == Decimal("140.0000")
    assert result.calculation.advance_before_partial_exemption == Decimal("140.0000")
    assert result.calculation.taxable_amount == Decimal("98.000000")
    assert result.calculation.assessed_tax_liability == Decimal("25.84750000000")
    assert [part.kind for part in result.calculation.expected_components] == [
        "CAPITAL_GAINS_TAX", "SOLIDARITY_SURCHARGE"]
    assert result.carryforward.taxed_advance_amount == Decimal("140.0000")


@pytest.mark.parametrize(("exemption", "expected"), [
    ("0", "140"), ("0.30", "98"), ("0.60", "56"), ("0.80", "28")])
def test_supports_different_partial_exemptions(exemption, expected):
    result = validate_advance_tax(event(partial_exemption_rate=Decimal(exemption)), rules())
    assert result.calculation.taxable_amount == Decimal(expected)


def test_acquisition_during_year_reduces_base_yield_proportionally():
    result = validate_advance_tax(event(acquisition_date=date(2025, 7, 10)), rules())
    assert result.calculation.pro_rata_factor == Decimal("0.5")
    assert result.calculation.base_yield == Decimal("70.00000")


def test_distributions_and_appreciation_cap_limit_advance():
    distributed = validate_advance_tax(event(distributions=Decimal("100")), rules())
    capped = validate_advance_tax(event(end_value=Decimal("10040")), rules())
    assert distributed.calculation.advance_before_partial_exemption == Decimal("40.0000")
    assert capped.calculation.appreciation_cap == Decimal("40")
    assert capped.calculation.advance_before_partial_exemption == Decimal("40")


def test_fsa_and_loss_offsets_remain_separate_and_can_remove_tax_burden():
    result = validate_advance_tax(event(exemption_order_used=Decimal("60"),
                                        loss_offset_used=Decimal("38")), rules())
    assert result.calculation.taxable_amount == Decimal("98.000000")
    assert result.calculation.assessed_tax_liability == Decimal("0.000000000")
    assert result.calculation.expected_components[0].amount == Decimal("0.00000000")


def test_missing_offsets_are_not_assumed_to_be_zero():
    result = validate_advance_tax(event(exemption_order_used=MissingValue.UNKNOWN), rules())
    assert result.calculation.assessed_tax_liability is MissingValue.UNKNOWN
    assert "ADVANCE_TAX_OFFSETS_UNKNOWN" in {issue.code for issue in result.issues}


def test_missing_calculation_input_stays_unknown():
    result = validate_advance_tax(event(acquisition_date=MissingValue.NOT_FOUND), rules())
    assert result.calculation.base_yield is MissingValue.UNKNOWN
    assert result.calculation.taxable_amount is MissingValue.UNKNOWN
    assert "ADVANCE_TAX_ACQUISITION_DATE_MISSING" in {issue.code for issue in result.issues}


def test_advance_tax_without_withholding_creates_no_cash_movement():
    result = validate_advance_tax(event(actually_withheld_tax=Decimal("0")), rules())
    assert not any(issue.code.startswith("ADVANCE_TAX_CASH") for issue in result.issues)
    assert not hasattr(result, "cash_movements")


def test_evidenced_withholding_must_match_real_account_debit():
    tax = event(account_id="giro-1", actually_withheld_tax=Decimal("25.85"),
                cash_movement_id="cash-1", booking_date=date(2026, 1, 3),
                value_date=date(2026, 1, 4))
    cash = CashMovement("cash-1", "event-1", Decimal("-25.85"), "EUR", CashStatus.ACTUAL,
                        account_id="giro-1", movement_type=CashMovementType.TAX_DEBIT,
                        evidence_ids=("statement-ev",))
    result = validate_advance_tax(tax, rules(), (cash,))
    assert not any(issue.code.startswith("ADVANCE_TAX_CASH") for issue in result.issues)
    assert tax.accrual_date != tax.booking_date != tax.value_date


def test_withholding_does_not_assume_settlement_account():
    result = validate_advance_tax(event(actually_withheld_tax=Decimal("10")), rules())
    codes = {issue.code for issue in result.issues}
    assert "ADVANCE_TAX_DEBIT_ACCOUNT_MISSING" in codes
    assert "ADVANCE_TAX_CASH_EVIDENCE_MISSING" in codes


def test_extracted_values_are_preserved_and_differences_are_separate():
    tax = event(advance_before_partial_exemption=Decimal("141"), taxable_amount=Decimal("99"))
    result = validate_advance_tax(tax, rules())
    assert tax.advance_before_partial_exemption == Decimal("141")
    assert dict(result.calculation.differences) == {
        "advance_before_partial_exemption": Decimal("1.0000"),
        "taxable_amount": Decimal("1.000000"),
    }


def test_unconfirmed_reference_calculation_is_not_approved():
    incomplete = TaxRuleSet(2025, StatutoryBaseRate(2025, Decimal("0.02"), "rate-source"))
    result = validate_advance_tax(event(approval_status=TaxApprovalStatus.REFERENCE_CONFIRMED), incomplete)
    assert result.calculation.approval_status is TaxApprovalStatus.NOT_APPROVED


def test_bank_and_year_specific_rules_are_checked():
    result = validate_advance_tax(event(bank_id="other"), rules(bank="bank-1"))
    assert "ADVANCE_TAX_RULE_BANK_MISMATCH" in {issue.code for issue in result.issues}


def test_deduplicates_notice_and_statement_tax_event_without_cash_duplication():
    second = event(tax_event_id="tax-2", event_id="event-2", evidence_ids=("ev-2",))
    result = deduplicate_tax_events((event(), second))
    assert len(result.events) == 1
    assert result.duplicate_ids == (("tax-1", "tax-2"),)
    assert result.issues[0].code == "DUPLICATE_TAX_EVENT"


def test_carryforward_is_tax_history_not_security_movement():
    result = validate_advance_tax(event(), rules())
    assert result.carryforward.isin == "DE000TEST001"
    assert set(result.carryforward.evidence_ids) == {"ev-1"}
    assert result.carryforward.__class__.__name__ != "SecurityMovement"
