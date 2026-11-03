from decimal import Decimal


CENT = Decimal("0.01")


def within_tolerance(actual: Decimal, expected: Decimal, tolerance: Decimal = CENT) -> bool:
    if not all(isinstance(value, Decimal) for value in (actual, expected, tolerance)):
        raise TypeError("money validation requires Decimal values")
    if tolerance < 0:
        raise ValueError("tolerance must not be negative")
    return abs(actual - expected) <= tolerance

