"""Reference-aware quality summaries; technical success is never approval."""

from dataclasses import dataclass

from portman_pdf_lab.reviews.models import ReviewStatus

QUALITY_CATEGORIES = (
    "document_detection", "extracted_fields", "cashflow", "depot_holdings",
    "tax_components", "fees", "references", "evidence",
)


@dataclass(frozen=True, slots=True)
class QualitySummary:
    status: ReviewStatus
    reviewed_fields: int
    matching_fields: int
    score: float | None
    categories: tuple[str, ...] = QUALITY_CATEGORIES


def reference_quality_summary(reference_comparison: tuple[dict, ...] | list[dict],
                              status: ReviewStatus = ReviewStatus.NOT_REVIEWED) -> QualitySummary:
    comparisons = tuple(reference_comparison)
    matches = sum(bool(item.get("matches")) for item in comparisons)
    score = matches / len(comparisons) if comparisons else None
    return QualitySummary(status, len(comparisons), matches, score)
