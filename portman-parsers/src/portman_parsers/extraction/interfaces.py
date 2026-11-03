"""Lazy extraction boundary; no PDF or OCR dependency is imported here."""

from pathlib import Path
from typing import Protocol

from portman_parsers.api import PdfPage


class TextExtractor(Protocol):
    def extract(self, source: Path) -> tuple[PdfPage, ...]: ...

