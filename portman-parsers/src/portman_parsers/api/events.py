"""Economic event contracts with explicit cash and security effects."""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import StrEnum

from .values import MissingValue


def _decimal(value: Decimal) -> Decimal:
    if not isinstance(value, Decimal):
        raise TypeError("financial values must be Decimal")
    return value


def _currency(value: str) -> str:
    value = value.upper()
    if len(value) != 3 or not value.isalpha():
        raise ValueError("currency must be a three-letter ISO-style code")
    return value


class CashStatus(StrEnum):
    ACTUAL = "ACTUAL"
    EXPECTED = "EXPECTED"


class CashMovementType(StrEnum):
    DEPOSIT = "DEPOSIT"
    WITHDRAWAL = "WITHDRAWAL"
    TRANSFER = "TRANSFER"
    STANDING_ORDER = "STANDING_ORDER"
    DIRECT_DEBIT = "DIRECT_DEBIT"
    CARD_PAYMENT = "CARD_PAYMENT"
    INTERNAL_TRANSFER = "INTERNAL_TRANSFER"
    INTEREST_CREDIT = "INTEREST_CREDIT"
    INTEREST_DEBIT = "INTEREST_DEBIT"
    DIVIDEND_CREDIT = "DIVIDEND_CREDIT"
    SECURITY_BUY = "SECURITY_BUY"
    SECURITY_SELL = "SECURITY_SELL"
    TAX_DEBIT = "TAX_DEBIT"
    TAX_REFUND = "TAX_REFUND"
    FEE_DEBIT = "FEE_DEBIT"
    FEE_REFUND = "FEE_REFUND"
    REVERSAL = "REVERSAL"
    OTHER = "OTHER"


class FeeEffect(StrEnum):
    ACTUAL_BOOKED = "ACTUAL_BOOKED"
    INCLUDED_IN_SETTLEMENT = "INCLUDED_IN_SETTLEMENT"
    INFORMATIONAL = "INFORMATIONAL"
    ESTIMATED = "ESTIMATED"
    REFUND = "REFUND"
    REVERSAL = "REVERSAL"


class CostInformationType(StrEnum):
    NONE = "NONE"
    MIFID_EX_ANTE = "MIFID_EX_ANTE"
    MIFID_EX_POST = "MIFID_EX_POST"


class AllocationStatus(StrEnum):
    VERIFIED = "VERIFIED"
    UNSECURED = "UNSECURED"


@dataclass(frozen=True, slots=True)
class FeeAllocation:
    target_type: str
    target_id: str
    status: AllocationStatus = AllocationStatus.UNSECURED
    evidence_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.target_type or not self.target_id:
            raise ValueError("fee allocation target type and identity are required")
        object.__setattr__(self, "evidence_ids", tuple(self.evidence_ids))


@dataclass(frozen=True, slots=True)
class FeeEvent:
    fee_id: str
    category: str
    subcategory: str
    amount: Decimal
    currency: str
    fee_date: date
    effect: FeeEffect
    document_id: str
    bank_id: str = ""
    depot_id: str | None = None
    account_id: str | None = None
    security_id: str | None = None
    transaction_id: str | None = None
    cash_movement_id: str | None = None
    external_reference: str | None = None
    reverses_fee_id: str | None = None
    allocations: tuple[FeeAllocation, ...] = ()
    evidence_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not all((self.fee_id, self.category, self.subcategory, self.document_id)):
            raise ValueError("fee identity, category, subcategory and document are required")
        object.__setattr__(self, "amount", _decimal(self.amount))
        object.__setattr__(self, "currency", _currency(self.currency))
        object.__setattr__(self, "allocations", tuple(self.allocations))
        object.__setattr__(self, "evidence_ids", tuple(self.evidence_ids))
        if self.amount < 0:
            raise ValueError("fee amount is unsigned; refunds and reversals use FeeEffect")
        if not self.evidence_ids:
            raise ValueError("every fee requires Evidence")
        if self.effect == FeeEffect.REVERSAL and not self.reverses_fee_id:
            raise ValueError("fee reversals must reference the original fee")

    @property
    def economic_amount(self) -> Decimal:
        if self.effect in {FeeEffect.REFUND, FeeEffect.REVERSAL}:
            return -self.amount
        return self.amount


