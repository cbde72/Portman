"""Cross-bank fee deduplication, validation, reconciliation and aggregation."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Iterable

from portman_parsers.api import (
    AllocationStatus,
    FeeEffect,
    FeeEvent,
    Issue,
    IssueNature,
    IssueSeverity,
)
from portman_parsers.utilities import stable_id

from .money import CENT, within_tolerance


@dataclass(frozen=True, slots=True)
class FeeDeduplicationResult:
    fees: tuple[FeeEvent, ...]
    duplicate_fee_ids: tuple[tuple[str, str], ...]
    issues: tuple[Issue, ...]


@dataclass(frozen=True, slots=True)
class FeeAggregate:
    dimensions: tuple[tuple[str, str], ...]
    currency: str
    amount: Decimal
    fee_ids: tuple[str, ...]


_EFFECT_PRIORITY = {
    FeeEffect.ACTUAL_BOOKED: 0,
    FeeEffect.INCLUDED_IN_SETTLEMENT: 1,
    FeeEffect.REFUND: 2,
    FeeEffect.REVERSAL: 3,
    FeeEffect.INFORMATIONAL: 4,
    FeeEffect.ESTIMATED: 5,
}


def _identity(fee: FeeEvent) -> tuple[object, ...]:
    reference = fee.external_reference or fee.transaction_id or ""
    return (reference, fee.category, fee.subcategory, fee.amount, fee.currency, fee.fee_date,
            fee.bank_id, fee.depot_id, fee.account_id, fee.security_id)


def deduplicate_fees(fees: Iterable[FeeEvent]) -> FeeDeduplicationResult:
    groups: dict[tuple[object, ...], list[FeeEvent]] = {}
    for fee in fees:
        groups.setdefault(_identity(fee), []).append(fee)
    kept: list[FeeEvent] = []
    duplicates: list[tuple[str, str]] = []
    issues: list[Issue] = []
    for group in groups.values():
        ordered = sorted(group, key=lambda item: (_EFFECT_PRIORITY[item.effect], item.fee_id))
        canonical = ordered[0]
        kept.append(canonical)
        for duplicate in ordered[1:]:
            duplicates.append((canonical.fee_id, duplicate.fee_id))
            issues.append(Issue(
                stable_id("issue", canonical.fee_id, duplicate.fee_id), "DUPLICATE_FEE",
                IssueSeverity.WARNING,
                f"Fee {duplicate.fee_id} duplicates economic cost {canonical.fee_id} and is not counted twice.",
                evidence_id=duplicate.evidence_ids[0]))
    return FeeDeduplicationResult(tuple(sorted(kept, key=lambda item: item.fee_id)),
                                  tuple(sorted(duplicates)), tuple(issues))


def validate_fee(fee: FeeEvent, known_evidence: set[str] | None = None) -> tuple[Issue, ...]:
    issues: list[Issue] = []
    if known_evidence is not None:
        missing = [item for item in fee.evidence_ids if item not in known_evidence]
        if missing:
            issues.append(Issue(
                stable_id("issue", fee.fee_id, "evidence"), "FEE_EVIDENCE_MISSING",
                IssueSeverity.ERROR, f"Fee {fee.fee_id} references missing Evidence {missing[0]}.",
                evidence_id=missing[0], nature=IssueNature.MISSING_INFORMATION))
    if not fee.bank_id:
        issues.append(Issue(
            stable_id("issue", fee.fee_id, "bank"), "FEE_BANK_MISSING", IssueSeverity.WARNING,
            f"Fee {fee.fee_id} has no bank assignment.",
            evidence_id=fee.evidence_ids[0], nature=IssueNature.MISSING_INFORMATION))
    if any(item.status == AllocationStatus.UNSECURED for item in fee.allocations):
        issues.append(Issue(
            stable_id("issue", fee.fee_id, "allocation"), "FEE_ASSIGNMENT_UNSECURED",
            IssueSeverity.WARNING, f"Fee {fee.fee_id} has an unsecured assignment.",
            evidence_id=fee.evidence_ids[0], nature=IssueNature.UNSECURED_ASSIGNMENT))
    if fee.effect in {FeeEffect.INFORMATIONAL, FeeEffect.ESTIMATED} and fee.cash_movement_id:
        issues.append(Issue(
            stable_id("issue", fee.fee_id, "cash"), "NON_ACTUAL_FEE_HAS_CASH",
            IssueSeverity.CRITICAL, "Informational or estimated fees must not create cash movement.",
            evidence_id=fee.evidence_ids[0], nature=IssueNature.CONFIRMED_DEVIATION))
    return tuple(issues)


def validate_trade_settlement(*, transaction_id: str, side: str, market_value: Decimal,
                              fees: Iterable[FeeEvent], taxes: Decimal,
                              net_settlement: Decimal, currency: str,
                              tolerance: Decimal = CENT) -> tuple[Issue, ...]:
    values = (market_value, taxes, net_settlement, tolerance)
    if not all(isinstance(value, Decimal) for value in values):
        raise TypeError("trade settlement validation requires Decimal values")
    relevant = [fee for fee in deduplicate_fees(fees).fees
                if fee.effect == FeeEffect.INCLUDED_IN_SETTLEMENT]
    foreign = [fee for fee in relevant if fee.currency != currency]
    if foreign:
        return (Issue(
            stable_id("issue", transaction_id, "currency"), "FEE_CURRENCY_CONVERSION_MISSING",
            IssueSeverity.ERROR, "Trade fees use a different currency without documented conversion.",
            nature=IssueNature.MISSING_INFORMATION),)
    fee_total = sum((fee.economic_amount for fee in relevant), Decimal("0"))
    normalized_side = side.upper()
    if normalized_side == "BUY":
        expected = -(market_value + fee_total + taxes)
    elif normalized_side == "SELL":
        expected = market_value - fee_total - taxes
    else:
        raise ValueError("trade side must be BUY or SELL")
    if within_tolerance(net_settlement, expected, tolerance):
        return ()
    return (Issue(
        stable_id("issue", transaction_id, "settlement"), "TRADE_SETTLEMENT_MISMATCH",
        IssueSeverity.ERROR,
        f"Settlement {net_settlement} differs from calculated {expected} {currency}.",
        nature=IssueNature.MATHEMATICAL_INCONSISTENCY),)


def aggregate_fees(fees: Iterable[FeeEvent], *, group_by: tuple[str, ...] = ("bank_id",),
                   date_from: date | None = None, date_to: date | None = None,
                   include_non_actual: bool = False) -> tuple[FeeAggregate, ...]:
    allowed = {"bank_id", "depot_id", "account_id", "security_id", "category", "subcategory",
               "transaction_id", "effect"}
    if not set(group_by) <= allowed:
        raise ValueError("unsupported fee aggregation dimension")
    deduplicated = deduplicate_fees(fees).fees
    groups: dict[tuple[tuple[tuple[str, str], ...], str], list[FeeEvent]] = {}
    for fee in deduplicated:
        if date_from and fee.fee_date < date_from or date_to and fee.fee_date > date_to:
            continue
        if not include_non_actual and fee.effect in {FeeEffect.INFORMATIONAL, FeeEffect.ESTIMATED}:
            continue
        dimensions = tuple((name, str(getattr(fee, name) or "")) for name in group_by)
        groups.setdefault((dimensions, fee.currency), []).append(fee)
    result = [FeeAggregate(dimensions, currency,
                           sum((fee.economic_amount for fee in values), Decimal("0")),
                           tuple(sorted(fee.fee_id for fee in values)))
              for (dimensions, currency), values in groups.items()]
    return tuple(sorted(result, key=lambda item: (item.dimensions, item.currency)))

