from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable

from ..models import ImportBatch


@dataclass(frozen=True)
class PdfPage:
    number: int
    text: str
    used_ocr: bool = False
    confidence: float | None = None


@dataclass(frozen=True)
class PdfDocument:
    path: Path
    content: bytes
    file_hash: str
    pages: tuple[PdfPage, ...]

    @property
    def text(self):
        return '\n'.join(page.text for page in self.pages)


@dataclass(frozen=True)
class Detection:
    confidence: float
    document_type: str
    handler_id: str
    reason: str = ''


@dataclass
class ParseContext:
    batch: ImportBatch
    options: dict = field(default_factory=dict)


@runtime_checkable
class PdfImporterPlugin(Protocol):
    """One bank plugin may expose any number of document handlers."""
    plugin_id: str
    bank_name: str
    version: str

    def detect(self, document: PdfDocument) -> list[Detection]: ...
    def parse(self, document: PdfDocument, detection: Detection,
              context: ParseContext) -> ImportBatch: ...
