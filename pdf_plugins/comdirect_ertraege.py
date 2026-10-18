"""comdirect Wertpapier-Erträge (Dividende, Ausschüttung, Einlösung); user plugin."""
import base64
import re
from decimal import Decimal, ROUND_HALF_UP

from portfolio_v5.models import (BankDocument, BankTransaction, FeeItem, Kind, SecurityInfo,
                                 TaxEvent, TaxItem, correction_number, digest, money, parse_date)
from portfolio_v5.pdf_plugins import Detection

DIVIDEND_KIND = Kind.DIVIDEND      # Dividenden und Fonds-Ausschüttungen
OTHER_KIND = Kind.BANK_BOOKING     # Einlösungen: einfache, nicht klassifizierte Gutschrift
# Hinweis: Die Dividenden-Zusammenführung (settlement.py) erkennt comdirect-Belege an booking_text
# 'comdirect Dividendengutschrift' / 'comdirect Ertragsgutschrift' und setzt income_basis='gross'.

HANDLERS = {
    'dividendengutschrift': dict(title='comdirect Dividendengutschrift', kind=DIVIDEND_KIND,
                                 marker=re.compile(r'Abrechnung\s*Dividendengutschrift')),
    'ertragsgutschrift': dict(title='comdirect Ertragsgutschrift', kind=DIVIDEND_KIND,
                              marker=re.compile(r'Abrechnung\s*Ertragsgutschrift')),
    'einloesung': dict(title='comdirect Einlösung', kind=OTHER_KIND,
                       marker=re.compile(r'Abrechnung\s*Einl[öo]sung')),
}

# Eine Zeile: <IBAN> EUR <Valuta> EUR <Betrag>. Unabhängig von der Zeilenreihenfolge,
# denn pypdf liefert diese Belege teils von unten nach oben, teils ohne Leerzeichen.
SETTLEMENT = re.compile(
    r'(?m)^[ \t]*(?P<iban>DE(?:[ \t]*\d){20})[ \t]+[A-Z]{3}[ \t]+'
    r'(?P<date>\d{2}\.\d{2}\.\d{4})[ \t]+(?P<currency>[A-Z]{3})[ \t]+(?P<amount>[0-9.]+,\d{2})[ \t]*$')
HOLDING = re.compile(r'(?m)^[ \t]*STK[ \t]*(?P<qty>\d[\d.]*(?:,\d+)?)(?P<rest>[^\n]*)$')
PER_LINE = re.compile(r'(?m)^[ \t]*per[ \t]+\d{2}\.\d{2}\.\d{4}[ \t]+(?P<rest>\S[^\n]*)$')
ISIN = re.compile(r'(?<![A-Za-z0-9])[A-Z]{2}[A-Z0-9]{9}\d')
FOREIGN = re.compile(r'(?:Bruttobetrag:|Kurswert\s*Einl[öo]sung)\s*(?P<currency>[A-Z]{3})\s+(?P<amount>[0-9.]+,\d{2})')
PER_SHARE = re.compile(
    r'(?P<c>[A-Z]{3})\s+(?P<r>[0-9.]+,\d+)\s+(?:Dividende|Ausschüttung)\s+pro\s+Stück'
    r'(?:\s+für\s+Geschäftsjahr\s+(?P<a>\d{2}\.\d{2}\.\d{2})\s+bis\s+(?P<b>\d{2}\.\d{2}\.\d{2}))?')
PAY_DATE = re.compile(r'zahlbar\s+ab\s*(?P<d>\d{2}\.\d{2}\.\d{4})')
FX_PAIR = re.compile(r'Devisenkurs:\s*(?P<pair>[A-Z]{3}/[A-Z]{3})\s+(?P<rate>[0-9.]+,\d+)')
DOMICILE = re.compile(r'Emissionsland:\s*(?P<c>[A-ZÄÖÜa-zäöüß][^\n]*?)\s*(?:\n|$)')
AMOUNT = r'[0-9]{1,3}(?:\.[0-9]{3})*,\d{2}|\d+,\d{2}'

# Older comdirect trade confirmations often have broken embedded fonts and are
# extracted without spaces.  These patterns therefore use stable ASCII labels
# and accept both compact and normally spaced text.
TRADE_MARKER = re.compile(r'Wertpapier(?P<type>kauf|verkauf)', re.I)
TRADE_FEE = re.compile(r'Provision\s*:?\s*EUR\s*(?:-\s*)?(?P<a>' + AMOUNT + ')', re.I)
TRADE_LINE = re.compile(
    r'Stk\.\s*(?P<qty>\d[\d.]*(?:,\d+)?)\s*(?P<name>.+?)\s*,?\s*WKN/ISIN\s*:\s*'
    r'(?P<wkn>[A-Z0-9]{6})\s*/\s*(?P<isin>[A-Z]{2}[A-Z0-9]{9}\d)', re.I | re.S)
