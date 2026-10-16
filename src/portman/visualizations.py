from datetime import date
from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QComboBox, QLabel, QPushButton, QFileDialog, QCheckBox
from .chart_style import (COLORS, style_figure, create_figure, CHART_STYLE,
                          chart_style_signature, save_figure)
from .safe_canvas import SafeFigureCanvas
from .chart_data import prepare_chart, prepare_chart_for_config, comparison_data
from .chart_loader import ChartLoader
from .chart_rendering import draw_wealth, draw_accounts, draw_depot_value, draw_positions, draw_price_comparison
from .chart_specs import chart_spec, chart_views
from .chart_config import ChartConfig
from .dynamic_renderer import render_chart
from .gui.chart_settings import ChartSettingsMixin


class VisualizationsWidget(ChartSettingsMixin, QWidget):
    VIEWS = chart_views()

    def __init__(self, repo, scope_getter, parent=None, *, compact=False, initial_view=0,
                 custom_charts=None, defer_canvas=False):
        super().__init__(parent)
        self.repo, self.scope_getter = repo, scope_getter
        self._render_key = None
        self._render_note = ''
        self.custom_charts = custom_charts or []
        self._custom_chart_map: dict[int, ChartConfig] = {}
        original = getattr(repo, 'repository', repo)
        cache = original.__dict__.setdefault('_prepared_chart_cache', {})
        self.chart_loader = ChartLoader(self, cache=cache)
        self.refresh_timer = QTimer(self)
        self.refresh_timer.setSingleShot(True)
        self.refresh_timer.timeout.connect(self.refresh)
        layout = QVBoxLayout(self); layout.setContentsMargins(6, 6, 6, 6); layout.setSpacing(5)
        bar = QHBoxLayout(); bar.setSpacing(5)
        self.view = QComboBox(); self.view.addItems(self.VIEWS)
        # Benutzerdefinierte Diagramme hinzufügen
        if self.custom_charts:
            self.view.insertSeparator(len(self.VIEWS))
            for config in self.custom_charts:
                self.view.addItem(config.title)
                index = self.view.count() - 1
                self._custom_chart_map[index] = config
                self.view.setItemData(index, config.id, Qt.ItemDataRole.UserRole)
        self.view.currentIndexChanged.connect(self.refresh)
        bar.addWidget(self.view); bar.addStretch()
        settings_btn = QPushButton('Diagramme …'); settings_btn.clicked.connect(self.open_chart_settings)
        if not compact: bar.addWidget(settings_btn)
        export = QPushButton('Grafik exportieren'); export.clicked.connect(self.export); bar.addWidget(export)
        history = QPushButton('Kursverläufe laden …'); history.clicked.connect(self.open_history); bar.addWidget(history)
        if compact:
            export.hide(); history.hide()
        self.cancel_chart_button = QPushButton('Berechnung abbrechen')
        self.cancel_chart_button.clicked.connect(self.cancel_chart)
        self.cancel_chart_button.hide(); bar.addWidget(self.cancel_chart_button)
        layout.addLayout(bar)
        self.comparison_bar = QWidget(); comparison = QHBoxLayout(self.comparison_bar)
        self.compare_a, self.compare_b = QComboBox(), QComboBox()
        for combo in (self.compare_a, self.compare_b):
            combo.setMinimumContentsLength(20); comparison.addWidget(combo)
            combo.currentIndexChanged.connect(self.refresh)
        self.carry_prices = QCheckBox('Letzte Kurse fortführen')
        self.carry_prices.setToolTip('Fortgeschriebene Kurse sind keine neuen Beobachtungen. Standard: gemeinsame Handelstage.')
        self.carry_prices.toggled.connect(self.refresh); comparison.addWidget(self.carry_prices)
        layout.addWidget(self.comparison_bar); self.comparison_bar.hide()
        self._layout = layout
        self._canvas_minimum_height = 190 if compact else 250
        self.fig = None
        self.canvas = None
        self._canvas_placeholder = QLabel('Diagramm wird beim Öffnen geladen …')
        self._canvas_placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._canvas_placeholder, 1)
        self.note = QLabel(); self.note.setObjectName('muted'); self.note.setWordWrap(True); layout.addWidget(self.note)
        if not defer_canvas:
            self._ensure_canvas()
        self.chart_loader.ready.connect(self.receive_data)
        self.chart_loader.failed.connect(self.receive_error)
        self.chart_loader.busy.connect(self.cancel_chart_button.setVisible)
        self.chart_loader.retry.connect(self.refresh)
        # Erst nach dem Aufbau aller Steuerelemente die Ausgangsansicht wählen,
        # damit der ausgelöste refresh() auf compare_a/compare_b zugreifen kann.
        self.view.setCurrentIndex(max(0, min(initial_view, self.view.count() - 1)))

    def _ensure_canvas(self):
        if self.canvas is not None:
            return self.canvas
        self.fig = create_figure()
        style_figure(self.fig)
        self.canvas = SafeFigureCanvas(self.fig)
        self.canvas.setMinimumHeight(self._canvas_minimum_height)
        self._layout.replaceWidget(self._canvas_placeholder, self.canvas)
        self._canvas_placeholder.hide()
        from .chart_interaction import install_chart_tooltips
        install_chart_tooltips(self.canvas, self.note.text)
        return self.canvas

    def export(self):
        self._ensure_canvas()
        formats = [fmt.lower() for fmt in CHART_STYLE.get('export_formats', ['png'])]
        filters = ';;'.join(f'{fmt.upper()} (*.{fmt})' for fmt in formats)
        default_ext = formats[0] if formats else 'png'
        path, _ = QFileDialog.getSaveFileName(
            self, 'Grafik speichern', f'portman-analyse.{default_ext}', filters)
        if not path:
            return
        suffix = path.rsplit('.', 1)[-1].lower() if '.' in path else ''
        if suffix not in formats:
            if formats:
                path += '.' + formats[0]
            else:
                path += '.png'
        save_figure(self.fig, path, dpi=CHART_STYLE['export_dpi'])

    def open_custom_charts(self):
        """Öffnet den Dialog zur Verwaltung benutzerdefinierter Diagramme."""
        from .chart_config import default_manager
        from .chart_config_dialog import CustomChartsDialog
        manager = default_manager(self.repo)
        dialog = CustomChartsDialog(manager, self, repo=self.repo, scope_getter=self.scope_getter)
        if dialog.exec():
            # Konfigurationen neu laden und aktualisieren
            self.custom_charts = manager.all()
            self._update_custom_charts()
            self.refresh()

    def _update_custom_charts(self):
        """Aktualisiert die Dropdown-Liste mit benutzerdefinierten Diagrammen."""
        # Alles nach den festen Ansichten (inkl. Trenner) entfernen
        while self.view.count() > len(self.VIEWS):
            self.view.removeItem(self.view.count() - 1)
        self._custom_chart_map.clear()
        # Neue benutzerdefinierte Diagramme hinzufügen
        if self.custom_charts:
            self.view.insertSeparator(len(self.VIEWS))
            for config in self.custom_charts:
                self.view.addItem(config.title)
                index = self.view.count() - 1
                self._custom_chart_map[index] = config
                self.view.setItemData(index, config.id, Qt.ItemDataRole.UserRole)


    def refresh(self):
        if getattr(self.repo, 'defer_initial_views', False): return
        if hasattr(self.repo, 'db') and self.repo.db.in_transaction:
            self.refresh_timer.start(100)
            return
        key = self.render_key()
        if key is not None and key == self._render_key:
            self.chart_loader.cancel()
            self.note.setText(self._render_note)
            return
        account, as_of = self.scope_getter()
        mode = self.view.currentIndex()
        config = self._custom_chart_map.get(mode)
        if config:
            # Benutzerdefiniertes Diagramm
            self.comparison_bar.setVisible(config.comparison)
            if key is None:
                self.draw_data(prepare_chart_for_config(self.repo, config.data_source, as_of, account,
                                                        config.options))
                return
        else:
            spec = chart_spec(mode)
            self.comparison_bar.setVisible(bool(spec and spec.comparison))
            if key is None:
                self.draw_data(prepare_chart(self.repo, mode, as_of, account))
                return
        data_key = self.data_key()
        original = getattr(self.repo, 'repository', self.repo)
        self.note.setText('Diagrammdaten werden im Hintergrund berechnet … Die Auswahl bleibt bedienbar.')
        self.chart_loader.request(data_key, dict(path=original.store.path, repository_type=type(original),
            mode=mode, as_of=as_of, account=account, documented=getattr(self.repo, 'documented_only', False),
            data_source=config.data_source if config else None,
            options=config.options if config else None))

    def data_key(self):
        key = self.render_key()
        mode = self.view.currentIndex()
        config = self._custom_chart_map.get(mode)
        if config:
            return (key[0], key[1], tuple(self.scope_getter()), config.cache_group,
                    getattr(self.repo, 'documented_only', False), date.today().isoformat())
        spec = chart_spec(mode)
        return (key[0], key[1], tuple(self.scope_getter()), spec.cache_group if spec else mode,
                getattr(self.repo, 'documented_only', False), date.today().isoformat())

    def receive_data(self, key, data):
        try:
            current = self.data_key()
        except Exception:
            return
        if key == current: self.draw_data(data)
        else: self.refresh_timer.start(0)

    def receive_error(self, error):
        self.note.setText('Diagramm konnte nicht geladen werden: ' + error)

    def closeEvent(self, event):
        self.refresh_timer.stop()
        self.chart_loader.shutdown()
        super().closeEvent(event)

    def cancel_chart(self):
        self.chart_loader.cancel()
        self.note.setText('Diagrammberechnung abgebrochen. Ansicht erneut auswählen, um neu zu laden.')

    def hideEvent(self, event):
        self.refresh_timer.stop()
        self.chart_loader.cancel()
        super().hideEvent(event)

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh_timer.start(0)

    def draw_data(self, data):
        self._ensure_canvas()
        account, as_of = self.scope_getter()
        mode = self.view.currentIndex()
        self.fig.clear()
        self.fig.set_size_inches(CHART_STYLE['figure_width'], CHART_STYLE['figure_height'])
        style_figure(self.fig)
        self.fig.set_layout_engine('constrained')
        config = self._custom_chart_map.get(mode)
        if config:
            # Benutzerdefiniertes Diagramm: dynamischer Renderer
            self.comparison_bar.setVisible(config.comparison)
            context = {'as_of': as_of, 'account': account, 'carry_prices': self.carry_prices.isChecked()}
            note = render_chart(self.fig, data, config, context)
            if note:
                self.note.setText(note)
            else:
                self.note.setText('')
        else:
            spec = chart_spec(mode)
            self.comparison_bar.setVisible(bool(spec and spec.comparison))
            if spec is None:
                note = draw_positions(self.fig, data.get('positions', []), mode)
            elif spec.render == 'comparison':
                self.draw_comparison(as_of, account, data)
                note = None
            elif spec.render == 'wealth':
                note = draw_wealth(self.fig, data, mode)
            elif spec.render == 'accounts':
                note = draw_accounts(self.fig, data['rows'], account)
            elif spec.render == 'depot_value':
                note = draw_depot_value(self.fig, data['rows'], as_of)
            else:
                note = draw_positions(self.fig, data['positions'], mode)
            if note is not None:
                self.note.setText(note)
        self.canvas.draw_idle()
        self._render_key = self.render_key()
        self._render_note = self.note.text()

    def render_key(self):
        if not hasattr(self.repo, 'db') or self.repo.db.in_transaction: return None
        return (self.repo.db.total_changes, self.repo.db.execute('PRAGMA data_version').fetchone()[0],
                self.scope_getter(), self.view.currentIndex(), self.compare_a.currentData(), self.compare_b.currentData(),
                self.carry_prices.isChecked(), tuple(COLORS.values()), chart_style_signature(), date.today().isoformat(),
                getattr(self.repo, 'documented_only', False))

    def open_history(self):
        from .price_history_dialog import PriceHistoryDialog
        PriceHistoryDialog(self.repo, self.scope_getter()[0], self).exec()
        self.refresh()

    def draw_comparison(self, as_of, account, prepared=None):
        prepared = prepared if prepared is not None else comparison_data(self.repo, as_of, account)
        records, choices = prepared['records'], prepared['choices']
        for index, combo in enumerate((self.compare_a, self.compare_b)):
            selected = combo.currentData()
            combo.blockSignals(True)
            combo.clear()
            for key, name in choices:
                combo.addItem(name, key)
            found = combo.findData(selected)
            combo.setCurrentIndex(found if found >= 0 else min(index, len(choices) - 1))
            combo.blockSignals(False)
        data = [records.get(combo.currentData(), {}).get('data', {})
                for combo in (self.compare_a, self.compare_b)]
        self.note.setText(draw_price_comparison(self.fig, data, as_of, self.carry_prices.isChecked()))
