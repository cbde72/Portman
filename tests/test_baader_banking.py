from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from test_ing_banking import FakeClient, RAW
from portman.baader_banking import fetch_baader, create_client, BankingError, Cancelled, ENDPOINT
from portman.baader_credentials import BaaderCredentialStore
from portman.ing_credentials import INGCredentialStore
from portman.comdirect_credentials import ComdirectCredentialStore
from portman.ing_banking import parse_holdings
from fints.client import NeedTANResponse, FinTSOperations as Op
from fints.exceptions import FinTSClientPINError


def challenge():
    result = object.__new__(NeedTANResponse)
    result.challenge = 'Bitte SMS-TAN eingeben'
    result.decoupled = False
    return result


def fetch(fake, tmp_path, **kwargs):
    return fetch_baader('user', 'secret', 'product', source_root=tmp_path,
        client_factory=lambda *args: fake, today=date(2026, 9, 24), **kwargs)


def test_login_and_holdings_tan_source_identity_and_cleanup(tmp_path):
    fake = FakeClient()
    fake.init_tan_response = challenge()
    fake.get_holdings.return_value = challenge()
    fake.send_tan = Mock(side_effect=[None, parse_holdings(RAW)])
    answer = Mock(return_value='123456')
    batches = fetch(fake, tmp_path, challenge=answer)
    assert answer.call_count == 2
    assert fake.send_tan.call_count == 2
    assert all(b.source_sheet == 'Online Baader' for b in batches)
    assert all(Path(b.path).name.startswith('baader-') for b in batches)
    assert batches[0].balances[0].account == 'Baader Konto 1234567890'
    assert batches[1].snapshots[0].positions[0].quantity == '6.847'
    assert fake.get_holdings.call_args.args[0].blz == '70033100'
    assert fake.pin is None
    fake.connection.session.close.assert_called_once()
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize('answer,cancelled', [(None, False), ('123456', True)])
def test_cancelled_tan_never_sent(tmp_path, answer, cancelled):
    fake = FakeClient()
    fake.init_tan_response = challenge()
    fake.send_tan = Mock()
    stopped = False

    def respond(message):
        nonlocal stopped
        stopped = cancelled
        return answer

    with pytest.raises(Cancelled):
        fetch(fake, tmp_path, challenge=respond, cancelled=lambda: stopped)
    fake.send_tan.assert_not_called()
    fake.get_balance.assert_not_called()
    assert fake.pin is None


def test_bad_tan_stops_without_retry(tmp_path):
    fake = FakeClient()
    fake.init_tan_response = challenge()
    fake.send_tan = Mock(side_effect=FinTSClientPINError('secret'))
    with pytest.raises(BankingError, match='Baader hat die FinTS-Anmeldung oder Freigabe abgelehnt'):
        fetch(fake, tmp_path, challenge=lambda message: '123456')
    fake.send_tan.assert_called_once()
    fake.get_balance.assert_not_called()


def test_history_has_baader_identity(tmp_path):
    from mt940.models import Amount
    fake = FakeClient()
    fake.get_information = lambda: {'accounts': [{'account_number': '1234567890',
        'supported_operations': {Op.GET_BALANCE: True, Op.GET_TRANSACTIONS: True}}]}
    fake.get_transactions = Mock(return_value=[SimpleNamespace(data={
        'date': date(2026, 9, 23), 'amount': Amount('10', 'C', currency='EUR')})])
    batches = fetch(fake, tmp_path, history_start=date(2026, 9, 1))
    history = batches[1]
    assert not history.errors
    assert history.source_sheet == 'Online Baader'
    assert history.transactions[0].external_id.startswith('baader-booking-')
    assert all('ING' not in warning for warning in history.warnings)
    assert fetch(FakeClient(), tmp_path)[0].file_hash == batches[0].file_hash


def test_baader_transport_and_deferred_holdings_parser():
    client = create_client('user', 'secret', 'product', lambda: False)
    client.connection.session.post = Mock(return_value=SimpleNamespace(status_code=302))
    with pytest.raises(BankingError, match='Baader-Server'):
        client.connection.send(SimpleNamespace(render_bytes=lambda: b'test'))
    assert client.connection.session.post.call_args.args == (ENDPOINT,)
    assert client.connection.session.post.call_args.kwargs['allow_redirects'] is False
    assert client.connection.session.post.call_args.kwargs['timeout'] == (10, 30)
    assert client.parse_depot_responses([SimpleNamespace(holdings=RAW)])[0].value == '61.62'
    with pytest.raises(BankingError):
        client.parse_depot_responses([])
    client.connection.session.close()


def test_credentials_are_isolated(tmp_path):
    stores = [cls(tmp_path) for cls in (BaaderCredentialStore, INGCredentialStore, ComdirectCredentialStore)]
    assert len({s.target for s in stores}) == 3
    assert BaaderCredentialStore(tmp_path / 'other').target != stores[0].target


