from portman_parsers.api import Issue, IssueSeverity, ParsedDocument
from portman_parsers.utilities import stable_id

from .cashflows import validate_event
from .fees import deduplicate_fees, validate_fee
from .references import possible_duplicate_events
from .taxes import deduplicate_tax_events


def validate_parsed_document(result: ParsedDocument) -> tuple[Issue, ...]:
    issues = list(result.issues)
    known_evidence = {item.evidence_id for item in result.evidence}
    evidence_by_id = {item.evidence_id: item for item in result.evidence}
    all_fees = tuple(fee for event in result.events for fee in event.fee_events)
    all_taxes = tuple(tax for event in result.events for tax in event.tax_events)
    fee_ids = {fee.fee_id for fee in all_fees}

    def evidence_issues(owner: str, event_id: str | None, evidence_ids) -> None:
        for evidence_id in evidence_ids:
            evidence = evidence_by_id.get(evidence_id)
            if evidence is None:
                issues.append(Issue(
                    stable_id("issue", owner, evidence_id), "EVIDENCE_REFERENCE_MISSING",
                    IssueSeverity.ERROR, f"{owner} references unknown evidence {evidence_id}.",
                    evidence_id=evidence_id, event_id=event_id))
            elif evidence.document_id != result.document_id:
                issues.append(Issue(
                    stable_id("issue", owner, evidence_id, "document"), "EVIDENCE_DOCUMENT_MISMATCH",
                    IssueSeverity.ERROR, f"{owner} references evidence from another document.",
                    evidence_id=evidence_id, event_id=event_id))

    for event in result.events:
        issues.extend(validate_event(event))
        evidence_issues(f"Event {event.event_id}", event.event_id, event.evidence_ids)
        evidence_issues(f"Event {event.event_id} date", event.event_id, event.event_date_evidence_ids)
        if event.reversal_details is not None:
            details = event.reversal_details
            for label, evidence_ids in (
                ("original reference", details.original_reference_evidence_ids),
                ("original ex date", details.original_ex_date_evidence_ids),
                ("original payment date", details.original_payment_date_evidence_ids),
                ("original business date", details.original_business_date_evidence_ids),
                ("original value date", details.original_value_date_evidence_ids),
                ("original booking date", details.original_booking_date_evidence_ids),
                ("original quantity", details.quantity_evidence_ids),
            ):
                evidence_issues(f"Event {event.event_id} reversal {label}", event.event_id, evidence_ids)
        evidence_issues(f"Event {event.event_id} security identity", event.event_id,
                        event.security_identity_evidence_ids)
        evidence_issues(f"Event {event.event_id} bank reference", event.event_id,
                        event.bank_reference_evidence_ids)
        evidence_issues(f"Event {event.event_id} counterparty", event.event_id,
                        event.counterparty_evidence_ids)
        evidence_issues(f"Event {event.event_id} purpose", event.event_id,
                        event.purpose_evidence_ids)
        for exchange_rate in event.exchange_rates:
            evidence_issues(f"Exchange rate {exchange_rate.exchange_rate_id}", event.event_id,
                            exchange_rate.evidence_ids)
        for trade in event.trades:
            evidence_issues(f"Trade {trade.trade_id}", event.event_id, trade.evidence_ids)
            evidence_issues(f"Trade {trade.trade_id} booking date", event.event_id, trade.booking_date_evidence_ids)
        for movement in (*event.cash_movements, *event.security_movements):
            evidence_issues(f"Movement {movement.movement_id}", event.event_id, movement.evidence_ids)
        for tax in event.tax_events:
            evidence_issues(f"Tax event {tax.tax_event_id}", event.event_id, tax.evidence_ids)
            evidence_issues(f"Tax event {tax.tax_event_id} tax year", event.event_id, tax.tax_year_evidence_ids)
            evidence_issues(f"Tax event {tax.tax_event_id} accrual date", event.event_id, tax.accrual_date_evidence_ids)
            evidence_issues(f"Tax event {tax.tax_event_id} exemption consumption", event.event_id,
                            tax.exemption_order_used_evidence_ids)
        for fee in event.fee_events:
            evidence_issues(f"Fee {fee.fee_id}", event.event_id, fee.evidence_ids)
            for allocation in fee.allocations:
                evidence_issues(f"Fee allocation {allocation.target_id}", event.event_id,
                                allocation.evidence_ids)
        for cost in event.cost_events:
            evidence_issues(f"Cost event {cost.cost_event_id}", event.event_id, cost.evidence_ids)
    for first, second in possible_duplicate_events(result.events):
        issues.append(Issue(
            stable_id("issue", first, second), "POSSIBLE_DUPLICATE", IssueSeverity.WARNING,
            f"Events {first} and {second} have the same economic signature.", event_id=second))
    account_ids = {item.account_id for item in result.accounts}
    depot_ids = {item.depot_id for item in result.depots}
    for fee in all_fees:
        issues.extend(validate_fee(fee, known_evidence))
        if any(evidence_by_id[item].document_id != fee.document_id
               for item in fee.evidence_ids if item in evidence_by_id):
            issues.append(Issue(
                stable_id("issue", fee.fee_id, "document"), "FEE_DOCUMENT_EVIDENCE_MISMATCH",
                IssueSeverity.ERROR, f"Fee {fee.fee_id} Evidence belongs to another document.",
                evidence_id=fee.evidence_ids[0]))
        if fee.account_id and fee.account_id not in account_ids:
            issues.append(Issue(
                stable_id("issue", fee.fee_id, "account"), "FEE_ACCOUNT_REFERENCE_MISSING",
                IssueSeverity.ERROR, f"Fee {fee.fee_id} references an unknown account.",
                evidence_id=fee.evidence_ids[0]))
        if fee.depot_id and fee.depot_id not in depot_ids:
            issues.append(Issue(
                stable_id("issue", fee.fee_id, "depot"), "FEE_DEPOT_REFERENCE_MISSING",
                IssueSeverity.ERROR, f"Fee {fee.fee_id} references an unknown depot.",
                evidence_id=fee.evidence_ids[0]))
        if fee.effect.value == "REVERSAL" and fee.reverses_fee_id not in fee_ids:
            issues.append(Issue(
                stable_id("issue", fee.fee_id, "reversal"), "FEE_REVERSAL_REFERENCE_MISSING",
                IssueSeverity.ERROR, f"Fee reversal {fee.fee_id} references an unknown fee.",
                evidence_id=fee.evidence_ids[0]))
    issues.extend(deduplicate_fees(all_fees).issues)
    issues.extend(deduplicate_tax_events(all_taxes).issues)
    for tax in all_taxes:
        if tax.depot_id and tax.depot_id not in depot_ids:
            issues.append(Issue(
                stable_id("issue", tax.tax_event_id, "depot"),
                "TAX_DEPOT_REFERENCE_MISSING", IssueSeverity.ERROR,
                f"Tax event {tax.tax_event_id} references an unknown depot.",
                event_id=tax.event_id))
        if tax.account_id and tax.account_id not in account_ids:
            issues.append(Issue(
                stable_id("issue", tax.tax_event_id, "account"),
                "TAX_ACCOUNT_REFERENCE_MISSING", IssueSeverity.ERROR,
                f"Tax event {tax.tax_event_id} references an unknown account.",
                event_id=tax.event_id))
    for event in result.events:
        for movement in event.cash_movements:
            if movement.account_id and movement.account_id not in account_ids:
                issues.append(Issue(
                    stable_id("issue", movement.movement_id, "account"),
                    "ACCOUNT_REFERENCE_MISSING", IssueSeverity.ERROR,
                    f"Cash movement {movement.movement_id} references unknown account {movement.account_id}.",
                    event_id=event.event_id))
        for movement in event.security_movements:
            if movement.depot_id and movement.depot_id not in depot_ids:
                issues.append(Issue(
                    stable_id("issue", movement.movement_id, "depot"),
                    "DEPOT_REFERENCE_MISSING", IssueSeverity.ERROR,
                    f"Security movement {movement.movement_id} references unknown depot {movement.depot_id}.",
                    event_id=event.event_id))
    return tuple(issues)
