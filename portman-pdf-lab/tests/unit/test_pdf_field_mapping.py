import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QApplication, QLineEdit

from portman_pdf_lab.field_catalog import CatalogStore
from portman_pdf_lab.storage import ReferenceRepository
from portman_pdf_lab.training import SafeRuleEngine
from portman_pdf_lab.ui.field_mapping import EditorFactory, FieldMappingDialog, catalog_help_html
from portman_pdf_lab.ui.pdf_text_layer import PdfTextLayer
from portman_pdf_lab.ui.result_view import DisplayRow, RecognitionStatus, ResultTable


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


def test_catalog_yaml_versions_custom_optional_field_and_help(tmp_path):
    store = CatalogStore(tmp_path / "catalogs")
    catalog = store.catalog("comdirect", "user.comdirect-ertraege", "Kauf", "layout-a")
    assert catalog.field("security.isin").path != catalog.field("security.wkn").path
    assert catalog.field("trade.venue").requirement == "OPTIONAL"
    updated, custom = store.add_optional_field(catalog, "trade.counterparty", "Gegenpartei")
    restarted = store.catalog("comdirect", "user.comdirect-ertraege", "Kauf", "layout-a")
    assert updated.version == 2 and restarted.field(custom.path).requirement == "OPTIONAL"
    help_text = catalog_help_html(restarted)
    assert "Unbedingt erforderliche" in help_text and "Optionale Werte" in help_text and "Gegenpartei" in help_text


def test_catalog_driven_editors_preserve_original_and_normalized_values(tmp_path):
    catalog = CatalogStore(tmp_path).catalog()
    isin = catalog.field("security.isin"); decimal = catalog.field("trade.quantity")
    assert isinstance(EditorFactory.create(isin, "DE0008474511"), QLineEdit)
    original, normalized = EditorFactory.normalize("1.234,500", decimal, "DECIMAL_DE")
    assert original == "1.234,500" and normalized == "1234.500"


def test_mapping_existing_and_new_optional_field(tmp_path):
    application = app(); store = CatalogStore(tmp_path); catalog = store.catalog()
    context = {"bank": "comdirect", "parser_id": "user.comdirect-ertraege", "document_type": "Kauf", "rule_mode": "STANDARD"}
    dialog = FieldMappingDialog(catalog, store, context, "XETRA", 2)
    index = next(i for i in range(dialog.field_choice.count()) if dialog.field_choice.itemData(i) == "trade.venue")
    dialog.field_choice.setCurrentIndex(index); dialog._accept()
    assert dialog.mapping_result.field.path == "attributes.user_fields.trade.venue" and dialog.mapping_result.page_number == 2
    custom = FieldMappingDialog(catalog, store, context, "Spezialwert", 1, define_new=True)
    custom.new_id.setText("trade.special"); custom.new_label.setText("Spezial"); custom._accept()
    assert custom.mapping_result.field.path == "attributes.user_fields.trade.special"


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
