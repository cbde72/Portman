"""Bank of Scotland (Lloyds Bank GmbH) Kontoauszug, z. B. Tagesgeld und Festgeld; user plugin."""
import base64
import re
from decimal import Decimal

from portfolio_v5.models import (AccountInfo, AccountStatement, BankDocument, BankTransaction, Kind,
                                 digest, money, parse_date)
from portfolio_v5.pdf_plugins import Detection
from portfolio_v5.booking_details import classify_cash_booking, enrich_details

DATE = r'\d{2}\.\d{2}\.\d{4}'
AMOUNT = r'[0-9]{1,3}(?:\.[0-9]{3})*,\d{2}|\d+,\d{2}'

HEADER = re.compile(r'^[ \t]*Buchungstag[ \t]+Wertstellung[ \t]+Beschreibung[ \t]+(?P<debit>Soll|Belastungen)[ \t]+(?P<credit>Haben|Gutschriften)[ \t]*$', re.M)
ROW = re.compile(r'^[ \t]*(?P<date>' + DATE + r')[ \t]+(?P<value>' + DATE + r')(?P<rest>.*)$')
ROW_AMOUNT = re.compile(r'^(?P<body>.*?)[ \t]+(?P<amount>' + AMOUNT + r')[ \t]*$')
TOTALS = re.compile(r'Gesamtsummen?\s+in\s+Euro:\s*(?P<a>' + AMOUNT + r')(?:[ \t]+(?P<b>' + AMOUNT + r'))?')
OLD_BALANCE = re.compile(r'Alter\s+Saldo:\s*(?P<v>-?(?:' + AMOUNT + r'))')
NEW_BALANCE = re.compile(r'Neuer\s+Saldo:\s*(?P<v>-?(?:' + AMOUNT + r'))')
STATEMENT_DATE = re.compile(r'Datum:\s*(?P<date>' + DATE + ')')
STATEMENT_NO = re.compile(r'Auszugsnummer:\s*(?P<no>\S+)')
IBAN_HEADER = re.compile(r'IBAN:\s*(?P<iban>DE(?:[ \t]*\d){20})')
ACCOUNT_NO = re.compile(r'Kontonummer:\s*(?P<no>\d+)')
BIC_HEADER = re.compile(r'BIC:\s*(?P<bic>[A-Z]{6}[A-Z0-9]{2}(?:[A-Z0-9]{3})?)')
BANK_CODE = re.compile(r'Bankleitzahl:\s*(?P<a>\d{3})\s*(?P<b>\d{3})\s*(?P<c>\d{2})')
IBAN_TOKEN = re.compile(r'^[A-Z]{2}\d{2}[A-Z0-9]{11,30}$')
BIC_TOKEN = re.compile(r'^[A-Z]{4}[A-Z]{2}[A-Z0-9]{2}(?:[A-Z0-9]{3})?$')


