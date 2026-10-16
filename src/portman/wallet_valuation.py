import json
from decimal import Decimal


def daily_values_for_snapshots(db, snapshot_ids):
    """Load wallet values only for relevant snapshots, within SQLite limits."""
    # Synthetic positions derived purely from transactions have no backing
    # snapshot and therefore cannot have a frozen snapshot valuation.
    ids = sorted({int(value) for value in snapshot_ids if value is not None})
    values = {}
    for start in range(0, len(ids), 900):
        chunk = ids[start:start + 900]
        placeholders = ','.join('?' for _ in chunk)
        for row in db.execute(
                f'SELECT * FROM wallet_daily_values WHERE snapshot_id IN ({placeholders})', chunk):
            values[(row['snapshot_id'], row['security_key'])] = dict(row)
    return values


def save_daily_values(db, result):
    if result.get('status') != 'ok' or result.get('currency') != 'EUR':
        return 0
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='snapshots'").fetchone():
        return 0
    prices = {p['date']: p['close'] for p in result.get('prices', [])}
    key = result['security_key']
    candidates = []
    for snapshot in db.execute('''SELECT s.* FROM snapshots s JOIN imports i ON i.id=s.import_id
            WHERE i.active=1''').fetchall():
        day = snapshot['as_of']
        # Today's daily candle can still change; freeze only completed UTC days.
        if not day or day >= result['attempted_at'][:10] or day not in prices:
            continue
        price = Decimal(str(prices[day]))
        if not price.is_finite() or price <= 0:
            continue
        if key not in snapshot['payload'] or 'Krypto' not in snapshot['payload']:
            continue
        for position in json.loads(snapshot['payload'])['positions']:
            if position['asset_type'] != 'Krypto' or position['key'] != key:
                continue
            quantity = Decimal(position['quantity'])
            if not quantity.is_finite():
                continue
            value = (quantity * price).quantize(Decimal('.01'))
            candidates.append((snapshot['id'], position['key'], day, str(price),
                str(quantity), str(value), 'EUR', result.get('source_url') or result['provider'], result['attempted_at']))
    if not candidates:
        return 0
    with db:
        cursor = db.executemany('''INSERT OR IGNORE INTO wallet_daily_values
            (snapshot_id,security_key,day,price,quantity,value,currency,source,recorded_at)
            VALUES(?,?,?,?,?,?,?,?,?)''', candidates)
    return cursor.rowcount


def apply_daily_values(db, positions):
    values = daily_values_for_snapshots(db, (position['snapshot_id'] for position in positions))
    for position in positions:
        saved = values.get((position['snapshot_id'], position['key']))
        if saved and Decimal(position['quantity']) == Decimal(saved['quantity']):
            position.update(value=saved['value'], currency=saved['currency'], quote_date=saved['day'],
                valuation_source=saved['source'],
                valuation_note='Einmalig gespeicherter EUR-Tagesendwert · ' + saved['source'])
    return positions
