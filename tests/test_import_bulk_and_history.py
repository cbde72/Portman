import os
from datetime import date
from types import SimpleNamespace
from unittest.mock import Mock

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest
from PySide6.QtWidgets import QApplication, QComboBox, QDialog, QLineEdit, QMessageBox, QTableWidget
from portfolio_v5.models import ImportBatch, BankTransaction
from portman.repository import PortfolioRepository
from portman.bank_history_range import ALL_HISTORY_START, last_history_date, history_start_editor
from portman.import_conflict_actions import copy_first_decision, copy_first_reason, ask_conflict_policy


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


def conflict_widgets():
    table = QTableWidget(4, 2)
    for row in range(4):
        combo = QComboBox()
        for label, value in [('Offen', None), ('Behalten', 'keep'), ('Überspringen', 'skip')]:
            combo.addItem(label, value)
        if row != 3:
            combo.addItem('Ersetzen', 'replace')
        table.setCellWidget(row, 0, combo)
        table.setCellWidget(row, 1, QLineEdit())
    return SimpleNamespace(conflict_table=table)


def test_bulk_preserves_decisions_and_reasons(app):
    wizard = conflict_widgets()
    table = wizard.conflict_table
    table.cellWidget(0, 0).setCurrentIndex(3)
    table.cellWidget(0, 1).setText('Neuer Beleg vollständig')
    table.cellWidget(2, 0).setCurrentIndex(2)
    table.cellWidget(2, 1).setText('Eigene Begründung')
    copy_first_decision(wizard)
    copy_first_reason(wizard)
    assert [table.cellWidget(i, 0).currentData() for i in range(4)] == ['replace', 'replace', 'skip', None]
    assert table.cellWidget(1, 1).text() == 'Neuer Beleg vollständig'
    assert table.cellWidget(2, 1).text() == 'Eigene Begründung'
    assert table.cellWidget(3, 1).text() == ''
    table.cellWidget(1, 1).setText('Individuell')
    copy_first_reason(wizard)
    assert table.cellWidget(1, 1).text() == 'Individuell'


@pytest.mark.parametrize('label, expected', [('Alte durch neue ersetzen', 'replace'),
    ('Alle alten behalten', 'skip'), ('Einzeln entscheiden', None)])
def test_initial_conflict_policy(app, monkeypatch, label, expected):
    wizard = QDialog()
    wizard.conflict_table = conflict_widgets().conflict_table
    wizard.conflict_table.cellWidget(1, 0).setCurrentIndex(1)
    monkeypatch.setattr(QMessageBox, 'exec', lambda self: 0)
    monkeypatch.setattr(QMessageBox, 'clickedButton', lambda self: next(b for b in self.buttons() if b.text() == label))
    ask_conflict_policy(wizard)
    assert wizard.conflict_table.cellWidget(0, 0).currentData() == expected
    assert wizard.conflict_table.cellWidget(1, 0).currentData() == 'keep'


def test_last_history_is_committed_bank_specific_and_undoable(tmp_path, app):
    repo = PortfolioRepository(tmp_path / 'test.sqlite')
    try:
        assert last_history_date(repo, 'comdirect') == ALL_HISTORY_START
        def batch(path, bank, end):
            return ImportBatch(path, path + end, source_sheet='Online ' + bank,
                transactions=[BankTransaction(bank, path + end, end, 'BANK_BOOKING', '1', 'EUR')],
                warnings=[f'Zeitraum: gesamte verfügbare Historie bis {end}. Nur verfügbare Buchungen.'])
        first = batch('account-a.bank', 'comdirect', '2026-09-10')
        repo.commit_batches([first, batch('ing.bank', 'ING', '2026-09-20')])
        assert last_history_date(repo, 'comdirect') == date(2026, 9, 10)
        newer = batch('account-a.bank', 'comdirect', '2026-09-25')
        newer.warnings = []
        newer.history_end = '2026-09-25'
        newer.transactions[0].date = '2026-09-22'
        assert last_history_date(repo, 'comdirect') == date(2026, 9, 10)
        result = repo.commit_batches([newer])[0]
        assert history_start_editor(repo, 'comdirect').date().toPython() == date(2026, 9, 22)
        repo.undo_import(result['id'])
        assert last_history_date(repo, 'comdirect') == date(2026, 9, 10)
        repo.commit_batches([batch('account-b.bank', 'comdirect', '2026-09-05')])
        assert last_history_date(repo, 'comdirect') == date(2026, 9, 10)
    finally:
        repo.close()


def test_online_dialog_and_sync_use_saved_start(tmp_path, app, monkeypatch):
    from PySide6.QtWidgets import QWidget
    from portman.comdirect_dialog import ComdirectDialog
    from portman import bank_sync_dialog as sync
    repo = PortfolioRepository(tmp_path / 'test.sqlite')
    parent = QWidget()
    parent.repository = repo
    try:
        repo.commit_batches([ImportBatch('comdirect.bank', 'hash', source_sheet='Online comdirect',
            history_end='2026-09-25', transactions=[BankTransaction('comdirect', 'id',
                '2026-09-25', 'BANK_BOOKING', '1', 'EUR')])])
        store = Mock(load=lambda: {}, fields=('user', 'pin', 'client_id', 'client_secret'))
        dialog = ComdirectDialog(tmp_path, parent, credential_store=store)
        assert dialog.history_start.date().toPython() == date(2026, 9, 25)
        dialog.reject()
        monkeypatch.setattr(sync.QTimer, 'singleShot', lambda *args: None)
        monkeypatch.setattr(sync.ComdirectCredentialStore, 'load', lambda self: dict.fromkeys(self.fields, 'test'))
        worker = Mock()
        factory = Mock(return_value=worker)
        monkeypatch.setattr(sync, 'ComdirectWorker', factory)
        dialog = sync.BankSyncDialog(tmp_path, parent)
        dialog.pending = [('comdirect', sync.ComdirectCredentialStore)]
        dialog.start_next()
        assert factory.call_args.kwargs['history_start'] == date(2026, 9, 25)
        assert factory.call_args.kwargs['history_end'] == date.today()
        dialog.worker = None
        dialog.reject()
    finally:
        parent.deleteLater()
        repo.close()
