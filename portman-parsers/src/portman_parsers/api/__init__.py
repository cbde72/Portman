"""Stable public data-transfer contracts."""

from .accounts import Account, AccountBalance, AccountFunction, AccountType
from .depots import Depot, DepotAccountLink, DepotPosition, DepotSnapshot, DepotType
from .detection import Detection
from .documents import PdfDocument, PdfPage
from .events import (
    AdvanceTaxCalculation,
    AdvanceTaxCarryforward,
    AllocationStatus,
    CashMovement,
    CashMovementType,
    CashStatus,
    CostEvent,
    CostInformationType,
    ExchangeRate,
    FeeAllocation,
    FeeEffect,
    FeeEvent,
    FinancialEvent,
    Position,
    PositionSnapshot,
    ReversalDetails,
    SecurityMovement,
    SecurityTrade,
    TaxComponent,
    TaxEvent,
    TaxApprovalStatus,
    TaxRuleSet,
    StatutoryBaseRate,
)
from .evidence import Evidence
from .issues import Issue, IssueNature, IssueSeverity
from .results import MissingValue, ParsedDocument, SCHEMA_VERSION as RESULT_SCHEMA_VERSION, normalize_result_payload, to_json_compatible
from .values import FieldValue, ReviewStatus, ValueSource

API_VERSION = "0.9"
SCHEMA_VERSION = RESULT_SCHEMA_VERSION

__all__ = [
    "API_VERSION", "SCHEMA_VERSION", "Account", "AccountBalance", "AccountFunction", "AccountType", "AdvanceTaxCalculation", "AdvanceTaxCarryforward", "AllocationStatus",
    "CashMovement", "CashMovementType", "CashStatus", "CostEvent", "CostInformationType", "ExchangeRate",
    "Depot", "DepotAccountLink", "DepotPosition", "DepotSnapshot", "DepotType",
    "Detection", "Evidence", "FeeAllocation", "FeeEffect", "FeeEvent", "FinancialEvent",
    "Issue", "IssueNature", "IssueSeverity",
    "FieldValue", "MissingValue", "ParsedDocument", "PdfDocument", "PdfPage", "Position",
    "ReviewStatus", "ValueSource",
    "PositionSnapshot", "ReversalDetails", "SecurityMovement", "SecurityTrade", "StatutoryBaseRate", "TaxApprovalStatus", "TaxComponent", "TaxEvent", "TaxRuleSet",
    "normalize_result_payload", "to_json_compatible",
]