@dataclass(frozen=True, slots=True)
class CashMovement:
    movement_id: str
    event_id: str
    amount: Decimal
    currency: str
    status: CashStatus
    account_ref: str = ""
    evidence_ids: tuple[str, ...] = ()
    account_id: str | None = None
    linked_security_movement_id: str | None = None
    movement_type: CashMovementType = CashMovementType.OTHER
    transfer_id: str | None = None
    counterpart_movement_id: str | None = None

    def __post_init__(self) -> None:
        if not self.movement_id or not self.event_id:
            raise ValueError("cash movement and event identities are required")
        object.__setattr__(self, "amount", _decimal(self.amount))
        object.__setattr__(self, "currency", _currency(self.currency))
        object.__setattr__(self, "evidence_ids", tuple(self.evidence_ids))


@dataclass(frozen=True, slots=True)
class SecurityMovement:
    movement_id: str
    event_id: str
    security_id: str
    quantity: Decimal
    evidence_ids: tuple[str, ...] = ()
    depot_id: str | None = None
    linked_cash_movement_id: str | None = None

    def __post_init__(self) -> None:
        if not self.movement_id or not self.event_id or not self.security_id:
            raise ValueError("security movement identity, event and security are required")
        object.__setattr__(self, "quantity", _decimal(self.quantity))
        object.__setattr__(self, "evidence_ids", tuple(self.evidence_ids))


@dataclass(frozen=True, slots=True)
class SecurityTrade:
    """Values printed on a security settlement; printed values are never recomputed."""

    trade_id: str
    event_id: str
    side: str
    security_name: str | MissingValue = MissingValue.UNKNOWN
    isin: str | MissingValue = MissingValue.UNKNOWN
    wkn: str | MissingValue = MissingValue.UNKNOWN
    quantity: Decimal | MissingValue = MissingValue.UNKNOWN
    trade_date: date | MissingValue = MissingValue.UNKNOWN
    execution_date: date | MissingValue = MissingValue.UNKNOWN
    value_date: date | MissingValue = MissingValue.UNKNOWN
    price: Decimal | MissingValue = MissingValue.UNKNOWN
    price_currency: str | MissingValue = MissingValue.UNKNOWN
    market_value: Decimal | MissingValue = MissingValue.UNKNOWN
    gross_amount: Decimal | MissingValue = MissingValue.UNKNOWN
    exchange_rate: Decimal | MissingValue = MissingValue.UNKNOWN
    settlement_amount: Decimal | MissingValue = MissingValue.UNKNOWN
    settlement_currency: str | MissingValue = MissingValue.UNKNOWN
    depot_id: str | None = None
    account_id: str | None = None
    evidence_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.trade_id or not self.event_id or self.side not in {"BUY", "SELL", "REDEMPTION"}:
            raise ValueError("trade identity, parent event and supported side are required")
        for name in ("quantity", "price", "market_value", "gross_amount", "exchange_rate", "settlement_amount"):
            value = getattr(self, name)
            if isinstance(value, Decimal):
                object.__setattr__(self, name, _decimal(value))
        for name in ("price_currency", "settlement_currency"):
            value = getattr(self, name)
            if isinstance(value, str) and not isinstance(value, MissingValue):
                object.__setattr__(self, name, _currency(value))
        object.__setattr__(self, "evidence_ids", tuple(self.evidence_ids))


@dataclass(frozen=True, slots=True)
class TaxComponent:
    kind: str
    amount: Decimal
    currency: str

    def __post_init__(self) -> None:
        if not self.kind:
            raise ValueError("tax component kind is required")
        object.__setattr__(self, "amount", _decimal(self.amount))
        object.__setattr__(self, "currency", _currency(self.currency))
        if self.amount < 0:
            raise ValueError("tax components are unsigned; cash direction belongs to CashMovement")


class TaxApprovalStatus(StrEnum):
    NOT_APPROVED = "NOT_APPROVED"
    SYNTHETIC_ONLY = "SYNTHETIC_ONLY"
    REFERENCE_CONFIRMED = "REFERENCE_CONFIRMED"


@dataclass(frozen=True, slots=True)
class StatutoryBaseRate:
    tax_year: int
    rate: Decimal
    source_reference: str
    published_on: date | None = None
    jurisdiction: str = "DE"

    def __post_init__(self) -> None:
        object.__setattr__(self, "rate", _decimal(self.rate))
        if not self.source_reference:
            raise ValueError("statutory rates require a source reference")