def test_balance_import_does_not_replace_other_accounts(tmp_path):
    from portfolio_v5.models import ImportBatch, Balance
    from portman.repository import PortfolioRepository
    repo = PortfolioRepository(tmp_path / 'test.sqlite')
    repo.commit_batches([ImportBatch('overview.xlsx', 'old', balances=[
        Balance('2026-09', 'Liquidität', 'Baader Konto 1234567890', '100', 'Overview', 1),
        Balance('2026-09', 'Liquidität', 'Andere Bank', '700', 'Overview', 2)])])
    batch = fetch(FakeClient(), tmp_path)[0]
    first = repo.commit_batches([batch])[0]
    assert repo.commit_batches([batch])[0]['status'] == 'duplicate'
    assert {b['value'] for b in repo.balances()} == {'-12.34', '700'}
    repo.undo_import(first['id'])
    assert {b['value'] for b in repo.balances()} == {'100', '700'}
    repo.close()


def test_all_bank_error_codes_survive_early_library_error_without_secret_text(tmp_path, caplog):
    import base64
    client = create_client('user', 'secret', 'product', lambda: False)
    # A real parsed FinTS response, not a stubbed client method. The library can
    # abort before it reaches the second, more specific feedback segment.
    payload = b"HIRMG:1:2+9050::private-bank-text'HIRMS:2:2:3+9078::private-product-text'"
    client.connection.session.post = Mock(return_value=SimpleNamespace(
        status_code=200, content=base64.b64encode(payload)))
    with pytest.raises(BankingError) as result:
        fetch_baader('user', 'secret', 'product', source_root=tmp_path, client_factory=lambda *a: client)
    message = str(result.value)
    assert '9050' in message and '9078' in message
    assert 'Phase: FinTS-Anmeldung' in message
    assert 'private-' not in message and 'secret' not in message
    assert 'private-' not in caplog.text
    assert client.pin is None
    # Session termination may issue a close, but no second authentication attempt.
    assert client.connection.session.post.call_count <= 2


@pytest.mark.parametrize('error_type,expected', [
    ('SSLError', 'Zertifikatsfehler'), ('Timeout', 'Zeitüberschreitung'),
    ('ConnectionError', 'nicht hergestellt'),
])
def test_transport_failure_is_not_reported_as_wrong_credentials(error_type, expected):
    from requests import exceptions
    client = create_client('user', 'secret', 'product', lambda: False)
    client.connection.session.post = Mock(side_effect=getattr(exceptions, error_type)('private-content'))
    with pytest.raises(BankingError) as result:
        client.connection.send(SimpleNamespace(render_bytes=lambda: b'test'))
    assert expected in str(result.value)
    assert 'private-content' not in str(result.value)
    client.connection.session.close()


def test_tan_diagnostic_reports_stage_and_only_numeric_codes(tmp_path):
    fake = FakeClient()
    fake.init_tan_response = challenge()
    fake.connection.response_codes = ['9050', '9340', 'private-secret']
    fake.send_tan = Mock(side_effect=FinTSClientPINError('private-secret'))
    with pytest.raises(BankingError) as result:
        fetch(fake, tmp_path, challenge=lambda message: '123456')
    assert 'Phase: TAN-Freigabe' in str(result.value)
    assert '9050, 9340' in str(result.value)
    assert 'private-secret' not in str(result.value)
    fake.send_tan.assert_called_once()


def test_generic_client_failure_preserves_type_without_leaking_exception(tmp_path):
    fake = FakeClient()
    fake.get_information = Mock(return_value={'accounts': []})
    fake.get_sepa_accounts = Mock(side_effect=AttributeError('private bank data'))
    with pytest.raises(BankingError) as result:
        fetch(fake, tmp_path)
    assert 'Phase: Kontenliste abrufen' in str(result.value)
    assert 'Diagnose: AttributeError' in str(result.value)
    assert 'private bank data' not in str(result.value)


def test_upd_accounts_avoid_denied_sepa_request(tmp_path):
    fake = FakeClient()
    fake.get_sepa_accounts = Mock(side_effect=RuntimeError('HKSPA denied: 9050, 9210'))
    fake.get_information = Mock(return_value={'accounts': [
        {'account_number': '1234567890', 'subaccount_number': '01', 'iban': 'DEFAKE',
         'supported_operations': {Op.GET_BALANCE: True}},
        {'account_number': '9999999999', 'subaccount_number': '02',
         'supported_operations': {Op.GET_HOLDINGS: True}},
        {'account_number': '3333333333', 'supported_operations': {}},
    ]})
    batches = fetch(fake, tmp_path)
    fake.get_sepa_accounts.assert_not_called()
    assert len(batches) == 2 and not any(batch.errors for batch in batches)
    assert batches[0].balances[0].value == '-12.34'
    assert batches[1].snapshots[0].positions[0].quantity == '6.847'
    account = fake.get_balance.call_args.args[0]
    assert (account.accountnumber, account.subaccount, account.iban, account.blz) == (
        '1234567890', '01', 'DEFAKE', '70033100')
    assert fake.get_holdings.call_args.args[0].subaccount == '02'
    assert account.bic == 'BDWBDEMMXXX'


