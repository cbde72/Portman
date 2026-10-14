from collections import defaultdict
from decimal import Decimal
import json

from portfolio_v5.accounts import account_key


def purchase_value(transaction):
    value = abs(Decimal(transaction['amount']))
    # The booking amount is the settlement total; fees are already included.
    return value


def advance_holdings(rows, snapshots, transactions, as_of):
    baselines = {}
    for snapshot in snapshots:
        if snapshot['complete'] and snapshot['effective_date'] <= as_of and snapshot['account']:
            baselines[account_key(snapshot['depot'])] = snapshot
    positions = {(account_key(p['depot']), p['key'], p['currency']): dict(p) for p in rows}
    cutoffs = {key: p['as_of'] or p['period'] + '-01' for key, p in positions.items()}
    split_groups = defaultdict(set)
    for key in positions:
        split_groups[key[:2]].add(key)
    for tx in sorted(transactions, key=lambda t: (t['date'], t.get('sequence', 1000000), t['external_id'])):
        if tx['kind'] not in ('BUY', 'SELL', 'SPLIT') or tx['date'] > as_of:
            continue
        if tx['kind'] == 'SPLIT':
            for key in tuple(split_groups.get((account_key(tx['depot']), tx['security']), ())):
                p = positions.get(key)
                if p is None: continue
                baseline = baselines.get(key[0])
                if tx['date'] <= max(baseline['effective_date'] if baseline else '', cutoffs.get(key, '')):
                    continue
                if p.get('quantity') is not None:
                    p.update(quantity=str(Decimal(p['quantity']) * Decimal(tx['quantity'])),
                             as_of=tx['date'], period=tx['date'][:7], date_basis='transactions',
                             quantity_source=tx['source'])
            continue
        key = (account_key(tx['depot']), tx['security'], tx['currency'])
        baseline = baselines.get(key[0])
        if tx['date'] <= max(baseline['effective_date'] if baseline else '', cutoffs.get(key, '')):
            continue
        if baseline and tx['account'] != baseline['account']:
            continue
        p = positions.get(key)
        if p is not None and p.get('quantity') is None:
            continue
        if p is None and baseline is None and tx['kind'] == 'SELL':
            continue
        previous = Decimal(p['quantity']) if p else Decimal(0)
        quantity = previous + Decimal(tx['quantity']) * (-1 if tx['kind'] == 'SELL' else 1)
        if quantity < 0:
            raise ValueError('Depotbestand nicht fortschreibbar: Verkauf übersteigt den belegten Bestand für ' + tx['security'])
        if not quantity:
            split_groups[key[:2]].discard(key)
            positions.pop(key, None)
            continue
        if p is None:
            p = dict(key=tx['security'], isin=tx['security'].removeprefix('ISIN:'), wkn='',
                name=tx.get('purpose') or tx['security'], asset_type='Sonstiges', cost=None,
                account=tx['account'], depot=tx['depot'], snapshot_id=baseline['id'] if baseline else None, row=0,
                value=None, currency=tx['currency'], quote_date=None, source=tx['source'])
            positions[key] = p
            split_groups[key[:2]].add(key)
        if p.get('cost') is not None:
            p['cost'] = str(Decimal(p['cost']) * quantity / previous if tx['kind'] == 'SELL'
                            else Decimal(p['cost']) + purchase_value(tx))
        p.update(quantity=str(quantity), as_of=tx['date'], period=tx['date'][:7],
            quantity_source=tx['source'], sheet='Depotbuchungen · Stückzahl und Einstand', date_basis='transactions',
            valuation_note=('Stückzahl aus Abrechnungen fortgeschrieben; Kurswert unverändert aus letztem Depotstand.'
                            if baseline else 'Belegter Teilbestand aus Abrechnungen; kein vollständiger Depotstand.'))
    result = list(positions.values())
    apply_costs(result, snapshots, transactions, as_of)
    return result


def apply_costs(positions, snapshots, transactions, as_of):
    trades = [t for t in transactions if t['kind'] in ('BUY', 'SELL', 'SPLIT') and t['date'] <= as_of]
    depots = {account_key(p['depot']) for p in positions}
    events = [(t['date'], t.get('sequence', 1000000), t) for t in trades]
    observations = {(account_key(s['depot']), s['effective_date']): s for s in snapshots
                    if s['complete'] and s['account'] and s['effective_date'] <= as_of and account_key(s['depot']) in depots}
    events += [(s['effective_date'], 2000000000, s) for s in observations.values()]
    lots = {}
    for day, kind, event in sorted(events, key=lambda e: (e[0], e[1])):
        depot = account_key(event['depot'])
        if 'payload' in event:
            observed = {p['key']: p for p in json.loads(event['payload'])['positions']}
            for key in [k for k in lots if k[0] == depot and k[1] not in observed]:
                del lots[key]
            for security, p in observed.items():
                key = (depot, security, p.get('currency', 'EUR'))
                if p.get('quantity') is None:
                    lots.pop(key, None)
                    continue
                quantity = Decimal(p['quantity'])
                if p.get('cost_corrected') or sum((lot[0] for lot in lots.get(key, [])), Decimal(0)) != quantity:
                    # Unexplained deliveries/splits are not invented purchases.
                    lots[key] = [[quantity, Decimal(p['cost']) / quantity if p.get('cost') is not None and quantity else None]]
            continue
        if event['kind'] == 'SPLIT':
            ratio = Decimal(event['quantity'])
            for key, book in lots.items():
                if key[:2] == (depot, event['security']):
                    for lot in book:
                        lot[0] *= ratio
                        if lot[1] is not None:
                            lot[1] /= ratio
            continue
        key = (depot, event['security'], event['currency'])
        quantity = Decimal(event['quantity'])
        book = lots.setdefault(key, [])
        if event['kind'] == 'BUY':
            book.append([quantity, purchase_value(event) / quantity])
        else:
            while quantity and book:
                used = min(quantity, book[0][0])
                quantity -= used
                book[0][0] -= used
                if not book[0][0]: book.pop(0)
    for p in positions:
        book = lots.get((account_key(p['depot']), p['key'], p['currency']))
        if p.get('quantity') is None or (p.get('cost') is not None and p.get('date_basis') != 'transactions') or not book:
            continue
        known = sum((q * unit for q, unit in book if unit is not None), Decimal(0))
        unknown = sum((q for q, unit in book if unit is None), Decimal(0))
        if not unknown and sum((q for q, _ in book), Decimal(0)) == Decimal(p['quantity']):
            p['cost'] = str(known.quantize(Decimal('.01')))
            p['cost_source'] = 'Belegte Einstandswerte und Depot-Kaufbuchungen · inklusive enthaltener Kosten · FIFO'
        elif known:
            p['known_partial_cost'] = str(known.quantize(Decimal('.01')))
            p['unknown_cost_quantity'] = str(unknown)