@dataclass(frozen=True, slots=True)
class TaxRuleSet:
    tax_year: int
    base_rate: StatutoryBaseRate
    base_yield_factor: Decimal = Decimal("0.70")
    capital_gains_tax_rate: Decimal = Decimal("0.25")
    solidarity_rate: Decimal = Decimal("0.055")
    church_tax_rate: Decimal | MissingValue = MissingValue.UNKNOWN
    bank_id: str | None = None
    source_reference: str = ""

    def __post_init__(self) -> None:
        for name in ("base_yield_factor", "capital_gains_tax_rate", "solidarity_rate"):
            object.__setattr__(self, name, _decimal(getattr(self, name)))
        if isinstance(self.church_tax_rate, Decimal):
            object.__setattr__(self, "church_tax_rate", _decimal(self.church_tax_rate))
        if self.base_rate.tax_year != self.tax_year:
            raise ValueError("base rate and rule set tax years must match")


@dataclass(frozen=True, slots=True)
class AdvanceTaxCalculation:
    tax_event_id: str
    base_yield: Decimal | MissingValue
    appreciation_cap: Decimal | MissingValue
    assessment_basis: Decimal | MissingValue
    advance_before_partial_exemption: Decimal | MissingValue
    taxable_amount: Decimal | MissingValue
    assessed_tax_liability: Decimal | MissingValue
    expected_components: tuple[TaxComponent, ...] = ()
    pro_rata_factor: Decimal | MissingValue = MissingValue.UNKNOWN
    differences: tuple[tuple[str, Decimal], ...] = ()
    approval_status: TaxApprovalStatus = TaxApprovalStatus.NOT_APPROVED
    rule_source_reference: str = ""
    currency: str = "EUR"

    def __post_init__(self) -> None:
        object.__setattr__(self, "expected_components", tuple(self.expected_components))
        object.__setattr__(self, "differences", tuple(self.differences))
        object.__setattr__(self, "currency", _currency(self.currency))


@dataclass(frozen=True, slots=True)
class AdvanceTaxCarryforward:
    carryforward_id: str
    tax_event_id: str
    depot_id: str
    isin: str
    tax_year: int
    taxed_advance_amount: Decimal
    evidence_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "taxed_advance_amount", _decimal(self.taxed_advance_amount))
        object.__setattr__(self, "evidence_ids", tuple(self.evidence_ids))


@dataclass(frozen=True, slots=True)
class TaxEvent:
    tax_event_id: str
    event_id: str
    kind: str
    components: tuple[TaxComponent, ...] = ()
    taxable_basis: Decimal | None = None
    cash_movement_id: str | None = None
    evidence_ids: tuple[str, ...] = ()
    depot_id: str | None = None
    isin: str | None = None
    tax_year: int | None = None
    accrual_date: date | None = None
    booking_date: date | MissingValue = MissingValue.UNKNOWN
    value_date: date | MissingValue = MissingValue.UNKNOWN
    bank_id: str = ""
    currency: str = "EUR"
    account_id: str | None = None
    assessment_basis: Decimal | MissingValue = MissingValue.UNKNOWN
    advance_before_partial_exemption: Decimal | MissingValue = MissingValue.UNKNOWN
    taxable_amount: Decimal | MissingValue = MissingValue.UNKNOWN
    stated_tax_liability: Decimal | MissingValue = MissingValue.UNKNOWN
    actually_withheld_tax: Decimal | MissingValue = MissingValue.UNKNOWN
    distributions: Decimal | MissingValue = MissingValue.UNKNOWN
    start_value: Decimal | MissingValue = MissingValue.UNKNOWN
    end_value: Decimal | MissingValue = MissingValue.UNKNOWN
    partial_exemption_rate: Decimal | MissingValue = MissingValue.UNKNOWN
    exemption_order_used: Decimal | MissingValue = MissingValue.UNKNOWN
    loss_offset_used: Decimal | MissingValue = MissingValue.UNKNOWN
    acquisition_date: date | MissingValue = MissingValue.UNKNOWN
    approval_status: TaxApprovalStatus = TaxApprovalStatus.NOT_APPROVED

    def __post_init__(self) -> None:
        if not self.tax_event_id or not self.event_id or not self.kind:
            raise ValueError("tax event identity, parent event and kind are required")
        if self.taxable_basis is not None:
            object.__setattr__(self, "taxable_basis", _decimal(self.taxable_basis))
        object.__setattr__(self, "components", tuple(self.components))
        object.__setattr__(self, "evidence_ids", tuple(self.evidence_ids))
        object.__setattr__(self, "currency", _currency(self.currency))
        for name in ("assessment_basis", "advance_before_partial_exemption", "taxable_amount",
                     "stated_tax_liability", "actually_withheld_tax", "distributions", "start_value",
                     "end_value", "partial_exemption_rate", "exemption_order_used", "loss_offset_used"):
            value = getattr(self, name)
            if isinstance(value, Decimal):
                object.__setattr__(self, name, _decimal(value))


