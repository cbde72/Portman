"""Inspect every retained balance/depot revision, including same-day imports."""
from datetime import date
from decimal import Decimal

from PySide6.QtWidgets import QComboBox, QLabel, QVBoxLayout, QWidget, QAbstractItemView

from .safe_canvas import SafeFigureCanvas
from .chart_style import style_figure, style_axis, currency_axis, date_axis, create_figure


class StateHistoryWidget(QWidget):
    def __init__(self, repository, account_getter, parent=None):
        super().__init__(parent)
        from .history_widget import table
        self.repo, self.account_getter = repository, account_getter
        layout = QVBoxLayout(self)
        label = QLabel('Alle gespeicherten Import- und Synchronisationsstände bleiben nachvollziehbar. '
                       'Wertänderungen enthalten auch Ein- und Auszahlungen. Monatsstände haben keinen bekannten Tag.')
        label.setWordWrap(True)
        layout.addWidget(label)
        self.series = QComboBox()
        layout.addWidget(self.series)
        self.figure = create_figure()
        style_figure(self.figure)
        self.canvas = SafeFigureCanvas(self.figure)
        layout.addWidget(self.canvas)
        self.table = table(['Stand', 'Gespeichert (UTC)', 'Konto', 'Quelle/Kategorie', 'Wert', 'Status', 'Import'])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        layout.addWidget(self.table)
        self.series.currentIndexChanged.connect(self.draw)
        self.rows = []

    def refresh(self):
        self.rows = self.repo.state_history(self.account_getter())
        selected = self.series.currentData()
        self.series.blockSignals(True)
        self.series.clear()
        for key in sorted({(r['account'], r['source_account'], r['kind']) for r in self.rows}):
            self.series.addItem(' · '.join(key), key)
        index = self.series.findData(selected)
        self.series.setCurrentIndex(max(0, index))
        self.series.blockSignals(False)
        self.draw()

    def draw(self):
        from .history_widget import fill, euro
        key = self.series.currentData()
        rows = [r for r in self.rows if (r['account'], r['source_account'], r['kind']) == key]
        fill(self.table, [(r['date'], r['imported_at'][:19], r['account'], r['kind'], euro(r['value']),
                          'gespeichert' if r['active'] else 'zurückgenommen/ausgeschlossen', r['import_id']) for r in rows])
        self.figure.clear()
        ax = self.figure.add_subplot(111)
        for monthly in (False, True):
            points = [r for r in rows if r['active'] and r['value'] is not None and (len(r['date']) == 7) == monthly]
            if points:
                dates = [date.fromisoformat(r['date'] + '-01' if monthly else r['date']) for r in points]
                ax.plot(dates, [float(Decimal(r['value'])) for r in points], marker='o',
                        linestyle='--' if monthly else '-', label='Monatsstände' if monthly else 'Datierte Stände')
        if ax.lines: ax.legend()
        ax.set_title('Gespeicherte Werte' if not key else key[2])
        style_axis(ax)
        currency_axis(ax)
        date_axis(ax)
        self.figure.subplots_adjust(left=.15, bottom=.2, top=.88, right=.97)
        self.canvas.draw_idle()
