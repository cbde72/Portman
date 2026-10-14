"""Read-only ING FinTS adapter. Credentials and protocol messages are never persisted."""
from dataclasses import asdict
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
import base64
import re

from portfolio_v5.models import Balance, ImportBatch, Position, Snapshot, digest
from portfolio_v5.importers import asset_type

ENDPOINT = 'https://fints.ing.de/fints/'
SOURCE = 'Online ING'


class BankingError(Exception):
    """Only explicitly safe messages may be displayed to the user."""


class Cancelled(BankingError):
    pass


def safe_diagnostic(client, phase, error):
    """Expose only our phase, known exception types and numeric bank codes."""
    from fints.exceptions import FinTSError
    from requests.exceptions import RequestException
    codes = getattr(getattr(client, 'connection', None), 'response_codes', [])
    codes = codes if isinstance(codes, (list, tuple)) else []
    codes = sorted({code for code in codes if isinstance(code, str) and re.fullmatch(r'[39]\d{3}', code)})
    known = (FinTSError, RequestException, ValueError, TypeError, AttributeError, KeyError, ImportError)
    kind = type(error).__name__ if isinstance(error, known) and re.fullmatch(r'[A-Za-z]+', type(error).__name__) else 'Verarbeitungsfehler'
    message = f'Phase: {phase}. Diagnose: {kind}. Bankcodes: {", ".join(codes) if codes else "keine empfangen"}.'
    reasons = getattr(getattr(client, 'connection', None), 'response_reasons', [])
    reasons = reasons if isinstance(reasons, (list, tuple)) else []
    if 'insufficient_permission' in reasons:
        message += (' Die Bank meldet: Berechtigung für den FinTS-Auftrag nicht ausreichend. '
                    'Bitte die FinTS-Freigabe und Kontozuordnung bei der Bank prüfen lassen. '
                    'Ein funktionierender Kundenportal-Zugang bestätigt diese Berechtigung nicht.')
    elif '9210' in codes:
        message += (' Der Bankcode 9210 kann auf eine fehlende Auftragsberechtigung hinweisen. '
                    'Der Code allein bestimmt die Ursache nicht eindeutig.')
    return message


def reset_diagnostic(client):
    connection = getattr(client, 'connection', None)
    for field in ('response_codes', 'response_reasons'):
        values = getattr(connection, field, None)
        if isinstance(values, list):
            values.clear()


def check_bank_response(client):
    codes = getattr(getattr(client, 'connection', None), 'response_codes', [])
    if isinstance(codes, (list, tuple)) and any(isinstance(code, str) and re.fullmatch(r'9\d{3}', code) for code in codes):
        raise BankingError('Die Bank hat für diesen Abruf einen Fehler gemeldet; keine Übernahme dieses Abrufteils.')


def decimal_value(value):
    try:
        result = Decimal(str(value))
        if not result.is_finite():
            raise ValueError
        return result
    except (InvalidOperation, ValueError, TypeError):
        raise BankingError('Die Bank hat einen fehlenden oder ungültigen Zahlenwert geliefert.') from None


def parse_holdings(raw):
    """Strict subset of MT535: reject unknown/missing fields instead of losing positions.

    In particular use HOLD currency, not the currency of the security's price.
    python-fints' minimal parser can silently omit fields or reuse total_value.
    """
    from fints.utils import MT535_Miniparser
    if isinstance(raw, bytes):
        raw = raw.decode('iso-8859-1')
    lines = [line for line in raw.splitlines() if line and line != '-']
    clauses = MT535_Miniparser().collapse_multilines(lines + ['-'])
    starts = sum(c == ':16R:FIN' for c in clauses)
    ends = sum(c == ':16S:FIN' for c in clauses)
    segments = MT535_Miniparser().grab_financial_instrument_segments(clauses)
    if starts != ends or len(segments) != starts:
        raise BankingError('Unvollständige Depotantwort; der bisherige Bestand bleibt erhalten.')
    if not segments:
        # Do not interpret an absent/unparsed bank response as an empty depot.
        if ':17B::ACTI//N' not in clauses:
            raise BankingError('Kein eindeutig bestätigter Depotbestand in der Bankantwort.')
        return []
    positions = []
    for segment in segments:
        def required(pattern):
            matches = [m for c in segment if (m := re.fullmatch(pattern, c))]
            if len(matches) != 1:
                raise BankingError('Ein Depotfeld fehlt oder hat ein nicht unterstütztes Format. Kein Import dieses Depots.')
            return matches[0]
        identification = required(r':35B:ISIN\s+([A-Z]{2}[A-Z0-9]{9}\d)\|(.+)')
        quantity = required(r':93B::AGGR//UNIT/(\d+,\d*)')
        value = required(r':19A::HOLD//([A-Z]{3})(N?)(\d+,\d*)')
        if value[1] != 'EUR' or value[2]:
            raise BankingError('Nur Depotpositionen mit positivem EUR-Bewertungswert werden unterstützt.')
        name = identification[2].split('|')
        if name[0].startswith('/'):
            name = name[1:]
        name = ' '.join(name) or identification[1]
        quote_date = None
        for clause in segment:
            if match := re.fullmatch(r':98A::PRIC//(\d{8})', clause):
                quote_date = datetime.strptime(match[1], '%Y%m%d').date().isoformat()
        positions.append(Position(identification[1], name, isin=identification[1],
            asset_type=asset_type(name, ''),
            quantity=str(decimal_value(quantity[1].replace(',', '.'))),
            value=str(decimal_value(value[3].replace(',', '.'))), currency='EUR',
            quote_date=quote_date))
    if len({p.key for p in positions}) != len(positions):
        raise BankingError('Mehrere Positionen mit derselben ISIN; Depot muss zunächst geprüft werden.')
    return positions


