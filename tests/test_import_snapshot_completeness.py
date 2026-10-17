from portfolio_v5.importers import parse_deka, parse_file


HEADER = ['ISIN', 'Bezeichnung', 'Anzahl', 'Wert in EUR']
APPLE = ['US0378331005', 'Apple', '1', '100,00']
MICROSOFT = ['US5949181045', 'Microsoft', '2', '200,00']


def parse_rows(tmp_path, rows, **kwargs):
    path = tmp_path / 'finanzen2026-03.csv'
    path.write_text('synthetic fixture', encoding='utf-8')
    return parse_file(path, sheets={'CSV': rows}, **kwargs)


def test_generic_position_table_is_partial_without_completeness_proof(tmp_path):
    batch = parse_rows(tmp_path, [HEADER, APPLE, MICROSOFT])
    assert not batch.errors
    assert batch.snapshots[0].complete is False
    assert any('Teilbestand' in warning for warning in batch.snapshots[0].warnings)


def test_matching_total_or_explicit_review_can_mark_snapshot_complete(tmp_path):
    proven = parse_rows(tmp_path, [HEADER, APPLE, MICROSOFT, ['Depotwert', 'EUR', '300,00']])
    assert not proven.errors and proven.snapshots[0].complete is True

    reviewed = parse_rows(tmp_path, [HEADER, APPLE], complete=True)
    assert not reviewed.errors and reviewed.snapshots[0].complete is True
    assert any('manuell bestätigt' in warning for warning in reviewed.snapshots[0].warnings)


def test_missing_position_is_rejected_by_total_and_position_count(tmp_path):
    wrong_total = parse_rows(tmp_path, [HEADER, APPLE, ['Depotwert', 'EUR', '300,00']])
    assert not wrong_total.snapshots
    assert any('Positionssumme' in warning for warning in wrong_total.warnings)

    wrong_count = parse_rows(tmp_path, [HEADER, APPLE, ['Positionszahl', '2']])
    assert not wrong_count.snapshots
    assert any('1 Positionen erkannt' in warning for warning in wrong_count.warnings)


def test_duplicate_position_prevents_snapshot_import(tmp_path):
    batch = parse_rows(tmp_path, [HEADER, APPLE, APPLE, ['Depotwert', 'EUR', '200,00']])
    assert not batch.snapshots
    assert any('Doppelte Position' in warning for warning in batch.warnings)


def test_legacy_deka_table_without_aggregate_proof_is_partial():
    rows = [
        ['ISIN', 'DE0008474511'],
        ['Bezeichnung', 'AriDeka'],
        ['Unterdepot', '01'],
        ['Bestand', '10,0'],
        ['Wert', '1.000,00'],
        ['Bewertungsdatum', '31.03.2026'],
    ]
    snapshots = parse_deka(rows, 'Deka', '2026-03')
    assert len(snapshots) == 1
    assert snapshots[0].complete is False
    assert any('Teilbestand' in warning for warning in snapshots[0].warnings)
