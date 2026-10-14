import os

import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from portfolio_v5.models import ImportBatch, BankTransaction
from portfolio_v5.pdf_importer import analyse_pages
from portfolio_v5.pdf_bookings import parse_bookings
from portman.repository import PortfolioRepository
from portman.renault_pdf_import import import_renault_batches
from portman.renault_pdf_import import is_renault_statement


@pytest.mark.parametrize('bic', ['RCIDDE3NPAY', 'RCIDDE3NXXX', 'RCIDDE3N'])
def test_bank_identified_by_header_bic_without_text_logo(tmp_path, bic):
    repo = PortfolioRepository(tmp_path / 'test.sqlite')
    repo.save_account('Renault', {'number': '12345678'})
    batch = statement()
    batch.pdf_text = batch.pdf_text.replace('Renault Bank direkt', 'BIC: ' + bic)
    result = import_renault_batches(repo, [batch])[0]
    assert result['status'] == 'imported', result
    assert len(repo.transactions()) == 1
    repo.close()


def test_counterparty_bic_does_not_identify_statement_bank():
    assert not is_renault_statement('Andere Bank\nBIC: OTHERBIC\nBu-Tag Wert Vorgang\n'
        '01.09. Überweisung 25,00 H\nBIC: RCIDDE3NPAY')
    assert not is_renault_statement('BIC: RCIDDE3NPAYMORE\nBu-Tag Wert Vorgang')


def statement(amount='25,00', closing='125,00'):
    text = ('Renault Bank direkt\nKontoauszug\nKonto: 12345678\nEUR\nBu-Tag Wert Vorgang\n'
            'alter Kontostand vom 31.08.2026 100,00 H\n'
            f'01.09. 01.09. Überweisung {amount} H\n'
            f'neuer Kontostand vom 30.09.2026 {closing} H')
    transactions, _, evidence = parse_bookings([text], analyse_pages)
    return ImportBatch('renault.pdf', 'hash', source_sheet='PDF', document_type='Kontoauszug',
        transactions=transactions, pdf_booking_evidence=evidence, pdf_text='--- Seite 1 ---\n' + text)


@pytest.mark.parametrize('version', ['base', 'v09'])
def test_replaces_period_and_repeat_without_duplicates_and_undo(tmp_path, version):
    from portman.repository_v09 import RepositoryV09
    repo = (RepositoryV09 if version == 'v09' else PortfolioRepository)(tmp_path / 'test.sqlite')
    repo.save_account('Renault', {'number': '12345678'})
    repo.save_account('Other', {})
    original = ImportBatch('online', 'original', transactions=[
        BankTransaction('Renault', 'old', '2026-09-01', 'BANK_BOOKING', '20', 'EUR'),
        BankTransaction('Renault', 'outside', '2026-08-01', 'BANK_BOOKING', '7', 'EUR'),
        BankTransaction('Other', 'other', '2026-09-01', 'BANK_BOOKING', '3', 'EUR')])
    repo.commit_batches([original])
    for batch in (statement(), statement(), statement('30,00', '130,00')):
        result = import_renault_batches(repo, [batch])[0]
        assert result['status'] == 'imported', result
        assert len(repo.transactions()) == 3
    assert next(t for t in repo.transactions('Renault') if t['date'] == '2026-09-01')['amount'] == '30.00'
    repo.store.undo_import(result['id'])
    assert next(t for t in repo.transactions('Renault') if t['date'] == '2026-09-01')['amount'] == '25.00'
    repo.close()


def test_unclear_account_or_unbalanced_statement_does_not_write(tmp_path):
    repo = PortfolioRepository(tmp_path / 'test.sqlite')
    assert import_renault_batches(repo, [statement()])[0]['status'] == 'error'
    repo.save_account('Renault', {'number': '12345678'})
    assert import_renault_batches(repo, [statement(closing='999,00')])[0]['status'] == 'error'
    assert not repo.imports()
    repo.close()


