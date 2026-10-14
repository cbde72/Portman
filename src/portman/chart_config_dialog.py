"""Qt-Dialog zum Erstellen und Bearbeiten von Diagramm-Konfigurationen.

Bietet einen professionellen, tab-basierten Editor mit Live-Vorschau für alle
konfigurierbaren Aspekte: Typ, Datenquelle, Styling, Achsen, Zeitraum,
Aggregation und typ-spezifische Optionen. Zusätzlich gibt es eine Galerie
vorgefertigter Diagramm-Vorlagen.
"""
from __future__ import annotations

from datetime import date

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLineEdit, QComboBox,
    QDoubleSpinBox, QSpinBox, QCheckBox, QPushButton, QDialogButtonBox,
    QLabel, QGroupBox, QColorDialog, QDateEdit, QTabWidget, QWidget,
    QMessageBox, QScrollArea, QListWidget, QListWidgetItem, QSplitter,
    QInputDialog,
)

from .chart_config import (
    ChartConfig, ChartConfigManager, CHART_TYPES, DATA_SOURCES,
    AXIS_TYPES, Y_AXIS_FORMATS, AGGREGATION_TYPES, AGGREGATION_METHODS,
    DEFAULT_STYLING, ALL_ACCOUNTS,
)
from .chart_data import prepare_chart_for_config
from .dynamic_renderer import render_chart
from .safe_canvas import SafeFigureCanvas
from .chart_style import COLORS, PALETTES, create_figure_constrained, style_figure


# ---------------------------------------------------------------------------
# Übersetzungen für die GUI
# ---------------------------------------------------------------------------
CHART_TYPE_LABELS = {
    'line': 'Linien',
    'bar': 'Balken (vertikal)',
    'barh': 'Balken (horizontal)',
    'pie': 'Kreis',
    'area': 'Fläche (gestapelt)',
    'scatter': 'Streu',
    'comparison': 'Kursvergleich',
    'candlestick': 'Candlestick',
    'heatmap': 'Heatmap',
    'boxplot': 'Boxplot',
    'violin': 'Violinplot',
    'histogram': 'Histogramm',
    'treemap': 'Treemap',
    'radar': 'Radar',
}

DATA_SOURCE_LABELS = {
    'wealth': 'Vermögen',
    'accounts': 'Konten',
    'positions': 'Positionen',
    'valuation': 'Depotwert',
    'comparison': 'Kursvergleich',
}

AXIS_TYPE_LABELS = {'date': 'Datum', 'category': 'Kategorie', 'number': 'Zahl'}

Y_AXIS_FORMAT_LABELS = {
    'currency': 'Währung (€)',
    'percent': 'Prozent (%)',
    'number': 'Zahl',
}

AGGREGATION_TYPE_LABELS = {
    'none': 'Keine',
    'daily': 'Täglich',
    'weekly': 'Wöchentlich',
    'monthly': 'Monatlich',
}

AGGREGATION_METHOD_LABELS = {
    'last': 'Letzter Wert',
    'sum': 'Summe',
    'mean': 'Mittelwert',
}

PALETTE_LABELS = {
    'default': 'Standard',
    'tableau': 'Tableau 10',
    'viridis': 'Viridis',
    'corporate': 'Corporate',
}

THEME_LABELS = {'light': 'Hell', 'dark': 'Dunkel'}

GRID_AXIS_LABELS = {'y': 'Horizontal', 'x': 'Vertikal', 'both': 'Beide'}

SORT_LABELS = {'value': 'Nach Wert', 'gain': 'Nach Gewinn/Verlust'}

CANDLE_AGGREGATE_LABELS = {
    'none': 'Keine (nur echte OHLC)',
    'daily': 'Täglich',
    'weekly': 'Wöchentlich',
    'monthly': 'Monatlich',
    'yearly': 'Jährlich',
}

MARKER_CHOICES = [
    ('', 'Keiner'),
    ('o', 'Kreis'),
    ('s', 'Quadrat'),
    ('^', 'Dreieck'),
    ('D', 'Raute'),
]


def _labeled_combo(labels: dict, values) -> QComboBox:
    combo = QComboBox()
    for value in values:
        combo.addItem(labels.get(value, value), value)
    return combo


def _is_valid_color(value: str) -> bool:
    return bool(value) and QColor.isValidColorName(value)


class ColorButton(QPushButton):
    """Button zum Auswählen einer Farbe mit Signal bei Änderung."""

    colorChanged = Signal(str)

    def __init__(self, color: str, parent=None):
        super().__init__(parent)
        self._color = color
        self.setFixedSize(84, 24)
        self._apply()
        self.clicked.connect(self._choose)

    def _apply(self):
        self.setStyleSheet(
            f'background-color: {self._color}; border: 1px solid {COLORS["grid"]}; border-radius: 3px;'
        )
        self.setText(self._color.upper())

    def _choose(self):
        color = QColorDialog.getColor(QColor(self._color), self, 'Farbe wählen')
        if color.isValid():
            self.set_color(color.name())
            self.colorChanged.emit(self._color)

    def set_color(self, color: str):
        self._color = color if _is_valid_color(color) else DEFAULT_STYLING['line_color']
        self._apply()

    def color(self) -> str:
        return self._color


