import os

import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, NameObject, DictionaryObject

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from portfolio_v5.importers import parse_file
from portfolio_v5.pdf_importer import analyse_pages
from portman.repository import PortfolioRepository


def make_pdf(path, texts):
    writer = PdfWriter()
    for text in texts:
        page = writer.add_blank_page(width=600, height=800)
        font = DictionaryObject({NameObject('/Type'): NameObject('/Font'),
            NameObject('/Subtype'): NameObject('/Type1'), NameObject('/BaseFont'): NameObject('/Helvetica')})
        page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'):
            DictionaryObject({NameObject('/F1'): writer._add_object(font)})})
        stream = DecodedStreamObject()
        stream.set_data(('BT /F1 12 Tf 50 700 Td (' + text + ') Tj ET').encode('ascii'))
        page[NameObject('/Contents')] = writer._add_object(stream)
    writer.write(path)
    return path


def test_multiple_accounts_and_repeated_pages():
    result = analyse_pages(['Konto-Nr.: 12345678\nDepotnummer: 87654321',
                            'Konto-Nr.: 12345678'])
    assert result == {'Konto 12345678': {1, 2}, 'Depot 87654321': {1}}


def test_pdf_preview_confirmation_and_separate_targets(tmp_path):
    from PySide6.QtWidgets import QApplication
    from portman.import_preview import ImportPreviewDialog
    QApplication.instance() or QApplication([])
    path = make_pdf(tmp_path / 'accounts.pdf', ['Konto: 12345678', 'Depot: 87654321'])
    batch = parse_file(path)
    assert not batch.errors
    assert len(batch.documents) == 2
    repo = PortfolioRepository(tmp_path / 'test.sqlite')
    repo.create_accounts(['A', 'B'])
    dialog = ImportPreviewDialog(repo, [batch])
    with pytest.raises(ValueError):
        dialog.selected_batches()
    for row, target in zip(dialog.mapping_rows, ['a', 'b']):
        row[2].setCurrentIndex(row[2].findData(target))
    selected = dialog.selected_batches()
    dialog.reject()
    assert not repo.imports()
    assert not repo.store.bank_documents()
    assert repo.commit_batches(selected)[0]['status'] == 'imported'
    assert len(repo.store.bank_documents('A')) == 1
    assert len(repo.store.bank_documents('B')) == 1
    assert repo.commit_batches(selected)[0]['status'] == 'duplicate'
    assert not repo.transactions()
    dialog.close()
    repo.close()


def test_unreadable_and_scan(tmp_path, monkeypatch):
    monkeypatch.setattr('portfolio_v5.pdf_ocr.ocr_page', lambda *args: ('', 0.0))
    broken = tmp_path / 'broken.pdf'
    broken.write_bytes(b'not a pdf')
    assert parse_file(broken).errors
    scan = parse_file(make_pdf(tmp_path / 'scan.pdf', ['']))
    assert not scan.errors
    assert len(scan.documents) == 1
    assert any('OCR' in warning for warning in scan.warnings)


def test_skip_counterparty(tmp_path):
    from PySide6.QtWidgets import QApplication
    from portman.import_preview import ImportPreviewDialog
    QApplication.instance() or QApplication([])
    batch = parse_file(make_pdf(tmp_path / 'two.pdf', ['Konto: 12345678', 'Konto: 87654321']))
    repo = PortfolioRepository(tmp_path / 'skip.sqlite')
    repo.create_accounts(['A'])
    dialog = ImportPreviewDialog(repo, [batch])
    for row, target in zip(dialog.mapping_rows, ['a', '__skip__']):
        row[2].setCurrentIndex(row[2].findData(target))
    selected = dialog.selected_batches()[0]
    assert len(selected.documents) == 1
    assert len(batch.documents) == 2
    assert len(selected.account_assignments) == 1
    dialog.close()
    repo.close()


