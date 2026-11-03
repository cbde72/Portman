from decimal import Decimal, InvalidOperation


def decimal_value(value: str, *, decimal_separator: str = ".") -> Decimal | None:
    normalized = value.strip()
    if decimal_separator == ",":
        normalized = normalized.replace(".", "").replace(",", ".")
    try:
        return Decimal(normalized)
    except (InvalidOperation, AttributeError):
        return None

