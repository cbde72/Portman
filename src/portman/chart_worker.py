"""Cancelable chart calculations on a separate read-only SQLite connection."""
import logging
from PySide6.QtCore import QThread, Signal
from .chart_reader import open_chart_reader
from .chart_data import prepare_chart, prepare_chart_for_config

logger = logging.getLogger(__name__)


class ChartWorker(QThread):
    result = Signal(object)
    failed = Signal(str)

    def __init__(self, path, repository_type, mode, as_of, account, documented, parent=None,
                 data_source=None, options=None):
        super().__init__(parent)
        self.path, self.repository_type = path, repository_type
        self.mode, self.as_of, self.account, self.documented = mode, as_of, account, documented
        self.data_source = data_source
        self.options = options or {}

    def run(self):
        repo = None
        try:
            if self.isInterruptionRequested(): return
            repo = open_chart_reader(self.path, self.repository_type, self.isInterruptionRequested)
            repo.documented_only = self.documented
            version = repo.db.execute('PRAGMA data_version').fetchone()[0]
            if self.data_source is not None:
                data = prepare_chart_for_config(repo, self.data_source, self.as_of, self.account,
                                                self.options)
            else:
                data = prepare_chart(repo, self.mode, self.as_of, self.account)
            if self.isInterruptionRequested(): return
            if repo.db.execute('PRAGMA data_version').fetchone()[0] != version:
                self.result.emit(None)
            else:
                self.result.emit(data)
        except Exception as error:
            if not self.isInterruptionRequested():
                logger.exception('ChartWorker fehlgeschlagen (%s)', self.mode)
                self.failed.emit(str(error))
        finally:
            if repo is not None: repo.close()