def create_client(user, pin, product_id, cancelled, *, endpoint=ENDPOINT, bank_code='50010517', bank='ING'):
    from fints.client import FinTS3PinTanClient
    from fints.message import FinTSInstituteMessage
    from fints.segments.depot import HKWPD5, HKWPD6
    from fints.connection import FinTSHTTPSConnection

    class Connection(FinTSHTTPSConnection):
        def __init__(self, url):
            super().__init__(url)
            self.response_codes = []
            self.response_reasons = []

        def send(self, msg):
            from requests.exceptions import SSLError, Timeout, ConnectionError
            if cancelled():
                raise Cancelled('Abruf abgebrochen.')
            # No protocol logging, redirects, retries or unbounded HTTP wait.
            try:
                response = self.session.post(endpoint,
                    data=base64.b64encode(msg.render_bytes()),
                    headers={'Content-Type': 'text/plain'}, timeout=(10, 30), allow_redirects=False)
            except SSLError:
                raise BankingError(f'Die TLS-Verbindung zum {bank}-Server konnte nicht geprüft werden. Zertifikatsfehler; keine Aussage über die Zugangsdaten.') from None
            except Timeout:
                raise BankingError(f'Der {bank}-Server hat nicht rechtzeitig geantwortet. Zeitüberschreitung; keine Aussage über die Zugangsdaten.') from None
            except ConnectionError:
                raise BankingError(f'Die Verbindung zum {bank}-Server konnte nicht hergestellt werden. Keine Aussage über die Zugangsdaten.') from None
            if response.status_code != 200:
                raise BankingError(f'Der {bank}-Server hat den Abruf mit HTTP {response.status_code} beendet. Keine Aussage über die Zugangsdaten.')
            message = FinTSInstituteMessage(segments=base64.b64decode(response.content))
            # Capture the complete response before the library may raise on its
            # first generic error (e.g. 9050). Never retain response text/parameters.
            for segment in message.find_segments(['HIRMG', 'HIRMS']):
                for reply in segment.responses:
                    code = str(reply.code)
                    if re.fullmatch(r'[39]\d{3}', code) and code not in self.response_codes:
                        self.response_codes.append(code)
                    if code == '9210' and 'kompetenz nicht ausreichend' in ' '.join(str(reply.text).casefold().split()):
                        if 'insufficient_permission' not in self.response_reasons:
                            self.response_reasons.append('insufficient_permission')
            self.response_codes = self.response_codes[-20:]
            return message

    class Client(FinTS3PinTanClient):
        def _log_response(self, segment, response):
            # Bank text/parameters may contain personal data. Diagnostics use codes.
            pass

        @staticmethod
        def parse_depot_responses(responses):
            if not responses:
                raise BankingError('Keine Depotantwort erhalten; der bisherige Bestand bleibt erhalten.')
            positions = [p for response in responses for p in parse_holdings(response.holdings)]
            if len({p.key for p in positions}) != len(positions):
                raise BankingError('Doppelte ISIN in der Depotantwort; kein Import dieses Depots.')
            return positions

        def get_holdings(self, account):
            # Same paginated HKWPD request as python-fints 5.0, strict parsing below.
            with self._get_dialog() as dialog:
                command = self._find_highest_supported_command(HKWPD5, HKWPD6)
                return self._fetch_with_touchdowns(dialog,
                    lambda touchdown: command(account=command._fields['account'].type.from_sepa_account(account),
                                              touchdown_point=touchdown),
                    self.parse_depot_responses, 'HIWPD')

    client = Client(bank_code, user, pin, endpoint, product_id=product_id)
    client.connection.session.close()
    client.connection = Connection(endpoint)
    return client


