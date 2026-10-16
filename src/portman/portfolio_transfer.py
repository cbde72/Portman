"""Portable selection of account data, independent of credentials and UI settings."""
import json
from dataclasses import asdict, fields
from decimal import Decimal
from pathlib import Path
from portfolio_v5.accounts import account_key
from portfolio_v5.models import ImportBatch, Snapshot, Position, Balance, BankTransaction, digest
from .import_v09 import decode_batch, transaction
from .persistence import atomic_json


IDENTIFIER_FIELDS = {'iban': 'IBAN', 'bic': 'BIC', 'number': 'Konto- / Depotnummer'}


def merge_identifiers(current, incoming, name):
    merged = dict(current)
    for field, label in IDENTIFIER_FIELDS.items():
        value = str(incoming.get(field) or '').strip()
        old = str(current.get(field) or '').strip()
        if not value:
            continue
        if old and ''.join(old.split()).upper() != ''.join(value.split()).upper():
            raise ValueError(f'{name}: Abweichende {label} im Zielkonto. Bitte ein anderes oder neues Zielkonto wählen.')
        if not old:
            merged[field] = value
    return merged


def export_accounts(repo, keys, path):
    with transaction(repo):
        return _export_accounts(repo, keys, path)


def _export_accounts(repo, keys, path):
    if Path(path).resolve() == Path(repo.store.path).resolve():
        raise ValueError('Die Portfolio-Datenbank darf nicht als Exportdatei überschrieben werden.')
    keys = set(keys)
    records = {r['account_key']: r for r in repo.account_records() if r['active']}
    if not keys or not keys <= records.keys(): raise ValueError('Bitte vorhandene Konten auswählen.')
    batch = ImportBatch('Portfolio-Export', '', source_sheet='Portfolio-Paket')
    accounts = []
    for key in sorted(keys):
        r = records[key]
        accounts.append(dict(key=key, name=r['name'], details=json.loads(r['details']),
                             parent=r['parent_key'] if r['parent_key'] in keys else None,
                             manual=repo.balance_history(r['name'])))
    owners = {account_key(r['name']): key for key, r in records.items()}
    sources = {r['name']: key for key, r in records.items() if key in keys}
    def source(name, depot):
        value = name + ' / ' + depot
        sources[value] = owners[account_key(name)]
        return value
    corrections = {(r['snapshot_id'], r['security_key']): r['cost'] for r in repo.db.execute('SELECT * FROM cost_corrections ORDER BY id')}
    snapshot_rows = repo.snapshots()
    from .wallet_valuation import daily_values_for_snapshots
    daily_values = daily_values_for_snapshots(repo.db, (row['id'] for row in snapshot_rows
        if owners.get(account_key(row['account'])) in keys))
    for row in snapshot_rows:
        if owners.get(account_key(row['account'])) not in keys: continue
        data = json.loads(row['payload'])
        positions = [Position(**p) for p in data['positions']]
        for p in positions:
            p.cost = corrections.get((row['id'], p.key), p.cost)
            saved = daily_values.get((row['id'], p.key))
            if saved and Decimal(p.quantity) == Decimal(saved['quantity']):
                # Materialize frozen historical values: snapshot ids are local to
                # a portfolio and cannot be referenced by a portable package.
                p.value = saved['value']
                p.currency = saved['currency']
                p.quote_date = saved['day']
        batch.snapshots.append(Snapshot(source(row['account'], row['depot']), row['period'], row['as_of'],
                                        data.get('sheet', 'Portfolio'), positions, bool(row['complete'])))
    allowed = {f.name for f in fields(BankTransaction)}
    for row in repo.transactions():
        if owners.get(account_key(row['account'])) not in keys: continue
        data = {k: v for k, v in row.items() if k in allowed}
        data['external_id'] = 'portfolio-' + digest([row.get('depot', row['account']), row['external_id']])
        batch.transactions.append(BankTransaction(**data))
    links = repo.store._import_links()
    for raw in repo.db.execute('SELECT b.* FROM balances b JOIN imports i ON i.id=b.import_id WHERE i.active=1 ORDER BY b.id'):
        row = dict(raw)
        name = repo.store._depot_account(row['account'], records, {}, links.get((row['import_id'], account_key(row['account']))))
        if name and owners.get(account_key(name)) in keys:
            batch.balances.append(Balance(row['period'], row['category'], source(name, row['account']), row['value'],
                                          row['sheet'], row['row_number'], row['priority']))
    payload = dict(format='portman-accounts', version=1, accounts=accounts, sources=sources, batch=asdict(batch))
    payload['checksum'] = digest(payload)
    atomic_json(Path(path), payload)
    return payload


def read_package(path):
    payload = json.loads(Path(path).read_text(encoding='utf-8-sig'))
    if not isinstance(payload, dict) or payload.get('format') != 'portman-accounts' or payload.get('version') != 1:
        raise ValueError('Keine unterstützte PortMan-Kontendatei.')
    expected = payload.pop('checksum', None)
    if digest(payload) != expected: raise ValueError('Die Exportdatei ist unvollständig oder verändert.')
    payload['checksum'] = expected
    accounts = payload['accounts']
    keys = [a['key'] for a in accounts]
    if any(not isinstance(k, str) or not k.strip() for k in keys) or len(set(keys)) != len(keys) or any(not isinstance(a['name'], str) or not a['name'].strip() for a in accounts):
        raise ValueError('Ungültige Kontokennungen in der Exportdatei.')
    decode_batch(payload['batch'])
    return payload


