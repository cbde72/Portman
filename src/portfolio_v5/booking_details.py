"""Preserve full bank text and extract only identifiable labelled details."""
import re

from .models import TaxItem

DETAIL_FIELDS = ('purpose', 'counterparty', 'bank_reference', 'operation', 'booking_text',
                 'counterparty_iban', 'counterparty_bic', 'raw_text')

REFERENCE_LABEL = re.compile(
    r'(?:End-to-End-(?:Ref(?:erenz)?\.?)|Buchungsreferenz|Kundenreferenz|Mandatsreferenz|'
    r'Vorgangs(?:nummer|-Nr\.)|Transaktions(?:nummer|-Nr\.)|Referenz(?:-Nr\.)?)'
    # Do not interpret ordinary fields such as "Referenzkonto" or
    # "Referenzwert" as transaction references.
    r'(?=\s|:|$)\s*:?[ \t]*(?P<value>[^\r\n]+)', re.I)
REFERENCE_PLACEHOLDERS = {'nonref', 'notprovided', 'nicht angegeben', 'keine', '-'}


def extract_bank_reference(value):
    """Return a labelled bank/transaction reference without consuming the next line."""
    for match in REFERENCE_LABEL.finditer(value or ''):
        reference = ' '.join(match.group('value').split()).strip(' ·;|')
        # Flattened exports sometimes place the next labelled field on the same
        # physical line. Stop there while retaining spaces inside the reference.
        reference = re.split(
            r'\s+(?=(?:IBAN|BIC|Verwendungszweck|Auftraggeber|Empfänger|Betrag|Valuta)\s*:)',
            reference, maxsplit=1, flags=re.I)[0].strip()
        if reference and reference.casefold() not in REFERENCE_PLACEHOLDERS:
            return reference
    return ''


def full_booking_text(tx):
    from pathlib import Path
    sources = tx.get('booking_sources')
    if not sources: return tx.get('raw_text') or tx.get('purpose', '')
    return '\n\n'.join('Quelle: ' + Path(source['source']).name + '\n' +
                        (source.get('raw_text') or source.get('purpose', '')) for source in sources)


def readable_purpose(tx):
    """Build a labelled, lossless purpose from fields identified by an importer."""
    if tx.field_sources.get('gross_income') == 'comdirect Finanzreport · Abschluss Zinsen':
        return tx.purpose
    original = ' '.join((tx.purpose or '').split())
    booking = ' '.join((tx.booking_text or original).split())
    operation = ' '.join((tx.operation or '').split())
    if operation and booking.casefold().startswith(operation.casefold()):
        booking = booking[len(operation):].lstrip(' /·:-')
    auxiliary = any((tx.counterparty, tx.bank_reference, tx.counterparty_iban, tx.counterparty_bic))
    if not auxiliary and not booking:
        return original
    parts = []
    for label, value in (
        ('Vorgang', operation), ('Gegenpartei', tx.counterparty),
        ('Verwendungszweck', booking), ('Referenz', tx.bank_reference),
        ('Gegenkonto-IBAN', tx.counterparty_iban), ('Gegenkonto-BIC', tx.counterparty_bic),
    ):
        value = ' '.join((value or '').split())
        if value and value.casefold() not in {part.split(': ', 1)[-1].casefold() for part in parts}:
            parts.append(f'{label}: {value}')
    if len(parts) == 1 and parts[0].startswith('Verwendungszweck: '):
        return original
    return ' · '.join(parts) or original


