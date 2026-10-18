"""ING (ING-DiBa): Dividendengutschrift, Kauf (Sparplan, Wiederanlage), Jahresdepotauszug; user plugin."""
import base64
import re

from decimal import Decimal, ROUND_HALF_UP

from portfolio_v5.models import (BankDocument, BankTransaction, FeeItem, Kind, Position, SecurityInfo,
                                 Snapshot, TaxEvent, TaxItem, Transaction,
                                 correction_number, digest, money, parse_date)
from portfolio_v5.pdf_plugins import Detection
from portfolio_v5.booking_details import extract_bank_reference

DIVIDEND_KIND = Kind.DIVIDEND
BUY_KIND = Kind.BUY
BUY_AMOUNT_SIGN = -1         # ANNAHME: Kauf = Mittelabfluss, Betrag negativ
ASSET_TYPE = 'Sonstiges'     # ANNAHME: im Jahresdepotauszug steht keine Anlageklasse

DATE = r'\d{2}\.\d{2}\.\d{4}'
AMOUNT = r'[0-9]{1,3}(?:\.[0-9]{3})*,\d{2}|\d+,\d{2}'
QTY = r'\d[\d.]*(?:,\d+)?'

DIVIDEND_TITLE = re.compile(r'(?m)^[ \t]*Dividendengutschrift[ \t]*$')
DIVIDEND_TOTAL = re.compile(r'Gesamtbetrag\s+zu\s+Ihren\s+Gunsten\s+(?P<currency>[A-Z]{3})\s+(?P<amount>' + AMOUNT + ')')
BUY_TITLE = re.compile(r'Wertpapierabrechnung[ \t]+(?P<type>Kauf[^\n]*?)[ \t]*\n')
BUY_TOTAL = re.compile(r'Endbetrag\s+zu\s+Ihren\s+Lasten\s+(?P<currency>[A-Z]{3})\s+(?P<amount>' + AMOUNT + ')')
SELL_TITLE = re.compile(r'Wertpapierabrechnung[ \t]+(?P<type>Verkauf[^\n]*?)[ \t]*\n')
SELL_TOTAL = re.compile(r'Endbetrag\s+zu\s+Ihren\s+Gunsten\s+(?P<currency>[A-Z]{3})\s+(?P<amount>' + AMOUNT + ')')

SECURITY = re.compile(r'ISIN\s*\(WKN\)\s+(?P<isin>[A-Z]{2}[A-Z0-9]{9}\d)\s*\((?P<wkn>[A-Z0-9]{6})\)')
NAME = re.compile(r'Wertpapierbezeichnung\s+(?P<name>.+?)\s*(?=Nominale)', re.S)
NOMINAL_DIV = re.compile(r'Nominale\s+(?P<qty>' + QTY + r')\s+St\u00fcck')
NOMINAL_BUY = re.compile(r'Nominale\s+St\u00fcck\s+(?P<qty>' + QTY + ')')
VALUTA = re.compile(r'Valuta\s+(?P<date>' + DATE + ')')
IBAN = re.compile(r'Abrechnungs-IBAN\s+(?P<iban>DE(?:[ \t]*\d){20})')
DEPOT = re.compile(r'Direkt-Depot\s*Nr\.:\s*(?P<id>\d+)')
LETTER_DATE = re.compile(r'Datum:\s*(?P<date>' + DATE + ')')
GROSS = re.compile(r'Brutto\s+(?P<currency>[A-Z]{3})\s+(?P<amount>' + AMOUNT + ')')
WITHHOLDING = re.compile(
    r'QuSt\s+(?P<rate>[\d,]+)\s*%\s*\(EUR\s+(?P<eur>' + AMOUNT + r')\)\s+(?P<currency>[A-Z]{3})\s+(?P<amount>' + AMOUNT + ')')
