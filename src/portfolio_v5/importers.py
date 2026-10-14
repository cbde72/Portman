"""Read-only adapters for the existing Excel archive and broker exports.

Never evaluates workbook formulas or performs network requests. Cached source
values and their provenance are retained, with malformed sections quarantined.
"""
import csv
import hashlib
import io
import re
import warnings
import zipfile
from collections import Counter
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from xml.etree import ElementTree as ET

from .models import Balance, ImportBatch, Position, Snapshot, Transaction, money, norm, number, parse_date, text

PARSER_VERSION = '5.1.0'

# File contents are hashed once per working session. The cache is keyed by
# (mtime_ns, size), so edits are still detected while repeated per-sheet
# parses of the same workbook skip a full disk re-read.
_DIGEST_CACHE = {}


def file_digest(path):
    path = Path(path)
    try:
        stat = path.stat()
    except OSError:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    key = (stat.st_mtime_ns, stat.st_size)
    cached = _DIGEST_CACHE.get(str(path))
    if cached and cached[0] == key:
        return cached[1]
    value = hashlib.sha256(path.read_bytes()).hexdigest()
    _DIGEST_CACHE[str(path)] = (key, value)
    return value


def read_sheets(path, sheet_name=None):
    path = Path(path)
    if path.suffix.lower() == '.xlsx':
        import openpyxl
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', UserWarning)
            book = openpyxl.load_workbook(path, data_only=True, read_only=True)
            try:
                return {s.title: [list(r) for r in s.iter_rows(values_only=True)] for s in book
                        if sheet_name is None or s.title.strip().casefold() == sheet_name.casefold()}
            finally:
                book.close()
    if path.suffix.lower() == '.xls':
        import xlrd
        book = xlrd.open_workbook(path, on_demand=True)
        result = {}
        for name in book.sheet_names():
            if sheet_name is not None and name.strip().casefold() != sheet_name.casefold():
                continue
            sheet = book.sheet_by_name(name)
            result[sheet.name] = [[xlrd.xldate_as_datetime(c.value, book.datemode) if c.ctype == xlrd.XL_CELL_DATE
                                   else ('#EXCEL_ERROR' if c.ctype == xlrd.XL_CELL_ERROR else c.value)
                                   for c in sheet.row(i)] for i in range(sheet.nrows)]
        book.release_resources()
        return result
    if path.suffix.lower() == '.ods':
        ns = {'t': 'urn:oasis:names:tc:opendocument:xmlns:table:1.0',
              'o': 'urn:oasis:names:tc:opendocument:xmlns:office:1.0',
              'x': 'urn:oasis:names:tc:opendocument:xmlns:text:1.0'}
        with zipfile.ZipFile(path) as archive:
            root = ET.fromstring(archive.read('content.xml'))
        result = {}
        for sheet in root.findall('.//t:table', ns):
            rows = []
            for row in sheet.findall('t:table-row', ns):
                values = []
                for cell in row:
                    typ = cell.get('{%s}value-type' % ns['o'])
                    value = '\n'.join(''.join(p.itertext()) for p in cell.findall('x:p', ns))
                    if typ in ('float', 'percentage', 'currency'):
                        value = Decimal(cell.get('{%s}value' % ns['o'], '0'))
                    elif typ == 'date':
                        value = cell.get('{%s}date-value' % ns['o'])
                    repeat = min(int(cell.get('{%s}number-columns-repeated' % ns['t'], '1')), 256)
                    values.extend([value] * repeat)
                if any(text(v) for v in values):
                    repeat = min(int(row.get('{%s}number-rows-repeated' % ns['t'], '1')), 10000)
                    rows.extend([values] * repeat)
            result[sheet.get('{%s}name' % ns['t'])] = rows
        return result
    if path.suffix.lower() == '.csv':
        raw = path.read_bytes()
        try:
            content = raw.decode('utf-8-sig')
        except UnicodeDecodeError:
            content = raw.decode('cp1252')
        delimiter = ';' if content.count(';') >= content.count('\t') else '\t'
        return {'CSV': list(csv.reader(io.StringIO(content), delimiter=delimiter))}
    raise ValueError(f'Nicht unterstütztes Format: {path.suffix}')


def file_period(path):
    match = re.search(r'finanzen(\d{4})-(\d{1,2})', Path(path).stem, re.I)
    if match:
        year, month = map(int, match.groups())
        return datetime(year, month, 1).strftime('%Y-%m')
    return None