def enrich_details(tx):
    text = tx.raw_text or tx.purpose
    if not tx.raw_text:
        tx.raw_text = tx.purpose
    if not tx.booking_text:
        tx.booking_text = tx.purpose
    if not tx.operation:
        operation = re.match(r'(Übertrag\s*/\s*Überweisung|Lastschrift\s*/\s*Belastung|Lastschrift Einzug|'
                             r'Auszahlung GAA|Überweisungsgutschr\.|Spar/Fest/Termingeld|Kontoabschluss|'
                             r'Kontoübertrag|Zinsgutschrift|Abschluss|Überweisung|Lastschrift|Dauerauftrag|Kupon)(?!\w)', tx.purpose)
        if operation:
            tx.operation = operation[1]
    ibans = []
    for match in re.finditer(r'\bDE(?:[ \t]*\d){20}(?!\d)', text):
        value = re.sub(r'\s', '', match[0])
        if int(value[4:] + '1314' + value[2:4]) % 97 == 1 and value not in tx.account and value not in ibans:
            ibans.append(value)
    if not tx.counterparty_iban and len(ibans) == 1:
        tx.counterparty_iban = ibans[0]
    bics = re.findall(r'\bBIC\s*:?\s*([A-Z]{6}[A-Z0-9]{2}(?:[A-Z0-9]{3})?)\b', text)
    if not bics:
        bics = re.findall(r'(?m)^\s*([A-Z]{6}[A-Z0-9]{2}(?:[A-Z0-9]{3})?)\s*$', text)
    if not tx.counterparty_bic and len(set(bics)) == 1:
        tx.counterparty_bic = bics[0]
    if not tx.bank_reference:
        tx.bank_reference = extract_bank_reference(text)
        if tx.bank_reference:
            tx.field_sources['bank_reference'] = 'Beschriftete Referenz im Originaltext'
    if not tx.transaction_reference:
        tx.transaction_reference = tx.bank_reference or tx.document_reference
    if not tx.counterparty:
        match = re.search(r'(?:Auftraggeber|Empfänger|Zahlungspflichtiger|Zahlungsempfänger)\s*:\s*([^\n]+)', text, re.I)
        if match:
            tx.counterparty = match[1].strip()
    tx.purpose = readable_purpose(tx)


def classify_cash_booking(tx):
    """Classify only explicit cash-account wording; never infer from the sign alone."""
    text = ' '.join((tx.booking_text or tx.purpose or tx.raw_text or '').split())
    amount = tx.amount or '0'
    negative = amount.startswith('-')
    if re.match(
            r'^(?:Vorgang:\s*)?(?:(?:Storno\s+)?Abschluss|Bonuszins(?:en)?|Habenzins(?:en)?|'
            r'Zins(?:en|gutschrift)?|Zinsen/Kontof.hrung)\b', text, re.I):
        tx.kind = 'INTEREST'
        return tx
    tax_patterns = (
        ('kapitalertragsteuer', r'\b(?:Kapitalertragsteuer|Kapitalertragssteuer|Abgeltungssteuer|Kap\.\s*Steuer)\b'),
        ('solidaritaetszuschlag', r'\b(?:Solid(?:arit.t)?s?\.?-?Zuschlag|Sol\.?\s*Zuschl)\b'),
        ('kirchensteuer', r'\bKirchensteuer\b'),
    )
    tax_kind = next((kind for kind, pattern in tax_patterns if re.search(pattern, text, re.I)), None)
    if tax_kind:
        tx.kind = 'TAX' if negative else 'TAX_REFUND'
        if negative:
            value = amount.lstrip('-')
            tx.taxes = value
            tx.tax_items = [TaxItem(tax_kind, value)]
        return tx
    if negative and re.match(r'^(?:Vorgang:\s*)?(?:Gebühr|Gebuehr|Entgelt)\b', text, re.I):
        tx.kind = 'FEE'
        tx.fees = amount.lstrip('-')
        return tx
    transfer = re.search(
        r'\b(?:Zahlungseingang|Überweisungs?-?Gutschrift|Ueberweisungs?-?Gutschrift|'
        r'Dauerauftrags?gutschr(?:ift)?|Internet-Euro-Überweisung|Überweisung|Ueberweisung|'
        r'Einzahlung|Auszahlung|Kontoübertrag)\b', text, re.I)
    if transfer:
        tx.kind = 'WITHDRAWAL' if negative else 'DEPOSIT'
    return tx


