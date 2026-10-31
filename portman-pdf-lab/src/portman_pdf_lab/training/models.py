"""Immutable training states; original parser output remains outside this model."""

from enum import StrEnum


class AnnotationKind(StrEnum):
    TEXT = "TEXT"
    AMOUNT = "AMOUNT"
    DATE = "DATE"
    SECURITY_ID = "SECURITY_ID"
    QUANTITY = "QUANTITY"
    PRICE = "PRICE"
    MARKET_VALUE = "MARKET_VALUE"
    FEE = "FEE"
    TAX = "TAX"
    ACCOUNT = "ACCOUNT"
    DEPOT = "DEPOT"
    REFERENCE = "REFERENCE"
    TABLE_ROW = "TABLE_ROW"
    MULTILINE = "MULTILINE"
    MISSING = "MISSING"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class Decision(StrEnum):
    CONFIRMED = "CONFIRMED"
    CORRECTED = "CORRECTED"
    UNKNOWN = "UNKNOWN"
    MISSING = "MISSING"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class RuleStatus(StrEnum):
    DRAFT = "DRAFT"
    TESTED = "TESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"