OCR_STATEMENT = '''Konto-Nr.: 12345678
EUR-Konto
Bu-Tag Wert Vorgang
alter Kontostand vom 31.08.2026 100,00 H
01.09. 01.09. Einzahlung 25,00 H
02.09. 02.09. Gebuehr 5,00 S
neuer Kontostand vom 30.09.2026 120,00 H'''


def test_ocr_bookings_review_edit_skip_and_commit(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import Qt
    from portman.import_preview import ImportPreviewDialog
    monkeypatch.setattr('portfolio_v5.pdf_ocr.ocr_page', lambda *args: (OCR_STATEMENT, .96))
    QApplication.instance() or QApplication([])
    batch = parse_file(make_pdf(tmp_path / 'scan.pdf', ['']))
    assert len(batch.transactions) == 2
    assert all(item['ocr'] for item in batch.pdf_booking_evidence)
    repo = PortfolioRepository(tmp_path / 'ocr.sqlite')
    repo.create_accounts(['A'])
    dialog = ImportPreviewDialog(repo, [batch])
    combo = dialog.mapping_rows[0][2]
    combo.setCurrentIndex(combo.findData('a'))
    assert not dialog.selected_batches()[0].transactions
    table = dialog.pdf_bookings_table
    table.item(0, 0).setCheckState(Qt.CheckState.Checked)
    table.item(0, 5).setText('26,00')
    table.item(0, 6).setText('Korrigierte Einzahlung')
    selected = dialog.selected_batches()
    assert len(selected[0].transactions) == 1
    assert selected[0].transactions[0].amount == '26.00'
    assert batch.transactions[0].amount == '25.00'
    table.item(0, 3).setText('2026-02-31')
    with pytest.raises(ValueError, match='Datum'):
        dialog.selected_batches()
    table.item(0, 3).setText('2026-09-01')
    dialog.reject()
    assert not repo.transactions()
    assert not repo.imports()
    assert repo.commit_batches(selected)[0]['status'] == 'imported'
    assert len(repo.transactions('A')) == 1
    assert repo.transactions('A')[0]['purpose'] == 'Korrigierte Einzahlung'
    assert repo.commit_batches(selected)[0]['status'] == 'duplicate'
    dialog.close()
    repo.close()


def test_ocr_failure_keeps_document_and_other_files(tmp_path, monkeypatch):
    def fail(*args):
        raise RuntimeError('Testfehler')
    monkeypatch.setattr('portfolio_v5.pdf_ocr.ocr_page', fail)
    scanned = parse_file(make_pdf(tmp_path / 'scan.pdf', ['']))
    assert not scanned.errors
    assert scanned.documents and not scanned.transactions
    assert any('OCR fehlgeschlagen' in warning for warning in scanned.warnings)
    native = parse_file(make_pdf(tmp_path / 'native.pdf', ['Konto: 12345678']))
    assert not native.errors
    assert native.documents[0].account == 'Konto 12345678'


@pytest.mark.parametrize('title, expected', [
    ('Kontoauszug', 'Kontoauszug'),
    ('Jahres-Steuerbescheinigung', 'Steuerbescheinigung'),
    ('Zinsmitteilung', 'Zinsmitteilung'),
    ('Wertpapierabrechnung', 'Wertpapierabrechnung'),
    ('Depotaufstellung', 'Depotauszug'),
    ('Quartalsaufstellung MiFID II', 'Kosteninformation'),
    ('Basisinformationsblatt', 'Produktinformation'),
    ('Sonstiges Schreiben', 'Unbekanntes Dokument'),
])
def test_document_type_from_content(tmp_path, title, expected):
    batch = parse_file(make_pdf(tmp_path / 'Kontoauszug.pdf', [title]))
    assert not batch.errors
    assert batch.document_type == expected
    assert not batch.transactions


def test_tax_document_does_not_import_statement_like_table(tmp_path, monkeypatch):
    monkeypatch.setattr('portfolio_v5.pdf_ocr.ocr_page', lambda *args:
        ('Jahres-Steuerbescheinigung\n' + OCR_STATEMENT, .99))
    batch = parse_file(make_pdf(tmp_path / 'tax.pdf', ['']))
    assert batch.document_type == 'Steuerbescheinigung'
    assert not batch.transactions
    assert batch.documents


def test_statement_transfers_import_and_document_type_visible(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import Qt
    from portman.import_preview import ImportPreviewDialog
    text = 'Kontoauszug\n' + OCR_STATEMENT.replace('Einzahlung', 'SEPA-Überweisung Eingang').replace('Gebuehr', 'SEPA-Überweisung Ausgang')
    monkeypatch.setattr('portfolio_v5.pdf_ocr.ocr_page', lambda *args: (text, .99))
    batch = parse_file(make_pdf(tmp_path / 'statement.pdf', ['']))
    assert batch.document_type == 'Kontoauszug'
    assert [tx.amount for tx in batch.transactions] == ['25.00', '-5.00']
    QApplication.instance() or QApplication([])
    repo = PortfolioRepository(tmp_path / 'transfers.sqlite')
    repo.create_accounts(['A'])
    dialog = ImportPreviewDialog(repo, [batch])
    assert dialog.table.item(0, dialog.table.columnCount() - 1).text() == 'Kontoauszug'
    combo = dialog.mapping_rows[0][2]
    combo.setCurrentIndex(combo.findData('a'))
    for _, _, row in dialog.pdf_booking_rows:
        dialog.pdf_bookings_table.item(row, 0).setCheckState(Qt.CheckState.Checked)
    assert repo.commit_batches(dialog.selected_batches())[0]['status'] == 'imported'
    assert len(repo.transactions('A')) == 2
    assert all('Überweisung' in tx['purpose'] for tx in repo.transactions('A'))
    dialog.close()
    repo.close()


def test_skipped_account_removes_its_bookings(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import Qt
    from portman.import_preview import ImportPreviewDialog
    monkeypatch.setattr('portfolio_v5.pdf_ocr.ocr_page', lambda path, index:
        (OCR_STATEMENT.replace('12345678', '87654321') if index else OCR_STATEMENT, .99))
    QApplication.instance() or QApplication([])
    batch = parse_file(make_pdf(tmp_path / 'two.pdf', ['', '']))
    assert len(batch.transactions) == 4
    repo = PortfolioRepository(tmp_path / 'skip-bookings.sqlite')
    repo.create_accounts(['A'])
    dialog = ImportPreviewDialog(repo, [batch])
    for row, target in zip(dialog.mapping_rows, ['a', '__skip__']):
        row[2].setCurrentIndex(row[2].findData(target))
    for _, _, row in dialog.pdf_booking_rows:
        dialog.pdf_bookings_table.item(row, 0).setCheckState(Qt.CheckState.Checked)
    selected = dialog.selected_batches()[0]
    assert len(selected.transactions) == 2
    assert {tx.account for tx in selected.transactions} == {'Konto 12345678'}
    dialog.close()
    repo.close()


@pytest.mark.skipif(os.environ.get('PORTMAN_TEST_OCR') != '1', reason='Optional real OCR integration test')
def test_real_image_only_pdf(tmp_path):
    from PIL import Image, ImageDraw, ImageFont
    image = Image.new('RGB', (1654, 2339), 'white')
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype('C:/Windows/Fonts/arial.ttf', 28)
    for index, line in enumerate(OCR_STATEMENT.splitlines()):
        draw.text((100, 150 + index * 65), line, fill='black', font=font)
    path = tmp_path / 'real-scan.pdf'
    image.save(path, 'PDF', resolution=150)
    image.close()
    batch = parse_file(path)
    assert not batch.errors
    assert [tx.amount for tx in batch.transactions] == ['25.00', '-5.00'], batch.warnings
    assert all(item['ocr'] for item in batch.pdf_booking_evidence)
