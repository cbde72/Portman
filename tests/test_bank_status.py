import os

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from portman.ing_dialog import INGDialog
from portman.baader_dialog import BaaderDialog
from portman.comdirect_dialog import ComdirectDialog
from portman.bank_sync_dialog import BankSyncDialog


class EmptyStore:
    fields = ('user', 'pin', 'client_id', 'client_secret')

    def load(self):
        return {}


@pytest.mark.parametrize('dialog_type', [INGDialog, BaaderDialog, ComdirectDialog])
def test_copy_current_message_without_credentials(tmp_path, dialog_type):
    app = QApplication.instance() or QApplication([])
    dialog = dialog_type(tmp_path, credential_store=EmptyStore())
    dialog.user.setText('private-user')
    dialog.pin.setText('private-pin')
    message = 'Phase: FinTS-Anmeldung.\nBankcodes: 3060, 3076, 3920, 9050, 9210.'
    dialog.status.setText(message)
    assert dialog.status.textInteractionFlags() & Qt.TextInteractionFlag.TextSelectableByMouse
    dialog.copy_message.click()
    assert app.clipboard().text() == message
    dialog.status.setText('Neue Meldung')
    dialog.copy_message.click()
    assert app.clipboard().text() == 'Neue Meldung'
    dialog.reject()
    app.clipboard().clear()


def test_copy_all_sync_messages(tmp_path):
    app = QApplication.instance() or QApplication([])
    dialog = BankSyncDialog(tmp_path)
    dialog.status.setText('Abruf abgeschlossen')
    dialog.record('ING: Abgerufen')
    dialog.record('Baader: Bankcode 9210')
    dialog.copy_message.click()
    assert app.clipboard().text() == 'Abruf abgeschlossen\n\nING: Abgerufen\nBaader: Bankcode 9210\n'
    dialog.reject()  # Prevent the queued automatic start from running.
    app.processEvents()
    app.clipboard().clear()
