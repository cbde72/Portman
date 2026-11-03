"""Structured context passed from field analysis into the existing training UI."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from typing import Any


@dataclass(frozen=True)
class TrainingContext:
    """Everything the training UI needs, without relying on table row numbers.

    The context is deliberately independent from visible widgets.  A sorted or
    filtered field-analysis table can therefore hand over a stable context while
    the training tab still knows the document, parser, field and evidence.
    """

    document_id: str = ""
    document_hash: str = ""
    bank: str = ""
    parser_id: str = ""
    handler_id: str = ""
    document_type: str = ""
    rule_mode: str = "STANDARD"
    field_path: str = ""
    field_id: str = ""
    field_name: str = ""
    requirement: str = ""
    data_type: str = ""
    current_value: Any = None
    reference_value: Any = None
    evidence: Any = None
    page_number: int = 0
    original_text: str = ""
    selected_text: str = ""
    coordinates: Any = None
    catalog_version: int = 0
    rule_profile_version: int = 0
    annotation_id: int | None = None
    candidate_id: int | None = None
    candidate_status: str = ""
    training_status: str = "Untrainiert"
    source: str = ""
    report: Any = field(default=None, compare=False, repr=False)

    def as_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value.pop("report", None)
        return value

    def with_selection(self, selection, field_path: str | None = None) -> "TrainingContext":
        """Return a copy enriched with a direct PDF selection."""
        if selection is None:
            return self
        return replace(
            self,
            field_path=field_path or self.field_path,
            page_number=int(getattr(selection, "page_number", 0) or self.page_number or 1),
            original_text=str(getattr(selection, "text", "") or self.original_text),
            selected_text=str(getattr(selection, "text", "") or self.selected_text),
            coordinates=getattr(selection, "coordinates", None) or self.coordinates,
        )

    @property
    def has_document(self) -> bool:
        return bool(self.parser_id or self.document_id)
