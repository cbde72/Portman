import importlib.util
from pathlib import Path

import pytest

from portfolio_v5.models import ImportBatch
from portfolio_v5.pdf_plugins import ParseContext, PdfDocument, PdfPage
from portman.repository_v09 import RepositoryV09


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


def test_ing_sale_without_fee_is_documented_zero_and_equation_valid():
    plugin = load_plugin('ing_wertpapiere.py')
    path = FIXTURES / 'ing/verkauf/current-v1/source.txt'
    text = path.read_text(encoding='utf-8').replace('Provision EUR 1,00\n', '').replace(
        'Endbetrag zu Ihren Gunsten EUR 99,00', 'Endbetrag zu Ihren Gunsten EUR 100,00')
    document = PdfDocument(path, text.encode(), 'no-fee-sale', (PdfPage(1, text),))
    batch = plugin.parse(document, plugin.detect(document)[0],
                         ParseContext(ImportBatch(path.name, 'no-fee-sale', source_sheet='PDF')))
    tx = batch.transactions[0]
    assert (tx.kind, tx.amount, tx.gross_amount, tx.fees) == (
        'SELL', '100.00', '100.00', '0.00')
    assert [(item.kind, item.amount) for item in tx.fee_items] == [('entgelt', '0.00')]


def test_comdirect_unreadable_zero_quantity_is_never_booked():
    plugin = load_plugin('comdirect_ertraege.py')
    path = FIXTURES / 'comdirect/verkauf/compact-v1/source.txt'
    text = path.read_text(encoding='utf-8').replace('Stk. 2,000', 'Stk. 0').replace(
        'NennwertZumKursvonSt.2,000', 'NennwertZumKursvon')
    document = PdfDocument(path, text.encode(), 'unreadable-quantity', (PdfPage(1, text),))
    with pytest.raises(ValueError, match='Stückzahl fehlt sowohl'):
        plugin.parse(document, plugin.detect(document)[0],
                     ParseContext(ImportBatch(path.name, 'unreadable-quantity', source_sheet='PDF')))


def comdirect_purchase_document(execution_line, tax_quantity='0', market='21,98'):
    business = f'''comdirect bank AG
Wertpapierkauf Nr. 91229890 vom 01.06.2026
{execution_line}
Kurswert: EUR {market}
ZuIhrenLastenvorSteuern: EUR -{market}
Depotnummer: 123456789
'''
    tax = f'''Steuerliche Behandlung: Wertpapierkauf Nr. 91229890 vom 01.06.2026
Stk.{tax_quantity} Muster Index, WKN/ISIN: A1TEST/DE000A1TEST0
ZuIhrenLastennachSteuern: EUR -{market}
Valuta 03.06.2026 auf Konto mit der IBAN DE11111111111111111111
Referenz-Nummer: ANONYMIZED1
'''
    return PdfDocument(Path('anonymous.pdf'), b'%PDF-anonymous', 'anonymous-hash',
                       (PdfPage(1, business), PdfPage(2, tax)))


@pytest.mark.parametrize('execution_line', [
    'Nennwert Zum Kurs von St. 0,006 EUR 3.662,71',
    'NennwertZumKursvonSt.0,006 EUR3.662,71',
])
def test_comdirect_trade_prefers_business_quantity_for_both_text_layouts(execution_line):
    plugin = load_plugin('comdirect_ertraege.py')
    source = comdirect_purchase_document(execution_line)
    batch = plugin.parse(source, plugin.detect(source)[0],
                         ParseContext(ImportBatch('anonymous.pdf', 'anonymous-hash', source_sheet='PDF')))
    tx = batch.transactions[0]
    assert (tx.quantity, tx.price, tx.gross_amount) == ('0.006', '3662.71', '21.98')
    assert tx.field_sources['quantity'] == 'comdirect Geschäftsabrechnung · Nennwert/Zum Kurs von'


