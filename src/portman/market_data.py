"""Public market observations. Never rewrites imported holdings or cash balances."""
import json
import math
import re
import statistics
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta
from .market_values import finite, utcnow


def calculate_metrics(prices, annual_days=252):
    values = [p['adjusted_close'] for p in prices if p.get('adjusted_close') is not None and p['adjusted_close'] > 0]
    result = {}
    if not values: return result
    for label, days in [('return_1m_pct', 30 if annual_days == 365 else 21), ('return_3m_pct', 90 if annual_days == 365 else 63), ('return_1y_pct', annual_days)]:
        result[label] = (values[-1] / values[-1 - days] - 1) * 100 if len(values) > days else None
    window = values[-(annual_days + 1):]
    returns = [math.log(b / a) for a, b in zip(window, window[1:])]
    result['volatility_pct'] = statistics.stdev(returns) * math.sqrt(annual_days) * 100 if len(returns) >= 20 else None
    peak, worst = window[0], 0
    for value in window:
        peak = max(peak, value); worst = min(worst, (value / peak - 1) * 100)
    result['max_drawdown_pct'] = worst if len(window) >= 20 else None
    closes = [p['close'] for p in prices if p.get('close') is not None]
    for size in (50, 200):
        result[f'ma_{size}'] = statistics.mean(closes[-size:]) if len(closes) >= size else None
    result['observations'] = len(window)
    return result


