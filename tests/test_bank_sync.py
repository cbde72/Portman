import os

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import QEventLoop, QThread, QTimer
from PySide6.QtWidgets import QApplication, QDialogButtonBox
from portman import bank_sync_dialog as ui
from portman import ing_dialog, comdirect_dialog, baader_dialog, renault_dialog
from portman.bank_history_range import ALL_HISTORY_START


def run_until(app, predicate):
    loop = QEventLoop()
    timer = QTimer()
    timer.timeout.connect(lambda: loop.quit() if predicate() else None)
    timer.start(5)
    QTimer.singleShot(5000, loop.quit)
    loop.exec()
    timer.stop()
    app.processEvents()
    assert predicate()


def saved_logins(monkeypatch):
    monkeypatch.setattr(ui.INGCredentialStore, 'load', lambda self: dict.fromkeys(self.fields, 'test'))
    monkeypatch.setattr(ui.BaaderCredentialStore, 'load', lambda self: {})
    monkeypatch.setattr(ui.RenaultCredentialStore, 'load', lambda self: {})


def test_all_banks_are_collected_and_tan_is_supported(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    saved_logins(monkeypatch)
    calls = []

    def ing(*args, **options):
        calls.append('ING')
        assert options['history_start'] == ALL_HISTORY_START
        assert options['fetch_documents']
        return ['ing batch']

    def comdirect(*args, **options):
        calls.append('comdirect')
        assert options['history_start'] == ALL_HISTORY_START
        assert options['challenge']({'typ': 'M_TAN'}) == '123456'
        return ['comdirect batch']

    def baader(*args, **options):
        calls.append('Baader')
        assert options['history_start'] == ALL_HISTORY_START
        assert options['challenge']('SMS-TAN eingeben') == '654321'
        assert not options['fetch_documents']
        return ['baader batch']

    def renault(*args, **options):
        calls.append('Renault Bank direkt')
        assert options['history_start'] == ALL_HISTORY_START
        assert options['challenge']('SecureGo+ TAN eingeben') == '456789'
        assert not options['fetch_documents']
        return ['renault batch']

    monkeypatch.setattr(ing_dialog, 'fetch_ing', ing)
    monkeypatch.setattr(comdirect_dialog, 'fetch_comdirect', comdirect)
    monkeypatch.setattr(ui.BaaderCredentialStore, 'load', lambda self: dict.fromkeys(self.fields, 'test'))
    monkeypatch.setattr(baader_dialog, 'fetch_baader', baader)
    monkeypatch.setattr(ui.BaaderTANDialog, 'exec', lambda self: (self.tan.setText('654321'), 1)[1])
    monkeypatch.setattr(ui.RenaultCredentialStore, 'load', lambda self: dict.fromkeys(self.fields, 'test'))
    monkeypatch.setattr(renault_dialog, 'fetch_renault', renault)
    monkeypatch.setattr(ui.RenaultTANDialog, 'exec', lambda self: (self.tan.setText('456789'), 1)[1])
    monkeypatch.setattr(ui.TANDialog, 'exec', lambda self: (self.tan.setText('123456'), 1)[1])
    dialog = ui.BankSyncDialog(tmp_path)
    run_until(app, lambda: dialog.buttons.button(QDialogButtonBox.StandardButton.Ok).isEnabled())
    assert calls == ['ING', 'comdirect', 'Baader', 'Renault Bank direkt']
    assert dialog.results == [('ING', ['ing batch']), ('comdirect', ['comdirect batch']),
                              ('Baader', ['baader batch']), ('Renault Bank direkt', ['renault batch'])]
    assert dialog.progress.value() == 4
    dialog.accept()
    assert dialog.result() == 1


def test_bank_failure_does_not_block_next_bank(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    saved_logins(monkeypatch)

    def fail(*args, **kwargs):
        raise ing_dialog.BankingError('Testfehler')

    monkeypatch.setattr(ing_dialog, 'fetch_ing', fail)
    monkeypatch.setattr(comdirect_dialog, 'fetch_comdirect', lambda *a, **kw: ['batch'])
    dialog = ui.BankSyncDialog(tmp_path)
    run_until(app, lambda: dialog.progress.value() == 4)
    assert dialog.results == [('comdirect', ['batch'])]
    assert 'Testfehler' in dialog.log.toPlainText()
    dialog.reject()


def test_missing_and_unreadable_credentials(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(ui.INGCredentialStore, 'load', lambda self: {})

    def fail(self):
        raise ui.CredentialError('Nicht lesbar')

    monkeypatch.setattr(ui.ComdirectCredentialStore, 'load', fail)
    dialog = ui.BankSyncDialog(tmp_path)
    run_until(app, lambda: dialog.progress.value() == 4)
    assert dialog.worker is None and dialog.results == []
    assert not dialog.buttons.button(QDialogButtonBox.StandardButton.Ok).isEnabled()
    assert 'Übersprungen' in dialog.log.toPlainText()
    assert 'Nicht lesbar' in dialog.log.toPlainText()
    dialog.reject()


def test_cancel_stops_queue_and_discards_results(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    saved_logins(monkeypatch)
    calls = []

    def ing(*args, **options):
        while not options['cancelled']():
            QThread.msleep(5)
        raise ing_dialog.Cancelled('Abbruch')

    monkeypatch.setattr(ing_dialog, 'fetch_ing', ing)
    monkeypatch.setattr(comdirect_dialog, 'fetch_comdirect', lambda *a, **kw: calls.append('unexpected'))
    dialog = ui.BankSyncDialog(tmp_path)
    run_until(app, lambda: dialog.worker is not None)
    worker = dialog.worker
    dialog.reject()
    run_until(app, lambda: not worker.isRunning())
    assert worker.credentials is None
    assert not calls and not dialog.results and not dialog.pending
    assert dialog.result() == 0


def test_successful_sync_can_continue_automatically(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    saved_logins(monkeypatch)
    monkeypatch.setattr(ui.ComdirectCredentialStore, 'load', lambda self: {})
    monkeypatch.setattr(ing_dialog, 'fetch_ing', lambda *a, **kw: ['batch'])
    dialog = ui.BankSyncDialog(tmp_path, auto_continue=True)
    run_until(app, lambda: dialog.result() == 1)
    assert dialog.results == [('ING', ['batch'])]


def test_failed_sync_continues_without_confirmation(tmp_path, monkeypatch):
    from portfolio_v5.models import ImportBatch
    app = QApplication.instance() or QApplication([])
    saved_logins(monkeypatch)
    monkeypatch.setattr(ui.ComdirectCredentialStore, 'load', lambda self: {})
    monkeypatch.setattr(ing_dialog, 'fetch_ing', lambda *a, **kw: [ImportBatch('test', 'hash', errors=['Fehler'])])
    dialog = ui.BankSyncDialog(tmp_path, auto_continue=True)
    run_until(app, lambda: dialog.progress.value() == 4)
    assert dialog.result() == 1
    assert dialog.has_errors
    assert 'Fehler' in dialog.log.toPlainText()
