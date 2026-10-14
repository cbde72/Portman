"""Conservative statement-table recognition, shared by text PDFs and local OCR."""
from collections import Counter
from datetime import date
from decimal import Decimal
import re

from portfolio_v5.models import BankTransaction, digest, money, parse_date
from portfolio_v5.booking_details import enrich_details

DATE = r'\d{2}\.\d{2}\.(?:\d{4})?'
ROW = re.compile(r'^\s*(?P<date>' + DATE + r')\s+(?P<body>.+)$')
AMOUNT = re.compile(r'(?<![\d.,])(?P<before>[+-]?)\s*(?P<number>\d{1,3}(?:\.\d{3})*,\d{2}|\d+,\d{2})\s*(?:EUR|€)?\s*(?P<after>[HS+-]?)\s*$')
HEADER = re.compile(r'(?:Bu-Tag.*Wert|Buchungstag.*(?:Valuta|Betrag|Gutschrift)|Buchungsdatum.*(?:Valuta|Betrag)|Datum.*(?:Valuta|Betrag)|Datum\s+Buchungsvorgang\s+Soll\s+Haben)', re.I)
STOP = re.compile(r'(?:(?:(?:alter|neuer)\s+)?Kontostand|Saldo|Gesamtumsatz|Übertrag|Hinweise|Herausgeberin|finanzen\.net zero GmbH|Dieses Dokument|Bitte beachten)', re.I)


def statement_end(text):
    matches = re.findall(r'(?:neuer Kontostand vom|Kontostand in EUR am|Kontoauszug vom|Auszug vom|Stand zum)\s*(\d{2}\.\d{2}\.\d{4})', text, re.I)
    dates = [parse_date(item) for item in matches]
    dates = [date.fromisoformat(item) for item in dates if item]
    return max(dates) if dates else None


def booking_date(raw, end, *, value=False):
    if len(raw) == 10:
        parsed = parse_date(raw)
        if not parsed:
            raise ValueError('ungültiges Datum')
        return parsed
    if end is None:
        raise ValueError('Jahr fehlt und Auszugsdatum ist nicht eindeutig')
    day, month = map(int, raw.rstrip('.').split('.'))
    candidates = []
    for year in (end.year - 1, end.year, end.year + 1):
        try:
            candidate = date(year, month, day)
        except ValueError:
            continue
        distance = (candidate - end).days
        if -370 <= distance <= (31 if value else 0):
            candidates.append(candidate)
    if not candidates:
        raise ValueError('ungültiges Datum')
    return min(candidates, key=lambda item: abs((item - end).days)).isoformat()


def owner_from_header(text, identify):
    sources = identify([text])
    accounts = [name for name in sources if name.startswith('Konto ')]
    ibans = [name for name in sources if name.startswith('IBAN ')]
    for iban in ibans:
        value = iban[5:]
        digits = ''.join(str(ord(char) - 55) if char.isalpha() else char for char in value[4:] + value[:4])
        if int(digits) % 97 != 1:
            return None
    # A German account number and its zero-padded IBAN suffix identify one account.
    if len(ibans) == 1 and all(ibans[0][5:].startswith('DE') and
            ibans[0][-10:].lstrip('0') == name[6:].replace(' ', '').lstrip('0') for name in accounts):
        return ibans[0]
    if len(accounts) == 1 and not ibans:
        return accounts[0]
    return None


