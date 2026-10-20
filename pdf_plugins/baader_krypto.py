"""Baader Bank / finanzen.net zero: Abrechnung über den Kauf von Kryptowerten; user plugin.

Die PDFs haben teils keine Textebene und werden dann per OCR gelesen. Stückzahl und Kurs
stehen deshalb doppelt im Beleg (Kopf und "Details zur Ausführung") und werden gegeneinander
sowie gegen den Kurswert geprüft; bei Abweichung wird nichts importiert.
"""
import base64
import re
from decimal import Decimal

from portfolio_v5.models import BankDocument, FeeItem, Kind, SecurityInfo, Transaction, digest, parse_date
from portfolio_v5.pdf_plugins import Detection

BUY_KIND = Kind.BUY
BUY_AMOUNT_SIGN = -1         # ANNAHME: Kauf = Mittelabfluss, Betrag negativ

DATE = r'\d{2}\.\d{2}\.\d{4}'
AMOUNT = r'[0-9]{1,3}(?:\.[0-9]{3})*,\d{2}|\d+,\d{2}'
NUMBER = r'\d[\d.]*,\d+'

TITLE = re.compile(r'Abrechnung\s+über\s+den\s+Kauf\s+von\s+Kryptowerten')
SETTLEMENT = re.compile(
    r'Zu\s+Lasten\s+Konto\s+(?P<account>\d+)\s+Valuta:\s*(?P<valuta>' + DATE + r')\s+(?P<currency>[A-Z]{3})\s+(?P<amount>' + AMOUNT + ')')
MARKET_VALUE = re.compile(r'Kurswert\s+(?P<currency>[A-Z]{3})\s+(?P<amount>' + AMOUNT + ')')
HEADER_ROW = re.compile(
    r'(?m)^[ \t]*STK[ \t]+(?P<qty>' + NUMBER + r')[ \t]+(?P<name>[^\d\n][^\n]*?)[ \t]+(?P<currency>[A-Z]{3})[ \t]+(?P<price>' + NUMBER + r')[ \t]*$')
DETAIL_ROW = re.compile(
    r'(?m)^[ \t]*STK[ \t]+(?P<qty>' + NUMBER + r')[ \t]+(?P<currency>[A-Z]{3})[ \t]+(?P<price>' + NUMBER + r')[ \t]+'
    r'(?P<venue>\S[^\n]*?)[ \t]+(?P<date>' + DATE + r')[ \t]+(?P<time>[\d:]+)[ \t]*$')
CODE = re.compile(r'Kennung:\s*(?P<code>[A-Z0-9]{2,10})')
REFERENCE = re.compile(r'referenz:\s*(?P<ref>[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12})')
ORDER_NO = re.compile(r'Vorgangs-Nr\.:\s*(?P<no>[A-Z]+\s*\d+)')
CUSTOMER_NO = re.compile(r'Stammnr\.:\s*(?P<no>\d+)')
LETTER_DATE = re.compile(r'(?m)^[ \t]*(' + DATE + r')[ \t]*$')
CUSTODIAN = re.compile(r'Kryptoverwahrer,\s+der\s+(?P<c>[A-Z][\w ]*?GmbH)')
ORDER_DATE = re.compile(r'Auftragsdatum\s+(?P<date>' + DATE + ')')


def decimal(value):
    """Deutsche Zahl -> Decimal (Punkt = Tausender, Komma = Dezimal)."""
    return Decimal(value.replace('.', '').replace(',', '.'))


def plain(value):
    """Dezimalstring ohne Exponentschreibweise (kleine Krypto-Stückzahlen)."""
    return format(value, 'f')