class YahooMarketProvider:
    name = 'Yahoo Finance (öffentliche Schnittstelle)'

    def __init__(self, transport=None):
        self.transport = transport or self._request

    @staticmethod
    def _request(url):
        request = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json'})
        with urllib.request.urlopen(request, timeout=12) as response:
            return json.load(response)

    def fetch(self, position, mapping=None):
        key = position['key']
        result = {'security_key': key, 'attempted_at': utcnow(), 'provider': self.name}
        try:
            selected = dict(mapping or {})
            candidates = []
            if not selected.get('symbol'):
                isin = position.get('isin', '')
                if not re.fullmatch(r'[A-Z]{2}[A-Z0-9]{9}\d', isin):
                    return {**result, 'status': 'mapping_needed', 'message': 'Keine ISIN vorhanden. Börsensymbol manuell zuordnen.'}
                url = 'https://query1.finance.yahoo.com/v1/finance/search?' + urllib.parse.urlencode({'q': isin, 'quotesCount': 8, 'newsCount': 0})
                search = self.transport(url)
                candidates = [q for q in search.get('quotes', []) if q.get('symbol') and q.get('isYahooFinance')
                              and q.get('quoteType') in {'EQUITY', 'ETF', 'MUTUALFUND', 'CRYPTOCURRENCY'}]
                choices = candidates
                if len(choices) > 1:
                    xetra = [q for q in choices if q.get('exchange') == 'GER']
                    etfs = [q for q in choices if q.get('quoteType') == 'ETF']
                    if len(xetra) == 1: choices = xetra
                    elif len(etfs) == 1: choices = etfs
                if len(choices) != 1:
                    return {**result, 'status': 'mapping_needed', 'message': 'Kein eindeutiger ISIN-Treffer. Börsensymbol prüfen und zuordnen.', 'candidates': candidates}
                selected = {'symbol': choices[0]['symbol'], 'method': 'ISIN-Suche · Xetra/ETF bevorzugt' if len(candidates) > 1 else 'ISIN-Suche (automatisch)'}
                candidates = choices
            symbol = selected['symbol']
            history_range = '5y' if position.get('asset_type') == 'Krypto' else '2y'
            params = {'range': history_range, 'interval': '1d', 'events': 'div,splits'}
            if position.get('_history_request'):
                first = datetime.fromisoformat(position['history_start']).replace(tzinfo=timezone.utc)
                last = datetime.fromisoformat(position['history_end']).replace(tzinfo=timezone.utc) + timedelta(days=1)
                params = {'period1': int(first.timestamp()), 'period2': int(last.timestamp()), 'interval': '1d', 'events': 'div,splits'}
            url = 'https://query1.finance.yahoo.com/v8/finance/chart/' + urllib.parse.quote(symbol, safe='') + '?' + urllib.parse.urlencode(params)
            payload = self.transport(url)
            chart = payload.get('chart', {})
            if chart.get('error') or not chart.get('result'):
                raise ValueError('Keine Kurshistorie für dieses Börsensymbol verfügbar.')
            chart = chart['result'][0]; meta = chart.get('meta', {})
            if str(meta.get('symbol', '')).casefold() != symbol.casefold():
                raise ValueError('Antwortsymbol stimmt nicht mit der Zuordnung überein.')
            indicators = chart.get('indicators', {})
            quote = (indicators.get('quote') or [{}])[0]
            adjusted = (indicators.get('adjclose') or [{}])[0].get('adjclose', [])
            prices = []
            for i, stamp in enumerate(chart.get('timestamp') or []):
                closes = quote.get('close') or []
                close = finite(closes[i]) if i < len(closes) else None
                if close is None or close <= 0: continue
                adjusted_close = finite(adjusted[i]) if i < len(adjusted) else None
                prices.append({'date': datetime.fromtimestamp(stamp, timezone.utc).date().isoformat(),
                               'close': close, 'adjusted_close': adjusted_close if adjusted_close and adjusted_close > 0 else close})
            prices.sort(key=lambda p: p['date'])
            if position.get('_history_request'):
                if not meta.get('currency'): raise ValueError('Kurswährung fehlt.')
                return {**result, 'status': 'ok', 'message': f'{len(prices)} Tageskurse geladen.',
                        'symbol': symbol, 'currency': meta['currency'], 'prices': prices}
            adjusted_complete = len(adjusted) == len(chart.get('timestamp') or []) and all(
                finite(v) is not None and finite(v) > 0 for v in adjusted)
            if not adjusted_complete:
                for p in prices: p['adjusted_close'] = p['close']
            price = finite(meta.get('regularMarketPrice'))
            if price is None or price <= 0 or not prices:
                raise ValueError('Kurs oder gültige Kurshistorie fehlt.')
            currency = meta.get('currency')
            stamp = finite(meta.get('regularMarketTime'))
            if not currency or not stamp:
                raise ValueError('Kurswährung oder Börsenzeit fehlt.')
            quote_time = datetime.fromtimestamp(stamp, timezone.utc).isoformat(timespec='seconds')
            previous = finite(meta.get('previousClose'))
            if previous is None and len(prices) >= 2: previous = prices[-2]['close']
            annual_days = 365 if meta.get('instrumentType') == 'CRYPTOCURRENCY' else 252
            metrics = calculate_metrics(prices, annual_days)
            metrics.update(price=price, day_change_pct=(price / previous - 1) * 100 if previous else None,
                           high_52w=finite(meta.get('fiftyTwoWeekHigh')), low_52w=finite(meta.get('fiftyTwoWeekLow')),
                           volume=finite(meta.get('regularMarketVolume')), market_cap=finite(meta.get('marketCap')))
            if candidates:
                metrics['sector'] = candidates[0].get('sector')
            return {**result, 'status': 'ok', 'message': 'Kurse und berechenbare Kennzahlen gespeichert.',
                    'symbol': symbol, 'mapping_method': selected.get('method', 'Manuell bestätigt'),
                    'name': meta.get('longName') or meta.get('shortName') or position['name'],
                    'currency': currency, 'exchange': meta.get('fullExchangeName') or meta.get('exchangeName', ''),
                    'quote_time': quote_time, 'metrics': metrics, 'prices': prices,
                    'source_url': 'https://finance.yahoo.com/quote/' + urllib.parse.quote(symbol, safe='') + '/',
                    'calculation': f'Volatilität: logarithmische Tagesänderungen, sqrt({annual_days}); '
                                   f'Drawdown: bis zu {annual_days + 1} Beobachtungen; '
                                   + ('bereinigte Schlusskurse.' if adjusted_complete else 'unbereinigte Schlusskurse; Ausschüttungen/Splits können die Kennzahlen beeinflussen.')}
        except Exception as exc:
            # Do not persist exception URLs: future providers may put credentials there.
            code = getattr(exc, 'code', None)
            detail = str(exc) if isinstance(exc, ValueError) else f'{type(exc).__name__}' + (f' (HTTP {code})' if code else '')
            return {**result, 'status': 'error', 'message': f'Abruf fehlgeschlagen: {detail}'}