def parse_bookings(pages, identify):
    transactions, warnings, evidence = [], [], []
    occurrences = Counter()
    previous_owner = None
    previous_end = None
    reconciliations = {}
    for page_number, text in enumerate(pages, 1):
        lines = text.splitlines()
        headers = [i for i, line in enumerate(lines) if HEADER.search(line)]
        if not headers:
            if any(ROW.match(line) and AMOUNT.search(line) for line in lines):
                warnings.append(f'Seite {page_number}: mögliche Buchungen ohne unterstützten Tabellenkopf; bitte Original prüfen.')
            continue
        for section_index, header_index in enumerate(headers):
            next_header = headers[section_index + 1] if section_index + 1 < len(headers) else len(lines)
            prefix = '\n'.join(lines[:header_index])
            # Use the last explicit header region when there are several accounts
            # on one page. A table's own header, never its purpose, sets ownership.
            if section_index:
                last_stop = max((i for i in range(headers[section_index - 1], header_index) if STOP.search(lines[i])), default=headers[section_index - 1])
                prefix = '\n'.join(lines[last_stop + 1:header_index])
            owner = owner_from_header(prefix, identify)
            if owner is None and not identify([prefix]) and section_index == 0 and re.search(r'Fortsetzung|Übertrag', prefix, re.I):
                owner = previous_owner
            end = statement_end('\n'.join(lines[header_index:next_header])) or statement_end(prefix)
            if end is None and owner == previous_owner:
                end = previous_end
            previous_owner, previous_end = owner, end
            if not owner:
                warnings.append(f'Seite {page_number}: Buchungstabelle ohne eindeutiges Quellkonto; keine Buchungen übernommen.')
                continue
            section = '\n'.join(lines[:next_header])
            if re.search(r'\b(?:USD|GBP|CHF|JPY)\b', section) or not re.search(r'\bEUR\b|€', section):
                warnings.append(f'Seite {page_number}: Kontowährung nicht eindeutig EUR; Buchungstabelle ausgelassen.')
                continue
            header = lines[header_index]
            debit, credit = header.lower().find('belastung'), header.lower().find('gutschrift')
            if re.search(r'Datum\s+Buchungsvorgang\s+Soll\s+Haben', header, re.I):
                debit, credit = header.lower().find('soll'), header.lower().find('haben')
            balances = reconciliations.setdefault(owner, [])
            for line in lines[header_index + 1:next_header]:
                if re.search(r'alter Kontostand|neuer Kontostand|Kontostand in EUR am', line, re.I):
                    match = AMOUNT.search(line)
                    if match:
                        sign = -1 if match.group('before') == '-' or match.group('after') in ('S', '-') else 1
                        balances.append(Decimal(money(match.group('number'))) * sign)
            pending = None

            def flush():
                nonlocal pending
                if pending is None:
                    return
                tx, source_line, source_row = pending
                tx.purpose = ' '.join(tx.purpose.split())
                enrich_details(tx)
                identity = digest([tx.account, tx.date, tx.value_date, tx.amount, tx.currency, tx.purpose])
                occurrences[identity] += 1
                tx.external_id = f'pdf-booking-{identity}-{occurrences[identity]}'
                transactions.append(tx)
                evidence.append({'page': page_number, 'line': source_row, 'text': source_line})
                pending = None

            for line_number in range(header_index + 1, next_header):
                line = lines[line_number].replace('\u2212', '-')
                # OCR sometimes joins adjacent date columns; restore only the
                # separator, never alter recognized digits or monetary values.
                line = re.sub(r'^(\s*' + DATE + r')(?=\d{2}\.\d{2}\.)', r'\1 ', line)
                row = ROW.match(line)
                if STOP.match(line.strip()) and not row and not (
                        pending and re.match(r'\s*Übertrag\s+(?:auf|an|von)\b', line, re.I)):
                    flush()
                    # A balance is not a booking; subsequent dated rows still count.
                    continue
                if not row:
                    if pending and line.strip() and not re.fullmatch(r'[\s─_-]+', line):
                        # Inside a booking, account numbers identify the other
                        # party. Only table headers establish the source account.
                        pending[0].purpose += ' ' + line.strip()
                        pending[0].raw_text += '\n' + ' '.join(line.split())
                    continue
                flush()
                amount = AMOUNT.search(line)
                if not amount:
                    warnings.append(f'Seite {page_number}, Zeile {line_number + 1}: datierte Zeile ohne eindeutigen Betrag ausgelassen.')
                    continue
                try:
                    booked = booking_date(row.group('date'), end)
                    body = line[row.start('body'):amount.start()].strip()
                    explicit_value = re.search(r'\bWertstellung\s*:\s*(' + DATE + r')', body, re.I)
                    if explicit_value:
                        # Older Renault statements embed the value date in the
                        # purpose column, rather than in a separate date column.
                        body = (body[:explicit_value.start()] + body[explicit_value.end():]).strip()
                    dates = list(re.finditer(DATE, body))
                    value_date = booked
                    if explicit_value:
                        try:
                            value_date = booking_date(explicit_value[1], end, value=True)
                        except ValueError:
                            value_date = ''
                            warnings.append(f'Seite {page_number}, Zeile {line_number + 1}: '
                                            f'Valuta {explicit_value[1]} ist kein gültiges Kalenderdatum; Valuta bleibt offen, bitte prüfen.')
                    elif dates:
                        # Known tables place value date first or last in the body.
                        candidate = dates[0] if dates[0].start() == 0 else dates[-1]
                        if candidate.start() == 0 or candidate.end() == len(body):
                            try:
                                value_date = booking_date(candidate.group(), end, value=True)
                            except ValueError:
                                value_date = ''
                                warnings.append(f'Seite {page_number}, Zeile {line_number + 1}: '
                                                f'Valuta {candidate.group()} ist kein gültiges Kalenderdatum; Valuta bleibt offen, bitte prüfen.')
                            body = (body[:candidate.start()] + body[candidate.end():]).strip()
                    if not body:
                        raise ValueError('Buchungstext fehlt')
                    signs = [s for s in (amount.group('before'), amount.group('after')) if s]
                    polarities = {-1 if s in ('-', 'S') else 1 for s in signs}
                    if len(polarities) > 1:
                        raise ValueError('widersprüchliche Vorzeichen')
                    if polarities:
                        sign = polarities.pop()
                    elif 0 <= debit < credit and amount.start('number') >= debit:
                        sign = -1 if amount.end('number') < credit else 1
                    else:
                        raise ValueError('Soll/Haben bzw. Vorzeichen unklar')
                    value = str(Decimal(money(amount.group('number'))) * sign)
                    tx = BankTransaction(owner, '', booked, 'BANK_BOOKING', value, 'EUR',
                        row=line_number + 1, value_date=value_date, purpose=body, raw_text=' '.join(line.split()))
                    pending = (tx, line.strip(), line_number + 1)
                except ValueError as error:
                    warnings.append(f'Seite {page_number}, Zeile {line_number + 1}: {error}; Buchung ausgelassen.')
            flush()
    for owner, balances in reconciliations.items():
        if len(balances) >= 2:
            total = sum((Decimal(tx.amount) for tx in transactions if tx.account == owner), Decimal(0))
            if balances[0] + total != balances[-1]:
                warnings.append(f'{owner}: Saldenprüfung weicht um {balances[-1] - balances[0] - total:.2f} EUR ab. '
                                'Möglicherweise fehlen Buchungen oder Beträge wurden falsch erkannt; einzeln prüfen.')
    return transactions, warnings, evidence
