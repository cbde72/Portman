"""GUI-independent projection backing the future 'Gebühren & Kosten' tab."""

from datetime import date

from portman_parsers.api import FeeEffect, ParsedDocument, to_json_compatible
from portman_parsers.validation import aggregate_fees, deduplicate_fees, validate_fee


def fee_cost_view(result: ParsedDocument, *, bank_id: str | None = None,
                  depot_id: str | None = None, account_id: str | None = None,
                  date_from: date | None = None, date_to: date | None = None) -> dict[str, object]:
    fees = tuple(fee for event in result.events for fee in event.fee_events)
    filtered = tuple(fee for fee in fees
                     if (not bank_id or fee.bank_id == bank_id)
                     and (not depot_id or fee.depot_id == depot_id)
                     and (not account_id or fee.account_id == account_id)
                     and (not date_from or fee.fee_date >= date_from)
                     and (not date_to or fee.fee_date <= date_to))
    deduplication = deduplicate_fees(filtered)
    evidence = {item.evidence_id: item for item in result.evidence}
    warnings = list(deduplication.issues)
    for fee in deduplication.fees:
        warnings.extend(validate_fee(fee, set(evidence)))
    booked = [fee for fee in deduplication.fees if fee.effect in {
        FeeEffect.ACTUAL_BOOKED, FeeEffect.INCLUDED_IN_SETTLEMENT,
        FeeEffect.REFUND, FeeEffect.REVERSAL}]
    informational = [fee for fee in deduplication.fees if fee.effect in {
        FeeEffect.INFORMATIONAL, FeeEffect.ESTIMATED}]
    documents = {fee.fee_id: [to_json_compatible(evidence[item]) for item in fee.evidence_ids
                              if item in evidence]
                 for fee in deduplication.fees}
    return to_json_compatible({
        "fees": deduplication.fees,
        "booked_fees": booked,
        "informational_fees": informational,
        "fees_per_transaction": aggregate_fees(
            deduplication.fees, group_by=("transaction_id", "category"),
            date_from=date_from, date_to=date_to, include_non_actual=True),
        "bank_comparison": aggregate_fees(
            deduplication.fees, group_by=("bank_id", "category"),
            date_from=date_from, date_to=date_to),
        "document_evidence": documents,
        "duplicate_pairs": deduplication.duplicate_fee_ids,
        "warnings": tuple(warnings),
    })