def import_accounts(repo, payload, targets, progress=None):
    """targets maps selected package keys to existing or new target names."""
    progress = progress or (lambda current, total, text: None)
    total = len(targets) * 2 + 2
    completed = 0
    progress(completed, total, 'Import wird vorbereitet …')
    source_accounts = {a['key']: a for a in payload['accounts']}
    if not targets or not set(targets) <= source_accounts.keys(): raise ValueError('Bitte Konten auswählen.')
    if len({account_key(n) for n in targets.values()}) != len(targets):
        raise ValueError('Jedes Quellkonto benötigt ein eigenes Zielkonto.')
    batch = decode_batch(payload['batch'])
    names = {account_key(a['name']): a['key'] for a in payload['accounts']}
    def owner(name):
        key = payload['sources'].get(name)
        if key in source_accounts: return key
        return names.get(account_key(name), names.get(key, key))
    for attribute in ('snapshots', 'balances', 'transactions', 'documents'):
        setattr(batch, attribute, [r for r in getattr(batch, attribute) if owner(r.account) in targets])
    batch.path = 'Portfolio-Paket ' + payload['checksum'][:12]
    batch.file_hash = digest([payload['checksum'], sorted(targets.items())])
    existing = {r['account_key']: r for r in repo.account_records()}
    named_targets = {account_key(r['name']): key for key, r in existing.items()}
    target_keys = {name: named_targets.get(account_key(name), account_key(name)) for name in targets.values()}
    batch.account_names = list(targets.values())
    batch.account_assignments = {account_key(name): target_keys[name] for name in targets.values()}
    for attribute in ('snapshots', 'balances', 'transactions', 'documents'):
        for item in getattr(batch, attribute):
            target = targets[owner(item.account)]
            item.account = target + ' / ' + item.account if attribute in ('snapshots', 'balances') else target
            batch.account_assignments[account_key(item.account)] = target_keys[target]
    batch.source_sheet = 'Portfolio-Paket'
    if hasattr(repo, 'backup') and getattr(repo, 'backups_enabled', False): repo.backup('before-account-import')
    with transaction(repo, commit=True):
        new_details = {}
        for key, name in targets.items():
            found = existing.get(target_keys[name])
            if found and not found['active']: raise ValueError('Zielkonto ist deaktiviert: ' + name)
            if not found:
                details = dict(source_accounts[key]['details'])
                cash_source = details.pop('cash_account_key', None)
                repo.save_account(name, details)
                if cash_source in targets:
                    details['cash_account_key'] = target_keys[targets[cash_source]]
                new_details[key] = details
            else:
                current = json.loads(found['details'])
                merged = merge_identifiers(current, source_accounts[key]['details'], name)
                if merged != current:
                    repo.save_account(found['name'], merged, found['parent_key'], original=found['name'])
            completed += 1
            progress(completed, total, f'Konto / Depot „{name}“ wird vorbereitet …')
        # Restore links only once every selected account exists in the target.
        for key, details in new_details.items():
            parent = source_accounts[key]['parent']
            parent_key = target_keys[targets[parent]] if parent in targets else None
            repo.save_account(targets[key], details, parent_key, original=targets[key])
        completed += 1
        progress(completed, total, 'Konten und Verrechnungskonten werden verknüpft …')
        # The database commit consists of many rows but exposes no reliable row count.
        # Use an animated, indeterminate bar so the UI visibly remains active.
        progress(0, 0, 'Buchungen, Salden und Depotstände werden übernommen …')
        result = repo.commit_batches([batch])[0]
        if result['status'] == 'error': raise ValueError('; '.join(result['errors']))
        completed += 1
        progress(completed, total, 'Buchungen, Salden und Depotstände wurden übernommen.')
        if result['status'] == 'duplicate':
            progress(total, total, 'Import bereits vorhanden.')
            return result
        for key, name in targets.items():
            record = source_accounts[key]
            for balance in reversed(record['manual']):
                from datetime import date
                from decimal import Decimal
                date.fromisoformat(balance['effective_date'])
                if not Decimal(balance['value']).is_finite(): raise ValueError('Ungültiger Saldo im Paket.')
                # Internal decimal values bypass German input heuristics.
                if repo.db.execute('SELECT 1 FROM manual_balances WHERE account_key=? AND effective_date=? AND value=? AND note=?',
                                   (target_keys[name], balance['effective_date'], balance['value'], balance['note'])).fetchone(): continue
                repo.db.execute('INSERT INTO manual_balances(account_key,effective_date,value,note) VALUES(?,?,?,?)',
                                (target_keys[name], balance['effective_date'], balance['value'], balance['note']))
            completed += 1
            progress(completed, total, f'Historie für „{name}“ wird übernommen …')
    progress(total, total, 'Import abgeschlossen.')
    return result
