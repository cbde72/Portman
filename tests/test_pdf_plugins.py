from pathlib import Path

import pytest

from portfolio_v5.models import ImportBatch
from portfolio_v5.pdf_plugins import Detection, PdfDocument, PdfPage, ParseContext
from portfolio_v5.pdf_plugins.config import ConfigPdfPlugin
from portfolio_v5.pdf_plugins.registry import discover_plugins, select_plugin


def document(text):
    return PdfDocument(Path('sample.pdf'), b'%PDF-test', 'hash', (PdfPage(1, text),))


def test_toml_plugin_supports_multiple_document_types(tmp_path):
    profile = tmp_path / 'bank.toml'
    profile.write_text('''
[plugin]
id="test.bank"
bank="Test Bank"
[[documents]]
id="statement"
type="Test Kontoauszug"
required=["TESTBANK", "BUCHUNGEN"]
account_regex="IBAN (?P<id>DE[0-9 ]+)"
account_prefix="IBAN "
transaction_regex="(?m)^(?P<date>[0-9.]{10}) (?P<purpose>.+) (?P<amount>[+-][0-9]+,[0-9]{2})$"
[[documents]]
id="portfolio"
type="Test Depotstand"
required=["TESTBANK", "DEPOTSTAND"]
account_regex="Depot (?P<id>[0-9]+)"
account_prefix="Test Depot "
snapshot_date_regex="Stand (?P<date>[0-9.]{10})"
position_regex="(?m)^(?P<isin>[A-Z0-9]{12}) (?P<name>.+) (?P<quantity>[0-9]+) (?P<value>[0-9]+,[0-9]{2})$"
''', encoding='utf-8')
    plugin = ConfigPdfPlugin(profile)
    statement = document('TESTBANK BUCHUNGEN\nIBAN DE12 3456\n01.02.2026 Gehalt +100,00')
    detections = plugin.detect(statement)
    assert [(d.handler_id, d.document_type) for d in detections] == [('statement', 'Test Kontoauszug')]
    batch = plugin.parse(statement, detections[0], ParseContext(ImportBatch('sample.pdf', 'hash', source_sheet='PDF')))
    assert batch.transactions[0].account == 'IBAN DE123456'
    assert batch.transactions[0].amount == '100.00'
    portfolio = document('TESTBANK DEPOTSTAND\nDepot 77\nStand 01.02.2026\nUS0378331005 Apple 2 400,00')
    detected = plugin.detect(portfolio)[0]
    batch = plugin.parse(portfolio, detected, ParseContext(ImportBatch('sample.pdf', 'hash', source_sheet='PDF')))
    assert detected.handler_id == 'portfolio'
    assert batch.snapshots[0].account == 'Test Depot 77'
    assert batch.snapshots[0].positions[0].name == 'Apple'


def test_registry_rejects_ambiguous_document_handlers():
    class Plugin:
        plugin_id, bank_name, version = 'test', 'Test', '1'
        def detect(self, doc):
            return [Detection(.90, 'A', 'a'), Detection(.85, 'B', 'b')]
        def parse(self, document, detection, context): return context.batch
    with pytest.raises(ValueError, match='mehrdeutig'):
        select_plugin(document('x'), [Plugin()])


def test_toml_plugin_preserves_named_reference_group(tmp_path):
    profile = tmp_path / 'reference.toml'
    profile.write_text('''
[plugin]
id="test.reference"
bank="Test Bank"
[[documents]]
id="statement"
type="Test Kontoauszug"
required=["TESTBANK"]
account_regex="IBAN (?P<id>DE[0-9]+)"
transaction_regex='(?m)^(?P<date>[0-9.]{10}) (?P<purpose>[^|]+) \\| (?P<reference>[^|]+) \\| (?P<amount>[+][0-9]+,[0-9]{2})$'
''', encoding='utf-8')
    plugin = ConfigPdfPlugin(profile)
    source = document('TESTBANK\nIBAN DE1234\n01.02.2026 Gehalt | REF 42/7 | +100,00')
    batch = plugin.parse(source, plugin.detect(source)[0], ParseContext(ImportBatch('sample.pdf', 'hash')))
    tx = batch.transactions[0]
    assert tx.bank_reference == tx.document_reference == 'REF 42/7'


