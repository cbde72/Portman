from datetime import date
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from test_ing_banking import FakeClient
from test_baader_banking import challenge
from test_ing_history import transaction
from test_bank_sync import run_until
from test_baader_dialog import MemoryStore
from fints.client import FinTSOperations as Op
from portman import renault_dialog as ui
from portman.renault_banking import fetch_renault, create_client, ENDPOINT, BankingError
from portman.renault_credentials import RenaultCredentialStore
from portman.baader_credentials import BaaderCredentialStore
from portman.repository import PortfolioRepository


def client():
    fake = FakeClient()
    fake.get_information = Mock(return_value={'accounts': [
        {'account_number': '1111111111', 'iban': 'DEFAKE',
         'supported_operations': {Op.GET_BALANCE: True, Op.GET_TRANSACTIONS: True}},
    ]})
    fake.get_sepa_accounts = Mock(return_value=[])
    fake.get_transactions = Mock(return_value=[transaction()])
    return fake


def fetch(fake, tmp_path, **kwargs):
    return fetch_renault('user', 'secret', 'product', source_root=tmp_path,
        client_factory=lambda *a: fake, today=date(2026, 9, 24), **kwargs)


def test_renault_balance_history_tan_and_identity(tmp_path):
    fake = client()
    fake.init_tan_response = challenge()
    fake.send_tan = Mock(return_value=None)
    answer = Mock(return_value='123456')
    batches = fetch(fake, tmp_path, challenge=answer, history_start=date(2026, 9, 1))
    assert len(batches) == 2 and not any(b.errors for b in batches)
    assert all(b.source_sheet == 'Online Renault Bank direkt' for b in batches)
    assert batches[1].transactions[0].external_id.startswith('renault-booking-')
    account = fake.get_balance.call_args.args[0]
    assert account.bic == 'RCIDDE3NPAY' and account.blz == '30520037'
    assert batches[0].balances[0].account == 'Renault Bank direkt Konto 1111111111'
    answer.assert_called_once()
    assert fake.pin is None
    assert RenaultCredentialStore(tmp_path).target != BaaderCredentialStore(tmp_path).target


def test_renault_endpoint_and_http_safety():
    c = create_client('user', 'secret', 'product', lambda: False)
    c.connection.session.post = Mock(return_value=SimpleNamespace(status_code=302))
    with pytest.raises(BankingError):
        c.connection.send(SimpleNamespace(render_bytes=lambda: b'test'))
    call = c.connection.session.post.call_args
    assert call.args == (ENDPOINT,)
    assert call.kwargs['allow_redirects'] is False
    assert call.kwargs['timeout'] == (10, 30)
    c.connection.session.close()


def test_refresh_replaces_only_target_balance_and_is_idempotent(tmp_path):
    from portfolio_v5.models import ImportBatch, Balance
    repo = PortfolioRepository(tmp_path / 'test.sqlite')
    source = 'Renault Bank direkt Konto 1111111111'
    repo.commit_batches([ImportBatch('overview.xlsx', 'old', balances=[
        Balance('2026-09', 'Liquidität', source, '100', 'Overview', 1),
        Balance('2026-09', 'Liquidität', 'Andere Bank', '200', 'Overview', 2)])])
    batch = fetch(client(), tmp_path)[0]
    result = repo.commit_batches([batch])[0]
    assert result['status'] == 'imported'
    assert {b['value'] for b in repo.balances()} == {'-12.34', '200'}
    assert repo.commit_batches([batch])[0]['status'] == 'duplicate'
    repo.undo_import(result['id'])
    assert {b['value'] for b in repo.balances()} == {'100', '200'}
    repo.close()


@pytest.mark.parametrize('accepted', [True, False])
def test_dialog_tan_completion_or_cancel(tmp_path, monkeypatch, accepted):
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    received = []

    def fake_fetch(*args, **options):
        received.append(options['challenge']('SecureGo+ TAN'))
        return ['batch']

    monkeypatch.setattr(ui, 'fetch_renault', fake_fetch)
    monkeypatch.setattr(ui.RenaultTANDialog, 'exec', lambda self: (self.tan.setText('123456'), int(accepted))[1])
    dialog = ui.RenaultDialog(tmp_path, credential_store=MemoryStore())
    for field in (dialog.user, dialog.pin, dialog.product):
        field.setText('test')
    dialog.start_fetch()
    run_until(app, lambda: not dialog.worker.isRunning())
    assert dialog.worker.credentials is None and dialog.worker.tan is None
    assert received == (['123456'] if accepted else [])
    assert dialog.batches == (['batch'] if accepted else None)
    assert dialog.documents.isHidden()
    dialog.reject()
