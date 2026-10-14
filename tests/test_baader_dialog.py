import pytest
from PySide6.QtWidgets import QApplication, QLineEdit, QTabWidget

from test_bank_sync import run_until
from test_ing_banking import FakeClient, RAW
from test_baader_banking import fetch
from portman import baader_dialog as ui
from portman.ing_credentials import CredentialError


class MemoryStore:
    def __init__(self):
        self.saved = {}

    def load(self):
        return dict(self.saved)

    def save(self, user, pin, product_id):
        self.saved = dict(user=user, pin=pin, product_id=product_id)

    def delete(self):
        self.saved.clear()


def test_login_dialog_and_storage(tmp_path):
    QApplication.instance() or QApplication([])
    store = MemoryStore()
    dialog = ui.BaaderDialog(tmp_path, credential_store=store)
    dialog.start_fetch()
    assert dialog.worker is None
    assert dialog.pin.echoMode() == QLineEdit.EchoMode.Password
    assert dialog.documents.isHidden() and not dialog.documents.isChecked()
    for field, value in zip((dialog.user, dialog.pin, dialog.product), ('user', 'secret', 'product')):
        field.setText(value)
    assert dialog.save_credentials()
    dialog.reject()
    assert dialog.pin.text() == 'secret'
    restored = ui.BaaderDialog(tmp_path, credential_store=store)
    assert restored.pin.text() == 'secret'
    restored.delete_credentials()
    assert store.saved == {} and not restored.user.text()
    restored.reject()


@pytest.mark.parametrize('accept_tan', [True, False])
def test_worker_tan_success_and_rejection(tmp_path, monkeypatch, accept_tan):
    app = QApplication.instance() or QApplication([])
    received = []

    def fake_fetch(*args, **options):
        received.append(options['challenge']('SMS-TAN eingeben'))
        return ['batch']

    monkeypatch.setattr(ui, 'fetch_baader', fake_fetch)
    monkeypatch.setattr(ui.BaaderTANDialog, 'exec',
        lambda self: (self.tan.setText('123456'), int(accept_tan))[1])
    dialog = ui.BaaderDialog(tmp_path, credential_store=MemoryStore())
    for field in (dialog.user, dialog.pin, dialog.product):
        field.setText('test')
    dialog.start_fetch()
    assert dialog.pin.text() == 'test'
    run_until(app, lambda: not dialog.worker.isRunning())
    assert dialog.worker.credentials is None and dialog.worker.tan is None
    if accept_tan:
        assert dialog.batches == ['batch'] and received == ['123456']
        assert dialog.result() == 1
    else:
        assert dialog.batches is None and received == []
        assert dialog.fetch_button.isEnabled()
        assert 'abgebrochen' in dialog.status.text()
    dialog.reject()


def test_cancel_while_waiting_for_tan(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(ui, 'fetch_baader', lambda *a, **kw: kw['challenge']('SMS-TAN'))
    dialog = ui.BaaderDialog(tmp_path, credential_store=MemoryStore())
    # Leave the worker waiting without opening a modal dialog.
    monkeypatch.setattr(dialog, 'show_challenge', lambda message: None)
    for field in (dialog.user, dialog.pin, dialog.product):
        field.setText('test')
    dialog.start_fetch()
    dialog.reject()
    run_until(app, lambda: not dialog.worker.isRunning())
    assert dialog.batches is None and dialog.worker.credentials is None
    assert dialog.result() == 0


def test_failed_credential_save_prevents_fetch(tmp_path):
    QApplication.instance() or QApplication([])
    store = MemoryStore()

    def fail(*args):
        raise CredentialError('Speichern fehlgeschlagen')

    store.save = fail
    dialog = ui.BaaderDialog(tmp_path, credential_store=store)
    for field in (dialog.user, dialog.pin, dialog.product):
        field.setText('test')
    dialog.start_fetch()
    assert dialog.worker is None
    assert 'fehlgeschlagen' in dialog.status.text()
    dialog.reject()


def test_missing_product_and_iban_instead_of_user_are_explained(tmp_path):
    QApplication.instance() or QApplication([])
    dialog = ui.BaaderDialog(tmp_path, credential_store=MemoryStore())
    dialog.user.setText('1234567')
    dialog.pin.setText('test')
    dialog.product.clear()
    dialog.start_fetch()
    assert dialog.worker is None
    assert 'FinTS-Produkt-ID für Portman fehlt' in dialog.status.text()
    dialog.user.setText('DE00 7003 3100 0000 0000 00')
    dialog.product.setText('product')
    dialog.start_fetch()
    assert dialog.worker is None
    assert 'IBAN' in dialog.status.text()
    assert not dialog.credential_store.saved
    dialog.reject()


def test_zero_history_continues_and_crypto_is_preserved(tmp_path):
    from portfolio_v5.models import ImportBatch, Snapshot, Position
    from portman.ing_banking import parse_holdings
    from portman.ing_dialog import INGDepotDialog
    from portman.import_preview import ImportPreviewDialog
    from portman.repository import PortfolioRepository
    QApplication.instance() or QApplication([])
    repo = PortfolioRepository(tmp_path / 'test.sqlite')
    repo.commit_batches([
        ImportBatch('ZERO-pos.csv', 'old', snapshots=[Snapshot('ZERO', '2026-09', '2026-09-01', 'CSV', parse_holdings(RAW))]),
        ImportBatch('crypto.csv', 'crypto', snapshots=[Snapshot('ZERO/Krypto', '2026-09', '2026-09-01', 'CSV',
            [Position('BTC', 'Bitcoin', asset_type='Krypto', quantity='1', value='100')])])])
    batches = fetch(FakeClient(), tmp_path)
    dialog = INGDepotDialog(repo, batches, bank='Baader')
    batch, combo = dialog.choices[0]
    assert combo.findData('ZERO/Krypto') == -1
    combo.setCurrentIndex(combo.findData('ZERO'))
    dialog.accept()
    repo.commit_batches([batch])
    assert len(repo.holdings()) == 2
    assert next(p for p in repo.holdings() if p['depot'] == 'ZERO')['as_of'] == '2026-09-24'
    assert repo.previous_bank_depot(batch.path) == 'ZERO'
    preview = ImportPreviewDialog(repo, batches)
    tabs = preview.findChild(QTabWidget)
    assert any(tabs.tabText(i) == 'Baader · Abrufdetails' for i in range(tabs.count()))
    preview.reject()
    repo.close()
