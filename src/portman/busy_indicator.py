"""Application-wide wait cursor for foreground work and background threads."""
from contextlib import contextmanager
from functools import wraps

from PySide6.QtCore import QObject, QEvent, QThread, QTimer, Qt
from PySide6.QtWidgets import QApplication


class BusyIndicator(QObject):
    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.depth = 0
        self.pending_input = False
        self.cursor_active = False
        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self.refresh)
        app.installEventFilter(self)
        app.aboutToQuit.connect(self.stop)
        self.timer.start()

    def running_workers(self):
        # Some legacy fetchers have no QObject parent and live in widget fields.
        workers = set(self.app.findChildren(QThread))
        for window in self.app.topLevelWidgets():
            workers.update(window.findChildren(QThread))
        for widget in self.app.allWidgets():
            workers.update(value for value in vars(widget).values() if isinstance(value, QThread))
        for worker in workers:
            try:
                if worker.isRunning():
                    return True
            except RuntimeError:
                pass  # A deleteLater() worker may still have a Python reference.
        return False

    def set_busy(self, active):
        if active == self.cursor_active:
            return
        if active:
            self.app.setOverrideCursor(Qt.CursorShape.WaitCursor)
        else:
            self.app.restoreOverrideCursor()
        self.cursor_active = active

    def refresh(self):
        self.set_busy(bool(self.depth or self.pending_input or self.running_workers()))

    def eventFilter(self, watched, event):
        # Set the native cursor BEFORE a handler can block the GUI thread.
        # A timer alone cannot update the cursor while that thread is blocked.
        if event.type() in (QEvent.Type.MouseButtonRelease, QEvent.Type.KeyPress,
                            QEvent.Type.Shortcut, QEvent.Type.Wheel):
            if not self.pending_input:
                self.pending_input = True
                self.set_busy(True)
                QTimer.singleShot(0, self.input_finished)
        return False

    def input_finished(self):
        self.pending_input = False
        self.refresh()

    def stop(self):
        self.timer.stop()
        self.app.removeEventFilter(self)
        self.set_busy(False)


def install_busy_indicator():
    app = QApplication.instance()
    if app is None:
        return None
    if not hasattr(app, '_portman_busy_indicator'):
        app._portman_busy_indicator = BusyIndicator(app)
    return app._portman_busy_indicator


@contextmanager
def busy_cursor():
    indicator = install_busy_indicator()
    if indicator is None:
        yield
        return
    indicator.depth += 1
    indicator.set_busy(True)
    try:
        yield
    finally:
        indicator.depth -= 1
        indicator.refresh()


def busy_operation(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        with busy_cursor():
            return function(*args, **kwargs)
    return wrapped
