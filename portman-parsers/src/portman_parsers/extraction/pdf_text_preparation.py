"""Named public entry point for Phase 7.3 PDF text preparation.

The implementation lives in :mod:`preparation`; this module keeps the
descriptive API name without creating a second preparation pipeline.
"""

from .preparation import (
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
