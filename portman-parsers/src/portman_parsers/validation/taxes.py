"""Validation and calculation of German fund advance tax events.

Calculations are deliberately separate from extracted values.  This module never
creates cash or security movements.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from portman_parsers.api import (
    AdvanceTaxCalculation, AdvanceTaxCarryforward, CashMovement, CashMovementType,
    CashStatus, Issue, IssueNature, IssueSeverity, MissingValue, TaxApprovalStatus,
    TaxComponent, TaxEvent, TaxRuleSet,
)
from portman_parsers.utilities import stable_id


@dataclass(frozen=True, slots=True)
class AdvanceTaxValidationResult:
    calculation: AdvanceTaxCalculation
    carryforward: AdvanceTaxCarryforward | None
    issues: tuple[Issue, ...]


@dataclass(frozen=True, slots=True)
class TaxDeduplicationResult:
    events: tuple[TaxEvent, ...]
    duplicate_ids: tuple[tuple[str, str], ...]
    issues: tuple[Issue, ...]


def _issue(event: TaxEvent, code: str, message: str, nature: IssueNature,
           severity: IssueSeverity = IssueSeverity.WARNING) -> Issue:
    return Issue(stable_id("issue", event.tax_event_id, code), code, severity, message,
                 evidence_id=event.evidence_ids[0] if event.evidence_ids else None,
                 event_id=event.event_id, nature=nature)


def _known_decimal(value: Decimal | MissingValue) -> Decimal | None:
    return value if isinstance(value, Decimal) else None


def _pro_rata(acquisition: date | MissingValue, tax_year: int) -> Decimal | MissingValue:
    if not isinstance(acquisition, date):
        return MissingValue.UNKNOWN
    if acquisition.year < tax_year:
        return Decimal("1")
    if acquisition.year > tax_year:
        return Decimal("0")
    return Decimal(13 - acquisition.month) / Decimal(12)


def validate_advance_tax(event: TaxEvent, rules: TaxRuleSet,
                         cash_movements: tuple[CashMovement, ...] = ()) -> AdvanceTaxValidationResult:
    """Calculate, compare and corroborate one advance-tax event without mutating it."""
    issues: list[Issue] = []
    if event.tax_year != rules.tax_year:
        issues.append(_issue(event, "ADVANCE_TAX_RULE_YEAR_MISMATCH",
                             "Steuerjahr und Regelwerk stimmen nicht ueberein.",
                             IssueNature.CONFIRMED_DEVIATION, IssueSeverity.ERROR))
    if rules.bank_id and event.bank_id and rules.bank_id != event.bank_id:
        issues.append(_issue(event, "ADVANCE_TAX_RULE_BANK_MISMATCH",
                             "Das bankspezifische Regelwerk passt nicht zur Bank.",
                             IssueNature.CONFIRMED_DEVIATION, IssueSeverity.ERROR))
    for name, value in (("depot", event.depot_id), ("ISIN", event.isin),
                        ("Steuerjahr", event.tax_year), ("Zuflussdatum", event.accrual_date),
                        ("Bank", event.bank_id), ("PDF-Nachweis", event.evidence_ids)):
        if not value:
            issues.append(_issue(event, f"ADVANCE_TAX_{name.upper()}_MISSING",
                                 f"{name} fehlt; der Wert wird nicht geschaetzt.",
                                 IssueNature.MISSING_INFORMATION))

    start = _known_decimal(event.start_value)
    end = _known_decimal(event.end_value)
    distributions = _known_decimal(event.distributions)
    exemption = _known_decimal(event.partial_exemption_rate)
    prorata = _pro_rata(event.acquisition_date, rules.tax_year)
    for name, value in (("START_VALUE", start), ("END_VALUE", end),
                        ("DISTRIBUTIONS", distributions), ("PARTIAL_EXEMPTION", exemption),
                        ("ACQUISITION_DATE", None if isinstance(prorata, MissingValue) else prorata)):
        if value is None:
            issues.append(_issue(event, f"ADVANCE_TAX_{name}_MISSING",
                                 f"{name} fehlt; die Berechnung bleibt unbekannt.",
                                 IssueNature.MISSING_INFORMATION))

    base_yield: Decimal | MissingValue = MissingValue.UNKNOWN
    cap: Decimal | MissingValue = MissingValue.UNKNOWN
    assessment: Decimal | MissingValue = MissingValue.UNKNOWN
    advance: Decimal | MissingValue = MissingValue.UNKNOWN
    taxable: Decimal | MissingValue = MissingValue.UNKNOWN
    if start is not None and isinstance(prorata, Decimal):
        base_yield = max(Decimal("0"), start * rules.base_rate.rate * rules.base_yield_factor * prorata)
    if start is not None and end is not None and distributions is not None:
        cap = max(Decimal("0"), end - start + distributions)
    if isinstance(base_yield, Decimal) and isinstance(cap, Decimal):
        assessment = min(base_yield, cap)
    if isinstance(assessment, Decimal) and distributions is not None:
        advance = max(Decimal("0"), assessment - distributions)
    if isinstance(advance, Decimal) and exemption is not None:
        if not Decimal("0") <= exemption <= Decimal("1"):
            issues.append(_issue(event, "ADVANCE_TAX_PARTIAL_EXEMPTION_INVALID",
                                 "Die Teilfreistellung muss zwischen 0 und 1 liegen.",
                                 IssueNature.MATHEMATICAL_INCONSISTENCY, IssueSeverity.ERROR))
        else:
            taxable = advance * (Decimal("1") - exemption)

    fsa = _known_decimal(event.exemption_order_used)
    loss = _known_decimal(event.loss_offset_used)
    liability: Decimal | MissingValue = MissingValue.UNKNOWN
    components: tuple[TaxComponent, ...] = ()
    if isinstance(taxable, Decimal) and fsa is not None and loss is not None:
        remaining = max(Decimal("0"), taxable - fsa - loss)
        kest = remaining * rules.capital_gains_tax_rate
        soli = kest * rules.solidarity_rate
        built = [TaxComponent("CAPITAL_GAINS_TAX", kest, event.currency),
                 TaxComponent("SOLIDARITY_SURCHARGE", soli, event.currency)]
        church = _known_decimal(rules.church_tax_rate)
        if church is not None:
            built.append(TaxComponent("CHURCH_TAX", remaining * church, event.currency))
        liability = sum((item.amount for item in built), Decimal("0"))
        components = tuple(built)
    elif isinstance(taxable, Decimal):
        issues.append(_issue(event, "ADVANCE_TAX_OFFSETS_UNKNOWN",
                             "Freistellungsauftrag oder Verlustverrechnung ist unbekannt; die Steuerschuld wird nicht geschaetzt.",
                             IssueNature.MISSING_INFORMATION))

    differences: list[tuple[str, Decimal]] = []
    for name, extracted, calculated in (
        ("assessment_basis", event.assessment_basis, assessment),
        ("advance_before_partial_exemption", event.advance_before_partial_exemption, advance),
        ("taxable_amount", event.taxable_amount, taxable),
        ("stated_tax_liability", event.stated_tax_liability, liability),
    ):
        if isinstance(extracted, Decimal) and isinstance(calculated, Decimal):
            delta = extracted - calculated
            if abs(delta) > Decimal("0.01"):
                differences.append((name, delta))
                issues.append(_issue(event, f"ADVANCE_TAX_{name.upper()}_DIFFERS",
                                     f"Ausgewiesener und berechneter Wert fuer {name} weichen ab.",
                                     IssueNature.MATHEMATICAL_INCONSISTENCY))

    withheld = _known_decimal(event.actually_withheld_tax)
    if withheld is not None and withheld > 0:
        if not event.account_id:
            issues.append(_issue(event, "ADVANCE_TAX_DEBIT_ACCOUNT_MISSING",
                                 "Eine belegte Steuerbelastung ist keinem tatsaechlichen Konto zugeordnet.",
                                 IssueNature.UNSECURED_ASSIGNMENT, IssueSeverity.ERROR))
        matching = [m for m in cash_movements if m.movement_id == event.cash_movement_id]
        if not matching:
            issues.append(_issue(event, "ADVANCE_TAX_CASH_EVIDENCE_MISSING",
                                 "Zur einbehaltenen Steuer fehlt die nachgewiesene Kontobelastung.",
                                 IssueNature.MISSING_INFORMATION))
        else:
            movement = matching[0]
            if (movement.status != CashStatus.ACTUAL or movement.movement_type != CashMovementType.TAX_DEBIT
                    or movement.account_id != event.account_id or abs(movement.amount + withheld) > Decimal("0.01")):
                issues.append(_issue(event, "ADVANCE_TAX_CASH_MISMATCH",
                                     "Die Kontobelastung stimmt nicht mit der einbehaltenen Steuer ueberein.",
                                     IssueNature.CONFIRMED_DEVIATION, IssueSeverity.ERROR))

    approval = event.approval_status
    if approval == TaxApprovalStatus.REFERENCE_CONFIRMED and not rules.source_reference:
        approval = TaxApprovalStatus.NOT_APPROVED
    if not event.evidence_ids or not rules.source_reference:
        approval = TaxApprovalStatus.NOT_APPROVED

    calculation = AdvanceTaxCalculation(
        event.tax_event_id, base_yield, cap, assessment, advance, taxable, liability, components,
        prorata, tuple(differences), approval, rules.source_reference or rules.base_rate.source_reference,
        event.currency)
    carryforward = None
    if (event.depot_id and event.isin and event.tax_year is not None
            and isinstance(advance, Decimal) and advance > 0):
        carryforward = AdvanceTaxCarryforward(
            stable_id("advance-tax-carryforward", event.tax_event_id), event.tax_event_id,
            event.depot_id, event.isin, event.tax_year, advance, event.evidence_ids)
    return AdvanceTaxValidationResult(calculation, carryforward, tuple(issues))


def deduplicate_tax_events(events: tuple[TaxEvent, ...]) -> TaxDeduplicationResult:
    """Keep one economic tax event per depot/ISIN/year while reporting evidence duplicates."""
    kept: dict[tuple[object, ...], TaxEvent] = {}
    duplicates: list[tuple[str, str]] = []
    issues: list[Issue] = []
    for event in events:
        key = (event.kind.casefold(), event.bank_id, event.depot_id, event.isin, event.tax_year)
        if key not in kept or event.depot_id is None or event.isin is None or event.tax_year is None:
            kept[key + ((event.tax_event_id,) if key in kept else ())] = event
            continue
        original = kept[key]
        duplicates.append((original.tax_event_id, event.tax_event_id))
        issues.append(_issue(event, "DUPLICATE_TAX_EVENT",
                             "Dasselbe Steuerereignis ist in mehreren Dokumenten enthalten; es wird nicht doppelt gezaehlt.",
                             IssueNature.CONFIRMED_DEVIATION))
    return TaxDeduplicationResult(tuple(kept.values()), tuple(duplicates), tuple(issues))
