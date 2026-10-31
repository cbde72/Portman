"""Traceable evidence for extracted values."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Evidence:
    evidence_id: str
    document_id: str
    page_number: int
    field: str
    excerpt: str = ""
    source_ref: str = ""
    document_hash: str = ""
    parser_id: str = ""
    handler_id: str = ""
    parser_version: str = ""
    review_status: str = "UNREVIEWED"

    def __post_init__(self) -> None:
        if not self.evidence_id or not self.document_id or not self.field:
            raise ValueError("evidence identity, document identity and field are required")
        if self.page_number < 1:
            raise ValueError("evidence page number must be positive")

