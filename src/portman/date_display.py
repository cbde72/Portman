"""German dates for presentation; stored dates remain ISO for ordering."""
import re
from datetime import date


def display_dates(value):
    if not isinstance(value, str):
        return value
    def replace(match):
        try:
            return date.fromisoformat(match[0]).strftime('%d.%m.%Y')
        except ValueError:
            return match[0]
    value = re.sub(r'(?<![\w-])\d{4}-\d{2}-\d{2}(?!\d)', replace, value)
    # Month-only sources must not acquire a fictitious statement day.
    return re.sub(r'(?<![\w-])(\d{4})-(0[1-9]|1[0-2])(?![\w-])',
                  lambda m: m[2] + '.' + m[1], value)
