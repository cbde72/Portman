import importlib.util
from copy import deepcopy
from pathlib import Path

import pytest

from portfolio_v5.models import ImportBatch, check_transaction
from portfolio_v5.pdf_plugins import ParseContext, PdfDocument, PdfPage
from portman.repository_v09 import RepositoryV09


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / 'tests' / 'fixtures' / 'importers' / 'fnz'


def plugin():
    path = ROOT / 'pdf_plugins' / 'fnz_finvesto.py'
    spec = importlib.util.spec_from_file_location('phase_c_fnz', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.plugin


def parse(relative, *, used_ocr=False):
    path = FIXTURES / relative / 'source.txt'
    text = path.read_text(encoding='utf-8')
    document = PdfDocument(path, text.encode(), 'fnz-fixture', (PdfPage(1, text, used_ocr),))
    selected = plugin()
    detection = selected.detect(document)
    assert len(detection) == 1
    return selected.parse(document, detection[0],
                          ParseContext(ImportBatch(path.name, 'fnz-fixture', source_sheet='PDF')))


def test_distribution_reinvestment_and_purchase_are_three_economic_events():
    batch = parse('umsatzabrechnung/fnz-current-v1')
    assert [(tx.kind, tx.amount, tx.currency, tx.order_subtype) for tx in batch.transactions] == [
        ('DIVIDEND', '10.00', 'USD', ''),
        ('BUY', '-10.00', 'USD', 'wiederanlage'),
        ('BUY', '-50.00', 'EUR', ''),
    ]
    assert len({tx.external_id for tx in batch.transactions}) == 3
    assert batch.snapshots[0].complete is False
    assert batch.snapshots[0].positions[0].quantity == '5.600'


def test_purchase_cashflow_includes_fee_when_extracted_payment_has_no_separator():
    text = '''FNZ Bank SE
    Umsatzabrechnung-Nr. 1
Umsatzabrechnung für Ihr finvesto Depot bei der FNZ Bank
    Depot-Nr. 00000000001
    Kauf 161,00 EUR mit Kursdatum 15.01.2024 in Depotposition 00000000001.02
    Ref. Nr. 1/1, Buchungsdatum 15.01.2024
ISIN Anteile Abrechnungskurs Devisenkurs Betrag
    ZZ0000000008 2,000000 100,000000 USD 1,250000 160,00 EUR
    ETF-Transaktionsentgelt 1,00 EUR
    Zahlungsbetragaus Überweisung 161,00 EUR
    Kauf 161,00 EUR mit Kursdatum 16.01.2024 in Depotposition 00000000001.02
    Ref. Nr. 2/2, Buchungsdatum 16.01.2024
ISIN Anteile Abrechnungskurs Devisenkurs Betrag
    ZZ0000000008 1,000000 200,000000 USD 1,250000 160,00 EUR
    ETF-Transaktionsentgelt 1,00 EUR
    Zahlungsbetragaus Überweisung 161,00 EUR
Bestand der Depotpositionen mit Umsatz nach Verbuchung
Pos. Fonds Anteile Bewertungskurs zum Datum Devisenkurs Bestand
    02 ZZ0000000008 3,000000 100,000000 USD 16.01.2024 1,0000 300,00 EUR
    Depotgesamtwert 300,00 EUR
'''
    path = FIXTURES / 'umsatzabrechnung/fnz-current-v1/source.txt'
    document = PdfDocument(path, text.encode(), 'fnz-payment-spacing', (PdfPage(1, text),))
    selected = plugin()
    batch = selected.parse(document, selected.detect(document)[0],
                           ParseContext(ImportBatch(path.name, 'fnz-payment-spacing', source_sheet='PDF')))

    assert [(tx.amount, tx.gross_amount, tx.fees) for tx in batch.transactions] == [
        ('-161.00', '160.00', '1.00'),
        ('-161.00', '160.00', '1.00'),
    ]
    assert all(tx.fx_rate is not None for tx in batch.transactions)
    assert all(check_transaction(tx) == [] for tx in batch.transactions)
    assert all([(item.kind, item.amount) for item in tx.fee_items] ==
               [('transaktionsentgelt', '1.00')] for tx in batch.transactions)


def test_quarterly_depot_statement_is_complete_only_after_total_check():
    batch = parse('depotauszug/fnz-current-v1')
    snapshot = batch.snapshots[0]
    assert snapshot.complete is True
    assert (snapshot.reported_total_value, snapshot.reported_position_count) == ('560.00', 1)


def test_fnz_total_mismatch_is_rejected():
    path = FIXTURES / 'depotauszug/fnz-current-v1/source.txt'
    text = path.read_text(encoding='utf-8').replace('Depotgesamtwert 560,00', 'Depotgesamtwert 999,00')
    document = PdfDocument(path, text.encode(), 'bad-total', (PdfPage(1, text),))
    selected = plugin()
    with pytest.raises(ValueError, match='Positionssumme'):
        selected.parse(document, selected.detect(document)[0],
                       ParseContext(ImportBatch(path.name, 'bad-total', source_sheet='PDF')))


def test_ocr_on_document_page_does_not_discard_verified_structured_rows():
    batch = parse('umsatzabrechnung/fnz-current-v1', used_ocr=True)
    assert len(batch.transactions) == 3
    assert batch.snapshots[0].reported_total_value == '560.00'


def test_foreign_currency_distribution_uses_documented_tax_total_and_rate():
    path = FIXTURES / 'umsatzabrechnung/fnz-current-v1/source.txt'
    text = path.read_text(encoding='utf-8')
    text = text.replace('DE0008474511 5,000 2,0000 USD 10,00 USD',
                        'DE0008474511 5,000 2,0000 USD 2,98 USD', 1)
    text = text.replace(
        'Zahlungsbetrag 10,00 USD',
        'Kapitalertragsteuer Solidaritätszuschlag Kirchensteuer Devisenkurs abzgl. Steuern\n'
        '0,45 EUR 0,02 EUR 0,00 EUR 1,153077 0,54 USD\nZahlungsbetrag 2,44 USD', 1)
    text = text.replace('Wiederanlage Fondsertrag 10,00 USD', 'Wiederanlage Fondsertrag 2,44 USD')
    text = text.replace('0,100 100,0000 USD 10,00 USD', '0,0244 100,0000 USD 2,44 USD')
    text = text.replace('Zahlungsbetrag 10,00 USD', 'Zahlungsbetrag 2,44 USD')
    document = PdfDocument(path, text.encode(), 'taxed-fnz', (PdfPage(1, text),))
    selected = plugin()
    batch = selected.parse(document, selected.detect(document)[0],
                           ParseContext(ImportBatch(path.name, 'taxed-fnz', source_sheet='PDF')))
    distribution = batch.transactions[0]
    assert (distribution.amount, distribution.gross_amount, distribution.taxes, distribution.fx_rate) == (
        '2.44', '2.98', '0.54', '1.153077')
    assert [(item.kind, item.amount, item.original_amount, item.original_currency)
            for item in distribution.tax_items] == [
        ('kapitalertragsteuer', '0.52', '0.45', 'EUR'),
        ('solidaritaetszuschlag', '0.02', '0.02', 'EUR'),
        ('kirchensteuer', '0.00', '0.00', 'EUR'),
    ]


def test_fnz_persistence_is_idempotent_for_same_file_and_same_economic_events(tmp_path):
    batch = parse('umsatzabrechnung/fnz-current-v1')
    # The fixture is extracted text, not a synthetic PDF container.  Document
    # archiving is covered by PDF import tests; this check targets economics.
    batch.documents.clear()
    repo = RepositoryV09(tmp_path / 'fnz.sqlite', backups=False)
    try:
        first = repo.commit_batches([batch])[0]
        repeated = repo.commit_batches([batch])[0]
        renamed = deepcopy(batch)
        renamed.path = 'same-events-under-another-name.pdf'
        renamed.file_hash = 'different-pdf-container-hash'
        same_events = repo.commit_batches([renamed])[0]

        assert first['status'] == 'imported', first
        assert repeated['status'] == 'duplicate'
        assert same_events['status'] == 'imported'
        assert same_events['transactions'] == 0
        assert same_events['unchanged'] == 4  # three transactions and the partial snapshot
        assert repo.db.execute('SELECT count(*) FROM transactions').fetchone()[0] == 3
        assert repo.store.model_records(kind='tax_event') == []
    finally:
        repo.close()
