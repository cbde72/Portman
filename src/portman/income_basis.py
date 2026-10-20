"""One documented net/gross rule for investment income across all views.

``income_basis`` states what the booked ``amount`` already is: ``'gross'``
means the booking is the credit *before* taxes (comdirect settles taxes as
separate bookings, see docs/pdf-import.md), ``'net'`` means it is the net
receipt (ING, Baader).  A documented ``gross_income`` only qualifies when its
currency matches the booking currency — the repository performs no income FX
conversion, so a foreign-currency gross must never enter a booking-currency
sum (it is replaced by the component reconstruction instead).
"""
from decimal import Decimal, InvalidOperation


def _number(value):
    try:
        result = Decimal(str(value))
        return result if result.is_finite() else None
    except (InvalidOperation, TypeError, ValueError):
        return None


def gross_income_amount(tx):
    """Documented gross in booking currency, or ``None`` when not evidenced."""
    documented = _number(tx.get('gross_income'))
    currency = tx.get('currency') or 'EUR'
    if documented is None or (tx.get('gross_currency') or currency) != currency:
        return None
    return documented


def dividend_amounts(tx):
    """Return ``(net, gross)`` of one income booking in booking currency."""
    amount = _number(tx.get('amount'))
    if amount is None:
        return Decimal(), Decimal()
    fees = abs(_number(tx.get('fees')) or Decimal())
    taxes = abs(_number(tx.get('taxes')) or Decimal())
    documented = gross_income_amount(tx)
    if tx.get('income_basis') == 'gross':
        # The booked amount itself is the gross credit; embedded components
        # are deductions from it (separately booked ones stay separate rows
        # and are flagged through ``dividends_net_complete``).
        return amount - fees - taxes, documented if documented is not None else amount
    return amount, documented if documented is not None else amount + fees + taxes
