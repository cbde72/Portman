"""FNZ Bank (formerly ebase) finvesto statements verified against local documents."""
import base64
import re
from decimal import Decimal

from portfolio_v5.models import (BankDocument, FeeItem, Position, SecurityInfo, Snapshot,
                                 Transaction, correction_number, digest, money, parse_date,
                                 valid_isin)
from portfolio_v5.pdf_plugins import Detection

DATE = r'\d{2}\.\d{2}\.\d{4}'
NUMBER = r'\d[\d.]*(?:,\d+)?'
MONEY = r'\d[\d.]*,\d{2}'
BANK = re.compile(r'FNZ\s*Bank|European\s*Bank\s*for\s*Financial\s*Services|\bebase\b', re.I)
TURNOVER_TITLE = re.compile(r'Umsatzabrechnung\s+f.r\s+Ihr\s*finvesto\s*Depot', re.I)
DEPOT_TITLE = re.compile(r'Depotauszug\s+f.r\s+Ihr\s*finvesto\s*Depot', re.I)
DEPOT = re.compile(r'Depot-Nr\.\s*(?P<id>\d+)', re.I)
STATEMENT_NO = re.compile(r'(?:Umsatzabrechnung|Depotauszug)-Nr\.\s*(?P<id>\d+)', re.I)
REFERENCE = re.compile(r'Ref\.\s*Nr\.\s*(?P<ref>\d+/\d+)\s*,?\s*Buchungsdatum\s*(?P<date>' + DATE + ')', re.I)

BUY = re.compile(
    r'Kauf\s*(?P<amount>' + MONEY + r')\s*EUR(?:\s*mit\s*Kursdatum\s*(?P<course_date>' + DATE + r'))?'
    r'\s*in\s*Depotposition\s*(?P<position>\d+\.\d+)', re.I)
DIVIDEND = re.compile(
    r'Fondsertrag\s*\(Aussch.ttung\)\s*mit\s*Bestandsdatum\s*(?P<record_date>' + DATE + r')'
    r'\s*in\s*Depotposition\s*(?P<position>\d+\.\d+)', re.I)
REINVEST = re.compile(
    r'Wiederanlage\s*Fondsertrag\s*(?P<amount>' + MONEY + r')\s*(?P<currency>[A-Z]{3})'
    r'\s*mit\s*Kursdatum\s*(?P<course_date>' + DATE + r')\s*in\s*Depotposition\s*(?P<position>\d+\.\d+)', re.I)
TRADE_ROW_FX = re.compile(
    r'(?m)^\s*(?P<isin>[A-Z]{2}[A-Z0-9]{9}\d)\s+(?P<qty>' + NUMBER + r')\s+'
    r'(?P<price>' + NUMBER + r')\s+(?P<price_currency>[A-Z]{3})\s+(?P<fx>' + NUMBER + r')\s+'
    r'(?P<amount>' + MONEY + r')\s+(?P<currency>[A-Z]{3})\s*$')
TRADE_ROW = re.compile(
    r'(?m)^\s*(?P<isin>[A-Z]{2}[A-Z0-9]{9}\d)\s+(?P<qty>' + NUMBER + r')\s+'
    r'(?P<price>' + NUMBER + r')\s+(?P<currency>[A-Z]{3})\s+(?P<amount>' + MONEY + r')\s+(?P=currency)\s*$')
DIVIDEND_ROW = re.compile(
    r'(?m)^\s*(?P<isin>[A-Z]{2}[A-Z0-9]{9}\d)\s+(?P<qty>' + NUMBER + r')\s+'
    r'(?P<per_share>' + NUMBER + r')\s+(?P<currency>[A-Z]{3})\s+(?P<amount>' + MONEY + r')\s+(?P=currency)\s*$')
FEE = re.compile(r'(?:ETF-)?Transaktionsentgelt\s+(?P<amount>' + MONEY + r')\s*EUR', re.I)
PAYMENT = re.compile(r'Zahlungsbetrag(?:\s+aus\s+.berweisung)?\s*(?P<amount>' + MONEY + r')\s*(?P<currency>[A-Z]{3})', re.I)

POSITION_HEADER = re.compile(r'(?:Bestand\s+Depotpositionen|Bestand\s+der\s*Depotpositionen)', re.I)
POSITION_ROW = re.compile(
    r'(?m)^\s*(?P<sub>\d{2})\s+(?P<isin>[A-Z]{2}[A-Z0-9]{9}\d)\s+(?P<qty>' + NUMBER + r')\s+'
    r'(?P<price>' + NUMBER + r')\s+(?P<price_currency>[A-Z]{3})\s+(?P<date>' + DATE + r')\s+'
    r'(?P<fx>' + NUMBER + r')\s+(?P<value>' + MONEY + r')\s+EUR\s*$')
