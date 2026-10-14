"""Durable settings, verified rotating SQLite backups and versioned V07 migrations."""
import json
import os
import sqlite3
import tempfile
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)
    handle, temporary = tempfile.mkstemp(dir=path.parent, prefix=path.name + '.', suffix='.tmp')
    try:
        with os.fdopen(handle, 'w', encoding='utf-8') as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        if path.exists():
            try:
                previous = json.loads(path.read_text(encoding='utf-8'))
            except (ValueError, UnicodeError):
                previous = None
            if previous is not None:
                atomic_json(path.with_suffix(path.suffix + '.last-good'), previous) if not str(path).endswith('.last-good') else None
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def read_json(path, default=None):
    path = Path(path)
    if not path.exists():
        return {} if default is None else default
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (ValueError, UnicodeError):
        fallback = path.with_suffix(path.suffix + '.last-good')
        if fallback.exists():
            return json.loads(fallback.read_text(encoding='utf-8'))
        raise ValueError(f'Datei beschädigt: {path}. Bitte eine Sicherung wiederherstellen.')


def inspect_database(path):
    with closing(sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)) as db:
        integrity = db.execute('PRAGMA integrity_check').fetchone()[0]
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        required = {'meta', 'imports', 'accounts', 'snapshots', 'balances', 'transactions'}
        if integrity != 'ok' or not required <= tables:
            raise ValueError('Keine intakte PortMan-Datenbank: ' + str(integrity))
        if db.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone() != ('1',):
            raise ValueError('Nicht unterstützte Basis-Schemaversion.')
        version = db.execute('PRAGMA user_version').fetchone()[0]
        if version > 7:
            raise ValueError('Die Sicherung stammt aus einer neueren PortMan-Version.')
        return {name: db.execute(f'SELECT count(*) FROM {name}').fetchone()[0]
                for name in sorted(required - {'meta'})}


def backup_database(connection, folder, reason='automatic', keep=12):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-%f')
    path = folder / f'portman-{stamp}-{reason}.sqlite'
    with closing(sqlite3.connect(path)) as target:
        connection.backup(target)
    inspect_database(path)
    # Only our generated backups are eligible for rotation.
    for old in sorted(folder.glob('portman-*.sqlite'), reverse=True)[keep:]:
        old.unlink()
    return path


def initialize_v07(root):
    root = Path(root)
    folder = root / 'data' / 'v07'
    folder.mkdir(parents=True, exist_ok=True)
    database = folder / 'portfolio.sqlite'
    legacy = root / 'data' / 'portfolio_v05.sqlite'
    if not database.exists() and legacy.exists():
        inspect_database(legacy)
        temporary = folder / 'migration.sqlite.tmp'
        with closing(sqlite3.connect(legacy.resolve().as_uri() + '?mode=ro', uri=True)) as src:
            backup_database(src, folder / 'backups', 'before-v07')
            with closing(sqlite3.connect(temporary)) as dst:
                src.backup(dst)
        os.replace(temporary, database)
    for filename in ('portfolio_settings.json', 'etf_cache.json'):
        target = folder / filename
        if not target.exists():
            source = next((p for p in (root / 'src' / 'Gui' / filename, root / filename) if p.exists()), None)
            if source:
                atomic_json(target, read_json(source))
    banking = root / 'data' / 'banking'
    if banking.is_dir() and not (folder / 'banking').exists():
        import shutil
        with tempfile.TemporaryDirectory(dir=folder) as temporary:
            staged = Path(temporary) / 'banking'
            shutil.copytree(banking, staged)
            os.replace(staged, folder / 'banking')
    return folder


def migrate_v07(db):
    version = db.execute('PRAGMA user_version').fetchone()[0]
    if version > 7:
        raise ValueError('Neuere Datenbankversion; bitte passende PortMan-Version verwenden.')
    if version == 7:
        return
    with db:
        db.execute('CREATE TABLE IF NOT EXISTS schema_migrations(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)')
        db.execute('''CREATE TABLE IF NOT EXISTS change_log(
            id INTEGER PRIMARY KEY, changed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            entity TEXT NOT NULL, operation TEXT NOT NULL, old_data TEXT, new_data TEXT)''')
        db.execute('CREATE TABLE IF NOT EXISTS saved_views(name TEXT PRIMARY KEY, payload TEXT NOT NULL)')
        # Triggers also cover edits performed through existing V06-compatible dialogs.
        tables = ('manual_balances', 'account_tax_years', 'cost_corrections', 'security_master', 'security_metadata',
                  'security_classifications', 'accounts', 'depot_accounts', 'imports')
        for table in tables:
            columns = [r[1] for r in db.execute(f'PRAGMA table_info({table})')]
            for operation in ('INSERT', 'UPDATE', 'DELETE'):
                def expression(prefix):
                    return 'json_object(' + ','.join(f"'{c}',{prefix}.\"{c}\"" for c in columns) + ')'
                before = 'NULL' if operation == 'INSERT' else expression('OLD')
                after = 'NULL' if operation == 'DELETE' else expression('NEW')
                condition = '' if operation != 'UPDATE' else 'WHEN ' + ' OR '.join(f'OLD."{c}" IS NOT NEW."{c}"' for c in columns if c != 'updated_at')
                db.execute(f'''CREATE TRIGGER IF NOT EXISTS audit_{table}_{operation} AFTER {operation} ON {table}
                    {condition} BEGIN INSERT INTO change_log(entity,operation,old_data,new_data)
                    VALUES('{table}','{operation}',{before},{after}); END''')
        db.execute('CREATE INDEX IF NOT EXISTS manual_balance_date ON manual_balances(account_key,effective_date DESC,id DESC)')
        db.execute('CREATE INDEX IF NOT EXISTS cost_correction_lookup ON cost_corrections(snapshot_id,security_key,id DESC)')
        db.execute('INSERT INTO schema_migrations VALUES(7,?)', (datetime.now(timezone.utc).isoformat(),))
        db.execute('PRAGMA user_version=7')


def restore_database(connection, source, backup_folder, source_label=None):
    """Restore into the existing connection so all repository components stay valid."""
    inspect_database(source)
    # Normalize and validate older schemas away from the live database first.
    with tempfile.TemporaryDirectory() as directory:
        prepared = Path(directory) / 'restore.sqlite'
        with closing(sqlite3.connect(Path(source).resolve().as_uri() + '?mode=ro', uri=True)) as src:
            with closing(sqlite3.connect(prepared)) as dst: src.backup(dst)
        from .repository import PortfolioRepository
        repository = PortfolioRepository(prepared)
        try: migrate_v07(repository.db)
        finally: repository.close()
        inspect_database(prepared)
        backup_database(connection, backup_folder, 'before-restore')
        with closing(sqlite3.connect(prepared)) as src:
            src.backup(connection)
        with connection:
            connection.execute("INSERT INTO change_log(entity,operation,new_data) VALUES('database','RESTORE',?)",
                               (json.dumps({'backup': source_label or Path(source).name}),))
