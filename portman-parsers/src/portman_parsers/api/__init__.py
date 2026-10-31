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
    FeeAllocation,
    FeeEffect,
    FeeEvent,
    FinancialEvent,
    Position,
    PositionSnapshot,
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
from .results import MissingValue, ParsedDocument, to_json_compatible
from .values import FieldValue, ReviewStatus, ValueSource

API_VERSION = "0.6"
SCHEMA_VERSION = "1.5.0"

__all__ = [
    "API_VERSION", "SCHEMA_VERSION", "Account", "AccountBalance", "AccountFunction", "AccountType", "AdvanceTaxCalculation", "AdvanceTaxCarryforward", "AllocationStatus",
    "CashMovement", "CashMovementType", "CashStatus", "CostEvent", "CostInformationType",
    "Depot", "DepotAccountLink", "DepotPosition", "DepotSnapshot", "DepotType",
    "Detection", "Evidence", "FeeAllocation", "FeeEffect", "FeeEvent", "FinancialEvent",
    "Issue", "IssueNature", "IssueSeverity",
    "FieldValue", "MissingValue", "ParsedDocument", "PdfDocument", "PdfPage", "Position",
    "ReviewStatus", "ValueSource",
    "PositionSnapshot", "SecurityMovement", "SecurityTrade", "StatutoryBaseRate", "TaxApprovalStatus", "TaxComponent", "TaxEvent", "TaxRuleSet",
    "to_json_compatible",
]