TRADE_DAY = re.compile(r'Wertpapier(?P<type>kauf|verkauf)\s*Nr\.?\s*(?P<order>\d+)\s*vom\s*(?P<d>\d{2}\.\d{2}\.\d{4})', re.I)
TRADE_SETTLEMENT = re.compile(
    r'Valuta\s*(?P<d>\d{2}\.\d{2}\.\d{4}).{0,80}?IBAN\s*(?P<iban>DE\d{20})|'
    r'Valuta.{0,80}?(?P<iban2>DE\d{20})\s*EUR\s*(?P<d2>\d{2}\.\d{2}\.\d{4})', re.I | re.S)
TRADE_TOTAL = re.compile(r'ZuIhren(?P<direction>Lasten|Gunsten)(?:nach|vor)Steuern\s*:\s*EUR\s*-?\s*(?P<a>' + AMOUNT + ')', re.I)
TRADE_MARKET = re.compile(r'Kurswert\s*:?\s*EUR\s*(?P<a>' + AMOUNT + ')', re.I)
TRADE_EXECUTION = re.compile(
    r'Nennwert\s*Zum\s*Kurs\s*von\s*(?:St\.\s*(?P<qty>\d[\d.]*(?:,\d+)?)\s*)?'
    r'EUR\s*(?P<price>\d[\d.]*(?:,\d+)?)\s*Kurswert\s*:?\s*EUR\s*(?P<market>' + AMOUNT + ')',
    re.I)
TRADE_DEPOT = re.compile(r'Depot(?:nummer|nr\.)\s*:?\s*(?P<n>\d+)', re.I)
TRADE_REFERENCE = re.compile(r'Referenz-Nummer\s*:\s*(?P<r>[A-Z0-9]+)', re.I)
TRADE_TAX_TOTAL = re.compile(r'abgef.hrteSteuern\s*:?\s*EUR\s*-?\s*(?P<a>' + AMOUNT + ')', re.I)
TRADE_TAX_ITEMS = {
    'kapitalertragsteuer': re.compile(r'Kapitalertragsteuer\s*:?\s*EUR\s*-?\s*(?P<a>' + AMOUNT + ')', re.I),
    'solidaritaetszuschlag': re.compile(r'Solidarit.tszuschlag\s*:?\s*EUR\s*-?\s*(?P<a>' + AMOUNT + ')', re.I),
    'kirchensteuer': re.compile(r'Kirchensteuer\s*:?\s*EUR\s*-?\s*(?P<a>' + AMOUNT + ')', re.I),
}

# Kurs und Stückzahl werden auf den ausgewiesenen Kurswert in Cent gerundet.
# Ein Cent Toleranz deckt ausschließlich Differenzen der gedruckten Kurspräzision ab;
# größere Abweichungen werden als widersprüchliche Abrechnung abgewiesen.
TRADE_VALUE_TOLERANCE = Decimal('0.01')


