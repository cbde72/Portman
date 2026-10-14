"""Read-only comdirect REST import. Tokens live only for one preview fetch."""
import json
import re
import time
import uuid
from dataclasses import asdict
from datetime import date
from pathlib import Path
from urllib.parse import quote, urlsplit

import requests

from portfolio_v5.importers import asset_type
from portfolio_v5.models import Balance, BankTransaction, ImportBatch, Position, Snapshot, digest
from .ing_banking import BankingError, Cancelled, decimal_value
from .comdirect_requests import REQUEST_QUEUE, retry_delay
from .comdirect_cache import FETCH_CACHE

BASE = 'https://api.comdirect.de'
SOURCE = 'Online comdirect'
SESSIONS = '/api/session/clients/user/v1/sessions'


def identifier(value):
    if not isinstance(value, str) or not value.strip():
        raise BankingError('Eine Konto-, Depot- oder Wertpapierkennung fehlt in der Bankantwort.')
    return value


def amount(value, unit='EUR'):
    if not isinstance(value, dict) or value.get('unit') != unit:
        raise BankingError('Betrag oder Einheit wird nicht unterstützt. Bestände benötigen EUR, Stückzahlen XXX.')
    return decimal_value(value.get('value'))


class ComdirectClient:
    def __init__(self, cancelled=lambda: False, progress=lambda message: None, *, session=None, request_queue=None):
        self.http = session or requests.Session()
        self.cancelled, self.progress = cancelled, progress
        self.token = ''
        self.session_id = uuid.uuid4().hex
        self.request_queue = request_queue if request_queue is not None else REQUEST_QUEUE

    def check(self):
        if self.cancelled():
            raise Cancelled('Abruf abgebrochen.')

    def request(self, method, path, *, expected=(200,), headers=None, **kwargs):
        self.check()
        # A server-supplied TAN link must never forward credentials elsewhere.
        url = urlsplit(path)
        if url.scheme or url.netloc:
            if url.scheme != 'https' or url.netloc != 'api.comdirect.de':
                raise BankingError('Ungültiger Freigabelink der Bank.')
            path = url.path + ('?' + url.query if url.query else '')
        if not path.startswith(('/api/', '/oauth/')) or '\\' in path:
            raise BankingError('Ungültiger API-Pfad.')
        request_headers = {'Accept': 'application/json'}
        if 'data' not in kwargs:
            request_headers['Content-Type'] = 'application/json'
        if self.token:
            request_headers['Authorization'] = 'Bearer ' + self.token
        request_headers.update(headers or {})
        for attempt in range(4):
            request_headers['x-http-request-info'] = json.dumps({'clientRequestId': {
                'sessionId': self.session_id, 'requestId': str(time.time_ns())[-9:]}})
            try:
                response = self.request_queue.run(lambda: self.http.request(method, BASE + path,
                    headers=request_headers.copy(), timeout=(10, 30), allow_redirects=False, **kwargs),
                    self.check, self.progress)
            except requests.RequestException:
                raise BankingError('comdirect ist nicht erreichbar oder antwortet zu langsam. Bitte später erneut versuchen.') from None
            self.check()
            if response.status_code != 429:
                break
            delay = retry_delay(response.headers.get('Retry-After'), attempt)
            self.request_queue.defer(delay)
            # Never replay TAN activation or token exchanges automatically.
            if method != 'GET' or attempt == 3 or delay > 120:
                break
            self.progress(f'comdirect-Abruflimit erreicht. Neuer Versuch {attempt + 1}/3 nach mindestens {delay:g} Sekunden …')
            response.close()
        self.check()
        if response.status_code not in expected:
            messages = {400: 'comdirect hat die Anfrage abgelehnt. Zugangsdaten und API-Freischaltung prüfen.',
                401: 'comdirect-Zugang abgelehnt oder Sitzung abgelaufen. Bitte erneut anmelden.',
                403: 'comdirect hat den Zugriff nicht freigegeben. API-Berechtigung und TAN-Freigabe prüfen.',
                429: 'comdirect-Abruflimit erreicht. Bitte später erneut versuchen.'}
            raise BankingError(messages.get(response.status_code,
                'comdirect lieferte einen unerwarteten HTTP-Status. Es erfolgt kein automatischer Neuversuch.'))
        return response

    def data(self, method, path, **kwargs):
        try:
            return self.request(method, path, **kwargs).json()
        except (ValueError, TypeError):
            raise BankingError('comdirect lieferte keine gültige JSON-Antwort.') from None

    def login(self, user, pin, client_id, client_secret, challenge):
        self.progress('Verbindung zu comdirect wird hergestellt …')
        credentials = dict(client_id=client_id, client_secret=client_secret)
        self.token = identifier(self.data('POST', '/oauth/token', data=dict(
            credentials, grant_type='password', username=user, password=pin))['access_token'])
        sessions = self.data('GET', SESSIONS)
        if not isinstance(sessions, list) or len(sessions) != 1:
            raise BankingError('comdirect hat keine eindeutige Sitzung geliefert.')
        sid = identifier(sessions[0].get('identifier'))
        path = SESSIONS + '/' + quote(sid, safe='')
        body = dict(identifier=sid, sessionTanActive=True, activated2FA=True)
        response = self.request('POST', path + '/validate', json=body, expected=(201,))
        try:
            auth = json.loads(response.headers['x-once-authentication-info'])
            auth_id = identifier(auth['id'])
        except (KeyError, ValueError, TypeError):
            raise BankingError('comdirect hat keine gültige TAN-Anforderung geliefert.') from None
        headers = {'x-once-authentication-info': json.dumps({'id': auth_id})}
        if auth.get('typ') == 'P_TAN_PUSH':
            self.progress('Bitte die Anmeldung in der comdirect photoTAN-App freigeben …')
            link = auth.get('link', {})
            if link.get('method', 'GET') != 'GET' or not link.get('href'):
                raise BankingError('Der Statuslink für die photoTAN-Freigabe fehlt.')
            deadline = time.monotonic() + 180
            while time.monotonic() < deadline:
                self.check()
                status = self.data('GET', link['href']).get('status')
                if status == 'AUTHENTICATED':
                    break
                if status not in ('PENDING', 'WAITING', 'CREATED', 'INITIALIZED'):
                    raise BankingError('Die photoTAN-Freigabe wurde abgelehnt oder ist abgelaufen.')
                for _ in range(20):
                    self.check()
                    time.sleep(.1)
            else:
                raise BankingError('Die photoTAN-Freigabe ist abgelaufen. Bitte erneut abrufen.')
        elif auth.get('typ') in ('P_TAN', 'M_TAN'):
            tan = challenge(auth)
            self.check()
            if not tan:
                raise Cancelled('TAN-Eingabe abgebrochen.')
            if not re.fullmatch(r'\d{6}', tan):
                raise BankingError('Bitte eine sechsstellige TAN eingeben.')
            headers['x-once-authentication'] = tan
        else:
            raise BankingError('Das von comdirect geforderte TAN-Verfahren wird nicht unterstützt.')
        self.data('PATCH', path, json=body, headers=headers)
        self.token = identifier(self.data('POST', '/oauth/token', data=dict(
            credentials, grant_type='cd_secondary', token=self.token))['access_token'])

    def collection(self, path, *, params=None):
        """Never turn an absent/truncated collection into a complete empty depot."""
        rows, first, total = [], 0, None
        for _ in range(1000):
            payload = self.data('GET', path, params={**(params or {}), 'paging-first': first})
            if not isinstance(payload, dict) or not isinstance(payload.get('values'), list):
                raise BankingError('Unvollständige Liste in der comdirect-Antwort.')
            paging = payload.get('paging', {})
            matches, index = paging.get('matches'), paging.get('index')
            if type(matches) is not int or type(index) is not int or matches < 0 or index != first:
                raise BankingError('Die Vollständigkeit der comdirect-Antwort lässt sich nicht bestätigen.')
            if total is not None and total != matches:
                raise BankingError('Bankdaten haben sich während des Abrufs geändert. Bitte erneut abrufen.')
            total = matches
            page = payload['values']
            if any(not isinstance(row, dict) for row in page):
                raise BankingError('Ungültiger Eintrag in der comdirect-Antwort.')
            rows.extend(page)
            first += len(page)
            if first == total:
                return rows
            if not page or first > total:
                raise BankingError('Unvollständige comdirect-Antwort; bisherige Daten bleiben erhalten.')
        raise BankingError('Zu viele Datensätze für einen einzelnen Abruf.')

    def close(self):
        # Best effort revoke also on failed authentication. Never mask fetch errors.
        if self.token:
            try:
                self.request_queue.run(lambda: self.http.request('DELETE', BASE + '/oauth/revoke',
                    headers={'Authorization': 'Bearer ' + self.token, 'Accept': 'application/json',
                             'Content-Type': 'application/x-www-form-urlencoded'},
                    timeout=(5, 5), allow_redirects=False),
                    lambda: None, lambda message: None, max_wait=10)
            except Exception:
                pass
        self.token = ''
        self.http.close()


