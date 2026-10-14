from pathlib import Path
from decimal import Decimal
import pytest
from portfolio_v5.import_accounts import import_sources
from portman.excel_import import parse_excel_file
from portman.repository_v09 import RepositoryV09


EXAMPLE = Path(__file__).resolve().parents[1] / 'history/Deka/depot_übersicht.xlsx'


def test_example_subaccounts_reinvestment_and_repeat(tmp_path):
    if not EXAMPLE.exists():
        pytest.skip('Private example workbook unavailable')
    batches = parse_excel_file(EXAMPLE)
    assert [b.source_sheet for b in batches] == ['Bestaende', 'Umsaetze']
    assert not any(b.errors for b in batches)
    assert len(batches[0].snapshots) == 74
    assert len(batches[1].transactions) == 154
    assert len(import_sources(batches[0])) == 5
    assert {t.account for t in batches[1].transactions} == {s.account for s in batches[0].snapshots}
    dividends = [t for t in batches[1].transactions if t.kind == 'DIVIDEND']
    assert len(dividends) == 53
    for dividend in dividends:
        buy = next(t for t in batches[1].transactions if t.external_id == dividend.external_id.replace(':dividend', ':buy'))
        assert Decimal(buy.amount) + Decimal(dividend.amount) == 0
        assert Decimal(buy.quantity) > 0
    repo = RepositoryV09(tmp_path / 'test.sqlite', backups=False)
    try:
        assert all(r['status'] == 'imported' for r in repo.commit_batches(batches))
        before = len(repo.transactions())
        repo.commit_batches(parse_excel_file(EXAMPLE))
        assert len(repo.transactions()) == before == 154
        assert len(repo.accounts()) == 5
    finally:
        repo.close()


def test_conflicting_and_missing_values_block_sheet(tmp_path):
    path = tmp_path / 'source.xlsx'
    path.write_bytes(b'test')
    header = ['depot', 'unterdepot', 'isin', 'datum', 'anteile', 'wert_eur', 'typ']
    row = ['123', 0, 'DE0008474511', '2020-12-31', 1, 100, 'Ende']
    sheets = {'Bestand': [header, row, row[:4] + [2, 200, 'Anfang']]}
    assert 'Widersprüchliche' in parse_excel_file(path, sheets)[0].errors[0]
    sheets['Bestand'][2] = row[:1] + [None] + row[2:]
    assert 'Unterdepot' in parse_excel_file(path, sheets)[0].errors[0]


def test_reinvestment_ids_and_unknown_operations(tmp_path):
    path = tmp_path / 'source.xlsx'
    path.write_bytes(b'test')
    header = ['depot', 'unterdepot', 'isin', 'buchungstag', 'betrag_eur', 'anteile', 'umsatzart']
    row = ['123', '00', 'DE0008474511', '2020-02-21', '10,50', '0,125', 'Ausschüttung / Kauf aus Ertrag']
    batch = parse_excel_file(path, {'Umsätze': [header, row]})[0]
    assert not batch.errors
    assert [(t.kind, t.amount, t.quantity) for t in batch.transactions] == [('DIVIDEND', '10.50', None), ('BUY', '-10.50', '0.125')]
    shifted = parse_excel_file(path, {'Umsätze': [header, [None] * len(header), row]})[0]
    assert [t.external_id for t in shifted.transactions] == [t.external_id for t in batch.transactions]
    row[-1] = 'Unbekannt'
    assert parse_excel_file(path, {'Umsätze': [header, row]})[0].errors


def test_dialog_sheet_selection(tmp_path, monkeypatch):
    if not EXAMPLE.exists():
        pytest.skip('Private example workbook unavailable')
    from PySide6.QtWidgets import QApplication
    from portman import excel_import_dialog as ui
    QApplication.instance() or QApplication([])
    monkeypatch.setattr(ui, 'run_job', lambda parent, path, title, function: function(None))
    repo = RepositoryV09(tmp_path / 'ui.sqlite', backups=False)
    try:
        dialog = ui.ExcelImportDialog(repo, EXAMPLE)
        assert dialog.sheet.count() == 5
        dialog.sheet.setCurrentText('Umsaetze')
        assert dialog.preview.rowCount() == 154
        dialog.choices['Umsaetze'].setChecked(False)
        dialog.accept()
        assert [b.source_sheet for b in dialog.batches] == ['Bestaende']
        assert not repo.imports()
        dialog.close()
    finally:
        repo.close()
