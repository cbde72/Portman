"""Version eight business revisions, bounded reads and auditable corrections."""
import json
import sqlite3
from contextlib import closing
from datetime import date, datetime, timezone
from decimal import Decimal
from functools import wraps
from pathlib import Path
from .repository import PortfolioRepository
from .repository_base import RepositoryV07
from .storage_v09 import migrate, backup_database, backup_records
from portfolio_v5.accounts import account_key
from portfolio_v5.storage import cached_read


def reference(tx):
    return json.dumps([tx['import_id'], tx.get('depot', tx['account']), tx['external_id']], ensure_ascii=False, separators=(',', ':'))


def booking_direction_matches(depot_tx, cash_tx):
    """Return whether both records describe the same economic cash direction."""
    expected = {'BUY': -1, 'SELL': 1, 'DIVIDEND': 1, 'TAX': -1,
                'TAX_REFUND': 1, 'FEE': -1}
    direction = expected.get(depot_tx.get('kind'))
    if direction is None:
        return False
    depot_amount = Decimal(str(depot_tx['amount']))
    cash_amount = Decimal(str(cash_tx['amount']))
    return depot_amount * direction > 0 and cash_amount * direction > 0


def valid_cash_transfer(a,b):
    kinds={'BANK_BOOKING','DEPOSIT','WITHDRAWAL','TRANSFER_IN','TRANSFER_OUT'}
    return bool(a and b and a['kind'] in kinds and b['kind'] in kinds
        and not a.get('security') and not b.get('security')
        and account_key(a['account'])!=account_key(b['account']) and a['currency']==b['currency']
        and Decimal(a['amount']) and Decimal(a['amount'])+Decimal(b['amount'])==0
        and abs((date.fromisoformat(a['date'])-date.fromisoformat(b['date'])).days)<=3)


def bounded(method):
    @wraps(method)
    def read(self, *args, **kwargs):
        if self.db.in_transaction: return method(self, *args, **kwargs)
        revision = (self.db.total_changes, self.db.execute('PRAGMA data_version').fetchone()[0])
        if getattr(self, '_v8_cache_revision', None) != revision:
            self._v8_cache_revision, self._v8_cache = revision, {}
        key = (method.__name__, args, tuple(sorted(kwargs.items())))
        if key not in self._v8_cache:
            result = method(self, *args, **kwargs)
            if len(self._v8_cache) >= getattr(self, '_v8_cache_cap', 32): self._v8_cache.pop(next(iter(self._v8_cache)))
            self._v8_cache[key] = result
        result = self._v8_cache[key]
        if getattr(self, '_no_copy_reads', False):
            return result
        # Nur Listen von Zeilen werden flach kopiert, damit Aufrufer die
        # gecachten Einträge nicht verändern. Dictionary-Ergebnisse (z. B.
        # wealth_summary) sind bereits frisch und werden unverändert zurückgegeben.
        if isinstance(result, list):
            return [dict(row) if isinstance(row, dict) else row for row in result]
        return result
    return read