def parse_positions(rows, depot_id):
    positions = []
    for row in rows:
        if row.get('depotId') != depot_id:
            raise BankingError('Eine Depotposition gehört nicht zum angefragten Depot.')
        instrument = row.get('instrument') or {}
        isin = instrument.get('isin', '')
        if not re.fullmatch(r'[A-Z]{2}[A-Z0-9]{9}\d', isin):
            raise BankingError('ISIN fehlt oder ist ungültig. Dieses Depot wird nicht übernommen.')
        quantity, value = amount(row.get('quantity'), 'XXX'), amount(row.get('currentValue'))
        if quantity < 0 or value < 0:
            raise BankingError('Negative Depotbestände werden nicht unterstützt.')
        name = instrument.get('name') or instrument.get('shortName') or isin
        price_date = (row.get('currentPrice') or {}).get('priceDateTime')
        quote_date = date.fromisoformat(price_date[:10]).isoformat() if price_date else None
        cost = None
        if row.get('purchaseValue') is not None:
            cost = str(amount(row['purchaseValue']))
        positions.append(Position(isin, name, isin=isin, wkn=instrument.get('wkn') or row.get('wkn', ''),
            asset_type=asset_type(name, ''), quantity=str(quantity), value=str(value), cost=cost,
            currency='EUR', quote_date=quote_date))
    if len({p.key for p in positions}) != len(positions):
        raise BankingError('Mehrere Positionen derselben ISIN. Dieses Depot muss zunächst geprüft werden.')
    return positions


