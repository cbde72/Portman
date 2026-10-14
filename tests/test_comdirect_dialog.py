import os
from unittest.mock import Mock

import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from portman.comdirect_credentials import ComdirectCredentialStore, CredentialError
from portman.ing_credentials import INGCredentialStore


class MemoryStore:
    fields = ComdirectCredentialStore.fields

    def __init__(self):
        self.saved = {}

    def load(self):
        return dict(self.saved)

    def save(self, *values):
        self.saved = dict(zip(self.fields, values))

    def delete(self):
        self.saved.clear()


def test_credential_namespace_and_validation(tmp_path, monkeypatch):
    store = ComdirectCredentialStore(tmp_path)
    api = Mock()
    monkeypatch.setattr(store, 'api', api)
    assert store.target != INGCredentialStore(tmp_path).target
    assert store.target != ComdirectCredentialStore(tmp_path / 'other').target
    with pytest.raises(CredentialError):
        store.save('user', 'pin', 'id', '')
    with pytest.raises(CredentialError):
        store.save('user', 'pin', 'id', 'x' * 3000)
    api.assert_not_called()


def test_dialog_masks_saves_loads_deletes_without_network(tmp_path):
    from PySide6.QtWidgets import QApplication, QLineEdit
    from portman.comdirect_dialog import ComdirectDialog
    QApplication.instance() or QApplication([])
    store = MemoryStore()
    dialog = ComdirectDialog(tmp_path, credential_store=store)
    assert dialog.pin.echoMode() == dialog.client_secret.echoMode() == QLineEdit.EchoMode.Password
    dialog.start_fetch()
    assert dialog.worker is None
    for field, value in zip(dialog.fields, ('user', ' p ä ss ', 'client', 'secret')):
        field.setText(value)
    assert dialog.save_credentials()
    assert dialog.worker is None
    assert dialog.remember.isChecked()
    dialog.reject()
    assert dialog.pin.text() == ' p ä ss ' and dialog.client_secret.text() == 'secret'
    another = ComdirectDialog(tmp_path, credential_store=store)
    if os.name == 'nt':
        assert another.pin.text() == ' p ä ss '
        assert another.client_secret.text() == 'secret'
    another.delete_credentials()
    assert not store.saved and not any(field.text() for field in another.fields)
    another.reject()
    assert not list(tmp_path.iterdir())


def test_storage_failure_prevents_login(tmp_path):
    from PySide6.QtWidgets import QApplication
    from portman.comdirect_dialog import ComdirectDialog
    QApplication.instance() or QApplication([])
    store = MemoryStore()
    store.save = Mock(side_effect=CredentialError('Speichern fehlgeschlagen'))
    dialog = ComdirectDialog(tmp_path, credential_store=store)
    for field in dialog.fields:
        field.setText('value')
    dialog.remember.setChecked(True)
    dialog.start_fetch()
    assert dialog.worker is None
    assert 'fehlgeschlagen' in dialog.status.text()
    dialog.reject()


def test_worker_cancellation_clears_credentials_and_keeps_dialog_alive(tmp_path, monkeypatch):
    from PySide6.QtCore import QEventLoop, QThread, QTimer
    from PySide6.QtWidgets import QApplication
    import portman.comdirect_dialog as ui
    app = QApplication.instance() or QApplication([])

    def fake_fetch(*args, **kwargs):
        while not kwargs['cancelled']():
            QThread.msleep(5)
        raise ui.Cancelled('Abbruch')

    monkeypatch.setattr(ui, 'fetch_comdirect', fake_fetch)
    dialog = ui.ComdirectDialog(tmp_path, credential_store=MemoryStore())
    for field in dialog.fields:
        field.setText('secret')
    dialog.start_fetch()
    assert dialog.pin.text() == 'secret' and dialog.client_secret.text() == 'secret'
    assert not dialog.fetch_button.isEnabled()
    dialog.reject()
    loop = QEventLoop()
    dialog.worker.finished.connect(loop.quit)
    QTimer.singleShot(5000, loop.quit)
    loop.exec()
    assert dialog.worker.wait(1000)
    app.processEvents()
    assert dialog.worker.credentials is None and dialog.worker.tan is None
    assert dialog.batches is None


def test_tan_callback_and_failure_allow_retry(tmp_path, monkeypatch):
    from PySide6.QtCore import QEventLoop, QTimer
    from PySide6.QtWidgets import QApplication
    import portman.comdirect_dialog as ui
    app = QApplication.instance() or QApplication([])
    received = []

    def fake_fetch(*args, **kwargs):
        received.append(kwargs['challenge']({'typ': 'M_TAN'}))
        raise ui.BankingError('Testfehler')

    monkeypatch.setattr(ui, 'fetch_comdirect', fake_fetch)
    monkeypatch.setattr(ui.TANDialog, 'exec', lambda self: (self.tan.setText('123456'), 1)[1])
    dialog = ui.ComdirectDialog(tmp_path, credential_store=MemoryStore())
    for field in dialog.fields:
        field.setText('secret')
    dialog.start_fetch()
    loop = QEventLoop()
    dialog.worker.finished.connect(loop.quit)
    QTimer.singleShot(5000, loop.quit)
    loop.exec()
    assert dialog.worker.wait(1000)
    app.processEvents()
    assert received == ['123456']
    assert dialog.worker.credentials is None and dialog.worker.tan is None
    assert dialog.fetch_button.isEnabled()
    assert dialog.status.text() == 'Testfehler'
    dialog.reject()
