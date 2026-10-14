"""Additional daily-price adapters; all errors are credential-free."""
from datetime import date, datetime, timedelta, timezone
from urllib.parse import quote
from .online_providers import api_url, ProviderError


def fetch_rows(provider, position, mapping):
    symbol = mapping['symbol']
    start = position.get('history_start') or (date.today() - timedelta(days=364)).isoformat()
    end = position.get('history_end') or (date.today() - timedelta(days=1)).isoformat()
    get, key = provider.transport, provider.key
    if provider.id == 'leeway':
        payload = get(api_url('https://api.leeway.tech/api/v1/public/historicalquotes/' + quote(symbol, safe=''),
            apitoken=key, filter='close', **{'from': start, 'to': end}), {})
        if not isinstance(payload, list):
            raise ProviderError('Leeway: Symbol, Token und Freischaltung prüfen.')
        return [{'date': r['time'], 'close': r['value']} for r in payload], None
    if provider.id == 'quandl':
        if len(symbol.split('/')) != 2:
            raise ProviderError('Dataset als DATENBANK/DATASET eingeben.')
        payload = get(api_url('https://data.nasdaq.com/api/v3/datasets/' + quote(symbol, safe='/') + '.json',
            api_key=key, start_date=start, end_date=end, order='asc'), {})
        dataset = payload.get('dataset', {})
        columns = [str(c).lower() for c in dataset.get('column_names', [])]
        if 'date' not in columns or 'close' not in columns:
            raise ProviderError('Dataset enthält keine Date-/Close-Spalten. Passendes Kurs-Dataset auswählen.')
        return [{'date': r[columns.index('date')], 'close': r[columns.index('close')]} for r in dataset['data']], None
    if provider.id == 'sifting':
        if mapping['currency'].upper() != 'USD':
            raise ProviderError('Sifting-US-Aktien benötigen die Kurswährung USD.')
        rows, seen, cursor = [], set(), None
        for _ in range(100):
            payload = get(api_url('https://api.sifting.io/v1/hist/stocks/' + quote(symbol, safe='') + '/bars',
                start=start, end=end, interval='1d', limit=2000, cursor=cursor),
                {'X-API-Key': key, 'Accept-Encoding': 'gzip'})
            meta = payload.get('meta', {})
            if payload.get('error') or str(meta.get('symbol', '')).casefold() != symbol.casefold():
                raise ProviderError('Sifting: Antwortsymbol, API-Schlüssel und Freischaltung prüfen.')
            rows.extend({'date': datetime.fromtimestamp(r['t'] / 1000, timezone.utc).date().isoformat(),
                         'close': r['c']} for r in payload['data'])
            cursor = meta.get('next_cursor')
            if not cursor: return rows, 'USD'
            if cursor in seen: break
            seen.add(cursor)
        raise ProviderError('Sifting: Historie nicht vollständig geliefert; Seitengrenze erreicht.')
    if date.fromisoformat(start) < date.today() - timedelta(days=365):
        raise ProviderError('CoinGecko Demo liefert nur die letzten 365 Tage. Für den ersten Bestand eine andere Kursquelle wählen.')
    stamp = lambda day: int(datetime.combine(day, datetime.min.time(), timezone.utc).timestamp())
    payload = get(api_url('https://api.coingecko.com/api/v3/coins/' + quote(symbol, safe='') + '/market_chart/range',
        vs_currency=mapping['currency'].lower(), **{'from': stamp(date.fromisoformat(start)),
        'to': stamp(date.fromisoformat(end) + timedelta(days=1)) - 1}), {'x-cg-demo-api-key': key})
    # Keep the last available observation of each UTC day, including short hourly ranges.
    daily = {}
    for timestamp, price in sorted(payload.get('prices', [])):
        day = datetime.fromtimestamp(timestamp / 1000, timezone.utc).date().isoformat()
        if start <= day <= end: daily[day] = price
    return [{'date': day, 'close': price} for day, price in daily.items()], mapping['currency']