class BankOfScotlandPlugin:
    plugin_id = 'user.bank-of-scotland-kontoauszug'
    bank_name = 'Bank of Scotland'
    version = '1.0'
    document_types = 'Kontoauszug (Tagesgeld, Festgeld)'

    def detect(self, document):
        text = document.text
        # Nicht auf "KONTOAUSZUG" oder die Absenderzeile stützen: pypdf lässt sie im Layout-Modus teils weg.
        if (re.search(r'Bank of Scotland|Lloyds Bank GmbH', text) and HEADER.search(text)
                and re.search(r'RECHNUNGSABSCHLUSS', text)):
            return [Detection(0.95, 'Bank of Scotland Kontoauszug', 'kontoauszug',
                              'Bank of Scotland, Kontoauszug und Buchungstabelle erkannt')]
        return []

    def parse(self, document, detection, context):
        if detection.handler_id != 'kontoauszug':
            raise ValueError('Nicht unterstützter Dokumenttyp: ' + detection.handler_id)
        batch = context.batch
        text = document.text

        iban, number = IBAN_HEADER.search(text), ACCOUNT_NO.search(text)
        if iban:
            account = 'IBAN ' + re.sub(r'\s+', '', iban.group('iban'))
        elif number:
            account = 'Konto ' + number.group('no')
        else:
            raise ValueError('Weder IBAN noch Kontonummer im Auszugskopf erkannt.')
        old, new = OLD_BALANCE.search(text), NEW_BALANCE.search(text)
        statement_date = STATEMENT_DATE.search(text)
        if not (old and new and statement_date):
            raise ValueError('Alter/Neuer Saldo oder Auszugsdatum nicht erkannt.')

        bookings, totals = [], None
        for page in document.pages:
            header = HEADER.search(page.text)
            if not header:
                if any(ROW.match(line) for line in page.text.splitlines()):
                    raise ValueError(f'Seite {page.number}: Buchungszeilen ohne Tabellenkopf; Import abgebrochen.')
                continue
            lines = page.text.splitlines()
            header_line = page.text[:header.start()].count('\n')
            end_line = next((i for i in range(header_line + 1, len(lines))
                             if re.search(r'Gesamtsummen?\s+in\s+Euro', lines[i])), len(lines))
            bookings.extend(self._read_table(page, lines, header_line + 1, end_line))
            found = TOTALS.search(page.text)
            if found:
                totals = found

        if not bookings:
            raise ValueError('Keine Buchungen in der Buchungstabelle erkannt.')

        # Soll/Haben: Spaltentrennung über die größte Lücke der rechten Betragskanten je Seite.
        # Nicht eindeutig (z. B. nur eine Spalte belegt) -> der Saldenabgleich entscheidet.
        for number in {b['page'] for b in bookings}:
            rows = [b for b in bookings if b['page'] == number]
            ends = sorted({b['end'] for b in rows})
            gaps = [(ends[i + 1] - ends[i], ends[i]) for i in range(len(ends) - 1)]
            cut = max(gaps)[1] if gaps and max(gaps)[0] >= 15 else None
            for b in rows:
                b['credit'] = None if cut is None else b['end'] > cut
        opening, closing = Decimal(money(old.group('v'))), Decimal(money(new.group('v')))
        known_credit = sum((Decimal(b['amount']) for b in bookings if b['credit'] is True), Decimal(0))
        known_debit = sum((Decimal(b['amount']) for b in bookings if b['credit'] is False), Decimal(0))
        open_rows = [b for b in bookings if b['credit'] is None]
        if open_rows:
            rest = sum((Decimal(b['amount']) for b in open_rows), Decimal(0))
            as_credit = opening + known_credit + rest - known_debit == closing
            as_debit = opening + known_credit - known_debit - rest == closing
            if as_credit == as_debit:
                raise ValueError('Soll/Haben nicht eindeutig bestimmbar; Import abgebrochen.')
            for b in open_rows:
                b['credit'] = as_credit

        # Prüfungen: Saldenabgleich und Summenzeile
        debit = sum((Decimal(b['amount']) for b in bookings if not b['credit']), Decimal(0))
        credit = sum((Decimal(b['amount']) for b in bookings if b['credit']), Decimal(0))
        if opening + credit - debit != closing:
            raise ValueError(f'Saldenprüfung fehlgeschlagen: {opening} + {credit} - {debit} ergibt nicht '
                             f'{closing}; Import abgebrochen.')
        if totals:
            printed = sorted(Decimal(money(totals.group(g))) for g in ('a', 'b') if totals.group(g))
            if printed != sorted(x for x in (debit, credit) if x != 0):
                raise ValueError(f'Spaltensummen (Soll {debit}, Haben {credit}) weichen von der Summenzeile '
                                 'des Auszugs ab; Import abgebrochen.')
        else:
            batch.warnings.append('Summenzeile nicht gefunden; nur Saldenabgleich geprüft.')

        occurrences = {}
        for b in bookings:
            amount = b['amount'] if b['credit'] else '-' + b['amount']
            tokens = b['description'].split()
            iban_at = next((i for i, t in enumerate(tokens) if IBAN_TOKEN.match(t)), None)
            counterparty_iban = tokens[iban_at] if iban_at is not None else ''
            bic_at = iban_at + 1 if iban_at is not None and iban_at + 1 < len(tokens) \
                and BIC_TOKEN.match(tokens[iban_at + 1]) else None
            counterparty_bic = tokens[bic_at] if bic_at is not None else ''
            booking_text = ' '.join(t for i, t in enumerate(tokens) if i not in (iban_at, bic_at))
            booked, value_date = parse_date(b['date']), parse_date(b['value'])
            identity = digest([account, booked, value_date, amount, 'EUR', b['description']])
            occurrences[identity] = occurrences.get(identity, 0) + 1
            transaction = BankTransaction(
                account=account, external_id=f'pdf-bos-{identity}-{occurrences[identity]}',
                date=booked, kind=Kind.BANK_BOOKING, amount=amount, currency='EUR', row=b['line'],
                value_date=value_date, purpose=b['description'], booking_text=booking_text,
                counterparty_iban=counterparty_iban, counterparty_bic=counterparty_bic,
                raw_text=b['raw'])
            enrich_details(transaction)
            classify_cash_booking(transaction)
            batch.transactions.append(transaction)
            batch.pdf_booking_evidence.append({
                'page': b['page'], 'line': b['line'], 'text': b['raw'],
                'ocr': b['ocr'], 'confidence': b['confidence'], 'review_required': b['ocr']})

        statement_end = parse_date(statement_date.group('date'))
        statement_no = STATEMENT_NO.search(text)
        batch.statements.append(AccountStatement(
            account=account, statement_no=statement_no.group('no') if statement_no else '',
            period_end=statement_end, opening_balance=f'{opening:.2f}', closing_balance=f'{closing:.2f}',
            closing_date=statement_end, currency='EUR',
            external_id='pdf-bos-statement-' + digest([account, statement_no.group('no') if statement_no else '', statement_end])))
        bic, bank_code = BIC_HEADER.search(text), BANK_CODE.search(text)
        batch.accounts.append(AccountInfo(
            key=account, account_type='Tagesgeld' if re.search(r'\bTagesgeld\b', text) else '',
            bank_name='Bank of Scotland', iban=account[5:] if account.startswith('IBAN ') else '',
            bic=bic.group('bic') if bic else '', account_no=ACCOUNT_NO.search(text).group('no') if ACCOUNT_NO.search(text) else '',
            bank_code=''.join(bank_code.group(g) for g in 'abc') if bank_code else ''))
        batch.documents.append(BankDocument(
            account, batch.file_hash + ':' + account, document.path.name,
            parse_date(statement_date.group('date')),
            base64.b64encode(document.content).decode('ascii')))
        if any(p.used_ocr for p in document.pages):
            batch.warnings.append('Seite per OCR gelesen; Buchungen bitte am Original prüfen.')
        batch.warnings.append(
            f"Auszug {STATEMENT_NO.search(text).group('no') if STATEMENT_NO.search(text) else '?'}: "
            f"Saldo {money(old.group('v'))} → {money(new.group('v'))} EUR geprüft.")
        return batch

    # ------------------------------------------------------------------ Tabelle
    def _read_table(self, page, lines, start, end):
        """Buchungen mit ihren Beschreibungszeilen. Mehrzeilige Beschreibungen stehen
        um die Datumszeile herum; zwischen zwei direkt aufeinanderfolgenden Buchungen
        wird die Zeilengruppe in der Mitte geteilt."""
        items = []
        for number in range(start, end):
            line = lines[number]
            if not line.strip():
                items.append(('blank', number, None))
            elif ROW.match(line):
                items.append(('row', number, ROW.match(line)))
            else:
                items.append(('text', number, ' '.join(line.split())))

        rows = {i: dict(before=[], after=[]) for i, it in enumerate(items) if it[0] == 'row'}
        i = 0
        while i < len(items):
            if items[i][0] != 'text':
                i += 1
                continue
            j = i
            while j < len(items) and items[j][0] == 'text':
                j += 1
            run = [items[k][2] for k in range(i, j)]
            prev_row = i - 1 in rows
            next_row = j in rows
            if prev_row and next_row:
                half = len(run) // 2
                rows[i - 1]['after'] += run[:half]
                rows[j]['before'] += run[half:]
            elif prev_row:
                rows[i - 1]['after'] += run
            elif next_row:
                rows[j]['before'] += run
            else:
                raise ValueError(f"Seite {page.number}: Text ohne zugehörige Buchung: {' '.join(run)}")
            i = j

        result = []
        for index, (kind, number, match) in enumerate(items):
            if kind != 'row':
                continue
            tail = ROW_AMOUNT.match(match.group('rest'))
            if not tail:
                raise ValueError(f"Seite {page.number}, Zeile {number + 1}: kein Betrag in der Buchungszeile.")
            amount_end = len(lines[number].rstrip())
            description = ' '.join(rows[index]['before'] + [' '.join(tail.group('body').split())] + rows[index]['after'])
            if not description:
                raise ValueError(f"Seite {page.number}, Zeile {number + 1}: Buchungstext fehlt.")
            result.append(dict(
                date=match.group('date'), value=match.group('value'), description=description,
                amount=money(tail.group('amount')), end=amount_end, credit=None,
                page=page.number, line=number + 1, raw=' '.join(lines[number].split()),
                ocr=page.used_ocr, confidence=page.confidence))
        return result


plugin = BankOfScotlandPlugin()
