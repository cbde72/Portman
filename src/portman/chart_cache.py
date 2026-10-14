from copy import deepcopy
from decimal import Decimal
from pathlib import Path

from .persistence import atomic_json, read_json

SERIES_CACHE_FILE = 'chart-series-cache.json'


def _clone(value):
    """Schnelle typerhaltende Kopie für die bekannten Diagramm-Datenstrukturen.

    ``copy.deepcopy`` legt pro Aufruf eine Memo-Tabelle an und sucht bei jedem
    Knoten über ``__deepcopy__`` – für die JSON-artigen Reihen aus Listen,
    Dictionaries und ``Decimal``-Werten ist eine spezialisierte Rekursion
    deutlich schneller. Unbekannte Typen fallen auf ``deepcopy`` zurück.
    """
    value_type = type(value)
    if value_type is dict:
        return {key: _clone(item) for key, item in value.items()}
    if value_type is list:
        return [_clone(item) for item in value]
    if value_type is tuple:
        return tuple(_clone(item) for item in value)
    if value_type is set:
        return {_clone(item) for item in value}
    if value_type is frozenset:
        return frozenset(_clone(item) for item in value)
    if value is None or value_type in (str, int, float, bool, bytes, Decimal):
        return value
    return deepcopy(value)


def cached_series(repo, key, build):
    """Share bounded chart data until local or external database changes."""
    if repo.db.in_transaction:
        repo._chart_series_cache = None
        return build()
    revision = (repo.db.total_changes, repo.db.execute('PRAGMA data_version').fetchone()[0])
    cached = repo.__dict__.get('_chart_series_cache')
    if cached is None or cached[0] != revision:
        cached = (revision, {})
        repo._chart_series_cache = cached
    entries = cached[1]
    if key not in entries:
        result = build()
        if len(entries) >= 8:
            entries.pop(next(iter(entries)))
        entries[key] = result
    return _clone(entries[key])


def _dump_value(value):
    if isinstance(value, Decimal):
        return 'D:' + str(value)
    if isinstance(value, dict):
        return {str(k): _dump_value(v) for k, v in value.items()}
    if isinstance(value, (bool, int, float)) or value is None:
        return value
    return str(value)


def _load_value(value):
    if isinstance(value, dict):
        return {k: _load_value(v) for k, v in value.items()}
    if isinstance(value, str) and value.startswith('D:'):
        return Decimal(value[2:])
    return value


def _dump_series(rows):
    """Convert Decimal-bearing rows to a JSON-safe structure."""
    return [{field: _dump_value(value) for field, value in row.items()} for row in rows]


def _load_series(rows):
    """Restore the structure written by ``_dump_series``."""
    return [{field: _load_value(value) for field, value in row.items()} for row in rows]


def load_series_cache(repo):
    """Read the persistent series cache; failures just fall back to rebuilding."""
    try:
        payload = read_json(Path(repo.store.path).parent / SERIES_CACHE_FILE) or {}
        entries = payload.get('entries') if payload.get('version') == 1 else None
        return entries if isinstance(entries, list) else []
    except Exception:
        return []


def save_series_cache(repo, entry):
    """Atomically persist a bounded series cache next to the database."""
    try:
        current = [c for c in load_series_cache(repo)
                   if not (c.get('revision') == entry['revision'] and c.get('as_of') == entry['as_of']
                           and c.get('account') == entry['account'] and c.get('documented') == entry['documented']
                           and c.get('today') == entry['today'])]
        current.insert(0, entry)
        path = Path(repo.store.path).parent / SERIES_CACHE_FILE
        atomic_json(path, {'version': 1, 'entries': current[:3]})
    except Exception:
        pass


def prepare_series_cache_entry(repo, as_of, account, documented):
    """Revision-keyed key so a changed database invalidates the cached series."""
    try:
        revision = repo.db.execute('SELECT value FROM v09_revision WHERE id=1').fetchone()[0]
    except Exception:
        revision = (repo.db.total_changes, repo.db.execute('PRAGMA data_version').fetchone()[0])
    from datetime import date
    return {'as_of': as_of, 'account': account, 'documented': documented,
            'revision': revision, 'today': date.today().isoformat()}