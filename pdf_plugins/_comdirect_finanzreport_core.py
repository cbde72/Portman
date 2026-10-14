"""Read comdirect financial reports without confusing counterparties with owners."""
import base64
import re
from collections import Counter
from pdf_plugins._finanzreport_help import report_date, balance_error
from portfolio_v5.booking_details import enrich_details
from decimal import Decimal
from portfolio_v5.models import Balance, BankDocument, BankTransaction, TaxItem, digest, money, parse_date

DATE = r'\d{2}\.\d{2}\.\d{4}'
NUM = r'\d[\d.]*,\d{2}'
ACCOUNT = r'(Girokonto|Tagesgeld PLUS(?:-Konto)?|Tagesgeldkonto|Verrechnungskonto|O&F-Konto)'
HEADING = re.compile(ACCOUNT + r'(?: (?:Dispositionskredit|ec |girocard).*)?$')
BOOKING_AMOUNT = re.compile(r'[+-]' + NUM)


def enrich_interest_closing(tx, batch=None):
    """Structure comdirect's whitespace-poor quarterly interest closing text."""
    # Coordinate-based extraction may repair the logical booking columns after
    # raw reading, so prefer the cleaned purpose and retain raw text as fallback.
    candidates = [re.sub(r'\s+', '', value) for value in (tx.purpose, tx.raw_text) if value]
    header = closing = compact = None
    for candidate in candidates:
        found_header = re.search(r'AbschlussZinsenKto(\d+)EUR.*?von(' + DATE + r')bis(' + DATE +
                                 r').*?Habenzinsen', candidate, re.I)
        found_closing = re.search(r'Abschlussrechnung(' + NUM + r')EUR', candidate, re.I)
        if found_header and found_closing:
            compact, header, closing = candidate, found_header, found_closing
            break
    if compact is None:
        return False
    interest_block = compact[header.end():closing.start()]
    components = re.findall(r'(\d[\d.]*,\d{2,4})%ab(\d{2}\.\d{2}\.)(' + NUM + r')EUR',
                            interest_block, re.I)
    if not components:
        return False
    account_number, start, end = header[1], header[2], header[3]
    gross = money(sum((Decimal(money(amount)) for _, _, amount in components), Decimal()))
    net = money(closing[1])
    tax_specs = (
        ('kapitalertragsteuer', 'Kapitalertragsteuer'),
        ('solidaritaetszuschlag', 'Solidaritätszuschlag'),
        ('kirchensteuer', 'Kirchensteuer'),
    )
    tax_items, tax_parts = [], []
    for kind, label in tax_specs:
        pattern_label = label if label != 'Solidaritätszuschlag' else r'Solidarit(?:ä|ae|.)tszuschlag'
        found = re.search(pattern_label + r'(' + NUM + r')[\-−]EUR', compact, re.I)
        if found:
            amount = money(found[1])
            tax_items.append(TaxItem(kind, amount))
            tax_parts.append(f'{label} {found[1]} EUR')
    taxes = sum((Decimal(item.amount) for item in tax_items), Decimal())
    difference = Decimal(gross) - taxes - Decimal(net)
    mismatch = abs(difference) > Decimal('0.01')
    saldo = re.search(r'SaldonachAbschluss(' + NUM + r')EUR', compact, re.I)
    purpose = [f'Abschluss Zinsen · Konto {account_number}', f'Zeitraum {start}–{end}']
    purpose.extend(f'Habenzinsen {rate} % ab {rate_from}: {amount} EUR'
                   for rate, rate_from, amount in components)
    if len(components) > 1:
        purpose.append('Habenzinsen gesamt ' + gross.replace('.', ',') + ' EUR')
    purpose.extend([*tax_parts, f'Abschlussrechnung {closing[1]} EUR'])
    if saldo:
        purpose.append(f'Saldo nach Abschluss {saldo[1]} EUR')
    if mismatch:
        warning = (f'PRÜFUNG ERFORDERLICH: Zinsabschluss Konto {account_number} zum {end}: '
                   f'Brutto {gross} EUR − Steuern {money(taxes)} EUR ergibt nicht Netto {net} EUR '
                   f'(Abweichung {money(difference)} EUR). Werte wurden aus dem Original übernommen.')
        purpose.insert(0, '⚠ PRÜFUNG ERFORDERLICH')
        tx.field_sources['interest_reconciliation'] = warning
        if batch is not None and warning not in batch.warnings:
            batch.warnings.append(warning)
    tx.kind = 'INTEREST'
    tx.purpose = ' · '.join(purpose)
    tx.booking_text = 'Abschluss Zinsen'
    tx.operation = 'Zinsgutschrift'
    tx.counterparty = 'comdirect'
    tx.bank_reference = 'Konto ' + account_number
    tx.document_reference = 'Zinsabschluss Konto ' + account_number + ' · ' + end
    tx.value_date = parse_date(end) or tx.value_date
    tx.pay_date = parse_date(end) or ''
    tx.fiscal_period_start = parse_date(start) or ''
    tx.fiscal_period_end = parse_date(end) or ''
    tx.gross_income = gross
    tx.gross_amount = gross
    tx.gross_currency = 'EUR'
    tx.taxes = money(taxes)
    # German Kapitalertragsteuer is part of total tax, not foreign withholding tax.
    tx.withholding_tax = next((item.amount for item in tax_items if item.kind == 'quellensteuer'), None)
    tx.solidarity_tax = next((item.amount for item in tax_items if item.kind == 'solidaritaetszuschlag'), None)
    tx.tax_items = tax_items
    tx.income_basis = 'net'
    tx.field_sources.update({field: 'comdirect Finanzreport · Abschluss Zinsen'
                             for field in ('kind', 'gross_income', 'gross_amount', 'taxes', 'value_date',
                                           'solidarity_tax',
                                           'fiscal_period_start', 'fiscal_period_end')})
    from portfolio_v5.models import enrich_tax_details
    enrich_tax_details(tx)
    return True


