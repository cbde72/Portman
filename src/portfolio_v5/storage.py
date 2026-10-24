"""Atomic, revisioned SQLite storage. Amounts are decimal strings, not floats."""
import json
import base64
import hashlib
import sqlite3
from collections import defaultdict
from dataclasses import asdict
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from functools import wraps
from bisect import bisect_right

from .models import digest
from .importers import PARSER_VERSION
from .accounts import account_key, account_name, canonical_depot


def balance_date(row):
    """Observation date, independent of file import order and source alias."""
    import re
    stamp, display = row['period'] + '-01', row['period']
    match = re.search(r'\b\d{4}-\d{2}-\d{2}\b', row['sheet']) if row['sheet'].startswith(('Online ', 'PDF comdirect Finanzreport ')) else None
    if match:
        try: stamp = display = date.fromisoformat(match[0]).isoformat()
        except ValueError: pass
    return stamp, display


def cached_read(method):
    """Invalidate on local writes/rollbacks and commits by other connections."""
    @wraps(method)
    def read(self, *args, **kwargs):
        if self.db.in_transaction:
            self._read_revision = None
            return method(self, *args, **kwargs)
        revision = (self.db.total_changes, self.db.execute('PRAGMA data_version').fetchone()[0])
        # Repository.__getattr__ delegates to Store. Cache state must belong to
        # this instance, otherwise repository classifications can be bypassed.
        if self.__dict__.get('_read_revision') != revision:
            self._read_revision = revision; self._read_cache = {}
        key = (method.__name__, args, tuple(sorted(kwargs.items())))
        if key not in self._read_cache:
            result = method(self, *args, **kwargs)
            if len(self._read_cache) >= getattr(self, '_read_cache_cap', 64): self._read_cache.pop(next(iter(self._read_cache)))
            self._read_cache[key] = result
        result = self._read_cache[key]
        return [dict(r) for r in result] if isinstance(result, list) else dict(result)
    return read


SCHEMA = '''
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS accounts(
 account_key TEXT PRIMARY KEY, name TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1,
 source TEXT NOT NULL DEFAULT 'Import');
CREATE TABLE IF NOT EXISTS depot_accounts(
 depot_key TEXT PRIMARY KEY, depot_name TEXT NOT NULL,
 account_key TEXT NOT NULL REFERENCES accounts(account_key));
INSERT OR IGNORE INTO meta VALUES('schema_version','1');
CREATE TABLE IF NOT EXISTS imports(
 id INTEGER PRIMARY KEY, path TEXT NOT NULL, file_hash TEXT NOT NULL,
 parser TEXT NOT NULL, imported_at TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1,
 report TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS import_account_links(
 import_id INTEGER NOT NULL REFERENCES imports(id), source_key TEXT NOT NULL,
 account_key TEXT NOT NULL REFERENCES accounts(account_key), PRIMARY KEY(import_id,source_key));
CREATE TABLE IF NOT EXISTS import_account_rules(
 scope TEXT NOT NULL, source_key TEXT NOT NULL, account_key TEXT NOT NULL REFERENCES accounts(account_key),
 PRIMARY KEY(scope,source_key));
CREATE TABLE IF NOT EXISTS snapshots(
 id INTEGER PRIMARY KEY, import_id INTEGER NOT NULL REFERENCES imports(id),
 account TEXT NOT NULL, period TEXT NOT NULL, as_of TEXT, effective_date TEXT NOT NULL,
 complete INTEGER NOT NULL, content_hash TEXT NOT NULL, payload TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS snapshot_lookup ON snapshots(account,effective_date);
CREATE TABLE IF NOT EXISTS snapshot_exclusions(
 snapshot_id INTEGER PRIMARY KEY REFERENCES snapshots(id), reason TEXT NOT NULL,
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS balances(
 id INTEGER PRIMARY KEY, import_id INTEGER NOT NULL REFERENCES imports(id),
 period TEXT NOT NULL, category TEXT NOT NULL, account TEXT NOT NULL,
 value TEXT NOT NULL, priority INTEGER NOT NULL, sheet TEXT NOT NULL, row_number INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS balance_lookup ON balances(period,category,account);
CREATE TABLE IF NOT EXISTS transactions(
 id INTEGER PRIMARY KEY, import_id INTEGER NOT NULL REFERENCES imports(id),
 account TEXT NOT NULL, external_id TEXT NOT NULL, date TEXT NOT NULL,
 content_hash TEXT NOT NULL, payload TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS transaction_lookup ON transactions(account,external_id);
CREATE TABLE IF NOT EXISTS bank_booking_replacements(
 old_transaction INTEGER NOT NULL REFERENCES transactions(id) ON DELETE CASCADE,
 new_import INTEGER NOT NULL REFERENCES imports(id) ON DELETE CASCADE,
 PRIMARY KEY(old_transaction,new_import));
CREATE TABLE IF NOT EXISTS bank_documents(
 id INTEGER PRIMARY KEY, import_id INTEGER NOT NULL REFERENCES imports(id),
 account TEXT NOT NULL, external_id TEXT NOT NULL, title TEXT NOT NULL,
 date TEXT NOT NULL, media_type TEXT NOT NULL, content_hash TEXT NOT NULL, content BLOB NOT NULL);
CREATE INDEX IF NOT EXISTS bank_document_lookup ON bank_documents(account,external_id);
CREATE TABLE IF NOT EXISTS import_model_records(
 import_id INTEGER NOT NULL REFERENCES imports(id), kind TEXT NOT NULL,
 ordinal INTEGER NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(import_id,kind,ordinal));
CREATE INDEX IF NOT EXISTS import_model_record_kind ON import_model_records(kind,import_id);
CREATE TABLE IF NOT EXISTS original_files(
 content_hash TEXT NOT NULL, path TEXT NOT NULL, content BLOB NOT NULL,
 PRIMARY KEY(content_hash,path));
CREATE TABLE IF NOT EXISTS booking_details(
 transaction_id INTEGER PRIMARY KEY REFERENCES transactions(id) ON DELETE CASCADE,
 payload TEXT NOT NULL, source_hash TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS coverage(
 account TEXT NOT NULL, start_date TEXT NOT NULL, end_date TEXT NOT NULL,
 confirmed_at TEXT NOT NULL, PRIMARY KEY(account,start_date,end_date));
CREATE INDEX IF NOT EXISTS import_duplicate_lookup ON imports(file_hash,active);
CREATE INDEX IF NOT EXISTS snapshot_import ON snapshots(import_id);
CREATE INDEX IF NOT EXISTS balance_import ON balances(import_id);
CREATE INDEX IF NOT EXISTS transaction_import ON transactions(import_id);
CREATE INDEX IF NOT EXISTS document_import ON bank_documents(import_id);
CREATE INDEX IF NOT EXISTS snapshot_revision ON snapshots(account,effective_date,complete,id DESC);
'''

