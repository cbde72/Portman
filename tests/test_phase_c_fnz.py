import importlib.util
from pathlib import Path

import pytest

from portfolio_v5.models import ImportBatch
from portfolio_v5.pdf_plugins import ParseContext, PdfDocument, PdfPage


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / 'tests' / 'fixtures' / 'importers' / 'fnz'


def plugin():
    path = ROOT / 'pdf_plugins' / 'fnz_finvesto.py'
    spec = importlib.util.spec_from_file_location('phase_c_fnz', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.plugin


def parse(relative):
    path = FIXTURES / relative / 'source.txt'
    text = path.read_text(encoding='utf-8')
    document = PdfDocument(path, text.encode(), 'fnz-fixture', (PdfPage(1, text),))
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
