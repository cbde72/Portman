import pytest
from openpyxl import Workbook

from portman.history_import import parse_history_file


@pytest.mark.parametrize('bank', ['ING', 'comdirect', 'ZERO'])
@pytest.mark.parametrize('mode', ['explicit', 'quote', 'missing', 'conflict'])
def test_history_uses_sheet_date_not_filename(tmp_path, bank, mode):
    path = tmp_path / 'finanzen2026-09-29.xlsx'
    book = Workbook()
    sheet = book.active
    sheet.title = bank
    if mode in ('explicit', 'conflict'):
        sheet.append(['Stichtag', '12.08.2026'])
    if mode == 'conflict': sheet.append(['Stand', '13.08.2026'])
    sheet.append(['ISIN', 'Name', 'Anzahl', 'Wert', 'Kursdatum'])
    sheet.append(['DE0000000001', 'Beispiel', '2', '100', '11.08.2026' if mode != 'missing' else ''])
    book.save(path)
    book.close()
    batch = parse_history_file(path)[0]
    if mode in ('missing', 'conflict'):
        assert batch.errors
        assert not batch.snapshots
    else:
        assert not batch.errors
        assert batch.snapshots[0].as_of == ('2026-08-12' if mode == 'explicit' else '2026-08-11')
        assert batch.snapshots[0].period == '2026-08'
        assert batch.snapshots[0].date_basis == ('document' if mode == 'explicit' else 'quote')
