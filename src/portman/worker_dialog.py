"""Shared close handling for dialogs that run a background worker thread."""


class WorkerDialogMixin:
    """Ignore close requests while the dialog's worker is still running.

    The host dialog must provide ``reject()`` and a ``worker`` attribute that is
    either ``None`` or exposes ``isRunning()``.
    """

    def closeEvent(self, event):
        self.reject()
        if self.worker and self.worker.isRunning():
            event.ignore()
        else:
            event.accept()
