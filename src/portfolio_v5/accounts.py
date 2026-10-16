"""Account names from the account block in column A of the ETF overview."""
from pathlib import Path


def account_name(value):
    name = ' '.join(str(value).split()) if value is not None else ''
    return {'ing': 'Ing Diba', 'ing diba': 'Ing Diba',
            'zero': 'Finanzen zero', 'finanzen zero': 'Finanzen zero',
            'comdirect': 'Comdirect'}.get(name.casefold(), name)


def account_key(value):
    return account_name(value).casefold()


def canonical_depot(name):
    """Return the physical depot name encoded in a portfolio-transfer alias."""
    transferred = name.split(' / ', 2)
    return transferred[2] if len(transferred) == 3 else name


def overview_accounts(rows):
    # Anything after the first total belongs to allocation/planning tables.
    end = next((i for i, row in enumerate(rows)
                if row and str(row[0]).strip().casefold() in {'gesamt', 'summe', 'total'}), None)
    if end is None:
        raise ValueError('ETF: Summenzeile fehlt; Kontenblock nicht eindeutig erkennbar.')
    result = {}
    for index, row in enumerate(rows[1:end], 2):
        value = row[0] if row else None
        if not isinstance(value, str):
            continue
        name = account_name(value)
        if not name or name.startswith(('#', '=')) or name.casefold() in {'konto', 'konten', 'bank', 'jahr'}:
            continue
        result.setdefault(account_key(name), {'name': name, 'row': index})
    return list(result.values())


def discover_accounts(folder, progress=None):
    from .importers import read_sheets
    folder = Path(folder)
    paths = sorted(p for p in folder.iterdir() if p.is_file()
                   and p.suffix.lower() in {'.xls', '.xlsx'} and not p.name.startswith('~$'))
    candidates, warnings = {}, []
    for index, path in enumerate(paths, 1):
        if progress:
            progress(index, len(paths))
        try:
            sheets = read_sheets(path, sheet_name='etf')
            if not sheets:
                warnings.append(f'{path.name}: Tabellenblatt ETF fehlt.')
            for sheet, rows in sheets.items():
                for entry in overview_accounts(rows):
                    item = candidates.setdefault(account_key(entry['name']),
                                                 {'name': entry['name'], 'sources': []})
                    item['sources'].append(f'{path.name} / {sheet}!A{entry["row"]}')
        except Exception as exc:
            warnings.append(f'{path.name}: {exc}')
    return {'accounts': sorted(candidates.values(), key=lambda x: x['name'].casefold()),
            'warnings': warnings, 'files': len(paths)}
