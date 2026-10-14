"""Deka Investments Quartalsbericht (Depotübersicht, Umsatzübersicht); user plugin."""
import base64
import re
from decimal import Decimal

from portfolio_v5.models import (BankDocument, Position, Snapshot, Transaction,
                                 correction_number, digest, money, parse_date)
from portfolio_v5.pdf_plugins import Detection
from portfolio_v5.booking_details import extract_bank_reference

DIVIDEND_KIND = 'dividende'   # Ausschüttung / Kauf aus Ertrag
ASSET_TYPE = 'Fonds'

DATE = r'\d{2}\.\d{2}\.\d{4}'
AMOUNT = r'[0-9]{1,3}(?:\.[0-9]{3})*,\d{2}'

TITLE = re.compile(r'Quartalsbericht\s*per\s*(?P<date>' + DATE + ')')
OVERVIEW_PAGE = re.compile(r'(?m)^[ \t]*Depotübersicht[ \t]*$')
TURNOVER_PAGE = re.compile(r'(?m)^[ \t]*Umsatzübersicht[ \t]*$')
DEPOT = re.compile(r'Depot:\s*(?P<id>\d{6,})')
OVERVIEW_ROW = re.compile(
    r'(?m)^[ \t]*(?P<isin>[A-Z]{2}[A-Z0-9]{9}\d)[ \t]+(?P<ud>\d{2})[ \t]+(?P<name>\S.*?)[ \t]+'
    r'(?P<value>' + AMOUNT + r')[ \t]+(?P<perf>[+-]' + AMOUNT + r')[ \t]*$')
OVERVIEW_NOTE = re.compile(r'(?m)^[ \t]*(?P<note>VL-Vertrag:[^\n]*)$')
OVERVIEW_TOTAL = re.compile(r'Gesamt\s*in\s*EUR[ \t]+(?P<value>' + AMOUNT + r')[ \t]+[+-]' + AMOUNT)
BLOCK = re.compile(r'ISIN:\s*(?P<isin>[A-Z]{2}[A-Z0-9]{9}\d)\s+Unterdepot:\s*(?P<ud>\d+)')
STOCK = re.compile(
    r'Bestand\s+am\s+(?P<date>' + DATE + r')[ \t]+(?P<value>' + AMOUNT + r')[ \t]+'
    r'(?P<price>[0-9.]+,\d+)[ \t]+(?P<shares>[0-9.]+,\d+)')
VALUATION = re.compile(r'Bewertung\s+mit\s+dem\s+Rücknahmepreis\s+vom\s+(?P<date>' + DATE + ')')
DATED_ROW = re.compile(r'(?m)^(?P<line>[^\n]*' + DATE + r'[ \t]+' + DATE + r')[ \t]*$')
DISTRIBUTION = re.compile(
    r'Ausschüttung\s*/\s*Kauf\s+aus\s+Ertrag[ \t]+(?P<amount>' + AMOUNT + r')[ \t]+'
    r'(?P<price>[0-9.]+,\d+)[ \t]+(?P<shares>[+-][0-9.]+,\d+)[ \t]+'
    r'(?P<date>' + DATE + r')[ \t]+(?P<settled>' + DATE + r')')


