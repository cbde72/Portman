"""Bank-independent validation of explicitly modeled economic effects."""

from decimal import Decimal

from portman_parsers.api import FinancialEvent, Issue, IssueSeverity
from portman_parsers.utilities import stable_id

from .money import CENT, within_tolerance


def _issue(event: FinancialEvent, code: str, severity: IssueSeverity, message: str) -> Issue:
    return Issue(stable_id("issue", event.event_id, code), code, severity, message,
                 event_id=event.event_id)


def validate_event(event: FinancialEvent) -> tuple[Issue, ...]:
    issues: list[Issue] = []
    cash_ids = {item.movement_id for item in event.cash_movements}
    security_ids = {item.movement_id for item in event.security_movements}
    if len(cash_ids) != len(event.cash_movements) or len(security_ids) != len(event.security_movements):
        issues.append(_issue(event, "DUPLICATE_MOVEMENT_ID", IssueSeverity.CRITICAL,
                             "Movement identities must be unique within an event."))
    currencies = {item.currency for item in event.cash_movements}
    if len(currencies) > 1:
        issues.append(_issue(event, "CASH_MULTIPLE_CURRENCIES", IssueSeverity.WARNING,
                             "Cash movements use multiple currencies; explicit FX evidence is required."))

    for tax in event.tax_events:
        if tax.cash_movement_id and tax.cash_movement_id not in cash_ids:
            issues.append(_issue(event, "TAX_CASH_REFERENCE_MISSING", IssueSeverity.ERROR,
                                 f"Tax event {tax.tax_event_id} references an unknown cash movement."))
    for cost in event.cost_events:
        if cost.cash_movement_id and cost.cash_movement_id not in cash_ids:
            issues.append(_issue(event, "COST_CASH_REFERENCE_MISSING", IssueSeverity.ERROR,
                                 f"Cost event {cost.cost_event_id} references an unknown cash movement."))
        if cost.informational and cost.cash_movement_id:
            issues.append(_issue(event, "INFORMATIONAL_COST_HAS_CASH", IssueSeverity.CRITICAL,
                                 "An informational cost disclosure must not create cash movement."))
    for movement in event.cash_movements:
        if movement.linked_security_movement_id and movement.linked_security_movement_id not in security_ids:
            issues.append(_issue(event, "SECURITY_MOVEMENT_REFERENCE_MISSING", IssueSeverity.ERROR,
                                 f"Cash movement {movement.movement_id} references an unknown security movement."))
    for movement in event.security_movements:
        if movement.linked_cash_movement_id and movement.linked_cash_movement_id not in cash_ids:
            issues.append(_issue(event, "CASH_MOVEMENT_REFERENCE_MISSING", IssueSeverity.ERROR,
                                 f"Security movement {movement.movement_id} references an unknown cash movement."))

    kind = event.kind.upper()
    actual_movements = tuple(item for item in event.cash_movements if item.status.value == "ACTUAL")
    actual_cash = sum((item.amount for item in actual_movements), Decimal("0"))
    if kind == "BUY" and actual_movements and actual_cash >= 0:
        issues.append(_issue(event, "BUY_CASH_SIGN", IssueSeverity.ERROR,
                             "A documented purchase settlement must be a negative cash outflow."))
    if kind in {"SELL", "DIVIDEND"} and actual_movements and actual_cash <= 0:
        issues.append(_issue(event, f"{kind}_CASH_SIGN", IssueSeverity.ERROR,
                             f"A documented {kind.lower()} settlement must be a positive cash inflow."))
    if kind in {"ADVANCE_TAX", "MIFID_COST_INFORMATION", "POSITION_SNAPSHOT"}:
        if kind != "ADVANCE_TAX" and event.cash_movements:
            issues.append(_issue(event, f"{kind}_UNEXPECTED_CASH", IssueSeverity.CRITICAL,
                                 "This informational/non-transaction event must not create cash movement."))
        if kind == "ADVANCE_TAX" and any(not tax.cash_movement_id for tax in event.tax_events) \
                and event.cash_movements:
            issues.append(_issue(event, "ADVANCE_TAX_UNLINKED_CASH", IssueSeverity.CRITICAL,
                                 "Advance-tax basis does not justify an unlinked cash movement."))
    return tuple(issues)


def validate_gross_net(event: FinancialEvent, gross: Decimal, net: Decimal,
                       taxes: Decimal, costs: Decimal, tolerance: Decimal = CENT) -> tuple[Issue, ...]:
    expected = gross - taxes - costs
    if within_tolerance(net, expected, tolerance):
        return ()
    return (_issue(event, "GROSS_NET_MISMATCH", IssueSeverity.ERROR,
                   f"Net {net} differs from gross less taxes and costs {expected}."),)


def validate_reversal(original: FinancialEvent, reversal: FinancialEvent) -> tuple[Issue, ...]:
    if reversal.reversal_of_event_id != original.event_id:
        return (_issue(reversal, "REVERSAL_REFERENCE_MISSING", IssueSeverity.ERROR,
                       "Reversal does not reference the original event."),)
    original_cash = sum((item.amount for item in original.cash_movements), Decimal("0"))
    reversal_cash = sum((item.amount for item in reversal.cash_movements), Decimal("0"))
    original_security = sum((item.quantity for item in original.security_movements), Decimal("0"))
    reversal_security = sum((item.quantity for item in reversal.security_movements), Decimal("0"))
    if original_cash + reversal_cash or original_security + reversal_security:
        return (_issue(reversal, "REVERSAL_NOT_NEUTRAL", IssueSeverity.CRITICAL,
                       "Original and reversal do not cancel their economic effects."),)
    return ()