@pytest.mark.parametrize('version', [5, 6])
def test_upd_depot_can_build_real_fints_request(tmp_path, version):
    from contextlib import nullcontext
    from fints.segments.depot import HKWPD5, HKWPD6
    from fints.segments.saldo import HKSAL7
    fake = FakeClient()
    fake.get_information = Mock(return_value={'accounts': [
        {'account_number': '1234567890', 'iban': 'DEFAKE',
         'supported_operations': {Op.GET_BALANCE: True}},
        {'account_number': '9999999999', 'supported_operations': {Op.GET_HOLDINGS: True}},
    ]})
    real = create_client('user', 'secret', 'product', lambda: False)
    real._get_dialog = lambda: nullcontext()
    command = HKWPD5 if version == 5 else HKWPD6
    real._find_highest_supported_command = lambda *args: command
    captured = []

    def respond(dialog, factory, parser, *args):
        request = factory(None)
        captured.append(request)
        return parser([SimpleNamespace(holdings=RAW)])

    real._fetch_with_touchdowns = respond
    fake.get_holdings.side_effect = real.get_holdings
    batches = fetch(fake, tmp_path)
    assert not any(batch.errors for batch in batches)
    request = captured[0]
    assert request.account.account_number == '9999999999'
    identifier = request.account if version == 5 else request.account.bank_identifier
    assert identifier.country_identifier == '280'
    assert identifier.bank_code == '70033100'
    cash = fake.get_balance.call_args.args[0]
    converted = HKSAL7._fields['account'].type.from_sepa_account(cash)
    assert converted.iban == 'DEFAKE' and converted.bic == 'BDWBDEMMXXX'
    real.connection.session.close()


def test_silent_bank_rejection_does_not_look_like_empty_response(tmp_path):
    fake = FakeClient()
    fake.connection.response_codes = ['3060']
    fake.connection.response_reasons = []

    def rejected(account):
        fake.connection.response_codes.extend(['9050', '9210'])
        return None

    fake.get_balance.side_effect = rejected
    batches = fetch(fake, tmp_path)
    assert '9210' in batches[0].errors[0]
    assert 'Bank hat' in batches[0].errors[0]
    assert not batches[1].errors and batches[1].snapshots


def test_depot_processing_error_includes_safe_diagnostic(tmp_path):
    fake = FakeClient()
    fake.get_holdings.side_effect = TypeError('private-content')
    batch = fetch(fake, tmp_path)[1]
    assert 'Phase: Depotbestand abrufen' in batch.errors[0]
    assert 'TypeError' in batch.errors[0]
    assert 'private-content' not in str(batch)


def test_missing_upd_uses_sepa_discovery_and_refreshes_information(tmp_path):
    fake = FakeClient()
    information = fake.get_information()
    fake.get_information = Mock(side_effect=[{'accounts': []}, information])
    fake.get_sepa_accounts = Mock(return_value=fake.accounts)
    batches = fetch(fake, tmp_path)
    fake.get_sepa_accounts.assert_called_once()
    assert len(batches) == 2
    assert batches[0].balances and batches[1].snapshots


def test_upd_without_permissions_does_not_trigger_unapproved_requests(tmp_path):
    fake = FakeClient()
    fake.get_information = Mock(return_value={'accounts': [
        {'account_number': '1234567890', 'supported_operations': {}}]})
    fake.get_sepa_accounts = Mock()
    with pytest.raises(BankingError, match='keine Konten mit freigegebenem'):
        fetch(fake, tmp_path)
    fake.get_sepa_accounts.assert_not_called()
    fake.get_balance.assert_not_called()
    fake.get_holdings.assert_not_called()


def test_portal_pin_is_passed_unchanged(tmp_path):
    fake = FakeClient()
    factory = Mock(return_value=fake)
    fetch_baader('1234567', ' p ä ss ', 'product', source_root=tmp_path, client_factory=factory,
                today=date(2026, 9, 24))
    assert factory.call_args.args[:3] == ('1234567', ' p ä ss ', 'product')


@pytest.mark.parametrize('bank_text,confirmed', [
    ('FintsAuftrag abgelehnt-Kompetenz nicht ausreichend private-secret', True),
    ('FintsAuftrag aus technischen Gruenden abgelehnt private-secret', False),
])
def test_9210_explanation_uses_actual_reason_without_exposing_bank_text(bank_text, confirmed):
    import base64
    from portman.ing_banking import safe_diagnostic
    client = create_client('user', 'secret', 'product', lambda: False)
    payload = ("HIRMG:1:2+9050::Fehler'HIRMS:2:2:3+9210::" + bank_text + "'").encode()
    client.connection.session.post = Mock(return_value=SimpleNamespace(
        status_code=200, content=base64.b64encode(payload)))
    client.connection.send(SimpleNamespace(render_bytes=lambda: b'test'))
    message = safe_diagnostic(client, 'Kontenliste abrufen', ValueError('private-secret'))
    assert ('Die Bank meldet: Berechtigung' in message) == confirmed
    assert ('nicht eindeutig' in message) != confirmed
    assert 'private-secret' not in message
    client.connection.session.close()