# ---------------------------------------------------------------------------
# Konfigurations-Editor
# ---------------------------------------------------------------------------

class ChartConfigDialog(QDialog):
    """Tab-basierter Editor mit Live-Vorschau für eine Diagramm-Konfiguration."""

    def __init__(self, config: ChartConfig | None = None, parent=None, *,
                 repo=None, scope_getter=None):
        super().__init__(parent)
        self.setWindowTitle('Diagramm konfigurieren')
        self.setMinimumSize(1020, 660)
        self._config = config
        self._repo = repo
        self._scope_getter = scope_getter
        self._data_cache: dict = {}
        self._account: str | None = None
        self._as_of: str = date.today().isoformat()
        self._resolve_scope()

        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(200)
        self._preview_timer.timeout.connect(self._update_preview)

        root = QVBoxLayout(self)
        root.setSpacing(8)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._build_form())
        splitter.addWidget(self._build_preview())
        splitter.setStretchFactor(0, 4)
        splitter.setStretchFactor(1, 5)
        splitter.setSizes([430, 560])
        root.addWidget(splitter, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self._wire_preview()
        if config:
            self._load_config(config)
        self._on_type_changed()
        self._schedule_preview()

    # ------------------------------------------------------------------
    # Aufbau
    # ------------------------------------------------------------------
    def _resolve_scope(self):
        if self._scope_getter is None:
            return
        try:
            scope = self._scope_getter()
            self._account, self._as_of = scope[0], scope[1]
        except Exception:
            pass

    def _build_form(self) -> QWidget:
        tabs = QTabWidget()
        tabs.addTab(self._build_basics_tab(), 'Grundlagen')
        tabs.addTab(self._build_scope_tab(), 'Datenauswahl')
        tabs.addTab(self._build_styling_tab(), 'Darstellung')
        tabs.addTab(self._build_axes_tab(), 'Achsen & Zeitraum')
        tabs.addTab(self._build_options_tab(), 'Optionen')
        return tabs

    def _build_basics_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        form = QFormLayout()
        self.id_edit = QLineEdit()
        self.id_edit.setPlaceholderText('z.B. mein_vermogensverlauf')
        form.addRow('ID (intern):', self.id_edit)

        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText('Angezeigter Titel')
        form.addRow('Titel:', self.title_edit)

        self.chart_type = _labeled_combo(CHART_TYPE_LABELS, CHART_TYPES)
        form.addRow('Diagrammtyp:', self.chart_type)

        self.data_source = _labeled_combo(DATA_SOURCE_LABELS, DATA_SOURCES)
        form.addRow('Datenquelle:', self.data_source)
        self.data_source.currentIndexChanged.connect(self._on_type_changed)
        layout.addLayout(form)

        note = QLabel('Jedes eigene Diagramm erscheint nach dem Speichern im '
                      'Diagramm-Menü und kann dort ausgewählt werden.')
        note.setWordWrap(True)
        note.setStyleSheet(f'color: {COLORS["muted"]};')
        layout.addWidget(note)
        layout.addStretch()
        return page

    def _build_scope_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        scope = QGroupBox('Depot / Konto')
        scope_form = QFormLayout(scope)
        self.account_scope = QComboBox()
        self.account_scope.addItem('Global (Kopfbereich)', None)
        self.account_scope.addItem('Alle Konten', ALL_ACCOUNTS)
        if self._repo is not None:
            try:
                for account in self._repo.accounts():
                    self.account_scope.addItem(account, account)
            except Exception:
                pass
        self.account_scope.setToolTip('Legt fest, welches Depot dieses Diagramm auswertet.')
        self.account_scope.currentIndexChanged.connect(self._on_scope_account_changed)
        scope_form.addRow('Depot:', self.account_scope)
        layout.addWidget(scope)

        self.positions_group = QGroupBox('Depotpositionen (optional)')
        positions_layout = QVBoxLayout(self.positions_group)
        hint = QLabel('Ohne Einschränkung werden alle Positionen des gewählten '
                      'Depots ausgewertet. Einzelne Positionen lassen sich hier '
                      'frei auswählen.')
        hint.setWordWrap(True)
        hint.setStyleSheet(f'color: {COLORS["muted"]};')
        positions_layout.addWidget(hint)

        self.positions_list = QListWidget()
        self.positions_list.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        self.positions_list.itemChanged.connect(lambda *_: self._schedule_preview())
        positions_layout.addWidget(self.positions_list, 1)

        buttons = QHBoxLayout()
        select_all = QPushButton('Alle')
        select_all.clicked.connect(lambda: self._check_all_positions(True))
        select_none = QPushButton('Keine')
        select_none.clicked.connect(lambda: self._check_all_positions(False))
        buttons.addWidget(select_all); buttons.addWidget(select_none); buttons.addStretch()
        positions_layout.addLayout(buttons)
        layout.addWidget(self.positions_group, 1)
        return page

    def _check_all_positions(self, checked: bool):
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        self.positions_list.blockSignals(True)
        for index in range(self.positions_list.count()):
            self.positions_list.item(index).setCheckState(state)
        self.positions_list.blockSignals(False)
        self._schedule_preview()

    def _preview_account(self):
        """Ermittelt den für die Datenabfrage wirksamen Kontofilter."""
        data = self.account_scope.currentData() if hasattr(self, 'account_scope') else None
        if data == ALL_ACCOUNTS:
            return None
        return data or self._account

    def _selected_position_keys(self) -> set[str]:
        if not hasattr(self, 'positions_list'):
            return set()
        return {self.positions_list.item(i).data(Qt.ItemDataRole.UserRole)
                for i in range(self.positions_list.count())
                if self.positions_list.item(i).checkState() == Qt.CheckState.Checked}

    def _refresh_position_choices(self, *, preserve: bool = True):
        """Füllt die Positionsliste passend zur gewählten Datenquelle/Depot."""
        if not hasattr(self, 'positions_list'):
            return
        keep = self._selected_position_keys() if preserve else set()
        self.positions_list.blockSignals(True)
        self.positions_list.clear()
        if self._repo is not None and self.data_source.currentData() == 'positions':
            try:
                rows = self._repo.current(self._as_of, self._preview_account())
            except Exception:
                rows = []
            for position in sorted(rows, key=lambda r: (r.get('name') or '').casefold()):
                if position.get('value') is None:
                    continue
                item = QListWidgetItem(position.get('name') or position.get('key'))
                item.setData(Qt.ItemDataRole.UserRole, position.get('key'))
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                checked = (position.get('key') in keep) if preserve else True
                item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
                self.positions_list.addItem(item)
        self.positions_list.blockSignals(False)

    def _on_scope_account_changed(self, *_args):
        self._refresh_position_choices(preserve=False)
        self._schedule_preview()

    def _scope_options(self) -> dict:
        """Diagrammspezifische Depot-/Positionsauswahl als ``options``-Einträge."""
        options: dict = {}
        data = self.account_scope.currentData() if hasattr(self, 'account_scope') else None
        if data:
            options['account'] = data
        if hasattr(self, 'positions_list'):
            total = self.positions_list.count()
            checked = self._selected_position_keys()
            if 0 < len(checked) < total:
                options['positions'] = sorted(checked)
        return options

    def _build_styling_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        colors = QGroupBox('Farben & Palette')
        colors_form = QFormLayout(colors)
        self.line_color = ColorButton(DEFAULT_STYLING['line_color'])
        colors_form.addRow('Linienfarbe:', self.line_color)
        self.fill_color = ColorButton(DEFAULT_STYLING['fill_color'])
        colors_form.addRow('Füllfarbe:', self.fill_color)
        self.palette = _labeled_combo(PALETTE_LABELS, list(PALETTES.keys()))
        colors_form.addRow('Farbpalette:', self.palette)
        self.theme = _labeled_combo(THEME_LABELS, list(THEME_LABELS.keys()))
        colors_form.addRow('Farbschema:', self.theme)
        layout.addWidget(colors)

        lines = QGroupBox('Linien & Marker')
        lines_form = QFormLayout(lines)
        self.line_width = QDoubleSpinBox(); self.line_width.setRange(0.5, 8.0)
        self.line_width.setSingleStep(0.25); self.line_width.setValue(float(DEFAULT_STYLING['line_width']))
        lines_form.addRow('Linienbreite:', self.line_width)
        self.fill_alpha = QDoubleSpinBox(); self.fill_alpha.setRange(0.0, 1.0)
        self.fill_alpha.setSingleStep(0.05); self.fill_alpha.setValue(float(DEFAULT_STYLING['fill_alpha']))
        lines_form.addRow('Fülltransparenz:', self.fill_alpha)
        self.marker = QComboBox()
        for value, label in MARKER_CHOICES:
            self.marker.addItem(label, value)
        lines_form.addRow('Marker:', self.marker)
        self.marker_size = QDoubleSpinBox(); self.marker_size.setRange(1.0, 12.0)
        self.marker_size.setSingleStep(0.5); self.marker_size.setValue(float(DEFAULT_STYLING['marker_size']))
        lines_form.addRow('Markergröße:', self.marker_size)
        self.smooth = QCheckBox('Kurven glätten (monoton)')
        lines_form.addRow('', self.smooth)
        layout.addWidget(lines)

        display = QGroupBox('Raster, Legende & Beschriftung')
        display_form = QFormLayout(display)
        self.show_grid = QCheckBox('Raster anzeigen')
        self.show_grid.setChecked(bool(DEFAULT_STYLING['show_grid']))
        display_form.addRow('', self.show_grid)
        self.grid_axis = _labeled_combo(GRID_AXIS_LABELS, list(GRID_AXIS_LABELS.keys()))
        display_form.addRow('Rasterlinien:', self.grid_axis)
        self.show_legend = QCheckBox('Legende anzeigen')
        self.show_legend.setChecked(bool(DEFAULT_STYLING['show_legend']))
        display_form.addRow('', self.show_legend)
        self.show_data_labels = QCheckBox('Werte direkt beschriften')
        display_form.addRow('', self.show_data_labels)
        self.title_fontsize = QSpinBox(); self.title_fontsize.setRange(8, 22)
        self.title_fontsize.setValue(int(DEFAULT_STYLING['title_fontsize']))
        display_form.addRow('Titelgröße:', self.title_fontsize)
        layout.addWidget(display)

        layout.addStretch()
        return self._scroll_page(page)

    def _build_axes_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        axes = QGroupBox('Achsen')
        axes_form = QFormLayout(axes)
        self.x_axis_type = _labeled_combo(AXIS_TYPE_LABELS, AXIS_TYPES)
        axes_form.addRow('X-Achse Typ:', self.x_axis_type)
        self.x_axis_label = QLineEdit()
        axes_form.addRow('X-Achse Beschriftung:', self.x_axis_label)
        self.y_axis_format = _labeled_combo(Y_AXIS_FORMAT_LABELS, Y_AXIS_FORMATS)
        axes_form.addRow('Y-Achse Format:', self.y_axis_format)
        self.y_axis_label = QLineEdit()
        axes_form.addRow('Y-Achse Beschriftung:', self.y_axis_label)
        layout.addWidget(axes)

        period = QGroupBox('Zeitraum (optional)')
        period_form = QFormLayout(period)
        self.start_date = QDateEdit(); self.start_date.setCalendarPopup(True)
        self.start_date.setDisplayFormat('dd.MM.yyyy')
        self.start_date.setDate(date(2020, 1, 1))
        period_form.addRow('Start:', self.start_date)
        self.end_date = QDateEdit(); self.end_date.setCalendarPopup(True)
        self.end_date.setDisplayFormat('dd.MM.yyyy')
        self.end_date.setDate(date(9999, 12, 31))
        period_form.addRow('Ende:', self.end_date)
        hint = QLabel('Standardwerte (01.01.2020 / 31.12.9999) bedeuten "gesamter Zeitraum".')
        hint.setWordWrap(True)
        hint.setStyleSheet(f'color: {COLORS["muted"]};')
        period_form.addRow('', hint)
        layout.addWidget(period)

        layout.addStretch()
        return page

    def _build_options_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        aggregation = QGroupBox('Aggregation')
        aggregation_form = QFormLayout(aggregation)
        self.agg_type = _labeled_combo(AGGREGATION_TYPE_LABELS, AGGREGATION_TYPES)
        aggregation_form.addRow('Zeitliche Aggregation:', self.agg_type)
        self.agg_method = _labeled_combo(AGGREGATION_METHOD_LABELS, AGGREGATION_METHODS)
        aggregation_form.addRow('Methode:', self.agg_method)
        layout.addWidget(aggregation)

        options = QGroupBox('Typ-spezifische Optionen')
        options_form = QFormLayout(options)
        self.top_n = QSpinBox(); self.top_n.setRange(1, 50); self.top_n.setValue(10)
        options_form.addRow('Top-N (Positionen):', self.top_n)
        self.sort_by = _labeled_combo(SORT_LABELS, list(SORT_LABELS.keys()))
        options_form.addRow('Sortierung:', self.sort_by)
        self.candle_aggregate = _labeled_combo(CANDLE_AGGREGATE_LABELS, list(CANDLE_AGGREGATE_LABELS.keys()))
        options_form.addRow('Kerzen aus Schlusskursen:', self.candle_aggregate)
        self.by_position = QCheckBox('Treemap: einzelne Positionen statt Regionen')
        options_form.addRow('', self.by_position)
        layout.addWidget(options)

        layout.addStretch()
        return page

    def _build_preview(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)

        header = QHBoxLayout()
        title = QLabel('Live-Vorschau')
        title.setStyleSheet('font-weight: bold;')
        header.addWidget(title)
        header.addStretch()
        refresh = QPushButton('Aktualisieren')
        refresh.clicked.connect(self._update_preview)
        header.addWidget(refresh)
        layout.addLayout(header)

        self.preview_figure = create_figure_constrained(width=6.4, height=4.0)
        self.preview_canvas = SafeFigureCanvas(self.preview_figure)
        self.preview_canvas.setMinimumHeight(320)
        layout.addWidget(self.preview_canvas, 1)

        self.preview_note = QLabel()
        self.preview_note.setWordWrap(True)
        self.preview_note.setStyleSheet(f'color: {COLORS["muted"]};')
        layout.addWidget(self.preview_note)

        if self._repo is None:
            self.preview_note.setText('Live-Vorschau ist nur mit geöffneter Datenbank verfügbar.')
        return page

    def _scroll_page(self, inner: QWidget) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setWidget(inner)
        return scroll

    # ------------------------------------------------------------------
    # Vorschau
    # ------------------------------------------------------------------
    def _wire_preview(self):
        widgets = (
            self.chart_type, self.data_source, self.palette, self.theme,
            self.marker, self.grid_axis, self.x_axis_type, self.y_axis_format,
            self.sort_by, self.candle_aggregate,
        )
        for widget in widgets:
            if isinstance(widget, QComboBox):
                widget.currentIndexChanged.connect(self._schedule_preview)
        for widget in (self.top_n, self.line_width, self.fill_alpha,
                       self.marker_size, self.title_fontsize):
            widget.valueChanged.connect(self._schedule_preview)
        for widget in (self.show_grid, self.show_legend, self.show_data_labels,
                       self.smooth, self.by_position):
            widget.toggled.connect(self._schedule_preview)
        for widget in (self.title_edit, self.x_axis_label, self.y_axis_label):
            widget.textChanged.connect(self._schedule_preview)
        self.line_color.colorChanged.connect(lambda *_: self._schedule_preview())
        self.fill_color.colorChanged.connect(lambda *_: self._schedule_preview())
        self.start_date.dateChanged.connect(lambda *_: self._schedule_preview())
        self.end_date.dateChanged.connect(lambda *_: self._schedule_preview())
        self.agg_type.currentIndexChanged.connect(self._schedule_preview)
        self.agg_method.currentIndexChanged.connect(self._schedule_preview)
        if hasattr(self, 'account_scope'):
            self.account_scope.currentIndexChanged.connect(self._schedule_preview)

    def _schedule_preview(self, *_args):
        self._preview_timer.start()

    def _prepared(self, config: ChartConfig):
        options = config.options or {}
        key = (config.data_source, self._as_of, options.get('account'),
               tuple(options.get('positions') or ()))
        if key not in self._data_cache:
            self._data_cache[key] = prepare_chart_for_config(
                self._repo, config.data_source, self._as_of, self._account, options)
        return self._data_cache[key]

    def _update_preview(self):
        self.preview_figure.clear()
        style_figure(self.preview_figure)
        self.preview_figure.set_layout_engine('constrained')

        if self._repo is None:
            self.preview_note.setText('Live-Vorschau ist nur mit geöffneter Datenbank verfügbar.')
            self.preview_canvas.draw_idle()
            return

        try:
            config = self._build_config(require_id=False)
        except Exception as exc:
            self.preview_note.setText(f'Konfiguration unvollständig: {exc}')
            self.preview_canvas.draw_idle()
            return

        self.setCursor(Qt.CursorShape.BusyCursor)
        try:
            data = self._prepared(config)
            note = render_chart(self.preview_figure, data, config, {
                'as_of': self._as_of, 'account': self._account, 'carry_prices': False})
            self.preview_note.setText(note or '')
        except Exception as exc:
            self.preview_note.setText(f'Vorschau nicht möglich: {exc}')
        finally:
            self.unsetCursor()
        self.preview_canvas.draw_idle()

    # ------------------------------------------------------------------
    # Laden / Übernehmen
    # ------------------------------------------------------------------
    def _load_config(self, config: ChartConfig):
        self.id_edit.setText(config.id)
        self.id_edit.setReadOnly(True)
        self.title_edit.setText(config.title)

        index = self.chart_type.findData(config.chart_type)
        if index >= 0:
            self.chart_type.setCurrentIndex(index)
        index = self.data_source.findData(config.data_source)
        if index >= 0:
            self.data_source.setCurrentIndex(index)

        styling = dict(DEFAULT_STYLING)
        styling.update(config.styling or {})
        self.line_color.set_color(styling.get('line_color'))
        self.fill_color.set_color(styling.get('fill_color'))
        self.line_width.setValue(float(styling.get('line_width', DEFAULT_STYLING['line_width'])))
        self.fill_alpha.setValue(float(styling.get('fill_alpha', DEFAULT_STYLING['fill_alpha'])))
        self.marker.setCurrentIndex(max(0, self.marker.findData(styling.get('marker', 'o'))))
        self.marker_size.setValue(float(styling.get('marker_size', DEFAULT_STYLING['marker_size'])))
        self.show_grid.setChecked(bool(styling.get('show_grid', DEFAULT_STYLING['show_grid'])))
        self.grid_axis.setCurrentIndex(max(0, self.grid_axis.findData(styling.get('grid_axis', 'y'))))
        self.show_legend.setChecked(bool(styling.get('show_legend', DEFAULT_STYLING['show_legend'])))
        self.show_data_labels.setChecked(bool(styling.get('show_data_labels', False)))
        self.smooth.setChecked(bool(styling.get('smooth', False)))
        self.title_fontsize.setValue(int(styling.get('title_fontsize', DEFAULT_STYLING['title_fontsize'])))
        self.palette.setCurrentIndex(max(0, self.palette.findData(styling.get('palette', 'default'))))
        self.theme.setCurrentIndex(max(0, self.theme.findData(styling.get('theme', 'light'))))

        axes = config.axes or {}
        self.x_axis_type.setCurrentIndex(max(0, self.x_axis_type.findData((axes.get('x') or {}).get('type', 'date'))))
        self.x_axis_label.setText((axes.get('x') or {}).get('label', ''))
        self.y_axis_format.setCurrentIndex(max(0, self.y_axis_format.findData((axes.get('y') or {}).get('type', 'currency'))))
        self.y_axis_label.setText((axes.get('y') or {}).get('label', ''))

        time_range = config.time_range or {}
        if time_range.get('start'):
            try:
                self.start_date.setDate(date.fromisoformat(time_range['start']))
            except ValueError:
                pass
        if time_range.get('end'):
            try:
                self.end_date.setDate(date.fromisoformat(time_range['end']))
            except ValueError:
                pass

        aggregation = config.aggregation or {}
        self.agg_type.setCurrentIndex(max(0, self.agg_type.findData(aggregation.get('type', 'none'))))
        self.agg_method.setCurrentIndex(max(0, self.agg_method.findData(aggregation.get('method', 'last'))))

        options = config.options or {}
        self.top_n.setValue(int(options.get('top_n', 10)))
        self.sort_by.setCurrentIndex(max(0, self.sort_by.findData(options.get('sort_by', 'value'))))
        candle = options.get('candle_aggregate') or 'none'
        self.candle_aggregate.setCurrentIndex(max(0, self.candle_aggregate.findData(candle)))
        self.by_position.setChecked(bool(options.get('by_position', False)))

        self.account_scope.blockSignals(True)
        index = self.account_scope.findData(options.get('account'))
        self.account_scope.setCurrentIndex(index if index >= 0 else 0)
        self.account_scope.blockSignals(False)
        self._refresh_position_choices(preserve=False)
        wanted = set(options.get('positions') or [])
        if wanted:
            self.positions_list.blockSignals(True)
            for position_index in range(self.positions_list.count()):
                item = self.positions_list.item(position_index)
                checked = item.data(Qt.ItemDataRole.UserRole) in wanted
                item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
            self.positions_list.blockSignals(False)

    def _on_type_changed(self, *_args):
        chart_type = self.chart_type.currentData()
        source = self.data_source.currentData()
        is_positions = source == 'positions'
        self.top_n.setEnabled(is_positions)
        self.sort_by.setEnabled(is_positions)
        self.by_position.setEnabled(source in ('positions', 'wealth'))
        if hasattr(self, 'positions_group'):
            self.positions_group.setEnabled(is_positions)
            self._refresh_position_choices()
        self.candle_aggregate.setEnabled(chart_type in ('candlestick', 'comparison'))
        self.marker.setEnabled(chart_type in ('line', 'area', 'candlestick'))
        self.marker_size.setEnabled(chart_type in ('line', 'area', 'candlestick'))
        self.smooth.setEnabled(chart_type in ('line', 'area'))
        self.show_data_labels.setEnabled(chart_type not in ('radar',))
        self._schedule_preview()

    def _on_accept(self):
        config = self._build_config(require_id=True)
        errors = ChartConfigManager().validate(config)
        if errors:
            QMessageBox.warning(self, 'Validierungsfehler', '\n'.join(errors))
            return
        self._config = config
        self.accept()

    def _build_config(self, require_id: bool = True) -> ChartConfig:
        start = self.start_date.date().toString('yyyy-MM-dd')
        end = self.end_date.date().toString('yyyy-MM-dd')
        start = start if self.start_date.date().year() > 2020 else None
        end = end if self.end_date.date().year() < 9999 else None

        chart_id = self.id_edit.text().strip() or 'vorschau'
        if require_id and not self.id_edit.text().strip():
            chart_id = ''

        styling = dict(DEFAULT_STYLING)
        styling.update({
            'line_color': self.line_color.color(),
            'fill_color': self.fill_color.color(),
            'line_width': float(self.line_width.value()),
            'fill_alpha': float(self.fill_alpha.value()),
            'marker': self.marker.currentData() or '',
            'marker_size': float(self.marker_size.value()),
            'show_grid': self.show_grid.isChecked(),
            'grid_axis': self.grid_axis.currentData(),
            'show_legend': self.show_legend.isChecked(),
            'show_data_labels': self.show_data_labels.isChecked(),
            'smooth': self.smooth.isChecked(),
            'title_fontsize': int(self.title_fontsize.value()),
            'palette': self.palette.currentData(),
            'theme': self.theme.currentData(),
        })

        return ChartConfig(
            id=chart_id,
            title=self.title_edit.text().strip(),
            chart_type=self.chart_type.currentData(),
            data_source=self.data_source.currentData(),
            styling=styling,
            axes={
                'x': {'type': self.x_axis_type.currentData(), 'label': self.x_axis_label.text().strip()},
                'y': {'type': self.y_axis_format.currentData(), 'label': self.y_axis_label.text().strip()},
            },
            time_range={'start': start, 'end': end},
            aggregation={
                'type': self.agg_type.currentData(),
                'method': self.agg_method.currentData(),
            },
            options={
                'top_n': int(self.top_n.value()),
                'sort_by': self.sort_by.currentData(),
                'candle_aggregate': self.candle_aggregate.currentData(),
                'by_position': self.by_position.isChecked(),
                **self._scope_options(),
            },
            comparison=self.data_source.currentData() == 'comparison',
        )

    def config(self) -> ChartConfig | None:
        """Gibt die erstellte/bearbeitete Konfiguration zurück."""
        return self._config


# ---------------------------------------------------------------------------
# Vorlagen-Galerie
# ---------------------------------------------------------------------------

class TemplateGalleryDialog(QDialog):
    """Galerie vorgefertigter, professioneller Diagramm-Vorlagen.

    Zeigt eingebaute und eigene Vorlagen. Eigene Vorlagen können entfernt
    werden; die Auswahl liefert eine tiefe Kopie der gewählten Konfiguration.
    """

    _BUILTIN_ROLE = Qt.ItemDataRole.UserRole
    _SOURCE_ROLE = Qt.ItemDataRole.UserRole + 1

    def __init__(self, parent=None, manager=None):
        super().__init__(parent)
        self.setWindowTitle('Diagramm-Vorlagen')
        self.setMinimumSize(560, 480)
        self._selected: ChartConfig | None = None

        from .chart_templates import TemplateManager
        self._manager = manager if manager is not None else TemplateManager()

        layout = QVBoxLayout(self)
        info = QLabel('Wählen Sie eine Vorlage als Ausgangspunkt. Die Werte können '
                      'im Anschluss frei angepasst werden.')
        info.setWordWrap(True)
        layout.addWidget(info)

        self.list_widget = QListWidget()
        self.list_widget.itemDoubleClicked.connect(lambda *_: self._accept_selection())
        layout.addWidget(self.list_widget, 1)

        toolbar = QHBoxLayout()
        delete_btn = QPushButton('Eigene Vorlage löschen')
        delete_btn.clicked.connect(self._delete_selected)
        toolbar.addWidget(delete_btn)
        toolbar.addStretch()
        layout.addLayout(toolbar)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._accept_selection)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._rebuild_list()

    def _rebuild_list(self):
        self.list_widget.clear()
        categories: dict[str, list] = {}
        for template in self._manager.all():
            category = template.category or 'Vorlagen'
            source = 'user' if self._manager.get(template.name) is not None else 'builtin'
            categories.setdefault((category, source), []).append((template, source))
        for (category, source), templates in categories.items():
            header = QListWidgetItem(category.upper())
            header.setFlags(Qt.ItemFlag.NoItemFlags)
            self.list_widget.addItem(header)
            for template, item_source in templates:
                item = QListWidgetItem(f'   {template.name} — {template.description}')
                item.setData(self._BUILTIN_ROLE, template)
                item.setData(self._SOURCE_ROLE, item_source)
                self.list_widget.addItem(item)

    def _delete_selected(self):
        item = self.list_widget.currentItem()
        if item is None:
            return
        template = item.data(self._BUILTIN_ROLE)
        if template is None or item.data(self._SOURCE_ROLE) != 'user':
            QMessageBox.information(self, 'Keine eigene Vorlage',
                                    'Nur selbst erstellte Vorlagen können gelöscht werden.')
            return
        reply = QMessageBox.question(
            self, 'Vorlage löschen',
            f'Möchten Sie die eigene Vorlage „{template.name}" wirklich löschen?')
        if reply == QMessageBox.StandardButton.Yes:
            self._manager.remove(template.name)
            self._manager.save()
            self._rebuild_list()

    def _accept_selection(self):
        item = self.list_widget.currentItem()
        template = item.data(self._BUILTIN_ROLE) if item else None
        if template is None:
            QMessageBox.information(self, 'Keine Auswahl', 'Bitte wählen Sie eine Vorlage aus.')
            return
        self._selected = _copy_config(template.config)
        self.accept()

    def selected_config(self) -> ChartConfig | None:
        return self._selected


