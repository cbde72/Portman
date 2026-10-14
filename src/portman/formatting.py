"""Shared German-locale number and currency formatting for views and dialogs."""
from decimal import Decimal

DASH = '–'


def number(value, *, empty=DASH, decimals=2):
    """Format a number German-style, e.g. 1234.5 -> '1.234,50'."""
    if value is None:
        return empty
    return f'{Decimal(value):,.{decimals}f}'.replace(',', 'X').replace('.', ',').replace('X', '.')


def euro(value, *, empty=DASH):
    """Format a value as German currency, e.g. 1234.5 -> '1.234,50 €'."""
    if value is None:
        return empty
    return number(value) + ' €'
