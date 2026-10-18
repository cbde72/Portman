"""Lossless import of the comdirect tax-detail CSV export."""
from __future__ import annotations

import csv
import hashlib
from datetime import datetime
from pathlib import Path

from .models import ImportBatch, TaxDetailRecord


COLUMNS = (
    'Steuerjahr', 'Buchungstag', 'Steuerliches Datum', 'Referenznummer', 'Vorgang',
    'Stück/Nominale', 'Bezeichnung', 'WKN', 'Betrag Brutto', 'Gewinn/Verlust',
    'Gewinn Aktien', 'Verlust Aktien', 'Gewinn Sonstige', 'Verlust Sonstige',
    'verrechneter Gewinn Aktien', 'verrechneter Verlust Aktien',
    'verrechneter Gewinn Sonstige', 'verrechneter Verlust Sonstige', 'BMG nach VV',
    'Veränderung FSA', 'BMG nach FSA', 'Umsatz anrechenbarer Quellensteuer',
    'Veränderung Anrechenbare Quellensteuer', 'Veränderung Angerechnete Quellensteuer',
    'Kapitalertragssteuer', 'Solidaritätszuschlag', 'Kirchensteuer', 'Summe Steuern',
    'Gewinn/Verlust nach Steuern', 'Steuerbemessungsgrundlage',
    'Gewinn/Verlust Aktien (Saldo)', 'Gewinn/Verlust Sonstige (Saldo)')

GROUPS = {
    'Vorgang': COLUMNS[:8], 'Ertrag': COLUMNS[8:14],
    'Verlustverrechnung': COLUMNS[14:19], 'Freistellungsauftrag': COLUMNS[19:21],
    'Quellensteuer': COLUMNS[21:24], 'Steuern': COLUMNS[24:30], 'Salden': COLUMNS[30:]
}


def _read_rows(path):
    raw = Path(path).read_bytes()
    try:
        text = raw.decode('utf-8-sig')
    except UnicodeDecodeError:
        text = raw.decode('cp1252')
    return raw, list(csv.reader(text.splitlines(), delimiter=';'))


def _iso(value):
    try:
        return datetime.strptime(value.strip(), '%d.%m.%Y').date().isoformat()
    except (ValueError, AttributeError):
        return ''


def stable_identity(account, values):
    """Reference first, with a deterministic fallback for reference-less rows."""
    reference = values.get('Referenznummer', '').strip()
    material = [account.casefold(), reference] if reference else [
        account.casefold(), values.get('Steuerjahr', ''), values.get('Buchungstag', ''),
        values.get('Steuerliches Datum', ''), values.get('Vorgang', ''), values.get('WKN', ''),
        values.get('Betrag Brutto', ''), values.get('Steuerbemessungsgrundlage', ''),
        values.get('Summe Steuern', '')]
    return 'comdirect-tax:' + hashlib.sha256('\x1f'.join(material).encode('utf-8')).hexdigest()


def parse_comdirect_tax_detail(path, account=None):
    raw, rows = _read_rows(path)
    header_index = next((i for i, row in enumerate(rows) if tuple(row[:len(COLUMNS)]) == COLUMNS), None)
    if header_index is None:
        raise ValueError('Die 32 Spalten des comdirect-Steuerexports wurden nicht gefunden.')
    metadata = {row[0].strip().rstrip(':'): row[1].strip() for row in rows[:header_index]
                if len(row) >= 2 and row[0].strip() and row[1].strip()}
    institution = metadata.get('Institut', metadata.get('Kreditinstitut', 'comdirect'))
    source_account = account or f"comdirect Steuerdaten {Path(path).stem.split('_')[-2] if '_' in Path(path).stem else ''}".strip()
    records = []
    for number, row in enumerate(rows[header_index + 1:], start=header_index + 2):
        if not any(cell.strip() for cell in row):
            continue
        if len(row) < len(COLUMNS):
            raise ValueError(f'CSV-Zeile {number} enthält nur {len(row)} statt 32 Spalten.')
        values = dict(zip(COLUMNS, row[:len(COLUMNS)]))
        if not values['Steuerjahr'].strip():
            continue
        records.append(TaxDetailRecord(
            external_id=stable_identity(source_account, values), institution=institution,
            account=source_account, source_format='comdirect_tax_detail_v1',
            original_values=values, source_reference=values['Referenznummer'].strip()))
    if not records:
        raise ValueError('Der comdirect-Steuerexport enthält keine Buchungen.')
    return ImportBatch(path=str(Path(path)), file_hash=hashlib.sha256(raw).hexdigest(),
                       account_names=[source_account], tax_details=records,
                       plugin_id='comdirect_tax_detail', plugin_version='1.0',
                       plugin_handler='portfolio_v5.comdirect_tax_detail.parse_comdirect_tax_detail')


def date_value(values, name):
    return _iso(values.get(name, ''))
