"""Conservative recognition shared by every interest overview."""
import re
from decimal import Decimal, InvalidOperation


INTEREST_TEXT = re.compile(
    r'\b(?:zinsgutschrift|habenzinsen|abschluss\s+zinsen|zinsertrag|zinszahlung|guthabenzinsen?)\b',
    re.I)


def is_interest_transaction(tx):
    if tx.get('kind') == 'INTEREST':
        return True
    if tx.get('kind') != 'BANK_BOOKING':
        return False
    try:
        if Decimal(str(tx.get('amount') or 0)) <= 0:
            return False
    except (InvalidOperation, ValueError):
        return False
    text = ' '.join(str(tx.get(field) or '') for field in
                    ('operation', 'booking_text', 'purpose', 'raw_text'))
    return bool(INTEREST_TEXT.search(text))
