"""Read and reconcile comdirect holdings across old and current layouts."""
import re
from decimal import Decimal
from portfolio_v5.models import BankDocument, Position, Snapshot, money, parse_quantity
from pdf_plugins._finanzreport_help import report_date

AMOUNT = r'\d[\d.]*,\d{2}'
POSITION = re.compile(
    r'([A-Z0-9]{6})(?: / (?:Girosammelverwahrung|Wertpapierrechnung))? '
    r'(\d[\d.]*,\d+)(?: STK)? (\d[\d.]*,\d+)(?: ([A-Z]{3}))? (.+)')


def append_depot(batch, pages):
    lines = [' '.join(line.split()) for page in pages for line in page.splitlines() if line.strip()]
    text = '\n'.join(lines)
    overview = re.search(r'^Depot ([+-]?' + AMOUNT + r')$', text, re.M)
    expected = Decimal(money(overview[1])) if overview else None
    positions, pending, total, active = [], None, None, False

    def finish():
        nonlocal pending
        if pending:
            if not pending.name:
                raise ValueError('Finanzreport: Wertpapiername fehlt: ' + pending.wkn)
            positions.append(pending)
            pending = None

    day = report_date(text)
    for row, line in enumerate(lines, 1):
        if line == 'Depot' or line.startswith(('Depotbestand', 'Jahresdepotabstimmung')):
            active = True
            continue
        if not active:
            continue
        if line.startswith(('Finanzreport ', 'Kundennummer', 'Kontonummer ', 'comdirect',
                            '25449 Quickborn', 'WKN /', 'Bezeichnung', 'Kurs ', 'Stückzinsen', 'USt-ID:')):
            continue
        if ' über ' in line and 'AKV' in line:
            continue
        if pending and re.fullmatch(re.escape(pending.wkn) + r' / (?:GIROSAMMELVERWAHRUNG|WERTPAPIERRECHNUNG)(?: [A-ZÄÖÜ ]+)?', line):
            continue
        if line.startswith('Gesamtkurswert'):
            finish()
            values = re.findall(AMOUNT, line)
            total = Decimal(money(values[0])) if values else None
            active = False
            continue
        match = POSITION.fullmatch(line)
        if match:
            finish()
            values = re.fullmatch(r'([+-]?' + AMOUNT + r')\s*([+-]?' + AMOUNT +
                                 r'|-----)\s*([+-]?' + AMOUNT + r'|-----)(.*)', match[5])
            if not values:
                raise ValueError('Finanzreport: Kurswert/Kaufwert nicht eindeutig: ' + match[1])
            value, cost, profit = [money(v) if v != '-----' else None for v in values.groups()[:3]]
            if cost is not None and profit is not None and abs(Decimal(value) - Decimal(cost) - Decimal(profit)) > Decimal('0.02'):
                raise ValueError('Finanzreport: Wertpapierwerte nicht abgestimmt: ' + match[1])
            pending = Position('WKN:' + match[1], values[4].strip(), wkn=match[1],
                               quantity=parse_quantity(match[2], locale='de_DE'),
                               value=value, cost=cost, currency='EUR', quote_date=day, row=row)
        elif re.match(r'^[A-Z0-9]{6}(?: /| \d[\d.]*,)', line):
            raise ValueError('Finanzreport: nicht unterstützte Depotposition: ' + line)
        elif pending:
            name = re.sub(r'\s*[+-]' + AMOUNT + r'$', '', line).strip()
            if name:
                pending.name = (pending.name + ' ' + name).strip()
    finish()
    if not positions and expected is None:
        return
    if positions:
        if total is None or sum((Decimal(p.value) for p in positions), Decimal(0)) != total:
            raise ValueError('Finanzreport: Depotpositionen und Gesamtkurswert nicht abgestimmt.')
        if expected is not None and total != expected:
            raise ValueError('Finanzreport: Kontoübersicht und Depotgesamtwert widersprechen sich.')
    elif expected != 0:
        raise ValueError('Finanzreport: Depotübersicht vorhanden, aber keine Positionen erkannt.')
    customer = re.search(r'Kundennummer:? \d{3} (\d+)', text) or re.search(r'(?:Ihre Kontonummer:|Kontonummer) (\d+)', text)
    if not customer:
        raise ValueError('Finanzreport: Depotzuordnung ohne Kundennummer.')
    owner = 'Depot ' + customer[1]
    batch.snapshots.append(Snapshot(owner, day[:7], day, 'comdirect Finanzreport', positions))
    batch.account_names.append(owner)
    if batch.documents:
        batch.documents.append(BankDocument(owner, batch.file_hash + ':' + owner,
                                            'comdirect Finanzreport ' + day, day, batch.documents[0].content_b64))
