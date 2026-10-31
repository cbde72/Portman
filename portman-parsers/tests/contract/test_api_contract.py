from datetime import date
from decimal import Decimal
import json

import pytest

from portman_parsers.api import (
    API_VERSION,
    SCHEMA_VERSION,
    CashMovement,
    CashStatus,
    Evidence,
    FinancialEvent,
    MissingValue,
    ParsedDocument,
    PdfDocument,
    PdfPage,
)


def test_api_and_schema_are_versioned():
    assert API_VERSION == "0.6"
    assert SCHEMA_VERSION == "1.5.0"


def test_pdf_document_orders_pages_without_binary_payload():
    document = PdfDocument("doc-1", "sha256:test", (PdfPage(2, "b"), PdfPage(1, "a")), "test.pdf")
    assert document.text == "a\nb"
    assert not hasattr(document, "content")


def test_financial_values_must_be_decimal():
    with pytest.raises(TypeError, match="Decimal"):
        CashMovement("cash-1", "event-1", -10, "EUR", CashStatus.ACTUAL)  # type: ignore[arg-type]


def test_currency_is_explicit_and_normalized():
    movement = CashMovement("cash-1", "event-1", Decimal("1.00"), "eur", CashStatus.ACTUAL)
    assert movement.currency == "EUR"
    with pytest.raises(ValueError, match="currency"):
        CashMovement("cash-2", "event-1", Decimal("1"), "EU", CashStatus.ACTUAL)


def test_unknown_null_and_numeric_zero_are_distinct_in_json():
    result = ParsedDocument(
        "result-1", "doc-1", "demo", "1", "handler",
        attributes={"unknown": MissingValue.UNKNOWN, "not_found": MissingValue.NOT_FOUND,
                    "not_applicable": MissingValue.NOT_APPLICABLE, "zero": "0"},
    )
    data = result.to_dict()["attributes"]
    assert data == {"not_applicable": "NOT_APPLICABLE", "not_found": "NOT_FOUND",
                    "unknown": "UNKNOWN", "zero": "0"}


def test_ids_for_document_event_and_cash_are_separate():
    cash = CashMovement("cash-1", "event-1", Decimal("-1"), "EUR", CashStatus.ACTUAL)
    event = FinancialEvent("event-1", "doc-1", "BUY", date(2026, 1, 1), (cash,))
    assert len({event.document_id, event.event_id, cash.movement_id}) == 3


def test_evidence_references_document_and_serialization_is_deterministic():
    evidence = Evidence("evidence-1", "doc-1", 1, "amount", "EUR 1.00")
    result = ParsedDocument("result-1", "doc-1", "demo", "1", "handler", evidence=(evidence,))
    first = result.to_json()
    assert first == result.to_json()
    assert json.loads(first)["evidence"][0]["document_id"] == "doc-1"


def test_duplicate_evidence_ids_are_rejected():
    evidence = Evidence("same", "doc-1", 1, "amount")
    with pytest.raises(ValueError, match="unique"):
        ParsedDocument("result-1", "doc-1", "demo", "1", "handler",
                       evidence=(evidence, evidence))