@dataclass(frozen=True, slots=True)
class CostEvent:
    cost_event_id: str
    event_id: str
    kind: str
    amount: Decimal
    currency: str
    cash_movement_id: str | None = None
    informational: bool = False
    evidence_ids: tuple[str, ...] = ()
    information_type: CostInformationType = CostInformationType.NONE
    fee_ids: tuple[str, ...] = ()
    document_id: str = ""
    bank_id: str = ""
    depot_id: str | None = None
    account_id: str | None = None
    security_id: str | None = None
    transaction_id: str | None = None

    def __post_init__(self) -> None:
        if not self.cost_event_id or not self.event_id or not self.kind:
            raise ValueError("cost event identity, parent event and kind are required")
        object.__setattr__(self, "amount", _decimal(self.amount))
        object.__setattr__(self, "currency", _currency(self.currency))
        if self.amount < 0:
            raise ValueError("cost components are unsigned; cash direction belongs to CashMovement")
        object.__setattr__(self, "evidence_ids", tuple(self.evidence_ids))
        object.__setattr__(self, "fee_ids", tuple(self.fee_ids))
        if self.information_type != CostInformationType.NONE and not self.informational:
            raise ValueError("MiFID cost information must be informational")


@dataclass(frozen=True, slots=True)
class FinancialEvent:
    event_id: str
    document_id: str
    kind: str
    event_date: date | None = None
    cash_movements: tuple[CashMovement, ...] = ()
    security_movements: tuple[SecurityMovement, ...] = ()
    tax_events: tuple[TaxEvent, ...] = ()
    cost_events: tuple[CostEvent, ...] = ()
    reversal_of_event_id: str | None = None
    evidence_ids: tuple[str, ...] = ()
    fee_events: tuple[FeeEvent, ...] = ()
    trades: tuple[SecurityTrade, ...] = ()

    def __post_init__(self) -> None:
        if not self.event_id or not self.document_id or not self.kind:
            raise ValueError("event identity, document identity and kind are required")
        for name in ("cash_movements", "security_movements", "tax_events", "cost_events", "evidence_ids", "fee_events", "trades"):
            object.__setattr__(self, name, tuple(getattr(self, name)))
        children = (*self.cash_movements, *self.security_movements, *self.tax_events, *self.cost_events, *self.trades)
        if any(child.event_id != self.event_id for child in children):
            raise ValueError("all child records must reference their parent event")


@dataclass(frozen=True, slots=True)
class Position:
    security_id: str
    quantity: Decimal
    market_value: Decimal | None = None
    currency: str | None = None

    def __post_init__(self) -> None:
        if not self.security_id:
            raise ValueError("position security is required")
        object.__setattr__(self, "quantity", _decimal(self.quantity))
        if self.market_value is not None:
            object.__setattr__(self, "market_value", _decimal(self.market_value))
        if self.currency is not None:
            object.__setattr__(self, "currency", _currency(self.currency))


@dataclass(frozen=True, slots=True)
class PositionSnapshot:
    snapshot_id: str
    document_id: str
    account_ref: str
    as_of: date
    positions: tuple[Position, ...] = field(default_factory=tuple)
    evidence_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.snapshot_id or not self.document_id or not self.account_ref:
            raise ValueError("snapshot identity, document and account are required")
        object.__setattr__(self, "positions", tuple(self.positions))
        object.__setattr__(self, "evidence_ids", tuple(self.evidence_ids))

