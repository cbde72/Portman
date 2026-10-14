"""pbb direkt (Deutsche Pfandbriefbank): Kontoauszug und Steueroptimierung zum Jahresende; user plugin.

Kontoauszüge werden nur erkannt, wenn sie "keine Umsätze" ausweisen. Das Tabellenformat mit
Buchungen ist hier nicht bekannt; solche Auszüge überlässt das Plugin bewusst dem generischen Parser.
"""
import base64
import re
from decimal import Decimal

from portfolio_v5.models import (AccountInfo, AccountStatement, BankDocument, BankTransaction, Kind,
                                 TaxEvent, digest, money, parse_date)
from portfolio_v5.pdf_plugins import Detection

DATE = r'\d{2}\.\d{2}\.\d{4}'
AMOUNT = r'[0-9]{1,3}(?:\.[0-9]{3})*,\d{2}|\d+,\d{2}'

BANK = re.compile(r'pbb\s*direkt|Pfandbriefbank')
LETTER_DATE = re.compile(r'Garching,\s*(?P<date>' + DATE + ')')
BIC_FOOTER = re.compile(r'BIC\s+(?P<bic>[A-Z]{6}[A-Z0-9]{2}(?:[A-Z0-9]{3})?)')
BLZ = re.compile(r'BLZ\s*(?P<a>\d{3})\s*(?P<b>\d{3})\s*(?P<c>\d{2})')

TAX_TITLE = re.compile(r'Steueroptimierung\s+zum\s+Jahresende\s+(?P<year>\d{4})')
TAX_TOTAL = re.compile(r'in\s+Höhe\s+von\s+(?P<amount>' + AMOUNT + r')\s+EUR')
TAX_LINES = {label: re.compile(label + r'\s+(?P<amount>' + AMOUNT + r')\s+EUR')
             for label in ('Kapitalertragsteuer', 'Solidaritätszuschlag', 'Kirchensteuer')}
TAX_ACCOUNT = re.compile(r'Verrechnung\s+erfolgt\s+über\s+Konto\s+(?P<no>\d+)')
TAX_TRANSACTION = re.compile(r'Transaktions-Nr\.\s*(?P<no>\d+)')

STATEMENT_NO = re.compile(r'Kontoauszug\s+Nr:\s*(?P<no>\S+)')
STATEMENT_ACCOUNT = re.compile(r'Kontonummer\s*:\s*(?P<no>\d+)(?:\s+dazugehörige\s+IBAN:\s*(?P<iban>DE(?:\s?\d){20}))?')
STATEMENT_TYPE = re.compile(r'Kontenart\s*:\s*(?P<type>\S[^\n]*?)\s*(?:\n|$)')
OPENING = re.compile(r'Alter\s+Saldo\s+vom\s+(?P<date>' + DATE + r')\s+in\s+EUR\s+(?P<value>' + AMOUNT + r')(?P<sign>[+-])')
CLOSING = re.compile(r'Neuer\s+Saldo\s+(?P<date>' + DATE + r')\s+Nr\.\s*\S+\s+Währung\s+EUR\s+(?P<value>' + AMOUNT + r')(?P<sign>[+-])')
TABLE_BODY = re.compile(r'Buchungstext(?P<body>.*?)Neuer\s+Saldo', re.S)


def derived_iban(blz, account):
    """Deutsche IBAN aus BLZ und Kontonummer (Prüfziffer nach ISO 13616)."""
    bban = blz + account.zfill(10)
    return f'DE{98 - int(bban + "131400") % 97:02d}{bban}'


def valid_iban(iban):
    digits = ''.join(str(ord(c) - 55) if c.isalpha() else c for c in iban[4:] + iban[:4])
    return int(digits) % 97 == 1


def has_no_bookings(text):
    table = TABLE_BODY.search(text)
    if not table:
        return False
    body = re.sub(r'\b(?:Betrag|datum|in\s+EUR)\b', ' ', table.group('body'))
    return ' '.join(body.split()) == 'keine Umsätze'


def signed(value, sign):
    return Decimal(money(value)) * (-1 if sign == '-' else 1)


