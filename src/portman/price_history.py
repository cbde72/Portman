"""Persistent daily prices and requested intervals, isolated by market feed."""
from datetime import date, timedelta
import json
from portfolio_v5.models import Decimal
from .chart_cache import cached_series
from .market_values import finite
from .price_history_store import (store_history_result, history_intervals, history_currency, history_rows)
from .price_history_store import initialize_history  # noqa: F401 - re-exported for market_data


def retain_market_prices(market, result):
    key = result['security_key']
    mapping = market.mappings().get(key, {})
    if mapping.get('symbol') != result.get('symbol') or mapping.get('provider', 'yahoo') != result.get('provider_id', 'yahoo'):
        return
    prices = {p['date']: finite(p['close']) for p in result.get('prices', [])
              if p['date'] < date.today().isoformat() and finite(p.get('close')) and finite(p['close']) > 0}
    if not prices or not result.get('currency'): return
    observation = {**result, 'status': 'ok', 'message': 'Gespeicherte Marktdaten übernommen.'}
    store_history_result(market.db, key, mapping, prices, observation, min(prices), max(prices))


def historical_positions(repo, account=None):
    def build():
        found = {}
        aliases = repo.store.aliases()
        overrides = {(r['account'], r['security_key']): r['day'] for r in repo.db.execute('SELECT * FROM first_activity')}
        for snapshot in repo.snapshots(account):
            for p in json.loads(snapshot['payload'])['positions']:
                if p.get('quantity') is not None and Decimal(p['quantity']) <= 0:
                    continue
                if p.get('quantity') is None and (p.get('value') is None or Decimal(p['value']) <= 0):
                    continue
                key = aliases.get(p['key'], p['key'])
                day = overrides.get((snapshot['account'], key), snapshot['effective_date'])
                if key not in found or day < found[key]['history_start']:
                    found[key] = {**p, 'key': key, 'history_start': day}
        # Purchases can precede the first imported statement, or be the only
        # evidence of a holding. Manual first-activity corrections take priority.
        metadata = repo.metadata()
        identifiers = {}
        for key, p in {**metadata, **found}.items():
            for identifier in (key, p.get('isin'), 'ISIN:' + p['isin'] if p.get('isin') else '',
                               'WKN:' + p['wkn'] if p.get('wkn') else ''):
                if identifier: identifiers.setdefault(identifier, set()).add(key)
        for tx in repo.transactions(account=account):
            if tx['kind'] != 'BUY' or not tx.get('security') or not tx.get('quantity'):
                continue
            quantity = Decimal(tx['quantity'])
            if not quantity.is_finite() or quantity <= 0: continue
            identifier = aliases.get(tx['security'], tx['security'])
            matches = identifiers.get(identifier, {identifier})
            if len(matches) != 1: continue
            key = next(iter(matches))
            day = overrides.get((tx['account'], key), tx['date'])
            if key not in found or day < found[key]['history_start']:
                p = found.get(key, metadata.get(key, {}))
                found[key] = {**p, 'key': key, 'name': p.get('name') or p.get('canonical_name') or key,
                              'history_start': day, 'currency': p.get('currency', tx['currency'])}
        return sorted(found.values(), key=lambda p: p['name'].casefold())
    return cached_series(repo, ('historical_positions', account), build)


def missing_ranges(start, end, intervals):
    cursor = date.fromisoformat(start)
    last = date.fromisoformat(end)
    gaps = []
    for left, right in sorted(intervals):
        left, right = date.fromisoformat(left), date.fromisoformat(right)
        if right < cursor: continue
        if left > last: break
        if left > cursor: gaps.append((cursor.isoformat(), min(last, left - timedelta(days=1)).isoformat()))
        cursor = max(cursor, right + timedelta(days=1))
        if cursor > last: break
    if cursor <= last: gaps.append((cursor.isoformat(), last.isoformat()))
    return gaps


