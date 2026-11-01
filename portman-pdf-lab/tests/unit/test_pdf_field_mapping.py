import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QApplication, QLineEdit

from portman_pdf_lab.field_catalog import CatalogStore
from portman_pdf_lab.storage import ReferenceRepository
from portman_pdf_lab.training import SafeRuleEngine
from portman_pdf_lab.ui.field_mapping import EditorFactory, FieldMappingDialog, catalog_help_html
from portman_pdf_lab.ui.pdf_text_layer import PdfTextLayer
from portman_pdf_lab.ui.result_view import DisplayRow, RecognitionStatus, ResultTable
from portman_pdf_lab.ui.field_analysis import build_field_analysis_rows
from portman_parsers.registry.allowlist import APPROVED_PLUGINS


def app():
    return QApplication.instance() or QApplication([])


def select(layer, start, end):
    cursor = layer.textCursor(); cursor.setPosition(start); cursor.setPosition(end, QTextCursor.KeepAnchor); layer.setTextCursor(cursor)


def test_pdf_text_layer_multiline_selection_copy_page_and_marking():
    application = app(); layer = PdfTextLayer(); layer.set_pages({1: "Zeile eins\nZeile zwei", 2: "Andere Seite"})
    select(layer, 6, 21); selection = layer.remember_selection()
    assert selection.text == "eins\nZeile zwei" and selection.page_number == 1 and selection.coordinates is None
    layer.copy(); assert application.clipboard().text() == "eins\nZeile zwei"
    layer.show_page(2); layer.show_page(1)
    assert layer.extraSelections() and layer.markings[1][0] == selection


def test_scanned_page_has_explicit_no_textlayer_message():
    layer = PdfTextLayer(); layer.set_pages({1: ""})
    assert not layer.isEnabled() and "OCR" in layer.toPlainText() and layer.selection() is None


def test_catalog_does_not_create_new_user_fields(tmp_path):
    store = CatalogStore(tmp_path / "catalogs")
    catalog = store.catalog("comdirect", "user.comdirect-ertraege", "Kauf", "layout-a")
    assert catalog.field("trade.venue") is None
    with pytest.raises(ValueError, match="nicht angelegt"):
        store.add_optional_field(catalog, "trade.counterparty", "Gegenpartei")
    restarted = store.catalog("comdirect", "user.comdirect-ertraege", "Kauf", "layout-a")
    assert restarted.version == catalog.version
    assert restarted.field("trade.counterparty") is None
    assert "Optionale Werte" in catalog_help_html(restarted)


def test_catalog_driven_editors_preserve_original_and_normalized_values(tmp_path):
    catalog = CatalogStore(tmp_path).catalog()
    isin = catalog.field("security.isin"); decimal = catalog.field("trade.quantity")
    assert isinstance(EditorFactory.create(isin, "DE0008474511"), QLineEdit)
    original, normalized = EditorFactory.normalize("1.234,500", decimal, "DECIMAL_DE")
    assert original == "1.234,500" and normalized == "1234.500"


def test_mapping_only_existing_fields_even_when_define_new_requested(tmp_path):
    application = app(); store = CatalogStore(tmp_path); catalog = store.catalog()
    context = {"bank": "comdirect", "parser_id": "user.comdirect-ertraege", "document_type": "Kauf", "rule_mode": "STANDARD"}
    dialog = FieldMappingDialog(catalog, store, context, "1,25", 2, define_new=True)
    assert not hasattr(dialog, "new_field")
    assert not hasattr(dialog, "new_id")
    index = next(i for i in range(dialog.field_choice.count()) if dialog.field_choice.itemData(i) == "trade.quantity")
    dialog.field_choice.setCurrentIndex(index); dialog._accept()
    assert dialog.mapping_result.field.path == "events[0].trades[0].quantity"
    assert dialog.mapping_result.page_number == 2


