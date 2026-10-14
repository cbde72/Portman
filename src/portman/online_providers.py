"""Read-only provider adapters. Credentials and raw error bodies never enter results."""
import json
import gzip
import io
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from .market_data import YahooMarketProvider, calculate_metrics, finite, utcnow


PROVIDERS = {
    'yahoo': {'name': 'Yahoo Finance', 'key': False, 'interval': .5, 'daily': 0,
              'example': 'SAP.DE / AAPL', 'url': 'https://finance.yahoo.com/',
              'hint': 'Ohne API-Schlüssel. Öffentliche Schnittstelle ohne Verfügbarkeitsgarantie. ISIN-Suche möglich.'},
    'alphavantage': {'name': 'Alpha Vantage', 'key': True, 'interval': 13, 'daily': 25,
                     'example': 'IBM / SAP.DEX', 'url': 'https://www.alphavantage.co/support/#api-key',
                     'hint': 'Kostenloses Kontingent: 25 Abrufe/Tag. Tageskurse, letzte 100 Beobachtungen; keine Echtzeitkurse.'},
    'eodhd': {'name': 'EODHD', 'key': True, 'interval': 1, 'daily': 20,
              'example': 'AAPL.US / SAP.XETRA', 'url': 'https://eodhd.com/register',
              'hint': 'Kostenloses Kontingent: 20 Abrufe/Tag, bis zu ein Jahr Tageskurse. Symbol mit Börsensuffix verwenden.'},
    'finnhub': {'name': 'Finnhub', 'key': True, 'interval': 1.1, 'daily': 0,
                'example': 'AAPL', 'url': 'https://finnhub.io/register',
                'hint': 'Aktueller Kurs, insbesondere US-Aktien. Abdeckung abhängig vom Tarif. Keine kostenpflichtige Historie angefordert.'},
    'twelvedata': {'name': 'Twelve Data', 'key': True, 'interval': 8, 'daily': 800,
                   'example': 'AAPL / BTC/USD', 'url': 'https://twelvedata.com/pricing',
                   'hint': 'Basic-Kontingent: 8 Credits/Minute, 800/Tag. Börsenabdeckung tarifabhängig. Handelsplatz optional als MIC, z. B. XNAS.'},
    'kraken': {'name': 'Kraken · Krypto', 'key': False, 'interval': 1.1, 'daily': 0,
               'example': 'XBTEUR / ETHUSD', 'url': 'https://docs.kraken.com/api-reference/market-data/get-ohlc-data',
               'hint': 'Kostenlos ohne Schlüssel. Nur Kryptowährungen; bis zu 720 Tageskerzen. Laufende Tageskerze wird ausgeschlossen.'},
}
PROVIDERS.update({
    'leeway': dict(name='PWP Leeway UG', key=True, interval=1, daily=50,
        example='SAP.XETRA', url='https://leeway.tech/data-api',
        hint='API-Token aus dem Leeway-Konto. Symbol mit Börsensuffix; Historie abhängig von der Freischaltung.'),
    'sifting': dict(name='SiftingIO', key=True, interval=1, daily=0,
        example='AAPL / BRK.B', url='https://sifting.io/docs/historical/stocks',
        hint='US-Aktien in USD. API-Schlüssel erforderlich. Aggregierte Referenzkurse; keine offiziellen Börsenkurse.'),
    'quandl': dict(name='Quandl · Nasdaq Data Link', key=True, interval=1, daily=0,
        example='WIKI/AAPL', url='https://data.nasdaq.com/',
        hint='Zeitreihen-Dataset als DATENBANK/DATASET mit Close-Spalte. Keine Datatables. Historische WIKI-Daten enden 2018.'),
    'coingecko': dict(name='CoinGecko · Demo', key=True, interval=2.1, daily=0,
        example='bitcoin / ethereum', url='https://www.coingecko.com/en/api',
        hint='Demo-API-Schlüssel und Coin-ID (nicht Ticker). Demo-Historie auf die letzten 365 Tage begrenzt.'),
})
DIVVY = {'name': 'DivvyDiary', 'url': 'https://divvydiary.com/en/settings',
         'hint': 'API-Schlüssel aus deinem DivvyDiary-Konto. Dividendenabruf benötigt die passende API-Berechtigung; ein kostenloses Webkonto garantiert diese nicht.'}


class ProviderError(ValueError):
    def __init__(self, message, stop=False):
        super().__init__(message)
        self.stop = stop


