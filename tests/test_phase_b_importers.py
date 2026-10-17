import importlib.util
from pathlib import Path

import pytest

from portfolio_v5.models import ImportBatch
from portfolio_v5.pdf_plugins import ParseContext, PdfDocument, PdfPage


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / 'tests' / 'fixtures' / 'importers'


def load_plugin(name):
    path = ROOT / 'pdf_plugins' / name
    spec = importlib.util.spec_from_file_location('phase_b_' + path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.plugin


def parse(plugin, fixture):
    path = FIXTURES / fixture / 'source.txt'
    text = path.read_text(encoding='utf-8')
    document = PdfDocument(path, text.encode(), 'synthetic-hash', (PdfPage(1, text),))
    detections = plugin.detect(document)
    assert len(detections) == 1
    return detections[0], plugin.parse(
        document, detections[0], ParseContext(ImportBatch(path.name, 'synthetic-hash', source_sheet='PDF')))


def test_comdirect_sale_is_depot_event_with_positive_cash_direction():
    detection, batch = parse(load_plugin('comdirect_ertraege.py'), 'comdirect/verkauf/compact-v1')
    tx = batch.transactions[0]
    assert detection.handler_id == 'wertpapierverkauf'
    assert (tx.kind, tx.amount, tx.gross_amount, tx.fees) == ('SELL', '99.00', '100.00', '1.00')
    assert tx.account == tx.depot_account == 'Depot 123456789'
    assert tx.cash_account == 'IBAN DE11111111111111111111'
    assert tx.affects_cash is False


def test_comdirect_sale_rejects_debit_direction():
    plugin = load_plugin('comdirect_ertraege.py')
    path = FIXTURES / 'comdirect/verkauf/compact-v1/source.txt'
    text = path.read_text(encoding='utf-8').replace('ZuIhrenGunsten', 'ZuIhrenLasten')
    document = PdfDocument(path, text.encode(), 'bad-direction', (PdfPage(1, text),))
    with pytest.raises(ValueError, match='Zahlungsrichtung'):
        plugin.parse(document, plugin.detect(document)[0],
                     ParseContext(ImportBatch(path.name, 'bad-direction', source_sheet='PDF')))


def test_ing_sale_extracts_fee_and_positive_net_amount():
    detection, batch = parse(load_plugin('ing_wertpapiere.py'), 'ing/verkauf/current-v1')
    tx = batch.transactions[0]
    assert detection.handler_id == 'verkauf'
    assert (tx.kind, tx.amount, tx.gross_amount, tx.fees) == ('SELL', '99.00', '100.00', '1.00')
    assert (tx.quantity, tx.price, tx.cash_account) == ('2.00', '50.00', 'IBAN DE11111111111111111111')


def test_ing_advance_tax_separates_tax_basis_from_cash_debit():
    detection, batch = parse(load_plugin('ing_wertpapiere.py'), 'ing/vorabpauschale/current-v1')
    event, tx = batch.tax_events[0], batch.transactions[0]
    assert detection.handler_id == 'vorabpauschale'
    assert (event.taxable_income, event.per_unit, event.quantity) == ('10.00', '1.0000', '10.00')
    assert (tx.kind, tx.amount, tx.taxes) == ('TAX', '-2.63', '2.63')
    assert [(item.kind, item.amount) for item in tx.tax_items] == [
        ('kapitalertragsteuer', '2.50'), ('solidaritaetszuschlag', '0.13')]
    assert tx.account == 'Depot 1234567890'
    assert tx.cash_account == 'IBAN DE11111111111111111111'
    assert tx.affects_cash is False


def test_ing_tax_refund_has_positive_economic_direction():
    detection, batch = parse(load_plugin('ing_wertpapiere.py'), 'ing/steuererstattung/current-v1')
    tx = batch.transactions[0]
    assert detection.handler_id == 'steuerverrechnung'
    assert (tx.kind, tx.amount, tx.taxes) == ('TAX_REFUND', '2.63', '2.63')
    assert tx.account == 'Depot 1234567890'
    assert tx.cash_account == 'IBAN DE11111111111111111111'
    assert tx.affects_cash is False


def test_ing_tax_refund_rejects_inconsistent_components():
    plugin = load_plugin('ing_wertpapiere.py')
    path = FIXTURES / 'ing/steuererstattung/current-v1/source.txt'
    text = path.read_text(encoding='utf-8').replace('Erstattung/Belastung (-) 2,63',
                                                   'Erstattung/Belastung (-) 9,99')
    document = PdfDocument(path, text.encode(), 'bad-total', (PdfPage(1, text),))
    with pytest.raises(ValueError, match='Steuerkomponenten'):
        plugin.parse(document, plugin.detect(document)[0],
                     ParseContext(ImportBatch(path.name, 'bad-total', source_sheet='PDF')))
