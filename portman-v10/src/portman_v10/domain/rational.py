"""Exakte rationale Rechenwerte für nicht terminierende Dezimalanteile."""
from dataclasses import dataclass
from math import gcd

from portman_v10.domain.values import canonical_decimal


@dataclass(frozen=True, slots=True)
class RationalAmount:
    """Normalisierter Bruch; im Gegensatz zu Anzeigewerten nie gerundet."""

    numerator: int
    denominator: int = 1

    def __post_init__(self) -> None:
        if any(not isinstance(value, int) or isinstance(value, bool) for value in (self.numerator, self.denominator)):
            raise TypeError("Rationalwerte bestehen ausschließlich aus Ganzzahlen")
        if self.denominator == 0:
            raise ZeroDivisionError("Der Nenner darf nicht null sein")
        numerator = self.numerator
        denominator = self.denominator
        if denominator < 0:
            numerator = -numerator
            denominator = -denominator
        divisor = gcd(abs(numerator), denominator)
        object.__setattr__(self, "numerator", numerator // divisor)
        object.__setattr__(self, "denominator", denominator // divisor)

    @classmethod
    def from_decimal(cls, value: str) -> "RationalAmount":
        canonical = canonical_decimal(value)
        integer, separator, fraction = canonical.partition(".")
        scale = len(fraction) if separator else 0
        coefficient_text = integer + (fraction if separator else "")
        return cls(int(coefficient_text), 10**scale)

    @classmethod
    def from_storage_text(cls, value: str) -> "RationalAmount":
        numerator, separator, denominator = value.partition("/")
        if not separator or not numerator or not denominator:
            raise ValueError("Rationalwert muss als Zähler/Nenner vorliegen")
        try:
            parsed = cls(int(numerator), int(denominator))
        except ValueError as error:
            raise ValueError("Rationalwert enthält ungültige Ganzzahlen") from error
        if parsed.to_storage_text() != value:
            raise ValueError("Rationalwert muss normalisiert gespeichert werden")
        return parsed

    def to_storage_text(self) -> str:
        return f"{self.numerator}/{self.denominator}"

    def __add__(self, other: "RationalAmount") -> "RationalAmount":
        return RationalAmount(
            self.numerator * other.denominator + other.numerator * self.denominator,
            self.denominator * other.denominator,
        )

    def __sub__(self, other: "RationalAmount") -> "RationalAmount":
        return RationalAmount(
            self.numerator * other.denominator - other.numerator * self.denominator,
            self.denominator * other.denominator,
        )

    def __mul__(self, other: "RationalAmount") -> "RationalAmount":
        return RationalAmount(self.numerator * other.numerator, self.denominator * other.denominator)

    def __truediv__(self, other: "RationalAmount") -> "RationalAmount":
        if other.numerator == 0:
            raise ZeroDivisionError("Division durch null")
        return RationalAmount(self.numerator * other.denominator, self.denominator * other.numerator)

    def __lt__(self, other: "RationalAmount") -> bool:
        return self.numerator * other.denominator < other.numerator * self.denominator

    def is_exact_at_scale(self, scale: int) -> bool:
        """True wenn die Zahl ohne Rundung auf die gewünschte Stellenzahl passt."""
        if scale < 0:
            raise ValueError("Anzeigeskala darf nicht negativ sein")
        return (abs(self.numerator) * 10**scale) % self.denominator == 0

    def display(self, scale: int) -> str:
        """Rundet nur für die Darstellung auf scale Stellen, kaufmännisch half-up."""
        if scale < 0:
            raise ValueError("Anzeigeskala darf nicht negativ sein")
        sign = "-" if self.numerator < 0 else ""
        scaled_numerator = abs(self.numerator) * 10**scale
        rounded, remainder = divmod(scaled_numerator, self.denominator)
        if remainder * 2 >= self.denominator:
            rounded += 1
        digits = str(rounded)
        if not scale:
            return sign + digits
        digits = digits.rjust(scale + 1, "0")
        return f"{sign}{digits[:-scale]}.{digits[-scale:]}"