class RepositoryV09(RepositoryV07):
    def __init__(self, database, backups=True):
        self.backup_folder = Path(database).parent / 'backups'
        self.backups_enabled = backups
        if Path(database).exists():
            with closing(sqlite3.connect(database)) as existing:
                version=existing.execute('PRAGMA user_version').fetchone()[0]
                if version>9: raise ValueError('Diese Datenbank benötigt eine neuere PortMan-Version.')
                asset_schema = existing.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='asset_identity'").fetchone()
                if backups and (version<9 or not asset_schema): backup_database(existing,self.backup_folder,'before-migration')
        PortfolioRepository.__init__(self, database)
        migrate(self.db)
        from .asset_schema import install_revision_triggers
        install_revision_triggers(self.db)
        if backups:
            today = datetime.now(timezone.utc).date().isoformat()
            if not any(r.get('created', '').startswith(today) for r in backup_records(self.backup_folder)):
                self.backup('daily')
            for name in ('delete_imports', 'delete_all_imports', 'delete_all_accounts', 'undo_import', 'correct_import', 'reassign_imports'):
                original = getattr(self.store, name)
                def protect(*args, _method=original, **kwargs):
                    self.backup('before-change')
                    return _method(*args, **kwargs)
                setattr(self.store, name, protect)

    def revision(self): return self.db.execute('SELECT value FROM v09_revision WHERE id=1').fetchone()[0]

    def poll_revision(self):
        """Best-effort UI poll; never wait behind a writer or invent a revision."""
        timeout = self.db.execute('PRAGMA busy_timeout').fetchone()[0]
        try:
            self.db.execute('PRAGMA busy_timeout=0')
            return self.revision()
        except sqlite3.OperationalError as error:
            code = getattr(error, 'sqlite_errorcode', 0) & 0xff
            if code in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
                return None
            raise
        finally:
            self.db.execute(f'PRAGMA busy_timeout={int(timeout)}')

    def backup(self, reason='manual', label=''):
        return backup_database(self.db, self.backup_folder, reason, label=label)

    @bounded
    def account_overview(self, as_of='9999-12-31'): return PortfolioRepository.account_overview(self, as_of)
    @bounded
    def wealth_summary(self, as_of='9999-12-31', account=None): return PortfolioRepository.wealth_summary(self, as_of, account)
    @bounded
    def holdings(self, as_of='9999-12-31', account=None): return PortfolioRepository.holdings(self, as_of, account)

    @cached_read
    def transactions(self, account=None):
        hidden = {(r[0], r[1], r[2]) for r in self.db.execute('''SELECT s.old_import,s.old_account,s.old_id
            FROM transaction_supersessions s JOIN imports i ON i.id=s.new_import WHERE i.active=1''')}
        corrections={r['ref']:dict(r) for r in self.db.execute('SELECT * FROM transaction_classifications')}
        edits={r['ref']:json.loads(r['payload']) for r in self.db.execute('SELECT ref,payload FROM transaction_edits')}
        excluded={r[0] for r in self.db.execute('SELECT ref FROM transaction_exclusions')}
        rows=[]
        records = {r['account_key']: r for r in self.account_records() if r['active']}
        name_keys = {account_key(r['name']): r['account_key'] for r in records.values()}
        rules = [dict(r) for r in self.db.execute('SELECT * FROM portfolio_assignment_rules ORDER BY length(text_pattern) DESC,id')]
        security_booking_context = {}
        for t in self.store.transactions(account):
            if (t['import_id'],t['depot'],t['external_id']) in hidden: continue
            t=dict(t); ref=reference(t)
            if ref in excluded: continue
            if ref in edits: t.update(edits[ref], edited=True)
            c=corrections.get(ref)
            if c: t.update(kind=c['kind'],security=c['security'],quantity=c['quantity'],classification_source=c['reason'])
            elif not t.get('edited'):
                from portfolio_v5.settlement import infer_security_booking
                inferred = infer_security_booking(self.store, t, security_booking_context)
                if inferred: t.update(inferred)
            if t.get('kind') in ('BANK_BOOKING','DIVIDEND','TAX','FEE') and not t.get('performance_depot_key'):
                text = ' '.join(str(t.get(k) or '') for k in ('purpose','booking_text','operation','counterparty')).casefold()
                source_key = name_keys.get(account_key(t['account']), account_key(t['account']))
                matches = [rule for rule in rules if rule['account_key'] == source_key
                           and t['kind'] in ('BANK_BOOKING', rule['kind'])
                           and rule['text_pattern'].casefold() in text]
                if len(matches) == 1:
                    rule = matches[0]
                    depot = records.get(rule['depot_key'])
                    details = json.loads(depot['details']) if depot else {}
                    allowed_cash = {value for value in
                        (details.get('cash_account_key'), *(details.get('cash_account_keys') or [])) if value}
                    if depot and source_key in allowed_cash:
                        t.update(kind=rule['kind'], security=rule['security'], performance_depot_key=rule['depot_key'],
                                 assignment_source='Gespeicherte Zuordnungsregel')
            if not c and not t.get('edited'):
                from .interest_recognition import is_interest_transaction
                if is_interest_transaction(t):
                    t.update(kind='INTEREST',
                             classification_source='Automatisch aus eindeutigem Zinsbuchungstext')
            rows.append(t)
        return rows

    @cached_read
    def tax_events(self, account=None, income_year=None):
        """Return immutable tax facts mapped to their current depot, deduplicated by event id."""
        links = self.store._import_links()
        mappings = self.store._depot_mappings()
        records = {row['account_key']: row for row in self.account_records() if row['active']}
        imports = {row['id']: row['path'] for row in self.db.execute(
            'SELECT id,path FROM imports WHERE active=1')}
        latest = {}
        for record in self.store.model_records(kind='tax_events'):
            event = dict(record['payload'])
            source_key = account_key(event.get('account', ''))
            target_key = links.get((record['import_id'], source_key), mappings.get(source_key, source_key))
            target = records.get(target_key)
            if target is None:
                continue
            event.update(account=target['name'], depot=event.get('account', ''), import_id=record['import_id'],
                         source=imports.get(record['import_id'], ''))
            identity = event.get('external_id') or json.dumps([
                target_key, event.get('security_ref'), event.get('income_year'), event.get('date'), event.get('type')])
            latest[identity] = event
        result = list(latest.values())
        if account:
            result = [event for event in result if account_key(event['account']) == account_key(account)]
        if income_year is not None:
            result = [event for event in result if str(event.get('income_year') or '') == str(income_year)]
        return sorted(result, key=lambda event: (event.get('date', ''), event.get('external_id', '')))

    @cached_read
    def tax_detail_records(self, account=None, tax_year=None):
        """Return lossless CSV facts with conservative PDF/cash-booking links."""
        from portfolio_v5.comdirect_tax_detail import date_value
        links, mappings = self.store._import_links(), self.store._depot_mappings()
        accounts = {row['account_key']: row for row in self.account_records() if row['active']}
        imports = {row['id']: row['path'] for row in self.db.execute(
            'SELECT id,path FROM imports WHERE active=1')}
        tax_events = self.tax_events()
        transactions = self.transactions()
        result, seen = [], set()
        for record in self.store.model_records(kind='tax_details'):
            row = dict(record['payload'])
            if row.get('external_id') in seen:
                continue
            seen.add(row.get('external_id'))
            values = row.get('original_values') or {}
            source_key = account_key(row.get('account', ''))
            target_key = links.get((record['import_id'], source_key), mappings.get(source_key, source_key))
            target = accounts.get(target_key)
            if target is None:
                continue
            tax_day = date_value(values, 'Steuerliches Datum')
            booking_day = date_value(values, 'Buchungstag')
            reference_no = values.get('Referenznummer', '').strip()
            wkn = values.get('WKN', '').strip().upper()
            master = self.db.execute('SELECT isin FROM security_master WHERE wkn=?', (wkn,)).fetchone()
            security_refs = {wkn, master['isin'] if master and master['isin'] else ''} - {''}
            try:
                csv_taxable = Decimal(values.get('Steuerbemessungsgrundlage', '').replace('.', '').replace(',', '.'))
            except Exception:
                csv_taxable = None
            candidates = [event for event in tax_events
                          if account_key(event.get('account', '')) == target_key
                          and (not security_refs or event.get('security_ref') in security_refs)
                          and ((reference_no and event.get('reference_no') == reference_no) or
                               (event.get('date') in (tax_day, booking_day) and csv_taxable is not None
                                and abs(Decimal(str(event.get('taxable_income') or 0))) == abs(csv_taxable)))]
            cash = [tx for tx in transactions
                    if account_key(tx.get('account', '')) == target_key
                    and tx.get('date') in (tax_day, booking_day)
                    and (reference_no and reference_no in ' '.join(str(tx.get(k) or '') for k in
                         ('transaction_reference', 'bank_reference', 'document_reference', 'purpose', 'booking_text')))]
            if len(candidates) == 1 and candidates[0].get('related_transaction_id'):
                related = [tx for tx in transactions
                           if tx.get('external_id') == candidates[0]['related_transaction_id']]
                if len(related) == 1:
                    cash = related
            linked_event = candidates[0] if len(candidates) == 1 else {}
            row.update(account=target['name'], depot=row.get('account', ''), import_id=record['import_id'],
                       source=imports.get(record['import_id'], ''), booking_date=booking_day,
                       tax_date=tax_day, tax_year=values.get('Steuerjahr', '').strip(),
                       document_date=linked_event.get('document_date', ''),
                       income_year=linked_event.get('income_year', ''),
                       linked_tax_event_id=linked_event.get('external_id', ''),
                       linked_transaction_id=(reference(cash[0]) if len(cash) == 1 else ''),
                       match_status=('ambiguous' if len(candidates) > 1 or len(cash) > 1 else
                                     'matched' if len(candidates) == 1 else 'unmatched'))
            if account and account_key(row['account']) != account_key(account):
                continue
            if tax_year is not None and row['tax_year'] != str(tax_year):
                continue
            result.append(row)
        return sorted(result, key=lambda row: (row.get('tax_date', ''), row.get('external_id', '')))

    def tax_event_bookings(self, account):
        """Project tax facts into the depot booking view without creating transactions."""
        rows = []
        for event in self.tax_events(account):
            details = [f"Vorabpauschale Ertragsjahr {event.get('income_year') or '?'}",
                       f"Basis {event.get('advance_tax_base') or 'unbekannt'} {event.get('currency') or 'EUR'}",
                       f"steuerpflichtig {event.get('taxable_income') or 'unbekannt'}",
                       f"Freistellungsauftrag {event.get('used_exemption') or '0.00'}",
                       f"Verlustverrechnung {event.get('loss_offset') or '0.00'}",
                       f"gezahlte Steuern {event.get('paid_taxes') or '0.00'}"]
            rows.append(dict(event, kind='VORABPAUSCHALE', amount='0.00', affects_cash=False,
                             value_date=event.get('date', ''), security=event.get('security_ref', ''),
                             purpose=' · '.join(details), counterparty='Steuerereignis',
                             taxes=event.get('paid_taxes'), fees=None, gross_income=None,
                             external_id=event.get('external_id', ''), tax_event=True))
        return rows

    def advance_tax_credit(self, account, security_ref, through_date='9999-12-31'):
        """Tax-only basis available for a later sale; never part of portfolio cost or performance."""
        return sum((abs(Decimal(str(event.get('advance_tax_base') or 0)))
                    for event in self.tax_events(account)
                    if event.get('type') in ('vorabpauschale', 'vorabpauschale_ausland')
                    and event.get('security_ref') == security_ref
                    and event.get('date', '') <= through_date), Decimal())

    def depot_payment_accounts(self, depot_key):
        """Return the legacy default plus additional allowed cash accounts."""
        record = next((r for r in self.account_records() if r['account_key'] == depot_key and r['active']), None)
        if not record or json.loads(record['details']).get('kind') != 'Depot':
            raise ValueError('Depot nicht gefunden.')
        details = json.loads(record['details'])
        default = details.get('cash_account_key') or ''
        keys = [default, *(details.get('cash_account_keys') or [])]
        active = {r['account_key'] for r in self.account_records() if r['active']}
        unique = []
        for key in keys:
            if key and key in active and key != depot_key and key not in unique:
                unique.append(key)
        return [{'account_key': key, 'default': key == default} for key in unique]

    def save_depot_payment_accounts(self, depot_key, account_keys, default_key=''):
        """Atomically retain the old default and save additional sources."""
        records = {r['account_key']: r for r in self.account_records() if r['active']}
        depot = records.get(depot_key)
        if not depot or json.loads(depot['details']).get('kind') != 'Depot':
            raise ValueError('Depot nicht gefunden.')
        keys = list(dict.fromkeys(str(key) for key in account_keys if key))
        if default_key and default_key not in keys:
            keys.insert(0, default_key)
        if any(key not in records or key == depot_key for key in keys):
            raise ValueError('Zahlungskonto ist nicht aktiv oder bezeichnet das Depot selbst.')
        details = json.loads(depot['details'])
        details['cash_account_key'] = default_key
        details['cash_account_keys'] = [key for key in keys if key != default_key]
        with self.db:
            self.db.execute('UPDATE accounts SET details=? WHERE account_key=?',
                            (json.dumps(details, ensure_ascii=False), depot_key))

    def booking_links(self, include_invalid=False):
        rows = [dict(row) for row in self.db.execute(
            'SELECT * FROM transaction_reconciliations ORDER BY id')]
        if include_invalid:
            return rows
        active = {reference(tx) for tx in self.transactions()}
        return [row for row in rows if row['depot_ref'] in active and row['cash_ref'] in active]

    def confirm_booking_link(self, depot_ref, cash_ref, reason, allocated_amount=None):
        txs = {reference(tx): tx for tx in self.transactions()}
        depot_tx, cash_tx = txs.get(depot_ref), txs.get(cash_ref)
        if not depot_tx or not cash_tx or depot_ref == cash_ref:
            raise ValueError('Beide aktiven Buchungen müssen ausgewählt werden.')
        if not depot_tx.get('performance_depot_key'):
            raise ValueError('Die Wertpapierbuchung besitzt keine Depotzuordnung.')
        allowed = {row['account_key'] for row in self.depot_payment_accounts(depot_tx['performance_depot_key'])}
        records = {account_key(r['name']): r['account_key'] for r in self.account_records() if r['active']}
        if records.get(account_key(cash_tx['account']), account_key(cash_tx['account'])) not in allowed:
            raise ValueError('Das Geldkonto ist für dieses Depot nicht als Zahlungsquelle zugelassen.')
        if depot_tx['currency'] != cash_tx['currency']:
            raise ValueError('Währungen stimmen nicht überein.')
        if not booking_direction_matches(depot_tx, cash_tx):
            raise ValueError('Die Zahlungsrichtung passt nicht zur Wertpapierbuchung.')
        try:
            amount = abs(Decimal(str(allocated_amount if allocated_amount is not None else cash_tx['amount'])))
        except Exception:
            raise ValueError('Ungültiger Zuordnungsbetrag.') from None
        if not amount.is_finite() or not amount:
            raise ValueError('Ungültiger Zuordnungsbetrag.')
        if not reason.strip():
            raise ValueError('Prüfgrund fehlt.')
        existing = [row for row in self.booking_links() if not (
            row['depot_ref'] == depot_ref and row['cash_ref'] == cash_ref)]
        depot_allocated = sum((Decimal(row['allocated_amount']) for row in existing
                               if row['depot_ref'] == depot_ref), Decimal())
        cash_allocated = sum((Decimal(row['allocated_amount']) for row in existing
                              if row['cash_ref'] == cash_ref), Decimal())
        if depot_allocated + amount > abs(Decimal(depot_tx['amount'])):
            raise ValueError('Der Zuordnungsbetrag überschreitet den verfügbaren Betrag der Depotbuchung.')
        if cash_allocated + amount > abs(Decimal(cash_tx['amount'])):
            raise ValueError('Der Zuordnungsbetrag überschreitet den verfügbaren Betrag der Geldkontobuchung.')
        with self.db:
            self.db.execute('''INSERT INTO transaction_reconciliations
                (depot_ref,cash_ref,allocated_amount,currency,status,reason)
                VALUES(?,?,?,?,?,?) ON CONFLICT(depot_ref,cash_ref) DO UPDATE SET
                allocated_amount=excluded.allocated_amount,currency=excluded.currency,
                status='manual',reason=excluded.reason''',
                (depot_ref, cash_ref, str(amount), depot_tx['currency'], 'manual', reason.strip()))

    def reconcile_depot_bookings(self, depot_key, persist=False):
        """Find only unique amount/date/reference matches; ambiguity is explicit."""
        transactions = self.transactions()
        links = self.booking_links()
        linked = {}
        for link in links:
            linked.setdefault(link['depot_ref'], []).append(link)
        allocated_by_cash = {}
        for link in links:
            allocated_by_cash[link['cash_ref']] = allocated_by_cash.get(link['cash_ref'], Decimal()) + Decimal(link['allocated_amount'])
        payment_keys = {row['account_key'] for row in self.depot_payment_accounts(depot_key)}
        names = {account_key(r['name']): r['account_key'] for r in self.account_records() if r['active']}
        cash = [(reference(tx), tx) for tx in transactions
                if names.get(account_key(tx['account']), account_key(tx['account'])) in payment_keys
                and not tx.get('security')]
        depot_transactions = [tx for tx in transactions if tx.get('performance_depot_key') == depot_key]
        matches = {}
        for tx in depot_transactions:
            ref = reference(tx)
            if linked.get(ref):
                continue
            own_key = names.get(account_key(tx['account']), account_key(tx['account']))
            if tx.get('affects_cash', True) and own_key in payment_keys:
                continue
            amount = abs(Decimal(tx['amount']))
            refs = {str(tx.get(field) or '').strip().casefold() for field in
                    ('transaction_reference','order_id','execution_ref','bank_reference') if tx.get(field)}
            candidates = []
            for cash_ref, candidate in cash:
                if cash_ref == ref:
                    continue
                remaining = abs(Decimal(candidate['amount'])) - allocated_by_cash.get(cash_ref, Decimal())
                if (candidate['currency'] != tx['currency'] or remaining < amount
                        or abs(Decimal(candidate['amount'])) != amount
                        or not booking_direction_matches(tx, candidate)):
                    continue
                days = abs((date.fromisoformat(candidate.get('value_date') or candidate['date']) -
                            date.fromisoformat(tx.get('pay_date') or tx['date'])).days)
                if days > 3:
                    continue
                other_refs = {str(candidate.get(field) or '').strip().casefold() for field in
                              ('transaction_reference','order_id','execution_ref','bank_reference') if candidate.get(field)}
                candidates.append((cash_ref, candidate, bool(refs & other_refs)))
            strong = [candidate for candidate in candidates if candidate[2]]
            matches[ref] = strong or candidates

        # A candidate must be unique from both directions.  This prevents two
        # equal trades from independently consuming the same bank booking.
        strong_cash_refs = {cash_ref for candidates in matches.values()
                            for cash_ref, _, strong in candidates if strong}
        eligible_edges = set()
        cash_usage = {}
        for depot_ref, candidates in matches.items():
            for cash_ref, _, strong in candidates:
                if cash_ref in strong_cash_refs and not strong:
                    continue
                eligible_edges.add((depot_ref, cash_ref))
                cash_usage.setdefault(cash_ref, set()).add(depot_ref)

        result = []
        reserved_cash = set()
        for tx in depot_transactions:
            ref = reference(tx)
            if linked.get(ref):
                allocated = sum((Decimal(row['allocated_amount']) for row in linked[ref]), Decimal())
                required = abs(Decimal(tx['amount']))
                state = 'conflict' if allocated > required else 'complete' if allocated == required else 'partial'
                status = {'conflict': 'Konflikt', 'complete': 'Vollständig abgeglichen',
                          'partial': 'Teilweise zugeordnet'}[state]
                result.append({'transaction': tx, 'status': status, 'state': state,
                               'allocated_amount': str(allocated),
                               'remaining_amount': str(max(required - allocated, Decimal())),
                               'links': linked[ref]})
                continue
            own_key = names.get(account_key(tx['account']), account_key(tx['account']))
            if tx.get('affects_cash', True) and own_key in payment_keys:
                result.append({'transaction': tx, 'status': 'Vollständig abgeglichen',
                               'state': 'complete', 'allocated_amount': str(abs(Decimal(tx['amount']))),
                               'remaining_amount': '0', 'links': []})
                continue
            amount = abs(Decimal(tx['amount']))
            candidates = matches.get(ref, [])
            exclusive = [item for item in candidates if (ref, item[0]) in eligible_edges
                         and len(cash_usage[item[0]]) == 1 and item[0] not in reserved_cash]
            state = 'open' if not candidates else 'conflict' if len(exclusive) != 1 else 'complete'
            status = {'open': 'Offen', 'conflict': 'Konflikt',
                      'complete': 'Vollständig abgeglichen'}[state]
            new_links = []
            if len(exclusive) == 1:
                cash_ref, _, _ = exclusive[0]
                reserved_cash.add(cash_ref)
                new_links = [dict(depot_ref=ref, cash_ref=cash_ref, allocated_amount=str(amount),
                                  currency=tx['currency'], status='matched',
                                  reason='Eindeutiger Betrag, Währung und Datumsabstand')]
                if persist:
                    with self.db:
                        self.db.execute('''INSERT OR IGNORE INTO transaction_reconciliations
                            (depot_ref,cash_ref,allocated_amount,currency,status,reason) VALUES(?,?,?,?,?,?)''',
                            tuple(new_links[0][key] for key in ('depot_ref','cash_ref','allocated_amount','currency','status','reason')))
            result.append({'transaction': tx, 'status': status, 'state': state,
                           'allocated_amount': str(amount if new_links else Decimal()),
                           'remaining_amount': str(Decimal() if new_links else amount), 'links': new_links,
                           'candidates': [item[0] for item in candidates]})
        return result

    def edit_transaction(self, ref, values, reason):
        tx = next((row for row in self.transactions() if reference(row) == ref), None)
        if tx is None: raise ValueError('Buchung nicht mehr aktiv.')
        reason = reason.strip()
        if not reason: raise ValueError('Bitte einen Grund für die Änderung angeben.')
        allowed = {'date','value_date','kind','amount','currency','counterparty','purpose','security','quantity',
                   'gross_income','gross_currency','fees','taxes','withholding_tax','solidarity_tax',
                   'withholding_country','withholding_tax_rate','transaction_reference',
                   'tax_rate','per_share_amount','per_share_currency',
                   'income_basis','performance_depot_key'}
        payload = {key: values[key] for key in allowed if key in values}
        from portfolio_v5.models import parse_date
        if not parse_date(payload.get('date')) or parse_date(payload['date']) != payload['date']:
            raise ValueError('Ungültiger Buchungstag.')
        value_date = payload.get('value_date')
        if value_date and (not parse_date(value_date) or parse_date(value_date) != value_date):
            raise ValueError('Ungültige Valuta.')
        try: amount = Decimal(str(payload.get('amount')))
        except Exception: raise ValueError('Ungültiger Betrag.') from None
        if not amount.is_finite(): raise ValueError('Ungültiger Betrag.')
        payload['amount'] = str(amount)
        payload['currency'] = str(payload.get('currency', '')).strip().upper()
        if len(payload['currency']) != 3: raise ValueError('Währung mit drei Buchstaben angeben.')
        for field in ('quantity', 'per_share_amount', 'gross_income', 'fees', 'taxes', 'withholding_tax', 'solidarity_tax',
                      'withholding_tax_rate'):
            value = payload.get(field)
            if value in (None, ''):
                payload[field] = None
                continue
            try: number = Decimal(str(value))
            except Exception: raise ValueError(f'Ungültiger Wert für {field}.') from None
            if not number.is_finite() or number < 0: raise ValueError(f'{field} muss eine nichtnegative Zahl sein.')
            payload[field] = str(number)
        if payload.get('withholding_tax_rate') is not None and Decimal(payload['withholding_tax_rate']) > 100:
            raise ValueError('Der Quellensteuersatz darf nicht über 100 % liegen.')
        tax_rate = payload.get('tax_rate')
        if tax_rate in (None, ''):
            payload['tax_rate'] = None
        else:
            try: tax_rate = Decimal(str(tax_rate))
            except Exception: raise ValueError('Ungültiger effektiver Steuersatz.') from None
            if not tax_rate.is_finite() or not Decimal() <= tax_rate <= Decimal(100):
                raise ValueError('Der effektive Steuersatz muss zwischen 0 und 100 % liegen.')
            payload['tax_rate'] = str(tax_rate)
        payload['withholding_country'] = str(payload.get('withholding_country') or '').strip().upper()
        if payload['withholding_country'] and (len(payload['withholding_country']) != 2 or
                                               not payload['withholding_country'].isalpha()):
            raise ValueError('Quellenstaat als zweistelligen Ländercode angeben, z. B. US.')
        payload['transaction_reference'] = str(payload.get('transaction_reference') or '').strip()
        payload['gross_currency'] = str(payload.get('gross_currency') or payload['currency']).strip().upper()
        if len(payload['gross_currency']) != 3: raise ValueError('Bruttowährung mit drei Buchstaben angeben.')
        payload['per_share_currency'] = str(payload.get('per_share_currency') or '').strip().upper()
        if payload.get('per_share_amount') is not None and len(payload['per_share_currency']) != 3:
            raise ValueError('Für den Betrag je Stück eine Währung mit drei Buchstaben angeben.')
        if payload.get('withholding_tax') is not None and payload.get('taxes') is not None:
            if Decimal(payload['withholding_tax']) > Decimal(payload['taxes']):
                raise ValueError('Die Quellensteuer darf nicht höher als die gesamten Steuern sein.')
        if payload.get('solidarity_tax') is not None and payload.get('taxes') is not None:
            if Decimal(payload['solidarity_tax']) > Decimal(payload['taxes']):
                raise ValueError('Der Solidaritätszuschlag darf nicht höher als die gesamten Steuern sein.')
        if payload.get('kind') == 'DIVIDEND' and payload.get('gross_income') is not None \
                and payload['gross_currency'] == payload['currency']:
            expected = Decimal(payload['gross_income']) - Decimal(payload.get('fees') or 0) - Decimal(payload.get('taxes') or 0)
            if abs(expected - amount) > Decimal('0.02'):
                raise ValueError('Bei der Dividende muss Netto = Brutto − Gebühren − Steuern gelten.')
        payload['income_basis'] = 'net'
        depot_key = payload.get('performance_depot_key', '')
        if depot_key:
            records = {r['account_key']: r for r in self.account_records() if r['active']}
            depot = records.get(depot_key)
            source_key = next((r['account_key'] for r in records.values()
                               if account_key(r['name']) == account_key(tx['account'])), account_key(tx['account']))
            if not depot or json.loads(depot['details']).get('kind') != 'Depot':
                raise ValueError('Bitte ein aktives Depot wählen.')
            if json.loads(depot['details']).get('cash_account_key') != source_key:
                raise ValueError('Das Depot ist nicht mit dem Verrechnungskonto dieser Buchung verbunden.')
        if payload.get('kind') not in ('BANK_BOOKING','BUY','SELL','DIVIDEND','INTEREST','DEPOSIT','WITHDRAWAL','FEE','TAX','TRANSFER_IN','TRANSFER_OUT'):
            raise ValueError('Ungültige Buchungsart.')
        if self.backups_enabled: self.backup('before-change')
        with self.db:
            self.db.execute('''INSERT INTO transaction_edits(ref,payload,reason) VALUES(?,?,?)
                ON CONFLICT(ref) DO UPDATE SET payload=excluded.payload,reason=excluded.reason,updated_at=CURRENT_TIMESTAMP''',
                (ref,json.dumps(payload,ensure_ascii=False),reason))

    def assign_portfolio_transaction(self, ref, kind, security, depot_key, reason, text_pattern=''):
        """Attach a cash booking to one depot/security and optionally remember a rule."""
        tx = next((row for row in self.transactions() if reference(row) == ref), None)
        if tx is None: raise ValueError('Buchung nicht mehr aktiv.')
        kind, security, depot_key, reason = kind.strip().upper(), security.strip(), depot_key.strip(), reason.strip()
        if kind not in ('DIVIDEND','TAX','FEE'): raise ValueError('Nur Dividenden, Steuern und Gebühren können so zugeordnet werden.')
        if not security: raise ValueError('Bitte eine Wertpapierposition auswählen.')
        if not reason: raise ValueError('Bitte einen Grund oder Beleg angeben.')
        records = {r['account_key']: r for r in self.account_records() if r['active']}
        depot = records.get(depot_key)
        source_key = next((r['account_key'] for r in records.values()
                           if account_key(r['name']) == account_key(tx['account'])), account_key(tx['account']))
        if not depot or json.loads(depot['details']).get('kind') != 'Depot':
            raise ValueError('Bitte ein aktives Depot auswählen.')
        if json.loads(depot['details']).get('cash_account_key') != source_key:
            raise ValueError('Das Depot ist nicht mit dem Verrechnungskonto dieser Buchung verbunden.')
        holdings = self.holdings(tx['date'], depot['name'])
        if not any(security in (p.get('isin'), p.get('key'), p.get('wkn')) for p in holdings):
            raise ValueError('Die gewählte Wertpapierposition ist an diesem Buchungstag nicht im Depot belegt.')
        existing = self.db.execute('SELECT payload FROM transaction_edits WHERE ref=?', (ref,)).fetchone()
        payload = json.loads(existing[0]) if existing else {}
        payload.update(kind=kind, security=security, performance_depot_key=depot_key)
        pattern = ' '.join(text_pattern.split()).casefold()
        if text_pattern and len(pattern) < 4:
            raise ValueError('Der Regeltext muss mindestens vier Zeichen enthalten.')
        if self.backups_enabled: self.backup('before-change')
        with self.db:
            self.db.execute('''INSERT INTO transaction_edits(ref,payload,reason) VALUES(?,?,?)
                ON CONFLICT(ref) DO UPDATE SET payload=excluded.payload,reason=excluded.reason,updated_at=CURRENT_TIMESTAMP''',
                (ref,json.dumps(payload,ensure_ascii=False),reason))
            if pattern:
                self.db.execute('''INSERT INTO portfolio_assignment_rules(account_key,kind,text_pattern,security,depot_key,reason)
                    VALUES(?,?,?,?,?,?) ON CONFLICT(account_key,kind,text_pattern) DO UPDATE SET
                    security=excluded.security,depot_key=excluded.depot_key,reason=excluded.reason,created_at=CURRENT_TIMESTAMP''',
                    (source_key,kind,pattern,security,depot_key,reason))

    def portfolio_assignment_rules(self):
        return [dict(r) for r in self.db.execute('SELECT * FROM portfolio_assignment_rules ORDER BY kind,text_pattern')]

    def remove_portfolio_assignment_rule(self, identifier):
        with self.db:
            self.db.execute('DELETE FROM portfolio_assignment_rules WHERE id=?', (identifier,))

    def exclude_transactions(self, refs, reason):
        active = {reference(tx) for tx in self.transactions()}
        refs = list(dict.fromkeys(refs)); reason = reason.strip()
        if not refs or not set(refs) <= active: raise ValueError('Mindestens eine aktive Buchung auswählen.')
        if not reason: raise ValueError('Bitte einen Grund für das Löschen angeben.')
        if self.backups_enabled: self.backup('before-change')
        with self.db:
            self.db.executemany('INSERT OR REPLACE INTO transaction_exclusions(ref,reason) VALUES(?,?)',
                                [(ref,reason) for ref in refs])

    def reviewed_duplicates(self):
        return {r[0] for r in self.db.execute('SELECT ref FROM transaction_duplicate_reviews')}

    def resolve_duplicate(self, ref, reason):
        tx = next((row for row in self.transactions() if reference(row) == ref), None)
        if tx is None or len(tx.get('booking_sources', ())) < 2:
            raise ValueError('Die ausgewählte Buchung ist keine erkennbare Dublette.')
        reason = reason.strip()
        if not reason: raise ValueError('Bitte das Prüfergebnis angeben.')
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO transaction_duplicate_reviews(ref,reason) VALUES(?,?)',
                            (ref,reason))

    def classify(self,ref,kind,security,quantity,reason):
        if ref not in {reference(t) for t in self.transactions()}: raise ValueError('Buchung nicht mehr aktiv.')
        if kind not in ('BANK_BOOKING','BUY','SELL','DIVIDEND','INTEREST','DEPOSIT','WITHDRAWAL','FEE','TAX','TRANSFER_IN','TRANSFER_OUT') or not reason.strip(): raise ValueError('Art und Begründung angeben.')
        q=Decimal(str(quantity)) if quantity not in (None,'') else None
        if q is not None and (not q.is_finite() or q<=0): raise ValueError('Positive Stückzahl angeben.')
        if kind in ('BUY','SELL','TRANSFER_IN','TRANSFER_OUT') and (q is None or not security.strip()): raise ValueError('Wertpapier und Stückzahl fehlen.')
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO transaction_classifications(ref,kind,security,quantity,reason) VALUES(?,?,?,?,?)',
                            (ref,kind,security.strip(),str(q) if q is not None else None,reason.strip()))

    def remove_classification(self,ref):
        with self.db: self.db.execute('DELETE FROM transaction_classifications WHERE ref=?',(ref,))

    def confirm_fee(self,aux_ref,field,fee_ref,reason):
        txs={reference(t):t for t in self.transactions()}; a,b=txs.get(aux_ref),txs.get(fee_ref)
        if not a or not b or aux_ref==fee_ref or field not in ('fees','taxes') or not reason.strip(): raise ValueError('Zwei unterschiedliche aktive Buchungen und Begründung erforderlich.')
        if b['kind']!=('FEE' if field=='fees' else 'TAX') or a['account']!=b['account'] or a['currency']!=b['currency'] or a.get(field) is None or abs(Decimal(a[field]))!=abs(Decimal(b['amount'])): raise ValueError('Gebührenbelege passen nicht zusammen.')
        with self.db: self.db.execute('INSERT INTO fee_links VALUES(?,?,?,?)',(aux_ref,field,fee_ref,reason.strip()))

    def fee_links(self,include_invalid=False):
        txs={reference(t):t for t in self.transactions()}; result=[]
        for r in self.db.execute('SELECT * FROM fee_links'):
            if include_invalid: result.append(dict(r)); continue
            a,b=txs.get(r['aux_ref']),txs.get(r['fee_ref'])
            if a and b and r['aux_ref']!=r['fee_ref'] and a['account']==b['account'] and a['currency']==b['currency'] and a.get(r['field']) is not None and b['kind']==('FEE' if r['field']=='fees' else 'TAX') and abs(Decimal(a[r['field']]))==abs(Decimal(b['amount'])): result.append(dict(r))
        return result

    def revoke_fee(self,aux_ref,field):
        with self.db: self.db.execute('DELETE FROM fee_links WHERE aux_ref=? AND field=?',(aux_ref,field))

    def correct_action(self,identifier,**values):
        from .import_v09 import transaction
        if not self.db.execute('SELECT 1 FROM corporate_actions WHERE id=? AND active=1',(identifier,)).fetchone(): raise ValueError('Maßnahme nicht mehr aktiv.')
        with transaction(self,commit=True):
            self.add_action(**values)
            self.revoke_action(identifier,'Durch korrigierte Maßnahme ersetzt: '+values['source'])

    def revoke_action(self,identifier,reason):
        if not reason.strip(): raise ValueError('Begründung fehlt.')
        with self.db:
            self.db.execute('UPDATE corporate_actions SET active=0,source=source||? WHERE id=? AND active=1',(' · Rücknahme: '+reason,identifier))

    def revoke_transfer(self,identifier,reason):
        if not reason.strip(): raise ValueError('Begründung fehlt.')
        with self.db:
            self.db.execute('UPDATE transfer_pairs SET note=note||? WHERE id=?',(' · Rücknahme: '+reason,identifier))
            self.db.execute('DELETE FROM transfer_pairs WHERE id=?',(identifier,))

    def confirm_recurring(self,candidate):
        active={reference(t) for t in self.transactions()}
        if len(candidate['refs'])<3 or not set(candidate['refs'])<=active: raise ValueError('Mindestens drei aktive Belege erforderlich.')
        if self.db.execute('SELECT 1 FROM recurring_rules WHERE account=? AND description=? AND currency=? AND amount=? AND interval_days=?',
                           (candidate['account'],candidate['description'],candidate['currency'],candidate['amount'],candidate['interval_days'])).fetchone(): raise ValueError('Diese Regelmäßigkeit wurde bereits bestätigt.')
        with self.db: self.db.execute('INSERT INTO recurring_rules(account,description,currency,amount,interval_days,source_refs) VALUES(?,?,?,?,?,?)',
            (candidate['account'],candidate['description'],candidate['currency'],candidate['amount'],candidate['interval_days'],json.dumps(candidate['refs'])))

    def sync_security_master(self):
        # Opening a reviewed database must not rewrite unchanged security records.
        if not self.db.execute("SELECT 1 FROM sqlite_master WHERE name='v09_revision'").fetchone():
            return PortfolioRepository.sync_security_master(self)
        signature=str(self.revision())
        old=self.db.execute("SELECT value FROM meta WHERE key='v09_master_signature'").fetchone()
        if old and old[0]==signature: return
        PortfolioRepository.sync_security_master(self)
        with self.db: self.db.execute("INSERT OR REPLACE INTO meta VALUES('v09_master_signature',?)",(str(self.revision()),))

    def remember_transaction_security_identifiers(self):
        """Add an evidenced ISIN from a booking to an existing WKN master record."""
        import re
        from portfolio_v5.models import valid_isin
        updates = set()
        for tx in self.transactions():
            if tx.get('assignment_source') != 'Automatisch aus Wertpapierkennung oder Positionsname und Betrag':
                continue
            text = ' '.join(str(tx.get(key) or '') for key in ('purpose', 'booking_text', 'operation', 'raw_text')).upper()
            isins = {value for value in re.findall(r'(?<![A-Z0-9])[A-Z]{2}[A-Z0-9]{9}\d(?![A-Z0-9])', text)
                     if valid_isin(value)}
            wkns = set(re.findall(r'\b(?:WKN|WPKNR)\s*:?\s*([A-Z0-9]{6})\b', text))
            if len(isins) == len(wkns) == 1:
                updates.add((next(iter(isins)), next(iter(wkns))))
        with self.db:
            for isin, wkn in updates:
                row = self.db.execute('SELECT security_key,isin FROM security_master WHERE wkn=?', (wkn,)).fetchone()
                conflict = self.db.execute('SELECT security_key FROM security_master WHERE isin=?', (isin,)).fetchone()
                if row and not row['isin'] and (not conflict or conflict['security_key'] == row['security_key']):
                    self.db.execute('UPDATE security_master SET isin=?,updated_at=CURRENT_TIMESTAMP WHERE security_key=?',
                                    (isin, row['security_key']))
        if updates and 'assets' in self.__dict__:
            self.assets.sync()

    def save_view(self, name, payload, replace=False):
        name = name.strip()
        if not name or len(name) > 100: raise ValueError('Name: 1 bis 100 Zeichen.')
        with self.db:
            old = self.db.execute('SELECT payload FROM saved_views WHERE name=?', (name,)).fetchone()
            if old and not replace: raise ValueError('Name bereits vorhanden. Aktualisieren oder unter neuem Namen speichern.')
            if old: self.db.execute('INSERT INTO view_history(name,payload,operation) VALUES(?,?,?)', (name, old[0], 'UPDATE'))
            self.db.execute('INSERT OR REPLACE INTO saved_views VALUES(?,?)', (name, json.dumps(payload, ensure_ascii=False)))

    def delete_view(self, name):
        with self.db:
            old = self.db.execute('SELECT payload FROM saved_views WHERE name=?', (name,)).fetchone()
            if old:
                self.db.execute('INSERT INTO view_history(name,payload,operation) VALUES(?,?,?)', (name, old[0], 'DELETE'))
                self.db.execute('DELETE FROM saved_views WHERE name=?', (name,))

    def undo_view(self):
        with self.db:
            row = self.db.execute('SELECT * FROM view_history ORDER BY id DESC LIMIT 1').fetchone()
            if not row: return None
            name = row['name']
            if row['operation'] == 'DELETE' and name in self.saved_views():
                name += ' (wiederhergestellt ' + str(row['id']) + ')'
            self.db.execute('INSERT OR REPLACE INTO saved_views VALUES(?,?)', (name, row['payload']))
            self.db.execute('DELETE FROM view_history WHERE id=?', (row['id'],))
            return name

    def csv_profiles(self): return {r[0]: json.loads(r[1]) for r in self.db.execute('SELECT * FROM csv_profiles ORDER BY name')}

    def save_csv_profile(self, name, payload):
        if not name.strip(): raise ValueError('Profilname fehlt.')
        with self.db: self.db.execute('INSERT OR REPLACE INTO csv_profiles VALUES(?,?)', (name.strip(), json.dumps(payload)))

    def transfer_pairs(self,include_invalid=False):
        active = {reference(t): t for t in self.transactions()}
        return [dict(r) for r in self.db.execute('SELECT * FROM transfer_pairs') if include_invalid or valid_cash_transfer(active.get(r['first_ref']),active.get(r['second_ref']))]

    def confirm_transfer(self, first, second, note):
        active = {reference(t): t for t in self.transactions()}
        a, b = active.get(first), active.get(second)
        if not valid_cash_transfer(a,b): raise ValueError('Nur passende Geldbewegungen zwischen unterschiedlichen Konten können als Umbuchung bestätigt werden.')
        if not a or not b or a['account'] == b['account'] or a['currency'] != b['currency'] or Decimal(a['amount']) + Decimal(b['amount']) != 0 or not Decimal(a['amount']):
            raise ValueError('Umbuchung benötigt zwei aktive, betragsgleiche Gegenbuchungen auf unterschiedlichen Konten.')
        if a.get('security') or b.get('security'): raise ValueError('Wertpapierbewegungen als Kapitalmaßnahme erfassen.')
        if abs((date.fromisoformat(a['date']) - date.fromisoformat(b['date'])).days) > 3: raise ValueError('Buchungen liegen mehr als drei Tage auseinander.')
        used = {r[k] for r in self.transfer_pairs(include_invalid=True) for k in ('first_ref', 'second_ref')}
        if first in used or second in used or not note.strip(): raise ValueError('Bereits zugeordnet oder Begründung fehlt.')
        with self.db: self.db.execute('INSERT INTO transfer_pairs(first_ref,second_ref,note) VALUES(?,?,?)', (first, second, note.strip()))

    def add_action(self, day, depot, security, kind, source, target='', target_depot='', ratio='1', units=None, sequence=0):
        date.fromisoformat(day)
        if kind not in ('SPLIT', 'MERGER', 'TRANSFER') or not source.strip() or not depot or not security: raise ValueError('Art, Depot, Wertpapier und Belegquelle angeben.')
        factor = Decimal(str(ratio))
        if not factor.is_finite() or factor <= 0: raise ValueError('Verhältnis muss positiv sein.')
        if kind == 'MERGER' and (not target or target == security): raise ValueError('Abweichende Zielkennung angeben.')
        if kind == 'TRANSFER':
            qty = Decimal(str(units))
            if not target_depot or target_depot == depot or not qty.is_finite() or qty <= 0: raise ValueError('Anderes Zieldepot und positive Stückzahl angeben.')
            if any(t['date'] == day and t.get('depot') == depot and t.get('security') == security and t['kind'] == 'TRANSFER_OUT' for t in self.transactions()):
                raise ValueError('An diesem Tag liegt bereits eine ausgehende Transferbuchung vor; Doppelzählung vermeiden.')
        with self.db:
            self.db.execute('INSERT INTO corporate_actions(day,depot,security,kind,target,target_depot,ratio,units,sequence,source) VALUES(?,?,?,?,?,?,?,?,?,?)',
                (day,depot,security,kind,target,target_depot,str(factor),str(units) if units is not None else None,int(sequence),source.strip()))

    def actions(self, start, end):
        return [dict(r) for r in self.db.execute('SELECT * FROM corporate_actions WHERE active=1 AND day>? AND day<=? ORDER BY day,sequence,id', (start,end))]

    def save_fx(self, day, currency, rate, source):
        date.fromisoformat(day); rate = Decimal(str(rate)); currency = currency.strip().upper()
        if len(currency) != 3 or not currency.isalpha() or not rate.is_finite() or rate <= 0 or not source.strip(): raise ValueError('Datum, ISO-Währung, positiven EUR-Kurs und Quelle angeben.')
        if currency == 'EUR' and rate != 1: raise ValueError('EUR/EUR muss 1 sein.')
        with self.db: self.db.execute('INSERT OR REPLACE INTO historical_fx VALUES(?,?,?,?)', (day,currency,str(rate),source.strip()))

    def historical_rate(self, currency, day):
        if currency == 'EUR': return Decimal(1)
        row = self.db.execute('SELECT day,rate FROM historical_fx WHERE currency=? AND day<=? ORDER BY day DESC LIMIT 1', (currency,day)).fetchone()
        return Decimal(row['rate']) if row and (date.fromisoformat(day) - date.fromisoformat(row['day'])).days <= 7 else None
