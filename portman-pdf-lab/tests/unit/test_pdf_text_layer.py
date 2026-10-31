import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from portman_pdf_lab.ui.pdf_text_layer import PdfTextLayer


def app():
    return QApplication.instance() or QApplication([])


def test_text_layer_keeps_clean_layout_and_original_variants():
    application = app()
    layer = PdfTextLayer()
    variants = {1: {
        "Bereinigt": "SAP\n0,733\n2,20 EUR",
        "Layout": "SAP        0,733       2,20 EUR",
        "Original": "SAP @@@@@@@@@@@ 0,733 2,20 EUR",
    }}
    layer.set_page_variants(variants)
    assert layer.toPlainText() == variants[1]["Bereinigt"]
    layer.set_view_mode("Original")
    assert layer.toPlainText() == variants[1]["Original"]
    layer.set_view_mode("Layout")
    assert layer.toPlainText() == variants[1]["Layout"]
    application.processEvents()
