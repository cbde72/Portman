import importlib.util
from decimal import Decimal
from pathlib import Path

import pytest

from portfolio_v5.models import ImportBatch
from portfolio_v5.pdf_importer import _validate_plugin_batch
from portfolio_v5.pdf_plugins import ParseContext, PdfDocument, PdfPage


ROOT = Path(__file__).resolve().parents[1]


def load(name):
    path = ROOT / 'pdf_plugins' / name
    spec = importlib.util.spec_from_file_location('phase_c_' + path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.plugin


def document(text):
    return PdfDocument(Path('synthetic.pdf'), text.encode(), 'phase-c', (PdfPage(1, text),))


def parse_baader(text):
    source, plugin = document(text), load('baader.py')
    detection = plugin.detect(source)
    assert len(detection) == 1
    batch = plugin.parse(source, detection[0], ParseContext(ImportBatch('synthetic.pdf', 'phase-c')))
    _validate_plugin_batch(batch, source)
    return batch


def header(title, body):
    return f'''Baader Bank
Depot-Nr.: 1234567
Referenz-Nr.: 998877
{title}
{body}
'''


def test_baader_dividend_keeps_net_gross_and_tax_components_consistent():
    batch = parse_baader(header('Dividendenabrechnung', '''
Nominale ISIN: US0378331005 WKN: 865985 Ausschüttung
STK 2 Apple Inc. USD 1,00 p.STK
Kapitalertragsteuer EUR 0,25 -
US-Quellensteuer EUR 0,15 -
Zu Gunsten Konto 7654321 Valuta: 15.02.2026 EUR 1,60
'''))
    tx = batch.transactions[0]
    assert (tx.kind, tx.amount, tx.gross_amount, tx.taxes) == ('DIVIDEND', '1.60', '2.00', '0.40')
    assert tx.affects_cash is False


def test_baader_advance_tax_separates_basis_and_debit():
    batch = parse_baader(header('Vorabpauschale', '''
Nominale ISIN: DE0008474511 WKN: DBX1DA
STK 10 Xtrackers DAX
Kapitalertragsteuer EUR 2,50 -
Bemessungsgrundlage zur Kapitalertragsteuer EUR 10,00 EUR 10,00
Zu Lasten Konto 7654321 Valuta: 02.01.2026 EUR 2,50
'''))
    assert batch.tax_events[0].taxable_income == '10.00'
    tx = batch.transactions[0]
    assert (tx.kind, tx.amount, tx.taxes, tx.affects_cash) == ('TAX', '-2.50', '2.50', False)


def test_baader_annual_statement_requires_matching_depot_total():
    text = header('Depotauszug per 31.12.2026', '''
Stück 2 WKN: 865985 USD 100,00 200,00 EUR
ISIN: US0378331005
Apple Inc.
Depotwert 200,00 EUR
''')
    snapshot = parse_baader(text).snapshots[0]
    assert snapshot.complete is True
    with pytest.raises(ValueError, match='Depotwert'):
        parse_baader(text.replace('Depotwert 200,00', 'Depotwert 999,00'))


def test_baader_delivery_is_quantity_only_transfer():
    batch = parse_baader(header('Depoteinlieferung', '''
Nominale ISIN: DE000CBK1001 WKN: CBK100
STK 1 Commerzbank AG
Lagerstelle: 100 Valuta: 03.02.2026
service@baaderbank.de EINLIEFERUNG-041.057
'''))
    tx = batch.transactions[0]
    assert (tx.kind, tx.amount, tx.quantity) == ('TRANSFER_IN', '0', '1')


def test_deka_distribution_and_reinvestment_are_linked_and_cash_neutral():
    text = '''Deka
Quartalsbericht per 31.03.2026
Depot: 12345678
Depotübersicht
DE0008474511 01 AriDeka CF 100,00 +10,00
Gesamt in EUR 100,00 +10,00
Umsatzübersicht
ISIN: DE0008474511 Unterdepot: 01
Bestand am 31.12.2025 90,00 100,0000 0,900
Ausschüttung / Kauf aus Ertrag 10,00 100,0000 +0,100 01.02.2026 01.02.2026
Bestand am 31.03.2026 100,00 100,0000 1,000
Bewertung mit dem Rücknahmepreis vom 31.03.2026
'''
    source, plugin = document(text), load('deka_quartalsbericht.py')
    batch = plugin.parse(source, plugin.detect(source)[0], ParseContext(ImportBatch('deka.pdf', 'phase-c')))
    assert [(tx.kind, tx.amount) for tx in batch.transactions] == [('DIVIDEND', '10.00'), ('BUY', '-10.00')]
    assert batch.transactions[0].related_ids == [batch.transactions[1].external_id]
    assert batch.transactions[1].order_subtype == 'wiederanlage'
    assert sum(float(tx.amount) for tx in batch.transactions) == 0


def test_deka_historical_annual_statement_layout_is_detected():
    text = '''Deka
Jahresdepotauszug per 31.12.2016
Depot: 12345678
Depot�bersicht
DE0008474511 01 AriDeka CF 100,00 +10,00
Gesamt in EUR 100,00 +10,00
Umsatz�Jahres�bersicht
ISIN: DE0008474511 Unterdepot: 01
Bestand am 31.12.2016 100,00 100,0000 1,000
Bewertung mit dem Rücknahmepreis vom 31.12.2016
'''
    source, plugin = document(text), load('deka_quartalsbericht.py')
    detections = plugin.detect(source)
    assert detections[0].document_type == 'Deka Jahresdepotauszug'
    batch = plugin.parse(source, detections[0], ParseContext(ImportBatch('deka.pdf', 'phase-c')))
    assert batch.snapshots[0].complete is True


def test_deka_soft_hyphen_cross_page_turnover_and_ocr_page_are_supported():
    overview = '''Deka
Jahresdepotauszug per 31.12.2014
Depot: 12345678
Depotübersicht
DE0008474511 01 AriDeka CF 100,00 +10,00
Gesamt in EUR 100,00 +10,00
'''
    turnover_one = '''Umsatz\xadJahresübersicht Seite 1
ISIN: DE0008474511 Unterdepot: 01
Bestand am 31.12.2013 90,00 90,0000 1,000
Abrechnungsbetrag Ausschüttung 10,00 100,0000 +0,100 21.02.2014 21.02.2014
'''
    turnover_two = '''Umsatz\xadJahresübersicht Seite 2
ISIN: DE0008474511 Unterdepot: 01
Bestand am 31.12.2014 100,00 90,0000 1,100
Bewertung mit dem Rücknahmepreis vom 30.12.2014
'''
    source = PdfDocument(Path('historical.pdf'), b'pdf', 'historical', (
        PdfPage(1, overview), PdfPage(2, turnover_one), PdfPage(3, turnover_two, True)))
    plugin = load('deka_quartalsbericht.py')
    batch = plugin.parse(source, plugin.detect(source)[0],
                         ParseContext(ImportBatch('historical.pdf', 'historical')))

    assert batch.snapshots[0].complete is True
    assert batch.snapshots[0].positions[0].quantity == '1.100'
    assert [(tx.kind, tx.amount, tx.quantity) for tx in batch.transactions] == [
        ('DIVIDEND', '10.00', None), ('BUY', '-10.00', '0.100')]
    assert sum(Decimal(tx.amount) for tx in batch.transactions) == 0
