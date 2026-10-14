"""Latest-request-wins scheduling and bounded caching for chart workers."""
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication
from .chart_worker import ChartWorker


class ChartLoader(QObject):
    ready = Signal(object, object)
    failed = Signal(str)
    busy = Signal(bool)
    retry = Signal()

    def __init__(self, parent=None, cache=None):
        super().__init__(parent)
        self.worker = None
        self.cache = cache if cache is not None else {}
        self._pending_data_source = None
        self.wanted = None

    def request(self, key, arguments):
        self._pending_data_source = arguments.get('data_source') if arguments else None
        self.wanted = (key, arguments)
        if key in self.cache:
            self.cancel()
            self.ready.emit(key, self.cache[key])
        elif self.worker is not None:
            if self.active_key != key: self.worker.requestInterruption()
        else:
            self.start_pending()

    def start_pending(self):
        self.active_key, arguments = self.wanted
        self.result, self.error = None, None
        self.worker = ChartWorker(**arguments, parent=QApplication.instance())
        self.worker.result.connect(self.receive_result)
        self.worker.failed.connect(self.receive_error)
        self.worker.finished.connect(self.finish_request)
        self.worker.finished.connect(self.worker.deleteLater)
        self.destroyed.connect(self.worker.requestInterruption)
        self.busy.emit(True)
        self.worker.start()

    def receive_result(self, data):
        self.result = data

    def receive_error(self, message):
        self.error = message

    def finish_request(self):
        cancelled = self.worker.isInterruptionRequested()
        self.worker = None
        self.busy.emit(False)
        if self.wanted is None: return
        if self.wanted[0] != self.active_key or cancelled:
            self.start_pending()
            return
        self.wanted = None
        if self.error:
            self.failed.emit(self.error)
        elif self.result is None:
            self.retry.emit()
        else:
            if len(self.cache) >= 4: self.cache.pop(next(iter(self.cache)))
            self.cache[self.active_key] = self.result
            self.ready.emit(self.active_key, self.result)
        self._pending_data_source = None

    def cancel(self):
        self.wanted = None
        if self.worker is not None: self.worker.requestInterruption()

    def shutdown(self):
        """Stop the reader and release its SQLite handle before its view closes."""
        self.cancel()
        worker = self.worker
        if worker is not None:
            worker.wait(3000)
