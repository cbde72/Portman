import base64
import re
from decimal import Decimal

from portfolio_v5.models import (BankDocument, BankTransaction, FeeItem, Position, SecurityInfo, Snapshot,
                                 TaxEvent, TaxItem, Transaction, parse_date, valid_isin)
from portfolio_v5.importers import asset_type

NUMBER = r'\d[\d.]*(?:,\d+)?'

# The cancellation itself does not print the original document reference.  Only
# pairs verified against both original PDFs belong here; unknown cancellations
# must remain rejected instead of guessing their economic counterpart.
VERIFIED_DIVIDEND_REVERSALS = {
    '26172813': {
        'original_reference': '524443206',
        'reversal_reference': '526758625',
        'isin': 'US0378331005',
        'quantity': Decimal('4.125'),
        'date': '2024-02-15',
        'net': Decimal('0.78'),
        'taxes': Decimal('0.14'),
        'gross': Decimal('0.92'),
    },
}


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
            and bool(re.search(r'Quartalsaufstellung|Wertpapierabrechnung:|Dividendenabrechnung|Vorabpauschale|'
                               r'Depotauszug\s+per|Depoteinlieferung|Depotauslieferung', text)))


def security_header(text):
    match = required(r'Nominale\s+ISIN:\s*([A-Z0-9]{12})\s+WKN:\s*(\w{6})[^\n]*\n\s*STK\s+(' + NUMBER + r')\s+([^\n]+)', text)
    isin, wkn, quantity, rest = match[1], match[2], number(match[3]), match[4].strip()
    if not valid_isin(isin) or quantity <= 0:
        raise ValueError('Ungültige ISIN oder Stückzahl im Baader-Ereignis.')
    return isin, wkn, quantity, rest


def tax_items(text):
    patterns = (('kapitalertragsteuer', r'^\s*Kapitalertragsteuer\s+EUR\s+(' + NUMBER + r')\s*-?\s*$'),
                ('solidaritaetszuschlag', r'^\s*Solidaritätszuschlag\s+EUR\s+(' + NUMBER + r')\s*-?\s*$'),
                ('kirchensteuer', r'^\s*Kirchensteuer\s+EUR\s+(' + NUMBER + r')\s*-?\s*$'),
                ('quellensteuer', r'^\s*(?:US-)?Quellensteuer\s+EUR\s+(' + NUMBER + r')\s*-?\s*$'))
    return [TaxItem(kind, str(number(match[1]))) for kind, pattern in patterns
            for match in [re.search(pattern, text, re.M)] if match and number(match[1])]


def parse_baader_income(batch, text, account, is_reversal=False):
    isin, wkn, quantity, rest = security_header(text)
    settlement = required(r'Zu\s+Gunsten\s+Konto\s+(\d+)\s+Valuta:\s*(' + r'\d{2}\.\d{2}\.\d{4}' +
                          r')\s+([A-Z]{3})\s+(' + NUMBER + r')', text)
    day, amount, currency = parse_date(settlement[2]), number(settlement[4]), settlement[3]
    reference = required(r'Referenz-Nr\.:\s*(\d+)', text)[1]
    items = tax_items(text)
    taxes = sum((Decimal(item.amount) for item in items), Decimal())
    reverses_external_id = ''
    if is_reversal:
        process = required(r'Vorgangs-Nr\.:\s*(\d+)', text)[1]
        verified = VERIFIED_DIVIDEND_REVERSALS.get(process)
        actual = {
            'reversal_reference': reference, 'isin': isin, 'quantity': quantity,
            'date': day, 'net': amount, 'taxes': taxes, 'gross': amount + taxes,
        }
        if not verified or any(actual[field] != verified[field] for field in actual):
            raise ValueError('Baader-Dividendenstorno ist keinem vollständig geprüften Originalbeleg zugeordnet.')
        reverses_external_id = 'baader-income-' + verified['original_reference']
        amount, taxes = -amount, -taxes
        items = [TaxItem(item.kind, str(-Decimal(item.amount))) for item in items]
    tx = BankTransaction(
        account=account, external_id='baader-income-' + reference, date=day, value_date=day,
        kind='DIVIDEND', amount=str(amount), currency=currency, security=isin,
        security_ref=isin, quantity=str(quantity), taxes=str(taxes) if taxes else None,
        tax_items=items, gross_amount=str(amount + taxes), gross_income=str(amount + taxes),
        gross_currency=currency, income_basis='net', cash_account='Baader Konto ' + settlement[1],
        depot_account=account, affects_cash=False, bank_reference=reference,
        document_reference=reference, purpose=('STORNO ' if is_reversal else '') + rest,
        is_reversal=is_reversal, reverses_external_id=reverses_external_id)
    batch.transactions.append(tx)
    batch.securities.append(SecurityInfo(key=isin, isin=isin, wkn=wkn, name=rest))
    return day


