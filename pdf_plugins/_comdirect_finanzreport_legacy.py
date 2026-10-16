"""Legacy comdirect report: purpose first, two dates on the same booking row."""
import base64
import re
from collections import Counter
from pdf_plugins._finanzreport_help import report_date, balance_error
from decimal import Decimal
from portfolio_v5.models import Balance, BankDocument, BankTransaction, money, parse_date
from pdf_plugins._comdirect_finanzreport_core import DATE, NUM, flush_pending


def parse_legacy_finanzreport(batch, pages, content, *, bookings_only=False):
    lines = [(p, r, ' '.join(line.split())) for p, text in enumerate(pages, 1)
             for r, line in enumerate(text.splitlines(), 1) if line.strip()]
    text = '\n'.join(line for _, _, line in lines)
    day = report_date(text)
    customer = re.search(r'(?:Ihre Kontonummer:|Kontonummer) (\d+)', text)
    if not day or not customer:
        raise ValueError('Alter Finanzreport: Stichtag oder Stammkontonummer fehlt.')
    batch.document_type = 'comdirect Finanzreport'
    # Only the statement's own letterhead identifies an owner. IBANs in
    # payment purposes belong to counterparties and must not change ownership.
    header = re.split(r'Finanzreport\s+Nr\.', pages[0], maxsplit=1)[0]
    header_ibans = {}
    for raw in re.findall(r'\bIBAN\s*:\s*(DE(?:\s*\d){20})', header):
        iban = re.sub(r'\s+', '', raw)
        if int(iban[4:] + '1314' + iban[2:4]) % 97 != 1:
            raise ValueError('Alter Finanzreport: ungültige IBAN im Briefkopf.')
        header_ibans[iban[-10:]] = iban
    sections, current = [], None
    # A product name inside a payment purpose must never switch ownership.
    for i, entry in enumerate(lines):
        page, row, line = entry
        title = re.match(r'^(Girokonto|Tagesgeld PLUS(?:-Konto)?|Tagesgeldkonto|Verrechnungskonto)(?: ec .*)?$', line)
        following = [l for _, _, l in lines[i + 1:i + 3]]
        if title and any(l.startswith('Umsätze') for l in following):
            current = {'name': title[1], 'lines': []}
            sections.append(current)
            continue
        if current:
            if line.startswith(('Finanzreport ', 'Kontonummer ', 'comdirect ', 'Umsätze', 'Buchungstag ')):
                continue
            current['lines'].append(entry)
            if line.startswith('Neuer Saldo'):
                current = None
    if not sections:
        raise ValueError('Alter Finanzreport: keine Kontobereiche erkannt.')
    if not bookings_only and re.search(r'\bDepotbestand\b|^Depot [+-]?' + NUM, text, re.M):
        raise ValueError('Alter Finanzreport: Depotbestand in diesem Layout benötigt eine gesonderte Prüfung.')
    occurrences = Counter()
    sources = []
    for section in sections:
        rows = section['lines']
        section_text = '\n'.join(l for _, _, l in rows)
        identifiers = set(re.findall(r'(?:Kto|Konto) (\d{7,10}(?:/\d{2})?)\s*EUR', section_text))
        identifiers = {n.replace('/', '').zfill(10) for n in identifiers}
        if len(identifiers) > 1:
            raise ValueError('Alter Finanzreport: widersprüchliche Kontonummern im Kontobereich.')
        if identifiers:
            account_number = next(iter(identifiers))
            owner = ('IBAN ' + header_ibans[account_number] if account_number in header_ibans
                     else 'Konto ' + account_number)
        else:
            owner = 'comdirect ' + section['name'] + ' (Stammkonto ' + customer[1] + ')'
            batch.warnings.append(section['name'] + ': keine eindeutige Unterkontonummer im Original; Zielkonto manuell zuordnen oder auslassen.')
        sources.append(owner)
        opening = closing = None
        pending = None
        start_count = len(batch.transactions)
        def flush():
            nonlocal pending
            pending = flush_pending(pending, batch, occurrences)
        for page, row, line in rows:
            balance = re.fullmatch(r'(Alter|Neuer) Saldo (?:' + DATE + r' )?([+-]?' + NUM + ')', line)
            if balance:
                flush()
                if balance[1] == 'Alter': opening = Decimal(money(balance[2]))
                else: closing = Decimal(money(balance[2]))
                continue
            booking = re.fullmatch(r'(.+?) (' + DATE + ') (' + DATE + ') ([+-]' + NUM + r')(.*)', line)
            if booking:
                flush()
                booked, value_date = parse_date(booking[2]), parse_date(booking[3])
                if not booked or not value_date or booked > day:
                    raise ValueError('Alter Finanzreport: ungültiges Buchungsdatum.')
                pending = (BankTransaction(owner, '', booked, 'BANK_BOOKING', money(booking[4]), 'EUR',
                                           value_date=value_date, purpose=(booking[1] + ' ' + booking[5]).strip(), row=row,
                                           raw_text=line), page, row)
            elif pending:
                pending[0].purpose += ' ' + line
                pending[0].raw_text += '\n' + line
            elif re.search(DATE, line):
                raise ValueError('Alter Finanzreport: nicht zugeordnete datierte Zeile.')
        flush()
        total = sum((Decimal(t.amount) for t in batch.transactions[start_count:]), Decimal(0))
        if opening is None or closing is None or opening + total != closing:
            raise ValueError(balance_error(section['name'], opening, total, closing))
        summary = re.search(r'^' + re.escape(section['name']) + r' ([+-]?' + NUM + ')$', text, re.M)
        if not summary or Decimal(money(summary[1])) != closing:
            raise ValueError('Alter Finanzreport: Kontoübersicht und Endsaldo widersprechen sich.')
        batch.balances.append(Balance(day[:7], 'Liquidität', owner, str(closing),
                                      'PDF comdirect Finanzreport ' + day, rows[-1][1]))
    batch.account_names = sources
    encoded = base64.b64encode(content).decode('ascii')
    batch.documents = [BankDocument(owner, batch.file_hash + ':' + owner,
                       'comdirect Finanzreport ' + day, day, encoded) for owner in sources]
    batch.warnings.append('Altes Format: Anfangssalden sind ohne Datum angegeben und dienen nur der Saldenprüfung. Gespeichert werden die datierten Endsalden.')
    return batch
