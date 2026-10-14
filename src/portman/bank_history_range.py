"""Shared marker for requesting all bank-provided booking history."""
from datetime import date
import json
import re

ALL_HISTORY_START = date(1900, 1, 1)


def last_history_date(repository, bank):
    if repository is None:
        return ALL_HISTORY_START
    bank = 'Baader' if bank.startswith('Baader') else bank
    import_ids = []
    latest = {}
    for row in repository.db.execute('SELECT id, path, report FROM imports WHERE active=1 ORDER BY id'):
        report = json.loads(row['report'])
        if report.get('source_sheet') != 'Online ' + bank or report.get('errors'):
            continue
        import_ids.append(row['id'])
        dates = [report['history_end']] if report.get('history_end') else []
        for warning in report.get('warnings', []) if not dates else []:
            match = re.match(r'(?:Zeitraum|Angefordert): .* bis (\d{4}-\d{2}-\d{2})', warning)
            if match:
                dates.append(match[1])
        for value in dates:
            try:
                end = date.fromisoformat(value)
            except ValueError:
                continue
            latest[row['path']] = max(latest.get(row['path'], ALL_HISTORY_START), min(end, date.today()))

    # The next request starts at the latest booking actually stored for this
    # institution. The day remains inclusive because banks can add late entries.
    if import_ids:
        placeholders = ','.join('?' for _ in import_ids)
        row = repository.db.execute(
            f'SELECT MAX(date) AS last_booking FROM transactions WHERE import_id IN ({placeholders})',
            import_ids).fetchone()
        if row and row['last_booking']:
            try:
                return min(date.fromisoformat(row['last_booking']), date.today())
            except ValueError:
                pass
    return min(latest.values(), default=ALL_HISTORY_START)


def history_start_editor(repository=None, bank=''):
    from PySide6.QtCore import QDate
    from PySide6.QtWidgets import QDateEdit
    start = last_history_date(repository, bank)
    editor = QDateEdit(QDate(start.year, start.month, start.day))
    editor.setMinimumDate(QDate(1900, 1, 1))
    editor.setSpecialValueText('Gesamte verfügbare Historie')
    editor.setToolTip('Ab dem letzten gespeicherten Buchungstag dieses Instituts, einschließlich dieses Tages. Ohne bisherige Buchung: gesamte verfügbare Historie.')
    return editor