def parse_transactions(rows, source, start, end):
    result, seen = [], set()
    for row in rows:
        if row.get('bookingStatus') == 'NOTBOOKED':
            continue
        if row.get('bookingStatus') != 'BOOKED':
            raise BankingError('Eine Kontobuchung hat keinen eindeutigen Buchungsstatus.')
        booked = date.fromisoformat(row['bookingDate'])
        if not start <= booked <= end:
            continue
        reference = identifier(row.get('reference'))
        if reference in seen:
            raise BankingError('Doppelte Buchungsreferenz in der Bankantwort; kein Umsatzimport.')
        seen.add(reference)
        currency = row.get('amount', {}).get('unit', '')
        if not re.fullmatch(r'[A-Z]{3}', currency):
            raise BankingError('Ungültige Buchungswährung.')
        value_date = row.get('valutaDate', '')
        try:
            value_date = date.fromisoformat(value_date).isoformat()
        except ValueError:
            value_date = ''  # API explicitly permits invalid value dates.
        counterparty = next((row[k].get('holderName', '') for k in ('remitter', 'creditor', 'deptor')
                             if isinstance(row.get(k), dict) and row[k].get('holderName')), '')
        party = next((row[k] for k in ('remitter','creditor','deptor') if isinstance(row.get(k), dict) and row[k].get('holderName') == counterparty), {})
        result.append(BankTransaction(source, 'comdirect-booking-' + digest([source, reference]),
            booked.isoformat(), 'BANK_BOOKING', str(amount(row['amount'], currency)), currency,
            value_date=value_date, purpose=row.get('remittanceInfo') or '',
            counterparty=counterparty, bank_reference=reference,
            counterparty_iban=party.get('iban') or '', counterparty_bic=party.get('bic') or '',
            operation=row.get('bookingText') or '', booking_text=row.get('remittanceInfo') or '',
            raw_text=json.dumps(row, ensure_ascii=False)))
    return result