def request_json(url, headers=None):
    request = urllib.request.Request(url, headers={
        'User-Agent': 'PortMan/0.6', 'Accept': 'application/json', **(headers or {})})
    # Never forward an API key to a redirect target.
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, hdrs, newurl):
            return None
    opener = urllib.request.build_opener(NoRedirect())
    try:
        with opener.open(request, timeout=15) as response:
            raw = response.read(8 * 1024 * 1024 + 1)
            if len(raw) > 8 * 1024 * 1024:
                raise ProviderError('Antwort ist zu groß.')
            if response.headers.get('Content-Encoding') == 'gzip':
                raw = gzip.GzipFile(fileobj=io.BytesIO(raw)).read(8 * 1024 * 1024 + 1)
                if len(raw) > 8 * 1024 * 1024: raise ProviderError('Antwort ist zu groß.')
            return json.loads(raw)
    except urllib.error.HTTPError as exc:
        messages = {401: 'API-Schlüssel ungültig oder abgelaufen.',
                    403: 'Zugriff nicht freigeschaltet. API-Schlüssel und Tarif prüfen.',
                    404: 'Wertpapier / Symbol nicht gefunden.',
                    429: 'Abruflimit erreicht. Später erneut versuchen.'}
        raise ProviderError(messages.get(exc.code, f'Anbieter nicht erreichbar (HTTP {exc.code}).'),
                            exc.code in (401, 403, 429)) from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise ProviderError('Netzwerkfehler oder Zeitüberschreitung. Später erneut versuchen.') from None
    except (json.JSONDecodeError, UnicodeError):
        raise ProviderError('Anbieter lieferte keine gültigen JSON-Daten.') from None


def api_url(base, **params):
    return base + '?' + urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})


def currency_code(value):
    value = str(value or '').strip()
    return 'GBX' if value == 'GBp' else value.upper()


def checked_day(value):
    return date.fromisoformat(str(value)[:10]).isoformat()


def history_result(position, mapping, provider_id, rows, currency=None, exchange=None, adjusted=False):
    prices = {}
    for row in rows:
        day = checked_day(row['date'])
        close = finite(row.get('close'))
        if close is None or close <= 0 or day > date.today().isoformat():
            continue
        adj = finite(row.get('adjusted_close')) if adjusted else close
        prices[day] = {'date': day, 'close': close, 'adjusted_close': adj if adj and adj > 0 else close}
    prices = sorted(prices.values(), key=lambda p: p['date'])
    if not prices:
        raise ProviderError('Keine gültigen Kurse geliefert. Symbol und Freischaltung prüfen.')
    expected = currency_code(mapping.get('currency'))
    actual = currency_code(currency)
    if actual and expected and actual != expected:
        raise ProviderError('Kurswährung weicht von der Zuordnung ab. Währung prüfen.')
    currency = actual or expected
    if not re.fullmatch(r'[A-Z]{3}', currency):
        raise ProviderError('Kurswährung fehlt. Bitte in der Kursquelle festlegen.')
    metrics = calculate_metrics(prices, 365 if provider_id == 'kraken' else 252)
    metrics.update(price=prices[-1]['close'], day_change_pct=(prices[-1]['close'] / prices[-2]['close'] - 1) * 100 if len(prices) > 1 else None)
    return {'status': 'ok', 'message': f'{len(prices)} Tageskurse gespeichert.',
            'symbol': mapping['symbol'], 'mapping_method': 'Manuell bestätigt',
            'name': position['name'], 'currency': currency, 'exchange': exchange or mapping.get('exchange', ''),
            'quote_time': prices[-1]['date'], 'quote_precision': 'day',
            'prices': prices, 'metrics': metrics, 'source_url': PROVIDERS[provider_id]['url'],
            'calculation': 'Tageskurse; Kurszeit nur taggenau. ' +
                ('Bereinigte Schlusskurse für Rendite und Risiko.' if adjusted else
                 'Kennzahlen aus unbereinigten Schlusskursen; Splits/Ausschüttungen können sie beeinflussen.')}


