"""V07 repository with migration, recovery and persistent analysis presets."""
import json
from copy import deepcopy
from functools import wraps
import sqlite3
from datetime import datetime, timezone
from contextlib import closing
from pathlib import Path
from decimal import Decimal
from .repository import PortfolioRepository
from .persistence import backup_database, migrate_v07


def cached_view(method):
    @wraps(method)
    def read(self, *args, **kwargs):
        if self.db.in_transaction:
            return method(self, *args, **kwargs)
        revision = (self.db.total_changes, self.db.execute('PRAGMA data_version').fetchone()[0])
        if self.__dict__.get('_view_revision') != revision:
            self._view_revision, self._view_cache = revision, {}
        key = (method.__name__, args, tuple(sorted(kwargs.items())))
        if key not in self._view_cache:
            self._view_cache[key] = method(self, *args, **kwargs)
        return deepcopy(self._view_cache[key])
    return read


class RepositoryV07(PortfolioRepository):
    def __init__(self, database, backups=True):
        database = Path(database)
        self.backup_folder = database.parent / 'backups'
        self.backups_enabled = backups
        if backups and database.exists():
            with closing(sqlite3.connect(database)) as db:
                version = db.execute('PRAGMA user_version').fetchone()[0]
                day = datetime.now(timezone.utc).strftime('%Y%m%d')
                if version != 7:
                    backup_database(db, self.backup_folder, 'before-migration')
                elif not any(self.backup_folder.glob(f'portman-{day}-*-daily.sqlite')):
                    backup_database(db, self.backup_folder, 'daily')
        super().__init__(database)
        migrate_v07(self.db)
        # The backup hook executes before the transaction opens.
        if backups:
            from functools import wraps
            for name in ('delete_imports', 'delete_all_imports', 'delete_all_accounts',
                         'undo_import', 'correct_import', 'reassign_imports'):
                original = getattr(self.store, name)
                def protected(*args, _method=original, **kwargs):
                    self.backup('before-change')
                    return _method(*args, **kwargs)
                setattr(self.store, name, wraps(original)(protected))

    def backup(self, reason='manual'):
        return backup_database(self.db, self.backup_folder, reason)

    def commit_batches(self, batches):
        if self.backups_enabled and batches: self.backup('before-import')
        return super().commit_batches(batches)

    def saved_views(self):
        return {r['name']: json.loads(r['payload']) for r in self.db.execute('SELECT * FROM saved_views ORDER BY name')}

    def save_view(self, name, payload):
        name = name.strip()
        if not name or len(name) > 100:
            raise ValueError('Bitte einen Namen mit 1 bis 100 Zeichen eingeben.')
        with self.db:
            self.db.execute('INSERT INTO saved_views VALUES(?,?) ON CONFLICT(name) DO UPDATE SET payload=excluded.payload',
                            (name, json.dumps(payload, ensure_ascii=False)))

    def delete_view(self, name):
        with self.db:
            self.db.execute('DELETE FROM saved_views WHERE name=?', (name,))

    def correct_cost(self, snapshot_id, key, cost, source):
        cost = Decimal(str(cost)); source = source.strip()
        if not cost.is_finite() or cost <= 0 or not source:
            raise ValueError('Positiven Gesamteinstand und Belegquelle angeben.')
        row = self.db.execute('''SELECT s.payload FROM snapshots s JOIN imports i ON i.id=s.import_id
            WHERE s.id=? AND i.active=1 AND NOT EXISTS(SELECT 1 FROM snapshot_exclusions e WHERE e.snapshot_id=s.id)''', (snapshot_id,)).fetchone()
        if row is None or not any(p['key'] == key for p in json.loads(row['payload'])['positions']):
            raise ValueError('Der ausgewählte Datenstand ist nicht mehr aktiv. Bitte neu auswählen.')
        with self.db:
            self.db.execute('INSERT INTO cost_corrections(snapshot_id,security_key,cost,source) VALUES(?,?,?,?)',
                            (snapshot_id, key, str(cost), source))

    @cached_view
    def account_overview(self, as_of='9999-12-31'):
        return super().account_overview(as_of)

    @cached_view
    def wealth_summary(self, as_of='9999-12-31', account=None):
        return super().wealth_summary(as_of, account)

    @cached_view
    def holdings(self, as_of='9999-12-31', account=None):
        return super().holdings(as_of, account)
