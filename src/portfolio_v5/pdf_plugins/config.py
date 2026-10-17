"""Declarative TOML importer for regular statement and portfolio layouts."""
import base64
import re
import tomllib
from pathlib import Path

from .api import Detection
from ..models import (Balance, BankDocument, BankTransaction, Position, Snapshot,
                      correction_number, digest, money, number, parse_date)


def _patterns(value):
    return [value] if isinstance(value, str) else list(value or [])


class ConfigPdfPlugin:
    def __init__(self, path):
        self.path = Path(path)
        data = tomllib.loads(self.path.read_text(encoding='utf-8'))
        self.plugin_id = data['plugin']['id']
        self.bank_name = data['plugin']['bank']
        self.version = str(data['plugin'].get('version', 1))
        self.documents = data.get('documents', [])
        if not self.plugin_id or not self.documents:
            raise ValueError(f'{self.path}: plugin.id und mindestens [[documents]] sind erforderlich.')
        ids = [item['id'] for item in self.documents]
        if len(ids) != len(set(ids)): raise ValueError(f'{self.path}: Dokument-ID mehrfach vorhanden.')

    def detect(self, document):
        found = []
        for item in self.documents:
            required, optional = _patterns(item.get('required')), _patterns(item.get('optional'))
            if required and not all(re.search(p, document.text, re.I | re.M) for p in required): continue
            hits = sum(bool(re.search(p, document.text, re.I | re.M)) for p in optional)
            confidence = float(item.get('confidence', .75)) + min(.2, hits * .05)
            found.append(Detection(min(confidence, .99), item['type'], item['id'],
                                   f'{len(required)} Pflicht- und {hits} optionale Merkmale erkannt'))
        return found

    def parse(self, document, detection, context):
        spec = next(item for item in self.documents if item['id'] == detection.handler_id)
        batch = context.batch
        batch.document_type = detection.document_type
        account = self._account(document.text, spec)
        batch.account_names = [account]
        flags = re.M | (re.S if spec.get('dotall', False) else 0)
        currency = spec.get('currency', 'EUR')
        tx_pattern = spec.get('transaction_regex')
        if tx_pattern:
            for occurrence, match in enumerate(re.finditer(tx_pattern, document.text, flags), 1):
                row = match.groupdict(); day = parse_date(row.get('date'))
                amount = money(row.get('amount'))
                if not day or amount is None: raise ValueError(f'{detection.document_type}: Buchung ohne gültiges Datum oder Betrag.')
                purpose = (row.get('purpose') or '').strip()
                reference = (row.get('bank_reference') or row.get('reference') or
                             row.get('transaction_reference') or row.get('transaction_id') or '').strip()
                batch.transactions.append(BankTransaction(account,
                    f"{self.plugin_id}-{detection.handler_id}-" + digest([document.file_hash, occurrence, row])[:24],
                    day, row.get('kind') or spec.get('transaction_kind', 'BANK_BOOKING'), amount,
                    row.get('currency') or currency, value_date=parse_date(row.get('value_date')) or '',
                    purpose=purpose, bank_reference=reference, document_reference=reference,
                    transaction_reference=reference,
                    withholding_tax=money(row.get('withholding_tax')),
                    withholding_country=(row.get('withholding_country') or '').strip().upper(),
                    withholding_tax_rate=correction_number(row.get('withholding_tax_rate')) if row.get('withholding_tax_rate') else None,
                    tax_rate=correction_number(row.get('tax_rate')) if row.get('tax_rate') else None,
                    per_share_amount=correction_number(row.get('per_share_amount')) if row.get('per_share_amount') else None,
                    per_share_currency=(row.get('per_share_currency') or '').strip().upper(),
                    raw_text=match.group(0)))
                page = self._page(document, match.group(0))
                batch.pdf_booking_evidence.append(dict(page=page.number,
                    text=match.group(0), ocr=page.used_ocr, confidence=page.confidence,
                    review_required=page.used_ocr))
        balance_pattern = spec.get('balance_regex')
        if balance_pattern:
            match = re.search(balance_pattern, document.text, flags)
            if not match: raise ValueError(f'{detection.document_type}: ausgewiesener Saldo fehlt.')
            row = match.groupdict(); day = parse_date(row.get('date') or '')
            if not day: raise ValueError(f'{detection.document_type}: Saldodatum fehlt.')
            batch.balances.append(Balance(day[:7], spec.get('balance_category', 'Liquidität'),
                                          account, money(row['amount']), detection.document_type, 0))
        position_pattern = spec.get('position_regex')
        if position_pattern:
            day_match = re.search(spec.get('snapshot_date_regex', r'(?P<date>\d{2}\.\d{2}\.\d{4})'), document.text, flags)
            day = parse_date(day_match.groupdict().get('date') if day_match else '')
            if not day: raise ValueError(f'{detection.document_type}: Depotstichtag fehlt.')
            positions = []
            for row_number, match in enumerate(re.finditer(position_pattern, document.text, flags), 1):
                row = match.groupdict(); isin, wkn = row.get('isin') or '', row.get('wkn') or ''
                key = isin or ('WKN:' + wkn if wkn else row.get('key') or '')
                if not key: raise ValueError(f'{detection.document_type}: Position ohne Kennung.')
                positions.append(Position(key, (row.get('name') or key).strip(), isin, wkn,
                    row.get('asset_type') or spec.get('asset_type', 'Sonstiges'),
                    number(row.get('quantity')), money(row.get('cost')), money(row.get('value')),
                    row.get('currency') or currency, day, row_number))
            if not positions: raise ValueError(f'{detection.document_type}: keine Depotposition erkannt.')
            batch.snapshots.append(Snapshot(account, day[:7], day, detection.document_type, positions,
                                            bool(spec.get('complete_snapshot', False))))
        batch.documents.append(BankDocument(account, document.file_hash + ':' + account,
            detection.document_type, self._document_date(document.text, spec),
            base64.b64encode(document.content).decode('ascii')))
        batch.pdf_text = '\n\n'.join(f'--- Seite {p.number} ---\n{p.text}' for p in document.pages)
        return batch

    def _account(self, text, spec):
        pattern = spec.get('account_regex')
        if not pattern: return self.bank_name + ' · Konto unbekannt'
        match = re.search(pattern, text, re.I | re.M)
        if not match: raise ValueError(f"{spec['type']}: Konto- oder Depotkennung fehlt.")
        value = match.groupdict().get('id') or match.group(1)
        return spec.get('account_prefix', self.bank_name + ' ') + re.sub(r'\s+', '', value)

    @staticmethod
    def _document_date(text, spec):
        match = re.search(spec.get('document_date_regex', r'(?P<date>\d{2}\.\d{2}\.\d{4})'), text, re.I | re.M)
        return parse_date(match.groupdict().get('date') if match else '') or ''

    @staticmethod
    def _page(document, text):
        return next((page for page in document.pages if text in page.text), document.pages[0])
