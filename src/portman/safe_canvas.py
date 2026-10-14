from PySide6.QtCore import QTimer
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg


class SafeFigureCanvas(FigureCanvasQTAgg):
    """Matplotlib-Canvas, der Qt-6-QWindow-Wechsel beim Docken toleriert."""
    def showEvent(self, event):
        try:
            super().showEvent(event)
        except RuntimeError as exc:
            if "QWindow" not in str(exc) or "already deleted" not in str(exc):
                raise
            QTimer.singleShot(0, self.draw_idle)
