import os
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from portman.ing_credentials import INGCredentialStore, CredentialError


class MemoryStore:
    def __init__(self):
        self.saved = {}

    def load(self):
        return dict(self.saved)

    def save(self, user, pin, product_id):
        self.saved = dict(user=user, pin=pin, product_id=product_id)

    def delete(self):
        self.saved = {}


def test_save_reload_and_delete_without_bank_request(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication, QLineEdit
    from portman.ing_dialog import INGDialog
    QApplication.instance() or QApplication([])
    store = MemoryStore()
    dialog = INGDialog(tmp_path, credential_store=store)
    dialog.user.setText('Testuser')
    dialog.pin.setText(' p ä ss ')
    dialog.product.setText('Testprodukt')
    assert dialog.save_credentials()
    assert dialog.worker is None
    assert dialog.remember.isChecked()
    dialog.reject()
    assert dialog.pin.text() == ' p ä ss '
    next_dialog = INGDialog(tmp_path, credential_store=store)
    assert next_dialog.user.text() == 'Testuser'
    assert next_dialog.pin.text() == ' p ä ss '
    assert next_dialog.product.text() == 'Testprodukt'
    assert next_dialog.pin.echoMode() == QLineEdit.EchoMode.Password
    next_dialog.delete_credentials()
    assert not store.saved
    assert not next_dialog.pin.text() and not next_dialog.user.text() and not next_dialog.product.text()
    assert list(tmp_path.iterdir()) == []
    next_dialog.reject()


def test_save_failure_prevents_bank_fetch(tmp_path):
    from PySide6.QtWidgets import QApplication
    from portman.ing_dialog import INGDialog
    QApplication.instance() or QApplication([])
    store = Mock()
    store.load.return_value = {}
    store.save.side_effect = CredentialError('Speichern fehlgeschlagen')
    dialog = INGDialog(tmp_path, credential_store=store)
    dialog.user.setText('user')
    dialog.pin.setText('secret')
    dialog.product.setText('id')
    dialog.start_fetch()
    assert dialog.worker is None
    assert 'Speichern fehlgeschlagen' in dialog.status.text()
    dialog.reject()


def test_credential_validation_before_windows_write(tmp_path, monkeypatch):
    store = INGCredentialStore(tmp_path)
    api = Mock()
    monkeypatch.setattr(store, 'api', api)
    with pytest.raises(CredentialError):
        store.save('user', '', 'id')
    with pytest.raises(CredentialError):
        store.save('user', 'x' * 3000, 'id')
    api.assert_not_called()
    assert store.target != INGCredentialStore(tmp_path / 'other').target


def test_vscode_launch_uses_existing_entrypoint_and_virtualenv():
    root = Path(__file__).resolve().parents[1]
    config = json.loads((root / '.vscode' / 'launch.json').read_text())['configurations'][0]
    resolve = lambda value: Path(value.replace('${workspaceFolder}', str(root)))
    assert config['type'] == 'debugpy'
    assert resolve(config['program']).is_file()
    assert resolve(config['python']).is_file()
    assert config['name'] == 'PortMan 09 starten'
    assert resolve(config['program']) == root / 'src' / 'Gui' / 'PortMan_V09.py'
    assert resolve(config['cwd']) == root
    assert not any(key in config['env'] for key in ('ING_PIN', 'ING_USER_ID', 'FINTS_PRODUCT_ID'))