def file_date(path):
    name = Path(path).stem
    d = parse_date(name)
    if d:
        return d
    match = re.search(r'(20\d{2})(\d{2})(\d{2})(?:-|$)', name)
    if match:
        return datetime(*map(int, match.groups())).date().isoformat()
    return None


def cell(row, index):
    return row[index] if index is not None and index < len(row) else None


def field(headers, names):
    wanted = {norm(n) for n in names}
    return next((i for i, h in enumerate(headers) if norm(h) in wanted), None)


def asset_type(name, raw):
    joined = (text(name) + ' ' + text(raw)).upper()
    if any(w in joined for w in ('BITCOIN', 'KRYPTO', 'CRYPTO')):
        return 'Krypto'
    if any(w in joined for w in ('ETF', 'UCITS', 'ISHS', 'IS C.', 'ISIV-', 'ISHSV')):
        return 'ETF'
    if 'FONDS' in joined or 'FUND' in joined:
        return 'Fonds'
    if any(w in joined for w in ('AKTIE', 'STOCK', 'INC.', ' AG', ' SE', ' PLC', 'CORP')):
        return 'Aktie'
    return 'Sonstiges'


def table_date(rows):
    # Explicit document date wins over individual quote dates.
    dates = set()
    for row in rows:
        for i, value in enumerate(row):
            label = norm(value)
            if label.startswith(('depotubersichtvom', 'depotbewertungvom', 'stichtag', 'datenstand', 'standvom')):
                if d := parse_date(value):
                    dates.add(d)
            if label in ('datum', 'stand', 'bewertungsdatum', 'stichtag', 'datenstand', 'standvom'):
                if d := parse_date(cell(row, i + 1)):
                    dates.add(d)
    if len(dates) > 1:
        raise ValueError('Widersprüchliche Stichtage im Tabellenblatt: ' + ', '.join(sorted(dates)))
    return next(iter(dates), None)