def parse_baader_advance_tax(batch, text, account):
    isin, wkn, quantity, rest = security_header(text)
    settlement = required(r'Zu\s+Lasten\s+Konto\s+(\d+)\s+Valuta:\s*(' + r'\d{2}\.\d{2}\.\d{4}' +
                          r')\s+([A-Z]{3})\s+(' + NUMBER + r')', text)
    day, amount, currency = parse_date(settlement[2]), number(settlement[4]), settlement[3]
    reference = required(r'Referenz-Nr\.:\s*(\d+)', text)[1]
    items = tax_items(text)
    taxes = sum((Decimal(item.amount) for item in items), Decimal())
    if abs(taxes - amount) > Decimal('.01'):
        raise ValueError('Baader-Steuerkomponenten passen nicht zur Vorabpauschalen-Belastung.')
    bases = re.findall(r'Bemessungsgrundlage\s+zur\s+Kapitalertragsteuer\s+EUR\s+(' + NUMBER +
                       r')\s+EUR\s+(' + NUMBER + r')', text)
    taxable = str(number(bases[-1][1])) if bases else None
    event_id = 'baader-advance-' + reference
    batch.tax_events.append(TaxEvent(
        external_id=event_id, account=account, type='vorabpauschale', date=day,
        tax_year=day[:4], security_ref=isin, quantity=str(quantity), currency=currency,
        taxable_income=taxable, reference_no=reference))
    batch.transactions.append(BankTransaction(
        account=account, external_id=event_id + '-tax', date=day, value_date=day,
        kind='TAX', amount='-' + str(amount), currency=currency, security=isin,
        security_ref=isin, quantity=str(quantity), taxes=str(amount), tax_items=items,
        cash_account='Baader Konto ' + settlement[1], depot_account=account, affects_cash=False,
        bank_reference=reference, document_reference=reference, purpose='Vorabpauschale ' + rest))
    batch.securities.append(SecurityInfo(key=isin, isin=isin, wkn=wkn, name=rest))
    return day


def parse_baader_transfer(batch, text, account):
    inbound = 'Depoteinlieferung' in text
    isin, wkn, quantity, rest = security_header(text)
    valuta = required(r'Lagerstelle:\s*\d+\s+Valuta:\s*(\d{2}\.\d{2}\.\d{4})', text)[1]
    day = parse_date(valuta)
    reference = required(r'(?:EINLIEFERUNG|AUSLIEFERUNG)-(\d+[.]\d+)', text,)[1]
    batch.transactions.append(Transaction(
        account=account, external_id='baader-transfer-' + reference, date=day,
        kind='TRANSFER_IN' if inbound else 'TRANSFER_OUT', amount='0', currency='EUR',
        security=isin, security_ref=isin, quantity=str(quantity), depot_account=account,
        document_reference=reference, transaction_reference=reference))
    batch.securities.append(SecurityInfo(key=isin, isin=isin, wkn=wkn, name=rest))
    return day


