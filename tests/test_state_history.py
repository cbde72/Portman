
import pytest

from portfolio_v5.models import Balance, ImportBatch, Position, Snapshot
from portfolio_v5.storage import Store


@pytest.fixture
def store(tmp_path):
    instance = Store(tmp_path / 'history.sqlite')
    yield instance
    instance.db.close()


def batch(value, day='2026-09-12', online=True):
    source = 'Online Renault Bank direkt' if online else 'CSV'
    return ImportBatch('same-source', f'{value}-{day}',
        snapshots=[Snapshot('Depot', day[:7], day, source,
                            [Position('A', 'Test', value=value)])],
        balances=[Balance(day[:7], 'Liquidität', 'Konto', value, f'{source} · {day}', 1)],
        source_sheet=source)


@pytest.mark.parametrize('online', [True, False])
def test_sync_and_file_import_preserve_all_revisions(store, online):
    first = batch('100', online=online)
    store.import_batch(first)
    store.import_batch(batch('120', online=online))
    store.import_batch(batch('140', '2026-09-13', online))
    rows = store.state_history()
    assert len(rows) == 6
    assert [r['value'] for r in rows if r['kind'] == 'Depot'] == ['100', '120', '140']
    assert store.holdings('2026-09-12')[0]['value'] == '120'
    assert store.holdings()[0]['value'] == '140'
    store.import_batch(first)
    assert len(store.state_history()) == 6
    broken = batch('0', '2026-09-14', online)
    broken.errors = ['Bankantwort ungültig']
    with pytest.raises(ValueError): store.import_batch(broken)
    assert store.state_history() == rows
    path = store.path
    store.db.close()
    store.__init__(path)
    assert store.state_history() == rows
    assert store.db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'


def test_month_precision_and_account_filter(store):
    store.import_batch(batch('100', online=False))
    assert store.state_history('Konto')[0]['date'] == '2026-09'
    store.import_batch(batch('120', '2026-09-13'))
    assert store.state_history('Konto')[-1]['date'] == '2026-09-13'


def test_partial_updates_and_empty_complete_preserve_prior_state(store):
    store.import_batch(batch('100'))
    partial = ImportBatch('partial', 'partial', snapshots=[Snapshot('Depot', '2026-09', '2026-09-13', 'CSV',
        [Position('B', 'Second', value='50')], complete=False)])
    store.import_batch(partial)
    assert {p['value'] for p in store.holdings()} == {'100', '50'}
    store.import_batch(ImportBatch('empty', 'empty', snapshots=[Snapshot('Depot', '2026-09', '2026-09-14', 'CSV')]))
    assert store.holdings() == []
    assert len(store.holdings('2026-09-13')) == 2
    assert len(store.state_history('Depot')) == 3


def test_indexes_and_backup_retain_history(store, tmp_path):
    store.import_batch(batch('100'))
    store.import_batch(batch('200'))
    plan = str([tuple(r) for r in store.db.execute("EXPLAIN QUERY PLAN SELECT id FROM imports WHERE file_hash='x' AND active=1")])
    assert 'import_duplicate_lookup' in plan
    store.backup(tmp_path / 'backup.sqlite')
    restored = Store(tmp_path / 'backup.sqlite')
    try: assert restored.state_history() == store.state_history()
    finally: restored.db.close()


def test_history_widget_displays_same_day_revisions(store):
    import os
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PySide6.QtWidgets import QApplication
    from portman.state_history_widget import StateHistoryWidget
    QApplication.instance() or QApplication([])
    store.import_batch(batch('100'))
    store.import_batch(batch('120'))
    widget = StateHistoryWidget(store, lambda: 'Depot')
    try:
        widget.refresh()
        assert widget.table.rowCount() == 2
        assert list(widget.figure.axes[0].lines[0].get_ydata()) == [100, 120]
        widget.canvas.draw()
    finally: widget.close()


def test_current_holdings_decode_only_latest_complete_baseline(store, monkeypatch):
    import json
    from datetime import date, timedelta
    for offset in range(60):
        store.import_batch(batch(str(100 + offset), (date(2026, 1, 1) + timedelta(days=offset)).isoformat()))
    store.aliases()  # Alias resolution is independently cached.
    original = json.loads
    decoded = []
    def counted(payload, *args, **kwargs):
        decoded.append(payload)
        return original(payload, *args, **kwargs)
    monkeypatch.setattr('portfolio_v5.storage.json.loads', counted)
    assert store.holdings()[0]['value'] == '159'
    assert len(decoded) == 1
    assert store.db.execute('SELECT count(*) FROM snapshots').fetchone()[0] == 60