# Bump when ``SCHEMA`` gains tables/columns/indexes so the DDL script runs again.
CORE_SCHEMA_VERSION = '1'


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, timeout=30)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA synchronous=NORMAL')
        self.db.execute('PRAGMA temp_store=MEMORY')
        self.db.execute('PRAGMA busy_timeout=30000')
        # ``foreign_keys`` is a per-connection pragma; set it explicitly since the
        # schema script (which used to carry it) is skipped when already applied.
        self.db.execute('PRAGMA foreign_keys=ON')
        # Apply the DDL script only when this code version has not built the
        # schema yet; re-running ~30 CREATE/INDEX statements on every start is
        # pure overhead.
        if not self._schema_ready():
            self.db.executescript(SCHEMA)
            self.db.execute('INSERT OR REPLACE INTO meta(key,value) VALUES(?,?)',
                            ('core_schema_version', CORE_SCHEMA_VERSION))
        version = self.db.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0]
        if version != '1':
            raise ValueError(f'Unbekanntes Datenbankschema {version}')
        # The passes below are defensive repairs for imported/legacy data.
        # Imports register their own accounts and depots, so each repair only
        # has to run once per database.
        with self.db:
            if not self.db.execute("SELECT 1 FROM meta WHERE key='account_links_ready_v1'").fetchone():
                links = self._import_links()
                for row in self.db.execute('''SELECT account,import_id FROM snapshots UNION SELECT account,import_id FROM balances
                                             UNION SELECT account,import_id FROM transactions
                                             UNION SELECT account,import_id FROM bank_documents''').fetchall():
                    if row['account'] != 'Archiv' and (row['import_id'], account_key(row['account'])) not in links:
                        self._register_account(row['account'])
                self.db.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('account_links_ready_v1','1')")
        columns = {r['name'] for r in self.db.execute('PRAGMA table_info(accounts)')}
        for column, declaration in [('parent_key', 'TEXT'), ('details', "TEXT NOT NULL DEFAULT '{}'")]:
            if column not in columns:
                self.db.execute(f'ALTER TABLE accounts ADD COLUMN {column} {declaration}')
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS manual_balances(
          id INTEGER PRIMARY KEY, account_key TEXT NOT NULL REFERENCES accounts(account_key),
          effective_date TEXT NOT NULL, value TEXT NOT NULL, note TEXT NOT NULL,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        """)
        if not self.db.execute("SELECT 1 FROM meta WHERE key='depots_synced_v1'").fetchone():
            self.sync_depots()
            self.db.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('depots_synced_v1','1')")
        self._separate_zero_crypto()
        self._exclude_legacy_deka_duplicates()

    def _schema_ready(self):
        """True if the current code version already applied ``SCHEMA`` to this file."""
        try:
            row = self.db.execute("SELECT value FROM meta WHERE key='core_schema_version'").fetchone()
        except sqlite3.OperationalError:
            return False
        return bool(row) and row[0] == CORE_SCHEMA_VERSION

    def _separate_zero_crypto(self):
        """Repair legacy ZERO wallet source identities, retaining chosen targets."""
        from .import_accounts import rule_scope
        old_key, new_key = account_key('ZERO'), account_key('ZERO/Krypto')
        links, mappings = self._import_links(), self._depot_mappings()
        pending = [name for name, in self.db.execute('SELECT DISTINCT account FROM snapshots')
                   if account_key(name) == old_key]
        if not pending:
            return
        placeholders = ','.join('?' for _ in pending)
        rows = self.db.execute(
            f'SELECT s.*,i.path FROM snapshots s JOIN imports i ON i.id=s.import_id WHERE s.account IN ({placeholders})',
            pending).fetchall()
        with self.db:
            for row in rows:
                if account_key(row['account']) != old_key:
                    continue
                payload = json.loads(row['payload'])
                positions = payload.get('positions', [])
                if payload.get('sheet') != 'CSV' or not positions or not all(p.get('asset_type') == 'Krypto' for p in positions):
                    continue
                target = links.get((row['import_id'], old_key), mappings.get(old_key, old_key))
                payload['account'] = 'ZERO/Krypto'
                semantic = {key: payload[key] for key in ('account', 'as_of', 'complete')}
                semantic['positions'] = sorted([{k: v for k, v in p.items() if k != 'row'} for p in positions], key=lambda p: p['key'])
                self.db.execute('UPDATE snapshots SET account=?,payload=?,content_hash=? WHERE id=?',
                    ('ZERO/Krypto', json.dumps(payload, ensure_ascii=False), digest(semantic), row['id']))
                self.db.execute('INSERT OR IGNORE INTO depot_accounts VALUES(?,?,?)', (new_key, 'ZERO/Krypto', target))
                self.db.execute('INSERT OR REPLACE INTO import_account_links VALUES(?,?,?)', (row['import_id'], new_key, target))
                # Keep the old link for any non-wallet data in the same import.
                remains = any(account_key(r[0]) == old_key for table in ('snapshots', 'balances', 'transactions')
                    for r in self.db.execute(f'SELECT account FROM {table} WHERE import_id=?', (row['import_id'],)))
                if not remains:
                    self.db.execute('DELETE FROM import_account_links WHERE import_id=? AND source_key=?', (row['import_id'], old_key))
                self.db.execute('INSERT OR IGNORE INTO import_account_rules SELECT scope,?,account_key FROM import_account_rules WHERE scope=? AND source_key=?',
                    (new_key, rule_scope(row['path']), old_key))
                report_row = self.db.execute('SELECT report FROM imports WHERE id=?', (row['import_id'],)).fetchone()
                report = json.loads(report_row[0])
                report.setdefault('account_assignments', {})[new_key] = target
                if not remains:
                    report['account_assignments'].pop(old_key, None)
                report['zero_crypto_source_repaired'] = True
                self.db.execute('UPDATE imports SET report=? WHERE id=?', (json.dumps(report, ensure_ascii=False), row['import_id']))
                self.db.execute('DELETE FROM coverage')

    def _exclude_legacy_deka_duplicates(self):
        marker = 'deka_heading_duplicates_corrected_v1'
        if self.db.execute('SELECT 1 FROM meta WHERE key=?', (marker,)).fetchone(): return
        rows = self.db.execute("SELECT * FROM snapshots WHERE account LIKE 'Deka/%'").fetchall()
        signatures = set()
        def signature(row):
            positions = json.loads(row['payload'])['positions']
            return row['effective_date'], json.dumps(sorted(
                [(p['key'], p['quantity'], p['value'], p.get('currency')) for p in positions]), sort_keys=True)
        for row in rows:
            if row['account'].split('/', 1)[1].isdigit(): signatures.add(signature(row))
        invalid_names = {'Deka/Bestand', 'Deka/Bestand in Stück', 'Deka/davon steuerlicher', 'Deka/Vertragsart'}
        with self.db:
            count = 0
            for row in rows:
                if row['account'] in invalid_names and signature(row) in signatures:
                    self.db.execute('INSERT OR IGNORE INTO snapshot_exclusions(snapshot_id,reason) VALUES(?,?)',
                                    (row['id'], 'Doppelter Altimport: Tabellenüberschrift wurde als Unterdepot verwendet.'))
                    count += 1
            self.db.execute('INSERT INTO meta VALUES(?,?)', (marker, str(count)))

    def sync_depots(self, names=()):
        names = set(names) | {r[0] for r in self.db.execute('SELECT DISTINCT account FROM snapshots')}
        with self.db:
            for name in sorted(names):
                if self.db.execute('SELECT 1 FROM depot_accounts WHERE depot_key=?', (account_key(name),)).fetchone():
                    continue
                parent = name.split('/', 1)[0] if name.casefold().startswith('deka/') else name
                self._register_account(parent)
                self.db.execute('INSERT OR IGNORE INTO depot_accounts VALUES(?,?,?)',
                                (account_key(name), name, account_key(parent)))

    @cached_read
    def depots(self):
        records, mappings, links = self._account_view(), self._depot_mappings(), self._import_links()
        latest = {}
        for row in self.db.execute('''SELECT s.* FROM snapshots s JOIN imports i ON i.id=s.import_id
            WHERE i.active=1 AND NOT EXISTS (SELECT 1 FROM snapshot_exclusions e WHERE e.snapshot_id=s.id)
            ORDER BY s.effective_date,s.id'''):
            key = account_key(row['account'])
            target = links.get((row['import_id'], key), mappings.get(key, key))
            record = records.get(target)
            if record:
                latest[key] = {'depot_key': key, 'depot_name': row['account'], 'account_key': target,
                               'account': record['name'], 'active': record['active']}
        return sorted(latest.values(), key=lambda r: r['depot_name'])

    def assign_depot(self, depot, account):
        target = next((r for r in self.account_records() if r['name'] == account or r['account_key'] == account_key(account)), None)
        if target is None or not target['active']:
            raise ValueError('Bitte ein aktives Konto auswählen.')
        with self.db:
            changed = self.db.execute('UPDATE depot_accounts SET account_key=? WHERE depot_key=?',
                                      (target['account_key'], account_key(depot)))
            if not changed.rowcount:
                raise ValueError('Depot nicht gefunden.')
            self.db.execute('UPDATE import_account_links SET account_key=? WHERE source_key=?',
                            (target['account_key'], account_key(depot)))
            self.db.execute('DELETE FROM coverage')

    def _depot_account(self, name, records, mappings, target=None):
        target = target or mappings.get(account_key(name), account_key(name))
        record = records.get(target)
        return record['name'] if record and record['active'] else (account_name(name) if record is None else None)

    def _depot_mappings(self):
        return {r['depot_key']: r['account_key'] for r in self.db.execute('SELECT * FROM depot_accounts')}

    def _import_links(self):
        return {(r['import_id'], r['source_key']): r['account_key'] for r in self.db.execute('SELECT * FROM import_account_links')}

    def import_account_suggestions(self, batch):
        from .import_accounts import suggest_accounts
        return suggest_accounts(self, batch)

    def import_rules(self):
        return [dict(r) for r in self.db.execute('''SELECT r.*,a.name,a.active FROM import_account_rules r
            JOIN accounts a ON a.account_key=r.account_key ORDER BY scope,source_key''')]

    def _register_account(self, name, source='Import'):
        name = account_name(name)
        if not name:
            raise ValueError('Bitte einen Kontonamen eingeben.')
        details = {}
        if name.startswith('IBAN DE'):
            iban = ''.join(name[5:].split())
            if len(iban) == 22 and iban[2:].isdigit() and int(iban[4:] + '1314' + iban[2:4]) % 97 == 1:
                details = {'iban': iban, 'number': iban[-10:]}
        self.db.execute('INSERT OR IGNORE INTO accounts(account_key,name,source,details) VALUES(?,?,?,?)',
                        (account_key(name), name, source, json.dumps(details)))

    @cached_read
    def account_records(self):
        return [dict(r) for r in self.db.execute('''SELECT a.* FROM accounts a
            WHERE NOT (a.source='Import' AND a.account_key LIKE 'deka/%'
              AND EXISTS (SELECT 1 FROM depot_accounts d WHERE d.depot_key=a.account_key AND d.account_key<>a.account_key))
            ORDER BY a.name COLLATE NOCASE''')]

    def accounts(self):
        return [r['name'] for r in self.account_records() if r['active']]

    def create_accounts(self, names, source='Manuell'):
        names = [account_name(n) for n in names]
        if any(not n for n in names):
            raise ValueError('Bitte einen Kontonamen eingeben.')
        created = 0
        with self.db:
            for name in dict.fromkeys(names):
                exists = self.db.execute('SELECT 1 FROM accounts WHERE account_key=?', (account_key(name),)).fetchone()
                self._register_account(name, source)
                created += not bool(exists)
        return created

    def validate_account_name(self, name, original=None):
        name = account_name(name)
        key = next((k for k, r in self._account_view().items() if r['name'] == original), account_key(original or name))
        if not name:
            raise ValueError('Bitte einen Kontonamen eingeben.')
        records = self._account_view()
        if original and key not in records:
            raise ValueError('Konto nicht gefunden.')
        if not original and key in records:
            raise ValueError('Dieses Konto existiert bereits.')
        if account_key(name) in records and account_key(name) != key:
            raise ValueError('Dieser Kontoname ist bereits vergeben.')
        if any(r['name'].casefold() == name.casefold() and k != key for k, r in records.items()):
            raise ValueError('Dieser Kontoname ist bereits vergeben.')
        return name, key

    def save_account(self, name, details, parent=None, original=None):
        from .models import number
        from datetime import date
        name, key = self.validate_account_name(name, original)
        records = self._account_view()
        parent_key = account_key(parent) if parent else None
        cursor = parent_key
        seen = {key}
        while cursor:
            if cursor in seen:
                raise ValueError('Eine Zuordnung zu sich selbst oder einem Unterkonto ist nicht möglich.')
            seen.add(cursor)
            record = records.get(cursor)
            if not record or not record['active']:
                raise ValueError('Bitte ein aktives übergeordnetes Konto wählen.')
            cursor = record['parent_key']
        details = dict(details)
        cash_key = details.get('cash_account_key')
        if cash_key:
            cash = records.get(cash_key)
            if details.get('kind') != 'Depot' or cash_key == key:
                raise ValueError('Ein Verrechnungskonto kann nur einem anderen Depot zugeordnet werden.')
            if not cash or not cash['active'] or json.loads(cash['details']).get('kind') not in ('Girokonto', 'Verrechnungskonto'):
                raise ValueError('Bitte ein aktives Giro- oder Verrechnungskonto wählen.')
        if details.get('kind') not in ('Girokonto', 'Verrechnungskonto') and any(
                json.loads(r['details']).get('cash_account_key') == key for r in records.values() if r['active']):
            raise ValueError('Dieses Konto ist noch als Verrechnungskonto eines Depots verknüpft.')
        for field in ('interest', 'overdraft_interest', 'exemption', 'credit_limit', 'fee'):
            if details.get(field):
                details[field] = number(details[field])
                if field != 'interest' and Decimal(details[field]) < 0:
                    raise ValueError('Beträge und Überziehungszinsen dürfen nicht negativ sein.')
        for field in ('start', 'end'):
            if details.get(field):
                try: date.fromisoformat(details[field])
                except ValueError: raise ValueError('Datum bitte als JJJJ-MM-TT eingeben.')
        if details.get('start') and details.get('end') and details['start'] > details['end']:
            raise ValueError('Das Laufzeitende liegt vor dem Beginn.')
        with self.db:
            if not original:
                self._register_account(name, 'Manuell')
            self.db.execute('UPDATE accounts SET name=?,parent_key=?,details=? WHERE account_key=?',
                            (name, parent_key, json.dumps(details, ensure_ascii=False), key))
            if details.get('cash_account_key') != json.loads(records.get(key, {}).get('details', '{}')).get('cash_account_key'):
                self.db.execute('DELETE FROM coverage')

    def add_balance(self, account, value, effective_date, note='Manuell'):
        from datetime import date
        from .models import money
        record = next((r for r in self.account_records() if r['name'] == account), None)
        if not record or not record['active']:
            raise ValueError('Bitte ein aktives Konto wählen.')
        date.fromisoformat(effective_date)
        value = money(value)
        if value is None:
            raise ValueError('Bitte einen Saldo eingeben.')
        with self.db:
            self.db.execute('INSERT INTO manual_balances(account_key,effective_date,value,note) VALUES(?,?,?,?)',
                            (record['account_key'], effective_date, value, note.strip() or 'Manuell'))

    @cached_read
    def balance_history(self, account):
        record = next((r for r in self.account_records() if r['name'] == account), None)
        if not record: return []
        return [dict(r) for r in self.db.execute(
            'SELECT * FROM manual_balances WHERE account_key=? ORDER BY effective_date DESC,id DESC',
            (record['account_key'],))]

    @cached_read
    def balance_histories(self):
        """All manual histories grouped by visible account name (bulk variant)."""
        records = {r['account_key']: r['name'] for r in self.account_records()}
        groups = defaultdict(list)
        for row in self.db.execute('SELECT * FROM manual_balances ORDER BY effective_date DESC,id DESC'):
            name = records.get(row['account_key'])
            if name is not None:
                groups[name].append(dict(row))
        return dict(groups)

    def set_account_active(self, name, active):
        with self.db:
            if not active:
                key = next((r['account_key'] for r in self.account_records() if r['name'] == name), account_key(name))
                if any(json.loads(r['details']).get('cash_account_key') == key
                       for r in self.account_records() if r['active']):
                    raise ValueError('Bitte zuerst die Verrechnungskonto-Zuordnung an den Depots entfernen.')
                self.db.execute('UPDATE accounts SET parent_key=NULL WHERE parent_key=?', (key,))
            result = self.db.execute('UPDATE accounts SET active=? WHERE account_key=?',
                                    (int(active), next((r['account_key'] for r in self.account_records() if r['name'] == name), account_key(name))))
            if not result.rowcount:
                raise ValueError('Konto nicht gefunden.')

    def _account_view(self):
        return {r['account_key']: dict(r) for r in self.db.execute('SELECT * FROM accounts')}

    @staticmethod
    def _visible_account(name, records):
        record = records.get(account_key(name))
        return record['name'] if record and record['active'] else (name if record is None else None)

    def close(self):
        self.db.close()

    def backup(self, path):
        with sqlite3.connect(path) as target:
            self.db.backup(target)

    def _prepare_import_accounts(self, batch):
        """Validate and apply preview account assignments before persistence."""
        from .import_accounts import import_sources, required_target_kind, rule_scope, target_compatible
        source_rows = {r['key']: r for r in import_sources(batch)}
        sources = set(source_rows)
        assignments = dict(batch.account_assignments)
        records = self._account_view()
        new_accounts = {account_key(name): account_name(name) for name in batch.new_accounts}
        for tx in batch.transactions:
            depot_key = getattr(tx, 'performance_depot_key', '')
            if depot_key:
                tx.performance_depot_key = assignments.get(depot_key, depot_key)
                depot_key = tx.performance_depot_key
            if depot_key and (depot_key not in records or not records[depot_key]['active']):
                raise ValueError('Das zugeordnete Performance-Depot fehlt oder ist inaktiv.')
        if set(new_accounts) - sources or any(not name for name in new_accounts.values()):
            raise ValueError('Neue Konten / Depots müssen aus der Importquelle stammen.')
        if any(key in records and not records[key]['active'] for key in new_accounts):
            raise ValueError('Ein gewähltes Konto / Depot wurde gelöscht. Importvorschau erneut öffnen.')
        if set(assignments) - sources:
            raise ValueError('Importzuordnung enthält ein unbekanntes Quellkonto.')
        for target in assignments.values():
            if target not in new_accounts and (target not in records or not records[target]['active']):
                raise ValueError('Ein gewähltes Zielkonto fehlt oder wurde gelöscht. Importvorschau erneut öffnen.')
        for source, source_row in source_rows.items():
            required = required_target_kind(source_row)
            if not required:
                continue
            target = assignments.get(source, source)
            if target == source and 'Depotstände' in source_row['kinds']:
                continue
            if target in new_accounts or target not in records or not records[target]['active'] \
                    or not target_compatible(records[target], required):
                raise ValueError(f'{source_rows[source]["name"]} enthält Depotdaten und darf nur einem aktiven Depot zugeordnet werden.')
        for report in batch.cost_reports:
            mapped = assignments.get(account_key(report.account))
            if mapped:
                report.account = records[mapped]['name'] if mapped in records else mapped
        if set(batch.remember_assignments) - set(assignments):
            raise ValueError('Für gemerkte Zuordnungen muss ein bestehendes Zielkonto gewählt werden.')
        return assignments, records, new_accounts, rule_scope

    @staticmethod
    def _validate_import_rows(batch):
        """Validate snapshot and transaction values and retain advisory warnings."""
        from .models import transaction_validation, valid_isin
        for snapshot in batch.snapshots:
            try:
                date.fromisoformat(snapshot.as_of or snapshot.period + '-01')
            except (TypeError, ValueError):
                raise ValueError(f'{snapshot.sheet}: ungültiger Depotstichtag {snapshot.as_of or snapshot.period!r}.') from None
            for position in snapshot.positions:
                if position.isin and not valid_isin(position.isin):
                    batch.warnings.append(
                        f'{snapshot.sheet}: ungültige ISIN {position.isin!r} bei {position.name}; '
                        'Kennung unverändert übernommen und zur Prüfung markiert.')
                for field in ('quantity', 'cost', 'value', 'price'):
                    value = getattr(position, field, None)
                    if value is not None:
                        try:
                            parsed = Decimal(value)
                            if not parsed.is_finite(): raise InvalidOperation
                        except (InvalidOperation, TypeError, ValueError):
                            raise ValueError(f'{snapshot.sheet}: {position.name}: {field} ist keine endliche Zahl.') from None
        for tx in [*batch.transactions, *batch.booking_evidence]:
            hard_problems, advisory = transaction_validation(tx)
            if hard_problems or advisory:
                source = f'Buchung {tx.external_id or "ohne ID"}'
                if hard_problems:
                    raise ValueError(source + ': ' + '; '.join(hard_problems))
                batch.warnings.extend(source + ': ' + problem for problem in advisory)

    @staticmethod
    def _prepare_import_identity(batch, assignments):
        """Build the stable import identity and validate archival documents."""
        payload = asdict(batch)
        identity = {'file': batch.file_hash, 'parser': PARSER_VERSION,
                    'snapshots': payload['snapshots'], 'balances': payload['balances'],
                    'transactions': payload['transactions']}
        model_collections = ('securities', 'accounts', 'statements', 'tax_events', 'tax_details',
                             'booking_evidence', 'cost_reports', 'events')
        for name in model_collections:
            if payload.get(name):
                identity[name] = payload[name]
        prepared_documents = []
        original_path = Path(batch.path)
        original_content = original_path.read_bytes() if original_path.is_file() else None
        if (original_content is not None and len(batch.file_hash) == 64
                and all(c in '0123456789abcdef' for c in batch.file_hash)
                and hashlib.sha256(original_content).hexdigest() != batch.file_hash):
            raise ValueError('Die Quelldatei wurde seit dem Einlesen verändert. Bitte erneut einlesen.')
        for document in batch.documents:
            try:
                content = base64.b64decode(document.content_b64, validate=True)
            except (ValueError, TypeError):
                raise ValueError('Ungültige Dokumentdaten.') from None
            if (document.media_type != 'application/pdf' or not content.startswith(b'%PDF-')
                    or b'%%EOF' not in content[-4096:]):
                raise ValueError('Nur vollständige PDF-Dokumente werden archiviert.')
            metadata = {k: v for k, v in asdict(document).items() if k != 'content_b64'}
            metadata['content_hash'] = hashlib.sha256(content).hexdigest()
            prepared_documents.append((metadata, content))
        if prepared_documents:
            identity['documents'] = [metadata for metadata, content in prepared_documents]
        if assignments:
            identity['account_assignments'] = assignments
        if batch.source_sheet:
            identity['source_sheet'] = batch.source_sheet
        if batch.history_end:
            identity['history_end'] = batch.history_end
            identity['history_path'] = batch.path
        if batch.force_import:
            from uuid import uuid4
            identity['repeat'] = uuid4().hex
        return payload, model_collections, prepared_documents, original_content, digest(identity)

    def _deduplicate_tax_events(self, batch):
        """Remove already persisted tax events and reject conflicting facts."""
        if not batch.tax_events:
            return None
        event_records = self.model_records(kind='tax_events')
        existing_events = [record['payload'] for record in event_records]
        by_id = {event.get('external_id'): event for event in existing_events if event.get('external_id')}
        record_by_id = {record['payload'].get('external_id'): record for record in event_records
                        if record['payload'].get('external_id')}
        incoming = {event.external_id: asdict(event) for event in batch.tax_events if event.external_id}

        def source_tax_fact(payload):
            # Reconciliation may be corrected after a later statement arrives.
            payload = dict(payload or {})
            payload.pop('related_transaction_id', None)
            return payload

        if incoming and all(source_tax_fact(by_id.get(identifier)) == source_tax_fact(payload)
                            for identifier, payload in incoming.items()):
            old_imports = {record_by_id[identifier]['import_id'] for identifier in incoming}
            if len(old_imports) == 1:
                old_import = next(iter(old_imports))
                report = self.db.execute('SELECT report FROM imports WHERE id=? AND active=1',
                                         (old_import,)).fetchone()
                if report and json.loads(report['report']).get('source_sha256') == batch.file_hash:
                    return {'status': 'duplicate', 'path': batch.path, 'id': old_import}
        advance_types = {'vorabpauschale', 'vorabpauschale_ausland'}
        by_period = {(account_key(event.get('account', '')), event.get('security_ref', ''),
                      str(event.get('income_year') or ''), event.get('type', '')): event
                     for event in existing_events if event.get('type') in advance_types}
        unique = []
        seen_ids = set()
        for event in batch.tax_events:
            serialized = asdict(event)
            if not event.external_id or event.external_id in seen_ids:
                raise ValueError('Steuerereignis benötigt eine eindeutige externe ID; Doppelimport abgewiesen.')
            seen_ids.add(event.external_id)
            if event.external_id in by_id:
                continue
            period_key = (account_key(event.account), event.security_ref,
                          str(event.income_year or ''), event.type)
            conflict = by_period.get(period_key) if event.type in advance_types else None
            if conflict is not None:
                raise ValueError(
                    f'Für {event.security_ref or "das Wertpapier"} im Depot {event.account} ist für das '
                    f'Ertragsjahr {event.income_year or "unbekannt"} bereits eine Vorabpauschale gespeichert.')
            unique.append(event)
            by_id[event.external_id] = serialized
            if event.type in advance_types:
                by_period[period_key] = serialized
        batch.tax_events = unique
        return None

    def _deduplicate_tax_details(self, batch):
        """Remove existing tax details, preserving the historical duplicate result."""
        if not batch.tax_details:
            return None
        existing_ids = {record['payload'].get('external_id'): record['import_id']
                        for record in self.model_records(kind='tax_details')}
        seen_ids = set()
        unique = []
        duplicate_imports = []
        for record in batch.tax_details:
            if not record.external_id or record.external_id in seen_ids:
                raise ValueError('Steuerdetail benötigt eine eindeutige externe ID; Doppelimport abgewiesen.')
            seen_ids.add(record.external_id)
            if record.external_id not in existing_ids:
                unique.append(record)
                existing_ids[record.external_id] = None
            else:
                duplicate_imports.append(existing_ids[record.external_id])
        batch.tax_details = unique
        if (not unique and duplicate_imports and not batch.snapshots and not batch.balances
                and not batch.transactions and not batch.documents and not batch.tax_events
                and not batch.securities and not batch.accounts and not batch.statements
                and not batch.cost_reports and not batch.events):
            return {'status': 'duplicate', 'path': batch.path,
                    'id': next(iid for iid in duplicate_imports if iid is not None)}
        return None

    def import_batch(self, batch):
        if batch.errors:
            raise ValueError('; '.join(batch.errors))
        assignments, records, new_accounts, rule_scope = self._prepare_import_accounts(batch)
        self._validate_import_rows(batch)
        from .comdirect_identity import preserve_booking_ids
        batch = preserve_booking_ids(self, batch)
        duplicate_result = self._deduplicate_tax_events(batch)
        if duplicate_result:
            return duplicate_result
        duplicate_result = self._deduplicate_tax_details(batch)
        if duplicate_result:
            return duplicate_result
        (payload, model_collections, prepared_documents, original_content,
         import_key) = self._prepare_import_identity(batch, assignments)
        duplicate = self.db.execute('SELECT id FROM imports WHERE file_hash=? AND active=1', (import_key,)).fetchone()
        result = {'status': 'imported', 'snapshots': 0, 'balances': 0, 'transactions': 0, 'unchanged': 0}
        with self.db:
            if original_content is not None:
                self.db.execute('INSERT OR IGNORE INTO original_files VALUES(?,?,?)',
                                (hashlib.sha256(original_content).hexdigest(), batch.path, original_content))
            elif prepared_documents:
                for metadata, content in prepared_documents:
                    self.db.execute('INSERT OR IGNORE INTO original_files VALUES(?,?,?)',
                                    (metadata['content_hash'], batch.path, content))
            for name in new_accounts.values():
                self._register_account(name)
            records = self._account_view()
            names = (batch.account_names + [s.account for s in batch.snapshots]
                     + [b.account for b in batch.balances if b.account != 'Archiv']
                     + [t.account for t in batch.transactions]
                     + [t.account for t in batch.booking_evidence]
                     + [d.account for d in batch.documents] + [r.account for r in batch.tax_details]
                     + [r.account for r in batch.cost_reports])
            for name in names:
                if account_key(name) not in assignments:
                    self._register_account(name)
            for account in dict.fromkeys(s.account for s in batch.snapshots):
                parent = account.split('/', 1)[0] if account.casefold().startswith('deka/') else account
                target = assignments.get(account_key(account), account_key(parent))
                if target not in records:
                    self._register_account(parent)
                self.db.execute('INSERT OR IGNORE INTO depot_accounts VALUES(?,?,?)',
                                (account_key(account), account, target))
            for source in batch.remember_assignments:
                self.db.execute('INSERT OR REPLACE INTO import_account_rules VALUES(?,?,?)',
                                (rule_scope(batch.path), source, assignments[source]))
            if duplicate:
                return {'status': 'duplicate', 'path': batch.path, 'id': duplicate['id']}
            cur = self.db.execute('INSERT INTO imports(path,file_hash,parser,imported_at,report) VALUES(?,?,?,?,?)',
                                  (batch.path, import_key, PARSER_VERSION, datetime.now(timezone.utc).isoformat(),
                                   json.dumps({'source_sha256': batch.file_hash, **batch.summary(),
                                               'account_assignments': assignments,
                                               'source_sheet': batch.source_sheet,
                                               'parser_provenance': {
                                                   'plugin_id': batch.plugin_id,
                                                   'plugin_version': batch.plugin_version,
                                                   'handler': batch.plugin_handler,
                                                   'detection_confidence': batch.detection_confidence,
                                               }}, ensure_ascii=False)))
            iid = cur.lastrowid
            result['id'] = iid
            result['documents'] = 0
            result['model_records'] = 0
            for kind in model_collections:
                for ordinal, record in enumerate(payload.get(kind, [])):
                    self.db.execute('INSERT INTO import_model_records VALUES(?,?,?,?)',
                                    (iid, kind, ordinal, json.dumps(record, ensure_ascii=False)))
                    result['model_records'] += 1
            for metadata, content in prepared_documents:
                self.db.execute('''INSERT INTO bank_documents(import_id,account,external_id,title,date,media_type,content_hash,content)
                    VALUES(?,?,?,?,?,?,?,?)''', (iid, metadata['account'], metadata['external_id'], metadata['title'],
                    metadata['date'], metadata['media_type'], metadata['content_hash'], content))
                result['documents'] += 1
            for source, target in assignments.items():
                self.db.execute('INSERT INTO import_account_links VALUES(?,?,?)', (iid, source, target))
            if assignments: self.db.execute('DELETE FROM coverage')
            links = self._import_links()
            mappings = self._depot_mappings()
            for snapshot in batch.snapshots:
                data = asdict(snapshot)
                semantic = {k: data[k] for k in ('account', 'as_of', 'complete')}
                semantic['positions'] = sorted([{k: v for k, v in p.items() if k != 'row'} for p in data['positions']], key=lambda p: p['key'])
                fingerprint = digest(semantic)
                old = self.db.execute('''SELECT s.content_hash,s.import_id FROM snapshots s JOIN imports i ON i.id=s.import_id
                    WHERE i.active=1 AND s.account=? AND s.effective_date=? AND s.complete=? ORDER BY s.id DESC LIMIT 1''',
                    (snapshot.account, snapshot.effective_date, snapshot.complete)).fetchone()
                if not batch.force_import and old and old[0] == fingerprint and links.get((old['import_id'], account_key(snapshot.account)), mappings.get(account_key(snapshot.account))) == assignments.get(account_key(snapshot.account), mappings.get(account_key(snapshot.account))):
                    result['unchanged'] += 1
                    continue
                self.db.execute('''INSERT INTO snapshots(import_id,account,period,as_of,effective_date,complete,content_hash,payload)
                    VALUES(?,?,?,?,?,?,?,?)''', (iid, snapshot.account, snapshot.period, snapshot.as_of, snapshot.effective_date,
                                                snapshot.complete, fingerprint, json.dumps(data, ensure_ascii=False)))
                result['snapshots'] += 1
            # Multiple columns/rows may describe the same account/category; sum within this file only.
            grouped = defaultdict(list)
            for b in batch.balances:
                grouped[(b.period, b.category, b.account, b.priority, b.sheet)].append(b)
            for (period, category, account, priority, sheet), values in grouped.items():
                val = str(sum(Decimal(v.value) for v in values))
                self.db.execute('''INSERT INTO balances(import_id,period,category,account,value,priority,sheet,row_number)
                    VALUES(?,?,?,?,?,?,?,?)''', (iid, period, category, account, val, priority, sheet, values[0].row))
                result['balances'] += 1
            from .settlement import kind_of
            coverage_accounts = [r[0] for r in self.db.execute('SELECT account FROM coverage')]
            covered_keys, clear_coverage = set(), False
            for tx in batch.transactions:
                data = asdict(tx)
                clear_coverage = clear_coverage or kind_of(data) == 'DIVIDEND'
                fingerprint = digest({k: v for k, v in data.items() if k != 'row'})
                old = self.db.execute('''SELECT t.content_hash,t.import_id FROM transactions t JOIN imports i ON i.id=t.import_id
                    WHERE i.active=1 AND t.account=? AND t.external_id=? ORDER BY t.id DESC LIMIT 1''',
                    (tx.account, tx.external_id)).fetchone()
                if not batch.force_import and old and old[0] == fingerprint and links.get((old['import_id'], account_key(tx.account)), mappings.get(account_key(tx.account), account_key(tx.account))) == assignments.get(account_key(tx.account), mappings.get(account_key(tx.account), account_key(tx.account))):
                    result['unchanged'] += 1
                    continue
                # A changed transaction ID is an explicit revision visible in the preview/audit.
                self.db.execute('''INSERT INTO transactions(import_id,account,external_id,date,content_hash,payload)
                    VALUES(?,?,?,?,?,?)''', (iid, tx.account, tx.external_id, tx.date, fingerprint, json.dumps(data)))
                tx_key = account_key(tx.account)
                covered_keys.add(tx_key); covered_keys.add(mappings.get(tx_key, tx_key))
                result['transactions'] += 1
            if clear_coverage:
                self.db.execute('DELETE FROM coverage')
            elif covered_keys:
                stale = [name for name in coverage_accounts if account_key(name) in covered_keys]
                if stale:
                    self.db.executemany('DELETE FROM coverage WHERE account=?', [(name,) for name in stale])
            for old in batch.replace_bank_bookings:
                self.db.execute('''INSERT OR IGNORE INTO bank_booking_replacements
                    SELECT id,? FROM transactions WHERE import_id=? AND account=? AND external_id=?''',
                    (iid, old['import_id'], old['depot'], old['external_id']))
        return result

    def correct_import(self, iid, edits):
        from .models import correction_number, digest
        from datetime import date
        entry = self.db.execute('SELECT * FROM imports WHERE id=? AND active=1', (iid,)).fetchone()
        if not entry: raise ValueError('Bitte einen aktiven Import auswählen.')
        if self.db.execute('SELECT 1 FROM bank_documents WHERE import_id=?', (iid,)).fetchone():
            raise ValueError('Originaldokumente werden nicht verändert. Bitte den Import zurücknehmen oder die Kontozuordnung ändern.')
        prepared = {}
        for table in ('balances', 'snapshots', 'transactions'):
            rows = [dict(r) for r in self.db.execute(f'SELECT * FROM {table} WHERE import_id=?', (iid,))]
            for row in rows:
                change = edits.get(table, {}).get(row['id'], {})
                if table == 'balances':
                    row.update({k: change[k] for k in ('account', 'period', 'category', 'value') if k in change})
                    date.fromisoformat(row['period'] + '-01')
                    row['value'] = correction_number(row['value'])
                    if row['value'] is not None: row['value'] = str(Decimal(row['value']).quantize(Decimal('.01')))
                    if row['value'] is None: raise ValueError('Saldo fehlt.')
                else:
                    payload = json.loads(row['payload'])
                    payload.update(change)
                    row['account'] = payload['account']
                    if table == 'snapshots':
                        date.fromisoformat(payload['as_of'] or payload['period'] + '-01')
                        if payload['as_of']: payload['period'] = payload['as_of'][:7]
                        row.update(period=payload['period'], as_of=payload['as_of'],
                                   effective_date=payload['as_of'] or payload['period']+'-01')
                        for position in payload['positions']:
                            for field in ('quantity', 'value', 'cost'):
                                position[field] = correction_number(position.get(field))
                    else:
                        date.fromisoformat(payload['date'])
                        row['date'] = payload['date']
                        row['external_id'] = payload['external_id']
                        if not row['external_id'].strip(): raise ValueError('Buchungs-ID fehlt.')
                        payload['amount'] = correction_number(payload['amount'])
                        if payload['amount'] is not None: payload['amount'] = str(Decimal(payload['amount']).quantize(Decimal('.01')))
                        if payload['amount'] is None: raise ValueError('Betrag fehlt.')
                    row['payload'] = json.dumps(payload, ensure_ascii=False)
                    row['content_hash'] = digest(payload)
                row['account'] = account_name(row['account'])
                if not row['account']: raise ValueError('Konto fehlt.')
            prepared[table] = rows
        with self.db:
            cur = self.db.execute('INSERT INTO imports(path,file_hash,parser,imported_at,report) VALUES(?,?,?,?,?)',
                (entry['path'], digest(prepared), entry['parser'], datetime.now(timezone.utc).isoformat(),
                 json.dumps({'correction_of': iid, 'warnings': [], 'note': 'Manuelle Importkorrektur'})))
            new_id = cur.lastrowid
            self.db.execute('INSERT INTO import_account_links SELECT ?,source_key,account_key FROM import_account_links WHERE import_id=?', (new_id, iid))
            correction_links = self._import_links()
            for table, rows in prepared.items():
                for row in rows:
                    old_id = row.pop('id'); row['import_id'] = new_id
                    target = correction_links.get((new_id, account_key(row['account'])))
                    if target is None:
                        self._register_account(row['account'])
                    columns = list(row)
                    cur = self.db.execute(f"INSERT INTO {table}({','.join(columns)}) VALUES({','.join('?' for _ in columns)})", list(row.values()))
                    if table == 'snapshots':
                        self.db.execute('INSERT OR IGNORE INTO depot_accounts VALUES(?,?,?)',
                            (account_key(row['account']), row['account'], target or account_key(row['account'])))
                        self.db.execute('INSERT INTO snapshot_exclusions(snapshot_id,reason) SELECT ?,reason FROM snapshot_exclusions WHERE snapshot_id=?', (cur.lastrowid, old_id))
            self.db.execute('''INSERT INTO import_model_records(import_id,kind,ordinal,payload)
                SELECT ?,kind,ordinal,payload FROM import_model_records WHERE import_id=?''', (new_id, iid))
            self.db.execute('UPDATE imports SET active=0 WHERE id=?', (iid,))
            self.db.execute('DELETE FROM coverage')
        return new_id

    def undo_import(self, iid):
        with self.db:
            self.db.execute('UPDATE imports SET active=0 WHERE id=?', (iid,))
            self.db.execute('DELETE FROM coverage')

    @cached_read
    def model_records(self, import_id=None, kind=None):
        clauses, values = [], []
        if import_id is not None: clauses.append('r.import_id=?'); values.append(import_id)
        if kind is not None: clauses.append('r.kind=?'); values.append(kind)
        where = (' WHERE ' + ' AND '.join(clauses)) if clauses else ''
        return [dict(row, payload=json.loads(row['payload'])) for row in self.db.execute(
            'SELECT r.* FROM import_model_records r JOIN imports i ON i.id=r.import_id AND i.active=1' +
            where + ' ORDER BY r.import_id,r.kind,r.ordinal', values)]

    def import_assignment_rows(self, import_ids):
        records = self._account_view()
        links = self._import_links()
        mappings = self._depot_mappings()
        result = []
        for iid in sorted(set(import_ids)):
            entry = self.db.execute('SELECT * FROM imports WHERE id=?', (iid,)).fetchone()
            if not entry:
                raise ValueError(f'Import {iid} existiert nicht mehr.')
            sources = {}
            for table in ('snapshots', 'balances', 'transactions', 'bank_documents'):
                for row in self.db.execute(f'SELECT DISTINCT account FROM {table} WHERE import_id=?', (iid,)):
                    if row['account'] == 'Archiv':
                        continue
                    key = account_key(row['account'])
                    sources.setdefault(key, {'name': row['account'], 'tables': set()})['tables'].add(table)
            for row in self.db.execute(
                    "SELECT kind,payload FROM import_model_records WHERE import_id=? AND kind IN ('tax_events','tax_details')",
                    (iid,)):
                payload = json.loads(row['payload'])
                name = payload.get('account', '')
                if not name:
                    continue
                key = account_key(name)
                sources.setdefault(key, {'name': name, 'tables': set()})['tables'].add(row['kind'])
            for key, source in sources.items():
                target = links.get((iid, key), mappings.get(key, key) if 'snapshots' in source['tables'] else key)
                record = records.get(target)
                result.append({'import_id': iid, 'path': entry['path'], 'active': entry['active'],
                    'source_key': key, 'source_name': source['name'], 'target_key': target,
                    'target_name': record['name'] if record else source['name'],
                    'required_kind': ('Depot' if source['tables'] & {'tax_events', 'tax_details'} else '')})
        return result

    def reassign_imports(self, changes):
        """Update source associations together; preserve imported payloads and values."""
        from .import_accounts import rule_scope, target_compatible
        with self.db:
            rows = {(r['import_id'], r['source_key']): r for r in self.import_assignment_rows([c['import_id'] for c in changes])}
            records = self._account_view()
            prepared = {}
            rules = {}
            for change in changes:
                key = (change['import_id'], change['source_key'])
                if key not in rows:
                    raise ValueError('Das Quellkonto gehört nicht zu diesem Import.')
                target = change['target_key']
                if not records.get(target, {}).get('active'):
                    raise ValueError('Bitte ein vorhandenes, aktives Zielkonto auswählen.')
                if rows[key]['required_kind'] and not target_compatible(records[target], rows[key]['required_kind']):
                    raise ValueError('Depot-Steuerdaten dürfen nur einem aktiven Depot zugeordnet werden.')
                if key in prepared:
                    raise ValueError('Quellkonto wurde mehrfach zugeordnet.')
                prepared[key] = target
                if change.get('remember'):
                    rule = (rule_scope(rows[key]['path']), key[1])
                    if rule in rules and rules[rule] != target:
                        raise ValueError('Widersprüchliche Regeln für dasselbe Quellkonto und dieselbe Dateifamilie.')
                    rules[rule] = target
            for (iid, source), target in prepared.items():
                self.db.execute('INSERT OR REPLACE INTO import_account_links VALUES(?,?,?)', (iid, source, target))
            for (scope, source), target in rules.items():
                self.db.execute('INSERT OR REPLACE INTO import_account_rules VALUES(?,?,?)', (scope, source, target))
            for iid in {key[0] for key in prepared}:
                report = json.loads(self.db.execute('SELECT report FROM imports WHERE id=?', (iid,)).fetchone()[0])
                report.setdefault('account_assignments', {}).update({source: target for (import_id, source), target in prepared.items() if import_id == iid})
                report.setdefault('assignment_history', []).append({'at': datetime.now(timezone.utc).isoformat(),
                    'changes': [{'source': source, 'before': rows[(import_id, source)]['target_key'], 'after': target}
                        for (import_id, source), target in prepared.items() if import_id == iid]})
                self.db.execute('UPDATE imports SET report=? WHERE id=?', (json.dumps(report, ensure_ascii=False), iid))
            if prepared:
                self.db.execute('DELETE FROM coverage')

    def delete_imports(self, import_ids):
        """Permanently remove exactly the selected imports in one transaction."""
        ids = sorted(set(int(iid) for iid in import_ids))
        if not ids:
            return 0
        with self.db:
            for iid in ids:
                if not self.db.execute('SELECT 1 FROM imports WHERE id=?', (iid,)).fetchone():
                    raise ValueError(f'Import {iid} existiert nicht mehr. Bitte die Ansicht aktualisieren.')
            has_costs = self.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='cost_corrections'").fetchone()
            for iid in ids:
                if has_costs:
                    self.db.execute('DELETE FROM cost_corrections WHERE snapshot_id IN (SELECT id FROM snapshots WHERE import_id=?)', (iid,))
                self.db.execute('DELETE FROM snapshot_exclusions WHERE snapshot_id IN (SELECT id FROM snapshots WHERE import_id=?)', (iid,))
                for table in ('import_account_links', 'snapshots', 'balances', 'transactions', 'bank_documents', 'import_model_records'):
                    self.db.execute(f'DELETE FROM {table} WHERE import_id=?', (iid,))
                self.db.execute('DELETE FROM imports WHERE id=?', (iid,))
            self.db.execute('DELETE FROM coverage')
        return len(ids)

    def _clear_import_data(self):
        if self.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='cost_corrections'").fetchone():
            self.db.execute('DELETE FROM cost_corrections')
        for table in ('snapshot_exclusions', 'import_account_links', 'snapshots', 'balances',
                      'transactions', 'bank_documents', 'import_model_records', 'imports', 'coverage',
                      'import_account_rules', 'depot_accounts'):
            self.db.execute(f'DELETE FROM {table}')

    def delete_all_imports(self):
        """Clear active and inactive imports and their assignments atomically."""
        with self.db:
            self._clear_import_data()

    def delete_all_accounts(self):
        """Start with empty accounts and history, without resurrecting imported accounts."""
        with self.db:
            self._clear_import_data()
            self.db.execute('DELETE FROM manual_balances')
            if self.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='account_tax_years'").fetchone():
                self.db.execute('DELETE FROM account_tax_years')
            self.db.execute('DELETE FROM accounts')

    def imports(self):
        return [dict(r) for r in self.db.execute('SELECT * FROM imports ORDER BY id DESC')]

    def bank_documents(self, account=None):
        records, links = self._account_view(), self._import_links()
        latest = {}
        rows = self.db.execute('''SELECT d.id,d.import_id,d.account,d.external_id,d.title,d.date,d.media_type,
            d.content_hash,length(d.content) AS size FROM bank_documents d JOIN imports i ON i.id=d.import_id
            WHERE i.active=1 ORDER BY d.id''')
        for row in rows:
            name = self._depot_account(row['account'], records, {}, links.get((row['import_id'], account_key(row['account']))))
            key = (account_key(row['account']), row['external_id'])
            if name is None:
                latest.pop(key, None)
                continue
            latest[key] = {**dict(row), 'source_account': row['account'], 'account': name}
        return sorted((r for r in latest.values() if not account or account_key(r['account']) == account_key(account)),
                      key=lambda r: (r['date'], r['id']), reverse=True)

    def bank_document_content(self, document_id):
        if not any(row['id'] == document_id for row in self.bank_documents()):
            raise ValueError('Dokument ist nicht mehr aktiv.')
        return bytes(self.db.execute('SELECT content FROM bank_documents WHERE id=?', (document_id,)).fetchone()[0])

    def history_skip_sheets(self):
        row = self.db.execute("SELECT value FROM meta WHERE key='history_skip_sheets'").fetchone()
        return json.loads(row[0]) if row else []

    def set_history_skip_sheets(self, names):
        names = sorted({name.strip().casefold() for name in names if name.strip()})
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO meta(key,value) VALUES(?,?)',
                            ('history_skip_sheets', json.dumps(names, ensure_ascii=False)))

    @cached_read
    def snapshots(self, account=None, include_hidden=False):
        records = self._account_view()
        mappings = self._depot_mappings()
        links = self._import_links()
        rows = self.db.execute('''SELECT s.*,i.path FROM snapshots s JOIN imports i ON i.id=s.import_id
                                 WHERE i.active=1 AND NOT EXISTS
                                 (SELECT 1 FROM snapshot_exclusions e WHERE e.snapshot_id=s.id)
                                 ORDER BY s.effective_date,s.id''')
        latest = {}
        for r in rows:
            r = dict(r)
            depot = r['account']
            name = self._depot_account(depot, records, mappings, links.get((r['import_id'], account_key(depot))))
            if (name is None and not include_hidden) or (account and account_key(name) != account_key(account)):
                continue
            r['account'] = name
            r['depot'] = depot
            latest[(account_key(depot), r['effective_date'], r['complete'])] = dict(r)
        return sorted(latest.values(), key=lambda r: (r['effective_date'], r['id']))

    @cached_read
    def aliases(self):
        candidates = defaultdict(set)
        for row in self.snapshots():
            for p in json.loads(row['payload'])['positions']:
                if p['wkn'] and p['isin']:
                    candidates[p['wkn']].add(p['isin'])
        return {'WKN:' + k: next(iter(v)) for k, v in candidates.items() if len(v) == 1}

    @cached_read
    def holdings(self, as_of='9999-12-31', account=None):
        """Materialize full snapshots + partial updates, without mixing accounts."""
        aliases = self.aliases()
        accounts = {}
        # Only decode the last complete baseline and its partial updates.
        # All older revisions remain available in storage and history.
        pending = {}
        for row in self.snapshots(include_hidden=True):
            if row['effective_date'] > as_of: continue
            depot_parts = row['depot'].split(' / ', 2)
            physical = account_key(canonical_depot(row['depot']))
            assigned = account_key(row['account']) if row['account'] is not None else None
            assigned_key = (assigned, physical)
            # Portable-package aliases need the target account to keep two
            # independently imported copies apart. A later online snapshot uses
            # only the physical depot name and joins an existing alias. Ordinary
            # raw sources remain target-independent so reassignment replaces the
            # old target instead of leaving a stale holding behind.
            key = (assigned_key if len(depot_parts) == 3 or assigned_key in pending
                   else (None, physical))
            row['_holding_key'] = key
            if row['complete'] or row['account'] is None: pending[key] = []
            pending.setdefault(key, []).append(row)
        for row in (r for rows in pending.values() for r in rows):
            data = json.loads(row['payload'])
            key = row['_holding_key']
            if row['account'] is None:
                accounts.pop(key, None)
                continue
            if row['complete'] or key not in accounts:
                accounts[key] = {}
            for p in accounts[key].values(): p['account'] = row['account']
            for pos in data['positions']:
                p = dict(pos)
                p['key'] = aliases.get(p['key'], p['key'])
                p.update(account=row['account'], depot=row['depot'], as_of=row['as_of'], period=row['period'], source=row['path'],
                         sheet=data['sheet'], snapshot_id=row['id'], date_basis=data['date_basis'])
                accounts[key][p['key']] = p
        return [p for positions in accounts.values() for p in positions.values() if not account or account_key(p['account']) == account_key(account)]

    @cached_read
    def state_history(self, account=None):
        """Every stored observation, including superseded intraday revisions.

        Values are observations, not investment returns. Partial snapshots are
        labelled explicitly and must never be summed as complete depot values.
        """
        from .state_history import observations
        return observations(self, account)

    @cached_read
    def _balance_observations(self):
        """Resolve dates and account assignments once per database revision."""
        records, links = self._account_view(), self._import_links()
        result = []
        for raw in self.db.execute('''SELECT b.*,i.path FROM balances b
                JOIN imports i ON i.id=b.import_id WHERE i.active=1 AND b.priority=20 ORDER BY b.id'''):
            row = dict(raw)
            stamp, display = balance_date(row)
            source = account_key(row['account'])
            name = self._depot_account(row['account'], records, {}, links.get((row['import_id'], source)))
            if name is None: continue
            row.update(account=name, effective_date=stamp, state_date=display)
            result.append(row)
        return result

    @cached_read
    def balances_at(self, as_of='9999-12-31'):
        """Last known assigned balances, preserving monthly date precision."""
        latest = {}
        for row in self._balance_observations():
            stamp = row['effective_date']
            if stamp > as_of: continue
            key = (account_key(row['account']), row['category'])
            old = latest.get(key)
            if old is None or (stamp, row['id']) > (old['effective_date'], old['id']): latest[key] = row
        return list(latest.values())

    @cached_read
    def balances(self):
        # Overview is a complete monthly block; a revision replaces the block,
        # including previously present accounts which have since disappeared.
        rows = list(self.db.execute('''SELECT b.*,i.path,i.report FROM balances b JOIN imports i ON i.id=b.import_id
                                      WHERE i.active=1 ORDER BY b.id'''))
        # Bank refreshes are individual account observations, never a replacement
        # for the complete monthly overview containing other banks.
        bank_rows = [r for r in rows if r['sheet'].startswith('PDF comdirect Finanzreport ') or json.loads(r['report']).get('source_sheet') in ('Online ING', 'Online comdirect', 'Online Baader', 'Online Renault Bank direkt')]
        bank_ids = {r['id'] for r in bank_rows}
        rows = [r for r in rows if r['id'] not in bank_ids]
        # Category-only history imports revise exactly that source/category.
        # They must not replace the bank's other overview balances.
        savings_rows = [r for r in rows if json.loads(r['report']).get('source_sheet', '').startswith('Tagesgeld/Festgeld · ')]
        savings_ids = {r['id'] for r in savings_rows}
        all_rows = rows
        rows = [r for r in rows if r['id'] not in savings_ids]
        links = self._import_links()
        mapped_sources = {account_key(r['account']) for r in all_rows if (r['import_id'], account_key(r['account'])) in links}
        def block_key(row):
            source = account_key(row['account'])
            return (row['period'], 'overview' if row['priority'] == 20 else 'archive', source if source in mapped_sources else None)
        selected_blocks = {}
        for r in rows:
            key = block_key(r)
            selected_blocks[key] = max(selected_blocks.get(key, 0), r['import_id'])
        rows = [r for r in rows if selected_blocks[block_key(r)] == r['import_id']]
        overlays = {}
        for r in savings_rows:
            if r['import_id'] > selected_blocks.get(block_key(r), 0):
                overlays[(r['period'], account_key(r['account']), r['category'])] = r
        rows = [r for r in rows if (r['period'], account_key(r['account']), r['category']) not in overlays]
        rows.extend(overlays.values())
        records = self._account_view()
        links = self._import_links()
        result = []
        for r in rows:
            target = links.get((r['import_id'], account_key(r['account'])))
            name = self._depot_account(r['account'], records, {}, target) if target else self._visible_account(r['account'], records)
            if name is not None:
                result.append({**dict(r), 'account': name})
        bank_groups = defaultdict(list)
        for r in bank_rows:
            target = links.get((r['import_id'], account_key(r['account'])))
            name = self._depot_account(r['account'], records, {}, target) if target else self._visible_account(r['account'], records)
            if name is not None:
                bank_groups[(r['period'], account_key(name), r['category'])].append({**dict(r), 'account': name})
        for key, observations in bank_groups.items():
            existing = [r for r in result if (r['period'], account_key(r['account']), r['category']) == key]
            latest = max(existing + observations, key=lambda r: (balance_date(r)[0], r['id']))
            result = [r for r in result if (r['period'], account_key(r['account']), r['category']) != key]
            result.append(latest)
        return result

    def wealth_series(self, include_retirement=False, include_property=False, subtract_debt=False, archive=False, account=None):
        groups = defaultdict(lambda: defaultdict(Decimal))
        balance_rows = self.balances()
        manual = list(self.db.execute('SELECT * FROM manual_balances ORDER BY effective_date,id'))
        records = self._account_view()
        periods = sorted({r['period'] for r in balance_rows} | {r['effective_date'][:7] for r in manual})
        imported_months = defaultdict(set)
        for r in balance_rows:
            if r['priority'] == 20:
                imported_months[r['account']].add(r['period'])
        imported_months = {name: sorted(months) for name, months in imported_months.items()}
        latest = {}
        pointer = 0
        for period in periods:
            while pointer < len(manual) and manual[pointer]['effective_date'][:7] <= period:
                latest[manual[pointer]['account_key']] = manual[pointer]
                pointer += 1
            for key, row in latest.items():
                record = records.get(key)
                if not record or not record['active']: continue
                # Newer imported statements take precedence over an older manual balance.
                months = imported_months.get(record['name'])
                index = bisect_right(months, period) - 1 if months else -1
                imported_period = months[index] if index >= 0 else ''
                if imported_period > row['effective_date'][:7]: continue
                balance_rows = [b for b in balance_rows if not (b['priority'] == 20 and b['period'] == period and b['account'] == record['name'])]
                kind = json.loads(record['details']).get('kind', '')
                category = {'Festgeld': 'Festgeld', 'Depot': 'Wertpapiere', 'Riester': 'Altersvorsorge',
                            'Direktversicherung': 'Altersvorsorge'}.get(kind, 'Liquidität')
                balance_rows.append({'period': period, 'account': record['name'], 'priority': 20,
                                     'category': category, 'value': row['value']})
        for r in balance_rows:
            if account and account_key(r['account']) != account_key(account):
                continue
            if r['priority'] == 10:
                if r['category'] == 'Immobilie (Schätzung)' and include_property:
                    groups[r['period']]['Immobilie (Schätzung)'] += Decimal(r['value'])
                elif archive and r['category'].startswith('Archiv:'):
                    groups[r['period']][r['category']] += Decimal(r['value'])
                continue
            if archive:
                continue
            cat = r['category']
            if cat == 'Altersvorsorge' and not include_retirement:
                continue
            if cat == 'Schulden':
                if subtract_debt:
                    groups[r['period']]['Schulden'] -= Decimal(r['value'])
            else:
                groups[r['period']][cat] += Decimal(r['value'])
        return [{'period': p, 'categories': dict(v), 'total': sum(v.values())} for p, v in sorted(groups.items())]

    @cached_read
    def transactions(self, account=None):
        details = {r['transaction_id']: json.loads(r['payload']) for r in self.db.execute('SELECT * FROM booking_details')}
        records = self._account_view()
        mappings = self._depot_mappings()
        links = self._import_links()
        rows = self.db.execute('''SELECT t.*,i.path FROM transactions t JOIN imports i ON i.id=t.import_id
                                 WHERE i.active=1 AND NOT EXISTS (
                                   SELECT 1 FROM bank_booking_replacements r JOIN imports newer ON newer.id=r.new_import
                                   WHERE r.old_transaction=t.id AND newer.active=1) ORDER BY t.id''')
        latest = {}
        for r in rows:
            name = self._depot_account(r['account'], records, mappings, links.get((r['import_id'], account_key(r['account']))))
            if name is None:
                latest.pop((account_key(r['account']), r['external_id']), None)
                continue
            data = json.loads(r['payload'])
            data.update(details.get(r['id'], {}))
            data['account'] = name
            from .settlement import kind_of
            if kind_of(data) in ('DIVIDEND', 'TAX', 'FEE'):
                owner = next((record for record in records.values() if record['name'] == name), None)
                cash_key = json.loads(owner['details']).get('cash_account_key') if owner else None
                if cash_key and cash_key in records and records[cash_key]['active']:
                    data['account'] = records[cash_key]['name']
                    data['performance_depot_key'] = data.get('performance_depot_key') or owner['account_key']
            data['depot'] = r['account']
            data.update(source=r['path'], import_id=r['import_id'])
            latest[(account_key(r['account']), r['external_id'])] = data
        from .booking_duplicates import consolidate_bookings
        result = consolidate_bookings(self, list(latest.values()))
        return sorted((t for t in result if not account or account_key(t['account']) == account_key(account)), key=lambda t: (t['date'], t['external_id']))

    def confirm_coverage(self, account, start, end):
        if start > end:
            raise ValueError('Beginn muss vor Ende liegen')
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO coverage VALUES(?,?,?,?)',
                            (account_name(account), start, end, datetime.now(timezone.utc).isoformat()))

    def has_coverage(self, account, start, end):
        return any(account_key(r['account']) == account_key(account) for r in self.db.execute(
            'SELECT account FROM coverage WHERE start_date<=? AND end_date>=?', (start, end)))

    def compare(self, start, end, account=None):
        before = {(p['depot'], p['key']): p for p in self.holdings(start, account)}
        after = {(p['depot'], p['key']): p for p in self.holdings(end, account)}
        result = []
        for key in sorted(before.keys() | after.keys()):
            a, b = before.get(key), after.get(key)
            qa = Decimal(a['quantity']) if a and a['quantity'] is not None else (Decimal(0) if not a else None)
            qb = Decimal(b['quantity']) if b and b['quantity'] is not None else (Decimal(0) if not b else None)
            # An absent position has zero value; an unvalued position is unknown.
            va = Decimal(a['value']) if a and a['value'] is not None else (Decimal(0) if not a else None)
            vb = Decimal(b['value']) if b and b['value'] is not None else (Decimal(0) if not b else None)
            result.append({'account': (b or a)['account'], 'depot': key[0], 'key': key[1], 'name': (b or a)['name'], 'before': va, 'after': vb,
                           'change': vb - va if va is not None and vb is not None else None, 'quantity_change': qb - qa if qa is not None and qb is not None else None,
                           'status': 'Neu im Bestand' if not a else ('Nicht mehr im Bestand' if not b else 'Bestand'),
                           'date_before': a['as_of'] or a['period'] if a else '',
                           'date_after': b['as_of'] or b['period'] if b else ''})
        return result
