"""Small shared value helpers without provider or storage dependencies."""
import math
from datetime import datetime, timezone


def utcnow():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def finite(value):
    if isinstance(value, bool):
        return None
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (TypeError, ValueError):
        return None
