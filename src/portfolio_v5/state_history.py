"""Read-only access to retained import observations without daily deduplication."""
import json
import re
from datetime import date
from decimal import Decimal

from .accounts import account_key


def observations(store, account=None):
    records, mappings, links = store._account_view(), store._depot_mappings(), store._import_links()
    result = []
    for table in ('balances', 'snapshots'):
        extra = ',EXISTS(SELECT 1 FROM snapshot_exclusions e WHERE e.snapshot_id=r.id) AS excluded' if table == 'snapshots' else ',0 AS excluded'
        rows = store.db.execute(f'''SELECT r.*,i.imported_at,i.active,i.path{extra}
            FROM {table} r JOIN imports i ON i.id=r.import_id ORDER BY r.id''')
        for row in rows:
            name = store._depot_account(row['account'], records, mappings if table == 'snapshots' else {},
                                       links.get((row['import_id'], account_key(row['account']))))
            if name is None or (account and account_key(name) != account_key(account)): continue
            if table == 'snapshots':
                payload = json.loads(row['payload'])
                positions = payload['positions']
                valid = all(p.get('value') is not None and p.get('currency', 'EUR') == 'EUR' for p in positions)
                value = str(sum((Decimal(p['value']) for p in positions), Decimal(0))) if valid else None
                when = row['as_of'] or row['period']
                kind = 'Depot' if row['complete'] else 'Depot (Teilbestand)'
                sheet = payload['sheet']
            else:
                value, when, kind, sheet = row['value'], row['period'], row['category'], row['sheet']
                # Existing online adapters record the actual balance date here.
                # Never invent a day for monthly file imports.
                match = re.search(r'\b\d{4}-\d{2}-\d{2}\b', sheet) if sheet.startswith('Online ') else None
                if match:
                    try: when = date.fromisoformat(match[0]).isoformat()
                    except ValueError: pass
            result.append(dict(id=row['id'], import_id=row['import_id'], account=name,
                source_account=row['account'], kind=kind, date=when, value=value,
                imported_at=row['imported_at'], active=bool(row['active']) and not row['excluded'],
                source=row['path'], sheet=sheet))
    return sorted(result, key=lambda r: (r['date'], r['import_id'], r['id']))
