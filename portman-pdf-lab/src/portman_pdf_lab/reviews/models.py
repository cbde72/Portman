from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum


class ReviewStatus(StrEnum):
    NOT_REVIEWED = "NOT_REVIEWED"
    IN_REVIEW = "IN_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    NEEDS_CORRECTION = "NEEDS_CORRECTION"

    # Compatibility aliases for the Phase-3 demonstration API.
    OPEN = "NOT_REVIEWED"
    ACCEPTED = "APPROVED"


@dataclass(frozen=True, slots=True)
class ReviewDecision:
    result_id: str
    status: ReviewStatus
    reviewer: str
    reason: str
    decided_at: datetime

    @classmethod
    def create(cls, result_id: str, status: ReviewStatus, reviewer: str,
               reason: str) -> "ReviewDecision":
        return cls(result_id, status, reviewer, reason, datetime.now(timezone.utc))