class MarketProvider:
    def __init__(self, provider_id, api_key='', transport=None):
        self.id = provider_id
        self.key = api_key
        self.transport = transport or request_json

    def fetch(self, position, mapping=None):
        mapping = dict(mapping or {})
        info = PROVIDERS.get(self.id)
        base = {'security_key': position['key'], 'attempted_at': utcnow(),
                'provider_id': self.id, 'provider': info['name'] if info else self.id}
        if not info:
            return {**base, 'status': 'error', 'message': 'Unbekannter Kursanbieter.'}
        if self.id == 'yahoo':
            result = YahooMarketProvider().fetch(position, mapping) if self.transport == request_json else YahooMarketProvider(lambda url: self.transport(url, {})).fetch(position, mapping)
            if result['status'] == 'ok' and mapping.get('currency') and currency_code(result['currency']) != currency_code(mapping['currency']):
                return {**base, 'status': 'error', 'message': 'Kurswährung weicht von der Zuordnung ab.'}
            return {**result, 'provider_id': self.id}
        if info['key'] and not self.key:
            return {**base, 'status': 'error', 'message': 'API-Schlüssel fehlt. Unter „Online-Zugänge“ einrichten.', 'stop_provider': True}
        if not mapping.get('symbol') or not mapping.get('currency'):
            return {**base, 'status': 'mapping_needed', 'message': 'Anbietersymbol und Kurswährung unter „Kursquelle“ festlegen.'}
        symbol = mapping['symbol']
        try:
            if position.get('_history_request') and self.id == 'finnhub':
                raise ProviderError('Diese Quelle liefert hier nur aktuelle Kurse. Für Historie bitte eine andere Kursquelle wählen.')
            adjusted = False
            if self.id in ('leeway', 'sifting', 'quandl', 'coingecko'):
                from .additional_providers import fetch_rows
                rows, currency = fetch_rows(self, position, mapping)
                return {**base, **history_result(position, mapping, self.id, rows, currency)}
            if self.id == 'alphavantage':
                payload = self.transport(api_url('https://www.alphavantage.co/query', function='TIME_SERIES_DAILY',
                    symbol=symbol, outputsize='full' if position.get('_history_request') else 'compact', apikey=self.key), {})
                if payload.get('Note') or payload.get('Information'):
                    raise ProviderError('Anbieter meldet ein Limit oder eine fehlende Tarifberechtigung.', True)
                if payload.get('Error Message'):
                    raise ProviderError('Symbol nicht gefunden oder Abfrage nicht unterstützt.')
                if payload.get('Meta Data', {}).get('2. Symbol', '').casefold() != symbol.casefold():
                    raise ProviderError('Antwortsymbol stimmt nicht mit der Zuordnung überein.')
                rows = [{'date': d, 'close': v['4. close']} for d, v in payload.get('Time Series (Daily)', {}).items()]
            elif self.id == 'eodhd':
                payload = self.transport(api_url('https://eodhd.com/api/eod/' + urllib.parse.quote(symbol, safe=''),
                    api_token=self.key, fmt='json', period='d', order='a',
                    **{'from': position.get('history_start') if position.get('_history_request') else (date.today() - timedelta(days=364)).isoformat(),
                       'to': position.get('history_end') if position.get('_history_request') else None}), {})
                if not isinstance(payload, list):
                    raise ProviderError('EODHD meldet einen Fehler. Symbol, API-Schlüssel und Kontingent prüfen.')
                rows = payload
                adjusted = bool(rows) and all(finite(r.get('adjusted_close')) and finite(r.get('adjusted_close')) > 0 for r in rows)
            elif self.id == 'twelvedata':
                payload = self.transport(api_url('https://api.twelvedata.com/time_series', symbol=symbol,
                    interval='1day', outputsize=5000 if position.get('_history_request') else 365,
                    start_date=position.get('history_start') if position.get('_history_request') else None,
                    end_date=position.get('history_end') if position.get('_history_request') else None,
                    adjust='none', mic_code=mapping.get('exchange') or None,
                    apikey=self.key), {})
                if payload.get('status') == 'error':
                    code = str(payload.get('code'))
                    raise ProviderError('Twelve Data: Symbol, Tarifberechtigung oder Abruflimit prüfen.', code in ('429', '401', '403'))
                meta = payload.get('meta', {})
                if str(meta.get('symbol', '')).casefold() != symbol.casefold():
                    raise ProviderError('Antwortsymbol stimmt nicht mit der Zuordnung überein.')
                if mapping.get('exchange') and str(meta.get('mic_code', '')).upper() != mapping['exchange'].upper():
                    raise ProviderError('Antwort-Handelsplatz stimmt nicht mit dem gewählten MIC überein.')
                rows = [{'date': r['datetime'], 'close': r['close']} for r in payload.get('values', [])]
                return {**base, **history_result(position, mapping, self.id, rows, meta.get('currency'), meta.get('exchange'))}
            elif self.id == 'finnhub':
                payload = self.transport(api_url('https://finnhub.io/api/v1/quote', symbol=symbol), {'X-Finnhub-Token': self.key})
                if payload.get('error'):
                    raise ProviderError('Finnhub meldet einen Zugriffsfehler. Schlüssel, Tarif und Abruflimit prüfen.', True)
                price, stamp = finite(payload.get('c')), finite(payload.get('t'))
                if not price or price <= 0 or not stamp or stamp <= 0 or stamp > datetime.now(timezone.utc).timestamp() + 300:
                    raise ProviderError('Kein gültiger Finnhub-Kurs. Symbol und Tarifberechtigung prüfen.')
                previous = finite(payload.get('pc'))
                return {**base, 'status': 'ok', 'message': 'Aktueller Kurs gespeichert; keine Kurshistorie angefordert.',
                        'symbol': symbol, 'mapping_method': 'Manuell bestätigt', 'name': position['name'],
                        'currency': currency_code(mapping['currency']), 'exchange': mapping.get('exchange', ''),
                        'quote_time': datetime.fromtimestamp(stamp, timezone.utc).isoformat(timespec='seconds'),
                        'metrics': {'price': price, 'day_change_pct': (price / previous - 1) * 100 if previous and previous > 0 else None},
                        'prices': [], 'source_url': 'https://finnhub.io/',
                        'calculation': 'Einzelkurs. Ohne Historie werden keine Rendite- oder Risikokennzahlen berechnet.'}
            elif self.id == 'kraken':
                payload = self.transport(api_url('https://api.kraken.com/0/public/OHLC', pair=symbol, interval=1440), {})
                if payload.get('error'):
                    limited = any('limit' in str(e).lower() for e in payload['error'])
                    raise ProviderError('Kraken: Handelspaar nicht verfügbar oder Abruflimit erreicht.', limited)
                series = [v for k, v in payload.get('result', {}).items() if k != 'last']
                if len(series) != 1:
                    raise ProviderError('Kraken lieferte kein eindeutiges Handelspaar.')
                # Last OHLC entry is always the unfinished current interval.
                rows = [{'date': datetime.fromtimestamp(r[0], timezone.utc).date().isoformat(), 'close': r[4]} for r in series[0][:-1]]
            return {**base, **history_result(position, mapping, self.id, rows, adjusted=adjusted)}
        except ProviderError as exc:
            return {**base, 'status': 'error', 'message': str(exc), 'stop_provider': exc.stop}
        except Exception:
            return {**base, 'status': 'error', 'message': 'Abruf oder Datenformat fehlerhaft. Quelle und Zuordnung prüfen.'}


