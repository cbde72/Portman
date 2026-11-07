"""Synthetische Golden-Daten für V10-06; keine echten Konten oder Belege."""
from dataclasses import dataclass
from datetime import date
from fractions import Fraction


@dataclass(frozen=True, slots=True)
class Posting:
    account: str
    asset: str
    amount: str
    effective_date: date


@dataclass(frozen=True, slots=True)
class Detail:
    kind: str
    amount: str | None
    currency: str


@dataclass(frozen=True, slots=True)
class Lot:
    lot_id: str
    quantity: str
    acquired: date | None
    total_cost: str | None
    cost_currency: str | None


@dataclass(frozen=True, slots=True)
class LotSplit:
    tranche_id: str | None
    original_quantity: str
    original_cost: str | None
    transferred_quantity: str
    acquired: date | None
    cost_currency: str | None
    tranche_selected: bool = True

    @property
    def allocated_cost(self) -> Fraction | None:
        if not self.tranche_selected or self.original_cost is None:
            return None
        return Fraction(self.original_cost) * Fraction(self.transferred_quantity) / Fraction(self.original_quantity)

    @property
    def remaining_cost(self) -> Fraction | None:
        allocated = self.allocated_cost
        return Fraction(self.original_cost) - allocated if allocated is not None and self.original_cost is not None else None

    @property
    def remaining_quantity(self) -> Fraction:
        return Fraction(self.original_quantity) - Fraction(self.transferred_quantity)


@dataclass(frozen=True, slots=True)
class Evidence:
    import_id: str | None
    fields: frozenset[str]
    manual: bool = False
    values: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class Scenario:
    scenario_id: str
    kind: str
    postings: tuple[Posting, ...]
    details: tuple[Detail, ...] = ()
    lots: tuple[Lot, ...] = ()
    evidence: tuple[Evidence, ...] = ()
    related_event_id: str | None = None
    complete: bool = True


BUY = Scenario(
    "synthetic-buy-001",
    "buy",
    (
        Posting("demo-depot", "demo-fund", "2", date(2025, 11, 10)),
        Posting("demo-giro", "EUR", "-201", date(2025, 11, 12)),
    ),
    (Detail("trade_value", "200", "EUR"), Detail("fee", "1", "EUR")),
    evidence=(
        Evidence("demo-import-trade", frozenset({"kind", "trade_date", "quantity", "instrument", "trade_value", "fee", "account_assignment"}), values=(("account_assignment", "demo-giro"),)),
        Evidence("demo-import-cash", frozenset({"cash_posting", "cash_value_date"})),
        Evidence("demo-import-confirmation", frozenset({"kind", "trade_date", "quantity", "instrument", "trade_value", "fee", "cash_posting", "cash_value_date", "confirmation_only_note", "account_assignment"}), values=(("account_assignment", "demo-giro"),)),
        Evidence(None, frozenset({"user_note", "account_assignment"}), manual=True, values=(("account_assignment", "demo-giro-reviewed"),)),
    ),
)

DIVIDEND = Scenario(
    "synthetic-dividend-001",
    "dividend",
    (Posting("demo-giro", "EUR", "8", date(2025, 3, 25)),),
    (Detail("gross", "10", "EUR"), Detail("tax", "2", "EUR")),
    evidence=(
        Evidence("demo-import-dividend", frozenset({"net_posting", "value_date", "gross", "tax"})),
        Evidence("demo-import-annual-report", frozenset({"gross", "tax", "value_date"})),
    ),
)

OWN_TRANSFER = Scenario(
    "synthetic-own-transfer-001",
    "own_transfer",
    (
        Posting("demo-giro", "EUR", "-100", date(2025, 4, 2)),
        Posting("demo-savings", "EUR", "100", date(2025, 4, 2)),
    ),
    evidence=(
        Evidence("demo-import-giro", frozenset({"source_account", "source_posting"})),
        Evidence("demo-import-savings", frozenset({"destination_account", "destination_posting"})),
    ),
)

SECURITIES_TRANSFER = Scenario(
    "synthetic-depot-transfer-001",
    "securities_transfer",
    (
        Posting("demo-depot-a", "demo-fund", "-1", date(2025, 9, 15)),
        Posting("demo-depot-b", "demo-fund", "1", date(2025, 9, 15)),
        Posting("demo-depot-a", "demo-fund", "-1", date(2025, 9, 15)),
        Posting("demo-depot-b", "demo-fund", "1", date(2025, 9, 15)),
    ),
    lots=(
        Lot("demo-lot-1", "1", date(2023, 2, 3), "40", "EUR"),
        Lot("demo-lot-2", "1", date(2024, 6, 17), "60", "EUR"),
    ),
    evidence=(
        Evidence("demo-import-depot-a", frozenset({"instrument", "source_quantity", "source_date"})),
        Evidence("demo-import-depot-b", frozenset({"instrument", "destination_quantity", "destination_date", "lots"})),
    ),
)

TRANSFER_FEE = Scenario(
    "synthetic-transfer-fee-001",
    "transfer_fee",
    (Posting("demo-giro", "EUR", "-1", date(2025, 4, 3)),),
    (Detail("fee", "1", "EUR"),),
    related_event_id=OWN_TRANSFER.scenario_id,
)

INCOMPLETE_TRANSFER = Scenario(
    "synthetic-incomplete-depot-transfer-001",
    "securities_transfer",
    (Posting("demo-depot-a", "demo-fund", "-2", date(2025, 9, 15)),),
    lots=(Lot("demo-lot-unknown", "2", None, None, None),),
    complete=False,
)

TAX_REFUND = Scenario(
    "synthetic-tax-refund-001",
    "tax_refund",
    (Posting("demo-giro", "EUR", "0.40", date(2025, 8, 4)),),
    related_event_id=DIVIDEND.scenario_id,
)

PARTIAL_LOT_SPLITS = (
    LotSplit("demo-tranche-103-eur", "10", "103", "3", date(2022, 5, 12), "EUR"),
    LotSplit("demo-tranche-80-eur", "4", "80", "2", date(2023, 8, 9), "EUR"),
)

REPEATING_COST_SPLIT = LotSplit("demo-tranche-100-eur", "3", "100", "1", date(2021, 1, 4), "EUR")

UNCLEAR_LOT_SPLIT = LotSplit(None, "10", "103", "3", None, "EUR", tranche_selected=False)


def evidence_after_rollback(scenario: Scenario, removed_imports: frozenset[str]) -> frozenset[str]:
    """Reference policy: remove selected import provenance; retain manual and shared facts."""
    return frozenset(
        field
        for evidence in scenario.evidence
        if evidence.manual or evidence.import_id not in removed_imports
        for field in evidence.fields
    )


def fact_after_rollback(scenario: Scenario, field: str, removed_imports: frozenset[str]) -> str | None:
    """Resolves one synthetic fact: manual value wins; conflicting imported facts stay unknown."""
    sources = [
        source
        for source in scenario.evidence
        if source.manual or source.import_id not in removed_imports
    ]
    manual_values = [value for source in sources if source.manual for key, value in source.values if key == field]
    if manual_values:
        return manual_values[-1]
    imported_values = {value for source in sources if not source.manual for key, value in source.values if key == field}
    return next(iter(imported_values)) if len(imported_values) == 1 else None


SCENARIOS = (BUY, DIVIDEND, OWN_TRANSFER, SECURITIES_TRANSFER)
