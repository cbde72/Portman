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
    for event in result.events:
        issues.extend(validate_event(event))
        for evidence_id in event.evidence_ids:
            if evidence_id not in known_evidence:
                issues.append(Issue(
                    stable_id("issue", event.event_id, evidence_id),
                    "EVIDENCE_REFERENCE_MISSING", IssueSeverity.ERROR,
                    f"Event {event.event_id} references unknown evidence {evidence_id}.",
                    evidence_id=evidence_id, event_id=event.event_id))
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
        for evidence_id in tax.evidence_ids:
            if evidence_id not in known_evidence:
                issues.append(Issue(
                    stable_id("issue", tax.tax_event_id, evidence_id),
                    "TAX_EVIDENCE_REFERENCE_MISSING", IssueSeverity.ERROR,
                    f"Tax event {tax.tax_event_id} references unknown evidence {evidence_id}.",
                    evidence_id=evidence_id, event_id=tax.event_id))
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