TOTAL = re.compile(r'Depotgesamtwert\s*(?P<amount>' + MONEY + r')\s*EUR', re.I)


def _block(text, match, markers):
    ends = [candidate.start() for candidate in markers if candidate.start() > match.start()]
    return text[match.start():min(ends) if ends else len(text)]


class FnzFinvestoPlugin:
    plugin_id = 'fnz.finvesto'
    bank_name = 'FNZ Bank (ehemals ebase)'
    version = '1.0'
    document_types = 'FNZ/finvesto Umsatzabrechnung, FNZ/finvesto Depotauszug'

    def detect(self, document):
        text = document.text
        if not BANK.search(text):
            return []
        if TURNOVER_TITLE.search(text) and DEPOT.search(text):
            return [Detection(.99, 'FNZ Umsatzabrechnung', 'umsatzabrechnung',
                              'FNZ Bank/finvesto, Umsatzabrechnung und Depotnummer erkannt')]
        if DEPOT_TITLE.search(text) and DEPOT.search(text):
            return [Detection(.99, 'FNZ Depotauszug', 'depotauszug',
                              'FNZ Bank/finvesto, Depotauszug und Depotnummer erkannt')]
        return []

    def parse(self, document, detection, context):
        if any(page.used_ocr for page in document.pages):
            raise ValueError('FNZ-Belege benötigen eingebetteten Text für Betrags- und Vollständigkeitskontrollen.')
        text, batch = document.text, context.batch
        depot = DEPOT.search(text)
        if not depot:
            raise ValueError('FNZ-Depotnummer nicht erkannt.')
        account = 'FNZ Depot ' + depot.group('id')
        batch.account_names.append(account)
        if detection.handler_id == 'umsatzabrechnung':
            self._transactions(text, account, batch)
            self._snapshot(text, account, batch, complete=False)
        elif detection.handler_id == 'depotauszug':
            self._snapshot(text, account, batch, complete=True)
        else:
            raise ValueError('Nicht unterstützter FNZ-Dokumenttyp: ' + detection.handler_id)
        statement = STATEMENT_NO.search(text)
        dates = [tx.date for tx in batch.transactions] + [snap.as_of for snap in batch.snapshots]
        day = max(dates) if dates else ''
        batch.documents.append(BankDocument(
            account, batch.file_hash + ':' + account, document.path.name, day,
            base64.b64encode(document.content).decode('ascii'), document_type=detection.document_type,
            bank_name='FNZ Bank', document_no=statement.group('id') if statement else '',
            page_count=len(document.pages), extraction_method='PDF-Text',
            linked_ids=[tx.external_id for tx in batch.transactions]))
        return batch

    def _transactions(self, text, account, batch):
        markers = sorted([*BUY.finditer(text), *DIVIDEND.finditer(text), *REINVEST.finditer(text)],
                         key=lambda item: item.start())
        if not markers:
            raise ValueError('FNZ-Umsatzabrechnung enthält keinen unterstützten Umsatz.')
        seen_references = set()
        for marker in markers:
            body = _block(text, marker, markers)
            reference = REFERENCE.search(body)
            if not reference or reference.group('ref') in seen_references:
                raise ValueError('FNZ-Umsatz ohne eindeutige Referenz oder Buchungsdatum.')
            seen_references.add(reference.group('ref'))
            booked = parse_date(reference.group('date'))
            if marker.re is DIVIDEND:
                row = DIVIDEND_ROW.search(body)
                if not row:
                    raise ValueError('FNZ-Ausschüttung ohne eindeutige ISIN-/Betragszeile.')
                kind, amount, currency = 'DIVIDEND', money(row.group('amount')), row.group('currency')
                quantity, price = correction_number(row.group('qty')), correction_number(row.group('per_share'))
                extra = dict(per_share_amount=price, per_share_currency=currency,
                             ex_date=parse_date(marker.group('record_date')))
            else:
                row = TRADE_ROW_FX.search(body) or TRADE_ROW.search(body)
                if not row:
                    raise ValueError('FNZ-Kauf/Wiederanlage ohne eindeutige ISIN-/Betragszeile.')
                kind = 'BUY'
                amount, currency = money(row.group('amount')), row.group('currency')
                quantity, price = correction_number(row.group('qty')), correction_number(row.group('price'))
                extra = dict(price=price, price_currency=row.group('price_currency') if 'price_currency' in row.groupdict()
                             else currency, order_subtype='wiederanlage' if marker.re is REINVEST else '')
            if not booked or Decimal(quantity) <= 0 or Decimal(amount) <= 0 or not valid_isin(row.group('isin')):
                raise ValueError('FNZ-Umsatz enthält ungültiges Datum, ISIN, Stückzahl oder Betrag.')
            fee = FEE.search(body)
            fees = money(fee.group('amount')) if fee and Decimal(money(fee.group('amount'))) else None
            payment = PAYMENT.search(body)
            cash_amount = money(payment.group('amount')) if payment else amount
            expected_payment = Decimal(amount) + (Decimal(fees) if kind == 'BUY' and fees else Decimal())
            if payment and (payment.group('currency') != currency
                            or abs(Decimal(cash_amount) - expected_payment) > Decimal('.01')):
                raise ValueError('FNZ-Zahlungsbetrag stimmt nicht mit Umsatz und Entgelt überein.')
            external_id = 'pdf-fnz-' + digest([account, reference.group('ref'), kind, row.group('isin'), booked])
            batch.transactions.append(Transaction(
                account=account, external_id=external_id, date=booked, kind=kind,
                amount=('-' if kind == 'BUY' else '') + cash_amount, currency=currency,
                security=row.group('isin'), security_ref=row.group('isin'), quantity=quantity,
                gross_amount=amount,
                fees=fees, fee_items=[FeeItem('transaktionsentgelt', fees)] if fees else [],
                document_reference=reference.group('ref'), transaction_reference=reference.group('ref'),
                depot_account=account, pay_date=booked, **extra))
            batch.securities.append(SecurityInfo(key=row.group('isin'), isin=row.group('isin'),
                                                  name='FNZ Fonds ' + row.group('isin'),
                                                  quote_currency=extra.get('price_currency', currency)))
        batch.warnings.append('FNZ-Umsätze sind Depotereignisse; keine zusätzliche Kontobuchung wurde erzeugt.')

    def _snapshot(self, text, account, batch, complete):
        is_statement = complete
        header = POSITION_HEADER.search(text)
        total = TOTAL.search(text)
        if not header:
            raise ValueError('FNZ-Bestand nicht erkannt.')
        positions = []
        for row in POSITION_ROW.finditer(text, header.end()):
            if not valid_isin(row.group('isin')):
                raise ValueError('Ungültige ISIN im FNZ-Bestand.')
            quantity, value = correction_number(row.group('qty')), money(row.group('value'))
            if Decimal(quantity) < 0 or Decimal(value) < 0:
                raise ValueError('Negative Stückzahl oder Bewertung im FNZ-Bestand.')
            positions.append(Position(
                key=row.group('isin') + ':' + row.group('sub'), name='FNZ Fonds ' + row.group('isin'),
                isin=row.group('isin'), asset_type='Fonds', quantity=quantity, value=value,
                currency='EUR', quote_date=parse_date(row.group('date')),
                price=correction_number(row.group('price')), price_currency=row.group('price_currency'),
                sub_account=row.group('sub')))
        if not positions:
            raise ValueError('Keine FNZ-Depotposition erkannt.')
        reported = money(total.group('amount')) if total else None
        if reported is not None and abs(
                sum((Decimal(p.value) for p in positions), Decimal()) - Decimal(reported)) > Decimal('.01'):
            raise ValueError('FNZ-Positionssumme stimmt nicht mit dem Depotgesamtwert überein.')
        if complete and reported is None:
            complete = False
        as_of = max(p.quote_date for p in positions if p.quote_date)
        warnings = [] if complete else [
            ('Depotgesamtwert fehlt; Vollständigkeit des Depotauszugs nicht nachgewiesen.'
             if is_statement else 'Umsatzabrechnung zeigt nur Positionen mit Umsatz; Teilbestand.')]
        batch.snapshots.append(Snapshot(
            account=account, period=as_of[:7], as_of=as_of,
            sheet='FNZ ' + ('Depotauszug' if is_statement else 'Umsatzabrechnung'),
            positions=positions, complete=complete, warnings=warnings,
            reported_total_value=reported, reported_position_count=len(positions),
            statement_type='Depotauszug' if is_statement else 'Umsatzabrechnung'))


plugin = FnzFinvestoPlugin()
