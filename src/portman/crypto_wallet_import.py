import csv
from hashlib import sha256
from datetime import time
from io import StringIO
from decimal import Decimal
from pathlib import Path
from portfolio_v5.models import (ImportBatch, Snapshot, Position, BankTransaction,
                                 correction_number, number, parse_date, digest, norm, valid_isin)


COLUMNS = ('Dateiname', 'Depot-Nr.', 'Stamm-Nr.', 'Vorgangs-Nr.', 'WKN', 'ISIN',
           'Wertpapierbezeichnung', 'Auftragsdatum', 'Handelsdatum', 'Handelsuhrzeit',
           'Valuta', 'Nominale', 'Ausführungs-Kurs', 'Kurswert', 'Endbetrag',
           'Ausführungsplatz', 'Nominale_num', 'Kurswert_num', 'Endbetrag_num')
MODES = {'Nur Käufe / Zugänge': 'buys', 'Kauf / Verkauf im Dateinamen': 'filename',
         'Verkäufe mit negativer Nominale': 'signed'}


def csv_amount(row, field):
    raw = row[field + '_num'].strip()
    parsed = correction_number(raw) if raw else number(row[field])
    if parsed is None:
        raise ValueError(f'{field} fehlt.')
    return Decimal(parsed)


def read_wallet_csv(path, account, mode='buys', cancelled=None):
    if mode not in MODES.values():
        raise ValueError('Unbekannte Kauf-/Verkaufserkennung.')
    content = Path(path).read_bytes()
    try:
        text = content.decode('utf-8-sig')
    except UnicodeDecodeError:
        text = content.decode('cp1252')
    first = next((line for line in text.splitlines() if line.strip()), '')
    separator = max((';', ',', '\t'), key=first.count)
    reader = csv.DictReader(StringIO(text.lstrip('\r\n')), delimiter=separator, strict=True)
    reader.fieldnames = [h.strip() for h in (reader.fieldnames or [])]
    missing = set(COLUMNS) - set(reader.fieldnames)
    if missing:
        raise ValueError('CSV-Spalten fehlen: ' + ', '.join(sorted(missing)))
    if len(set(reader.fieldnames)) != len(reader.fieldnames):
        raise ValueError('Doppelte CSV-Spalten.')
    try:
        rows = list(reader)
    except csv.Error as error:
        raise ValueError(f'Ungültiges CSV-Format: {error}') from error
    total_fields = {'Kurswert', 'Endbetrag', 'Kurswert_num', 'Endbetrag_num'}
    if rows and all(not value.strip() for key, value in rows[-1].items()
                    if key not in total_fields and isinstance(value, str)) and None not in rows[-1]:
        footer = rows[-1]
        if any(footer.get(key) for key in total_fields):
            for field in ('Kurswert', 'Endbetrag'):
                if footer.get(field) or footer.get(field + '_num'):
                    try:
                        expected = csv_amount(footer, field)
                        actual = sum((csv_amount(row, field) for row in rows[:-1]), Decimal(0))
                    except (ValueError, AttributeError, KeyError) as error:
                        raise ValueError(f'Summenzeile nicht prüfbar: {error}') from error
                    if expected != actual:
                        raise ValueError(f'Summenzeile {field}: {expected} stimmt nicht mit {actual} überein.')
            rows.pop()
    for field in ('Depot-Nr.', 'Stamm-Nr.'):
        known = {row.get(field, '').strip() for row in rows if row.get(field, '').strip()}
        if len(known) > 1:
            raise ValueError('Die CSV enthält mehrere Depot-/Stammnummern. Bitte eine Datei pro Wallet verwenden.')
        if known:
            for row in rows:
                if row.get(field) is not None and not row[field].strip():
                    row[field] = next(iter(known))
    trades, seen, sources = [], {}, set()
    for index, row in enumerate(rows, 2):
        if cancelled and cancelled():
            raise ValueError('Import abgebrochen.')
        if not any(row.values()):
            continue
        try:
            if None in row or any(value is None for value in row.values()):
                raise ValueError('Spaltenanzahl stimmt nicht mit der Kopfzeile überein.')
            row = {key: value.strip() for key, value in row.items()}
            name = row['Wertpapierbezeichnung']
            if not name:
                raise ValueError('Wertpapierbezeichnung fehlt.')
            isin, wkn = row['ISIN'].upper(), row['WKN'].upper()
            key = isin if valid_isin(isin) else ('WKN:' + wkn if len(wkn) == 6 and wkn.isalnum()
                                                else 'KRYPTO:' + norm(isin or wkn or name))
            date = parse_date(row['Handelsdatum'] or row['Auftragsdatum'] or row['Valuta'])
            if not date:
                raise ValueError('Gültiges Handelsdatum fehlt.')
            clock = row['Handelsuhrzeit']
            if clock:
                try:
                    if clock.count(':') == 3:
                        clock, fraction = clock.rsplit(':', 1)
                        if not fraction.isdigit() or len(fraction) > 6:
                            raise ValueError('Ungültige Sekundenbruchteile.')
                        clock += '.' + fraction
                    clock = time.fromisoformat(clock.zfill(5) if len(clock) <= 5 else clock.zfill(8)).isoformat()
                except ValueError:
                    raise ValueError('Ungültige Handelsuhrzeit.') from None
            quantity, amount = csv_amount(row, 'Nominale'), abs(csv_amount(row, 'Endbetrag'))
            if not quantity or not amount:
                raise ValueError('Nominale und Endbetrag müssen ungleich null sein.')
            filename = norm(row['Dateiname'])
            selling = 'verkauf' in filename or 'sell' in filename
            buying = ('kauf' in filename and not selling) or 'buy' in filename
            if mode == 'filename' and (not selling and not buying):
                raise ValueError('Kauf oder Verkauf im Dateinamen nicht erkennbar.')
            if mode == 'buys' and (selling or quantity < 0):
                raise ValueError('Verkauf erkannt. Bitte passende Kauf-/Verkaufserkennung wählen.')
            sell = selling if mode == 'filename' else mode == 'signed' and quantity < 0
            source = (row['Depot-Nr.'], row['Stamm-Nr.'])
            sources.add(source)
            identity = (*source, row['Vorgangs-Nr.'] or row['Dateiname'])
            if not identity[-1]:
                raise ValueError('Vorgangs-Nr. oder Dateiname zur Duplikaterkennung fehlt.')
            if identity in seen:
                if seen[identity] == row:
                    continue
                raise ValueError('Vorgang mehrfach mit unterschiedlichen Daten enthalten.')
            seen[identity] = row
            trades.append((date, clock, index, key, name, abs(quantity), amount, sell, row, identity))
        except ValueError as error:
            raise ValueError(f'Zeile {index}: {error}') from error
    if not trades:
        raise ValueError('Die CSV enthält keine Buchungen.')
    if len(sources) > 1:
        raise ValueError('Die CSV enthält mehrere Depot-/Stammnummern. Bitte eine Datei pro Wallet verwenden.')
    batch = ImportBatch(str(path), sha256(content).hexdigest(), source_sheet='Krypto Wallet CSV')
    lots, metadata = {}, {}
    trades.sort()
    for trade_index, (date, trade_time, index, key, name, quantity, amount, sell, row, identity) in enumerate(trades):
        if cancelled and cancelled():
            raise ValueError('Import abgebrochen.')
        queue = lots.setdefault(key, [])
        isin, wkn = row['ISIN'].upper(), row['WKN'].upper()
        metadata[key] = (name, isin if valid_isin(isin) else '',
                         wkn if len(wkn) == 6 and wkn.isalnum() else '')
        if sell:
            if sum((lot[0] for lot in queue), Decimal(0)) < quantity:
                raise ValueError(f'Zeile {index}: Verkauf übersteigt den vorhandenen Bestand von {name}. Kaufhistorie fehlt.')
            remaining = quantity
            while remaining:
                units, cost = queue[0]
                used = min(units, remaining)
                if used == units:
                    queue.pop(0)
                else:
                    queue[0] = (units - used, cost * (units - used) / units)
                remaining -= used
        else:
            queue.append((quantity, amount))
        batch.transactions.append(BankTransaction(account, 'crypto-csv-' + digest(identity), date,
            'SELL' if sell else 'BUY', str(amount), 'EUR', key, str(quantity), row=index,
            value_date=parse_date(row['Valuta']) or date, bank_reference=row['Vorgangs-Nr.'],
            purpose=name, raw_text=str(row), affects_cash=False))
        if trade_index + 1 < len(trades) and trades[trade_index + 1][0] == date:
            continue
        positions = [Position(k, *metadata[k], asset_type='Krypto',
            quantity=str(sum((lot[0] for lot in entries), Decimal(0))),
            cost=str(sum((lot[1] for lot in entries), Decimal(0))))
            for k, entries in lots.items() if entries]
        snapshot = Snapshot(account, date[:7], date, 'Krypto Wallet CSV', positions)
        batch.snapshots.append(snapshot)
    return batch


def save_wallet(repo, name, details, parent, batch, cancelled=None):
    from .import_v09 import transaction
    from copy import deepcopy
    prepared = deepcopy(batch)
    for row in prepared.snapshots + prepared.transactions:
        row.account = name
    if cancelled and cancelled():
        raise ValueError('Import abgebrochen.')
    backups = getattr(repo, 'backups_enabled', False)
    if backups:
        repo.backup('before-import')
        repo.backups_enabled = False
    try:
        with transaction(repo, commit=True):
            if cancelled and cancelled():
                raise ValueError('Import abgebrochen.')
            repo.save_account(name, details, parent)
            result = repo.commit_batches([prepared])[0]
            if result['status'] != 'imported':
                raise ValueError('; '.join(result.get('errors', ['Diese Datei wurde bereits importiert.'])))
            from .wallet_valuation import save_daily_values
            for record in repo.market.records().values():
                save_daily_values(repo.db, record.get('data', {}))
            if cancelled and cancelled():
                raise ValueError('Import abgebrochen.')
    finally:
        if backups:
            repo.backups_enabled = True
