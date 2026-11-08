"""SQLite-Hilfen für exakte Dezimalvergleiche; keine Migration oder Persistenzschicht."""
from math import gcd
import sqlite3

from portman_v10.domain.values import compare_decimal_text


DECIMAL_COLLATION = "PORTMAN_DECIMAL"
RATIONAL_COLLATION = "PORTMAN_RATIONAL"


def register_decimal_collation(connection: sqlite3.Connection) -> None:
    """Registriert die numerische Textsortierung vor Nutzung entsprechender Indizes."""
    connection.create_collation(DECIMAL_COLLATION, compare_decimal_text)


def compare_rational_text(left: str, right: str) -> int:
    """Vergleicht normalisierte Zähler/Nenner-Werte exakt per Kreuzmultiplikation."""
    def parse(value: str) -> tuple[int, int]:
        numerator, separator, denominator = value.partition("/")
        if not separator:
            raise ValueError("Rationalwert muss als Zähler/Nenner vorliegen")
        parsed_numerator, parsed_denominator = int(numerator), int(denominator)
        if parsed_denominator <= 0 or gcd(abs(parsed_numerator), parsed_denominator) != 1:
            raise ValueError("Rationalwert muss normalisiert und mit positivem Nenner vorliegen")
        return parsed_numerator, parsed_denominator

    left_numerator, left_denominator = parse(left)
    right_numerator, right_denominator = parse(right)
    left_cross = left_numerator * right_denominator
    right_cross = right_numerator * left_denominator
    return (left_cross > right_cross) - (left_cross < right_cross)


def register_rational_collation(connection: sqlite3.Connection) -> None:
    """Registriert die numerische Sortierung rational gespeicherter Berechnungswerte."""
    connection.create_collation(RATIONAL_COLLATION, compare_rational_text)
