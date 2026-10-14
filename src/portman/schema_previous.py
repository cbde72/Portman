"""Upgrade older database schemas before the V09 migration."""
from datetime import datetime, timezone
from .persistence import migrate_v07

def migrate(db):
    version = db.execute('PRAGMA user_version').fetchone()[0]
    if version > 8: raise ValueError('Nicht unterstützte Datenbankversion.')
    if version == 8: return
    migrate_v07(db)
    with db:
        db.execute('CREATE TABLE IF NOT EXISTS v08_revision(id INTEGER PRIMARY KEY CHECK(id=1), value INTEGER NOT NULL)')
        db.execute('INSERT OR IGNORE INTO v08_revision VALUES(1,0)')
        db.execute('CREATE TABLE IF NOT EXISTS view_history(id INTEGER PRIMARY KEY, name TEXT NOT NULL, payload TEXT NOT NULL, operation TEXT NOT NULL, changed_at TEXT DEFAULT CURRENT_TIMESTAMP)')
        db.execute('CREATE TABLE IF NOT EXISTS csv_profiles(name TEXT PRIMARY KEY, payload TEXT NOT NULL)')
        db.execute('''CREATE TABLE IF NOT EXISTS transaction_supersessions(
            id INTEGER PRIMARY KEY, old_import INTEGER NOT NULL, old_account TEXT NOT NULL, old_id TEXT NOT NULL,
            new_import INTEGER NOT NULL, new_account TEXT NOT NULL, new_id TEXT NOT NULL, reason TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP)''')
        db.execute('CREATE INDEX IF NOT EXISTS supersession_new_import ON transaction_supersessions(new_import)')
        db.execute('CREATE TABLE IF NOT EXISTS transfer_pairs(id INTEGER PRIMARY KEY, first_ref TEXT UNIQUE NOT NULL, second_ref TEXT UNIQUE NOT NULL, note TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP)')
        db.execute('''CREATE TABLE IF NOT EXISTS corporate_actions(id INTEGER PRIMARY KEY, day TEXT NOT NULL,
            depot TEXT NOT NULL, security TEXT NOT NULL, kind TEXT NOT NULL, target TEXT, target_depot TEXT,
            ratio TEXT, units TEXT, sequence INTEGER NOT NULL DEFAULT 0, source TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1)''')
        db.execute('CREATE TABLE IF NOT EXISTS historical_fx(day TEXT NOT NULL, currency TEXT NOT NULL, rate TEXT NOT NULL, source TEXT NOT NULL, PRIMARY KEY(day,currency))')
        # A persistent business revision is comparable across SQLite connections.
        tables = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        excluded = {'v08_revision', 'schema_migrations', 'change_log', 'view_history', 'saved_views', 'csv_profiles', 'meta'}
        for table in tables:
            if table in excluded: continue
            columns = [r[1] for r in db.execute(f'PRAGMA table_info("{table}")')]
            for operation in ('INSERT', 'UPDATE', 'DELETE'):
                condition = '' if operation != 'UPDATE' else 'WHEN ' + ' OR '.join(
                    f'OLD."{c}" IS NOT NEW."{c}"' for c in columns if c not in ('updated_at',))
                db.execute(f'''CREATE TRIGGER IF NOT EXISTS revision08_{table}_{operation} AFTER {operation} ON "{table}"
                    {condition} BEGIN UPDATE v08_revision SET value=value+1 WHERE id=1; END''')
            if table in {'transfer_pairs', 'corporate_actions', 'historical_fx', 'transaction_supersessions'}:
                for operation in ('INSERT', 'UPDATE', 'DELETE'):
                    def js(prefix): return 'json_object(' + ','.join(f"'{c}',{prefix}.\"{c}\"" for c in columns) + ')'
                    old = 'NULL' if operation == 'INSERT' else js('OLD')
                    new = 'NULL' if operation == 'DELETE' else js('NEW')
                    db.execute(f'''CREATE TRIGGER IF NOT EXISTS audit08_{table}_{operation} AFTER {operation} ON "{table}"
                        BEGIN INSERT INTO change_log(entity,operation,old_data,new_data) VALUES('{table}','{operation}',{old},{new}); END''')
        db.execute('INSERT INTO schema_migrations VALUES(8,?)', (datetime.now(timezone.utc).isoformat(),))
        db.execute('PRAGMA user_version=8')
