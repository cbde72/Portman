"""Regression tests for semantic field catalog auditing."""

from portman_pdf_lab.field_catalog_adapter import _mapping, classify_unmapped


def test_verified_dto_paths():
    assert _mapping("accounts[].bank_name") == ("accounts[].bank_name", "exact")
    assert _mapping("trades[].net_amount") == ("events[].trades[].settlement_amount", "aliased")


def test_optional_extension_is_not_misrepresented_as_standard_dto():
    assert _mapping("trade.venue")[0] is None
    assert classify_unmapped("trade.venue", "unknown_collection")[0] == "OPTIONAL_EXTENSION"
    assert classify_unmapped("trades[].venue", "unknown_dto_member")[0] == "OPTIONAL_EXTENSION"


def test_unmapped_groups_preserve_distinctions():
    cases = {
        "document.page_count": "DOCUMENT_METADATA",
        "parser.run_id": "RUNTIME_METADATA",
        "income_events[].dividend_per_share": "UNSUPPORTED_COLLECTION",
        "securities[].isin": "UNSUPPORTED_COLLECTION",
        "accounts[].opening_balance": "UNSUPPORTED_DTO_FIELD",
        "tax_events[].capital_gains_tax": "UNSUPPORTED_DTO_FIELD",
    }
    for path, expected in cases.items():
        _, status = _mapping(path)
        category, reason = classify_unmapped(path, status)
        assert category == expected, path
        assert reason