def test_comdirect_trade_uses_positive_tax_quantity_only_after_value_check():
    plugin = load_plugin('comdirect_ertraege.py')
    source = comdirect_purchase_document(
        'Nennwert Zum Kurs von EUR 73,37', tax_quantity='0,240', market='17,61')
    batch = plugin.parse(source, plugin.detect(source)[0],
                         ParseContext(ImportBatch('anonymous.pdf', 'secondary', source_sheet='PDF')))
    tx = batch.transactions[0]
    assert (tx.quantity, tx.price, tx.gross_amount) == ('0.240', '73.37', '17.61')
    assert 'sekundär' in tx.field_sources['quantity']


def test_comdirect_trade_keeps_typed_fee_components_including_foreign_costs():
    plugin = load_plugin('comdirect_ertraege.py')
    source = comdirect_purchase_document(
        'Nennwert Zum Kurs von St. 0,006 EUR 3.662,71', market='21,98')
    pages = list(source.pages)
    pages[0] = PdfPage(1, pages[0].text.replace(
        'Kurswert: EUR 21,98',
        'Kurswert: EUR 21,98\nProvision: EUR 0,43\nOrderentgelt: EUR 0,20\n'
        'Handelsplatzgebühr: EUR 0,10\nFremdspesen: EUR 0,05').replace(
            'ZuIhrenLastenvorSteuern: EUR -21,98', 'ZuIhrenLastenvorSteuern: EUR -22,76'))
    pages[1] = PdfPage(2, pages[1].text.replace(
        'ZuIhrenLastennachSteuern: EUR -21,98', 'ZuIhrenLastennachSteuern: EUR -22,76'))
    document = PdfDocument(source.path, source.content, source.file_hash, tuple(pages))
    batch = plugin.parse(document, plugin.detect(document)[0],
                         ParseContext(ImportBatch('fees.pdf', 'typed-fees', source_sheet='PDF')))
    tx = batch.transactions[0]
    assert tx.fees == '0.78'
    assert [(item.kind, item.amount) for item in tx.fee_items] == [
        ('provision', '0.43'), ('orderentgelt', '0.20'),
        ('handelsplatzgebuehr', '0.10'), ('fremdspesen', '0.05')]


def test_comdirect_trade_rejects_quantity_value_contradiction():
    plugin = load_plugin('comdirect_ertraege.py')
    source = comdirect_purchase_document('Nennwert Zum Kurs von EUR 90,00', tax_quantity='0,240')
    with pytest.raises(ValueError, match='Geschäftsabrechnung widersprüchlich'):
        plugin.parse(source, plugin.detect(source)[0],
                     ParseContext(ImportBatch('anonymous.pdf', 'bad-secondary', source_sheet='PDF')))


def test_comdirect_trade_rejects_when_both_quantity_sources_are_missing():
    plugin = load_plugin('comdirect_ertraege.py')
    source = comdirect_purchase_document('Nennwert Zum Kurs von EUR 3.662,71', tax_quantity='0')
    with pytest.raises(ValueError, match='Stückzahl fehlt sowohl'):
        plugin.parse(source, plugin.detect(source)[0],
                     ParseContext(ImportBatch('anonymous.pdf', 'missing-quantity', source_sheet='PDF')))


def test_comdirect_trade_is_stored_under_depot_bookings(tmp_path):
    plugin = load_plugin('comdirect_ertraege.py')
    source = comdirect_purchase_document('NennwertZumKursvonSt.0,006 EUR3.662,71')
    batch = plugin.parse(source, plugin.detect(source)[0],
                         ParseContext(ImportBatch('anonymous.pdf', 'depot-booking', source_sheet='PDF')))
    batch.documents = []
    repo = RepositoryV09(tmp_path / 'portfolio.sqlite', backups=False)
    try:
        assert repo.commit_batches([batch])[0]['status'] == 'imported'
        bookings = repo.transactions('Depot 123456789')
        assert len(bookings) == 1
        assert (bookings[0]['account'], bookings[0]['security'], bookings[0]['quantity']) == (
            'Depot 123456789', 'DE000A1TEST0', '0.006')
        assert repo.transactions('IBAN DE11111111111111111111') == []
    finally:
        repo.close()


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