SUBTOTAL = re.compile(r'Zwischensumme\s+(?P<currency>[A-Z]{3})\s+(?P<amount>' + AMOUNT + ')')
FX_RATE = re.compile(r'Umg\.\s*z\.\s*Dev\.-Kurs\s*\((?P<rate>[0-9.,]+)\)')
EX_DAY = re.compile(r'Ex-Tag\s+(?P<d>' + DATE + ')')
PAY_DAY = re.compile(r'Zahltag\s+(?P<d>' + DATE + ')')
RATE = re.compile(r'Zins-/Dividendensatz\s+(?P<r>[0-9.]+,\d+)\s+(?P<c>[A-Z]{3})')
VENUE = re.compile(r'Handelsplatz\s+(?P<v>\S[^\n]*?)\s*(?:\n|$)')
PROVISION = re.compile(r'Provision\s+EUR\s+(?P<amount>' + AMOUNT + ')')
# Steuerdaten auf der Rückseite der Dividendenabrechnung
TAX_PAGE = {
    'taxable_income': re.compile(r'KapSt-pflichtiger\s+Kapitalertrag\s+(?P<a>' + AMOUNT + r')\s+EUR'),
    'creditable_withholding': re.compile(r'Anrechenbare\s+ausländische\s+Quellensteuer\s+(?P<a>' + AMOUNT + r')\s+EUR'),
    'allowance_before': re.compile(r'Sparer-Pauschbetrag\s+vor\s+Ertrag\s+(?P<a>' + AMOUNT + r')\s+EUR'),
    'allowance_after': re.compile(r'Sparer-Pauschbetrag\s+nach\s+Ertrag\s+(?P<a>' + AMOUNT + r')\s+EUR'),
    'withholding_pot_before': re.compile(r'Verrechnungstopf\s+ausländ\.\s+Quellenst\.\s+vor\s+Ertrag\s+(?P<a>' + AMOUNT + r')\s+EUR'),
    'withholding_pot_after': re.compile(r'Verrechnungstopf\s+ausländ\.\s+Quellenst\.\s+nach\s+Ertrag\s+(?P<a>' + AMOUNT + r')\s+EUR'),
}
REINVEST = re.compile(r'automatisch\s+wieder\s+an')
ORDER = re.compile(r'Ordernummer\s+(?P<order>[0-9.]+)')
EXECUTION = re.compile(r'Ausführungstag\s*/\s*-zeit\s+(?P<date>' + DATE + r')\s+um\s+(?P<time>\d{2}:\d{2}:\d{2})')
EXECUTION_DAY = re.compile(r'Ausführungstag(?:\s*/\s*-zeit)?\s+(?P<date>' + DATE + r')(?:\s+um\s+(?P<time>\d{2}:\d{2}:\d{2}))?')
MARKET_VALUE = re.compile(r'Kurswert\s+(?P<currency>[A-Z]{3})\s+(?P<amount>' + AMOUNT + ')')
PRICE = re.compile(r'\bKurs(?:[ \t]*\([^)\n]*\))?\s+(?P<currency>[A-Z]{3})\s+(?P<amount>' + AMOUNT + ')')

STATEMENT_TITLE = re.compile(r'(?m)^[ \t]*Jahresdepotauszug[ \t]*$')
STATEMENT_DATE = re.compile(r'zum\s+(?P<date>' + DATE + r')\s+abgeschlossene\s+Aufstellung')
STATEMENT_ROW = re.compile(
    r'^[ \t]*(?P<qty>' + QTY + r')[ \t]+Stück[ \t]+(?P<name>\S.*?)[ \t]+(?P<price>[0-9.]+,\d+)[ \t]+[A-Z]{3}'
    r'[ \t]+(?P<value>' + AMOUNT + r')[ \t]+EUR[ \t]*$')
STATEMENT_ISIN = re.compile(r'ISIN\s*\(WKN\):\s*(?P<isin>[A-Z]{2}[A-Z0-9]{9}\d)\s*\((?P<wkn>[A-Z0-9]{6})\)')
CARRY = re.compile(r'Übertrag\s+Kurswert\s+(?P<amount>' + AMOUNT + r')\s+EUR')
GRAND_TOTAL = re.compile(r'Gesamtkurswert\s+(?P<amount>' + AMOUNT + r')\s+EUR')
POSITION_COUNT = re.compile(r'Anzahl\s+Posten:\s*(?P<count>\d+)')
CUSTODY = re.compile(r'^[ \t]*(?P<label>Verwahrart|Lagerland):\s*(?P<value>\S.*?)[ \t]*$')

