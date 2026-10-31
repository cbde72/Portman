from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from portman_parsers.api import CashMovement, CashStatus, DepotAccountLink, Issue, IssueNature, IssueSeverity, MissingValue
from portman_parsers.utilities import stable_id


@dataclass(frozen=True, slots=True)
class AccountResolution:
    account_id: str | None
    issues: tuple[Issue, ...] = ()


def resolve_depot_account(links: tuple[DepotAccountLink, ...], depot_id: str, on_date: date,
                          role: str = "SETTLEMENT", explicit_account_id: str | None = None) -> AccountResolution:
    candidates = []
    for link in links:
        if link.depot_id != depot_id or str(link.role.value) != role:
            continue
        start = link.valid_from.value
        end = link.valid_until.value
        if not isinstance(start, MissingValue) and on_date < start or not isinstance(end, MissingValue) and on_date > end:
            continue
        candidates.append(link)
    if explicit_account_id:
        if candidates and explicit_account_id not in {item.account_id for item in candidates}:
            issue = Issue(stable_id("issue", depot_id, explicit_account_id, on_date),
                          "CONFLICTING_ACCOUNT_ASSIGNMENT", IssueSeverity.ERROR,
                          "Explicit transaction account conflicts with depot-account links.",
                          nature=IssueNature.CONFIRMED_DEVIATION)
            return AccountResolution(None, (issue,))
        return AccountResolution(explicit_account_id)
    defaults = [item for item in candidates if item.is_default.value is True]
    selected = defaults or candidates
    if len(selected) == 1:
        return AccountResolution(selected[0].account_id)
    code = "ACCOUNT_ASSIGNMENT_MISSING" if not selected else "ACCOUNT_ASSIGNMENT_AMBIGUOUS"
    message = "No settlement account is evidenced." if not selected else "Multiple settlement accounts are possible."
    return AccountResolution(None, (Issue(stable_id("issue", depot_id, on_date, code), code,
                                          IssueSeverity.WARNING, message,
                                          nature=IssueNature.UNSECURED_ASSIGNMENT),))


def validate_internal_transfer(movements: tuple[CashMovement, ...]) -> tuple[Issue, ...]:
    groups: dict[str, list[CashMovement]] = {}
    for movement in movements:
        if movement.transfer_id:
            groups.setdefault(movement.transfer_id, []).append(movement)
    issues = []
    for transfer_id, items in groups.items():
        if len(items) == 1:
            issues.append(Issue(stable_id("issue", transfer_id, "partial"), "TRANSFER_COUNTERPART_MISSING",
                                IssueSeverity.INFO, "Only one evidenced side of the internal transfer is known.",
                                nature=IssueNature.MISSING_INFORMATION))
        elif len(items) != 2 or sum((item.amount for item in items), Decimal()) != 0:
            issues.append(Issue(stable_id("issue", transfer_id, "mismatch"), "TRANSFER_MISMATCH",
                                IssueSeverity.ERROR, "Internal transfer sides do not cancel.",
                                nature=IssueNature.MATHEMATICAL_INCONSISTENCY))
    return tuple(issues)


def deduplicate_cash_movements(movements: tuple[CashMovement, ...]) -> tuple[CashMovement, ...]:
    """Prefer evidenced ACTUAL cash over EXPECTED settlement with the same transfer id."""
    groups: dict[str, list[CashMovement]] = {}
    standalone = []
    for movement in movements:
        if movement.transfer_id:
            groups.setdefault(movement.transfer_id, []).append(movement)
        else:
            standalone.append(movement)
    for items in groups.values():
        actual = [item for item in items if item.status == CashStatus.ACTUAL]
        standalone.extend(actual or items)
    return tuple(sorted(standalone, key=lambda item: item.movement_id))

