import os
import threading

import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import QEvent, QThread, Qt
from PySide6.QtWidgets import QApplication, QWidget
from portman.busy_indicator import busy_cursor, install_busy_indicator


@pytest.fixture
def indicator():
    app = QApplication.instance() or QApplication([])
    controller = install_busy_indicator()
    yield app, controller
    controller.stop()
    del app._portman_busy_indicator
    controller.deleteLater()
    app.processEvents()


def test_nested_work_and_exception_restore_previous_cursor(indicator):
    app, controller = indicator
    app.setOverrideCursor(Qt.CursorShape.CrossCursor)
    try:
        with pytest.raises(ValueError):
            with busy_cursor():
                assert app.overrideCursor().shape() == Qt.CursorShape.WaitCursor
                with busy_cursor():
                    assert controller.depth == 2
                assert app.overrideCursor().shape() == Qt.CursorShape.WaitCursor
                raise ValueError('failure')
        assert controller.depth == 0
        assert app.overrideCursor().shape() == Qt.CursorShape.CrossCursor
    finally:
        app.restoreOverrideCursor()


def test_overlapping_workers_keep_cursor_until_all_finish(indicator):
    app, controller = indicator
    class Worker(QThread):
        def __init__(self):
            super().__init__()
            self.done = threading.Event()
        def run(self):
            self.done.wait(5)
    widget = QWidget()
    widget.first, widget.second = Worker(), Worker()
    try:
        widget.first.start()
        widget.second.start()
        controller.refresh()
        assert controller.cursor_active
        widget.first.done.set()
        assert widget.first.wait(1000)
        controller.refresh()
        assert controller.cursor_active
        widget.second.requestInterruption()
        widget.second.done.set()
        assert widget.second.wait(1000)
        controller.refresh()
        assert not controller.cursor_active
    finally:
        for worker in (widget.first, widget.second):
            worker.done.set()
            worker.wait(1000)
        widget.close()


def test_input_sets_cursor_before_handler_and_clears_after(indicator):
    app, controller = indicator
    widget = QWidget()
    controller.eventFilter(widget, QEvent(QEvent.Type.MouseButtonRelease))
    assert app.overrideCursor().shape() == Qt.CursorShape.WaitCursor
    app.processEvents()
    assert not controller.cursor_active
    widget.close()
