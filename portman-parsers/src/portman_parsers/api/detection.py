"""Parser detection result."""

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class Detection:
    plugin_id: str
    plugin_version: str
    handler_id: str
    document_type: str
    confidence: Decimal
    reason: str = ""

    def __post_init__(self) -> None:
        value = Decimal(self.confidence)
        if not Decimal("0") <= value <= Decimal("1"):
            raise ValueError("detection confidence must be between 0 and 1")
        object.__setattr__(self, "confidence", value)

