"""Sheet-by-sheet preparation and duplicate detection for the history batch."""
from pathlib import Path
import json
import logging
from portfolio_v5.importers import read_sheets, parse_file
from portfolio_v5.models import ImportBatch

logger = logging.getLogger(__name__)

SAVINGS_PREFIX = 'Tagesgeld/Festgeld · '


def savings_source(sheet, account, category):
    kind = 'Tagesgeld' if category == 'Liquidität' else 'Festgeld'
    return f'{SAVINGS_PREFIX}{sheet} · {account} · {kind}'


def parse_savings_history_file(path):
    """Split monthly overview balances by bank and category, keeping provenance."""
    from collections import defaultdict
    result = []
    for batch in parse_history_file(path, sheet_name='ETF'):
        groups = defaultdict(list)
        for balance in batch.balances:
            if balance.category in ('Liquidität', 'Festgeld'):
                groups[savings_source(balance.sheet, balance.account, balance.category)].append(balance)
        for name, balances in groups.items():
            result.append(ImportBatch(batch.path, batch.file_hash, balances=balances,
                warnings=list(batch.warnings), source_sheet=name))
        if not groups:
            result.append(ImportBatch(batch.path, batch.file_hash,
                source_sheet=SAVINGS_PREFIX + (batch.source_sheet or 'Dateifehler'),
                warnings=list(batch.warnings),
                errors=batch.errors or ['Keine Tagesgeld-/Festgeldstände mit Monatszuordnung erkannt.']))
    return result


def history_files(folder):
    folder = Path(folder)
    if not folder.is_dir():
        raise ValueError('Der Ordner history wurde nicht gefunden.')
    return sorted((p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in ('.xls', '.xlsx') and not p.name.startswith('~$')), key=lambda p: p.name.casefold())


def parse_history_file(path, sheet_name=None):
    try:
        sheets = read_sheets(path, sheet_name=sheet_name)
    except Exception as error:
        logger.exception('History-Datei konnte nicht eingelesen werden: %s', path)
        return [ImportBatch(str(path), '', errors=[f'Excel-Datei konnte vom Importer nicht eingelesen werden ({type(error).__name__}): {error}'])]
    result = []
    for sheet, rows in sheets.items():
        try:
            batch = parse_file(path, sheets={sheet: rows}, sheet_date_only=True)
            for balance in batch.balances:
                if balance.account == 'Archiv':
                    balance.account = 'Historie / ' + sheet
        except Exception as error:
            logger.exception('History-Blatt konnte nicht verarbeitet werden: %s', path)
            batch = ImportBatch(str(path), '', errors=[f'Blatt konnte nicht verarbeitet werden ({type(error).__name__}): {error}'])
        batch.source_sheet = sheet
        result.append(batch)
    missing = f'Das Tabellenblatt {sheet_name} fehlt.' if sheet_name else 'Die Datei enthält keine Tabellenblätter.'
    return result or [ImportBatch(str(path), '', errors=[missing])]


def sheet_import_index(repository):
    entries = {r['id']: r for r in repository.imports()}
    sheets = {iid: set() for iid in entries}
    for iid, entry in entries.items():
        name = json.loads(entry['report']).get('source_sheet')
        if name:
            sheets[iid].add(name)
    for row in repository.db.execute('SELECT import_id,sheet,account,category FROM balances'):
        sheets.setdefault(row['import_id'], set()).add(row['sheet'])
        if row['category'] in ('Liquidität', 'Festgeld'):
            sheets[row['import_id']].add(savings_source(row['sheet'], row['account'], row['category']))
    for row in repository.db.execute('SELECT import_id,payload FROM snapshots'):
        name = json.loads(row['payload']).get('sheet')
        if name:
            sheets.setdefault(row['import_id'], set()).add(name)
    index = {}
    for iid, entry in entries.items():
        path = str(Path(entry['path']).resolve()).casefold()
        for sheet in sheets[iid]:
            index.setdefault((path, sheet.strip().casefold()), []).append(iid)
    return index


def previous_sheet_imports(repository, batch, index=None):
    if index is None:
        index = sheet_import_index(repository)
    key = (str(Path(batch.path).resolve()).casefold(), batch.source_sheet.strip().casefold())
    return index.get(key, [])
