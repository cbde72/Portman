import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from portman_pdf_lab.ui.standard_values import (
    StandardValuesDialog, build_standard_value_rows, normalize_description_path,
)
from portman_pdf_lab.field_catalog import CatalogStore
from portman_pdf_lab.field_descriptions import DescriptionCatalog, resolve_description


def app():
    return QApplication.instance() or QApplication([])


def test_standard_rows_only_contain_actual_base_parser_values():
    report = {
        "rule_mode_requested": "COMPARE",
        "result": {
            "plugin_id": "user.comdirect-ertraege",
            "amount": 0,
            "confirmed": False,
            "empty": "",
            "empty_list": [],
            "missing": None,
            "not_applicable": {"status": "NOT_APPLICABLE"},
            "events": [{"cash_movements": [{"amount": "1,61", "currency": "EUR"}]}],
            "evidence": [{"evidence_id": "e1", "page_number": 2, "excerpt": "1,61 EUR"}],
        },
        "rule_decisions": [{"field_path": "amount", "effective_value": 999}],
        "annotations": [{"field_path": "manual", "reference_value": "not-parser"}],
    }
    rows = build_standard_value_rows(report)
    paths = {row.path for row in rows}
    assert "amount" in paths and "confirmed" in paths
    assert "events[0].cash_movements[0].amount" in paths
    assert "empty" not in paths and "empty_list" not in paths
    assert "missing" not in paths and "not_applicable" not in paths
    assert all(row.value != 999 for row in rows)
    assert all("manual" not in row.path for row in rows)


def test_missing_evidence_remains_visible_as_review_and_catalog_description_is_used(tmp_path):
    report = {"result": {"value": "0,733", "evidence": []}}
    rows = build_standard_value_rows(report)
    assert len(rows) == 1
    assert rows[0].status == "Evidence fehlt / Prüfen"
    assert rows[0].description == "Zusätzlicher Wert des zugehörigen Objekts"


def test_dialog_search_details_and_count():
    application = app()
    rows = build_standard_value_rows({"result": {"isin": "DE0007164600", "quantity": 0.733}})
    dialog = StandardValuesDialog(rows)
    try:
        assert dialog.table.rowCount() == 2
        assert "2 von 2" in dialog.count.text()
        dialog.search.setText("isin")
        application.processEvents()
        assert dialog.count.text().startswith("1 von 2")
        assert not dialog.table.isColumnHidden(1)
        assert dialog.table.isColumnHidden(3)
        dialog.details.setChecked(True)
        assert not dialog.table.isColumnHidden(3)
        assert not dialog.table.isColumnHidden(7)
    finally:
        dialog.close()


def test_description_lookup_normalizes_list_indices_and_value_wrapper(tmp_path):
    catalog = CatalogStore(tmp_path / "catalogs").catalog(
        "generic", "bank.parser", "kontoauszug", "*")
    report = {"result": {
        "accounts": [
            {"bank_name": {"value": "Bank A"}, "iban": {"value": "DE123"}},
            {"bank_name": {"value": "Bank B"}},
        ]
    }}
    assert normalize_description_path("accounts[1].bank_name.value") == "accounts[].bank_name"
    rows = build_standard_value_rows(report, catalog)
    bank_rows = [row for row in rows if row.path.endswith("bank_name.value")]
    assert len(bank_rows) == 2
    assert all(row.description == "Name der Bank, bei der das Konto geführt wird" for row in bank_rows)
    assert any(row.path.endswith("iban.value") and "Bankkontonummer" in row.description for row in rows)


def test_derived_description_is_persisted_and_reused(tmp_path):
    path = tmp_path / "descriptions.json"
    first = DescriptionCatalog.load(path)
    entry = first.resolve("accounts[0].custom_reference.value")
    first.save()
    second = DescriptionCatalog.load(path)
    reused = second.resolve("accounts[1].custom_reference.value")
    assert entry.description == "Zusätzlicher Referenzwert des Bankkontos"
    assert reused.description == entry.description
    assert reused.source == "dto_context_derived"
    assert reused.status == "AUTO_DERIVED"
