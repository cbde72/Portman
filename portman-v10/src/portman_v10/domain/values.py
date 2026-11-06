"""Exakte Werte; keine Oberfläche und keine Persistenzabhängigkeit."""
from dataclasses import dataclass
from decimal import Decimal
import re

_PATTERN = re.compile(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?\Z")


def canonical_decimal(text: str) -> str:
    """Gibt einen validierten endlichen Dezimalwert ohne überflüssige Nullen zurück."""
    if not isinstance(text, str) or not _PATTERN.fullmatch(text):
        raise ValueError("Ein endlicher Dezimalstring ohne Exponent ist erforderlich")
    negative = text.startswith("-")
    unsigned = text[1:] if negative else text
    integer, separator, fraction = unsigned.partition(".")
    fraction = fraction.rstrip("0")
    if not integer.lstrip("0") and not fraction:
        return "0"
    result = integer + (f".{fraction}" if separator and fraction else "")
    return f"-{result}" if negative else result


def compare_decimal_text(left: str, right: str) -> int:
    """Vergleicht Dezimalstrings ohne Float und ohne Decimal-Arithmetik-Kontext."""
    left_value = Decimal(canonical_decimal(left))
    right_value = Decimal(canonical_decimal(right))
    return (left_value > right_value) - (left_value < right_value)


def sum_decimal_text(values: list[str] | tuple[str, ...]) -> str:
    """Addiert Dezimalstrings als Ganzzahlkoeffizienten, unabhängig vom Decimal-Kontext."""
    parts = [canonical_decimal(value).partition(".") for value in values]
    scale = max((len(fraction) for _, _, fraction in parts), default=0)
    total = 0
    for integer, separator, fraction in parts:
        digits = integer + (fraction if separator else "")
        coefficient = int(digits) if digits else 0
        total += coefficient * 10 ** (scale - len(fraction))
    sign = "-" if total < 0 else ""
    digits = str(abs(total)).rjust(scale + 1, "0")
    if not scale:
        return sign + digits
    return canonical_decimal(f"{sign}{digits[:-scale]}.{digits[-scale:]}")

@dataclass(frozen=True, slots=True)
class ExactValue:
    text: str

    def __post_init__(self):
        if not isinstance(self.text, str) or not _PATTERN.fullmatch(self.text):
            raise ValueError("Ein endlicher Dezimalstring ohne Exponent ist erforderlich")

    @property
    def decimal(self) -> Decimal:
        return Decimal(self.text)
