import json
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

from portfolio_v5.storage import Store, cached_read
from portfolio_v5.accounts import account_key
from .market_data import MarketDataStore
from .cash_timeline import cash_timeline, cash_through


class PortfolioRepository:
    """Single entry point for current holdings, history, imports and metadata."""
    def __init__(self, database):
        self.store = Store(database)
        self.market = MarketDataStore(self.store.db)
        self.store.db.executescript('''
        CREATE TABLE IF NOT EXISTS security_metadata(
          security_key TEXT PRIMARY KEY, region TEXT NOT NULL DEFAULT 'Unbekannt',
          cap_size TEXT NOT NULL DEFAULT 'Unbekannt', beta REAL NOT NULL DEFAULT 1,
          volatility REAL NOT NULL DEFAULT 15, dividend_yield REAL NOT NULL DEFAULT 0,
          updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        ''')
        columns={r['name'] for r in self.store.db.execute('PRAGMA table_info(security_metadata)')}
        if 'display_name' not in columns:
            self.store.db.execute('ALTER TABLE security_metadata ADD COLUMN display_name TEXT')
            self.store.db.commit()
        self.store.db.executescript('''
        CREATE TABLE IF NOT EXISTS security_master(
          security_key TEXT PRIMARY KEY, isin TEXT, wkn TEXT, canonical_name TEXT NOT NULL,
          asset_type TEXT NOT NULL DEFAULT 'Sonstiges', original_names TEXT NOT NULL DEFAULT '[]',
          region TEXT NOT NULL DEFAULT 'Unbekannt', cap_size TEXT NOT NULL DEFAULT 'Unbekannt',
          beta REAL NOT NULL DEFAULT 1, volatility REAL NOT NULL DEFAULT 15,
          dividend_yield REAL NOT NULL DEFAULT 0, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        CREATE UNIQUE INDEX IF NOT EXISTS security_master_isin ON security_master(isin) WHERE isin IS NOT NULL AND isin<>'';
        CREATE TABLE IF NOT EXISTS account_tax_years(
          account_key TEXT NOT NULL, year INTEGER NOT NULL,
          exemption TEXT NOT NULL DEFAULT '', capital_income TEXT NOT NULL DEFAULT '',
          taxes TEXT NOT NULL DEFAULT '', partial_exemption TEXT NOT NULL DEFAULT '',
          used_exemption TEXT NOT NULL DEFAULT '', solidarity_surcharge TEXT NOT NULL DEFAULT '',
          note TEXT NOT NULL DEFAULT '',
          PRIMARY KEY(account_key, year));
        CREATE TABLE IF NOT EXISTS institution_tax_years(
          institution_key TEXT NOT NULL, institution TEXT NOT NULL, year INTEGER NOT NULL,
          exemption TEXT NOT NULL DEFAULT '', capital_income TEXT NOT NULL DEFAULT '',
          taxes TEXT NOT NULL DEFAULT '', partial_exemption TEXT NOT NULL DEFAULT '',
          used_exemption TEXT NOT NULL DEFAULT '', solidarity_surcharge TEXT NOT NULL DEFAULT '',
          note TEXT NOT NULL DEFAULT '',
          PRIMARY KEY(institution_key, year));
        ''')
        tax_columns = {row['name'] for row in self.store.db.execute('PRAGMA table_info(account_tax_years)')}
        with self.store.db:
            for column in ('partial_exemption', 'used_exemption', 'solidarity_surcharge'):
                if column not in tax_columns:
                    self.store.db.execute(
                        f"ALTER TABLE account_tax_years ADD COLUMN {column} TEXT NOT NULL DEFAULT ''")
        self.store.db.execute('''CREATE TABLE IF NOT EXISTS first_activity(
          account TEXT NOT NULL, security_key TEXT NOT NULL, day TEXT NOT NULL,
          PRIMARY KEY(account, security_key))''')
        self.sync_security_master()
        self.store.db.execute('''CREATE TABLE IF NOT EXISTS security_wkn(
          security_key TEXT PRIMARY KEY, wkn TEXT NOT NULL, source TEXT NOT NULL,
          updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')
        self.store.db.execute('''CREATE TABLE IF NOT EXISTS security_classifications(
          security_key TEXT PRIMARY KEY REFERENCES security_master(security_key),
          asset_type TEXT, region TEXT, cap_size TEXT,
          updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')
        self.store.db.execute('''CREATE TABLE IF NOT EXISTS cost_corrections(
          id INTEGER PRIMARY KEY, snapshot_id INTEGER NOT NULL, security_key TEXT NOT NULL,
          cost TEXT NOT NULL, source TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP)''')
        from .asset_registry import AssetRegistry
        self.assets = AssetRegistry(self)
        self.market.asset_listing_callback = self.assets.remember_feed

    def holdings(self, as_of='9999-12-31', account=None):
        rows = self.store.holdings(as_of, account)
        corrections = {(r['snapshot_id'], r['security_key']): dict(r) for r in self.db.execute(
            'SELECT * FROM cost_corrections ORDER BY id')}
        for p in rows:
            correction = corrections.get((p['snapshot_id'], p['key']))
            if correction:
                p['cost'] = correction['cost']; p['cost_source'] = correction['source']
        from .baader_holdings import advance_holdings
        from .wallet_valuation import apply_daily_values
        from .security_movements import security_movements
        movements = security_movements(self.transactions(), rows)
        snapshots = self.store.snapshots(account)
        corrected_ids = {snapshot_id for snapshot_id, _ in corrections}
        for snapshot in snapshots:
            if snapshot['id'] not in corrected_ids:
                continue
            payload = json.loads(snapshot['payload'])
            for position in payload['positions']:
                correction = corrections.get((snapshot['id'], position['key']))
                if correction:
                    position['cost'] = correction['cost']
                    position['cost_corrected'] = True
            snapshot['payload'] = json.dumps(payload)
        if hasattr(type(self), 'actions'):
            accounts = {account_key(s['depot']): s['account'] for s in snapshots}
            accounts.update({account_key(t['depot']): t['account'] for t in movements})
            for action in self.actions('0001-01-01', as_of):
                if action['kind'] == 'SPLIT' and account_key(action['depot']) in accounts:
                    movements.append(dict(date=action['day'], kind='SPLIT', depot=action['depot'],
                        account=accounts[account_key(action['depot'])], security=action['security'],
                        quantity=action['ratio'], amount='0', currency='', source=action['source'],
                        external_id='split-' + str(action['id']), sequence=action['sequence']))
        if account:
            movements = [tx for tx in movements if account_key(tx['account']) == account_key(account)]
        return apply_daily_values(self.db, advance_holdings(rows, snapshots, movements, as_of))

    def correct_cost(self, snapshot_id, key, cost, source):
        cost = Decimal(str(cost)); source = source.strip()
        if not cost.is_finite() or cost <= 0 or not source:
            raise ValueError('Positiven Gesamteinstand und Belegquelle angeben.')
        if not any(p['snapshot_id'] == snapshot_id and p['key'] == key for p in self.store.holdings()):
            raise ValueError('Der ausgewählte Bestand ist nicht mehr aktuell.')
        with self.db:
            self.db.execute('INSERT INTO cost_corrections(snapshot_id,security_key,cost,source) VALUES(?,?,?,?)',
                            (snapshot_id, key, str(cost), source))

    def close(self): self.store.close()
    def accounts(self): return self.store.accounts()

    def account_tax_records(self, year):
        return [dict(row) for row in self.db.execute(
            'SELECT * FROM account_tax_years WHERE year=? ORDER BY account_key', (int(year),))]

    def institution_tax_records(self, year):
        return [dict(row) for row in self.db.execute(
            'SELECT * FROM institution_tax_years WHERE year=? ORDER BY institution', (int(year),))]

    def save_institution_tax_record(self, institution, year, exemption='', capital_income='', taxes='',
                                    partial_exemption='', used_exemption='', solidarity_surcharge='', note=''):
        institution = ' '.join(str(institution or '').split())
        if not institution:
            raise ValueError('Institut fehlt.')
        year = int(year)
        if not 1900 <= year <= 9999:
            raise ValueError('Ungültiges Steuerjahr.')
        values = []
        for label, value in (('Freistellungsauftrag', exemption), ('Kapitalerträge', capital_income),
                             ('Steuern', taxes), ('Teilfreistellung', partial_exemption),
                             ('Verbrauchter Freistellungsauftrag', used_exemption),
                             ('Solidaritätszuschlag', solidarity_surcharge)):
            text = str(value or '').strip()
            if not text:
                values.append('')
                continue
            text = text.replace('.', '').replace(',', '.') if ',' in text else text
            try:
                number = Decimal(text)
            except Exception as exc:
                raise ValueError(f'{label}: ungültiger Betrag.') from exc
            if not number.is_finite() or number < 0:
                raise ValueError(f'{label}: positiven Betrag eingeben.')
            values.append(str(number))
        key = institution.casefold()
        with self.db:
            self.db.execute('''INSERT INTO institution_tax_years(
                institution_key,institution,year,exemption,capital_income,taxes,partial_exemption,
                used_exemption,solidarity_surcharge,note) VALUES(?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(institution_key,year) DO UPDATE SET institution=excluded.institution,
                exemption=excluded.exemption,capital_income=excluded.capital_income,taxes=excluded.taxes,
                partial_exemption=excluded.partial_exemption,used_exemption=excluded.used_exemption,
                solidarity_surcharge=excluded.solidarity_surcharge,note=excluded.note''',
                (key, institution, year, *values, str(note or '').strip()))

    def rename_institution(self, original, name):
        from .institutions import account_institution
        name = ' '.join(name.split())
        if not name or len(name) > 120:
            raise ValueError('Bitte einen Institutsnamen mit 1 bis 120 Zeichen eingeben.')
        records = {r['account_key']: r for r in self.account_records()}
        groups = {key: account_institution(record, records) for key, record in records.items()}
        selected = [key for key, group in groups.items() if group.casefold() == original.casefold()]
        if not selected:
            raise ValueError('Das Institut wurde nicht gefunden.')
        if any(group.casefold() == name.casefold() and key not in selected for key, group in groups.items()):
            raise ValueError('Ein anderes Institut mit diesem Namen existiert bereits.')
        with self.db:
            for key in selected:
                details = json.loads(records[key]['details'])
                details['institution'] = name
                self.db.execute('UPDATE accounts SET details=? WHERE account_key=?',
                                (json.dumps(details, ensure_ascii=False), key))
            self.db.execute('''UPDATE institution_tax_years SET institution_key=?,institution=?
                               WHERE institution_key=?''', (name.casefold(), name, original.casefold()))
        return len(selected)
    def wealth_summary(self, as_of='9999-12-31', account=None):
        rows = [b for b in self.store.balances_at(as_of)
                if account is None or account_key(b['account']) == account_key(account)]
        for row in rows:
            row.setdefault('source', row.get('path', 'Importierter Saldo'))
        period = max((b['period'] for b in rows), default=None)
        histories = self.store.balance_histories()
        for record in self.account_records():
            if not record['active'] or (account and account_key(record['name']) != account_key(account)):
                continue
            history = [h for h in histories.get(record['name'], []) if h['effective_date'] <= as_of]
            imported_date = max((b.get('effective_date', '') for b in rows if b['account'] == record['name']), default='')
            if history and history[0]['effective_date'] >= imported_date:
                rows = [b for b in rows if b['account'] != record['name']]
                kind = json.loads(record['details']).get('kind', '')
                category = {'Festgeld': 'Festgeld', 'Depot': 'Wertpapiere', 'Riester': 'Altersvorsorge',
                            'Direktversicherung': 'Altersvorsorge'}.get(kind, 'Liquidität')
                rows.append({'account': record['name'], 'category': category, 'value': history[0]['value'],
                             'effective_date': history[0]['effective_date'], 'state_date': history[0]['effective_date'],
                             'source': history[0]['note'], 'manual': True})
        categories = defaultdict(Decimal)
        for row in rows:
            categories[row['category']] += Decimal(row['value']) * (-1 if row['category'] == 'Schulden' else 1)
        return {'value': sum(categories.values(), Decimal(0)) if rows else None,
                'period': period, 'categories': dict(categories),
                'accounts': len({account_key(b['account']) for b in rows}),
                'rows': rows, 'dates': sorted({b.get('effective_date', b.get('period', '')) for b in rows}),
                'sources': sorted({'Manueller Saldo' if b.get('manual') else 'Importierter Saldo' for b in rows})}
    @cached_read
    def _cash_timelines(self):
        transactions = defaultdict(list)
        for tx in self.transactions():
            if tx.get('currency') == 'EUR' and tx.get('affects_cash', True):
                transactions[account_key(tx['account'])].append(tx)
        return {key: cash_timeline(rows) for key, rows in transactions.items()}

    def account_overview(self, as_of='9999-12-31'):
        holdings = self.holdings(as_of)
        snapshots = [s for s in self.store.snapshots() if s['effective_date'] <= as_of]
        balances = self.store.balances_at(as_of)
        result = []
        all_depots = self.depots()
        snapshots_by_depot = defaultdict(list)
        snapshots_by_account = defaultdict(list)
        holdings_by_depot = defaultdict(list)
        balances_by_account = defaultdict(list)
        for snapshot in snapshots:
            snapshots_by_depot[account_key(snapshot['depot'])].append(snapshot)
            snapshots_by_account[snapshot['account']].append(snapshot)
        for position in holdings:
            holdings_by_depot[(account_key(position['depot']), position['account'])].append(position)
        for balance in balances:
            balances_by_account[balance['account']].append(balance)
        for account in self.accounts():
            depots = []
            for depot in all_depots:
                history = snapshots_by_depot[depot['depot_key']]
                latest = history[-1] if history else None
                if latest:
                    depot = {**depot, 'account': latest['account'], 'depot_name': latest['depot']}
                if depot['account'] != account:
                    continue
                positions = holdings_by_depot[(depot['depot_key'], account)]
                depots.append({**depot, 'value': sum((Decimal(p['value']) for p in positions), Decimal(0))
                               if latest and all(p['value'] is not None for p in positions) else None,
                               'date': (latest['as_of'] or latest['period']) if latest else '',
                               'positions': len(positions)})
            entries = balances_by_account[account]
            period = max((b['state_date'] for b in entries), default='')
            result.append({'name': account, 'depots': depots,
                           'depot_value': sum((d['value'] for d in depots if d['value'] is not None), Decimal(0))
                                          if any(d['value'] is not None for d in depots) else None,
                           'balance': sum((Decimal(b['value']) * (-1 if b['category'] == 'Schulden' else 1)
                                           for b in entries), Decimal(0)) if entries else None,
                           'period': period if entries else '',
                           'categories': ', '.join(sorted({b['category'] for b in entries}))})
        histories = self.store.balance_histories()
        for row in result:
            history = [h for h in histories.get(row['name'], []) if h['effective_date'] <= as_of]
            if history and (not row['period'] or history[0]['effective_date'] >= max((b['effective_date'] for b in balances_by_account.get(row['name'], [])), default='')):
                row['balance'] = Decimal(history[0]['value'])
                row['period'] = history[0]['effective_date']
                row['categories'] = 'Manueller Saldo · ' + history[0]['note']
            # A newer complete depot observation supersedes an older securities
            # overview balance. Cash balances are independent and stay intact.
            account_snapshots = snapshots_by_account[row['name']]
            latest = {}
            for snapshot in account_snapshots:
                latest[snapshot['depot']] = snapshot
            dates = [s['as_of'] for s in latest.values()]
            securities_balance = row['categories'] == 'Wertpapiere'
            if (securities_balance and latest and all(s['complete'] for s in latest.values())
                    and all(dates) and min(dates) >= (row['period'] or '')
                    and row['depot_value'] is not None):
                row['balance'] = row['depot_value']
                row['period'] = min(dates)
                row['categories'] = 'Wertpapiere · letzter vollständiger Depotstand'
        transactions = self._cash_timelines()
        future_balances = None
        for row in result:
            txs = transactions.get(account_key(row['name']), ())
            if not txs:
                continue
            cash, last_day = cash_through(txs, as_of)
            # A securities valuation is not a cash opening balance.
            anchor_date = row['period']
            securities = 'Wertpapiere' in row['categories']
            anchor = None if securities else row['balance']
            if anchor is None:
                future = [h for h in histories.get(row['name'], []) if h['effective_date'] > as_of] if not securities else []
                if future_balances is None:
                    future_balances = defaultdict(list)
                    for b in self.store.balances_at():
                        if b['category'] == 'Liquidität' and b['effective_date'] > as_of:
                            future_balances[b['account']].append({'effective_date': b['effective_date'], 'value': b['value']})
                future.extend(future_balances[row['name']])
                if future:
                    first = min(future, key=lambda h: h['effective_date'])
                    anchor_date, anchor = first['effective_date'], Decimal(first['value'])
            if anchor is None:
                if last_day is None:
                    continue
                row['balance'] = cash
                row['period'] = last_day
                row['categories'] = 'Umsatzsaldo · Startsaldo 0 €'
            else:
                anchor_date = anchor_date + '-01' if len(anchor_date) == 7 else anchor_date
                delta = cash - cash_through(txs, anchor_date)[0]
                if as_of >= anchor_date:
                    from .cash_balance_reference import cash_anchor
                    same_day = txs['manual'].get(anchor_date, ())
                    if same_day:
                        reference = cash_anchor(self, row['name'], anchor_date)
                        delta += sum((Decimal(t['amount']) for t in same_day if t.get('bank_reference') == reference), Decimal(0))
                row['balance'] = anchor + delta
                row['period'] = min(as_of, max(anchor_date, last_day or anchor_date))
                row['categories'] += ' · mit Umsätzen zum Stichtag'
            row['cash_from_transactions'] = True
        return result
    def previous_bank_depot(self, path):
        row = self.store.db.execute('''SELECT s.account FROM snapshots s JOIN imports i ON i.id=s.import_id
            WHERE i.active=1 AND i.path=? ORDER BY i.id DESC,s.id DESC LIMIT 1''', (str(path),)).fetchone()
        return row['account'] if row else None
    def preview_summary(self,batch):
        summary=batch.summary();changes={'new':0,'changed':0,'missing':0}
        for snap in batch.snapshots:
            before={p['key']:p for p in self.store.holdings(snap.effective_date)
                    if account_key(p['depot']) == account_key(snap.account)}
            after={p.key:p for p in snap.positions}
            changes['new']+=len(after.keys()-before.keys())
            changes['missing']+=len(before.keys()-after.keys()) if snap.complete else 0
            for key in after.keys() & before.keys():
                if str(after[key].quantity)!=str(before[key]['quantity']) or str(after[key].value)!=str(before[key]['value']):changes['changed']+=1
        summary.update(changes)
        summary['accounts']=', '.join(sorted(set(batch.account_names) | {s.account for s in batch.snapshots} | {t.account for t in batch.transactions} | {b.account for b in batch.balances} | {d.account for d in batch.documents}))
        dates = {s.as_of or s.period for s in batch.snapshots} | {b.period for b in batch.balances} | {d.date for d in batch.documents if d.date}
        if batch.transactions:
            transaction_dates = [t.date for t in batch.transactions]
            dates.add(min(transaction_dates) + ' … ' + max(transaction_dates))
        summary['dates']=', '.join(sorted(dates))
        return summary
    def commit_batches(self,batches):
        results=[]
        for batch in batches:
            if batch.errors: results.append({'path':batch.path,'status':'error','errors':batch.errors,'warnings':batch.summary()['warnings']})
            else:
                try:
                    result=self.store.import_batch(batch)
                except ValueError as exc:
                    result={'status':'error','errors':[str(exc)]}
                result.update(path=batch.path,warnings=batch.summary()['warnings']); results.append(result)
        if any(r['status']=='imported' for r in results): self.sync_security_master()
        return results
    def current(self, as_of='9999-12-31', account=None):
        raw=self.holdings(as_of,account)
        metadata=self.metadata()
        grouped={}
        for p in raw:
            key=p['key']; target=grouped.get(key)
            if target is None:
                target=dict(p); target['accounts']={p['account']}; grouped[key]=target
            else:
                target['quantity']=str(Decimal(target['quantity'])+Decimal(p['quantity']))
                target['cost']=(str(Decimal(target['cost'])+Decimal(p['cost']))
                                if target['cost'] is not None and p['cost'] is not None else None)
                target['value']=(str(Decimal(target['value'])+Decimal(p['value']))
                                 if target['value'] is not None and p['value'] is not None else None)
                target['accounts'].add(p['account'])
            target.update(metadata.get(key,metadata.get(p.get('isin',''),{})))
            if target.get('canonical_name'):
                target['name']=target['canonical_name']
        return list(grouped.values())
    def metadata(self):
        records = {r['security_key']:dict(r) for r in self.store.db.execute('SELECT * FROM security_master')}
        for row in self.db.execute('SELECT * FROM security_wkn'):
            if row['security_key'] in records:
                records[row['security_key']].update(wkn=row['wkn'], wkn_source=row['source'])
        for override in self.db.execute('SELECT * FROM security_classifications'):
            if override['security_key'] in records:
                records[override['security_key']].update({field: override[field] for field in
                    ('asset_type', 'region', 'cap_size') if override[field] is not None})
        return records

    def save_wkn(self, key, wkn, source='Manuell eingetragen'):
        return self.update_position(key, wkn=wkn, source=source)

    def _resolve_security_key(self, key):
        """Resolve a current ISIN/WKN alias to the stable master key."""
        value = str(key or '').strip().upper()
        direct = self.db.execute(
            'SELECT security_key FROM security_master WHERE security_key=?', (value,)).fetchone()
        if direct:
            return direct['security_key']
        if value.startswith('WKN:'):
            rows = self.db.execute(
                'SELECT security_key FROM security_master WHERE wkn=?', (value[4:],)).fetchall()
        else:
            rows = self.db.execute(
                'SELECT security_key FROM security_master WHERE isin=? OR wkn=?', (value, value)).fetchall()
        keys = {row['security_key'] for row in rows}
        return next(iter(keys)) if len(keys) == 1 else None

    def _save_wkn(self, key, wkn, source):
        wkn = wkn.strip().upper()
        if len(wkn) != 6 or not all(c in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789' for c in wkn):
            raise ValueError('Eine WKN besteht aus genau sechs Buchstaben oder Ziffern.')
        records = self.metadata()
        if key not in records:
            raise ValueError('Wertpapier nicht gefunden. Bitte die Positionen neu laden.')
        if any(k != key and r.get('wkn') == wkn and not (k == 'WKN:' + wkn and not r.get('isin'))
               for k, r in records.items()):
            raise ValueError('Diese WKN ist bereits einem anderen Wertpapier zugeordnet.')
        if not source.strip():
            raise ValueError('Bitte eine Quelle angeben.')
        with self.db:
            self.db.execute('''INSERT INTO security_wkn(security_key,wkn,source) VALUES(?,?,?)
                ON CONFLICT(security_key) DO UPDATE SET wkn=excluded.wkn,source=excluded.source,
                updated_at=CURRENT_TIMESTAMP''', (key, wkn, source.strip()))

    def update_position(self, key, *, classification=None, wkn=None, source='Manuell eingetragen'):
        """Single write entry point for user initiated position master-data edits."""
        if classification is None and wkn is None:
            raise ValueError('Keine Änderung für die Depotposition angegeben.')
        key = self._resolve_security_key(key)
        if key is None:
            raise ValueError('Wertpapier nicht gefunden. Bitte die Depotpositionen neu laden.')
        if classification is not None:
            self._save_security_classification(key, classification)
        if wkn is not None:
            self._save_wkn(key, wkn, source)

    def security_classification(self, key):
        from .security_classification import CLASSIFICATION_CHOICES
        key = self._resolve_security_key(key)
        if key is None:
            raise ValueError('Wertpapier nicht gefunden. Bitte die Depotpositionen neu laden.')
        row = self.db.execute('SELECT * FROM security_master WHERE security_key=?', (key,)).fetchone()
        override = self.db.execute('SELECT * FROM security_classifications WHERE security_key=?', (key,)).fetchone()
        return {'name': row['canonical_name'],
                'base': {field: row[field] for field in CLASSIFICATION_CHOICES},
                'overrides': {field: override[field] if override else None for field in CLASSIFICATION_CHOICES}}

    def save_security_classification(self, key, values):
        return self.update_position(key, classification=values)

    def _save_security_classification(self, key, values):
        from .security_classification import CLASSIFICATION_CHOICES
        state = self.security_classification(key)
        if set(values) - set(CLASSIFICATION_CHOICES):
            raise ValueError('Unbekanntes Zuordnungsfeld.')
        merged = {**state['overrides'], **values}
        for field, value in merged.items():
            if value is not None and value not in CLASSIFICATION_CHOICES[field]:
                raise ValueError('Bitte einen gültigen Wert aus der Auswahlliste wählen.')
        with self.db:
            if all(value is None for value in merged.values()):
                self.db.execute('DELETE FROM security_classifications WHERE security_key=?', (key,))
            else:
                self.db.execute('''INSERT INTO security_classifications(security_key,asset_type,region,cap_size)
                    VALUES(?,?,?,?) ON CONFLICT(security_key) DO UPDATE SET asset_type=excluded.asset_type,
                    region=excluded.region,cap_size=excluded.cap_size,updated_at=CURRENT_TIMESTAMP''',
                    (key, merged['asset_type'], merged['region'], merged['cap_size']))

    def sync_security_master(self):
        positions = [p for snap in self.store.snapshots()
                     for p in json.loads(snap['payload'])['positions']]
        # A security may first be known only by WKN and receive its ISIN in a
        # later import.  Keep the already established master key; otherwise an
        # INSERT under the ISIN key would collide with the unique ISIN index.
        master_rows = [dict(r) for r in self.store.db.execute(
            'SELECT security_key,isin,wkn FROM security_master')]
        by_isin = {r['isin']: r['security_key'] for r in master_rows if r['isin']}
        by_wkn = {r['wkn']: r['security_key'] for r in master_rows if r['wkn']}
        imported_isin_by_wkn = {}
        for p in positions:
            if p.get('isin') and p.get('wkn'):
                imported_isin_by_wkn.setdefault(p['wkn'], set()).add(p['isin'])
        imported_isin_by_wkn = {wkn: next(iter(isins)) for wkn, isins in imported_isin_by_wkn.items()
                                if len(isins) == 1}
        seen={}
        for p in positions:
            isin = p.get('isin') or imported_isin_by_wkn.get(p.get('wkn', ''), '')
            key = (by_isin.get(isin) or by_wkn.get(p.get('wkn', '')) or isin
                   or ('WKN:'+p['wkn'] if p.get('wkn') else p['key']))
            item=seen.setdefault(key,{'isin':isin,'wkn':p.get('wkn', ''),'name':p['name'],
                                      'type':p['asset_type'],'names':set()})
            if not item['isin'] and isin: item['isin'] = isin
            if not item['wkn'] and p.get('wkn'): item['wkn'] = p['wkn']
            if p['name']: item['names'].add(p['name'])
        legacy = {r['security_key']: dict(r) for r in self.store.db.execute('SELECT * FROM security_metadata')}
        existing = {r['security_key']: dict(r) for r in self.store.db.execute('SELECT security_key,canonical_name,original_names FROM security_master')}
        rows = []
        for key, p in seen.items():
            old = existing.get(key)
            meta = legacy.get(key, {})
            names = set(p['names'])
            if old:
                try: names.update(json.loads(old['original_names']))
                except Exception: pass
            canonical = (old['canonical_name'] if old else None) or meta.get('display_name') or p['name'] or key
            rows.append((key, p['isin'], p['wkn'], canonical, p['type'], json.dumps(sorted(names), ensure_ascii=False),
                         meta.get('region', 'Unbekannt'), meta.get('cap_size', 'Unbekannt'), meta.get('beta', 1),
                         meta.get('volatility', 15), meta.get('dividend_yield', 0)))
        with self.store.db:
            self.store.db.executemany('''INSERT INTO security_master
              (security_key,isin,wkn,canonical_name,asset_type,original_names,region,cap_size,beta,volatility,dividend_yield)
              VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(security_key) DO UPDATE SET
              isin=COALESCE(NULLIF(excluded.isin,''),security_master.isin),
              wkn=COALESCE(NULLIF(excluded.wkn,''),security_master.wkn),asset_type=excluded.asset_type,
              original_names=excluded.original_names,updated_at=CURRENT_TIMESTAMP''', rows)
        if 'assets' in self.__dict__:
            self.assets.sync()
    def save_metadata(self, holdings):
        with self.store.db:
            for h in holdings:
                existing = (self.db.execute('SELECT security_key FROM security_master WHERE isin=?', (h.isin,)).fetchone()
                            if h.isin else None)
                if existing is None and h.wkn:
                    existing = self.db.execute('SELECT security_key FROM security_master WHERE wkn=?', (h.wkn,)).fetchone()
                key = existing['security_key'] if existing else (h.isin or ('WKN:'+h.wkn))
                # Broad saves receive the effective UI values. Do not copy manual
                # overrides into the base metadata, or resetting would lose meaning.
                base = self.db.execute('SELECT * FROM security_master WHERE security_key=?', (key,)).fetchone()
                override = self.db.execute('SELECT * FROM security_classifications WHERE security_key=?', (key,)).fetchone()
                classification = {field: base[field] if base and override and override[field] is not None else getattr(h, field)
                                  for field in ('asset_type', 'region', 'cap_size')}
                self.store.db.execute('''INSERT INTO security_metadata(security_key,region,cap_size,beta,volatility,dividend_yield,display_name,updated_at)
                  VALUES(?,?,?,?,?,?,?,CURRENT_TIMESTAMP) ON CONFLICT(security_key) DO UPDATE SET
                  region=excluded.region,cap_size=excluded.cap_size,beta=excluded.beta,
                  volatility=excluded.volatility,dividend_yield=excluded.dividend_yield,
                  display_name=excluded.display_name,updated_at=CURRENT_TIMESTAMP''',
                  (key,classification['region'],classification['cap_size'],h.beta,h.volatility,h.dividend_yield,h.name))
                self.store.db.execute('''INSERT INTO security_master
                  (security_key,isin,wkn,canonical_name,asset_type,region,cap_size,beta,volatility,dividend_yield)
                  VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(security_key) DO UPDATE SET
                  canonical_name=excluded.canonical_name,asset_type=excluded.asset_type,region=excluded.region,
                  cap_size=excluded.cap_size,beta=excluded.beta,volatility=excluded.volatility,
                  dividend_yield=excluded.dividend_yield,updated_at=CURRENT_TIMESTAMP''',
                  (key,h.isin,h.wkn,h.name,classification['asset_type'],classification['region'],classification['cap_size'],h.beta,h.volatility,h.dividend_yield))
    def migrate_legacy_metadata(self,path):
        path=Path(path); marker='legacy_metadata_migrated'
        if self.store.db.execute('SELECT 1 FROM meta WHERE key=?',(marker,)).fetchone() or not path.exists(): return 0
        data=json.loads(path.read_text(encoding='utf-8')); count=0
        with self.store.db:
            for key,h in data.items():
                self.store.db.execute('''INSERT OR IGNORE INTO security_metadata
                  (security_key,region,cap_size,beta,volatility,dividend_yield) VALUES(?,?,?,?,?,?)''',
                  (h.get('isin') or key,h.get('region','Unbekannt'),h.get('cap_size','Unbekannt'),h.get('beta',1),h.get('volatility',15),h.get('dividend_yield',0)))
                count+=1
            self.store.db.execute('INSERT OR REPLACE INTO meta VALUES(?,?)',(marker,str(count)))
        return count
    def scope_dates(self):
        """Selectable dates from both securities and cash history.

        Monthly balances use the month end as a filter boundary, not as a
        claimed statement date; the UI explicitly labels them as monthly data.
        """
        from calendar import monthrange
        choices = {}
        for balance in self.store.balances():
            period = balance['period']
            year, month = map(int, period.split('-'))
            boundary = f'{period}-{monthrange(year, month)[1]:02d}'
            choices[boundary] = f'{period} (Monatsstand)'
        active = {r['account_key'] for r in self.account_records() if r['active']}
        for row in self.db.execute('SELECT account_key,effective_date FROM manual_balances'):
            if row['account_key'] in active:
                choices.setdefault(row['effective_date'], row['effective_date'])
        for snapshot in self.store.snapshots():
            value = snapshot['effective_date']
            choices.setdefault(value, value)
        return [(choices[value], value) for value in sorted(choices, reverse=True)]

    def __getattr__(self,name): return getattr(self.store,name)