class DivvyDiaryProvider:
    def __init__(self, api_key='', transport=None):
        self.key = api_key
        self.transport = transport or request_json

    def fetch(self, position):
        base = {'security_key': position['key'], 'attempted_at': utcnow(), 'provider': 'DivvyDiary'}
        if not self.key:
            return {**base, 'status': 'error', 'message': 'DivvyDiary-API-Schlüssel fehlt. Unter „Online-Zugänge“ einrichten.', 'stop_provider': True}
        isin = position.get('isin', '')
        if not re.fullmatch(r'[A-Z]{2}[A-Z0-9]{9}\d', isin):
            return {**base, 'status': 'mapping_needed', 'message': 'Für DivvyDiary wird eine gültige ISIN benötigt.'}
        try:
            payload = self.transport('https://api.divvydiary.com/symbols/' + isin, {'X-API-Key': self.key})
            if not isinstance(payload, dict) or not isinstance(payload.get('dividends'), list):
                raise ProviderError('Keine gültigen Dividenden geliefert. API-Berechtigung prüfen.')
            if payload.get('isin') and payload['isin'] != isin:
                raise ProviderError('Antwort-ISIN stimmt nicht mit dem Wertpapier überein.')
            events = set()
            for row in payload['dividends']:
                ex_date = checked_day(row['exDate']) if row.get('exDate') else ''
                pay_date = checked_day(row['payDate']) if row.get('payDate') else ''
                if not ex_date and not pay_date:
                    raise ProviderError('Dividendentermin ohne Datum geliefert.')
                amount = Decimal(str(row['amount']))
                currency = currency_code(row['currency'])
                if not amount.is_finite() or amount < 0 or not re.fullmatch(r'[A-Z]{3}', currency):
                    raise ProviderError('Ungültiger Dividendenbetrag oder fehlende Währung.')
                events.add((ex_date, pay_date, str(amount), currency))
            return {**base, 'status': 'ok', 'message': f'{len(events)} Dividendentermine gespeichert.', 'isin': isin,
                    'events': [{'ex_date': e, 'pay_date': p, 'amount': a, 'currency': c} for e, p, a, c in sorted(events)],
                    'source_url': 'https://divvydiary.com/en/' + isin}
        except ProviderError as exc:
            return {**base, 'status': 'error', 'message': str(exc), 'stop_provider': exc.stop}
        except Exception:
            return {**base, 'status': 'error', 'message': 'DivvyDiary-Antwort konnte nicht verarbeitet werden.'}