def parse_positions(rows, sheet, path, period, override_date=None, override_account=None, complete=True, sheet_date_only=False):
    header_idx = None
    for i, row in enumerate(rows):
        if field(row, ['ISIN', 'WKN']) is not None and field(row, ['Bezeichnung', 'Wertpapiername', 'Name']) is not None:
            header_idx = i
            break
    if header_idx is None:
        return None
    headers = rows[header_idx]
    indexes = {
        'isin': field(headers, ['ISIN']), 'wkn': field(headers, ['WKN']),
        'name': field(headers, ['Name', 'Bezeichnung', 'Wertpapiername']),
        'quantity': field(headers, ['Anzahl', 'Stück/Nominale', 'Stück / Nominale', 'Stück/Nom.', 'Bestand']),
        'cost': field(headers, ['Kaufwert', 'Kaufwert in EUR', 'Einstandswert']),
        'value': field(headers, ['Wert', 'Wert in EUR', 'Kurswert']),
        'type': field(headers, ['Art', 'Typ']), 'currency': field(headers, ['Währung']),
        'quote': field(headers, ['Kursdatum', 'Datum', 'Zeit'])}
    if indexes['value'] is None:
        return None
    profile = norm(sheet)
    if sheet == 'CSV':
        profile = 'ing' if field(headers, ['Einstandswert']) is not None else ('zero' if field(headers, ['Art']) is not None else 'comdirect')
    account = override_account or {'ing': 'ING', 'comdirect': 'comdirect', 'zero': 'ZERO', 'deka': 'Deka'}.get(profile, sheet)
    document_date = table_date(rows)
    d = document_date if sheet_date_only else override_date or document_date or file_date(path)
    basis = 'document' if sheet_date_only else ('manual' if override_date else ('document' if document_date else ('filename' if file_date(path) else 'month')))
    dates = [parse_date(cell(r, indexes['quote'])) for r in rows[header_idx + 1:]]
    dates = [v for v in dates if v]
    if not d and dates:
        d = max(dates)
        basis = 'quote'
    if sheet_date_only:
        if not d:
            raise ValueError(f'{sheet}: Kein Datum im Tabellenblatt gefunden; Stichtag wird nicht aus dem Dateinamen übernommen.')
        period = d[:7]
    if not period and d:
        period = d[:7]
    if not period:
        raise ValueError(f'{sheet}: Kein Stichtag erkennbar. Im Importdialog Datum angeben.')
    snapshot = Snapshot(account, period, d, sheet, complete=complete, date_basis=basis)
    if not d:
        snapshot.warnings.append('Nur Berichtsmonat bekannt; kein tagesgenauer Stichtag.')
    elif d[:7] != period:
        snapshot.warnings.append(f'Datenstand {d} weicht vom Dateimonat {period} ab; kein neuer Monatsbestand.')
    if basis == 'quote':
        snapshot.warnings.append('Stichtag aus Kursdaten abgeleitet.')
    seen = set()
    invalid = []
    for rownum, row in enumerate(rows[header_idx + 1:], header_idx + 2):
        isin = text(cell(row, indexes['isin'])).upper()
        wkn = text(cell(row, indexes['wkn'])).upper()
        if isinstance(cell(row, indexes['wkn']), (float, int)):
            wkn = str(int(cell(row, indexes['wkn']))).zfill(6)
        if not re.fullmatch(r'[A-Z]{2}[A-Z0-9]{9}\d', isin):
            isin = ''
        if not re.fullmatch(r'[A-Z0-9]{6}', wkn):
            wkn = ''
        if not isin and not wkn:
            continue
        name = text(cell(row, indexes['name']))
        key = isin or 'WKN:' + wkn
        try:
            pos = Position(key, name or key, isin, wkn, asset_type(name, cell(row, indexes['type'])),
                           number(cell(row, indexes['quantity'])), money(cell(row, indexes['cost'])),
                           money(cell(row, indexes['value'])), text(cell(row, indexes['currency'])) or 'EUR',
                           parse_date(cell(row, indexes['quote'])), rownum)
            # ING has several currency columns: the column following Kurswert is the valuation currency.
            if norm(cell(headers, indexes['value'] + 1)) == 'wahrung':
                pos.currency = text(cell(row, indexes['value'] + 1)) or 'EUR'
            if 'ineur' in norm(cell(headers, indexes['value'])):
                pos.currency = 'EUR'
            if pos.value is None or pos.quantity is None:
                raise ValueError('Menge oder Marktwert fehlt')
            if pos.currency != 'EUR':
                raise ValueError(f'Bewertungswährung {pos.currency}: EUR-Umrechnung erforderlich')
            if key in seen:
                raise ValueError(f'Doppelte Position {key}')
            seen.add(key)
            snapshot.positions.append(pos)
        except ValueError as exc:
            invalid.append(f'Zeile {rownum}: {exc}')
    if invalid:
        raise ValueError(f'{sheet}: Abschnitt nicht übernommen: ' + '; '.join(invalid))
    if not snapshot.positions:
        return None
    # ZERO exports its crypto wallet separately from the securities depot.
    # A complete wallet export must never replace the securities snapshot.
    if profile == 'zero' and sheet == 'CSV' and not override_account and all(p.asset_type == 'Krypto' for p in snapshot.positions):
        snapshot.account = 'ZERO/Krypto'
    for row in rows:
        for i, value in enumerate(row):
            if norm(value) == 'depotwert':
                try:
                    declared = money(cell(row, i + 2))
                    total = sum(Decimal(p.value) for p in snapshot.positions)
                    if declared is not None and abs(Decimal(declared) - total) > Decimal('.10'):
                        raise ValueError(f'{sheet}: Depotwert {declared} stimmt nicht mit Positionssumme {total} überein.')
                except ValueError:
                    raise
    return snapshot


def parse_deka(rows, sheet, period):
    """Older DEKA tables are transposed, with Unterdepot per column."""
    labels = {}
    for i, row in enumerate(rows):
        labels.setdefault(norm(cell(row, 0)), i)
    if not {'isin', 'bestand', 'wert'}.issubset(labels):
        return None
    result = []
    for col in range(1, len(rows[labels['isin']])):
        isin = text(cell(rows[labels['isin']], col))
        if not re.fullmatch(r'[A-Z]{2}[A-Z0-9]{9}\d', isin):
            continue
        sub = text(cell(rows[labels['unterdepot']], col)) if 'unterdepot' in labels else str(col)
        if sub.endswith('.0'):
            sub = sub[:-2]
        d = parse_date(cell(rows[labels['bewertungsdatum']], col)) if 'bewertungsdatum' in labels else None
        p = Position(isin, text(cell(rows[labels.get('bezeichnung', labels['isin'])], col)), isin=isin,
                     asset_type='Fonds', quantity=number(cell(rows[labels['bestand']], col)),
                     value=money(cell(rows[labels['wert']], col)), row=labels['wert'] + 1)
        if p.value is None:
            raise ValueError('Deka: Marktwert fehlt')
        result.append(Snapshot('Deka/' + sub, period or (d or '')[:7], d, sheet, [p], date_basis='document' if d else 'month'))
    return result