def history_plan(repo, positions, end=None, force=False):
    end = end or (date.today() - timedelta(days=1)).isoformat()
    mappings = repo.market.mappings()
    tasks = []
    for p in positions:
        start = p['history_start']
        if start > end: continue
        mapping = mappings.get(p['key'], {})
        intervals = history_intervals(repo.db, p['key'], mapping)
        for first, last in ([(start, end)] if force else missing_ranges(start, end, intervals)):
            while first <= last:
                chunk_end = min(last, (date.fromisoformat(first) + timedelta(days=3649)).isoformat()) if mapping.get('provider') == 'twelvedata' else last
                tasks.append({**p, 'history_start': first, 'history_end': chunk_end, '_history_request': True})
                first = (date.fromisoformat(chunk_end) + timedelta(days=1)).isoformat()
    return tasks


def save_history(repo, result, mapping):
    key = result['security_key']
    mapping = dict(mapping)
    if result.get('status') == 'ok' and result.get('symbol') and not mapping.get('symbol'):
        mapping['symbol'] = result['symbol']
        repo.market.set_feed(key, mapping.get('provider', 'yahoo'), result['symbol'], mapping.get('currency', ''), mapping.get('exchange', ''))
    start, end = result['history_start'], result['history_end']
    date.fromisoformat(start); date.fromisoformat(end)
    prices = {}
    if result['status'] == 'ok':
        if not result.get('currency'):
            raise ValueError('Kurswährung fehlt.')
        previous_currency = history_currency(repo.db, key, mapping)
        if previous_currency and previous_currency != result['currency']:
            raise ValueError('Kurswährung hat sich geändert. Bitte die Kursquelle neu zuordnen.')
        for p in result.get('prices', []):
            day = date.fromisoformat(p['date']).isoformat()
            close = finite(p['close'])
            if start <= day <= end and close is not None and close > 0:
                prices[day] = close
        if not prices:
            if (date.fromisoformat(end) - date.fromisoformat(start)).days > 7:
                result = {**result, 'status': 'error', 'message': 'Keine Kurse im angefragten Zeitraum. Historie bleibt offen; Kursquelle und Tarif prüfen.'}
            else:
                result = {**result, 'message': 'Keine Kurse im angefragten Zeitraum geliefert; Zeitraum geprüft.'}
        elif min(prices) > (date.fromisoformat(start) + timedelta(days=7)).isoformat():
            result = {**result, 'message': 'Historie unvollständig: beginnt erst am ' + min(prices) + '; früher keine Daten geliefert.'}
            start = min(prices)
        if prices and max(prices) < (date.fromisoformat(end) - timedelta(days=7)).isoformat():
            result = {**result, 'message': 'Historie unvollständig: endet bereits am ' + max(prices) + '.'}
            end = max(prices)
    with repo.db:
        store_history_result(repo.db, key, mapping, prices, result, start, end)
    return result


def stored_history(repo, key, start, end='9999-12-31', mapping=None):
    mapping = repo.market.mappings().get(key, {}) if mapping is None else mapping
    rows = history_rows(repo.db, key, mapping, start, end)
    return {'symbol': rows[0]['symbol'] if rows else mapping.get('symbol', ''),
            'currency': rows[0]['currency'] if rows else '',
            'provider': rows[0]['provider'] if rows else mapping.get('provider', 'yahoo'),
            'prices': [{'date': r['day'], 'close': r['close']} for r in rows]}


def save_first_activity(repo, account, key, value):
    if not account:
        raise ValueError('Bitte zuerst ein einzelnes Depot auswählen.')
    value = value.strip()
    if value:
        value = date.fromisoformat(value).isoformat()
        if value > date.today().isoformat():
            raise ValueError('Die erste Aktivität darf nicht in der Zukunft liegen.')
    with repo.db:
        if value:
            repo.db.execute('INSERT OR REPLACE INTO first_activity VALUES(?,?,?)', (account, key, value))
        else:
            repo.db.execute('DELETE FROM first_activity WHERE account=? AND security_key=?', (account, key))
