"""Transportneutrale Verträge, Vertragsentwurf 0.1; noch keine Implementierung."""
from dataclasses import dataclass
from datetime import date
from typing import Protocol, Literal
from portman_v10.domain.values import ExactValue

@dataclass(frozen=True, slots=True)
class BalanceLine:
    account_id: str
    value: ExactValue | None
    currency: str | None
    instrument_id: str | None
    completeness: Literal["complete", "incomplete", "unknown"]

@dataclass(frozen=True, slots=True)
class Overview:
    as_of: date
    data_revision: int
    lines: tuple[BalanceLine, ...]

@dataclass(frozen=True, slots=True)
class Search:
    text: str = ""
    account_ids: tuple[str, ...] = ()
    date_from: date | None = None
    date_to: date | None = None
    currency: str | None = None
    minimum: ExactValue | None = None
    maximum: ExactValue | None = None
    cursor: str | None = None
    limit: int = 100

@dataclass(frozen=True, slots=True)
class TransactionSummary:
    event_id: str
    booking_date: date
    kind: str
    description: str

@dataclass(frozen=True, slots=True)
class TransactionPage:
    items: tuple[TransactionSummary, ...]
    next_cursor: str | None
    data_revision: int

@dataclass(frozen=True, slots=True)
class RollbackSelection:
    import_ids: tuple[str, ...] = ()
    all_imports: bool = False

    def __post_init__(self):
        if bool(self.import_ids) == self.all_imports:
            raise ValueError("Entweder Import-IDs oder ausdrücklich alle Importe auswählen")

class ReadApplication(Protocol):
    def get_overview(self, as_of: date, account_ids: tuple[str, ...] = ()) -> Overview: ...
    def search_transactions(self, query: Search) -> TransactionPage: ...
