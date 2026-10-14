"""On-demand historical prices for present and past portfolio securities."""
from datetime import date
import re
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QCheckBox, QTableWidget, QProgressBar, QDialogButtonBox
from .price_history import historical_positions, history_plan, save_history, stored_history
from .price_history_store import latest_history_request
from .market_widget import MarketWorker
from .online_dialogs import FeedDialog
from .widgets_shared import populate
from .safe_canvas import SafeFigureCanvas
from .chart_style import style_figure, style_axis, date_axis, COLORS, create_figure


class PriceHistoryDialog(QDialog):
    def __init__(self, repo, account=None, parent=None, *, auto_start=False):
        super().__init__(parent)
        self.repo, self.account, self.worker = repo, account, None
        self.setWindowTitle('Gespeicherte Kursverläufe · ab erstem Bestand')
        self.resize(1150, 820)
        layout = QVBoxLayout(self)
        hint = QLabel('Tageskurse ab dem ersten Kauf beziehungsweise Bestand bis gestern. Eine manuell geänderte „Erste Aktivität“ hat Vorrang. '
            'Alle geladenen Kurse werden automatisch dauerhaft gespeichert und sind danach offline verfügbar. '
            'Vorhandene Zeiträume werden lokal gelesen; „Fehlende Zeiträume laden“ fragt nur noch nicht geprüfte Zeiträume ab. '
            'Die verfügbare Historie hängt vom Anbieter ab. Angezeigt werden Schlusskurse in Originalwährung, keine Depot-Rendite.')
        hint.setWordWrap(True); layout.addWidget(hint)
        bar = QHBoxLayout(); layout.addLayout(bar)
        self.all_accounts = QCheckBox('Alle Konten und Depots')
        self.all_accounts.setChecked(account is None)
        self.all_accounts.toggled.connect(self.refresh)
        bar.addWidget(self.all_accounts)
        self.load = QPushButton('Fehlende Zeiträume laden'); self.load.clicked.connect(lambda: self.start(False)); bar.addWidget(self.load)
        self.force = QPushButton('Auswahl vollständig neu laden'); self.force.clicked.connect(lambda: self.start(True)); bar.addWidget(self.force)
        self.source = QPushButton('Kursquelle wählen …'); self.source.clicked.connect(self.choose_source); bar.addWidget(self.source)
        self.cancel = QPushButton('Abruf abbrechen'); self.cancel.clicked.connect(self.stop); self.cancel.setEnabled(False); bar.addWidget(self.cancel)
        self.table = QTableWidget()
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.itemSelectionChanged.connect(self.show_chart)
        layout.addWidget(self.table, 1)
        self.fig = create_figure(10, 3); style_figure(self.fig)
        self.canvas = SafeFigureCanvas(self.fig); layout.addWidget(self.canvas, 1)
        self.progress = QProgressBar(); self.progress.hide(); layout.addWidget(self.progress)
        self.status = QLabel(); self.status.setWordWrap(True); self.status.setTextFormat(Qt.TextFormat.PlainText); layout.addWidget(self.status)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject); layout.addWidget(buttons)
        self.refresh()
        if auto_start: QTimer.singleShot(0, self.start)

    def refresh(self):
        self.positions = historical_positions(self.repo, None if self.all_accounts.isChecked() else self.account)
        self.saved = {}
        mappings = self.repo.market.mappings()
        metadata = self.repo.metadata()
        rows = []
        for p in self.positions:
            data = stored_history(self.repo, p['key'], p['history_start'], mapping=mappings.get(p['key'], {}))
            self.saved[p['key']] = data
            prices = data['prices']
            attempt = latest_history_request(self.repo.db, p['key'], mappings.get(p['key'], {}))
            candidates = (metadata.get(p['key'], {}).get('isin'), p.get('isin'), p['key'].removeprefix('ISIN:'))
            isin = next((value for value in candidates if value and re.fullmatch(r'[A-Z]{2}[A-Z0-9]{9}[0-9]', value)), '–')
            rows.append([p['name'], isin, p['history_start'], data['symbol'],
                prices[0]['date'] if prices else '–', prices[-1]['date'] if prices else '–', len(prices), data['currency'],
                attempt['message'] if attempt else 'Noch nicht geladen'])
        selected = self.table.currentRow()
        self.table.blockSignals(True)
        populate(self.table, ['Wertpapier', 'ISIN', 'Erster Bestand', 'Symbol', 'Kurse ab', 'Kurse bis', 'Tageskurse', 'Währung', 'Abrufstatus'], rows)
        self.table.blockSignals(False)
        if rows: self.table.selectRow(min(max(0, selected), len(rows) - 1))
        self.show_chart()

    def show_chart(self):
        row = self.table.currentRow()
        self.fig.clear(); style_figure(self.fig)
        axis = self.fig.add_subplot(111); style_axis(axis)
        if 0 <= row < len(self.positions):
            p = self.positions[row]; data = self.saved[p['key']]
            if data['prices']:
                axis.plot([date.fromisoformat(v['date']) for v in data['prices']], [v['close'] for v in data['prices']], color=COLORS['blue'], linewidth=1.4)
                date_axis(axis); axis.set_ylabel(data['currency'])
            else: axis.text(.5, .5, 'Noch keine Kursdaten gespeichert.', ha='center', transform=axis.transAxes)
            axis.set_title(p['name'] + ' · ' + data['provider'], loc='left')
        self.fig.set_layout_engine('constrained'); self.canvas.draw_idle()

    def choose_source(self):
        row = self.table.currentRow()
        if 0 <= row < len(self.positions):
            if FeedDialog(self.repo.market, self.positions[row], self).exec(): self.refresh()

    def start(self, force=False):
        if self.worker and self.worker.isRunning(): return
        positions = self.positions
        if force:
            row = self.table.currentRow()
            if not 0 <= row < len(positions): return
            positions = [positions[row]]
        tasks = history_plan(self.repo, positions, force=force)
        if not tasks:
            self.status.setText('Alle angefragten Zeiträume sind bereits gespeichert beziehungsweise geprüft. Kein Internetabruf nötig.'); return
        self.mappings = self.repo.market.mappings()
        try:
            keys = {provider: self.repo.market.credentials.get(provider) for provider in
                    {self.mappings.get(p['key'], {}).get('provider', 'yahoo') for p in tasks}}
        except ValueError as error:
            self.status.setText(str(error)); return
        self.completed, self.errors = 0, 0
        for button in (self.load, self.force, self.source, self.all_accounts): button.setEnabled(False)
        self.cancel.setEnabled(True); self.progress.setRange(0, len(tasks)); self.progress.setValue(0); self.progress.show()
        self.worker = MarketWorker(tasks, self.mappings, self, keys=keys, usage=self.repo.market.daily_usage(), history=True)
        self.worker.usage.connect(self.repo.market.record_usage)
        self.worker.observation.connect(self.save_result)
        self.worker.progress.connect(lambda i, total, name: self.status.setText(f'{i + 1}/{total} · {name}'))
        self.worker.finished.connect(self.download_finished)
        self.worker.start()

    def save_result(self, result):
        try:
            result = save_history(self.repo, result, self.mappings.get(result['security_key'], {}))
            if result['status'] != 'ok': self.errors += 1
        except Exception as error:
            self.errors += 1
            self.status.setText('Speichern fehlgeschlagen: ' + str(error))
        self.completed += 1
        self.progress.setValue(self.completed)

    def download_finished(self):
        for button in (self.load, self.force, self.source, self.all_accounts): button.setEnabled(True)
        self.cancel.setEnabled(False); self.progress.hide(); self.refresh()
        self.status.setText(f'{self.completed} Zeiträume bearbeitet · {self.errors} Fehler / offene Zuordnungen. '
            'Gespeicherte Kurse bleiben erhalten.' + (' Abruf abgebrochen.' if self.worker.isInterruptionRequested() else ''))

    def stop(self):
        if self.worker: self.worker.requestInterruption()
        self.status.setText('Abbruch nach der laufenden Anfrage …')

    def reject(self):
        if self.worker and self.worker.isRunning(): self.stop(); return
        super().reject()

    def closeEvent(self, event):
        if self.worker and self.worker.isRunning(): self.stop(); event.ignore(); return
        super().closeEvent(event)