def _trade_value_difference(qty, price, market):
    calculated = (Decimal(qty) * Decimal(price)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    return calculated, abs(calculated - Decimal(market))


def _trade_quantity(document, tax_security):
    """Primär Geschäftsabrechnung, sekundär nur eine positive steuerliche Stk.-Angabe."""
    executions = []
    for page in document.pages:
        compact = re.sub(r'[ \t]+', '', page.text)
        match = TRADE_EXECUTION.search(compact)
        if match:
            executions.append((page.number, match))
    if len(executions) > 1:
        raise ValueError('Mehrere Geschäftsabrechnungen mit Nennwert, Kurs und Kurswert erkannt.')

    tax_qty = correction_number(tax_security.group('qty')) if tax_security else None
    tax_qty = tax_qty if tax_qty is not None and Decimal(tax_qty) > 0 else None
    if executions:
        page_number, execution = executions[0]
        primary_qty = correction_number(execution.group('qty')) if execution.group('qty') else None
        price = correction_number(execution.group('price'))
        market = money(execution.group('market'))
        if primary_qty is not None and Decimal(primary_qty) <= 0:
            primary_qty = None
        if primary_qty is not None and tax_qty is not None and Decimal(tax_qty) != Decimal(primary_qty):
            raise ValueError(
                f'Stückzahlangaben widersprüchlich: Geschäftsabrechnung {primary_qty} Stück, '
                f'steuerliche Mitteilung {tax_qty} Stück.')
        qty = primary_qty or tax_qty
        if qty is None:
            raise ValueError('Stückzahl fehlt sowohl in der Geschäftsabrechnung als auch als positive Angabe '
                             'in der steuerlichen Mitteilung; Dokument nicht automatisch verbucht.')
        if price is None or market is None:
            raise ValueError(f'Ungültige Kurs- oder Kurswertangabe auf der Geschäftsabrechnung (Seite {page_number}).')
        calculated, difference = _trade_value_difference(qty, price, market)
        if difference > TRADE_VALUE_TOLERANCE:
            raise ValueError(
                f'Geschäftsabrechnung widersprüchlich: {qty} Stück × {price} EUR ergeben '
                f'{calculated:.2f} EUR, ausgewiesen sind {Decimal(market):.2f} EUR '
                f'(Toleranz {TRADE_VALUE_TOLERANCE:.2f} EUR).')
        source = ('comdirect Geschäftsabrechnung · Nennwert/Zum Kurs von' if primary_qty is not None
                  else 'comdirect steuerliche Mitteilung · Stk. (sekundär, gegen Geschäftsabrechnung geprüft)')
        return qty, price, market, page_number, source

    if tax_qty is None:
        raise ValueError('Stückzahl fehlt sowohl in der Geschäftsabrechnung als auch als positive Angabe '
                         'in der steuerlichen Mitteilung; Dokument nicht automatisch verbucht.')
    raise ValueError(f'Steuerliche Stückzahl {tax_qty} ist vorhanden, kann aber ohne Kurs und Kurswert '
                     'der Geschäftsabrechnung nicht plausibilisiert werden; Dokument nicht automatisch verbucht.')


def short_date(value):
    """'01.07.18' -> '2018-07-01' (zweistelliges Jahr; Belege ab 2000)."""
    if not value:
        return ''
    day, month, year = value.split('.')
    return f'{2000 + int(year):04d}-{month}-{day}'
# Rückfall bei defekter Schriftkodierung: nur der Name hinter dem Spaltenabstand ist lesbar.
NAME_AFTER_GAP = {
    'per': re.compile(r'(?m)^per[^\n]*?[ \t]{3,}(\S[^\n]*?)[ \t]*$'),
    'stk': re.compile(r'(?m)^STK[^\n]*?[ \t]{3,}(\S[^\n]*?)[ \t]*$'),
}

OCR_MIN_CONFIDENCE = 0.90   # je Textfeld (der Seitenwert ist der kleinste Einzelwert und zu grob)
QTY_TOKEN = re.compile(r'(?<![\d.,])\d[\d.]*,\d+(?![\d,])')
RATE = (re.compile(r'Einl[öo]sung\s+zum\s+Kurs\s+von\s+(?P<r>[0-9.]+,\d+)\s+[A-Z]{3}'),
        re.compile(r'[A-Z]{3}\s+(?P<r>[0-9.]+,\d+)\s+(?:Dividende|Ausschüttung)\s+pro\s+Stück'))
BASE = (re.compile(r'Kurswert\s*Einl[öo]sung\s+[A-Z]{3}\s+(?P<a>' + AMOUNT + ')'),
        re.compile(r'Bruttobetrag:\s*[A-Z]{3}\s+(?P<a>' + AMOUNT + ')'))

ADVANCE_TAX_TITLE = re.compile(
    r'Steuerliche\s+Behandlung:\s*Vorabpauschale\s+Ausland\s+vom\s+(?P<date>\d{2}\.\d{2}\.\d{4})', re.I)
ADVANCE_TAX_SECURITY = re.compile(
    r'Stk\.\s*(?P<qty>\d[\d.]*(?:,\d+)?)\s+(?P<name>.+?)\s*,\s*WKN\s*/\s*ISIN:\s*'
    r'(?P<wkn>[A-Z0-9]{6})\s*/\s*(?P<isin>[A-Z]{2}[A-Z0-9]{9}\d)', re.I)
ADVANCE_TAX_BASE = re.compile(r'Vorabpauschale\s+EUR\s+(?P<a>' + AMOUNT + r')', re.I)
ADVANCE_TAX_PARTIAL = re.compile(
    r'Teilfreistellung\s*\((?P<rate>[\d,.]+)%\)\s+EUR\s*-\s*(?P<a>' + AMOUNT + r')', re.I)
ADVANCE_TAX_TAXABLE = re.compile(
    r'Steuerbemessungsgrundlage\s+vor\s+Verlustverrechnung(?:\s*\(\d+\))?\s+EUR\s+(?P<a>' + AMOUNT + r')', re.I)
ADVANCE_TAX_USED = re.compile(
    r'in\s+Anspruch\s+genommener\s+Freistellungsauftrag\s+EUR\s+(?P<a>' + AMOUNT + r')', re.I)
ADVANCE_TAX_DEPOT = re.compile(r'Depotnummer:\s*(?P<n>\d+(?:\s+\d+)?)', re.I)
ADVANCE_TAX_REFERENCE = re.compile(r'Referenz-Nummer:\s*(?P<r>[A-Z0-9\s]+?)(?=Depotnummer:|\n\s*\n)', re.I)


def ocr_holding(document, page, options):
    """Ergänzt ISIN und Stückzahl per lokaler OCR (portfolio_v5.pdf_ocr), nur bei Bedarf.
    Rückgabe: (gefundene Felder, OCR-Text, Hinweis). Nur Felder mit ausreichendem Vertrauen."""
    if not options.get('allow_ocr', True):
        return {}, '', 'OCR ist ausgeschaltet; fehlende Felder bleiben offen.'
    try:
        from portfolio_v5.pdf_ocr import ocr_page, ocr_page_regions
        ocr_text, _ = ocr_page(document.path, page.number - 1)
        regions = ocr_page_regions(document.path, page.number - 1)
    except Exception as error:   # OCR-Pakete fehlen, PDF nicht lesbar o. ä.
        return {}, '', f'OCR-Ergänzung nicht möglich: {error}'

    def confidence(token):
        return max((r['confidence'] for r in regions if token in r['text']), default=0.0)

    found = {}
    line = re.search(r'(?m)^[ \t]*STK\b(?P<rest>[^\n]*)$', ocr_text)
    if line:
        isin, qty = ISIN.search(line.group('rest')), QTY_TOKEN.search(line.group('rest'))
        if isin and confidence(isin.group()) >= OCR_MIN_CONFIDENCE:
            found['isin'] = (isin.group(), confidence(isin.group()))
        if qty and confidence(qty.group()) >= OCR_MIN_CONFIDENCE:
            found['qty'] = (correction_number(qty.group()), confidence(qty.group()))
    return found, ocr_text, None


def plausible(qty, text):
    """Stückzahl × Satz pro Stück ≈ Brutto/Kurswert. True/False, None wenn nicht prüfbar."""
    rate = next((m for m in (r.search(text) for r in RATE) if m), None)
    base = next((m for m in (b.search(text) for b in BASE) if m), None)
    if not (rate and base):
        return None
    expected = float(correction_number(rate.group('r'))) * float(qty)
    return abs(expected - float(money(base.group('a')))) <= 0.01


def split_name_wkn(rest):
    """Die WKN steht je nach Textextraktion vor oder hinter dem Namen, ggf. ohne Leerzeichen."""
    rest = ' '.join(rest.split())

    def is_wkn(token):
        return bool(re.fullmatch(r'[A-Z0-9]{6}', token)) and any(c.isdigit() for c in token)

    parts = rest.split()
    if parts and is_wkn(parts[-1]):
        return ' '.join(parts[:-1]), parts[-1]
    if parts and is_wkn(parts[0]):
        return ' '.join(parts[1:]), parts[0]
    glued = re.match(r'([A-Z0-9]{6})(?=[A-Za-z])(.+)$', rest)
    if glued and any(c.isdigit() for c in glued.group(1)):
        return glued.group(2).strip(), glued.group(1)
    return rest, ''


class ComdirectErtraegePlugin:
    plugin_id = 'user.comdirect-ertraege'
    bank_name = 'comdirect'
    version = '1.2'
    document_types = ('Dividendengutschrift, Ertragsgutschrift, Einlösung, Wertpapierabrechnung Kauf/Verkauf, '
                      'Steuermitteilung Vorabpauschale')

    def detect(self, document):
        text = document.text
        if not re.search(r'comdirect', text, re.I):
            return []
        result = []
        if ADVANCE_TAX_TITLE.search(text) and ADVANCE_TAX_SECURITY.search(text):
            result.append(Detection(0.99, 'comdirect Steuermitteilung Vorabpauschale', 'vorabpauschale',
                                    'comdirect, Vorabpauschale und Wertpapierkennung erkannt'))
        trade_marker = TRADE_MARKER.search(text)
        compact = re.sub(r'[ \t]+', '', text)
        if trade_marker and TRADE_TOTAL.search(compact) and TRADE_MARKET.search(compact):
            trade_type = trade_marker.group('type').lower()
            result.append(Detection(0.97, 'comdirect Wertpapierabrechnung ' + trade_type.title(),
                                    'wertpapier' + trade_type,
                                    'comdirect, Wertpapier' + trade_type + ' und Provision erkannt'))
        if not SETTLEMENT.search(text):
            return result
        result.extend(Detection(0.95, handler['title'], handler_id,
                          'comdirect, Wertpapier-Abrechnung und Dokumenttyp erkannt')
                for handler_id, handler in HANDLERS.items() if handler['marker'].search(text))
        return result

    def parse(self, document, detection, context):
        if detection.handler_id == 'vorabpauschale':
            return self._advance_tax(document, context.batch)
        if detection.handler_id in ('wertpapierkauf', 'wertpapierverkauf'):
            return self._trade(document, context.batch)
        handler = HANDLERS.get(detection.handler_id)
        if handler is None:
            raise ValueError('Nicht unterstützter Dokumenttyp: ' + detection.handler_id)
        batch = context.batch
        text = document.text

        located = [(page, match) for page in document.pages for match in SETTLEMENT.finditer(page.text)]
        if len(located) != 1:
            raise ValueError('Genau eine Gutschrift pro PDF erwartet, gefunden: %d.' % len(located))
        page, settle = located[0]
        account = 'IBAN ' + re.sub(r'\s+', '', settle.group('iban'))

        holding, per_line = HOLDING.search(text), PER_LINE.search(text)
        isin_match = ISIN.search(holding.group('rest')) if holding else None
        isin = isin_match.group() if isin_match else None
        qty = correction_number(holding.group('qty')) if holding else None
        native_isin, native_qty = isin, qty        # nur diese gehen in die stabile external_id
        from_ocr, ocr_confidence = [], None
        if isin is None or qty is None:
            found, ocr_text, problem = ocr_holding(document, page, context.options)
            if problem:
                batch.warnings.append(problem)
            if isin is None and 'isin' in found:
                isin, ocr_confidence = found['isin'][0], found['isin'][1]
                from_ocr.append('ISIN')
            if qty is None and 'qty' in found:
                if plausible(found['qty'][0], text + '\n' + ocr_text) is False:
                    batch.warnings.append('OCR-Stückzahl %s passt nicht zum Betrag und wurde verworfen.' % found['qty'][0])
                else:
                    qty = found['qty'][0]
                    ocr_confidence = min(ocr_confidence or 1.0, found['qty'][1])
                    from_ocr.append('Stückzahl')
        if per_line:
            name, wkn = split_name_wkn(per_line.group('rest'))
        else:
            names = [m.group(1) for key in ('per', 'stk') for m in [NAME_AFTER_GAP[key].search(text)] if m]
            name, wkn = ' '.join(' '.join(names).split()), ''
        missing = [label for label, value in (('ISIN', isin), ('Stückzahl', qty)) if value is None]
        if missing and handler['kind'] == DIVIDEND_KIND:
            raise ValueError(' und '.join(missing) + ' im PDF nicht lesbar (defekte Schriftkodierung?) und per OCR '
                             'nicht sicher erkannt. Bitte Buchung manuell erfassen.')

        booked = parse_date(settle.group('date'))
        amount = money(settle.group('amount'))
        if not booked or amount is None:
            raise ValueError('Datum oder Betrag ungültig.')
        reference = re.search(
            r'(?:Referenz(?:-Nr\.)?|Vorgangs(?:nummer|-Nr\.)?)\s*:?\s*([A-Z0-9][A-Z0-9 /._-]*)',
            text, re.I)
        reference = ' '.join(reference.group(1).split()) if reference else ''

        purpose = f"{handler['title']}: {name}".rstrip(': ')
        purpose += (f" ({isin}" + (f', WKN {wkn}' if wkn else '') + ')') if isin else ' (Wertpapier-ID nicht lesbar)'
        purpose += f' {qty} Stk.' if qty is not None else ' (Stückzahl nicht lesbar)'
        foreign = FOREIGN.search(text)
        if foreign and foreign.group('currency') != settle.group('currency'):
            purpose += f" · {foreign.group('amount')} {foreign.group('currency')} umgerechnet"

        row = page.text[:settle.start()].count('\n') + 1
        source_line = ' '.join(settle.group().split())
        external_id = 'pdf-income-' + digest(
            [account, detection.handler_id, native_isin or name, booked, amount, native_qty, reference])

        # Zusatzfelder nach dem erweiterten Modell
        gross_basis = handler['kind'] == DIVIDEND_KIND          # comdirect weist den Betrag vor Steuern aus
        per_share = PER_SHARE.search(text)
        pay = PAY_DATE.search(text)
        fx = FX_PAIR.search(text)
        original_amount = original_currency = fx_rate = None
        if foreign and foreign.group('currency') != settle.group('currency') and fx:
            original_amount, original_currency = money(foreign.group('amount')), foreign.group('currency')
            fx_rate = correction_number(fx.group('rate'))
        sources = {}
        if 'ISIN' in from_ocr:
            sources['security'] = f'ocr:{ocr_confidence:.2f}'
        if 'Stückzahl' in from_ocr:
            sources['quantity'] = f'ocr:{ocr_confidence:.2f}'
        if page.used_ocr:
            sources.update({name: 'ocr' for name in ('amount', 'date')})

        batch.transactions.append(BankTransaction(
            account=account, external_id=external_id, date=booked, kind=handler['kind'],
            amount=amount, currency=settle.group('currency'),
            security=isin or '', quantity=qty, row=row,
            value_date=booked, purpose=purpose, bank_reference=reference,
            document_reference=reference,
            booking_text=handler['title'], raw_text=source_line,
            gross_amount=amount, original_amount=original_amount, original_currency=original_currency or '',
            fx_rate=fx_rate, security_ref=isin or '', income_basis='gross' if gross_basis else 'net',
            pay_date=parse_date(pay.group('d')) if pay else (booked if gross_basis else ''),
            per_share_amount=correction_number(per_share.group('r')) if per_share else None,
            per_share_currency=per_share.group('c') if per_share else '',
            fiscal_period_start=short_date(per_share.group('a')) if per_share else '',
            fiscal_period_end=short_date(per_share.group('b')) if per_share else '',
            field_sources=sources))
        if isin:
            domicile = DOMICILE.search(text)
            batch.securities.append(SecurityInfo(
                key=isin, isin=isin, wkn=wkn, name=name,
                domicile=domicile.group('c').title() if domicile else '',
                quote_currency=original_currency or settle.group('currency')))
        review = page.used_ocr or bool(from_ocr) or bool(missing)
        batch.pdf_booking_evidence.append({
            'page': page.number, 'line': row, 'text': source_line,
            'ocr': page.used_ocr or bool(from_ocr), 'review_required': review,
            'confidence': ocr_confidence if from_ocr else page.confidence})

        document_date = re.search(r'(?m)^[ \t]*(\d{2}\.\d{2}\.\d{4})[ \t]*$', text)
        batch.documents.append(BankDocument(
            account, batch.file_hash + ':' + account, document.path.name,
            parse_date(document_date.group(1)) if document_date else booked,
            base64.b64encode(document.content).decode('ascii')))

        batch.warnings.append('Betrag ist die Gutschrift vor Steuern; Steuerabzug steht in der separaten Steuermitteilung.')
        if from_ocr:
            batch.warnings.append(' und '.join(from_ocr) + ' per OCR ergänzt (defekte Schrift im PDF); '
                                  'bitte am Original prüfen.')
        if missing:
            batch.warnings.append(' und '.join(missing) + (' ist' if len(missing) == 1 else ' sind')
                                  + ' in diesem PDF nicht lesbar; übrige Felder wurden übernommen. Bitte am Original prüfen.')
        if page.used_ocr:
            batch.warnings.append('Seite per OCR gelesen; Betrag, Stückzahl und ISIN bitte am Original prüfen.')
        return batch

    def _advance_tax(self, document, batch):
        text = document.text
        title, security = ADVANCE_TAX_TITLE.search(text), ADVANCE_TAX_SECURITY.search(text)
        base, partial = ADVANCE_TAX_BASE.search(text), ADVANCE_TAX_PARTIAL.search(text)
        taxable, used = ADVANCE_TAX_TAXABLE.search(text), ADVANCE_TAX_USED.search(text)
        if not all((title, security, base, partial, taxable, used)):
            raise ValueError('Vorabpauschale, Teilfreistellung, Steuerbemessungsgrundlage oder Freistellungsnutzung nicht erkannt.')
        treatment_date = parse_date(title.group('date'))
        values = {name: money(match.group('a')) for name, match in
                  (('base', base), ('partial', partial), ('taxable', taxable), ('used', used))}
        if not treatment_date or any(value is None for value in values.values()):
            raise ValueError('Datum oder Steuerbetrag der Vorabpauschale ist ungültig.')
        if abs(Decimal(values['base']) - Decimal(values['partial']) - Decimal(values['taxable'])) > Decimal('0.01'):
            raise ValueError('Vorabpauschale minus Teilfreistellung passt nicht zur Steuerbemessungsgrundlage.')
        if Decimal(values['used']) > Decimal(values['taxable']):
            raise ValueError('Der verbrauchte Freistellungsauftrag übersteigt die Steuerbemessungsgrundlage.')

        isin, wkn = security.group('isin').upper(), security.group('wkn').upper()
        qty = correction_number(security.group('qty'))
        name = ' '.join(security.group('name').split())
        depot_match = ADVANCE_TAX_DEPOT.search(text)
        depot_number = re.sub(r'\s+', '', depot_match.group('n')) if depot_match else ''
        account = 'Depot ' + depot_number if depot_number else 'comdirect Depot'
        reference_match = ADVANCE_TAX_REFERENCE.search(text)
        reference = re.sub(r'\s+', '', reference_match.group('r')) if reference_match else ''
        external_id = 'pdf-comdirect-advance-tax-' + digest(
            [account, isin, treatment_date, values['base'], values['taxable'], reference])
        batch.tax_events.append(TaxEvent(
            external_id=external_id, account=account, type='vorabpauschale_ausland',
            date=treatment_date, tax_year=treatment_date[:4], security_ref=isin, quantity=qty,
            currency='EUR', taxable_income=values['taxable'], advance_tax_base=values['base'],
            partial_exemption_amount=values['partial'], used_exemption=values['used'],
            after_partial_exemption=values['taxable'],
            partial_exemption_rate=correction_number(partial.group('rate')),
            reference_no=reference))
        batch.securities.append(SecurityInfo(key=isin, isin=isin, wkn=wkn, name=name))
        document_date = re.search(r'Datum:\s*(\d{2}\.\d{2}\.\d{4})', text, re.I)
        batch.documents.append(BankDocument(
            account, batch.file_hash + ':' + account, document.path.name,
            parse_date(document_date.group(1)) if document_date else treatment_date,
            base64.b64encode(document.content).decode('ascii'),
            document_type='Steuermitteilung Vorabpauschale', bank_name='comdirect',
            document_no=reference, page_count=len(document.pages), extraction_method='PDF-Text'))
        batch.account_names.append(account)
        batch.warnings.append(
            f"Vorabpauschale {values['base']} EUR erkannt; nach {partial.group('rate')} % Teilfreistellung "
            f"wurden {values['used']} EUR Freistellungsauftrag verbraucht. Keine Kontobuchung erzeugt.")
        return batch

    def _trade(self, document, batch):
        text = document.text
        compact = re.sub(r'[ \t]+', '', text)
        fee = TRADE_FEE.search(compact)
        security = TRADE_LINE.search(text) or TRADE_LINE.search(compact)
        trade = TRADE_DAY.search(compact)
        settlement = TRADE_SETTLEMENT.search(compact)
        total = TRADE_TOTAL.search(compact)
        depot = TRADE_DEPOT.search(compact)
        if not all((security, trade, settlement, total, depot)):
            raise ValueError('Wertpapier, Geschäftstag, Valuta, IBAN oder Endbetrag nicht erkannt.')
        kind = Kind.BUY if trade.group('type').lower() == 'kauf' else Kind.SELL
        expected_direction = 'Lasten' if kind == Kind.BUY else 'Gunsten'
        if total.group('direction').lower() != expected_direction.lower():
            raise ValueError(f'Wirtschaftliche Zahlungsrichtung widerspricht {kind}: '
                             f"Zu Ihren {total.group('direction')} statt zu Ihren {expected_direction}.")
        valuta = parse_date(settlement.group('d') or settlement.group('d2'))
        iban = settlement.group('iban') or settlement.group('iban2')
        trade_day = parse_date(trade.group('d'))
        qty, price, execution_market, execution_page, quantity_source = _trade_quantity(document, security)
        amount = money(total.group('a'))
        if not all((valuta, trade_day, qty, amount)):
            raise ValueError('Betrag, Provision, Stückzahl oder Datum ungültig.')
        cash_account = 'IBAN ' + iban
        isin, wkn = security.group('isin').upper(), security.group('wkn').upper()
        name = ' '.join(security.group('name').split())
        reference = (TRADE_REFERENCE.search(compact).group('r')
                     if TRADE_REFERENCE.search(compact) else trade.group('order'))
        account = 'Depot ' + depot.group('n')
        market = TRADE_MARKET.search(compact)
        gross = execution_market or (money(market.group('a')) if market else None)
        tax_total_match = TRADE_TAX_TOTAL.search(compact)
        taxes = money(tax_total_match.group('a')) if tax_total_match else '0.00'
        tax_items = [TaxItem(name, money(match.group('a'))) for name, pattern in TRADE_TAX_ITEMS.items()
                     for match in [pattern.search(compact)] if match and Decimal(money(match.group('a'))) != 0]
        documented_tax_total = sum((Decimal(item.amount) for item in tax_items), Decimal())
        if tax_items and abs(documented_tax_total - Decimal(taxes)) > Decimal('0.01'):
            raise ValueError('Steuerkomponenten passen nicht zur ausgewiesenen Steuersumme.')
        if fee:
            provision = money(fee.group('a'))
        elif gross is not None:
            provision_value = ((Decimal(amount) - Decimal(gross) - Decimal(taxes)) if kind == Kind.BUY
                               else (Decimal(gross) - Decimal(taxes) - Decimal(amount)))
            if provision_value < Decimal('-0.01'):
                raise ValueError('Kurswert, Steuern und Endbetrag widersprechen der Zahlungsrichtung.')
            provision = money(max(provision_value, Decimal()))
        else:
            provision = None
        expected_total = (Decimal(gross) + Decimal(provision) if kind == Kind.BUY
                          else Decimal(gross) - Decimal(provision)) if gross is not None and provision is not None else None
        if expected_total is not None:
            expected_total = (expected_total + Decimal(taxes) if kind == Kind.BUY
                              else expected_total - Decimal(taxes))
        if expected_total is not None and abs(expected_total - Decimal(amount)) > Decimal('0.01'):
            batch.warnings.append('Kurswert, Provision und Endbetrag stimmen nicht überein; Abrechnung bitte prüfen.')
        booking_text = f'{name}\nWPKNR: {wkn} ISIN: {isin}'
        purpose = f'Wertpapiere · {name} · WPKNR: {wkn} ISIN: {isin}'
        if provision and Decimal(provision):
            purpose += f' · Provision {provision} EUR'
        # Keep the historical BUY identity stable across the model correction
        # from cash booking to depot event; otherwise a re-import after upgrade
        # could create a second economic transaction.
        external_id = 'pdf-comdirect-trade-' + digest(
            [cash_account, trade.group('order'), isin, trade_day, valuta, amount])
        batch.transactions.append(BankTransaction(
            account=account, external_id=external_id, date=trade_day, value_date=valuta,
            kind=kind, amount=('-' if kind == Kind.BUY else '') + amount, currency='EUR', security=isin,
            quantity=qty, fees=provision if provision and Decimal(provision) else None,
            taxes=taxes if Decimal(taxes) else None,
            fee_items=[FeeItem('provision', provision)] if provision and Decimal(provision) else [],
            tax_items=tax_items,
            gross_amount=gross, price=price, trade_date=trade_day, pay_date=valuta,
            cash_account=cash_account, depot_account=account, affects_cash=False,
            security_ref=isin, order_id=trade.group('order'), document_reference=reference,
            transaction_reference=reference, operation='Wertpapiere', booking_text=booking_text,
            purpose=purpose, raw_text=purpose,
            field_sources={'fees': 'comdirect Wertpapierabrechnung · Provision',
                           'quantity': quantity_source,
                           **({'price': 'comdirect Geschäftsabrechnung · Zum Kurs von'} if price else {}),
                           'security': 'comdirect Wertpapierabrechnung · WKN/ISIN',
                           'value_date': 'comdirect Wertpapierabrechnung · Valuta'}))
        batch.securities.append(SecurityInfo(key=isin, isin=isin, wkn=wkn, name=name, quote_currency='EUR'))
        page = (next((p for p in document.pages if p.number == execution_page), None) if execution_page else None)
        page = page or next((p for p in document.pages if TRADE_TOTAL.search(re.sub(r'[ \t]+', '', p.text))), document.pages[0])
        batch.pdf_booking_evidence.append({'page': page.number, 'line': 1, 'text': purpose,
            'ocr': page.used_ocr, 'confidence': page.confidence, 'review_required': page.used_ocr})
        batch.documents.append(BankDocument(
            account, batch.file_hash + ':' + account, document.path.name, trade_day,
            base64.b64encode(document.content).decode('ascii'), document_type='Wertpapierabrechnung ' + kind.title(),
            bank_name='comdirect', document_no=reference, page_count=len(document.pages),
            extraction_method='OCR' if page.used_ocr else 'PDF-Text', linked_ids=[external_id]))
        batch.account_names.extend([account, cash_account])
        batch.warnings.append(
            f'Gebühren {provision or "nicht ausgewiesen"} EUR; Zuordnung über Valuta, Betrag und WKN/ISIN.')
        return batch


plugin = ComdirectErtraegePlugin()