def is_finanzreport(pages):
    text = '\n'.join(pages)
    return bool(re.search(r'Finanzreport\s+Nr\.', text, re.I) and re.search(r'comdirect', text, re.I))


def parse_finanzreport(batch, pages, content, *, bookings_only=False):
    batch = _parse_cash_report(batch, pages, content)
    if not bookings_only:
        from pdf_plugins._comdirect_depot import append_depot
        append_depot(batch, pages)
    return batch


def _parse_cash_report(batch, pages, content):
    if any(re.search(r'Buchungstag\s+Valuta\s+Soll\s*/\s*Haben', text) for text in pages):
        from pdf_plugins._comdirect_finanzreport_legacy import parse_legacy_finanzreport
        return parse_legacy_finanzreport(batch, pages, content, bookings_only=True)
    lines = [(page, row, ' '.join(line.split())) for page, text in enumerate(pages, 1)
             for row, line in enumerate(text.splitlines(), 1) if line.strip()]
    text = '\n'.join(line for _, _, line in lines)
    day = report_date(text)
    batch.document_type = 'comdirect Finanzreport'
    owners, overview = {}, {}
    first_table = next((i for i, (_, _, line) in enumerate(lines)
                        if HEADING.fullmatch(line) and any('Buchungstag' in entry[2]
                            for entry in lines[i + 1:i + 4])), len(lines))
    customer = re.search(r'(?:Ihre Kontonummer:|Kontonummer) (\d+)', text)
    for _, _, line in lines[:first_table]:
        match = re.match(ACCOUNT + r'\s+(DE(?: ?\d){20})', line)
        if match:
            name, iban = match[1], match[2].replace(' ', '')
            if int(iban[4:] + '1314' + iban[2:4]) % 97 != 1:
                raise ValueError('Finanzreport: ungültige Konto-IBAN.')
            if name in owners and owners[name] != 'IBAN ' + iban:
                raise ValueError('Finanzreport: mehrdeutige Kontozuordnung.')
            owners[name] = 'IBAN ' + iban
            amount = re.fullmatch(r'\s*([+-]?' + NUM + ')', line[match.end():])
            if amount: overview[name] = money(amount[1])
        elif customer:
            summary = re.fullmatch(ACCOUNT + r' ([+-]?' + NUM + ')', line)
            if summary:
                name = summary[1]
                owners[name] = 'comdirect ' + name + ' (Stammkonto ' + customer[1] + ')'
                overview[name] = money(summary[2])
    if not owners:
        raise ValueError('Finanzreport: Kontoübersicht mit IBAN fehlt.')
    current, pending = None, None
    opened, closed = {}, {}
    occurrences = Counter()
    def flush():
        nonlocal pending
        if pending is None: return
        tx, page, row = pending
        enrich_interest_closing(tx, batch)
        enrich_details(tx)
        identity = digest([tx.account, tx.date, tx.value_date, tx.amount, tx.purpose])
        occurrences[identity] += 1
        tx.external_id = f'comdirect-pdf-{identity}-{occurrences[identity]}'
        batch.transactions.append(tx)
        batch.pdf_booking_evidence.append({'page': page, 'line': row, 'text': tx.purpose,
                                          'ocr': False,
                                          'review_required': 'interest_reconciliation' in tx.field_sources})
        pending = None
    depot_mode = False
    for index, (page, row, line) in enumerate(lines):
        if line.startswith(('Finanzreport ', 'Kundennummer', 'comdirect', '25449 Quickborn')):
            continue
        heading = HEADING.fullmatch(line)
        if heading and any('Buchungstag' in entry[2] or entry[2].startswith('Alter Saldo')
                           for entry in lines[index + 1:index + 4]):
            flush()
            current = heading[1]
            depot_mode = False
            continue
        if line == 'Depot':
            flush(); current = None; depot_mode = True
            continue
        if depot_mode:
            continue
        if not current: continue
        if line.startswith(('Buchungstag ', 'Valuta ', 'Wichtige Hinweise', 'Zinsübersicht')):
            continue
        balance = re.fullmatch(r'(Alter|Neuer) Saldo (' + DATE + r') ([+-]?' + NUM + ')', line)
        if balance:
            flush()
            owner = owners.get(current)
            if owner is None: raise ValueError('Finanzreport: Kontobereich ohne IBAN.')
            balance_day = parse_date(balance[2])
            if not balance_day or balance_day > day:
                raise ValueError(f'Finanzreport: ungültiges Saldendatum auf Seite {page}, Zeile {row}.')
            value = money(balance[3])
            (opened if balance[1] == 'Alter' else closed)[current] = Decimal(value)
            batch.balances.append(Balance(balance_day[:7], 'Liquidität', owner, value,
                                          'PDF comdirect Finanzreport ' + balance_day, row))
            if balance[1] == 'Neuer': current = None
            continue
        dated = re.fullmatch(r'(' + DATE + r')(?: (.*))?', line)
        amount = BOOKING_AMOUNT.search(line) if dated else None
        if dated and amount:
            flush()
            if current not in owners: raise ValueError('Finanzreport: Buchungskonto unbekannt.')
            booked = parse_date(dated[1])
            if not booked or booked > day: raise ValueError('Finanzreport: ungültiger Buchungstag.')
            tx = BankTransaction(owners[current], '', booked, 'BANK_BOOKING', money(amount[0]), 'EUR',
                                 row=row, value_date='',
                                 raw_text=line,
                                 purpose=' '.join((line[dated.start(2):amount.start()] + ' ' + line[amount.end():]).split()))
            pending = (tx, page, row)
        elif pending:
            pending[0].raw_text += '\n' + line
            if dated and not pending[0].value_date:
                pending[0].value_date = parse_date(dated[1]) or ''
                line = dated[2] or ''
            pending[0].purpose += ' ' + line
        elif dated:
            raise ValueError('Finanzreport: datierte Zeile ohne zugehörige Buchung.')
    flush()
    for name, owner in owners.items():
        total = sum((Decimal(tx.amount) for tx in batch.transactions if tx.account == owner), Decimal(0))
        if name not in opened or name not in closed or opened[name] + total != closed[name]:
            raise ValueError(balance_error(name, opened.get(name), total, closed.get(name)))
        if name in overview and closed[name] != Decimal(overview[name]):
            raise ValueError('Finanzreport: Kontoübersicht und Endsaldo widersprechen sich.')
    sources = list(owners.values())
    batch.account_names = sources
    encoded = base64.b64encode(content).decode('ascii')
    batch.documents = [BankDocument(owner, batch.file_hash + ':' + owner, 'comdirect Finanzreport ' + day,
                                    day, encoded) for owner in sources]
    return batch
