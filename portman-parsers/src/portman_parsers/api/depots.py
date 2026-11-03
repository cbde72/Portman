"""Depot master data, holdings snapshots and explicit account relationships."""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from types import MappingProxyType
from typing import Mapping
from enum import StrEnum

from .values import FieldValue, MissingValue


class DepotType(StrEnum):
    WERTPAPIER = "WERTPAPIER"


@dataclass(frozen=True, slots=True)
class Depot:
    depot_id: str
    bank_name: FieldValue[str] = field(default_factory=FieldValue.unknown)
    depot_name: FieldValue[str] = field(default_factory=FieldValue.unknown)
    depot_number: FieldValue[str] = field(default_factory=FieldValue.unknown)
    holder_name: FieldValue[str] = field(default_factory=FieldValue.unknown)
    base_currency: FieldValue[str] = field(default_factory=FieldValue.unknown)
    attributes: Mapping[str, FieldValue[str]] = field(default_factory=dict)
    depot_type: FieldValue[DepotType] = field(default_factory=FieldValue.unknown)

    def __post_init__(self) -> None:
        if not self.depot_id:
            raise ValueError("depot identity is required")
        object.__setattr__(self, "attributes", MappingProxyType(dict(sorted(self.attributes.items()))))


@dataclass(frozen=True, slots=True)
class DepotPosition:
    position_id: str
    security_id: FieldValue[str]
    quantity: FieldValue[Decimal]
    security_name: FieldValue[str] = field(default_factory=FieldValue.unknown)
    market_value: FieldValue[Decimal] = field(default_factory=FieldValue.unknown)
    currency: FieldValue[str] = field(default_factory=FieldValue.unknown)
    price: FieldValue[Decimal] = field(default_factory=FieldValue.unknown)
    price_date: FieldValue[date] = field(default_factory=FieldValue.unknown)

    def __post_init__(self) -> None:
        if not self.position_id:
            raise ValueError("position identity is required")
        for item in (self.quantity, self.market_value, self.price):
            if not isinstance(item.value, (Decimal, MissingValue)):
                raise TypeError("known position amounts and quantities must use Decimal")


@dataclass(frozen=True, slots=True)
class DepotSnapshot:
    snapshot_id: str
    depot_id: str
    as_of: FieldValue[date]
    positions: tuple[DepotPosition, ...] = ()
    total_value: FieldValue[Decimal] = field(default_factory=FieldValue.unknown)
    currency: FieldValue[str] = field(default_factory=FieldValue.unknown)

    def __post_init__(self) -> None:
        if not self.snapshot_id or not self.depot_id:
            raise ValueError("snapshot and depot identities are required")
        object.__setattr__(self, "positions", tuple(self.positions))
        ids = [item.position_id for item in self.positions]
        if len(ids) != len(set(ids)):
            raise ValueError("position identities must be unique within a snapshot")
        if not isinstance(self.total_value.value, (Decimal, MissingValue)):
            raise TypeError("known snapshot totals must use Decimal")


@dataclass(frozen=True, slots=True)
class DepotAccountLink:
    link_id: str
    depot_id: str
    account_id: str
    role: FieldValue[str]
    valid_from: FieldValue[date] = field(default_factory=FieldValue.unknown)
    valid_until: FieldValue[date] = field(default_factory=FieldValue.unknown)
    is_default: FieldValue[bool] = field(default_factory=FieldValue.unknown)

    def __post_init__(self) -> None:
        if not self.link_id or not self.depot_id or not self.account_id:
            raise ValueError("link, depot and account identities are required")

    @property
    def relationship(self) -> FieldValue[str]:
        return self.role

    @property
    def valid_to(self) -> FieldValue[date]:
        return self.valid_until

