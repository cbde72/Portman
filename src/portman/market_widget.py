from .date_display import display_dates
from .date_edit import DateLineEdit
import http.client
import logging
import time
from datetime import date
from xml.etree.ElementTree import ParseError
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QTableWidget, QTableWidgetItem, QHeaderView, QSplitter, QDialog, QDialogButtonBox,
    QFormLayout, QMessageBox, QProgressBar, QTabWidget)
from .market_data import utcnow
from .online_providers import PROVIDERS, MarketProvider, DivvyDiaryProvider
from .online_dialogs import FeedDialog, OnlineCredentialsDialog
from .safe_canvas import SafeFigureCanvas
from .chart_style import COLORS, style_figure, style_axis, date_axis, create_figure

logger = logging.getLogger(__name__)


FIELDS = {'price': 'Letzter Kurs', 'day_change_pct': 'Tagesänderung %', 'return_1m_pct': 'Entwicklung 1 Monat %',
          'return_3m_pct': 'Entwicklung 3 Monate %', 'return_1y_pct': 'Entwicklung 1 Jahr %',
          'volatility_pct': 'Volatilität annualisiert %', 'max_drawdown_pct': 'Max. Rückgang im Beobachtungsjahr %',
          'high_52w': '52-Wochen-Hoch', 'low_52w': '52-Wochen-Tief', 'ma_50': 'Durchschnitt 50 Tage',
          'ma_200': 'Durchschnitt 200 Tage', 'volume': 'Handelsvolumen', 'market_cap': 'Marktkapitalisierung',
          'pe': 'KGV', 'beta': 'Beta', 'dividend_yield_pct': 'Dividendenrendite %', 'ter_pct': 'ETF-Kostenquote TER %',
          'sector': 'Sektor', 'country': 'Land', 'currency': 'Kurswährung'}
MANUAL_FIELDS = ['price', 'currency', 'pe', 'beta', 'dividend_yield_pct', 'ter_pct', 'market_cap', 'sector', 'country']


def value_text(value):
    if value is None: return '–'
    if isinstance(value, (int, float)): return f'{value:,.2f}'.replace(',', 'X').replace('.', ',').replace('X', '.')
    return str(value)


class MarketWorker(QThread):
    observation = Signal(object)
    fx_observation = Signal(object)
    usage = Signal(str)
    progress = Signal(int, int, str)
    last_request = {}

    def __init__(self, positions, mappings, parent=None, keys=None, usage=None, dividends=False, history=False):
        super().__init__(parent)
        self.positions, self.mappings = positions, mappings
        self.keys, self.budget = keys or {}, dict(usage or {})
        self.dividends = dividends
        self.history = history

    def emit_observation(self, position, result):
        if self.history:
            result = {**result, 'history_start': position['history_start'], 'history_end': position['history_end']}
        self.observation.emit(result)

    def run(self):
        if not self.dividends and not self.history:
            from .valuation import fetch_fx
            try:
                self.fx_observation.emit(fetch_fx())
            except (OSError, ValueError, http.client.HTTPException, ParseError):
                pass
            except Exception:
                logger.exception('Unerwarteter Fehler beim FX-Abruf')
        blocked = {}
        budget_day = utcnow()[:10]
        for index, position in enumerate(self.positions):
            if self.isInterruptionRequested(): break
            if budget_day != utcnow()[:10]:
                self.budget.clear(); budget_day = utcnow()[:10]
            mapping = self.mappings.get(position['key'], {})
            provider_id = 'divvydiary' if self.dividends else mapping.get('provider', 'yahoo')
            info = PROVIDERS.get(provider_id, {'name': 'DivvyDiary', 'interval': 1, 'daily': 0})
            base = {'security_key': position['key'], 'attempted_at': utcnow(), 'status': 'error', 'provider_id': provider_id, 'provider': info['name']}
            self.progress.emit(index, len(self.positions), position['name'])
            if provider_id in blocked:
                self.emit_observation(position, {**base, 'message': blocked[provider_id]}); continue
            limit = info['daily']
            if limit and self.budget.get(provider_id, 0) >= limit:
                self.emit_observation(position, {**base, 'message': 'Lokales Tageskontingent erreicht. Morgen erneut abrufen oder eine andere Quelle wählen.'}); continue
            provider = DivvyDiaryProvider(self.keys.get(provider_id, '')) if self.dividends else MarketProvider(provider_id, self.keys.get(provider_id, ''))
            # Invalid configuration never consumes the local request budget.
            ready = bool(self.keys.get(provider_id)) if self.dividends else (not info.get('key') or bool(self.keys.get(provider_id)))
            ready = ready and (bool(position.get('isin')) if self.dividends else provider_id == 'yahoo' or bool(mapping.get('symbol') and mapping.get('currency')))
            if ready:
                remaining = self.last_request.get(provider_id, 0) + info['interval'] - time.monotonic()
                if remaining > 0:
                    self.progress.emit(index, len(self.positions), position['name'] + ' · warte auf Anbieter-Kontingent')
                while remaining > 0 and not self.isInterruptionRequested():
                    self.msleep(min(100, max(1, int(remaining * 1000))))
                    remaining = self.last_request.get(provider_id, 0) + info['interval'] - time.monotonic()
                if self.isInterruptionRequested(): break
                self.last_request[provider_id] = time.monotonic()
                self.budget[provider_id] = self.budget.get(provider_id, 0) + 1
                self.usage.emit(provider_id)
            result = provider.fetch(position) if self.dividends else provider.fetch(position, mapping)
            if result.get('stop_provider'): blocked[provider_id] = result['message']
            self.emit_observation(position, result)
        self.keys.clear()