def fetch_comdirect(user, pin, client_id, client_secret, *, source_root,
                    cancelled=lambda: False, progress=lambda message: None,
                    challenge=lambda auth: None, client_factory=ComdirectClient,
                    today=None, history_start=None, history_end=None, cache=FETCH_CACHE, refresh=False):
    """Build import previews; never write bank responses or portfolio data."""
    today = today or date.today()
    history_end = history_end or today
    if not all((user.strip(), pin, client_id.strip(), client_secret.strip())):
        raise BankingError('Bitte Zugangsnummer, PIN, Client-ID und Client-Secret eingeben.')
    if history_start is not None and not history_start <= history_end <= today:
        raise BankingError('Bitte einen gültigen Umsatzzeitraum bis spätestens heute wählen.')
    if cancelled():
        raise Cancelled('Abruf abgebrochen.')
    cache_key = digest([str(Path(source_root).resolve()), user.strip(), pin, client_id.strip(),
                        client_secret.strip(), str(today), str(history_start), str(history_end)])
    fetched_at = cache.clock() if cache is not None else None
    if cache is not None and refresh:
        cache.discard(cache_key)
    cached = cache.get(cache_key) if cache is not None and not refresh else None
    if cached is not None:
        progress('comdirect: Erfolgreichen Abruf aus dem Arbeitsspeicher übernommen (höchstens 5 Minuten alt).')
        for batch in cached:
            batch.warnings.append('Aus dem comdirect-Zwischenspeicher: Abruf höchstens 5 Minuten alt.')
        return cached
    client = client_factory(cancelled, progress)
    batches = []

    def batch_for(kind, identity, source):
        # Account/depot display IDs remain stable across API credentials/sessions.
        path = Path(source_root) / f'comdirect-{kind}-{digest(identity)[:24]}.bank'
        batch = ImportBatch(str(path), '', account_names=[source], source_sheet=SOURCE)
        batches.append(batch)
        return batch

    def fill(batch, action):
        try:
            client.check()
            action()
        except Cancelled:
            raise
        except BankingError as error:
            batch.errors.append(str(error))
        except Exception:
            batch.errors.append('Bankantwort konnte nicht sicher verarbeitet werden. Bisherige Daten bleiben erhalten.')
        batch.file_hash = digest({'source': batch.account_names, 'snapshots': [asdict(s) for s in batch.snapshots],
            'balances': [asdict(b) for b in batch.balances], 'transactions': [asdict(t) for t in batch.transactions]})

    try:
        client.login(user.strip(), pin, client_id.strip(), client_secret.strip(), challenge)
        progress('comdirect-Kontosalden werden abgerufen …')
        accounts = client.collection('/api/banking/clients/user/v2/accounts/balances')
        identities = set()
        for row in accounts:
            account = row.get('account') or {}
            account_id = identifier(row.get('accountId'))
            identity = identifier(account.get('iban') or account.get('accountDisplayId'))
            if identity in identities:
                raise BankingError('Doppelte Konten in der Bankantwort.')
            identities.add(identity)
            source = 'comdirect Konto ' + identity
            batch = batch_for('konto', identity, source)

            def balance():
                value = amount(row.get('balance'))
                batch.balances.append(Balance(today.strftime('%Y-%m'), 'Liquidität', source, str(value),
                    f'{SOURCE} · Abruf {today.isoformat()}', 0))
                batch.warnings.append('Aktueller Saldo zum Abrufzeitpunkt; kein Saldodatum geliefert. Portman führt Salden als Monatswerte.')
            fill(batch, balance)
            if history_start is not None:
                history = batch_for('umsaetze', identity, source)

                def transactions():
                    progress('Gebuchte comdirect-Kontoumsätze werden abgerufen …')
                    rows = client.collection('/api/banking/v1/accounts/' + quote(account_id, safe='') + '/transactions',
                        params={'transactionState': 'BOOKED', 'min-bookingDate': history_start.isoformat(),
                                'max-bookingDate': history_end.isoformat()})
                    history.transactions = parse_transactions(rows, source, history_start, history_end)
                    history.history_end = history_end.isoformat()
                    from .bank_history_range import ALL_HISTORY_START
                    requested_start = 'gesamte verfügbare Historie' if history_start == ALL_HISTORY_START else str(history_start)
                    history.warnings.append(f'Zeitraum: {requested_start} bis {history_end}. Nur von der Bank verfügbare Buchungen; keine Zusicherung einer lückenlosen Historie. Keine automatische Einstufung als Wertpapiergeschäft.')
                    if history.transactions:
                        dates = [tx.date for tx in history.transactions]
                        history.warnings.append(f'Geliefert: {len(dates)} Buchungen, {min(dates)} bis {max(dates)}.')
                    if not history.transactions:
                        history.warnings.append('Keine neuen gebuchten Umsätze im gewählten Zeitraum geliefert.')
                fill(history, transactions)
        progress('comdirect-Depots werden abgerufen …')
        depots = client.collection('/api/brokerage/clients/user/v3/depots')
        if not depots:
            diagnostic = batch_for('depotpruefung', 'missing-depots', 'comdirect Depotabruf')
            diagnostic.errors.append(
                'comdirect hat für diesen Zugang keine Depots zurückgegeben. '
                'Es wurden deshalb keine Depotbestände abgerufen. Bitte prüfen, ob das Depot '
                'im Online-Banking unter derselben Zugangsnummer sichtbar und für den '
                'API-Zugang freigegeben ist. Kontosalden und Umsätze können separat importiert werden.')
        identities = set()
        for depot in depots:
            depot_id = identifier(depot.get('depotId'))
            identity = identifier(depot.get('depotDisplayId'))
            if identity in identities:
                raise BankingError('Doppelte Depots in der Bankantwort.')
            identities.add(identity)
            source = 'comdirect Depot ' + identity
            batch = batch_for('depot', identity, source)

            def holdings():
                rows = client.collection('/api/brokerage/v3/depots/' + quote(depot_id, safe='') + '/positions',
                    params={'with-attr': 'instrument'})
                positions = parse_positions(rows, depot_id)
                batch.snapshots.append(Snapshot(source, today.strftime('%Y-%m'), today.isoformat(), SOURCE,
                    positions, complete=True, date_basis='retrieval'))
                batch.warnings.append('Bestand zum Abrufdatum; Einstandswerte werden nur übernommen, wenn comdirect sie in EUR liefert.')
            fill(batch, holdings)
        client.check()
        if not batches:
            raise BankingError('comdirect hat keine Konten oder Depots geliefert.')
        if cache is not None and not any(batch.errors for batch in batches):
            cache.put(cache_key, batches, acquired_at=fetched_at)
        return batches
    except BankingError:
        raise
    except Exception:
        raise BankingError('comdirect-Abruf fehlgeschlagen. Zugang und API-Freischaltung prüfen. Es wurden keine Portfolio-Daten gespeichert.') from None
    finally:
        client.close()