def test_annotation_coordinates_survive_repository_restart(tmp_path):
    path = tmp_path / "annotations.sqlite"; repo = ReferenceRepository(path)
    repo.register_document("doc", "a" * 64, "synthetic.pdf", "comdirect", "Kauf")
    annotation = repo.create_annotation("doc", "parser", "handler", 2, "Handelsplatz: XETRA",
                                        "attributes.user_fields.trade.venue", "XETRA", "TEXT",
                                        "CONFIRMED", "IN_REVIEW", "tester", [[10, 20, 30, 40]])
    restored = ReferenceRepository(path).annotation(annotation)
    assert restored["page_number"] == 2 and restored["coordinates"] == [[10, 20, 30, 40]]


def test_label_value_rule_generalizes_to_two_values():
    engine = SafeRuleEngine(); annotation = {"annotation_id": 1, "field_path": "attributes.user_fields.trade.venue",
        "original_text": "Handelsplatz: XETRA", "reference_value": "XETRA", "annotation_kind": "TEXT"}
    rule = engine.suggest(annotation)
    assert rule["rule_type"] == "REGEX_FIELD" and "XETRA" not in rule["pattern"]
    assert engine.execute(rule, "Handelsplatz: XETRA") == "XETRA"
    assert engine.execute(rule, "Handelsplatz: Tradegate") == "Tradegate"


def test_result_table_colors_entire_row():
    table = ResultTable(); table.set_rows([DisplayRow("x", "X", None, status=RecognitionStatus.MISSING)])
    assert all(table.item(0, column).background().color().alpha() > 0 for column in range(table.columnCount()))


def test_every_implemented_handler_has_a_specific_nontechnical_catalog(tmp_path):
    store = CatalogStore(tmp_path)
    for plugin in APPROVED_PLUGINS:
        for handler in plugin.handlers:
            if not handler.implemented:
                continue
            catalog = store.catalog(plugin.group.casefold().replace(" / ", "-"), plugin.plugin_id, handler.document_type, "*")
            assert any(field.requirement != "TECHNICAL" for field in catalog.fields), (plugin.plugin_id, handler.handler_id)


def test_trade_dependencies_and_account_document_do_not_create_security_errors(tmp_path):
    store = CatalogStore(tmp_path)
    catalog = store.catalog("comdirect", "user.comdirect-ertraege", "comdirect Wertpapierkauf", "*")
    result = {"events":[{"trades":[{"isin":"DE0008474511","evidence_ids":["ev"]}]}],
              "evidence":[{"evidence_id":"ev","page_number":1,"excerpt":"ISIN DE0008474511"}]}
    rows = {row.field_id: row for row in build_field_analysis_rows({"result":result}, catalog)}
    assert rows["security.isin"].status == RecognitionStatus.RECOGNIZED
    assert rows["security.wkn"].status == RecognitionStatus.NOT_APPLICABLE
    assert "trade.venue" not in rows
    assert rows["trade.quantity"].status == RecognitionStatus.MISSING
    account = store.catalog("bank of scotland", "user.bank-of-scotland-kontoauszug", "Bank of Scotland Kontoauszug", "*")
    assert not any(field.field_id.startswith(("security.", "trade.")) for field in account.fields)


def test_saved_custom_field_definitions_are_purged_from_yaml(tmp_path):
    from portman_pdf_lab.field_catalog import FieldCatalog, FieldDefinition
    store = CatalogStore(tmp_path / "catalogs")
    catalog = store.catalog("comdirect", "user.comdirect-ertraege", "Kauf", "layout-a")
    legacy = FieldDefinition("user.custom", "attributes.user_fields.user.custom",
                             "Altes Benutzerfeld", "Überholte Benutzerdefinition")
    legacy_catalog = FieldCatalog(catalog.bank, catalog.parser_id, catalog.document_type,
                                  catalog.layout, catalog.version, catalog.fields + (legacy,), catalog.path)
    legacy_catalog.save(catalog.path)
    loaded = store.catalog("comdirect", "user.comdirect-ertraege", "Kauf", "layout-a")
    assert loaded.field("user.custom") is None
    assert all(not item.path.startswith("attributes.user_fields.") for item in loaded.fields)
    assert all(not item.path.startswith("attributes.user_fields.")
               for item in FieldCatalog.load(catalog.path).fields)