ADVANCE_TITLE = re.compile(r'(?m)^[ \t]*Vorabpauschale[ \t]*$')
ADVANCE_TOTAL = re.compile(r'Gesamtbetrag\s+zu\s+Ihren\s+Lasten\s+(?P<currency>[A-Z]{3})\s*-?\s*(?P<amount>' + AMOUNT + ')')
ADVANCE_PER_UNIT = re.compile(r'Vorabpauschale\s+pro\s+Stück\s+(?P<currency>[A-Z]{3})\s+(?P<amount>[0-9.]+,\d+)')
ADVANCE_TAXABLE = re.compile(r'KapSt-pflichtiger\s+Kapitalertrag\s+(?P<amount>' + AMOUNT + r')\s+EUR')
ADVANCE_PARTIAL = re.compile(r'Teilfreistellung[^\n]*?(?P<amount>' + AMOUNT + r')\s+EUR')
TAX_COMPONENTS = {
    'kapitalertragsteuer': re.compile(r'Kapitalertragsteuer[^\n]*?EUR\s*-?\s*(?P<amount>' + AMOUNT + ')'),
    'solidaritaetszuschlag': re.compile(r'Solidaritätszuschlag[^\n]*?EUR\s*-?\s*(?P<amount>' + AMOUNT + ')'),
    'kirchensteuer': re.compile(r'Kirchensteuer[^\n]*?EUR\s*-?\s*(?P<amount>' + AMOUNT + ')'),
}
TAX_SETTLEMENT_TITLE = re.compile(r'(?:nachträgliche\s+)?Verlustverrechnung', re.I)
TAX_SETTLEMENT_TOTAL = re.compile(r'Erstattung/Belastung\s*\(-\)\s+(?P<sign>-)?\s*(?P<amount>' + AMOUNT + ')')
TAX_SETTLEMENT_IBAN = re.compile(r'(?:Gegenkonto|Abrechnungs-IBAN)\s+(?P<iban>DE(?:[ \t]*\d){20})')