class ManualMetricsDialog(QDialog):
    def __init__(self, old, parent=None):
        super().__init__(parent); self.setWindowTitle('Kennzahlen hinterlegen'); self.resize(490, 530)
        layout = QVBoxLayout(self); form = QFormLayout(); self.fields = {}
        for key in MANUAL_FIELDS:
            edit = QLineEdit(str(old.get('fields', {}).get(key, ''))); self.fields[key] = edit; form.addRow(FIELDS[key], edit)
        self.source = QLineEdit(old.get('source', '')); self.source.setPlaceholderText('z. B. Fonds-Factsheet / URL')
        self.as_of = DateLineEdit(old.get('as_of', date.today().isoformat()))
        form.addRow('Quelle', self.source); form.addRow('Datenstand (TT.MM.JJJJ)', self.as_of); layout.addLayout(form)
        note = QLabel('Leere Felder bleiben unbekannt. Zahlen ohne Tausendertrennzeichen eingeben. Manuelle Kennzahlen bleiben bei Online-Aktualisierungen erhalten.')
        note.setWordWrap(True); layout.addWidget(note)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept); buttons.rejected.connect(self.reject); layout.addWidget(buttons)


class MarketWidget(QWidget):
    changed = Signal()

    def __init__(self, repository, scope_getter, parent=None):
        super().__init__(parent); self.repo = repository; self.scope_getter = scope_getter; self.worker = None
        self.records = {}; self.positions = []; self.counts = {}
        root = QVBoxLayout(self); root.setContentsMargins(18, 8, 18, 14)
        title = QLabel('Wertpapierdaten & Kennzahlen'); title.setObjectName('pageTitle'); root.addWidget(title)
        note = QLabel('Öffentliche Marktdaten, unabhängig vom historischen Datum. Originalwährung und Börsenzeit bleiben erhalten. Depotstände werden nicht überschrieben.')
        note.setWordWrap(True); note.setObjectName('muted'); root.addWidget(note)
        bar = QHBoxLayout()
        self.search = QLineEdit(); self.search.setPlaceholderText('Name, ISIN oder Symbol suchen …'); self.search.textChanged.connect(self.filter_rows)
        self.all_button = QPushButton('Alle Depotwerte aktualisieren'); self.all_button.setObjectName('primary'); self.all_button.clicked.connect(lambda: self.start())
        self.one_button = QPushButton('Auswahl aktualisieren'); self.one_button.clicked.connect(self.update_selected)
        self.cancel_button = QPushButton('Abbrechen'); self.cancel_button.setEnabled(False); self.cancel_button.clicked.connect(self.cancel)
        for w in (self.search, self.all_button, self.one_button, self.cancel_button): bar.addWidget(w)
        root.addLayout(bar)
        self.history_button = QPushButton('Historische Kursverläufe …')
        self.history_button.clicked.connect(self.open_history)
        bar.addWidget(self.history_button)
        self.progress = QProgressBar(); self.progress.hide(); root.addWidget(self.progress)
        splitter = QSplitter(Qt.Orientation.Vertical)
        self.table = QTableWidget(0, 9)
        self.table.setHorizontalHeaderLabels(['Wertpapier / ISIN', 'Symbol', 'Kurs', 'Währung', '1 Jahr %', 'Vola. %', 'Kursdatum / Zeit UTC', 'Abrufstatus', 'Kursquelle'])
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True); self.table.verticalHeader().hide()
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.itemSelectionChanged.connect(self.show_details); splitter.addWidget(self.table)
        self.tabs = QTabWidget()
        detail = QWidget(); detail_layout = QVBoxLayout(detail)
        actions = QHBoxLayout()
        self.symbol_button = QPushButton('Kursquelle wählen …'); self.symbol_button.clicked.connect(self.set_symbol)
        self.manual_button = QPushButton('Kennzahlen hinterlegen …'); self.manual_button.clicked.connect(self.edit_manual)
        actions.addWidget(self.symbol_button); actions.addWidget(self.manual_button); actions.addStretch(); detail_layout.addLayout(actions)
        self.detail_note = QLabel('Wertpapier auswählen.'); self.detail_note.setWordWrap(True); self.detail_note.setTextFormat(Qt.TextFormat.PlainText)
        detail_layout.addWidget(self.detail_note)
        self.metrics = QTableWidget(0, 4); self.metrics.setHorizontalHeaderLabels(['Kennzahl', 'Wert', 'Quelle / Berechnung', 'Datenstand'])
        self.metrics.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.metrics.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch); self.metrics.verticalHeader().hide()
        detail_layout.addWidget(self.metrics); self.tabs.addTab(detail, 'Kennzahlen & Quellen')
        self.fig = create_figure(10, 3); style_figure(self.fig); self.canvas = SafeFigureCanvas(self.fig)
        self.tabs.addTab(self.canvas, 'Kursverlauf')
        dividend_page = QWidget(); dividend_layout = QVBoxLayout(dividend_page)
        dividend_note = QLabel('DivvyDiary · Ausschüttungsbetrag je Aktie / Anteil in Originalwährung. Termine sind keine Kontobuchungen und bestätigen keinen persönlichen Zahlungsanspruch.')
        dividend_note.setWordWrap(True); dividend_layout.addWidget(dividend_note)
        dividend_bar = QHBoxLayout()
        self.dividend_all_button = QPushButton('Dividenden im angezeigten Depot abrufen')
        self.dividend_all_button.clicked.connect(lambda: self.start(self.positions, dividends=True))
        self.dividend_one_button = QPushButton('Dividenden für Auswahl abrufen')
        self.dividend_one_button.clicked.connect(lambda: self.start([self.selected()], dividends=True) if self.selected() else None)
        dividend_bar.addWidget(self.dividend_all_button); dividend_bar.addWidget(self.dividend_one_button)
        dividend_layout.addLayout(dividend_bar)
        self.dividend_table = QTableWidget(0, 7)
        self.dividend_table.setHorizontalHeaderLabels(['Wertpapier', 'Ex-Tag', 'Zahltag', 'Betrag / Anteil', 'Währung', 'Abrufstatus', 'Daten abgerufen'])
        self.dividend_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.dividend_table.setAlternatingRowColors(True)
        self.dividend_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        dividend_layout.addWidget(self.dividend_table); self.tabs.addTab(dividend_page, 'Dividenden · DivvyDiary')
        self.history_table = QTableWidget(0, 5)
        self.history_table.setHorizontalHeaderLabels(['Abruf', 'Quelle', 'Symbol', 'Kurs', 'Währung'])
        self.history_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.history_table.setAlternatingRowColors(True)
        self.tabs.addTab(self.history_table, 'Abrufhistorie')
        splitter.addWidget(self.tabs); splitter.setSizes([420, 300]); root.addWidget(splitter, 1)
        self.status = QLabel(''); self.status.setWordWrap(True); root.addWidget(self.status)
        self.refresh()

    def selected(self):
        row = self.table.currentRow()
        return self.positions[row] if 0 <= row < len(self.positions) else None

    def refresh(self):
        if getattr(self.repo,'defer_initial_views',False): return
        old = self.selected(); old_key = old['key'] if old else None
        self.positions = self.repo.current(account=self.scope_getter()[0])
        self.records = self.repo.market.records(); mappings = self.repo.market.mappings()
        self.table.blockSignals(True); self.table.setRowCount(len(self.positions)); selected_row = 0
        for row, p in enumerate(self.positions):
            record = self.records.get(p['key'], {}); data = record.get('data', {}); metrics = data.get('metrics', {}); attempt = record.get('attempt', {})
            status = {'ok': 'Gespeichert', 'error': 'Abruf fehlgeschlagen', 'mapping_needed': 'Zuordnung prüfen'}.get(attempt.get('status'), 'Noch nicht abgerufen')
            if data and attempt.get('status') == 'error': status = 'Letzter guter Stand'
            mapping = mappings.get(p['key'], {})
            manual = record.get('manual', {})
            manual_price = manual.get('fields', {}).get('price')
            if manual_price is not None: status += ' · manueller Kurs'
            values = [p['name'] + '\n' + (p.get('isin') or p['key']), mapping.get('symbol', ''), value_text(metrics.get('price')),
                      data.get('currency', ''), value_text(metrics.get('return_1y_pct')), value_text(metrics.get('volatility_pct')),
                      data.get('quote_time', '').replace('T', ' ')[:19], status, PROVIDERS.get(mapping.get('provider', 'yahoo'), {}).get('name', 'Unbekannt')]
            if manual_price is not None:
                values[2] = value_text(manual_price); values[3] = manual['fields'].get('currency', ''); values[6] = manual['as_of']
            for col, value in enumerate(values):
                item = QTableWidgetItem(display_dates(value)); item.setToolTip(display_dates(attempt.get('message', '')))
                self.table.setItem(row, col, item)
            if p['key'] == old_key: selected_row = row
        self.table.resizeRowsToContents()
        for col in range(1, 9): self.table.resizeColumnToContents(col)
        self.table.blockSignals(False)
        if self.positions: self.table.selectRow(selected_row)
        self.filter_rows(); self.show_details(); self.refresh_dividends()

    def filter_rows(self):
        query = self.search.text().casefold()
        for row in range(self.table.rowCount()):
            self.table.setRowHidden(row, query not in (self.table.item(row, 0).text() + ' ' + self.table.item(row, 1).text()).casefold())

    def show_details(self):
        p = self.selected(); self.metrics.setRowCount(0); self.history_table.setRowCount(0); self.fig.clear(); style_figure(self.fig)
        if not p: self.detail_note.setText('Wertpapier auswählen.'); self.canvas.draw_idle(); return
        history = self.repo.market.observation_history(p['key'])[:200]
        self.history_table.setRowCount(len(history))
        for row, h in enumerate(history):
            for col, value in enumerate([h.get('attempted_at', ''), h.get('provider', ''), h.get('symbol', ''), value_text(h.get('metrics', {}).get('price')), h.get('currency', '')]):
                self.history_table.setItem(row, col, QTableWidgetItem(display_dates(value)))
        self.history_table.resizeColumnsToContents()
        record = self.records.get(p['key'], {}); data = record.get('data', {}); manual = record.get('manual', {})
        self.detail_note.setText(display_dates(f"{p['name']} · {data.get('exchange', 'Börsenplatz noch offen')} · {data.get('currency', '')}\n"
                                 + (data.get('calculation') or 'KGV, TER, Beta und weitere Fundamentaldaten können mit Quelle ergänzt werden.')))
        entries = []
        for key, label in FIELDS.items():
            if key in manual.get('fields', {}):
                entries.append((label, value_text(manual['fields'][key]), manual['source'], manual['as_of']))
            else:
                value = data.get('currency') if key == 'currency' else data.get('metrics', {}).get(key)
                calculated = key.startswith(('return_', 'ma_')) or key in {'volatility_pct', 'max_drawdown_pct'}
                entries.append((label, value_text(value), (('Berechnet · ' if calculated else '') + data.get('provider', 'Yahoo Finance')) if value is not None else 'Nicht verfügbar', data.get('quote_time', '')[:10] if value is not None else ''))
        self.metrics.setRowCount(len(entries))
        for row, values in enumerate(entries):
            for col, value in enumerate(values): self.metrics.setItem(row, col, QTableWidgetItem(display_dates(value)))
        for col in (0, 1, 3): self.metrics.resizeColumnToContents(col)
        axis = self.fig.add_subplot(111); style_axis(axis)
        prices = data.get('prices', [])
        from .price_history import historical_positions, stored_history
        first = next((v['history_start'] for v in historical_positions(self.repo, self.scope_getter()[0]) if v['key'] == p['key']), None)
        if first:
            saved = stored_history(self.repo, p['key'], first)
            prices = saved['prices'] or [v for v in prices if v['date'] >= first]
            if saved['prices']: data = {**data, **saved}
        if prices:
            axis.plot([date.fromisoformat(p['date']) for p in prices], [p['close'] for p in prices], color=COLORS['blue'], linewidth=1.7)
            date_axis(axis); axis.set_ylabel(data.get('currency', ''), color=COLORS['text'])
            axis.set_title(f"{data['symbol']} · Schlusskurse", loc='left', color=COLORS['text'])
        else: axis.text(.5, .5, 'Noch keine Kurshistorie gespeichert.', ha='center', color=COLORS['muted'], transform=axis.transAxes)
        self.fig.set_layout_engine('constrained'); self.canvas.draw_idle()

    def start(self, positions=None, dividends=False, incremental=False):
        if self.worker and self.worker.isRunning(): return
        positions = self.repo.current() if positions is None else positions
        if not positions: self.status.setText('Zuerst einen Depotbestand importieren.'); return
        self.incremental_mode = incremental
        if incremental:
            from .price_history import historical_positions, history_plan
            positions = history_plan(self.repo, historical_positions(self.repo))
            if not positions:
                self.status.setText('Kurse sind bereits aktuell. Keine neuen Zeiträume abzurufen.'); return
        mappings = self.repo.market.mappings()
        provider_ids = {'divvydiary'} if dividends else {mappings.get(p['key'], {}).get('provider', 'yahoo') for p in positions}
        try: keys = {p: self.repo.market.credentials.get(p) for p in provider_ids}
        except ValueError as exc:
            self.status.setText(str(exc)); return
        self.counts = {'ok': 0, 'error': 0, 'mapping_needed': 0}
        self.dividends_mode = dividends
        for button in (self.dividend_all_button, self.dividend_one_button): button.setEnabled(False)
        self.all_button.setEnabled(False); self.one_button.setEnabled(False); self.symbol_button.setEnabled(False)
        self.cancel_button.setEnabled(True); self.progress.setRange(0, len(positions)); self.progress.setValue(0); self.progress.show()
        self.worker = MarketWorker(list(positions), mappings, self, keys=keys, usage=self.repo.market.daily_usage(), dividends=dividends, history=incremental)
        self.worker.usage.connect(self.repo.market.record_usage)
        self.worker.observation.connect(self.save_observation)
        self.worker.fx_observation.connect(self.repo.market.save_fx)
        self.worker.progress.connect(lambda i, total, name: self.status.setText(display_dates(f'{i + 1}/{total}: {name}')))
        self.worker.finished.connect(self.finished); self.worker.start()

    def update_selected(self):
        if self.selected(): self.start([self.selected()])

    def save_observation(self, result):
        if getattr(self, 'incremental_mode', False):
            from .price_history import save_history, stored_history
            from .online_providers import history_result
            try:
                mapping = self.repo.market.mappings().get(result['security_key'], {})
                result = save_history(self.repo, result, mapping)
                if result['status'] == 'ok':
                    mapping = self.repo.market.mappings().get(result['security_key'], {})
                    saved = stored_history(self.repo, result['security_key'], '1900-01-01', mapping=mapping)
                    if saved['prices']:
                        merged = history_result({'name': result.get('name', result['security_key'])}, mapping,
                            mapping.get('provider', 'yahoo'), saved['prices'], saved['currency'])
                        self.repo.market.save_result({**result, **merged}, retain_history=False)
            except (ValueError, KeyError) as error:
                result = {**result, 'status': 'error', 'message': str(error)}
                self.status.setText('Kursdaten konnten nicht übernommen werden: ' + str(error))
        elif self.dividends_mode: self.repo.market.save_dividends(result)
        else: self.repo.market.save_result(result)
        self.counts[result['status']] += 1
        self.progress.setValue(sum(self.counts.values()))

    def finished(self):
        for button in (self.dividend_all_button, self.dividend_one_button): button.setEnabled(True)
        self.all_button.setEnabled(True); self.one_button.setEnabled(True); self.symbol_button.setEnabled(True)
        self.cancel_button.setEnabled(False); self.progress.hide(); self.refresh(); self.changed.emit()
        self.status.setText(display_dates(f"{self.counts['ok']} aktualisiert · {self.counts['mapping_needed']} Zuordnungen offen · {self.counts['error']} Abruffehler. Vorhandene gute Daten bleiben bei Fehlern erhalten."))

    def cancel(self):
        if self.worker: self.worker.requestInterruption(); self.status.setText('Abbruch nach der laufenden Anfrage …')

    def configure_credentials(self):
        OnlineCredentialsDialog(self.repo.market, self).exec()

    def open_history(self, checked=False, *, auto_start=False):
        if self.worker and self.worker.isRunning():
            self.status.setText('Bitte den laufenden Abruf zuerst beenden.'); return
        from .price_history_dialog import PriceHistoryDialog
        PriceHistoryDialog(self.repo, self.scope_getter()[0], self, auto_start=auto_start).exec()
        self.refresh(); self.changed.emit()

    def set_symbol(self):
        p = self.selected()
        if p and FeedDialog(self.repo.market, p, self).exec():
            self.refresh(); self.changed.emit()

    def refresh_dividends(self):
        records = self.repo.market.dividends()
        rows = []
        for p in self.positions:
            record = records.get(p['key'], {})
            data, attempt = record.get('data', {}), record.get('attempt', {})
            events = data.get('events', [])
            status = 'Gespeichert' if attempt.get('status') == 'ok' else attempt.get('message', 'Noch nicht abgerufen')
            if data and attempt.get('status') != 'ok': status = 'Letzter guter Stand · ' + status
            for event in events or [{}]:
                amount = str(event.get('amount', '')).replace('.', ',')
                rows.append([p['name'], event.get('ex_date', ''), event.get('pay_date', ''), amount,
                             event.get('currency', ''), 'Keine Ausschüttungen gemeldet' if data and not events and attempt.get('status') == 'ok' else status,
                             data.get('attempted_at', '')[:19].replace('T', ' ')])
        rows.sort(key=lambda r: (r[2] or r[1], r[0]), reverse=True)
        self.dividend_table.setRowCount(len(rows))
        for row, values in enumerate(rows):
            for col, value in enumerate(values):
                item = QTableWidgetItem(display_dates(value)); item.setToolTip(display_dates(value)); self.dividend_table.setItem(row, col, item)
        for col in range(1, 7): self.dividend_table.resizeColumnToContents(col)

    def edit_manual(self):
        p = self.selected()
        if not p: return
        dialog = ManualMetricsDialog(self.records.get(p['key'], {}).get('manual', {}), self)
        while dialog.exec() == QDialog.DialogCode.Accepted:
            try:
                self.repo.market.save_manual(p['key'], {k: v.text() for k, v in dialog.fields.items()}, dialog.source.text(), dialog.as_of.text())
                self.refresh(); self.changed.emit(); break
            except ValueError as exc: QMessageBox.warning(self, 'Kennzahlen', str(exc))