def test_reviewed_corrections_use_manual_account_and_recheck_balance(tmp_path):
    from portman.renault_pdf_import import prepare_renault_batch
    repo = PortfolioRepository(tmp_path / 'correct.sqlite')
    repo.save_account('Manuell', {})
    batch = statement()
    batch.pdf_text = batch.pdf_text.replace('01.09. 01.09.', '01.09. 30.02.')
    batch.pdf_reviewed = True
    batch.account_assignments = {'konto 12345678': 'manuell'}
    prepared = prepare_renault_batch(repo, batch)
    assert prepared.account_assignments == {'konto 12345678': 'manuell'}
    batch.transactions[0].amount = '30.00'
    with pytest.raises(ValueError, match='abgestimmt'):
        prepare_renault_batch(repo, batch)
    assert not repo.imports()
    repo.close()


def test_invalid_value_date_keeps_balanced_statement(tmp_path):
    from portman.renault_pdf_import import prepare_renault_batch
    repo = PortfolioRepository(tmp_path / 'value-date.sqlite')
    repo.save_account('Renault', {'number': '12345678'})
    batch = statement()
    batch.pdf_text = batch.pdf_text.replace('01.09. 01.09.', '01.09. 30.02.')
    batch.transactions[0].value_date = ''
    prepared = prepare_renault_batch(repo, batch)
    assert prepared.transactions[0].value_date == ''
    assert prepared.transactions[0].amount == '25.00'
    assert import_renault_batches(repo, [batch])[0]['status'] == 'imported'
    assert len(repo.transactions()) == 1
    repo.close()


