"""Parse files off the GUI thread; database preview and writes stay on the GUI thread."""
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from PySide6.QtCore import QThread, Signal
from portfolio_v5.importers import parse_file
from portfolio_v5.models import ImportBatch

logger = logging.getLogger(__name__)


class ImportWorker(QThread):
    progress = Signal(int, int)
    parsed = Signal(list)

    def __init__(self, paths, parent=None, history_sheets=False, document_tags=None):
        super().__init__(parent)
        self.paths = list(paths)
        self.history_sheets = history_sheets
        self.document_tags = document_tags
        self.plugin_catalog = None

    def _parse_single(self, path):
        """Parse a single file. Returns list of batches."""
        if self.history_sheets:
            from .history_import import parse_history_file, parse_savings_history_file
            parser = parse_savings_history_file if self.history_sheets == "savings" else parse_history_file
            return parser(path)
        else:
            return [parse_file(path, document_tags=self.document_tags, plugin_catalog=self.plugin_catalog)]

    def run(self):
        if not self.paths:
            self.parsed.emit([])
            return
        if not self.history_sheets and any(str(path).lower().endswith('.pdf') for path in self.paths):
            # Discovery dynamically loads every configured Python/TOML plugin.
            # Do it once per import job instead of once for every PDF.
            from portfolio_v5.pdf_plugins import discover_plugins
            self.plugin_catalog = discover_plugins()
        batches_by_path = [None] * len(self.paths)
        # Use ThreadPoolExecutor for I/O-bound parsing (PDF reading, file I/O)
        with ThreadPoolExecutor(max_workers=min(4, len(self.paths))) as executor:
            future_map = {executor.submit(self._parse_single, path): i for i, path in enumerate(self.paths)}
            completed = 0
            for future in as_completed(future_map):
                if self.isInterruptionRequested():
                    executor.shutdown(wait=False, cancel_futures=True)
                    return
                idx = future_map[future]
                try:
                    batches_by_path[idx] = future.result()
                except Exception as exc:
                    logger.exception('Datei-Parsing fehlgeschlagen: %s', self.paths[idx])
                    batches_by_path[idx] = [ImportBatch(str(self.paths[idx]), '', errors=[f'{type(exc).__name__}: {exc}'])]
                completed += 1
                self.progress.emit(completed, len(self.paths))
        if not self.isInterruptionRequested():
            # Every parser returns a list because one history file may contain
            # several sheets.  Consumers, however, operate on ImportBatch
            # objects, so flatten the per-file results while preserving the
            # original file and sheet order.
            batches = [batch for parsed in batches_by_path for batch in parsed]
            self.parsed.emit(batches)
