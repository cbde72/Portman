"""Derived displays, with dates/currencies and no guessed missing input."""
from datetime import date
from decimal import Decimal
from .price_history import historical_positions, stored_history, history_plan


def summary_rows(repo, key):
    uid = repo.assets.identity(key)
    keys = {r[0] for r in repo.db.execute('SELECT security_key FROM asset_keys WHERE asset_uuid=?', (uid,))}
    meta = repo.metadata().get(key, {})
    rows = [('ISIN', meta.get('isin')), ('WKN', meta.get('wkn')), ('Anlageklasse', meta.get('asset_type'))]
    transactions = repo.assets.transactions(key)
    if transactions: rows.append(('Letzte erfasste Bewegung', max(t['date'] for t in transactions)))
    first = next((p for p in historical_positions(repo) if p['key'] in keys), None)
    if first:
        rows.extend([('Erste Aktivität', first['history_start']),
                     ('Tage seit erster Aktivität (keine Aussage zu Unterbrechungen)',
                      (date.today() - date.fromisoformat(first['history_start'])).days)])
    for p in repo.holdings():
        if p['key'] not in keys: continue
        prefix = p['depot'] + ' · ' + p['currency'] + ' · '
        quantity = Decimal(p['quantity']) if p.get('quantity') is not None else None
        cost = Decimal(p['cost']) if p.get('cost') is not None else None
        value = Decimal(p['value']) if p.get('value') is not None else None
        rows.extend([(prefix + 'Bestandsstichtag', p.get('as_of') or p.get('period')),
                     (prefix + 'Stücke', quantity), (prefix + 'Bestandseinstand', cost),
                     (prefix + 'Mischkurs des Restbestands', cost / quantity if cost is not None and quantity else None),
                     (prefix + 'Gespeicherter Marktwert', value),
                     (prefix + 'Unrealisiert (auf Basis des gespeicherten Marktwerts)', value - cost if value is not None and cost is not None else None),
                     (prefix + 'Unrealisiert %', (value / cost - 1) * 100 if value is not None and cost else None)])
    record = repo.market.records().get(key, {}).get('data', {})
    rows.extend([('Letzter Onlinekurs · ' + record.get('currency', ''), record.get('metrics', {}).get('price')),
                 ('Onlinekurs-Zeitstempel', record.get('quote_time')), ('Kursquelle', record.get('provider'))])
    if first:
        data = stored_history(repo, key, first['history_start'])
        prices = [Decimal(str(p['close'])) for p in data['prices']]
        if prices:
            peak, drawdown = prices[0], Decimal(0)
            for price in prices:
                peak = max(peak, price); drawdown = min(drawdown, price / peak - 1)
            prefix = data['currency'] + ' · unbereinigte gespeicherte Schlusskurse · '
            rows.extend([(prefix + 'Hoch seit erster Aktivität', max(prices)),
                         (prefix + 'Tief seit erster Aktivität', min(prices)),
                         ('Kurs-Drawdown % (Splits/Ausschüttungen nicht bereinigt)', drawdown * 100),
                         ('Kursabdeckung', 'Noch fehlende Zeiträume' if history_plan(repo, [first]) else 'Angefragte Zeiträume gespeichert')])
    amounts = {}
    for tx in transactions:
        if tx['kind'] == 'DIVIDEND':
            amounts[tx['currency']] = amounts.get(tx['currency'], Decimal(0)) + Decimal(tx['amount'])
    rows.extend(('Gebuchte Ausschüttungsbeträge · ' + currency, amount) for currency, amount in amounts.items())
    if hasattr(type(repo), 'actions'):
        from .analysis_v09 import realized_profit
        realized = [r for r in realized_profit(repo, '0001-01-01', date.today().isoformat()) if r['security'] in keys]
        for r in realized:
            rows.append((f"Realisiert · {r['date']} · {r['account']} · {r['currency']} · {r['status']}", r['realized']))
    return rows
