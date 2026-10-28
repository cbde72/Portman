import os
from pathlib import Path
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from portfolio_v5.models import ImportBatch, BankTransaction
from portman.repository import PortfolioRepository
from portman.import_preview import ImportPreviewDialog


def batches():
    return [ImportBatch(f'/reports/report{i}.pdf', str(i), source_sheet='PDF', pdf_text='comdirect',
        transactions=[BankTransaction('IBAN DE89370400440532013000', str(i), '2026-01-01',
                                      'BANK_BOOKING', '10', 'EUR')]) for i in range(3)]


def test_grouped_account_choice_updates_every_selected_file(tmp_path):
    QApplication.instance() or QApplication([])
    repo = PortfolioRepository(tmp_path / 'ui.sqlite')
    try:
        repo.save_account('Bank', {'iban': 'DE89370400440532013000'})
        repo.save_account('Alternative', {})
        dialog = ImportPreviewDialog(repo, batches())
        assert dialog.mapping_table.rowCount() == 1
        assert len(dialog.mapping_rows) == 3
        combo = dialog.mapping_rows[0][2]
        assert combo.minimumHeight() == 38
        assert combo.font().pointSizeF() == 9.0
        assert 'min-height: 34px' in combo.view().styleSheet()
        assert dialog.mapping_table.verticalHeader().defaultSectionSize() == 52
        assert all(row[2] is combo for row in dialog.mapping_rows)
        assert combo.itemText(combo.findData('__skip__')) == (
            'Vorhandenes Zielkonto nicht zuordnen · gesamte Datei überspringen')
        combo.setCurrentIndex(combo.findData('alternative'))
        assert all(row[2].currentData() == 'alternative' for row in dialog.mapping_rows)
        assert '0 offen' in dialog.import_summary.text()
        dialog.only_unassigned.setChecked(True)
        assert dialog.mapping_table.isRowHidden(0)
        combo.setCurrentIndex(combo.findData(None))
        assert not dialog.mapping_table.isRowHidden(0)
        assert '1 offen' in dialog.import_summary.text()
        dialog.table.item(0, 0).setCheckState(Qt.CheckState.Unchecked)
        assert dialog.mapping_table.item(0, 0).text() == 'report1.pdf, report2.pdf'
        dialog.close()
    finally:
        repo.close()


def test_single_mapping_filename_is_visible_and_double_click_opens_pdf(tmp_path, monkeypatch):
    QApplication.instance() or QApplication([])
    source = tmp_path / 'unbekanntes-konto.pdf'
    source.write_bytes(b'%PDF-test\n%%EOF')
    batch = batches()[0]
    batch.path = str(source)
    repo = PortfolioRepository(tmp_path / 'open.sqlite')
    opened = []
    monkeypatch.setattr('portman.import_preview.QDesktopServices.openUrl',
                        lambda url: opened.append(url.toLocalFile()) or True)
    try:
        repo.save_account('Bank', {'iban': 'DE89370400440532013000'})
        dialog = ImportPreviewDialog(repo, [batch])
        assert dialog.mapping_table.item(0, 0).text() == source.name
        assert dialog.mapping_table.item(0, 0).toolTip() == str(source)
        dialog.open_mapping_file(0)
        dialog.open_import_file(0)
        assert [Path(path) for path in opened] == [source.resolve(), source.resolve()]
        dialog.close()
    finally:
        repo.close()


def test_different_saved_targets_and_ambiguous_banks_stay_separate(tmp_path):
    QApplication.instance() or QApplication([])
    repo = PortfolioRepository(tmp_path / 'conflict.sqlite')
    try:
        repo.save_account('A', {})
        repo.save_account('B', {})
        values = batches()
        values[0].account_assignments = {'iban de89370400440532013000': 'a'}
        values[1].account_assignments = {'iban de89370400440532013000': 'b'}
        dialog = ImportPreviewDialog(repo, values)
        assert dialog.mapping_table.rowCount() == 3
        dialog.close()
        source = dict(name='Konto 12345678', key='konto 12345678', target_key=None,
                      new_name='Konto 12345678', remembered=False, scope='scope')
        assert ImportPreviewDialog.mapping_group_key(ImportBatch('a', 'a', source_sheet='PDF', pdf_text='comdirect'), source) != ImportPreviewDialog.mapping_group_key(ImportBatch('b', 'b', source_sheet='PDF', pdf_text='Renault'), source)
    finally:
        repo.close()


def test_new_import_does_not_ask_duplicate_options(tmp_path, monkeypatch):
    from portman.import_options import choose_import_options, ImportOptionsDialog
    QApplication.instance() or QApplication([])
    repo = PortfolioRepository(tmp_path / 'new.sqlite')
    try:
        monkeypatch.setattr(ImportOptionsDialog, 'exec', lambda self: (_ for _ in ()).throw(AssertionError('Unnecessary dialog')))
        originals = batches()
        result = choose_import_options(None, repo, originals)
        assert len(result) == 3
        assert result[0] is not originals[0]
    finally:
        repo.close()



def test_pdf_bookings_show_owner_counterparty_filters_and_live_target(tmp_path):
    QApplication.instance() or QApplication([])
    repo = PortfolioRepository(tmp_path / 'bookings.sqlite')
    try:
        repo.save_account('Bank', {'iban': 'DE89370400440532013000'})
        repo.save_account('Alternative', {})
        values = batches()
        for i, batch in enumerate(values):
            batch.transactions[0].purpose = f'Buchung {i} Gegenkonto DE12500105170648489890'
        dialog = ImportPreviewDialog(repo, values)
        table = dialog.pdf_bookings_table
        assert table.item(0, 10).text() == 'DE89 3704 0044 0532 0130 00'
        assert table.item(0, 11).text() == 'DE12 5001 0517 0648 4898 90'
        assert table.item(0, 9).text() == 'Bank'
        combo = dialog.mapping_rows[0][2]
        combo.setCurrentIndex(combo.findData('alternative'))
        assert table.item(0, 9).text() == 'Alternative'
        dialog.pdf_booking_search.setText('Buchung 1')
        assert [table.isRowHidden(i) for i in range(3)] == [True, False, True]
        assert '1 Buchungen sichtbar' in dialog.pdf_booking_totals.text()
        assert 'Summe 10,00' in dialog.pdf_booking_totals.text()
        dialog.pdf_booking_search.setText('DE89370400440532013000')
        assert not any(table.isRowHidden(i) for i in range(3))
        combo.setCurrentIndex(combo.findData('__skip__'))
        assert '0 ausgewählt' in dialog.pdf_booking_totals.text()
        dialog.close()
    finally:
        repo.close()
