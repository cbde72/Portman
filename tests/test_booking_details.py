import csv
import hashlib
from io import StringIO
import os
import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from portfolio_v5.models import BankTransaction, ImportBatch
from portfolio_v5.storage import Store
from pdf_plugins._statement_bookings import parse_bookings
from portfolio_v5.pdf_importer import analyse_pages
from portfolio_v5.booking_details import enrich_details


def test_complete_purpose_preserves_counterparty_account_and_continuation():
    text = '''Konto: 12345678
EUR
Buchungstag Valuta Betrag
01.09.2026 01.09.2026 Überweisung -10,00
Empfänger: Beispiel Firma
IBAN: DE89370400440532013000
BIC: COBADEFFXXX
Referenz: ABC123
Übertrag auf Sparkonto
Kompletter mehrzeiliger Verwendungszweck
neuer Kontostand vom 30.09.2026 90,00 H
Kein Buchungstext'''
    txs, _, _ = parse_bookings([text], analyse_pages)
    assert len(txs) == 1
    tx = txs[0]
    assert tx.account == 'Konto 12345678'
    assert tx.counterparty_iban == 'DE89370400440532013000'
    assert tx.counterparty_bic == 'COBADEFFXXX'
    assert tx.bank_reference == 'ABC123'
    assert tx.transaction_reference == 'ABC123'
    assert tx.counterparty == 'Beispiel Firma'
    assert 'Kompletter mehrzeiliger Verwendungszweck' in tx.purpose
    assert 'Übertrag auf Sparkonto' in tx.raw_text
    assert 'Kontostand' not in tx.raw_text
    assert 'Kein Buchungstext' not in tx.purpose


def test_readable_purpose_labels_all_identified_booking_fields():
    tx = BankTransaction('Eigenes Konto', 'x', '2026-01-01', 'BANK_BOOKING', '-12.50', 'EUR',
        purpose='Überweisung Beispiel GmbH Rechnung 123', operation='Überweisung',
        counterparty='Beispiel GmbH', booking_text='Rechnung 123', bank_reference='REF-9',
        counterparty_iban='DE89370400440532013000', counterparty_bic='COBADEFFXXX')

    enrich_details(tx)

    assert tx.purpose == ('Vorgang: Überweisung · Gegenpartei: Beispiel GmbH · '
        'Verwendungszweck: Rechnung 123 · Referenz: REF-9 · '
        'Gegenkonto-IBAN: DE89370400440532013000 · Gegenkonto-BIC: COBADEFFXXX')
    assert tx.raw_text == 'Überweisung Beispiel GmbH Rechnung 123'


@pytest.mark.parametrize('label', [
    'Vorgangsnummer', 'Vorgangs-Nr.', 'Buchungsreferenz', 'Kundenreferenz',
    'End-to-End-Referenz', 'End-to-End-Ref.', 'Transaktions-Nr.', 'Referenz-Nr.',
])
def test_all_supported_reference_labels_are_preserved(label):
    tx = BankTransaction('Konto', 'id', '2026-01-01', 'BANK_BOOKING', '1', 'EUR',
                         purpose='Gutschrift', raw_text=f'{label}: REF 123/45-AB\nWeitere Angabe')
    enrich_details(tx)
    assert tx.bank_reference == 'REF 123/45-AB'
    assert tx.field_sources['bank_reference'] == 'Beschriftete Referenz im Originaltext'


def test_reference_placeholders_are_not_imported():
    tx = BankTransaction('Konto', 'id', '2026-01-01', 'BANK_BOOKING', '1', 'EUR',
                         purpose='Gutschrift', raw_text='End-to-End-Ref.: NOTPROVIDED')
    enrich_details(tx)
    assert tx.bank_reference == ''


@pytest.mark.parametrize('text', [
    'Referenzkonto: DE00123456780000000000',
    'Referenzwert 100,00 EUR',
    'Referenzzinssatz: 3,5 %',
])
def test_reference_prefix_inside_another_field_is_ignored(text):
    tx = BankTransaction('Konto', 'id', '2026-01-01', 'BANK_BOOKING', '1', 'EUR',
                         purpose='Gutschrift', raw_text=text)
    enrich_details(tx)
    assert tx.bank_reference == ''


def test_original_csv_retained_after_deleting_source_and_repeat(tmp_path):
    path = tmp_path / 'source.csv'
    content = 'Buchung;Text\n1;Vollständig\n'.encode('utf-8')
    path.write_bytes(content)
    store = Store(tmp_path / 'db.sqlite')
    try:
        batch = ImportBatch(str(path), hashlib.sha256(content).hexdigest(), transactions=[
            BankTransaction('Bank','tx','2026-01-01','BANK_BOOKING','10','EUR')])
        assert store.import_batch(batch)['status'] == 'imported'
        assert store.import_batch(batch)['status'] == 'duplicate'
        path.unlink()
        assert store.db.execute('SELECT content FROM original_files').fetchone()[0] == content
        assert store.db.execute('SELECT COUNT(*) FROM original_files').fetchone()[0] == 1
    finally: store.close()


def test_copy_all_filtered_sorted_rows_including_unloaded_and_multiline():
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import Qt
    from portman.tables_v09 import DataTable
    from portman.table_copy import table_text
    QApplication.instance() or QApplication([])
    table = DataTable(['ID','Text'],[(i, 'Sichtbar\nZweite Zeile' if i % 2 == 0 else 'Andere') for i in range(700)])
    table.search.setText('Sichtbar')
    table.model.sort(0, Qt.SortOrder.DescendingOrder)
    assert table.model.rowCount() == 256
    result = list(csv.reader(StringIO(table_text(table.view)), delimiter='\t'))
    assert len(result) == 351
    assert result[1] == ['698','Sichtbar\nZweite Zeile']
    assert result[-1][0] == '0'
    table.close()


def test_iban_upgrade_same_file_same_target_replaces_old_number(tmp_path):
    from portfolio_v5.models import digest
    from portfolio_v5.accounts import account_key
    store = Store(tmp_path / 'db.sqlite')
    try:
        store.create_accounts(['Bank'])
        for source, identity in [('Konto 532013000','pdf-booking-old'),('IBAN DE89370400440532013000','comdirect-pdf-new')]:
            batch = ImportBatch('file.pdf',digest('same'),source_sheet='PDF',transactions=[BankTransaction(
                source,identity,'2026-01-01','BANK_BOOKING','10','EUR',purpose='Gutschrift')],
                account_assignments={account_key(source):account_key('Bank')})
            store.import_batch(batch)
        assert len(store.transactions()) == 1
        assert store.transactions()[0]['depot'].startswith('IBAN ')
        store.import_batch(batch)
        assert len(store.transactions()) == 1
    finally: store.close()