def fetch_ing(user, pin, product_id, *, source_root, cancelled=lambda: False,
              progress=lambda message: None, client_factory=create_client, today=None,
              history_start=None, history_end=None, fetch_documents=False,
              bank='ING', bank_code='50010517', source_prefix='ing', challenge=None,
              prefer_upd_accounts=False, bank_bic=None):
    """Return preview batches only. Never writes to the repository or a file."""
    from fints.client import FinTSOperations, NeedTANResponse
    from fints.models import SEPAAccount
    from fints.exceptions import FinTSClientPINError, FinTSSCARequiredError, FinTSClientTemporaryAuthError
    today = today or date.today()
    history_end = history_end or today
    if history_start is not None and not history_start <= history_end <= today:
        raise BankingError('Bitte einen gültigen Umsatzzeitraum bis spätestens heute wählen.')
    if not user.strip() or not pin or not product_id.strip():
        raise BankingError('Bitte Benutzername/Zugangsnummer, PIN/Passwort und FinTS-Produkt-ID eingeben.')
    client = None
    phase = 'FinTS-Client vorbereiten'
    source_sheet = f'Online {bank}'
    def checked(result):
        nonlocal phase
        if cancelled():
            raise Cancelled('Abruf abgebrochen.')
        while isinstance(result, NeedTANResponse):
            if challenge is None:
                raise BankingError(f'{bank} fordert eine Freigabe. Bitte zuerst im {bank}-Online-Banking anmelden und danach erneut abrufen.')
            if result.decoupled or result.challenge_matrix or result.challenge_hhduc:
                raise BankingError('Dieses TAN-Verfahren wird hier nicht unterstützt. Bitte ein Verfahren mit manueller TAN-Eingabe verwenden.')
            tan = challenge(result.challenge or 'Bitte die SMS-TAN für den Datenabruf eingeben.')
            if tan is None or cancelled():
                raise Cancelled('Abruf abgebrochen.')
            try:
                previous_phase, phase = phase, 'TAN-Freigabe'
                result = client.send_tan(result, tan)
                phase = previous_phase
            finally:
                tan = None
            if cancelled():
                raise Cancelled('Abruf abgebrochen.')
        return result
    try:
        client = client_factory(user.strip(), pin, product_id.strip(), cancelled)
        phase = 'FinTS-Anmeldung'
        progress(f'Verbindung zur {bank} wird hergestellt …')
        batches = []
        with client:
            checked(client.init_tan_response)
            phase = 'Kontoberechtigungen auswerten'
            information = client.get_information()
            # Baader may deny HKSPA even though HIUPD already identifies the
            # accounts and their allowed operations. Use that authenticated list
            # directly; do not make a redundant SEPA request a login requirement.
            if prefer_upd_accounts and any(details.get('account_number')
                                           for details in information.get('accounts', [])):
                accounts = []
                progress(f'{bank}: Konten aus den übermittelten Benutzerparameterdaten übernehmen …')
            else:
                phase = 'Kontenliste abrufen (HKSPA)'
                accounts = checked(client.get_sepa_accounts())
                phase = 'Kontoberechtigungen auswerten'
                information = client.get_information()
            # UPD includes depots that may be absent from the SEPA account response.
            for details in information.get('accounts', []):
                checked(None)
                ops = details.get('supported_operations', {})
                depot = bool(ops.get(FinTSOperations.GET_HOLDINGS))
                if not any(ops.get(op) for op in (FinTSOperations.GET_HOLDINGS, FinTSOperations.GET_BALANCE,
                           FinTSOperations.GET_TRANSACTIONS, FinTSOperations.GET_TRANSACTIONS_XML,
                           FinTSOperations.GET_STATEMENT, FinTSOperations.GET_STATEMENT_PDF)):
                    continue
                number = details.get('account_number')
                sub = details.get('subaccount_number') or ''
                if not number:
                    continue
                account = next((a for a in accounts if a.accountnumber == number and (a.subaccount or '') == sub), None)
                if account is None:
                    account = SEPAAccount(details.get('iban'), bank_bic, number, sub, bank_code)
                kind = 'Depot' if depot else 'Konto'
                # Full source identity, independent of the login used to retrieve it.
                source = f'{bank} {kind} {number}' + (f'/{sub}' if sub else '')
                path = str(Path(source_root) / f'{source_prefix}-{kind.lower()}-{number}-{sub or "0"}.bank')
                batch = ImportBatch(path, '', account_names=[source], source_sheet=source_sheet)
                progress(f'{kind} …{number[-4:]} wird abgerufen …')
                try:
                    phase = 'Depotbestand abrufen' if depot else 'Kontosaldo abrufen'
                    reset_diagnostic(client)
                    if depot:
                        positions = checked(client.get_holdings(account))
                        check_bank_response(client)
                        batch.snapshots.append(Snapshot(source, today.strftime('%Y-%m'), today.isoformat(),
                            source_sheet, positions, complete=True, date_basis='retrieval'))
                        batch.warnings.append('Das Datum entspricht dem Abruftag. Einstandswerte werden nicht aus Kursen geschätzt.')
                    elif ops.get(FinTSOperations.GET_BALANCE):
                        balance = checked(client.get_balance(account))
                        check_bank_response(client)
                        if balance is None:
                            raise BankingError('Keine Saldoantwort geliefert; bisheriger Saldo bleibt erhalten.')
                        if balance.amount.currency != 'EUR':
                            raise BankingError('Der gelieferte Saldo ist nicht in EUR; bisheriger Saldo bleibt erhalten.')
                        amount = decimal_value(balance.amount.amount)
                        bank_date = balance.date
                        if not isinstance(bank_date, date) or bank_date > today:
                            raise BankingError('Kein gültiges Saldodatum von der Bank geliefert.')
                        batch.balances.append(Balance(bank_date.strftime('%Y-%m'), 'Liquidität', source,
                            str(amount), f'{source_sheet} · {bank_date.isoformat()}', 0))
                        batch.warnings.append(f'Saldo vom {bank_date.isoformat()}; Portman führt importierte Salden als Monatswerte.')
                    else:
                        batch.errors.append('Kein Saldo-/Depotabruf für dieses Konto freigegeben.')
                except (Cancelled, FinTSClientPINError, FinTSSCARequiredError, FinTSClientTemporaryAuthError):
                    raise
                except BankingError as error:
                    batch.errors.append(str(error) + ' ' + safe_diagnostic(client, phase, error))
                except Exception as error:
                    batch.errors.append('Bankantwort konnte nicht sicher verarbeitet werden. Bisherige Daten bleiben erhalten. '
                                        + safe_diagnostic(client, phase, error))
                batch.file_hash = digest({'source': source, 'snapshots': [asdict(s) for s in batch.snapshots],
                                          'balances': [asdict(b) for b in batch.balances]})
                batches.append(batch)
                if history_start is not None or fetch_documents:
                    phase = 'Kontohistorie abrufen'
                    from .ing_history import fetch_history
                    batches.extend(fetch_history(client, account, ops, source, path, checked, progress,
                        start=history_start, end=history_end, documents=fetch_documents,
                        source_sheet=source_sheet, source_prefix=source_prefix))
        checked(None)
        if not batches:
            raise BankingError(f'{bank} hat keine Konten mit freigegebenem Saldo- oder Depotabruf gemeldet. Bitte die FinTS-Freischaltung prüfen.')
        return batches
    except BankingError:
        raise
    except FinTSClientPINError as error:
        explanation = (f'{bank} hat die FinTS-Anmeldung oder Freigabe abgelehnt. '
                       'Das belegt nicht, dass die PIN für das Kundenportal falsch ist. '
                       if bank != 'ING' else f'{bank} hat die Zugangsdaten abgelehnt. ')
        raise BankingError(explanation + 'Es erfolgt kein automatischer Neuversuch. '
                           + safe_diagnostic(client, phase, error)) from None
    except FinTSClientTemporaryAuthError as error:
        raise BankingError(f'{bank} meldet eine vorübergehende Zugangssperre. '
                           'Bitte den Zugang im Kundenportal prüfen. '
                           + safe_diagnostic(client, phase, error)) from None
    except FinTSSCARequiredError as error:
        raise BankingError(f'{bank} verlangt eine zusätzliche Freigabe für FinTS. '
                           + safe_diagnostic(client, phase, error)) from None
    except Exception as error:
        raise BankingError(f'{bank}-Abruf fehlgeschlagen. Es wurden keine Portfolio-Daten gespeichert. '
                           + safe_diagnostic(client, phase, error)) from None
    finally:
        if client is not None:
            client.pin = None
            client.connection.session.close()
