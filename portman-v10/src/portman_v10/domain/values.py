"""Exakte Werte; keine Oberfläche und keine Persistenzabhängigkeit."""
from dataclasses import dataclass
from decimal import Decimal
import re

_PATTERN = re.compile(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?\Z")

@dataclass(frozen=True, slots=True)
class ExactValue:
    text: str

    def __post_init__(self):
        if not isinstance(self.text, str) or not _PATTERN.fullmatch(self.text):
            raise ValueError("Ein endlicher Dezimalstring ohne Exponent ist erforderlich")

    @property
    def decimal(self) -> Decimal:
        return Decimal(self.text)