def _copy_config(config: ChartConfig, chart_id: str | None = None,
                 title: str | None = None) -> ChartConfig:
    """Erstellt eine tiefe Kopie einer Konfiguration mit optional neuer ID/Title."""
    return ChartConfig(
        id=chart_id or config.id,
        title=title if title is not None else config.title,
        chart_type=config.chart_type,
        data_source=config.data_source,
        styling=dict(config.styling),
        axes={side: dict(value) for side, value in config.axes.items()},
        time_range=dict(config.time_range),
        aggregation=dict(config.aggregation),
        options=dict(config.options),
        comparison=config.comparison,
    )


# ---------------------------------------------------------------------------
# Verwaltung aller eigenen Diagramme
# ---------------------------------------------------------------------------

class CustomChartsDialog(QDialog):
    """Verwaltet alle benutzerdefinierten Diagramme.

    Ermöglicht das Hinzufügen (auch aus Vorlagen), Bearbeiten, Duplizieren und
    Entfernen von Diagramm-Konfigurationen. Änderungen werden sofort gespeichert.
    """

    def __init__(self, manager: ChartConfigManager, parent=None, *,
                 repo=None, scope_getter=None):
        super().__init__(parent)
        self.setWindowTitle('Eigene Diagramme')
        self.setMinimumSize(680, 460)
        self.manager = manager
        self._repo = repo
        self._scope_getter = scope_getter
        from .chart_templates import default_template_manager
        self._template_manager = default_template_manager(repo)

        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        toolbar = QHBoxLayout()
        for label, handler in (
            ('Neu', self._add_chart),
            ('Aus Vorlage …', self._add_from_template),
            ('Bearbeiten', self._edit_chart),
            ('Duplizieren', self._duplicate_chart),
            ('Als Vorlage speichern …', self._save_as_template),
            ('Entfernen', self._remove_chart),
        ):
            button = QPushButton(label)
            button.clicked.connect(handler)
            toolbar.addWidget(button)
        toolbar.addStretch()
        layout.addLayout(toolbar)

        self.list_widget = QListWidget()
        self.list_widget.itemDoubleClicked.connect(lambda *_: self._edit_chart())
        self._refresh_list()
        layout.addWidget(self.list_widget, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        # Schließen gilt als Bestätigung, damit Aufrufer nach dem Dialog
        # zuverlässig neu laden (Änderungen werden ohnehin sofort gespeichert).
        buttons.rejected.connect(self.accept)
        layout.addWidget(buttons)

    # -- Hilfen --------------------------------------------------------
    def _refresh_list(self):
        self.list_widget.clear()
        for config in self.manager.all():
            label = CHART_TYPE_LABELS.get(config.chart_type, config.chart_type)
            item = QListWidgetItem(f'{config.title}  ·  {label}  ·  {config.id}')
            item.setData(Qt.ItemDataRole.UserRole, config.id)
            self.list_widget.addItem(item)

    def _persist(self):
        self.manager.save()

    def _unique_id(self, base: str) -> str:
        candidate = base
        suffix = 1
        while self.manager.get(candidate) is not None:
            candidate = f'{base}_{suffix}'
            suffix += 1
        return candidate

    def _open_editor(self, config: ChartConfig | None) -> ChartConfig | None:
        dialog = ChartConfigDialog(config, self, repo=self._repo, scope_getter=self._scope_getter)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            return dialog.config()
        return None

    def _require_selection(self) -> str | None:
        item = self.list_widget.currentItem()
        if item is None:
            QMessageBox.information(self, 'Keine Auswahl', 'Bitte wählen Sie ein Diagramm aus.')
            return None
        return item.data(Qt.ItemDataRole.UserRole)

    # -- Aktionen ------------------------------------------------------
    def _add_chart(self):
        config = self._open_editor(None)
        if config is None:
            return
        errors = self.manager.add(config)
        if errors:
            QMessageBox.warning(self, 'Validierungsfehler', '\n'.join(errors))
            return
        self._persist()
        self._refresh_list()

    def _add_from_template(self):
        gallery = TemplateGalleryDialog(self, manager=self._template_manager)
        if gallery.exec() != QDialog.DialogCode.Accepted:
            return
        template = gallery.selected_config()
        if template is None:
            return
        template = _copy_config(template, chart_id=self._unique_id(template.id))
        config = self._open_editor(template)
        if config is None:
            return
        if self.manager.get(config.id) is not None and config.id != template.id:
            QMessageBox.warning(self, 'ID vergeben',
                                f'Die ID „{config.id}" ist bereits vergeben.')
            return
        errors = self.manager.add(config)
        if errors:
            QMessageBox.warning(self, 'Validierungsfehler', '\n'.join(errors))
            return
        self._persist()
        self._refresh_list()

    def _edit_chart(self):
        chart_id = self._require_selection()
        if chart_id is None:
            return
        existing = self.manager.get(chart_id)
        if existing is None:
            return
        config = self._open_editor(existing)
        if config is None:
            return
        errors = self.manager.validate(config)
        if errors:
            QMessageBox.warning(self, 'Validierungsfehler', '\n'.join(errors))
            return
        self.manager.remove(chart_id)
        self.manager.add(config)
        self._persist()
        self._refresh_list()

    def _duplicate_chart(self):
        chart_id = self._require_selection()
        if chart_id is None:
            return
        existing = self.manager.get(chart_id)
        if existing is None:
            return
        copy = _copy_config(existing,
                            chart_id=self._unique_id(f'{chart_id}_kopie'),
                            title=f'{existing.title} (Kopie)')
        self.manager.add(copy)
        self._persist()
        self._refresh_list()

    def _save_as_template(self):
        """Speichert das gewählte Diagramm als eigene (benutzerspezifische) Vorlage."""
        chart_id = self._require_selection()
        if chart_id is None:
            return
        existing = self.manager.get(chart_id)
        if existing is None:
            return
        from .chart_templates import ChartTemplate
        name, ok = QInputDialog.getText(
            self, 'Als Vorlage speichern', 'Name der Vorlage:', text=existing.title)
        name = name.strip() if ok else ''
        if not name:
            return
        description, ok = QInputDialog.getText(
            self, 'Vorlagenbeschreibung', 'Beschreibung (optional):')
        if not ok:
            return
        template = ChartTemplate(
            name=name,
            description=description.strip(),
            category='Eigene',
            config=_copy_config(existing),
        )
        error = self._template_manager.add(template)
        if error:
            QMessageBox.warning(self, 'Vorlage nicht gespeichert', error)
            return
        self._template_manager.save()
        QMessageBox.information(
            self, 'Vorlage gespeichert',
            f'„{name}" kann jetzt über „Aus Vorlage …" als Ausgangspunkt verwendet werden.')

    def _remove_chart(self):
        chart_id = self._require_selection()
        if chart_id is None:
            return
        existing = self.manager.get(chart_id)
        if existing is None:
            return
        reply = QMessageBox.question(
            self, 'Löschen bestätigen',
            f'Möchten Sie das Diagramm „{existing.title}" wirklich löschen?')
        if reply == QMessageBox.StandardButton.Yes:
            self.manager.remove(chart_id)
            self._persist()
            self._refresh_list()