def test_preview_correction_keeps_source_unchanged(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication
    from portman.renault_pdf_preview import RenaultPdfPreviewDialog
    from portman.import_preview import ImportPreviewDialog
    from copy import deepcopy
    QApplication.instance() or QApplication([])
    repo = PortfolioRepository(tmp_path / 'edit.sqlite')
    repo.save_account('Renault', {'number': '12345678'})
    original = statement()
    corrected = deepcopy(original)
    corrected.transactions[0].purpose = 'Korrigierter Text'
    corrected.account_assignments = {'konto 12345678': 'renault'}
    monkeypatch.setattr(ImportPreviewDialog, 'exec', lambda self: 1)
    monkeypatch.setattr(ImportPreviewDialog, 'selected_batches', lambda self: [corrected])
    preview = RenaultPdfPreviewDialog(repo, [original])
    preview.correct_file()
    assert preview.selected_batches()[0].transactions[0].purpose == 'Korrigierter Text'
    assert original.transactions[0].purpose == 'Überweisung'
    assert not repo.imports()
    preview.reject()
    repo.close()


def test_archive_search_all_accounts_and_dates(tmp_path):
    from PySide6.QtWidgets import QApplication
    from portman.bank_archive import BankArchiveWidget
    QApplication.instance() or QApplication([])
    repo = PortfolioRepository(tmp_path / 'test.sqlite')
    repo.commit_batches([ImportBatch('source', 'hash', transactions=[
        BankTransaction('A', str(i), '2026-01-01', 'BANK_BOOKING', str(i), 'EUR', purpose=f'Überweisung {i}')
        for i in range(350)])])
    widget = BankArchiveWidget(repo, lambda: 'Other')
    assert widget.bookings.rowCount() == 350
    widget.search.setText('Überweisung 349')
    assert widget.bookings.rowCount() == 1
    widget.search.clear()
    assert widget.bookings.rowCount() == 350
    widget.all_accounts.setChecked(False)
    assert widget.bookings.rowCount() == 0
    widget.close()
    repo.close()


def test_preview_is_read_only_shows_replacements_and_supports_selection(tmp_path):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QDialogButtonBox
    from portman.renault_pdf_preview import RenaultPdfPreviewDialog
    QApplication.instance() or QApplication([])
    repo = PortfolioRepository(tmp_path / 'preview.sqlite')
    repo.save_account('Renault', {'number': '12345678'})
    repo.commit_batches([ImportBatch('online', 'old', transactions=[
        BankTransaction('Renault', 'old', '2026-09-01', 'BANK_BOOKING', '20', 'EUR', purpose='Bisherige Buchung')])])
    before = repo.transactions()
    dialog = RenaultPdfPreviewDialog(repo, [statement(), statement(closing='999,00')])
    assert len(dialog.selected_batches()) == 1
    assert dialog.files.item(0, 3).text() == 'Renault'
    assert dialog.files.item(0, 7).text() == '1'
    assert dialog.bookings.item(0, 3).text() == '25,00'
    assert dialog.replacements.item(0, 5).text() == 'Bisherige Buchung'
    dialog.search.setText('keine passende Buchung')
    assert dialog.bookings.isRowHidden(0)
    dialog.search.clear()
    assert not dialog.bookings.isRowHidden(0)
    dialog.files.item(0, 0).setCheckState(Qt.CheckState.Unchecked)
    assert not dialog.selected_batches()
    assert not dialog.buttons.button(QDialogButtonBox.StandardButton.Ok).isEnabled()
    dialog.files.selectRow(1)
    assert 'Prüfung' in dialog.status.text()
    assert dialog.bookings.rowCount() == 1
    dialog.reject()
    assert repo.transactions() == before
    assert len(repo.imports()) == 1
    dialog.close()
    repo.close()



def legacy_statement(value_date='30.02.', closing='25.023,87'):
    text = f'''Renault Bank direkt
KONTOAUSZUG Nr. 2/2016
Kontonummer: 123 456 789
erstellt am 29.02.2016
DATUM   BUCHUNGSVORGANG                                    SOLL      HABEN
        ALTER KONTOSTAND VOM 29.01.2016 IN EUR                   15.009,83+
02.02.  Überweisungs-Gutschrift                                      0,10+
        Absender Eins
        Ueberweisung
03.02.  Überweisungs-Gutschrift                                  5.000,00+
        Absender Zwei
29.02.  Überweisungs-Gutschrift                                  5.000,00+
29.02.  Wertstellung: {value_date} Zinsen/Kontoführung               13,94+
        Abrechnung vom 29.02.2016
        GESAMTUMSATZ                                           10.014,04+
        NEUER KONTOSTAND VOM 29.02.2016 IN EUR                 {closing}+
'''
    transactions, warnings, evidence = parse_bookings([text], analyse_pages)
    return ImportBatch('legacy.pdf', 'legacy-hash', source_sheet='PDF',
        document_type='Kontoauszug', transactions=transactions,
        pdf_booking_evidence=evidence, pdf_text='--- Seite 1 ---\n' + text), warnings


@pytest.mark.parametrize('value_date, expected', [('30.02.', ''), ('29.02.', '2016-02-29')])
def test_legacy_renault_recognizes_all_bookings_and_embedded_value_date(tmp_path, value_date, expected):
    from decimal import Decimal
    batch, warnings = legacy_statement(value_date)
    assert len(batch.transactions) == 4
    assert [t.date for t in batch.transactions] == ['2016-02-02', '2016-02-03', '2016-02-29', '2016-02-29']
    assert sum(Decimal(t.amount) for t in batch.transactions) == Decimal('10014.04')
    assert batch.transactions[-1].value_date == expected
    assert batch.transactions[-1].purpose == 'Zinsen/Kontoführung Abrechnung vom 29.02.2016'
    assert all(t.account == 'Konto 123456789' for t in batch.transactions)
    assert bool(warnings) == (not expected)
    repo = PortfolioRepository(tmp_path / 'legacy.sqlite')
    try:
        repo.save_account('Renault', {'number': '123456789'})
        result = import_renault_batches(repo, [batch])[0]
        assert result['status'] == 'imported', result
        assert len(repo.transactions('Renault')) == 4
        assert import_renault_batches(repo, [batch])[0]['status'] == 'imported'
        assert len(repo.transactions('Renault')) == 4
    finally:
        repo.close()


def test_legacy_renault_still_rejects_unreconciled_amounts(tmp_path):
    repo = PortfolioRepository(tmp_path / 'legacy-mismatch.sqlite')
    try:
        repo.save_account('Renault', {'number': '123456789'})
        batch, warnings = legacy_statement(closing='25.024,87')
        assert any('Saldenprüfung' in w for w in warnings)
        assert import_renault_batches(repo, [batch])[0]['status'] == 'error'
        assert not repo.imports()
    finally:
        repo.close()
