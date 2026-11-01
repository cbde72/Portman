import json
from datetime import date
from decimal import Decimal

import pytest

from portman_parsers.api import (
    CashMovement, CashMovementType, CashStatus, Evidence, FinancialEvent,
    IssueSeverity, ParsedDocument, PdfDocument, PdfPage, MissingValue,
    normalize_result_payload, to_json_compatible,
)
from portman_parsers.validation import validate_parsed_document


def _event(**kwargs):
    return FinancialEvent("event-1", "doc-1", "DIVIDEND", **kwargs)


def _result(event, evidence=()):
    return ParsedDocument("result-1", "doc-1", "plugin", "1", "dividend",
                          events=(event,), evidence=tuple(evidence))


def test_event_and_child_evidence_references_are_reported_centrally():
    movement = CashMovement("movement-1", "event-1", Decimal("1.00"), "EUR",
                            CashStatus.EXPECTED, evidence_ids=("missing-child",),
                            movement_type=CashMovementType.DIVIDEND_CREDIT)
    result = _result(_event(evidence_ids=("missing-event",), cash_movements=(movement,)))
    issues = validate_parsed_document(result)
    missing = {issue.evidence_id for issue in issues if issue.code == "EVIDENCE_REFERENCE_MISSING"}
    assert {"missing-event", "missing-child"} <= missing


def test_duplicate_evidence_references_are_safe_and_valid_evidence_is_preserved():
    evidence = Evidence("ev-1", "doc-1", 1, "event", "Dividend", "page:1", "a" * 64)
    result = _result(_event(evidence_ids=("ev-1", "ev-1")), (evidence,))
    assert not [issue for issue in validate_parsed_document(result)
                if issue.code.startswith("EVIDENCE_")]


def test_foreign_document_evidence_is_rejected_by_the_result_contract():
    evidence = Evidence("ev-foreign", "other-document", 1, "event", "x")
    with pytest.raises(ValueError, match="evidence must reference the parsed document"):
        _result(_event(evidence_ids=("ev-foreign",)), (evidence,))


def test_legacy_result_payload_gets_phase0_defaults_without_losing_values():
    legacy = {"schema_version": "1.5.0", "events": [{"event_id": "e", "amount": "1.25"}]}
    normalized = normalize_result_payload(legacy)
    assert normalized["schema_version"] == "1.6.0"
    assert normalized["events"][0]["amount"] == "1.25"
    assert normalized["events"][0]["bank_reference_status"] == "MISSING"
    assert normalized["events"][0]["bank_reference"] == "UNKNOWN"


def test_new_event_fields_round_trip_as_json_without_changing_financial_amount():
    event = _event(bank_reference="Ref-ABC123", bank_reference_status="RECOGNIZED")
    payload = json.loads(json.dumps(to_json_compatible(event)))
    assert payload["bank_reference"] == "Ref-ABC123"
    assert payload["bank_reference_status"] == "RECOGNIZED"
    assert payload["kind"] == "DIVIDEND"
