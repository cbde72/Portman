"""Deka annual report tables with separate subaccounts and source rows."""
from portfolio_v5.importers import read_sheets, parse_file
from portfolio_v5.models import ImportBatch, Snapshot, Position, BankTransaction, digest, money, number, parse_date, text, norm
from portman.storage_v09 import file_hash


def sheet_kind(rows):
    headers = set(rows[0]) if rows else set()
    if {'depot', 'unterdepot', 'isin', 'datum', 'anteile', 'wert_eur', 'typ'} <= headers:
        return 'Bestände'
    if {'depot', 'unterdepot', 'isin', 'buchungstag', 'betrag_eur', 'anteile', 'umsatzart'} <= headers:
        return 'Umsätze'
    if {'stichtag', 'fonds', 'endbestand_eur'} <= headers or {'stichtag', 'fonds', 'wertentwicklung_eur'} <= headers:
        return 'Vergleichsblatt (nicht zusätzlich importieren)'
    return 'Standardtabelle'


def source_account(data):
    depot, sub = text(data.get('depot')), number(data.get('unterdepot'))
    if not depot or sub is None or float(sub) < 0 or not float(sub).is_integer():
        raise ValueError('Depot oder Unterdepot fehlt / ist ungültig.')
    return f'Deka {depot} · Unterdepot {int(float(sub)):02d}'


def parse_excel_file(path, sheets=None):
    sheets = read_sheets(path) if sheets is None else sheets
    batches = []
    for sheet, rows in sheets.items():
        kind = sheet_kind(rows)
        if kind.startswith('Vergleichsblatt'):
            continue
        if kind == 'Standardtabelle':
            batch = parse_file(path, sheets={sheet: rows}, sheet_date_only=True)
            batch.source_sheet = sheet
            batches.append(batch)
            continue
        batch = ImportBatch(str(path), file_hash(path), source_sheet=sheet, document_type='Deka Excel · ' + kind)
        grouped = {}
        seen = {}
        occurrences = {}
        for row_number, row in enumerate(rows[1:], 2):
            if not any(text(v) for v in row):
                continue
            data = dict(zip(rows[0], row))
            try:
                account = source_account(data)
                isin = text(data.get('isin'))
                if len(isin) != 12:
                    raise ValueError('ISIN fehlt / ist ungültig.')
                if kind == 'Bestände':
                    day = parse_date(data.get('datum'))
                    quantity, value = number(data.get('anteile')), money(data.get('wert_eur'))
                    if not day or quantity is None or value is None or float(quantity) < 0 or float(value) < 0:
                        raise ValueError('Datum, Bestand oder Wert fehlt / ist ungültig.')
                    key = account, day, isin
                    values = quantity, value
                    if key in seen:
                        if seen[key] != values:
                            raise ValueError('Widersprüchliche Bestände für dasselbe Unterdepot, Datum und Wertpapier.')
                        continue
                    seen[key] = values
                    snapshot = grouped.setdefault((account, day), Snapshot(account, day[:7], day, sheet, complete=False))
                    snapshot.positions.append(Position(isin, text(data.get('fonds')) or isin, isin=isin,
                        asset_type='Fonds', quantity=quantity, value=value, quote_date=day, row=row_number))
                else:
                    day = parse_date(data.get('buchungstag'))
                    amount, quantity = money(data.get('betrag_eur')), number(data.get('anteile'))
                    if not day or amount is None or quantity is None or float(amount) < 0 or float(quantity) < 0:
                        raise ValueError('Datum, Betrag oder Anteile fehlt / ist ungültig.')
                    operation = norm(data.get('umsatzart'))
                    if operation.startswith('thesaurierung') and float(amount) == 0 and float(quantity) == 0:
                        batch.warnings.append(f'{sheet}!{row_number}: Thesaurierung ohne Geld- oder Anteilsbewegung ausgelassen.')
                        continue
                    dividend = 'aussch' in operation
                    if not dividend and operation not in ('kauf', 'lastschrifteinzug'):
                        raise ValueError('Unbekannte Umsatzart: ' + text(data.get('umsatzart')))
                    if float(quantity) <= 0 or float(amount) <= 0:
                        raise ValueError('Kauf / Wiederanlage benötigt positive Anteile und Betrag.')
                    identity = digest([account, isin, day, parse_date(data.get('abrechnungstag')), operation, amount, quantity])
                    occurrences[identity] = occurrences.get(identity, 0) + 1
                    identity += ':' + str(occurrences[identity])
                    reference = next((text(data.get(column)) for column in
                        ('vorgangsnummer', 'vorgangs-nr.', 'referenz', 'buchungsreferenz',
                         'transaktionsnummer', 'transaktions-nr.') if text(data.get(column))), '')
                    common = dict(account=account, date=day, currency='EUR', security=isin, row=row_number,
                        value_date=parse_date(data.get('abrechnungstag')) or '', operation=text(data.get('umsatzart')),
                        purpose=text(data.get('quelle')), bank_reference=reference,
                        document_reference=reference, transaction_reference=reference, raw_text=repr(data),
                        withholding_tax=money(data.get('quellensteuer')),
                        withholding_country=text(data.get('quellenstaat')).upper(),
                        withholding_tax_rate=number(data.get('quellensteuersatz')),
                        tax_rate=number(data.get('steuersatz')))
                    if dividend:
                        batch.transactions.append(BankTransaction(**common, external_id='deka:' + identity + ':dividend', kind='DIVIDEND', amount=amount))
                    batch.transactions.append(BankTransaction(**common, external_id='deka:' + identity + ':buy', kind='BUY', amount='-' + amount, quantity=quantity))
            except (ValueError, TypeError) as error:
                batch.errors.append(f'{sheet}!Zeile {row_number}: {error}')
        batch.snapshots = sorted(grouped.values(), key=lambda s: (s.effective_date, s.account))
        batches.append(batch)
    return batches