def parse_overview(rows, sheet, period, batch):
    if not period:
        batch.warnings.append(f'{sheet}: Jahresdatei ohne Monatszuordnung; Vermögensübersicht nicht übernommen.')
        return
    header = rows[0] if rows else []
    categories = {'bausparen': 'Bausparen', 'festgeld': 'Festgeld', 'tagesgeld': 'Liquidität',
                  'aktienoderfond': 'Wertpapiere', 'aktienfond': 'Wertpapiere', 'aktien': 'Wertpapiere',
                  'aktienkrypto': 'Wertpapiere', 'altersvorsorge': 'Altersvorsorge'}
    cols = {i: categories[norm(v)] for i, v in enumerate(header) if norm(v) in categories}
    if not cols:
        batch.warnings.append(f'{sheet}: Unbekanntes Übersichtsformat.')
        return
    total_idx = next((i for i, r in enumerate(rows[:30]) if norm(cell(r, 0)) == 'gesamt'), None)
    if total_idx is None:
        batch.warnings.append(f'{sheet}: Summenzeile fehlt; Übersicht nicht übernommen.')
        return
    staged = []
    account = ''
    for i, row in enumerate(rows[1:total_idx], 2):
        label = text(cell(row, 0))
        if label:
            account = label
        if not account:
            continue
        for col, category in cols.items():
            if norm(account) == 'darlehen' and col != min(cols):
                continue  # Other cells in this row contain unrelated planning annotations.
            raw = cell(row, col)
            if raw is None or not text(raw):
                continue
            try:
                amount = money(raw)
                if amount is None:
                    continue
                cat = 'Schulden' if norm(account) == 'darlehen' else category
                if cat == 'Schulden':
                    amount = str(abs(Decimal(amount)))
                staged.append(Balance(period, cat, account, amount, sheet, i))
            except ValueError as exc:
                batch.warnings.append(f'{sheet}!Zeile {i}: {exc}; Übersicht zur Prüfung zurückgestellt.')
                return
    # Per-column sums can exclude cells containing numeric text; preserve the difference for review.
    for category in set(cols.values()):
        declared = []
        for col, cat in cols.items():
            if cat == category:
                try:
                    val = money(cell(rows[total_idx], col))
                    if val is not None:
                        declared.append(Decimal(val))
                except ValueError:
                    pass
        actual = sum(Decimal(b.value) for b in staged if b.category == category)
        if declared and abs(sum(declared) - actual) > Decimal('.10'):
            batch.warnings.append(f'{sheet}: {category}: Einzelwerte {actual} / Excel-Summe {sum(declared)}. Einzelwerte übernommen.')
    batch.balances.extend(staged)


def parse_timeline(rows, sheet, batch):
    # Existing overview is authoritative. Timeline provides a separate audit series,
    # never additive balances, and ambiguous duplicated months are quarantined.
    parsed = []
    for i, row in enumerate(rows, 1):
        try:
            year = int(cell(row, 0))
            month = int(re.match(r'\d+', text(cell(row, 1))).group())
            period = datetime(year, month, 1).strftime('%Y-%m')
            if not 2000 <= year <= 2100:
                continue
            vals = [(category, money(cell(row, col))) for category, col in [('Archiv: Liquidität/Festgeld', 5), ('Archiv: Wertpapiere', 8), ('Immobilie (Schätzung)', 2)]]
            parsed.append((period, i, vals))
        except (ValueError, TypeError, AttributeError):
            continue
    counts = Counter(p for p, _, _ in parsed)
    for period, row, vals in parsed:
        if counts[period] > 1:
            batch.warnings.append(f'{sheet}!Zeile {row}: Monat {period} doppelt; Verlaufspunkt zurückgestellt.')
            continue
        for category, value in vals:
            if value is not None:
                batch.balances.append(Balance(period, category, 'Archiv', value, sheet, row, 10))


KINDS = {'BUY', 'SELL', 'DIVIDEND', 'INTEREST', 'DEPOSIT', 'WITHDRAWAL', 'FEE', 'TAX', 'TRANSFER_IN', 'TRANSFER_OUT'}