class BaaderKryptoPlugin:
    plugin_id = 'user.baader-krypto'
    bank_name = 'Baader Bank (finanzen.net zero Krypto)'
    version = '1.0'
    document_types = 'Abrechnung Kauf von Kryptowerten'

    def detect(self, document):
        text = document.text
        if TITLE.search(text) and SETTLEMENT.search(text):
            return [Detection(1.0, 'Baader Kryptoabrechnung Kauf', 'kauf',
                              'Abrechnung über den Kauf von Kryptowerten und Belastungskonto erkannt')]
        return []

    def parse(self, document, detection, context):
        if detection.handler_id != 'kauf':
            raise ValueError('Nicht unterstützter Dokumenttyp: ' + detection.handler_id)
        batch = context.batch
        located = [(page, m) for page in document.pages for m in SETTLEMENT.finditer(page.text)]
        if len(located) != 1:
            raise ValueError('Genau eine Abrechnung pro PDF erwartet, gefunden: %d.' % len(located))
        page, settle = located[0]
        text = document.text

        header, detail = HEADER_ROW.search(text), DETAIL_ROW.search(text)
        code, market, reference = CODE.search(text), MARKET_VALUE.search(text), REFERENCE.search(text)
        if not (header and detail and code and market and reference):
            raise ValueError('Stückzahl, Kurs, Kennung, Kurswert oder Ausführungsreferenz nicht erkannt.')

        # Gegenprüfungen: Kopf gegen Details, Kurs x Stückzahl gegen Kurswert
        qty, price = decimal(header.group('qty')), decimal(header.group('price'))
        if qty != decimal(detail.group('qty')) or price != decimal(detail.group('price')):
            raise ValueError('Stückzahl oder Kurs im Beleg und in den Ausführungsdetails weichen ab '
                             '(Lesefehler?); Import abgebrochen.')
        if 'EUR' not in (header.group('currency'), detail.group('currency')) or \
                market.group('currency') != 'EUR' or settle.group('currency') != 'EUR':
            raise ValueError('Nur Abrechnungen in EUR werden unterstützt.')
        market_value, total = decimal(market.group('amount')), decimal(settle.group('amount'))
        if abs(qty * price - market_value) > Decimal('0.01'):
            raise ValueError(f'Stückzahl x Kurs ({qty * price:.4f}) passt nicht zum Kurswert {market_value}; '
                             'Import abgebrochen.')
        fees = total - market_value
        if fees < 0:
            raise ValueError('Belastung ist kleiner als der Kurswert; Import abgebrochen.')

        account = 'Konto ' + settle.group('account')
        executed = parse_date(detail.group('date'))
        if not executed or not parse_date(settle.group('valuta')):
            raise ValueError('Ausführungs- oder Valutadatum ungültig.')
        customer = CUSTOMER_NO.search(text)
        if customer and not settle.group('account').startswith(customer.group('no')):
            batch.warnings.append('Belastungskonto passt nicht zur Stammnummer; bitte Zuordnung prüfen.')
        order_date = ORDER_DATE.search(text)
        if order_date and parse_date(order_date.group('date')) != executed:
            batch.warnings.append('Auftrags- und Ausführungsdatum weichen ab; Ausführungsdatum wurde verwendet.')

        amount = BUY_AMOUNT_SIGN * total
        row = page.text[:settle.start()].count('\n') + 1
        source_line = ' '.join(settle.group().split())
        order = ORDER_NO.search(text)
        custodian = CUSTODIAN.search(text)
        sources = {name: 'ocr' for name in ('quantity', 'price', 'amount')} if page.used_ocr else {}
        executed_at = f"{executed}T{':'.join(detail.group('time').split(':')[:3])}"
        batch.transactions.append(Transaction(
            account=account,
            external_id='pdf-crypto-' + digest([account, reference.group('ref').lower(), plain(qty), plain(price)]),
            date=executed, kind=BUY_KIND, amount=f'{amount:.2f}', currency='EUR',
            security=code.group('code'), quantity=plain(qty),
            fees=f'{fees:.2f}', row=row,
            gross_amount=f'{market_value:.2f}', price=plain(price), price_currency='EUR',
            fee_items=[FeeItem('entgelt', f'{fees:.2f}')],
            trade_date=executed, executed_at=executed_at, pay_date=parse_date(settle.group('valuta')),
            cash_account=account, security_ref=code.group('code'),
            order_id=' '.join(order.group('no').split()) if order else '', execution_ref=reference.group('ref').lower(),
            venue=' '.join(detail.group('venue').split()), document_reference=' '.join(order.group('no').split()) if order else '',
            field_sources=sources))
        batch.securities.append(SecurityInfo(
            key=code.group('code'), identifier_type='ticker', symbol=code.group('code'),
            name=' '.join(header.group('name').split()), asset_class='Krypto', quote_currency='EUR',
            custody_type='Wallet', custodian=' '.join(custodian.group('c').split()) if custodian else ''))
        batch.pdf_booking_evidence.append({
            'page': page.number, 'line': row, 'text': source_line,
            'ocr': page.used_ocr, 'confidence': page.confidence, 'review_required': page.used_ocr})

        letter_date = LETTER_DATE.search(text)
        batch.documents.append(BankDocument(
            account, batch.file_hash + ':' + account, document.path.name,
            parse_date(letter_date.group(1)) if letter_date else executed,
            base64.b64encode(document.content).decode('ascii')))

        batch.warnings.append(
            f"Kauf {code.group('code')} ({' '.join(header.group('name').split())}), "
            f"{'Vorgang ' + ' '.join(order.group('no').split()) + ', ' if order else ''}"
            f"Valuta {parse_date(settle.group('valuta'))}, Ausführungsplatz {' '.join(detail.group('venue').split())}. "
            'Kryptowerte haben keine ISIN; als Kennung wird das Kürzel verwendet. '
            'Die Belastung des Kontos wurde nicht als eigene Kontobuchung erzeugt.')
        if page.used_ocr:
            batch.warnings.append('Seite per OCR gelesen; Stückzahl, Kurs und Betrag wurden gegeneinander '
                                  'geprüft, bitte dennoch am Original kontrollieren.')
        return batch


plugin = BaaderKryptoPlugin()