class DekaQuartalsberichtPlugin:
    plugin_id = 'user.deka-quartalsbericht'
    bank_name = 'Deka Investments'
    version = '1.0'
    document_types = 'Quartalsbericht (Depotübersicht, Umsatzübersicht)'

    def detect(self, document):
        text = document.text
        if not (re.search(r'Deka', text) and TITLE.search(text) and OVERVIEW_PAGE.search(text)):
            return []
        return [Detection(0.95, 'Deka Quartalsbericht', 'quartalsbericht',
                          'Deka, Quartalsbericht und Depotübersicht erkannt')]

    def parse(self, document, detection, context):
        if any(page.used_ocr for page in document.pages):
            raise ValueError('Deka-Berichte benötigen eingebetteten Text zur sicheren Bestandsprüfung.')
        if detection.handler_id != 'quartalsbericht':
            raise ValueError('Nicht unterstützter Dokumenttyp: ' + detection.handler_id)
        batch = context.batch
        text = document.text

        depot = DEPOT.search(text)
        title = TITLE.search(text)
        as_of = parse_date(title.group('date')) if title else None
        if not (depot and as_of):
            raise ValueError('Depotnummer oder Stichtag nicht erkannt.')
        account = 'Depot ' + depot.group('id')

        overview_text = '\n'.join(p.text for p in document.pages if OVERVIEW_PAGE.search(p.text))
        turnover_pages = [p for p in document.pages if TURNOVER_PAGE.search(p.text)]

        # 1) Depotübersicht: maßgebliche Liste der Bestände (je Unterdepot eine Zeile)
        rows, notes = [], {}
        for line in overview_text.splitlines():
            row = OVERVIEW_ROW.match(line)
            if row:
                rows.append(row.groupdict())
            elif rows and (note := OVERVIEW_NOTE.match(line)):
                notes[(rows[-1]['isin'], rows[-1]['ud'])] = note.group('note').strip()
        if not rows:
            raise ValueError('Keine Depotpositionen in der Depotübersicht erkannt.')
        total = OVERVIEW_TOTAL.search(overview_text)
        if not total:
            raise ValueError('Gesamtsumme der Depotübersicht nicht erkannt; Vollständigkeit nicht prüfbar.')
        listed = sum((Decimal(money(r['value'])) for r in rows), Decimal(0))
        if listed != Decimal(money(total.group('value'))):
            raise ValueError(f"Summe der Positionen ({listed}) weicht von 'Gesamt in EUR' "
                             f"({money(total.group('value'))}) ab; Import abgebrochen.")

        # 2) Umsatzübersicht: Anteile, Bewertungsdatum und Ausschüttungen je Unterdepot
        turnover = {}
        for page in turnover_pages:
            blocks = list(BLOCK.finditer(page.text))
            for index, block in enumerate(blocks):
                end = blocks[index + 1].start() if index + 1 < len(blocks) else len(page.text)
                turnover[(block.group('isin'), block.group('ud'))] = (page, page.text[block.start():end], block.start())
        # Berichte, bei denen ein Unterdepot-Block über eine Seitengrenze läuft, sind nicht belegt.

        positions, transactions, evidence, warnings = [], [], [], []
        for order, row in enumerate(rows, 1):
            key = (row['isin'], row['ud'])
            value = money(row['value'])
            quantity, quote_date = None, None
            block = turnover.get(key)
            if block is None:
                warnings.append(f"Unterdepot {row['ud']}: keine Umsatzübersicht gefunden; Anteile unbekannt.")
            else:
                page, body, offset = block
                stocks = [m for m in STOCK.finditer(body) if parse_date(m.group('date')) == as_of]
                if len(stocks) != 1:
                    warnings.append(f"Unterdepot {row['ud']}: Bestand per Stichtag nicht eindeutig; Anteile unbekannt.")
                else:
                    stock = stocks[0]
                    if money(stock.group('value')) != value:
                        raise ValueError(f"Unterdepot {row['ud']}: Wert in Depotübersicht ({value}) und "
                                         f"Umsatzübersicht ({money(stock.group('value'))}) weichen ab.")
                    quantity = correction_number(stock.group('shares'))
                    valuation = VALUATION.search(body, stock.end())
                    quote_date = parse_date(valuation.group('date')) if valuation else None
                    opening = [m for m in STOCK.finditer(body) if m is not stock]
                    moved = Decimal(0)
                    for dated in DATED_ROW.finditer(body):
                        line = dated.group('line')
                        dist = DISTRIBUTION.search(line)
                        if not dist:
                            warnings.append(f"Unterdepot {row['ud']}: Umsatz nicht unterstützt und ausgelassen: "
                                            + ' '.join(line.split()))
                            continue
                        booked = parse_date(dist.group('date'))
                        amount = money(dist.group('amount'))
                        moved += Decimal(correction_number(dist.group('shares')))
                        line_no = page.text[:offset + dated.start()].count('\n') + 1
                        reference = extract_bank_reference(line)
                        transactions.append(Transaction(
                            account=account, security=row['isin'], kind=DIVIDEND_KIND,
                            date=booked, amount=amount, currency='EUR', row=line_no,
                            document_reference=reference,
                            external_id='pdf-deka-' + digest([account, row['ud'], row['isin'], booked, amount,
                                                              dist.group('shares')])))
                        evidence.append({'page': page.number, 'line': line_no, 'text': ' '.join(line.split()),
                                         'ocr': False, 'confidence': None, 'review_required': False})
                    if opening and Decimal(quantity) != Decimal(correction_number(opening[0].group('shares'))) + moved:
                        warnings.append(f"Unterdepot {row['ud']}: Anteilsbewegung passt nicht zu Anfangs- und "
                                        'Endbestand; Umsätze bitte am Original prüfen.')
            if key in notes:
                warnings.append(f"Unterdepot {row['ud']}: {notes[key]}")
            positions.append(Position(
                key=f"{row['isin']}:{row['ud']}", name=f"{row['name']} (Unterdepot {row['ud']})",
                isin=row['isin'], asset_type=ASSET_TYPE, quantity=quantity, value=value,
                currency='EUR', quote_date=quote_date, row=order))

        complete = all(p.quantity is not None for p in positions)
        batch.snapshots.append(Snapshot(account=account, period=as_of[:7], as_of=as_of,
                                        sheet='Deka Quartalsbericht', positions=positions,
                                        complete=True, warnings=warnings))
        batch.transactions.extend(transactions)
        batch.pdf_booking_evidence.extend(evidence)
        batch.documents.append(BankDocument(
            account, batch.file_hash + ':' + account, document.path.name, as_of,
            base64.b64encode(document.content).decode('ascii')))

        if re.search(r'Informationen\s*über\s*Kosten\s*und\s*Nebenkosten', text):
            batch.warnings.append('Kosteninformation im Bericht wird nicht importiert.')
        if not complete:
            batch.warnings.append('Nicht für alle Unterdepots sind Anteile bekannt; Bestände bitte prüfen.')
        if transactions:
            batch.warnings.append('Ausschüttungen wurden wiederangelegt (Kauf aus Ertrag); der Anteilszuwachs '
                                  'steckt im Bestand, es wurde keine Kaufbuchung erzeugt.')
        return batch


plugin = DekaQuartalsberichtPlugin()