def test_baader_is_loaded_as_external_python_file(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    plugins, errors = discover_plugins()
    baader = [plugin for plugin in plugins if plugin.plugin_id == 'baader.pdf']
    assert len(baader) == 1
    assert baader[0].source_path.name == 'baader.py'
    assert not any('baader.py' in error for error in errors)


def test_all_shipped_bank_parsers_are_loaded_from_external_plugin_folder(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    plugins, errors = discover_plugins()
    expected = {'baader.pdf', 'comdirect.finanzreport', 'renault.kontoauszug', 'generic.kontoauszug'}
    selected = {plugin.plugin_id: plugin for plugin in plugins if plugin.plugin_id in expected}
    assert set(selected) == expected
    assert all(plugin.source_path.parent.name == 'pdf_plugins' for plugin in selected.values())
    assert not any(plugin.plugin_id.startswith('builtin.') for plugin in plugins)
    assert not errors


def test_renault_statement_uses_external_plugin(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from portfolio_v5 import pdf_importer
    text = ('Renault Bank direkt\nKontoauszug\nKonto: 12345678\nEUR\nBu-Tag Wert Vorgang\n'
            'alter Kontostand vom 31.08.2026 100,00 H\n'
            '01.09. 01.09. Überweisung 25,00 H\n'
            'neuer Kontostand vom 30.09.2026 125,00 H')
    page = SimpleNamespace(extract_text=lambda **kwargs: text, images=[])
    monkeypatch.setattr(pdf_importer, 'PdfReader', lambda path: SimpleNamespace(is_encrypted=False, pages=[page]))
    path = tmp_path / 'renault.pdf'; path.write_bytes(b'test')
    batch = pdf_importer.parse_pdf(path)
    assert not batch.errors
    assert batch.plugin_id == 'renault.kontoauszug'
    assert batch.plugin_handler == 'kontoauszug'
    assert batch.transactions[0].amount == '25.00'


def test_comdirect_income_keeps_reference_for_later_assignment():
    import importlib.util
    path = Path(__file__).resolve().parents[1] / 'pdf_plugins' / 'comdirect_ertraege.py'
    spec = importlib.util.spec_from_file_location('comdirect_income_reference_test', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    text = '''comdirect
Abrechnung Dividendengutschrift
STK 10 US0378331005
per 31.12.2025 Apple Inc. 865985
Referenz-Nr.: ABC-123 / 9
DE89370400440532013000 EUR 31.12.2025 EUR 10,00
'''
    parsed_document = document(text)
    detection = module.plugin.detect(parsed_document)[0]
    batch = module.plugin.parse(
        parsed_document, detection, ParseContext(ImportBatch('sample.pdf', 'hash', source_sheet='PDF')))

    tx = batch.transactions[0]
    assert tx.bank_reference == 'ABC-123 / 9'
    assert tx.document_reference == 'ABC-123 / 9'


def test_comdirect_trade_extracts_provision_and_settlement_identity():
    import importlib.util
    path = Path(__file__).resolve().parents[1] / 'pdf_plugins' / 'comdirect_ertraege.py'
    spec = importlib.util.spec_from_file_location('comdirect_trade_fee_test', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    text = '''comdirect
Wertpapierkauf Nr. 91159075 vom 23.07.2026
Stk. 0,620 ISH.S.EUROP.MID 200 U.ETF, WKN/ISIN: 593399/DE0005933998
Kurswert: EUR 41,33
Provision: EUR 0,62
ZuIhrenLastennachSteuern: EUR -41,95
Valuta 27.07.2026 auf Konto mit der IBAN DE84200411330476492400
Depotnummer: 476492400
Referenz-Nummer: 24INLL4XX5T001NI
'''
    parsed_document = document(text)
    detection = module.plugin.detect(parsed_document)[0]
    batch = module.plugin.parse(
        parsed_document, detection, ParseContext(ImportBatch('trade.pdf', 'hash', source_sheet='PDF')))

    tx = batch.transactions[0]
    assert detection.handler_id == 'wertpapierkauf'
    assert (tx.date, tx.value_date, tx.amount, tx.gross_amount) == (
        '2026-07-23', '2026-07-27', '-41.95', '41.33')
    assert (tx.security, tx.quantity, tx.fees) == ('DE0005933998', '0.620', '0.62')
    assert [(item.kind, item.amount) for item in tx.fee_items] == [('provision', '0.62')]
    assert tx.account == tx.cash_account == 'IBAN DE84200411330476492400'
    assert tx.depot_account == 'Depot 476492400'
    assert batch.securities[0].wkn == '593399'