def parse_baader_statement(batch, text, account):
    day = parse_date(required(r'Depotauszug\s+per\s+(\d{2}\.\d{2}\.\d{4})', text)[1])
    starts = list(re.finditer(r'^\s*Stück\s+(' + NUMBER + r')\s+WKN:\s*(\w{6})\s+([A-Z]{3})\s+(' +
                              NUMBER + r')\s+(' + NUMBER + r')\s+EUR\s*$', text, re.M))
    positions = []
    for index, row in enumerate(starts):
        end = starts[index + 1].start() if index + 1 < len(starts) else len(text)
        block = text[row.start():end]
        isin = required(r'ISIN:\s*([A-Z0-9]{12})', block)[1]
        if not valid_isin(isin):
            raise ValueError('Ungültige ISIN im Baader-Jahresdepotauszug.')
        name_match = re.search(r'ISIN:[^\n]*\n\s*([^\n]+)', block)
        name = name_match[1].strip() if name_match else 'Baader Wertpapier ' + isin
        positions.append(Position(
            key=isin, name=name, isin=isin, wkn=row[2], quantity=str(number(row[1])),
            value=str(number(row[5])), currency='EUR', quote_date=day,
            price=str(number(row[4])), price_currency=row[3]))
    total = number(required(r'Depotwert\s+(' + NUMBER + r')\s+EUR', text)[1])
    if not positions or abs(sum((Decimal(p.value) for p in positions), Decimal()) - total) > Decimal('.01'):
        raise ValueError('Baader-Jahresbestand ist leer oder stimmt nicht mit dem Depotwert überein.')
    batch.snapshots.append(Snapshot(
        account=account, period=day[:7], as_of=day, sheet='Baader Jahresdepotauszug',
        positions=positions, complete=True, reported_total_value=str(total),
        reported_position_count=len(positions), statement_type='Jahresdepotauszug'))
    return day


def parse_baader_portfolio(batch, pages, content):
    text = '\n'.join(pages)
    depot = required(r'Depot-Nr\.:\s*(\d+)', text)[1]
    account = 'Baader Depot ' + depot
    batch.account_names = [account]
    batch.pdf_text = text
    is_reversal = bool(re.search(r'\bStorno\b|\bStornierung\b', text, re.I))
    if is_reversal and 'Dividendenabrechnung' not in text:
        raise ValueError('Baader-Stornobeleg muss mit der ursprünglichen Abrechnung abgeglichen werden.')
    if 'Dividendenabrechnung' in text:
        batch.document_type = ('Baader Dividendenabrechnung Storno' if is_reversal
                               else 'Baader Dividendenabrechnung')
        day = parse_baader_income(batch, text, account, is_reversal)
    elif 'Vorabpauschale' in text:
        batch.document_type = 'Baader Vorabpauschale'
        day = parse_baader_advance_tax(batch, text, account)
    elif 'Depoteinlieferung' in text or 'Depotauslieferung' in text:
        batch.document_type = 'Baader Depotein-/auslieferung'
        day = parse_baader_transfer(batch, text, account)
    elif re.search(r'Depotauszug\s+per', text):
        batch.document_type = 'Baader Jahresdepotauszug'
        day = parse_baader_statement(batch, text, account)
    elif 'Quartalsaufstellung' in text:
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
        amount = number(settlement[4]) * (-1 if kind == 'Kauf' else 1)
        tx = BankTransaction(account, 'baader-trade-' + depot + '-' + reference, day,
            'BUY' if kind == 'Kauf' else 'SELL', str(amount), settlement[3],
            security=isin, quantity=str(quantity), value_date=parse_date(settlement[2]) or '',
            fees=str(fees), taxes=str(taxes), gross_amount=str(gross),
            fee_items=[FeeItem('mindermengenzuschlag', str(fees))],
            purpose=nominal[2].strip(), bank_reference=reference, document_reference=reference,
            booking_text=f'Nominale STK {quantity} · Kurs {nominal[3]} {number(nominal[4])} · Kurswert {settlement[3]} {gross}',
            raw_text=nominal[0].strip() + '\n' + f'Kurswert {settlement[3]} {gross}', affects_cash=False)
        batch.transactions.append(tx)
        batch.pdf_booking_evidence.append(dict(page=1, text=nominal[0].strip(), ocr=False, review_required=False))
        batch.warnings.append('Käufe: Nominale und Kurswert als Stückzahl und Einstand; Gebühren und Steuern separat. Verkäufe bauen den Einstand der verkauften Stücke nach FIFO ab. Keine neue Kursbewertung oder Kontobuchung. Bereits im Depotstand enthaltene Stücke werden nicht erneut addiert.')
    batch.documents.append(BankDocument(account, batch.file_hash + ':' + account,
        batch.document_type, day, base64.b64encode(content).decode('ascii')))
    return batch
