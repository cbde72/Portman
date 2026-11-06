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
    """Vergleicht endliche Dezimalstrings stellenweise, ohne Float oder Decimal-Kontext."""
    left = canonical_decimal(left)
    right = canonical_decimal(right)

    def magnitude(value: str) -> tuple[int, str, str]:
        integer, separator, fraction = value.lstrip("-").partition(".")
        return len(integer), integer, fraction if separator else ""

    left_negative = left.startswith("-")
    right_negative = right.startswith("-")
    if left_negative != right_negative:
        return -1 if left_negative else 1
    left_magnitude = magnitude(left)
    right_magnitude = magnitude(right)
    scale = max(len(left_magnitude[2]), len(right_magnitude[2]))
    left_key = (left_magnitude[0], left_magnitude[1], left_magnitude[2].ljust(scale, "0"))
    right_key = (right_magnitude[0], right_magnitude[1], right_magnitude[2].ljust(scale, "0"))
    result = (left_key > right_key) - (left_key < right_key)
    return -result if left_negative else result


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
