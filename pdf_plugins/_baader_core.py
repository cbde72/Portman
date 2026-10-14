import base64
import re
from decimal import Decimal

from portfolio_v5.models import BankDocument, BankTransaction, Position, Snapshot, parse_date, valid_isin
from portfolio_v5.importers import asset_type

NUMBER = r'\d[\d.]*(?:,\d+)?'


def number(value):
    return Decimal(value.replace('.', '').replace(',', '.'))


def required(pattern, text):
    match = re.search(pattern, text, re.M)
    if not match:
        raise ValueError('Baader-Beleg: Pflichtfeld fehlt oder Format unbekannt: ' + pattern)
    return match


def is_baader_portfolio(pages):
    text = '\n'.join(pages)
    return ('Baader Bank' in text and bool(re.search(r'Depot-Nr\.:\s*\d+', text))
            and bool(re.search(r'Quartalsaufstellung|Wertpapierabrechnung:', text)))


def parse_baader_portfolio(batch, pages, content):
    text = '\n'.join(pages)
    depot = required(r'Depot-Nr\.:\s*(\d+)', text)[1]
    account = 'Baader Depot ' + depot
    batch.account_names = [account]
    batch.pdf_text = text
    if re.search(r'\bStorno\b|\bStornierung\b', text, re.I):
        raise ValueError('Baader-Stornobeleg muss mit der ursprünglichen Abrechnung abgeglichen werden.')
    if 'Quartalsaufstellung' in text:
        batch.document_type = 'Baader Quartalsaufstellung'
        day = parse_date(required(r'MIFID II per\s+(\d{2}\.\d{2}\.\d{4})', text)[1])
        if not day:
            raise ValueError('Ungültiger Quartalsstichtag.')
        positions = []
        category = 'Aktie'
        for page_number, page in enumerate(pages, 1):
            for line in page.splitlines():
                if re.match(r'^\s*Stück\s+', line) and 'WKN:' not in line and 'Offene Lieferung CA' not in line:
                    raise ValueError('Nicht unterstützte Bestandszeile in der Quartalsaufstellung.')
            starts = list(re.finditer(r'^\s*Stück\s+' + NUMBER + r'\s+WKN:', page, re.M))
            for index, start in enumerate(starts):
                headings = re.findall(r'^\s*(?:Fortsetzung:\s*)?(Aktien und aktienähnliche|Fonds)\s*$', page[:start.start()], re.M)
                if headings:
                    category = 'Fonds' if headings[-1] == 'Fonds' else 'Aktie'
                block = page[start.start():starts[index + 1].start() if index + 1 < len(starts) else len(page)]
                row = required(r'^\s*Stück\s+(' + NUMBER + r')\s+WKN:\s*(\w{6})\s+([A-Z]{3})\s+(' + NUMBER + r')\s+(' + NUMBER + r')\s+([A-Z]{3})\s*$', block)
                isin = required(r'ISIN:\s*([A-Z0-9]{12})', block)[1]
                if not valid_isin(isin):
                    raise ValueError('Ungültige ISIN im Baader-Depotstand: ' + isin)
                name = required(r'ISIN:[^\n]*\n\s*([^\n]+)', block)[1].strip()
                quantity, value = number(row[1]), number(row[5])
                if quantity <= 0 or value < 0 or row[6] != 'EUR':
                    raise ValueError('Unzulässige Stückzahl oder Depotbewertung.')
                if row[3] == 'EUR' and abs(quantity * number(row[4]) - value) > Decimal('.02'):
                    raise ValueError('Stückzahl, Kurs und Kurswert passen nicht zusammen: ' + isin)
                positions.append(Position(isin, name, isin, row[2], asset_type(name, category),
                    str(quantity), value=str(value), currency=row[6], quote_date=day, row=page_number))
        total = number(required(r'Depotwert\s+(' + NUMBER + r')\s+EUR', text)[1])
        if not positions or len({p.isin for p in positions}) != len(positions):
            raise ValueError('Keine eindeutigen Positionen in der Quartalsaufstellung.')
        if sum((Decimal(p.value) for p in positions), Decimal(0)) != total:
            raise ValueError('Positionssumme stimmt nicht mit dem ausgewiesenen Depotwert überein.')
        batch.snapshots.append(Snapshot(account, day[:7], day, batch.document_type, positions))
        batch.warnings.append('Vollständiger Depotstand zum Quartalsstichtag; keine Einstandswerte ausgewiesen.')
    else:
        batch.document_type = 'Baader Wertpapierabrechnung'
        kind = required(r'Wertpapierabrechnung:\s*(Kauf|Verkauf)\b', text)[1]
        reference = required(r'Referenz-Nr\.:\s*(\d+)', text)[1]
        isin = required(r'ISIN:\s*([A-Z0-9]{12})', text)[1]
        if not valid_isin(isin):
            raise ValueError('Ungültige ISIN in der Abrechnung: ' + isin)
        nominal = required(r'^\s*STK\s+(' + NUMBER + r')\s+(.+?)\s{2,}([A-Z]{3})\s+(' + NUMBER + r')\s*$', text)
        quantity = number(nominal[1])
        execution = required(r'Details zur Ausführung:([\s\S]*?)Verwahrart:', text)[1]
        dates = set(re.findall(r'\b\d{2}\.\d{2}\.\d{4}\b', execution))
        if len(dates) != 1:
            raise ValueError('Kein eindeutiger Handelstag in der Ausführungstabelle.')
        day = parse_date(next(iter(dates)))
        settlement = required(r'(?:Zu (Lasten|Gunsten) Konto\s+\d+|Total)\s+Valuta:\s*(\d{2}\.\d{2}\.\d{4})\s+([A-Z]{3})\s+(' + NUMBER + r')', text)
        if not day or quantity <= 0 or nominal[3] != settlement[3]:
            raise ValueError('Handelstag, Stückzahl oder Währung der Abrechnung ungültig.')
        if settlement[1] is None and number(settlement[4]) != 0:
            raise ValueError('Abrechnung ohne Belastungs-/Gutschriftrichtung.')
        if settlement[1] is not None and (kind == 'Kauf') != (settlement[1] == 'Lasten'):
            raise ValueError('Kauf/Verkauf und Belastung/Gutschrift widersprechen sich.')
        gross = number(required(r'^\s*Kurswert\s+' + settlement[3] + r'\s+(' + NUMBER + r')\s*$', text)[1])
        fees = sum((number(v) for v in re.findall(r'^\s*Mindermengenzuschlag Finanzen\.net\s+' + settlement[3] + r'\s+(' + NUMBER + r')', text, re.M)), Decimal(0))
        taxes = sum((number(v) for v in re.findall(r'^\s*(?:Kapitalertragsteuer|Solidaritätszuschlag|Kirchensteuer)\s+' + settlement[3] + r'\s+(' + NUMBER + r')', text, re.M)), Decimal(0))
        if abs(gross - quantity * number(nominal[4])) > Decimal('.02'):
            raise ValueError('Stückzahl und Ausführungskurs passen nicht zum Kurswert.')
        if gross + (fees + taxes) * (1 if kind == 'Kauf' else -1) != number(settlement[4]):
            raise ValueError('Kurswert, Gebühren und Steuern passen nicht zum Abrechnungsbetrag.')
        amount = number(settlement[4])
        tx = BankTransaction(account, 'baader-trade-' + depot + '-' + reference, day,
            'BUY' if kind == 'Kauf' else 'SELL', str(amount), settlement[3],
            security=isin, quantity=str(quantity), value_date=parse_date(settlement[2]) or '',
            fees=str(fees), taxes=str(taxes),
            purpose=nominal[2].strip(), bank_reference=reference, document_reference=reference,
            booking_text=f'Nominale STK {quantity} · Kurs {nominal[3]} {number(nominal[4])} · Kurswert {settlement[3]} {gross}',
            raw_text=nominal[0].strip() + '\n' + f'Kurswert {settlement[3]} {gross}', affects_cash=False)
        batch.transactions.append(tx)
        batch.pdf_booking_evidence.append(dict(page=1, text=nominal[0].strip(), ocr=False, review_required=False))
        batch.warnings.append('Käufe: Nominale und Kurswert als Stückzahl und Einstand; Gebühren und Steuern separat. Verkäufe bauen den Einstand der verkauften Stücke nach FIFO ab. Keine neue Kursbewertung oder Kontobuchung. Bereits im Depotstand enthaltene Stücke werden nicht erneut addiert.')
    batch.documents.append(BankDocument(account, batch.file_hash + ':' + account,
        batch.document_type, day, base64.b64encode(content).decode('ascii')))
    return batch
