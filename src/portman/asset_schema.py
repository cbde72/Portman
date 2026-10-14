"""Additive asset metadata; original imports and market tables stay authoritative."""
TABLES = ('asset_identity', 'asset_keys', 'asset_positions', 'asset_listings', 'asset_facts', 'asset_audit')


def initialize(db):
    db.executescript('''
        CREATE TABLE IF NOT EXISTS asset_identity(
            uuid TEXT PRIMARY KEY, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS asset_keys(
            security_key TEXT PRIMARY KEY, asset_uuid TEXT NOT NULL REFERENCES asset_identity(uuid));
        CREATE TABLE IF NOT EXISTS asset_positions(
            uuid TEXT PRIMARY KEY, asset_uuid TEXT NOT NULL REFERENCES asset_identity(uuid),
            depot_key TEXT NOT NULL, depot_name TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(asset_uuid,depot_key));
        CREATE TABLE IF NOT EXISTS asset_listings(
            uuid TEXT PRIMARY KEY, asset_uuid TEXT NOT NULL REFERENCES asset_identity(uuid),
            provider TEXT NOT NULL, symbol TEXT NOT NULL, exchange TEXT NOT NULL DEFAULT '',
            currency TEXT NOT NULL DEFAULT '', source TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(asset_uuid,provider,symbol,exchange,currency));
        CREATE TABLE IF NOT EXISTS asset_facts(
            asset_uuid TEXT NOT NULL REFERENCES asset_identity(uuid), scope TEXT NOT NULL,
            context TEXT NOT NULL DEFAULT '', valid_from TEXT NOT NULL DEFAULT '',
            payload TEXT NOT NULL, source TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY(asset_uuid,scope,context,valid_from));
        CREATE TABLE IF NOT EXISTS asset_audit(
            id INTEGER PRIMARY KEY, asset_uuid TEXT NOT NULL REFERENCES asset_identity(uuid),
            scope TEXT NOT NULL, context TEXT NOT NULL, valid_from TEXT NOT NULL,
            old_payload TEXT, new_payload TEXT NOT NULL, source TEXT NOT NULL,
            changed_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE INDEX IF NOT EXISTS asset_audit_security ON asset_audit(asset_uuid,id);
        INSERT OR IGNORE INTO meta VALUES('asset_extension_version','1');
    ''')
    install_revision_triggers(db)


def install_revision_triggers(db):
    if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='v09_revision'").fetchone(): return
    with db:
        for table in TABLES:
            for operation in ('INSERT', 'UPDATE', 'DELETE'):
                db.execute(f'''CREATE TRIGGER IF NOT EXISTS revision09_{table}_{operation}
                    AFTER {operation} ON {table}
                    BEGIN UPDATE v09_revision SET value=value+1 WHERE id=1; END''')
