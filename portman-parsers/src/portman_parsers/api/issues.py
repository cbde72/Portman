"""Machine-readable validation and review findings."""

from dataclasses import dataclass
from enum import StrEnum


class IssueSeverity(StrEnum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class IssueNature(StrEnum):
    MISSING_INFORMATION = "MISSING_INFORMATION"
    UNSECURED_ASSIGNMENT = "UNSECURED_ASSIGNMENT"
    MATHEMATICAL_INCONSISTENCY = "MATHEMATICAL_INCONSISTENCY"
    CONFIRMED_DEVIATION = "CONFIRMED_DEVIATION"


@dataclass(frozen=True, slots=True)
class Issue:
    issue_id: str
    code: str
    severity: IssueSeverity
    message: str
    evidence_id: str | None = None
    event_id: str | None = None
    nature: IssueNature | None = None

    def __post_init__(self) -> None:
        if not self.issue_id or not self.code or not self.message:
            raise ValueError("issue_id, code and message are required")

