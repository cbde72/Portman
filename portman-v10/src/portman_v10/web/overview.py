"""Stichtagsnavigation der Web-Testoberfläche (reine Datumslogik, keine Bestandsberechnung)."""
from calendar import monthrange
from datetime import date, timedelta

STEPS = (("day", "Tag"), ("week", "Woche"), ("month", "Monat"), ("year", "Jahr"))


def _shift_months(value: date, months: int, anchor_day: int) -> date:
    """Monat/Jahr verschieben und den Ankertag halten; kürzere Monate enden am Monatsletzten."""
    index = value.year * 12 + value.month - 1 + months
    year, month = divmod(index, 12)
    month += 1
    return date(year, month, min(anchor_day, monthrange(year, month)[1]))


def shift(value: date, step: str, direction: int, anchor_day: int | None = None) -> date:
    anchor = anchor_day or value.day
    if step == "day":
        return value + timedelta(days=direction)
    if step == "week":
        return value + timedelta(weeks=direction)
    if step == "month":
        return _shift_months(value, direction, anchor)
    if step == "year":
        return _shift_months(value, 12 * direction, anchor)
    raise ValueError("Unbekannter Schritt")


def parse_anchor(raw: str | None, as_of: date) -> int:
    try:
        anchor = int(raw or "")
    except ValueError:
        return as_of.day
    return anchor if 1 <= anchor <= 31 and anchor >= as_of.day else as_of.day
