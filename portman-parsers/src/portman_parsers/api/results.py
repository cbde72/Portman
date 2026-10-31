"""Aggregate parser result and deterministic JSON conversion."""

from dataclasses import dataclass, fields, is_dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
import json
from types import MappingProxyType
from typing import Any, Mapping

from .accounts import Account, AccountBalance
from .depots import Depot, DepotAccountLink, DepotSnapshot
from .events import AdvanceTaxCalculation, AdvanceTaxCarryforward, FinancialEvent, PositionSnapshot
from .evidence import Evidence
from .issues import Issue
from .values import FieldValue, MissingValue


def _field_values(value: Any):
    if isinstance(value, FieldValue):
        yield value
    elif is_dataclass(value) and not isinstance(value, type):
        for item in fields(value):
            yield from _field_values(getattr(value, item.name))
    elif isinstance(value, Mapping):
        for item in value.values():
            yield from _field_values(item)
    elif isinstance(value, (tuple, list)):
        for item in value:
            yield from _field_values(item)


def to_json_compatible(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return {item.name: to_json_compatible(getattr(value, item.name)) for item in fields(value)}
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): to_json_compatible(item) for key, item in sorted(value.items())}
    if isinstance(value, (tuple, list)):
        return [to_json_compatible(item) for item in value]
    return value


@dataclass(frozen=True, slots=True)
class ParsedDocument:
    result_id: str
    document_id: str
    plugin_id: str
    plugin_version: str
    handler_id: str
    schema_version: str = "1.5.0"
    events: tuple[FinancialEvent, ...] = ()
    snapshots: tuple[PositionSnapshot, ...] = ()
    evidence: tuple[Evidence, ...] = ()
    issues: tuple[Issue, ...] = ()
    attributes: Mapping[str, str | MissingValue] = MappingProxyType({})
    depots: tuple[Depot, ...] = ()
    accounts: tuple[Account, ...] = ()
    depot_snapshots: tuple[DepotSnapshot, ...] = ()
    account_balances: tuple[AccountBalance, ...] = ()
    depot_account_links: tuple[DepotAccountLink, ...] = ()
    tax_calculations: tuple[AdvanceTaxCalculation, ...] = ()
    tax_carryforwards: tuple[AdvanceTaxCarryforward, ...] = ()

    def __post_init__(self) -> None:
        if not all((self.result_id, self.document_id, self.plugin_id, self.plugin_version, self.handler_id)):
            raise ValueError("result, document, plugin and handler identities are required")
        for name in ("events", "snapshots", "evidence", "issues", "depots", "accounts",
                     "depot_snapshots", "account_balances", "depot_account_links"):
            object.__setattr__(self, name, tuple(getattr(self, name)))
        object.__setattr__(self, "tax_calculations", tuple(self.tax_calculations))
        object.__setattr__(self, "tax_carryforwards", tuple(self.tax_carryforwards))
        object.__setattr__(self, "attributes", MappingProxyType(dict(sorted(self.attributes.items()))))
        evidence_ids = [item.evidence_id for item in self.evidence]
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("evidence identities must be unique")
        if any(item.document_id != self.document_id for item in self.evidence):
            raise ValueError("evidence must reference the parsed document")
        evidence_by_id = {item.evidence_id: item for item in self.evidence}
        master_data = (self.depots, self.accounts, self.depot_snapshots,
                       self.account_balances, self.depot_account_links)
        for sourced in _field_values(master_data):
            for evidence_id in sourced.evidence_ids:
                evidence = evidence_by_id.get(evidence_id)
                if evidence is None:
                    raise ValueError(f"field value references unknown Evidence {evidence_id}")
                if sourced.page_number is not None and evidence.page_number != sourced.page_number:
                    raise ValueError(f"field value page differs from Evidence {evidence_id}")
        event_ids = [item.event_id for item in self.events]
        if len(event_ids) != len(set(event_ids)):
            raise ValueError("event identities must be unique")
        for values, attribute in ((self.depots, "depot_id"), (self.accounts, "account_id"),
                                  (self.depot_snapshots, "snapshot_id"),
                                  (self.account_balances, "balance_id"),
                                  (self.depot_account_links, "link_id")):
            identities = [getattr(item, attribute) for item in values]
            if len(identities) != len(set(identities)):
                raise ValueError(f"{attribute} identities must be unique")
        depot_ids = {item.depot_id for item in self.depots}
        account_ids = {item.account_id for item in self.accounts}
        if any(item.depot_id not in depot_ids for item in self.depot_snapshots):
            raise ValueError("depot snapshots must reference a known depot")
        if any(item.account_id not in account_ids for item in self.account_balances):
            raise ValueError("account balances must reference a known account")
        if any(item.depot_id not in depot_ids or item.account_id not in account_ids
               for item in self.depot_account_links):
            raise ValueError("depot-account links must reference known identities")

    def to_dict(self) -> dict[str, Any]:
        return to_json_compatible(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))

