"""Synthetic/plain-text adapter used by tests and the Phase-3 demo."""

from portman_parsers.api import PdfPage


def pages_from_text(*texts: str) -> tuple[PdfPage, ...]:
    return tuple(PdfPage(number=index, text=text, source_ref=f"text:{index}")
                 for index, text in enumerate(texts, 1))

