from threading import Event
from PySide6.QtCore import QTimer, QThread
import pytest
from portfolio_v5.models import ImportBatch, Snapshot, Position
from portman.repository_v09 import RepositoryV09
from portman.visualizations import VisualizationsWidget
from portman.chart_reader import open_chart_reader


@pytest.fixture
def repo(tmp_path):
    r = RepositoryV09(tmp_path / 'chart.sqlite', backups=False)
    r.commit_batches([ImportBatch('test', 'test', snapshots=[Snapshot('Depot', '2026-01', '2026-01-01', 'Test',
        [Position('A', 'Aktie', quantity='1', value='100')])])])
    yield r
    r.close()


def test_cold_load_returns_to_event_loop_and_never_reads_gui_repo(repo, qtbot, qapp, monkeypatch):
    from portman import chart_worker
    entered, release = Event(), Event()
    original = chart_worker.prepare_chart
    def slow(reader, *args):
        assert QThread.currentThread() != qapp.thread()
        entered.set()
        release.wait(5)
        return original(reader, *args)
    monkeypatch.setattr(chart_worker, 'prepare_chart', slow)
    monkeypatch.setattr(repo, 'account_overview', lambda *a: pytest.fail('GUI repository queried'))
    widget = VisualizationsWidget(repo, lambda: (None, '2026-02-01'))
    timer = QTimer(); ticks = []
    timer.timeout.connect(lambda: ticks.append(1)); timer.start(10)
    try:
        widget.refresh()
        qtbot.waitUntil(entered.is_set, timeout=2000)
        qtbot.waitUntil(lambda: len(ticks) >= 5, timeout=2000)
        assert widget.chart_loader.worker is not None and not widget.fig.axes
        release.set()
        qtbot.waitUntil(lambda: widget.chart_loader.worker is None, timeout=5000)
        assert widget.fig.axes, widget.note.text()
    finally:
        release.set(); timer.stop(); widget.close()
        qtbot.waitUntil(lambda: widget.chart_loader.worker is None, timeout=5000)


def test_changed_selection_discards_obsolete_result(repo, qtbot, monkeypatch):
    from portman import chart_worker
    entered, release = Event(), Event()
    original = chart_worker.prepare_chart
    calls = []
    def slow(reader, mode, day, account):
        calls.append(account)
        if len(calls) == 1: entered.set(); release.wait(5)
        return original(reader, mode, day, account)
    monkeypatch.setattr(chart_worker, 'prepare_chart', slow)
    scope = [None, '2026-02-01']
    widget = VisualizationsWidget(repo, lambda: tuple(scope))
    try:
        widget.view.setCurrentIndex(2)
        qtbot.waitUntil(entered.is_set)
        scope[0] = 'Nicht vorhanden'; widget.refresh()
        release.set()
        qtbot.waitUntil(lambda: len(calls) == 2 and widget.chart_loader.worker is None, timeout=5000)
        assert not widget.fig.axes[0].patches
        assert widget._render_key == widget.render_key()
    finally:
        release.set(); widget.close()
        qtbot.waitUntil(lambda: widget.chart_loader.worker is None, timeout=5000)


def test_cancel_does_not_restart_and_reader_cannot_write(repo, qtbot, monkeypatch):
    from portman import chart_worker
    entered, release = Event(), Event()
    def slow(*args):
        entered.set(); release.wait(5)
        return {'positions': []}
    monkeypatch.setattr(chart_worker, 'prepare_chart', slow)
    widget = VisualizationsWidget(repo, lambda: (None, '2026-02-01'))
    widget.view.setCurrentIndex(2)
    qtbot.waitUntil(entered.is_set)
    widget.cancel_chart(); release.set()
    qtbot.waitUntil(lambda: widget.chart_loader.worker is None)
    assert 'abgebrochen' in widget.note.text()
    widget.close()
    reader = open_chart_reader(repo.store.path, RepositoryV09, lambda: False)
    try:
        assert reader.db.execute('PRAGMA query_only').fetchone()[0] == 1
        with pytest.raises(Exception, match='readonly'): reader.db.execute('DELETE FROM imports')
    finally: reader.close()


def test_completed_chart_is_shared_between_views_and_invalidated_by_writes(repo, qtbot, monkeypatch):
    from portman import chart_worker
    original = chart_worker.prepare_chart
    calls = []
    def prepare(*args):
        calls.append(1)
        return original(*args)
    monkeypatch.setattr(chart_worker, 'prepare_chart', prepare)
    first = VisualizationsWidget(repo, lambda: (None, '2026-02-01'))
    second = VisualizationsWidget(repo, lambda: (None, '2026-02-01'))
    try:
        first.refresh()
        qtbot.waitUntil(lambda: first.chart_loader.worker is None, timeout=5000)
        second.view.setCurrentIndex(8)
        assert len(calls) == 1
        assert second.chart_loader.worker is None and second.fig.axes
        repo.add_balance('Depot', '200', '2026-01-20')
        second.refresh()
        qtbot.waitUntil(lambda: second.chart_loader.worker is None, timeout=5000)
        assert len(calls) == 2
    finally:
        first.close(); second.close()
