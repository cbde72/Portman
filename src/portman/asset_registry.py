"""Stable identities, dated sourced facts and read-through acquisition records."""
import json
from datetime import date
from decimal import Decimal
from uuid import uuid4, uuid5, NAMESPACE_URL
from portfolio_v5.accounts import account_key
from .asset_fields import validate
from .asset_schema import initialize


def transaction_ref(tx):
    return json.dumps([tx['import_id'], tx.get('depot', tx['account']), tx['external_id']],
                      ensure_ascii=False, separators=(',', ':'))


class AssetRegistry:
    def __init__(self, repo):
        self.repo = repo
        initialize(self.db)
        self.sync()

    @property
    def db(self):
        # Follow the import savepoint wrapper, including its rollback semantics.
        return self.repo.db

    def identity(self, key, *, aliases=None):
        if aliases is None:
            aliases = self.repo.store.aliases()
        canonical = aliases.get(key, key)
        if canonical.startswith('ISIN:'): canonical = canonical[5:]
        if not canonical.startswith('WKN:'):
            match = self.db.execute('SELECT security_key FROM security_master WHERE isin=?', (canonical,)).fetchone()
            if match: canonical = match[0]
        if canonical.startswith('WKN:'):
            matches = self.db.execute('SELECT security_key FROM security_master WHERE wkn=?', (canonical[4:],)).fetchall()
            if len(matches) == 1: canonical = matches[0][0]
        row = self.db.execute('SELECT asset_uuid FROM asset_keys WHERE security_key=?', (canonical,)).fetchone()
        if row is None:
            row = self.db.execute('SELECT asset_uuid FROM asset_keys WHERE security_key=?', (key,)).fetchone()
        if row is None:
            # An ISIN can arrive years after the first WKN-only statement.
            # Reuse the already recorded identity before allocating a new UUID.
            candidates = {alias for alias, target in aliases.items() if target == canonical}
            candidates.add('ISIN:' + canonical)
            existing = {r[0] for alias in candidates for r in self.db.execute(
                'SELECT asset_uuid FROM asset_keys WHERE security_key=?', (alias,))}
            if len(existing) == 1: row = (next(iter(existing)),)
        if row:
            present = {r[0] for r in self.db.execute('SELECT security_key FROM asset_keys WHERE security_key IN (?,?)', (key, canonical))}
            if present == {key, canonical}: return row[0]
        with self.db:
            uid = row[0] if row else str(uuid4())
            if row is None: self.db.execute('INSERT INTO asset_identity(uuid) VALUES(?)', (uid,))
            for alias in {key, canonical}:
                self.db.execute('INSERT OR IGNORE INTO asset_keys VALUES(?,?)', (alias, uid))
        return uid

    def position(self, key, depot, *, asset_uuid=None):
        uid = asset_uuid if asset_uuid is not None else self.identity(key)
        row = self.db.execute('SELECT uuid FROM asset_positions WHERE asset_uuid=? AND depot_key=?',
                              (uid, account_key(depot))).fetchone()
        if row: return row[0]
        position_id = str(uuid4())
        with self.db:
            self.db.execute('INSERT INTO asset_positions(uuid,asset_uuid,depot_key,depot_name) VALUES(?,?,?,?)',
                            (position_id, uid, account_key(depot), depot))
        return position_id

    def sync(self):
        aliases = self.repo.store.aliases()
        identities = {}
        def identity(key):
            if key not in identities:
                identities[key] = self.identity(key, aliases=aliases)
            return identities[key]
        for row in self.db.execute('SELECT security_key FROM security_master').fetchall(): identity(row[0])
        positions = set()
        for snapshot in self.repo.store.snapshots():
            for p in json.loads(snapshot['payload'])['positions']:
                positions.add((p.get('isin') or ('WKN:' + p['wkn'] if p.get('wkn') else p['key']), snapshot['depot']))
        for tx in self.repo.store.transactions():
            if tx.get('security'): positions.add((tx['security'], tx['depot']))
        for key, depot in sorted(positions):
            self.position(key, depot, asset_uuid=identity(key))
        for key, mapping in self.repo.market.mappings().items():
            if mapping.get('symbol'): self.remember_feed(key, mapping, asset_uuid=identity(key))

    def remember_feed(self, key, mapping, *, asset_uuid=None):
        uid = asset_uuid if asset_uuid is not None else self.identity(key)
        with self.db:
            self.db.execute('''INSERT OR IGNORE INTO asset_listings
                (uuid,asset_uuid,provider,symbol,exchange,currency,source) VALUES(?,?,?,?,?,?,?)''',
                (str(uuid4()), uid, mapping.get('provider', 'yahoo'), mapping['symbol'],
                 mapping.get('exchange', ''), mapping.get('currency', ''), 'Gespeicherte Kurszuordnung'))

    def listings(self, key):
        return [dict(r) for r in self.db.execute('SELECT * FROM asset_listings WHERE asset_uuid=? ORDER BY provider,symbol', (self.identity(key),))]

    def add_listing(self, key, provider, symbol, exchange, currency, source):
        from .online_providers import PROVIDERS
        import re
        if provider not in PROVIDERS or not re.fullmatch(r'[A-Za-z0-9.^=_/:-]{1,60}', symbol.strip()):
            raise ValueError('Gültigen Anbieter und Symbol angeben.')
        if not re.fullmatch(r'[A-Z]{3}', currency.strip().upper()): raise ValueError('Kurswährung fehlt.')
        if not source.strip(): raise ValueError('Quelle angeben.')
        uid = self.identity(key)
        with self.db:
            self.db.execute('''INSERT OR IGNORE INTO asset_listings
                (uuid,asset_uuid,provider,symbol,exchange,currency,source) VALUES(?,?,?,?,?,?,?)''',
                (str(uuid4()), uid, provider, symbol.strip(), exchange.strip(), currency.strip().upper(), source.strip()))

    def facts(self, key, scope, context='', as_of='9999-12-31'):
        row = self.db.execute('''SELECT * FROM asset_facts WHERE asset_uuid=? AND scope=? AND context=?
            AND valid_from<=? ORDER BY valid_from DESC LIMIT 1''', (self.identity(key), scope, context, as_of)).fetchone()
        return {**dict(row), 'values': json.loads(row['payload'])} if row else {'values': {}, 'source': '', 'valid_from': ''}

    def save_facts(self, key, scope, context, valid_from, values, source):
        values = validate(scope, values)
        if not source.strip(): raise ValueError('Quelle / Begründung fehlt.')
        day = date.fromisoformat(valid_from).isoformat()
        uid = self.identity(key)
        positions = {r[0] for r in self.db.execute('SELECT uuid FROM asset_positions WHERE asset_uuid=?', (uid,))}
        trades = {t['reference'] for t in self.transactions(key)} if scope in ('trade', 'tax') else set()
        listings = {r['uuid'] for r in self.listings(key)} if scope == 'listing' else set()
        valid = ((scope == 'security' and not context) or (scope == 'position' and context in positions)
                 or (scope == 'trade' and context in trades) or (scope == 'tax' and context in positions | trades)
                 or (scope == 'listing' and context in listings))
        if not valid: raise ValueError('Angaben sind keinem gültigen Wertpapier, Depot oder Beleg zugeordnet.')
        payload = json.dumps(values, ensure_ascii=False, sort_keys=True)
        old = self.db.execute('SELECT payload,source FROM asset_facts WHERE asset_uuid=? AND scope=? AND context=? AND valid_from=?',
                              (uid, scope, context, day)).fetchone()
        if old and old['payload'] == payload and old['source'] == source.strip(): return
        with self.db:
            self.db.execute('''INSERT INTO asset_facts(asset_uuid,scope,context,valid_from,payload,source)
                VALUES(?,?,?,?,?,?) ON CONFLICT(asset_uuid,scope,context,valid_from) DO UPDATE SET
                payload=excluded.payload,source=excluded.source,updated_at=CURRENT_TIMESTAMP''',
                (uid, scope, context, day, payload, source.strip()))
            self.db.execute('''INSERT INTO asset_audit(asset_uuid,scope,context,valid_from,old_payload,new_payload,source)
                VALUES(?,?,?,?,?,?,?)''', (uid, scope, context, day, old['payload'] if old else None, payload, source.strip()))

    def transactions(self, key):
        uid = self.identity(key)
        keys = {r[0] for r in self.db.execute('SELECT security_key FROM asset_keys WHERE asset_uuid=?', (uid,))}
        meta = self.repo.metadata().get(key, {})
        if meta.get('isin'): keys.update((meta['isin'], 'ISIN:' + meta['isin']))
        if meta.get('wkn'): keys.add('WKN:' + meta['wkn'])
        rows = []
        for tx in self.repo.transactions():
            if tx.get('security') not in keys: continue
            reference = transaction_ref(tx)
            row = {**tx, 'reference': reference, 'lot_uuid': str(uuid5(NAMESPACE_URL, uid + reference)) if tx['kind'] == 'BUY' else ''}
            doc = self.db.execute('SELECT file_hash,report FROM imports WHERE id=?', (tx['import_id'],)).fetchone()
            report = json.loads(doc['report']) if doc else {}
            row['document_hash'] = report.get('source_sha256', '')
            row['import_hash'] = doc['file_hash'] if doc else ''
            if tx['kind'] == 'BUY' and tx.get('quantity') and Decimal(tx['quantity']) > 0:
                row['acquisition_cost'] = str(abs(Decimal(tx['amount'])))
                row['unit_cost_including_fees'] = str(abs(Decimal(tx['amount'])) / Decimal(tx['quantity']))
            rows.append(row)
        return rows

    def positions(self, key):
        return [dict(r) for r in self.db.execute('SELECT * FROM asset_positions WHERE asset_uuid=? ORDER BY depot_name', (self.identity(key),))]

    def audit(self, key):
        return [dict(r) for r in self.db.execute('SELECT * FROM asset_audit WHERE asset_uuid=? ORDER BY id DESC', (self.identity(key),))]
