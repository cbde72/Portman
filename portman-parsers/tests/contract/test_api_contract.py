from datetime import date
from decimal import Decimal
from importlib.metadata import version
import json

import pytest

from portman_parsers import __version__
from portman_parsers.api import (
    API_VERSION,
    SCHEMA_VERSION,
    CashMovement,
    CashStatus,
    ExchangeRate,
    Evidence,
    FinancialEvent,
    MissingValue,
    ParsedDocument,
    PdfDocument,
    PdfPage,
)


def test_api_and_schema_are_versioned():
    assert __version__ == "0.8.2"
    assert version("portman-parsers") == __version__
    assert API_VERSION == "0.7"
    assert SCHEMA_VERSION == "1.7.0"


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


def test_structured_exchange_rate_and_payment_fields_round_trip_with_exact_evidence():
    evidence = (
        Evidence("ev-rate", "doc-1", 1, "exchange_rate", "1 USD = 0.923456 EUR"),
        Evidence("ev-party", "doc-1", 1, "counterparty", "Auftraggeber: Beispiel GmbH"),
        Evidence("ev-purpose", "doc-1", 1, "purpose", "Verwendungszweck: Rechnung Ä-17"),
    )
    rate = ExchangeRate("fx-1", "event-1", Decimal("0.9234560001"), "USD", "EUR",
                        date(2026, 2, 3), evidence_ids=("ev-rate",))
    event = FinancialEvent(
        "event-1", "doc-1", "CASH_BOOKING", counterparty="Beispiel GmbH",
        counterparty_evidence_ids=("ev-party",), purpose="Rechnung Ä-17",
        purpose_evidence_ids=("ev-purpose",), exchange_rates=(rate,),
    )
    result = ParsedDocument("result-1", "doc-1", "demo", "1", "handler",
                            events=(event,), evidence=evidence)
    payload = json.loads(result.to_json())["events"][0]
    assert payload["counterparty"] == "Beispiel GmbH"
    assert payload["purpose"] == "Rechnung Ä-17"
    assert payload["exchange_rates"][0]["rate"] == "0.9234560001"
    assert payload["exchange_rates"][0]["base_currency"] == "USD"
    assert payload["exchange_rates"][0]["quote_currency"] == "EUR"
    assert ExchangeRate.from_dict(payload["exchange_rates"][0]) == rate
    assert payload["exchange_rates"][0]["evidence_ids"] == ["ev-rate"]


def test_exchange_rate_deserializer_rejects_float_precision_loss():
    payload = {
        "exchange_rate_id": "fx-1", "event_id": "event-1", "rate": 0.923456,
        "base_currency": "USD", "quote_currency": "EUR", "evidence_ids": ["ev-1"],
    }
    with pytest.raises(TypeError, match="Decimal as a string"):
        ExchangeRate.from_dict(payload)


@pytest.mark.parametrize("rate", [Decimal("0"), Decimal("-1"), Decimal("NaN"), Decimal("Infinity")])
def test_structured_exchange_rate_must_be_finite_and_positive(rate):
    with pytest.raises(ValueError, match="finite and positive"):
        ExchangeRate("fx-1", "event-1", rate, "USD", "EUR", evidence_ids=("ev-1",))


def test_structured_exchange_rate_requires_different_currencies_and_evidence():
    with pytest.raises(ValueError, match="different"):
        ExchangeRate("fx-1", "event-1", Decimal("1.1"), "EUR", "EUR", evidence_ids=("ev-1",))
    with pytest.raises(ValueError, match="requires evidence"):
        ExchangeRate("fx-1", "event-1", Decimal("1.1"), "USD", "EUR")
    with pytest.raises(ValueError, match="currency"):
        ExchangeRate("fx-1", "event-1", Decimal("1.1"), "US", "EUR", evidence_ids=("ev-1",))


def test_structured_event_values_require_their_own_evidence():
    with pytest.raises(ValueError, match="counterparty requires evidence"):
        FinancialEvent("event-1", "doc-1", "CASH_BOOKING", counterparty="Beispiel GmbH")
    with pytest.raises(ValueError, match="purpose requires evidence"):
        FinancialEvent("event-1", "doc-1", "CASH_BOOKING", purpose="Rechnung 17")


def test_duplicate_evidence_ids_are_rejected():
    evidence = Evidence("same", "doc-1", 1, "amount")
    with pytest.raises(ValueError, match="unique"):
        ParsedDocument("result-1", "doc-1", "demo", "1", "handler",
                       evidence=(evidence, evidence))
