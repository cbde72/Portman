"""PDF-Lab facade for the shared parser-side text preparation contract."""

from portman_parsers.extraction.pdf_text_preparation import (
    PREPARATION_VERSION,
    PagePreparation,
    PreparedPdf,
    TextBlock,
    TextSpan,
    prepare_pdf,
)

__all__ = [
    "PREPARATION_VERSION", "PagePreparation", "PreparedPdf", "TextBlock",
    "TextSpan", "prepare_pdf",
]
