"""Input document contracts; binary PDF content is intentionally excluded."""

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping


def _frozen_mapping(value: Mapping[str, str]) -> Mapping[str, str]:
    return MappingProxyType(dict(sorted(value.items())))


@dataclass(frozen=True, slots=True)
class PdfPage:
    number: int
    text: str
    source_ref: str = ""
    extraction_method: str = "text"
    confidence: float | None = None

    def __post_init__(self) -> None:
        if self.number < 1:
            raise ValueError("page number must be positive")
        if self.confidence is not None and not 0 <= self.confidence <= 1:
            raise ValueError("page confidence must be between 0 and 1")


@dataclass(frozen=True, slots=True)
class PdfDocument:
    document_id: str
    source_hash: str
    pages: tuple[PdfPage, ...]
    filename: str = ""
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.document_id or not self.source_hash:
            raise ValueError("document_id and source_hash are required")
        if len({page.number for page in self.pages}) != len(self.pages):
            raise ValueError("page numbers must be unique")
        object.__setattr__(self, "pages", tuple(sorted(self.pages, key=lambda page: page.number)))
        object.__setattr__(self, "metadata", _frozen_mapping(self.metadata))

    @property
    def text(self) -> str:
        return "\n".join(page.text for page in self.pages)

