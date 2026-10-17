import importlib.util
from pathlib import Path

from portfolio_v5.models import ImportBatch
from portfolio_v5.pdf_plugins import ParseContext, PdfDocument, PdfPage
from pdf_plugins._generic_document import analyse_pages
from pdf_plugins._statement_bookings import parse_bookings
from portman.repository import PortfolioRepository


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / 'tests' / 'fixtures' / 'importers'


def load_plugin(name):
    path = ROOT / 'pdf_plugins' / name
    spec = importlib.util.spec_from_file_location('phase_d_' + path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.plugin


def fixture(bank):
    return (FIXTURES / bank / 'kontoauszug' / 'verified-v1' / 'source.txt').read_text(encoding='utf-8')


def test_renault_classifies_interest_tax_and_transfer_without_changing_cash_sum():
    text = fixture('renault')
    transactions, warnings, _ = parse_bookings([text], analyse_pages)
    assert not warnings
    assert [(tx.kind, tx.amount, tx.value_date) for tx in transactions] == [
        ('DEPOSIT', '100.00', '2026-02-01'),
        ('INTEREST', '10.00', '2026-02-28'),
        ('TAX', '-2.50', '2026-02-28'),
        ('TAX', '-0.14', '2026-02-28'),
    ]
    assert sum(float(tx.amount) for tx in transactions) == 107.36
    assert [item.kind for tx in transactions for item in tx.tax_items] == [
        'kapitalertragsteuer', 'solidaritaetszuschlag']

    document = PdfDocument(Path('renault.pdf'), text.encode(), 'renault-fixture', (PdfPage(1, text),))
    plugin = load_plugin('renault_kontoauszug.py')
    batch = plugin.parse(document, plugin.detect(document)[0],
                         ParseContext(ImportBatch('renault.pdf', 'renault-fixture')))
    assert [(row.opening_balance, row.closing_balance) for row in batch.statements] == [
        ('1000.00', '1107.36')]


def test_renault_storno_and_tax_refund_keep_economic_direction():
    text = fixture('renault').replace(
        '01.02. 01.02. Überweisungs-Gutschrift 100,00 H',
        '01.02. 01.02. Storno Abschluss 100,00 S').replace(
        '28.02. 28.02. Kapitalertragsteuer aus 2,50 S',
        '28.02. 28.02. Steuererstattung Kap.Steuer 2,50 H')
    transactions, _, _ = parse_bookings([text], analyse_pages)
    assert [(tx.kind, tx.amount) for tx in transactions[:3]] == [
        ('INTEREST', '-100.00'), ('INTEREST', '10.00'), ('TAX_REFUND', '2.50')]


def test_bank_of_scotland_statement_classifies_rows_and_reconciles_balance():
    text = fixture('bank_of_scotland')
    document = PdfDocument(Path('bos.pdf'), text.encode(), 'bos-fixture', (PdfPage(1, text),))
    plugin = load_plugin('bank_of_scotland_kontoauszug.py')
    batch = plugin.parse(document, plugin.detect(document)[0],
                         ParseContext(ImportBatch('bos.pdf', 'bos-fixture')))
    assert [(tx.kind, tx.amount) for tx in batch.transactions] == [
        ('WITHDRAWAL', '-100.00'), ('INTEREST', '10.00'),
        ('TAX', '-2.50'), ('TAX', '-0.14')]
    assert batch.statements[0].opening_balance == '1000.00'
    assert batch.statements[0].closing_balance == '907.36'


def test_bank_of_scotland_rejects_incomplete_or_wrong_statement_total():
    text = fixture('bank_of_scotland').replace('Neuer Saldo: 907,36', 'Neuer Saldo: 999,99')
    document = PdfDocument(Path('bos.pdf'), text.encode(), 'bad-balance', (PdfPage(1, text),))
    plugin = load_plugin('bank_of_scotland_kontoauszug.py')
    try:
        plugin.parse(document, plugin.detect(document)[0], ParseContext(ImportBatch('bos.pdf', 'bad')))
    except ValueError as error:
        assert 'Saldenprüfung' in str(error)
    else:
        raise AssertionError('abweichender Endsaldo wurde akzeptiert')


def test_overlapping_statement_rows_have_stable_ids_and_do_not_duplicate(tmp_path):
    text = fixture('renault')
    first, _, _ = parse_bookings([text], analyse_pages)
    overlap = text.replace('01.02. 01.02. Überweisungs-Gutschrift 100,00 H\n', '')
    second, _, _ = parse_bookings([overlap], analyse_pages)
    assert {tx.external_id for tx in second} <= {tx.external_id for tx in first}

    repo = PortfolioRepository(tmp_path / 'phase-d.sqlite')
    try:
        repo.commit_batches([ImportBatch('first.pdf', 'first', transactions=first)])
        repo.commit_batches([ImportBatch('overlap.pdf', 'overlap', transactions=second)])
        assert len(repo.transactions()) == len(first)
        assert sum(float(tx['amount']) for tx in repo.transactions()) == 107.36
    finally:
        repo.close()


def test_bank_of_scotland_multpage_statement_requires_all_pages():
    text = fixture('bank_of_scotland')
    split = text.index('31.12.2026 31.12.2026 Zinsen')
    page1 = text[:split]
    page2 = ('Bank of Scotland\nLloyds Bank GmbH\nKontonummer: 1234567890\n'
             'Buchungstag Wertstellung Beschreibung Soll Haben\n' + text[split:])
    document = PdfDocument(Path('bos.pdf'), text.encode(), 'bos-pages',
                           (PdfPage(1, page1), PdfPage(2, page2)))
    plugin = load_plugin('bank_of_scotland_kontoauszug.py')
    batch = plugin.parse(document, plugin.detect(document)[0],
                         ParseContext(ImportBatch('bos.pdf', 'bos-pages')))
    assert len(batch.transactions) == 4
    incomplete = PdfDocument(Path('bos.pdf'), text.encode(), 'bos-missing', (PdfPage(1, page1),))
    try:
        plugin.parse(incomplete, plugin.detect(incomplete)[0],
                     ParseContext(ImportBatch('bos.pdf', 'bos-missing')))
    except (IndexError, ValueError):
        pass
    else:
        raise AssertionError('fehlende Schlussseite wurde akzeptiert')