class PbbDirektPlugin:
    plugin_id = 'user.pbb-direkt'
    bank_name = 'pbb direkt'
    version = '1.0'
    document_types = 'Kontoauszug (ohne Umsätze), Steueroptimierung zum Jahresende'

    def detect(self, document):
        text = document.text
        if not BANK.search(text):
            return []
        result = []
        if TAX_TITLE.search(text) and re.search(r'Erstattung', text) and TAX_TOTAL.search(text):
            result.append(Detection(0.95, 'pbb direkt Steueroptimierung (Erstattung)', 'steueroptimierung',
                                    'pbb direkt, Steueroptimierung zum Jahresende und Erstattungsbetrag erkannt'))
        if (STATEMENT_NO.search(text) and OPENING.search(text) and CLOSING.search(text)
                and has_no_bookings(text)):
            result.append(Detection(0.95, 'pbb direkt Kontoauszug (keine Umsätze)', 'kontoauszug',
                                    'pbb direkt, Kontoauszug mit Alt-/Neusaldo und "keine Umsätze" erkannt'))
        return result

    def parse(self, document, detection, context):
        if detection.handler_id == 'steueroptimierung':
            return self._tax_refund(document, context.batch)
        if detection.handler_id == 'kontoauszug':
            return self._statement(document, context.batch)
        raise ValueError('Nicht unterstützter Dokumenttyp: ' + detection.handler_id)

    # ----------------------------------------------------------------- Konto
    def _account(self, text, number, iban=None):
        """IBAN-Konto; fehlt die IBAN im Beleg, wird sie aus BLZ und Kontonummer abgeleitet."""
        if iban:
            name = re.sub(r'\s+', '', iban)
            if not valid_iban(name):
                raise ValueError('IBAN im Beleg ist ungültig (Prüfziffer): ' + name)
            return 'IBAN ' + name, None
        blz = BLZ.search(text)
        if blz:
            name = derived_iban(blz.group('a') + blz.group('b') + blz.group('c'), number)
            return 'IBAN ' + name, f'IBAN {name} aus BLZ und Kontonummer {number} abgeleitet; bitte Zuordnung prüfen.'
        return 'Konto ' + number, None

    def _document(self, batch, document, account, date):
        batch.documents.append(BankDocument(
            account, batch.file_hash + ':' + account, document.path.name, date,
            base64.b64encode(document.content).decode('ascii')))

    # ------------------------------------------------------- Steueroptimierung
    def _tax_refund(self, document, batch):
        text = document.text
        located = [(page, m) for page in document.pages for m in TAX_TOTAL.finditer(page.text)]
        if len(located) != 1:
            raise ValueError('Genau ein Erstattungsbetrag erwartet, gefunden: %d.' % len(located))
        page, total = located[0]
        parts = {}
        for label, pattern in TAX_LINES.items():
            found = pattern.search(text)
            if not found:
                raise ValueError(f'Position "{label}" im Beleg nicht erkannt.')
            parts[label] = Decimal(money(found.group('amount')))
        refund = Decimal(money(total.group('amount')))
        if sum(parts.values()) != refund:
            raise ValueError(f'Summe der Steuerpositionen ({sum(parts.values())}) passt nicht zum '
                             f'Erstattungsbetrag {refund}; Import abgebrochen.')
        if refund <= 0:
            raise ValueError('Erstattungsbetrag ist nicht positiv.')

        number = TAX_ACCOUNT.search(text) or re.search(r'Kontonummer\s*:\s*(?P<no>\d+)', text)
        dated = LETTER_DATE.search(text)
        if not (number and dated):
            raise ValueError('Verrechnungskonto oder Belegdatum nicht erkannt.')
        account, note = self._account(text, number.group('no'))
        booked = parse_date(dated.group('date'))
        transaction = TAX_TRANSACTION.search(text)
        year = TAX_TITLE.search(text).group('year')
        purpose = (f'Steueroptimierung zum Jahresende {year}: Erstattung '
                   + ', '.join(f"{label} {value:.2f} EUR".replace('.', ',') for label, value in parts.items())
                   + (f" (Transaktions-Nr. {transaction.group('no')})" if transaction else ''))

        row = page.text[:total.start()].count('\n') + 1
        source_line = ' '.join(total.group().split())
        external_id = 'pdf-pbb-' + digest([account, 'steueroptimierung', booked, f'{refund:.2f}',
                                           transaction.group('no') if transaction else ''])
        batch.transactions.append(BankTransaction(
            account=account, external_id=external_id,
            date=booked, kind=Kind.BANK_BOOKING, amount=f'{refund:.2f}', currency='EUR',
            row=row, purpose=purpose, booking_text=f'Steueroptimierung zum Jahresende {year}',
            bank_reference=transaction.group('no') if transaction else '',
            document_reference=transaction.group('no') if transaction else '',
            raw_text=source_line))
        batch.pdf_booking_evidence.append({
            'page': page.number, 'line': row, 'text': source_line,
            'ocr': page.used_ocr, 'confidence': page.confidence, 'review_required': page.used_ocr})
        batch.tax_events.append(TaxEvent(
            external_id='pdf-pbb-tax-' + digest([account, booked, f'{refund:.2f}']), account=account,
            type='steueroptimierung', date=booked, tax_year=year, currency='EUR',
            refund_kapst=f"{parts['Kapitalertragsteuer']:.2f}", refund_solz=f"{parts['Solidaritätszuschlag']:.2f}",
            refund_kist=f"{parts['Kirchensteuer']:.2f}", reference_no=transaction.group('no') if transaction else '',
            related_transaction_id=external_id))
        self._document(batch, document, account, booked)
        if note:
            batch.warnings.append(note)
        batch.warnings.append('Buchungsdatum ist das Belegdatum; die Wertstellung steht im Kontoauszug des Kontos. '
                              'Wird dieser ebenfalls importiert, kann die Erstattung doppelt erscheinen.')
        if page.used_ocr:
            batch.warnings.append('Seite per OCR gelesen; Beträge bitte am Original prüfen.')
        return batch

    # --------------------------------------------------------------- Kontoauszug
    def _statement(self, document, batch):
        text = document.text
        account_match, opening, closing = STATEMENT_ACCOUNT.search(text), OPENING.search(text), CLOSING.search(text)
        if not (account_match and opening and closing):
            raise ValueError('Kontonummer oder Alt-/Neusaldo nicht erkannt.')
        if not has_no_bookings(text):
            raise ValueError('Kontoauszug enthält Buchungen; dieses Tabellenformat wird nicht unterstützt.')
        if not re.search(r'Kontowährung\s*:\s*EUR', text):
            raise ValueError('Nur Konten in EUR werden unterstützt.')
        old, new = signed(opening.group('value'), opening.group('sign')), signed(closing.group('value'), closing.group('sign'))
        if old != new:
            raise ValueError(f'Kontoauszug weist keine Umsätze aus, aber der Saldo ändert sich ({old} → {new}); '
                             'Import abgebrochen.')
        account, note = self._account(text, account_match.group('no'), account_match.group('iban'))
        dated = LETTER_DATE.search(text)
        end = parse_date(closing.group('date'))
        self._document(batch, document, account, parse_date(dated.group('date')) if dated else end)
        kind = STATEMENT_TYPE.search(text)
        number_no = account_match.group('no')
        statement_no = STATEMENT_NO.search(text)
        batch.statements.append(AccountStatement(
            account=account, statement_no=statement_no.group('no'), period_start=parse_date(opening.group('date')),
            period_end=end, opening_balance=f'{old:.2f}', opening_date=parse_date(opening.group('date')),
            closing_balance=f'{new:.2f}', closing_date=end, currency='EUR',
            external_id='pdf-pbb-statement-' + digest([account, statement_no.group('no'), end])))
        type_text = kind.group('type') if kind else ''
        bic, blz = BIC_FOOTER.search(text), BLZ.search(text)
        batch.accounts.append(AccountInfo(
            key=account, account_type='Festgeld' if 'Festgeld' in type_text else ('Tagesgeld' if 'Tagesgeld' in type_text else type_text),
            bank_name='pbb direkt', iban=account[5:] if account.startswith('IBAN ') else '',
            bic=bic.group('bic') if bic else '', account_no=number_no,
            bank_code=''.join(blz.group(g) for g in 'abc') if blz else ''))
        batch.warnings.append(
            f"Kontoauszug {STATEMENT_NO.search(text).group('no')} ({kind.group('type') if kind else 'Konto'}): "
            f"keine Umsätze vom {parse_date(opening.group('date'))} bis {end}; Saldo {new:.2f} EUR unverändert geprüft.")
        if note:
            batch.warnings.append(note)
        return batch


plugin = PbbDirektPlugin()