class IngWertpapierePlugin:
    plugin_id = 'user.ing-wertpapiere'
    bank_name = 'ING'
    version = '1.3'
    document_types = ('Dividendengutschrift, Wertpapierabrechnung Kauf/Verkauf, Vorabpauschale, '
                      'nachträgliche Verlustverrechnung, Jahresdepotauszug')

    def detect(self, document):
        text = document.text
        if not re.search(r'ING-DiBa|ing\.de', text):
            return []
        result = []
        if DIVIDEND_TITLE.search(text) and DIVIDEND_TOTAL.search(text):
            result.append(Detection(0.95, 'ING Dividendengutschrift', 'dividendengutschrift',
                                    'ING-DiBa, Dividendengutschrift und Gesamtbetrag erkannt'))
        if BUY_TITLE.search(text) and BUY_TOTAL.search(text):
            result.append(Detection(0.95, 'ING Wertpapierabrechnung Kauf', 'kauf',
                                    'ING-DiBa, Wertpapierabrechnung Kauf und Endbetrag erkannt'))
        if SELL_TITLE.search(text) and SELL_TOTAL.search(text):
            result.append(Detection(0.95, 'ING Wertpapierabrechnung Verkauf', 'verkauf',
                                    'ING-DiBa, Wertpapierabrechnung Verkauf und Endbetrag erkannt'))
        if ADVANCE_TITLE.search(text) and ADVANCE_TOTAL.search(text):
            result.append(Detection(0.98, 'ING Vorabpauschale', 'vorabpauschale',
                                    'ING-DiBa, Vorabpauschale und Kontobelastung erkannt'))
        if TAX_SETTLEMENT_TITLE.search(text) and TAX_SETTLEMENT_TOTAL.search(text):
            result.append(Detection(0.96, 'ING nachträgliche Verlustverrechnung', 'steuerverrechnung',
                                    'ING-DiBa, Verlustverrechnung und Steuerbetrag erkannt'))
        if STATEMENT_TITLE.search(text) and GRAND_TOTAL.search(text) and STATEMENT_DATE.search(text):
            result.append(Detection(0.95, 'ING Jahresdepotauszug', 'jahresdepotauszug',
                                    'ING-DiBa, Jahresdepotauszug und Gesamtkurswert erkannt'))
        return result

    # ------------------------------------------------------------------ common
    def _common(self, document, pattern):
        located = [(page, m) for page in document.pages for m in pattern.finditer(page.text)]
        if len(located) != 1:
            raise ValueError('Genau eine Abrechnung pro PDF erwartet, gefunden: %d.' % len(located))
        text = document.text
        security, name = SECURITY.search(text), NAME.search(text)
        valuta, iban = VALUTA.search(text), IBAN.search(text)
        if not (security and name and valuta and iban):
            raise ValueError('ISIN, Bezeichnung, Valuta oder Abrechnungs-IBAN nicht erkannt.')
        page, total = located[0]
        if total.group('currency') != 'EUR':
            raise ValueError('Abrechnung nicht in EUR: ' + total.group('currency'))
        row = page.text[:total.start()].count('\n') + 1
        return dict(page=page, total=total, security=security, name=' '.join(name.group('name').split()),
                    valuta=parse_date(valuta.group('date')), iban='IBAN ' + re.sub(r'\s+', '', iban.group('iban')),
                    row=row, source_line=' '.join(total.group().split()), text=text)

    def _finish(self, batch, document, common, account, review_note=None):
        page, text = common['page'], common['text']
        batch.pdf_booking_evidence.append({
            'page': page.number, 'line': common['row'], 'text': common['source_line'],
            'ocr': page.used_ocr, 'confidence': page.confidence, 'review_required': page.used_ocr})
        letter_date = LETTER_DATE.search(text)
        batch.documents.append(BankDocument(
            account, batch.file_hash + ':' + account, document.path.name,
            parse_date(letter_date.group('date')) if letter_date else common['valuta'],
            base64.b64encode(document.content).decode('ascii')))
        if page.used_ocr:
            batch.warnings.append('Seite per OCR gelesen; Betrag, Stückzahl und ISIN bitte am Original prüfen.')
        return batch

    # ------------------------------------------------------------------- parse
    def parse(self, document, detection, context):
        if detection.handler_id == 'dividendengutschrift':
            return self._dividend(document, context.batch)
        if detection.handler_id == 'kauf':
            return self._trade(document, context.batch, Kind.BUY)
        if detection.handler_id == 'verkauf':
            return self._trade(document, context.batch, Kind.SELL)
        if detection.handler_id == 'vorabpauschale':
            return self._advance_tax(document, context.batch)
        if detection.handler_id == 'steuerverrechnung':
            return self._tax_settlement(document, context.batch)
        if detection.handler_id == 'jahresdepotauszug':
            return self._statement(document, context.batch)
        raise ValueError('Nicht unterstützter Dokumenttyp: ' + detection.handler_id)

    def _dividend(self, document, batch):
        c = self._common(document, DIVIDEND_TOTAL)
        text, security = c['text'], c['security']
        reference = extract_bank_reference(text)
        nominal = NOMINAL_DIV.search(text)
        if not nominal:
            raise ValueError('Stückzahl nicht erkannt.')
        amount, qty = money(c['total'].group('amount')), correction_number(nominal.group('qty'))
        if not c['valuta'] or amount is None or qty is None:
            raise ValueError('Datum, Betrag oder Stückzahl ungültig.')

        gross, withholding = GROSS.search(text), WITHHOLDING.search(text)
        subtotal, fx = SUBTOTAL.search(text), FX_RATE.search(text)
        purpose = (f"ING Dividendengutschrift: {c['name']} ({security.group('isin')}, "
                   f"WKN {security.group('wkn')}) {qty} Stk.")
        if gross:
            purpose += f" · Brutto {gross.group('amount')} {gross.group('currency')}"
        if withholding:
            purpose += f" · Quellensteuer {withholding.group('rate')} % = {withholding.group('eur')} EUR"
        if fx:
            purpose += f" · Kurs {fx.group('rate')}"
        if subtotal and fx:
            converted = float(correction_number(subtotal.group('amount'))) / float(correction_number(fx.group('rate')))
            if abs(converted - float(amount)) > 0.015:
                batch.warnings.append('Gesamtbetrag passt nicht zu Zwischensumme und Devisenkurs; '
                                      'möglicherweise weitere Abzüge. Bitte am Original prüfen.')
        account = c['iban']
        isin = security.group('isin')
        # Brutto (Buchungswährung) = Gutschrift + einbehaltene Quellensteuer; netto bleibt der Betrag
        tax_items = []
        gross_eur = Decimal(amount)
        if withholding:
            tax_items.append(TaxItem('quellensteuer', money(withholding.group('eur')),
                                     rate=correction_number(withholding.group('rate')),
                                     original_amount=money(withholding.group('amount')),
                                     original_currency=withholding.group('currency')))
            gross_eur += Decimal(money(withholding.group('eur')))
        original_amount = original_currency = fx_rate = None
        if gross and gross.group('currency') != 'EUR' and fx:
            original_amount, original_currency = money(gross.group('amount')), gross.group('currency')
            fx_rate = correction_number(fx.group('rate'))
            if abs(Decimal(original_amount) / Decimal(fx_rate) - gross_eur) > Decimal('0.02'):
                batch.warnings.append('Brutto, Devisenkurs und Quellensteuer passen nicht zum Gesamtbetrag; '
                                      'bitte am Original prüfen.')
        ex, pay, rate = EX_DAY.search(text), PAY_DAY.search(text), RATE.search(text)
        external_id = 'pdf-ing-' + digest([account, isin, c['valuta'], amount, qty])
        batch.transactions.append(BankTransaction(
            account=account, external_id=external_id,
            date=c['valuta'], kind=DIVIDEND_KIND, amount=amount, currency='EUR',
            security=isin, quantity=qty, row=c['row'], value_date=c['valuta'], purpose=purpose,
            bank_reference=reference, document_reference=reference,
            booking_text='ING Dividendengutschrift', raw_text=c['source_line'],
            gross_amount=f'{gross_eur:.2f}', original_amount=original_amount, original_currency=original_currency or '',
            fx_rate=fx_rate, tax_items=tax_items, income_basis='net', security_ref=isin,
            gross_income=money(gross.group('amount')) if gross else None,
            gross_currency=gross.group('currency') if gross else '',
            withholding_tax=money(withholding.group('eur')) if withholding else None,
            ex_date=parse_date(ex.group('d')) if ex else '', pay_date=parse_date(pay.group('d')) if pay else c['valuta'],
            per_share_amount=correction_number(rate.group('r')) if rate else None,
            per_share_currency=rate.group('c') if rate else '',
            field_sources={'amount': 'ocr', 'quantity': 'ocr'} if c['page'].used_ocr else {}))
        batch.securities.append(SecurityInfo(key=isin, isin=isin, wkn=security.group('wkn'), name=c['name'],
                                             quote_currency=original_currency or 'EUR'))
        # Rückseite: Freibetrag, Verrechnungstopf, anrechenbare Quellensteuer
        tax = {key: money(m.group('a')) for key, p in TAX_PAGE.items() for m in [p.search(text)] if m}
        depot = DEPOT.search(text)
        if depot and tax:
            batch.tax_events.append(TaxEvent(
                external_id='pdf-ing-tax-' + digest([account, isin, c['valuta'], amount]),
                account='Depot ' + depot.group('id'), type='quellensteuer_anrechnung' if 'creditable_withholding' in tax else 'freistellung',
                date=c['valuta'], tax_year=c['valuta'][:4], security_ref=isin, quantity=qty,
                related_transaction_id=external_id, **tax))
        batch.warnings.append('Betrag ist die Gutschrift nach Quellensteuer; Brutto und Steuern stehen in den Zusatzfeldern.')
        if REINVEST.search(text):
            batch.warnings.append('ING legt diese Dividende automatisch wieder an; der zugehörige Kauf '
                                  'muss über seine eigene Abrechnung importiert werden.')
        return self._finish(batch, document, c, account)

    def _buy(self, document, batch):
        return self._trade(document, batch, Kind.BUY)

    def _trade(self, document, batch, kind):
        total_pattern = BUY_TOTAL if kind == Kind.BUY else SELL_TOTAL
        title_pattern = BUY_TITLE if kind == Kind.BUY else SELL_TITLE
        c = self._common(document, total_pattern)
        text, security = c['text'], c['security']
        reference = extract_bank_reference(text)
        nominal, depot = NOMINAL_BUY.search(text), DEPOT.search(text)
        order, execution = ORDER.search(text), EXECUTION_DAY.search(text)
        if not (nominal and depot and order and execution):
            raise ValueError('Stückzahl, Depotnummer, Ordernummer oder Ausführungstag nicht erkannt.')
        total = money(c['total'].group('amount'))
        qty = correction_number(nominal.group('qty'))
        executed = parse_date(execution.group('date'))
        if not executed or total is None or qty is None:
            raise ValueError('Datum, Betrag oder Stückzahl ungültig.')

        # Entgelte ergeben sich als Differenz Endbetrag - Kurswert (ING weist sie je nach Ordertyp unterschiedlich aus)
        market = MARKET_VALUE.search(text)
        fees = None
        if market:
            diff = ((Decimal(total) - Decimal(money(market.group('amount')))) if kind == Kind.BUY
                    else (Decimal(money(market.group('amount'))) - Decimal(total)))
            if diff < Decimal('-0.004'):
                raise ValueError('Endbetrag und Kurswert widersprechen der wirtschaftlichen Zahlungsrichtung.')
            fees = f'{diff:.2f}' if abs(diff) > 0.004 else None
            price = PRICE.search(text)
            if price and abs(float(correction_number(price.group('amount'))) * float(qty)
                             - float(money(market.group('amount')))) > 0.02:
                batch.warnings.append('Kurs × Stückzahl passt nicht zum Kurswert; bitte am Original prüfen.')
        else:
            batch.warnings.append('Kurswert nicht erkannt; Entgelte nicht prüfbar.')
        if fees:
            batch.warnings.append(f'Endbetrag weicht vom Kurswert um {fees} EUR ab; als Entgelt übernommen.')

        account = 'Depot ' + depot.group('id')
        amount = ('-' if kind == Kind.BUY else '') + total
        isin = security.group('isin')
        price = PRICE.search(text)
        venue = VENUE.search(text)
        kind_text = title_pattern.search(text).group('type')
        batch.transactions.append(Transaction(
            account=account,
            external_id='pdf-ing-order-' + digest([account, order.group('order'), isin, executed, qty]),
            date=executed, kind=kind, amount=amount, currency='EUR',
            security=isin, quantity=qty, fees=fees, row=c['row'],
            gross_amount=money(market.group('amount')) if market else None,
            fee_items=[FeeItem('provision' if PROVISION.search(text) else 'entgelt', fees)] if fees else [],
            price=correction_number(price.group('amount')) if price else None, price_currency='EUR' if price else '',
            trade_date=executed, executed_at=(f"{executed}T{execution.group('time')}"
                                               if execution.group('time') else ''), pay_date=c['valuta'],
            cash_account=c['iban'], depot_account=account, security_ref=isin,
            order_id=order.group('order'), venue=' '.join(venue.group('v').split()) if venue else '',
            document_reference=reference or order.group('order'),
            order_subtype='sparplan' if 'Sparplan' in kind_text else ('wiederanlage' if 'Wiederanlage' in kind_text else ''),
            field_sources={'amount': 'ocr', 'quantity': 'ocr'} if c['page'].used_ocr else {}))
        batch.securities.append(SecurityInfo(key=isin, isin=isin, wkn=security.group('wkn'), name=c['name'], quote_currency='EUR'))
        direction = 'Kontobelastung' if kind == Kind.BUY else 'Kontogutschrift'
        batch.warnings.append(f"ING {kind_text} (Order {order.group('order')}, Valuta {c['valuta']}): "
                              f'{direction} wurde nicht als eigene Kontobuchung erzeugt.')
        return self._finish(batch, document, c, account)

    def _advance_tax(self, document, batch):
        c = self._common(document, ADVANCE_TOTAL)
        text, security = c['text'], c['security']
        nominal, depot = NOMINAL_DIV.search(text), DEPOT.search(text)
        per_unit, taxable = ADVANCE_PER_UNIT.search(text), ADVANCE_TAXABLE.search(text)
        if not all((nominal, depot, per_unit, taxable)):
            raise ValueError('Stückzahl, Depot, Vorabpauschale je Stück oder Steuerbasis nicht erkannt.')
        amount = money(c['total'].group('amount'))
        qty = correction_number(nominal.group('qty'))
        components = [(name, money(match.group('amount'))) for name, pattern in TAX_COMPONENTS.items()
                      for match in [pattern.search(text)] if match]
        component_total = sum((Decimal(value) for _, value in components), Decimal())
        if amount is None or qty is None or abs(component_total - Decimal(amount)) > Decimal('0.01'):
            raise ValueError('Steuerkomponenten der Vorabpauschale passen nicht zur Kontobelastung.')
        account = 'Depot ' + depot.group('id')
        isin = security.group('isin')
        income_year = str(int(c['valuta'][:4]) - 1)
        event_id = 'pdf-ing-advance-' + digest([account, isin, income_year, c['valuta'], qty, taxable.group('amount')])
        transaction_id = event_id + '-tax'
        component_values = dict(components)
        advance_base = (Decimal(qty) * Decimal(correction_number(per_unit.group('amount')))).quantize(
            Decimal('0.01'), rounding=ROUND_HALF_UP)
        letter_date = LETTER_DATE.search(text)
        balances = {key: money(match.group('a')) for key, pattern in TAX_PAGE.items()
                    for match in [pattern.search(text)] if match}
        batch.tax_events.append(TaxEvent(
            external_id=event_id, account=account, type='vorabpauschale', date=c['valuta'],
            tax_year=c['valuta'][:4], income_year=income_year,
            document_date=parse_date(letter_date.group('date')) if letter_date else c['valuta'],
            security_ref=isin, quantity=qty, currency='EUR', advance_tax_base=f'{advance_base:.2f}',
            taxable_income=money(taxable.group('amount')), per_unit=correction_number(per_unit.group('amount')),
            partial_exemption_amount=(money(ADVANCE_PARTIAL.search(text).group('amount'))
                                      if ADVANCE_PARTIAL.search(text) else None),
            capital_gains_tax=component_values.get('kapitalertragsteuer'),
            solidarity_surcharge=component_values.get('solidaritaetszuschlag'),
            church_tax=component_values.get('kirchensteuer'), paid_taxes=amount,
            allowance_before=balances.get('allowance_before'), allowance_after=balances.get('allowance_after'),
            withholding_pot_before=balances.get('withholding_pot_before'),
            withholding_pot_after=balances.get('withholding_pot_after'),
            reference_no=extract_bank_reference(text), related_transaction_id=transaction_id,
            cash_account=c['iban']))
        batch.transactions.append(BankTransaction(
            account=account, external_id=transaction_id, date=c['valuta'], value_date=c['valuta'],
            kind=Kind.TAX, amount='-' + amount, currency='EUR', security=isin, quantity=qty,
            taxes=amount, tax_items=[TaxItem(name, value) for name, value in components],
            cash_account=c['iban'], depot_account=account, security_ref=isin, affects_cash=False,
            booking_text='ING Vorabpauschale Steuerbelastung', raw_text=c['source_line'],
            purpose=f'ING Vorabpauschale {c["name"]}', document_reference=extract_bank_reference(text)))
        batch.securities.append(SecurityInfo(key=isin, isin=isin, wkn=security.group('wkn'), name=c['name']))
        return self._finish(batch, document, c, account)

    def _tax_settlement(self, document, batch):
        text = document.text
        total, iban, valuta, depot = (TAX_SETTLEMENT_TOTAL.search(text), TAX_SETTLEMENT_IBAN.search(text),
                                      VALUTA.search(text), DEPOT.search(text))
        if not all((total, iban, valuta, depot)):
            raise ValueError('Steuerbetrag, Gegenkonto, Depotnummer oder Valuta nicht erkannt.')
        amount = money(total.group('amount'))
        components = [(name, money(match.group('amount'))) for name, pattern in TAX_COMPONENTS.items()
                      for match in [pattern.search(text)] if match]
        if not components or amount is None:
            raise ValueError('Keine prüfbaren Steuerkomponenten erkannt.')
        component_total = sum((Decimal(value) for _, value in components), Decimal())
        if abs(component_total - Decimal(amount)) > Decimal('0.01'):
            raise ValueError('Steuerkomponenten passen nicht zum Erstattungs-/Belastungsbetrag.')
        booked = parse_date(valuta.group('date'))
        is_charge = bool(total.group('sign'))
        kind = Kind.TAX if is_charge else Kind.TAX_REFUND
        cash_account = 'IBAN ' + re.sub(r'\s+', '', iban.group('iban'))
        account = 'Depot ' + depot.group('id')
        external_id = 'pdf-ing-tax-settlement-' + digest(
            [account, cash_account, booked, kind, amount, extract_bank_reference(text)])
        batch.transactions.append(BankTransaction(
            account=account, external_id=external_id, date=booked, value_date=booked, kind=kind,
            amount=('-' if is_charge else '') + amount, currency='EUR', taxes=amount,
            tax_items=[TaxItem(name, value) for name, value in components], cash_account=cash_account,
            depot_account=account, affects_cash=False,
            purpose='ING nachträgliche Verlustverrechnung', booking_text='ING Steuerverrechnung',
            raw_text=' '.join(total.group().split()), bank_reference=extract_bank_reference(text)))
        common = dict(page=document.pages[0], row=1, source_line=' '.join(total.group().split()),
                      text=text, valuta=booked)
        return self._finish(batch, document, common, account)


    def _statement(self, document, batch):
        if any(page.used_ocr for page in document.pages):
            raise ValueError('ING-Depotauszüge benötigen eingebetteten Text zur sicheren Bestandsprüfung.')
        text = document.text
        depot, date = DEPOT.search(text), STATEMENT_DATE.search(text)
        as_of = parse_date(date.group('date')) if date else None
        if not (depot and as_of):
            raise ValueError('Depotnummer oder Stichtag nicht erkannt.')
        account = 'Depot ' + depot.group('id')

        positions, running, current = [], 0, None
        for page in document.pages:
            for line in page.text.splitlines():
                row = STATEMENT_ROW.match(line)
                if row:
                    if current is not None:
                        raise ValueError(f"Position {current['name']}: ISIN nicht erkannt.")
                    current = row.groupdict()
                    continue
                isin = STATEMENT_ISIN.search(line)
                if isin and current is not None:
                    positions.append(Position(
                        key=isin.group('isin'), name=' '.join(current['name'].split()), isin=isin.group('isin'),
                        wkn=isin.group('wkn'), asset_type=ASSET_TYPE,
                        quantity=correction_number(current['qty']), value=money(current['value']),
                        currency='EUR', quote_date=as_of, row=len(positions) + 1,
                        security_ref=isin.group('isin'), price=correction_number(current['price']),
                        price_currency='EUR', price_basis='Kurs'))
                    running += float(money(current['value']))
                    current = None
                    continue
                custody = CUSTODY.match(line)
                if custody and positions:
                    if custody.group('label') == 'Verwahrart':
                        positions[-1].custody_type = custody.group('value')
                    else:
                        positions[-1].custody_country = custody.group('value')
            if current is not None:
                raise ValueError(f"Position {current['name']}: ISIN nicht erkannt.")
            carry = CARRY.search(page.text)
            if carry and abs(running - float(money(carry.group('amount')))) > 0.005:
                raise ValueError(f"Zwischensumme Seite {page.number} ({running:.2f}) weicht von "
                                 f"'Übertrag Kurswert' ({money(carry.group('amount'))}) ab; Import abgebrochen.")
        total, count = GRAND_TOTAL.search(text), POSITION_COUNT.search(text)
        if not positions:
            raise ValueError('Keine Depotpositionen erkannt.')
        if len({p.key for p in positions}) != len(positions):
            raise ValueError('Mehrfach aufgeführte ISIN im Depotauszug.')
        if abs(running - float(money(total.group('amount')))) > 0.005:
            raise ValueError(f"Summe der Positionen ({running:.2f}) weicht von 'Gesamtkurswert' "
                             f"({money(total.group('amount'))}) ab; Import abgebrochen.")
        if count and int(count.group('count')) != len(positions):
            raise ValueError(f"{len(positions)} Positionen erkannt, laut Auszug {count.group('count')}.")

        batch.snapshots.append(Snapshot(account=account, period=as_of[:7], as_of=as_of,
                                        sheet='ING Jahresdepotauszug', positions=positions,
                                        complete=True, statement_type='Jahresdepotauszug',
                                        reported_total_value=money(total.group('amount')),
                                        reported_position_count=len(positions)))
        for position in positions:
            batch.securities.append(SecurityInfo(
                key=position.isin, isin=position.isin, wkn=position.wkn, name=position.name,
                custody_type=position.custody_type, custody_country=position.custody_country, quote_currency='EUR'))
        letter_date = LETTER_DATE.search(text)
        batch.documents.append(BankDocument(
            account, batch.file_hash + ':' + account, document.path.name,
            parse_date(letter_date.group('date')) if letter_date else as_of,
            base64.b64encode(document.content).decode('ascii')))
        batch.warnings.append('Bestand und Kurswert je Position übernommen; Einstandswerte stehen nicht im Auszug.')
        return batch


plugin = IngWertpapierePlugin()
