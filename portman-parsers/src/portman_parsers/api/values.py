"""Field-level value semantics shared by master data and parser results."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Generic, TypeVar


class MissingValue(StrEnum):
    UNKNOWN = "UNKNOWN"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    NOT_FOUND = "NOT_FOUND"


class ValueSource(StrEnum):
    PDF = "PDF"
    MANUAL = "MANUAL"
    DERIVED = "DERIVED"
    NOT_PROVIDED = "NOT_PROVIDED"


class ReviewStatus(StrEnum):
    UNREVIEWED = "UNREVIEWED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class FieldValue(Generic[T]):
    """A value plus its origin and review trail.

    PDF values always identify their source page and at least one Evidence.
    Unknown properties use a MissingValue instead of guessed content.
    """

    value: T | MissingValue
    source: ValueSource
    review_status: ReviewStatus = ReviewStatus.UNREVIEWED
    page_number: int | None = None
    evidence_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence_ids", tuple(self.evidence_ids))
        if self.source == ValueSource.PDF:
            if self.page_number is None or self.page_number < 1 or not self.evidence_ids:
                raise ValueError("PDF field values require a page and Evidence reference")
        elif self.page_number is not None:
            raise ValueError("only PDF field values may carry a PDF page")
        if isinstance(self.value, MissingValue) and self.source in {ValueSource.MANUAL, ValueSource.DERIVED}:
            raise ValueError("manual or derived values must not pretend to contain missing information")

    @classmethod
    def unknown(cls) -> "FieldValue[T]":
        return cls(MissingValue.UNKNOWN, ValueSource.NOT_PROVIDED)

    @classmethod
    def from_pdf(cls, value: T, page_number: int, *evidence_ids: str,
                 review_status: ReviewStatus = ReviewStatus.UNREVIEWED) -> "FieldValue[T]":
        return cls(value, ValueSource.PDF, review_status, page_number, tuple(evidence_ids))

    @classmethod
    def manual(cls, value: T, review_status: ReviewStatus = ReviewStatus.VERIFIED) -> "FieldValue[T]":
        return cls(value, ValueSource.MANUAL, review_status)

