"""Account master data and balances, separate from transactions and events."""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from types import MappingProxyType
from typing import Mapping
from enum import StrEnum

from .values import FieldValue, MissingValue


class AccountType(StrEnum):
    GIRO = "GIRO"
    TAGESGELD = "TAGESGELD"
    FESTGELD = "FESTGELD"
    OTHER = "OTHER"


class AccountFunction(StrEnum):
    PAYMENT = "PAYMENT"
    SAVINGS = "SAVINGS"
    SETTLEMENT = "SETTLEMENT"
    DIVIDEND = "DIVIDEND"
    FEES = "FEES"
    TAX = "TAX"


@dataclass(frozen=True, slots=True)
class Account:
    account_id: str
    bank_name: FieldValue[str] = field(default_factory=FieldValue.unknown)
    account_name: FieldValue[str] = field(default_factory=FieldValue.unknown)
    account_type: FieldValue[AccountType] = field(default_factory=FieldValue.unknown)
    account_number: FieldValue[str] = field(default_factory=FieldValue.unknown)
    iban: FieldValue[str] = field(default_factory=FieldValue.unknown)
    bic: FieldValue[str] = field(default_factory=FieldValue.unknown)
    currency: FieldValue[str] = field(default_factory=FieldValue.unknown)
    holder_name: FieldValue[str] = field(default_factory=FieldValue.unknown)
    attributes: Mapping[str, FieldValue[str]] = field(default_factory=dict)
    functions: tuple[FieldValue[AccountFunction], ...] = ()

    def __post_init__(self) -> None:
        if not self.account_id:
            raise ValueError("account identity is required")
        object.__setattr__(self, "attributes", MappingProxyType(dict(sorted(self.attributes.items()))))
        object.__setattr__(self, "functions", tuple(self.functions))


@dataclass(frozen=True, slots=True)
class AccountBalance:
    balance_id: str
    account_id: str
    as_of: FieldValue[date]
    amount: FieldValue[Decimal]
    currency: FieldValue[str]
    balance_type: FieldValue[str] = field(default_factory=lambda: FieldValue.manual("closing"))

    def __post_init__(self) -> None:
        if not self.balance_id or not self.account_id:
            raise ValueError("balance and account identities are required")
        if not isinstance(self.amount.value, (Decimal, MissingValue)):
            raise TypeError("known account balances must use Decimal")