class MarketDataStore:
    def __init__(self, db):
        self.db = db
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS market_data(security_key TEXT PRIMARY KEY, payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS wallet_daily_values(
          snapshot_id INTEGER NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
          security_key TEXT NOT NULL, day TEXT NOT NULL, price TEXT NOT NULL,
          quantity TEXT NOT NULL, value TEXT NOT NULL, currency TEXT NOT NULL,
          source TEXT NOT NULL, recorded_at TEXT NOT NULL,
          PRIMARY KEY(snapshot_id,security_key));
        CREATE TABLE IF NOT EXISTS market_attempts(id INTEGER PRIMARY KEY, security_key TEXT NOT NULL,
          attempted_at TEXT NOT NULL, status TEXT NOT NULL, message TEXT NOT NULL, details TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS market_symbols(security_key TEXT PRIMARY KEY, symbol TEXT NOT NULL, method TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS market_manual(security_key TEXT PRIMARY KEY, payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS fx_rates(day TEXT PRIMARY KEY, payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS market_feeds(security_key TEXT PRIMARY KEY, provider TEXT NOT NULL,
          symbol TEXT NOT NULL, currency TEXT NOT NULL, exchange TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS market_observations(id INTEGER PRIMARY KEY, security_key TEXT NOT NULL,
          provider TEXT NOT NULL, attempted_at TEXT NOT NULL, payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS dividend_observations(id INTEGER PRIMARY KEY, security_key TEXT NOT NULL,
          attempted_at TEXT NOT NULL, status TEXT NOT NULL, payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS online_usage(id INTEGER PRIMARY KEY, provider TEXT NOT NULL, day TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS online_usage_day ON online_usage(provider,day);
        CREATE INDEX IF NOT EXISTS market_observation_key ON market_observations(security_key,id);
        CREATE INDEX IF NOT EXISTS dividend_observation_key ON dividend_observations(security_key,id);
        INSERT INTO market_observations(security_key,provider,attempted_at,payload)
          SELECT security_key,'yahoo','',payload FROM market_data m
          WHERE NOT EXISTS(SELECT 1 FROM market_observations o WHERE o.security_key=m.security_key);
        ''')
        from .online_credentials import CredentialStore
        self.credentials = CredentialStore(db)
        from .price_history import initialize_history, retain_market_prices
        initialize_history(db)
        with db:
            for row in db.execute('SELECT security_key,payload FROM market_data WHERE security_key NOT IN (SELECT security_key FROM price_history_requests)').fetchall():
                retain_market_prices(self, json.loads(row['payload']))

    def save_fx(self, observation):
        from decimal import Decimal
        datetime.strptime(observation['date'], '%Y-%m-%d')
        if not observation['rates'] or any(not Decimal(v).is_finite() or Decimal(v) <= 0 for v in observation['rates'].values()):
            raise ValueError('Ungültige Wechselkurse')
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO fx_rates VALUES(?,?)',
                            (observation['date'], json.dumps(observation)))

    def fx(self):
        row = self.db.execute('SELECT payload FROM fx_rates ORDER BY day DESC LIMIT 1').fetchone()
        return json.loads(row[0]) if row else None

    def records(self):
        data = {r['security_key']: {'data': json.loads(r['payload'])} for r in self.db.execute('SELECT * FROM market_data')}
        for row in self.db.execute('SELECT * FROM market_attempts WHERE id IN (SELECT MAX(id) FROM market_attempts GROUP BY security_key)'):
            data.setdefault(row['security_key'], {})['attempt'] = dict(row)
        for row in self.db.execute('SELECT * FROM market_manual'):
            data.setdefault(row['security_key'], {})['manual'] = json.loads(row['payload'])
        return data

    def mappings(self):
        mappings = {r['security_key']: {**dict(r), 'provider': 'yahoo'} for r in self.db.execute('SELECT * FROM market_symbols')}
        for r in self.db.execute('SELECT * FROM market_feeds'):
            mappings[r['security_key']] = {**dict(r), 'method': 'Manuell bestätigt'}
        return mappings

    def set_feed(self, key, provider, symbol, currency='', exchange=''):
        from .online_providers import PROVIDERS, currency_code
        if provider not in PROVIDERS:
            raise ValueError('Unbekannter Kursanbieter.')
        symbol = symbol.strip()
        currency = currency_code(currency)
        exchange = exchange.strip()
        if (symbol or provider != 'yahoo') and not re.fullmatch(r'[A-Za-z0-9.^=_/:-]{1,60}', symbol):
            raise ValueError('Bitte ein gültiges Anbietersymbol eingeben.')
        if (currency or provider != 'yahoo') and not re.fullmatch(r'[A-Z]{3}', currency):
            raise ValueError('Kurswährung bitte als dreistelligen Code angeben, z. B. EUR, USD oder GBX.')
        if provider == 'twelvedata' and exchange and not re.fullmatch(r'[A-Za-z0-9]{4}', exchange):
            raise ValueError('Handelsplatz bitte als vierstelligen MIC eingeben, z. B. XNAS oder XETR.')
        if provider == 'kraken':
            # Kraken aliases use e.g. XBT/EUR, XBTEUR, XXBTZEUR.
            tail = symbol.replace('/', '').upper()
            if not tail.endswith(currency):
                raise ValueError('Kraken-Handelspaar muss zur Kurswährung passen, z. B. XBTEUR / EUR.')
        old = self.mappings().get(key, {})
        identity = (provider, symbol, currency, exchange)
        previous = (old.get('provider', 'yahoo'), old.get('symbol', ''), old.get('currency', ''), old.get('exchange', ''))
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO market_feeds VALUES(?,?,?,?,?)', (key, *identity))
            if identity != previous:
                # Archived observations remain available; never label old data with a new feed.
                self.db.execute('DELETE FROM market_data WHERE security_key=?', (key,))
                self.db.execute('INSERT INTO market_attempts(security_key,attempted_at,status,message,details) VALUES(?,?,?,?,?)',
                                (key, utcnow(), 'mapping_needed', 'Kursquelle geändert. Bitte neu abrufen.', '[]'))
        callback = getattr(self, 'asset_listing_callback', None)
        if callback and symbol:
            callback(key, dict(provider=provider, symbol=symbol, currency=currency, exchange=exchange))

    def daily_usage(self):
        return {r['provider']: r['n'] for r in self.db.execute(
            'SELECT provider,COUNT(*) n FROM online_usage WHERE day=? GROUP BY provider', (utcnow()[:10],))}

    def record_usage(self, provider):
        with self.db:
            self.db.execute('INSERT INTO online_usage(provider,day) VALUES(?,?)', (provider, utcnow()[:10]))

    def observation_history(self, key, limit=200):
        return [json.loads(r[0]) for r in self.db.execute(
            'SELECT payload FROM market_observations WHERE security_key=? ORDER BY id DESC LIMIT ?', (key, limit))]

    def save_dividends(self, result):
        with self.db:
            self.db.execute('INSERT INTO dividend_observations(security_key,attempted_at,status,payload) VALUES(?,?,?,?)',
                            (result['security_key'], result['attempted_at'], result['status'], json.dumps(result, ensure_ascii=False, allow_nan=False)))

    def dividends(self):
        data = {}
        for r in self.db.execute('''SELECT * FROM dividend_observations WHERE id IN
            (SELECT MAX(id) FROM dividend_observations GROUP BY security_key)
            OR id IN (SELECT MAX(id) FROM dividend_observations WHERE status='ok' GROUP BY security_key)
            ORDER BY id'''):
            payload = json.loads(r['payload'])
            item = data.setdefault(r['security_key'], {})
            item['attempt'] = payload
            if r['status'] == 'ok': item['data'] = payload
        return data

    def set_symbol(self, key, symbol):
        symbol = symbol.strip()
        if not re.fullmatch(r'[A-Za-z0-9.^=_-]{1,40}', symbol):
            raise ValueError('Bitte ein gültiges Börsensymbol eingeben, z. B. AAPL oder SAP.DE.')
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO market_symbols VALUES(?,?,?)', (key, symbol, 'Manuell bestätigt'))
            self.db.execute('DELETE FROM market_feeds WHERE security_key=?', (key,))
            # Quotes for the old listing must not be displayed under the new mapping.
            self.db.execute('DELETE FROM market_data WHERE security_key=?', (key,))

    def save_result(self, result, *, retain_history=True):
        key = result['security_key']
        with self.db:
            self.db.execute('INSERT INTO market_attempts(security_key,attempted_at,status,message,details) VALUES(?,?,?,?,?)',
                            (key, result['attempted_at'], result['status'], result['message'],
                             json.dumps(result.get('candidates', []), ensure_ascii=False)))
            if result['status'] == 'ok':
                from .wallet_valuation import save_daily_values
                save_daily_values(self.db, result)
                self.db.execute('INSERT INTO market_observations(security_key,provider,attempted_at,payload) VALUES(?,?,?,?)',
                                (key, result.get('provider_id', 'yahoo'), result['attempted_at'], json.dumps(result, ensure_ascii=False, allow_nan=False)))
                self.db.execute('INSERT OR REPLACE INTO market_data VALUES(?,?)', (key, json.dumps(result, ensure_ascii=False, allow_nan=False)))
                if result.get('provider_id', 'yahoo') == 'yahoo':
                    self.db.execute('INSERT OR IGNORE INTO market_symbols VALUES(?,?,?)',
                                    (key, result['symbol'], result.get('mapping_method', 'ISIN-Suche (automatisch)')))
                    self.db.execute("UPDATE market_feeds SET symbol=? WHERE security_key=? AND provider='yahoo' AND symbol=''",
                                    (result['symbol'], key))
                from .price_history import retain_market_prices
                if retain_history:
                    retain_market_prices(self, result)

    def save_manual(self, key, fields, source, as_of):
        source = source.strip()
        if not source: raise ValueError('Bitte die Quelle der Kennzahlen angeben.')
        datetime.strptime(as_of, '%Y-%m-%d')
        cleaned = {}
        for name, value in fields.items():
            if value is None or str(value).strip() == '': continue
            if name in {'sector', 'country', 'currency'}: cleaned[name] = str(value).strip(); continue
            number = finite(str(value).replace(',', '.'))
            if number is None: raise ValueError(f'{name}: Bitte eine endliche Zahl eingeben.')
            if name in {'ter_pct', 'dividend_yield_pct', 'market_cap'} and number < 0:
                raise ValueError(f'{name}: Der Wert darf nicht negativ sein.')
            cleaned[name] = number
        if 'price' in cleaned and (cleaned['price'] <= 0 or not cleaned.get('currency')):
            raise ValueError('Für einen manuellen Kurs sind ein positiver Betrag und eine Währung erforderlich.')
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO market_manual VALUES(?,?)',
                            (key, json.dumps({'fields': cleaned, 'source': source, 'as_of': as_of, 'updated_at': utcnow()}, ensure_ascii=False)))