def parse_transactions(rows, batch):
    headers = [text(v).lower() for v in rows[0]] if rows else []
    required = {'transaction_id', 'account', 'date', 'type', 'amount', 'currency'}
    if not required.issubset(headers):
        return False
    transactions = []
    for i, row in enumerate(rows[1:], 2):
        if not any(text(v) for v in row):
            continue
        data = {h: cell(row, idx) for idx, h in enumerate(headers)}
        try:
            kind = text(data['type']).upper()
            d = parse_date(data['date'])
            amount = money(data['amount'])
            if kind not in KINDS or not d or amount is None:
                raise ValueError('Ungültiges Datum, Typ oder Betrag')
            if not text(data['transaction_id']) or not text(data['account']):
                raise ValueError('transaction_id und account sind Pflichtfelder')
            if text(data['currency']).upper() != 'EUR':
                raise ValueError('Beträge müssen in EUR vorliegen')
            positive = kind in {'SELL', 'DIVIDEND', 'INTEREST', 'DEPOSIT', 'TRANSFER_IN'}
            if (positive and Decimal(amount) < 0) or (not positive and Decimal(amount) > 0):
                raise ValueError('Vorzeichen passt nicht zum Transaktionstyp')
            security = text(data.get('isin') or data.get('security'))
            quantity = number(data.get('quantity'))
            if kind in {'BUY', 'SELL'} and (not security or quantity is None or Decimal(quantity) <= 0):
                raise ValueError('Kauf/Verkauf erfordert Wertpapierkennung und positive Stückzahl')
            fees, taxes = money(data.get('fees')), money(data.get('taxes'))
            if any(v is not None and Decimal(v) < 0 for v in (fees, taxes)):
                raise ValueError('Gebühren/Steuern als positive enthaltene Beträge angeben')
            transactions.append(Transaction(text(data['account']), text(data['transaction_id']), d, kind,
                                            amount, 'EUR', security, quantity, fees, taxes, i))
        except ValueError as exc:
            batch.errors.append(f'Transaktionen Zeile {i}: {exc}')
    if not batch.errors:
        batch.transactions = transactions
    return True


def parse_file(path, as_of=None, account=None, complete=True, *, sheets=None, sheet_date_only=False,
               document_tags=None, plugin_catalog=None):
    path = Path(path).resolve()
    if path.suffix.lower() == '.pdf':
        from .pdf_importer import parse_pdf
        return parse_pdf(path, document_tags=document_tags, plugin_catalog=plugin_catalog)
    batch = ImportBatch(str(path), file_digest(path))
    try:
        sheets = read_sheets(path) if sheets is None else sheets
        period = file_period(path)
        if path.suffix.lower() == '.csv' and parse_transactions(sheets['CSV'], batch):
            return batch
        for sheet, rows in sheets.items():
            try:
                n = norm(sheet)
                if n in ('ing', 'comdirect', 'zero', 'csv'):
                    snapshot = parse_positions(rows, sheet, path, period, as_of, account, complete, sheet_date_only)
                    if snapshot:
                        batch.snapshots.append(snapshot)
                    else:
                        batch.warnings.append(f'{sheet}: Keine unterstützte Positionstabelle gefunden.')
                elif n == 'deka':
                    deka = parse_deka(rows, sheet, period)
                    if deka:
                        batch.snapshots.extend(deka)
                    else:
                        batch.warnings.append('Deka: Ausschüttungs-/Zusatzblatt; Bestand nur aus Vermögensübersicht.')
                elif n == 'etf':
                    from .accounts import overview_accounts
                    batch.account_names.extend(entry['name'] for entry in overview_accounts(rows))
                    parse_overview(rows, sheet, period, batch)
                elif n == 'verlauf':
                    parse_timeline(rows, sheet, batch)
                elif n == 'ebase':
                    batch.warnings.append('ebase: Historischer Spezialbericht; keine neuen Positionen abgeleitet. Übersichtsbestand separat.')
                else:
                    snapshot = parse_positions(rows, sheet, path, period, as_of, account, complete, sheet_date_only)
                    if snapshot:
                        batch.snapshots.append(snapshot)
            except (ValueError, TypeError, IndexError) as exc:
                batch.warnings.append(str(exc))
        if not batch.snapshots and not batch.balances:
            batch.errors.append('Keine importierbaren Bestände erkannt. Format und Stichtag prüfen.')
    except (ValueError, TypeError, IndexError) as exc:
        batch.errors.append(f'{type(exc).__name__}: {exc}')
    return batch
