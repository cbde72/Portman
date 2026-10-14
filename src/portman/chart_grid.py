"""Frei konfigurierbares Diagramm-Raster.

Das Raster zeigt bis zu 5 × 5 Kacheln. Jede Kachel enthält ein eigenes,
über den Konfigurationsdialog frei einstellbares Diagramm. Als Datenquelle
lassen sich wahlweise Depotpositionen (mit frei gewählter Auswahl) oder
verschiedene Depots/Konten verwenden. Die Belegung wird als JSON-Datei neben
der Datenbank gespeichert.
"""
from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QSpinBox,
    QStackedWidget, QVBoxLayout, QWidget,
)

from .chart_config import ChartConfig
from .chart_data import prepare_chart_for_config
from .chart_style import create_figure, style_figure
from .dynamic_renderer import render_chart
from .safe_canvas import SafeFigureCanvas


GRID_FILENAME = 'custom_chart_grid.json'
MAX_GRID = 5


def default_grid_path(repo=None) -> Path:
    """Ermittelt den Speicherort der Raster-Belegung (neben der Datenbank)."""
    try:
        original = getattr(repo, 'repository', repo)
        store = getattr(original, 'store', None)
        database_path = getattr(store, 'path', None)
        if database_path:
            return Path(database_path).parent / GRID_FILENAME
    except Exception:
        pass
    return Path.home() / '.portman' / GRID_FILENAME


class ChartGridStore:
    """Lädt und speichert die Raster-Belegung als JSON."""

    def __init__(self, path=None):
        self.path = Path(path) if path else None

    def load(self) -> dict:
        if self.path is None or not self.path.exists():
            return {}
        try:
            with open(self.path, 'r', encoding='utf-8') as handle:
                data = json.load(handle)
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def save(self, rows: int, cols: int, cells: dict) -> None:
        if self.path is None:
            return
        payload = {
            'version': 1,
            'rows': int(rows),
            'cols': int(cols),
            'cells': {key: config.to_dict() for key, config in cells.items()
                      if config is not None},
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, 'w', encoding='utf-8') as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False)


class ChartTile(QFrame):
    """Eine einzelne, frei konfigurierbare Diagramm-Kachel."""

    changed = Signal()

    def __init__(self, index, repo, scope_getter, config: ChartConfig | None = None, parent=None):
        super().__init__(parent)
        self.index = index
        self.repo = repo
        self.scope_getter = scope_getter
        self.config = config
        self._figure = None
        self._canvas = None
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setMinimumSize(210, 170)

        root = QVBoxLayout(self)
        root.setContentsMargins(6, 4, 6, 6)
        root.setSpacing(4)

        header = QHBoxLayout()
        header.setSpacing(4)
        self.title = QLabel()
        self.title.setObjectName('muted')
        self.title.setStyleSheet('font-weight: bold;')
        header.addWidget(self.title, 1)
        self.configure_button = QPushButton('⚙')
        self.configure_button.setToolTip('Diagramm dieser Zelle konfigurieren')
        self.configure_button.setFixedWidth(30)
        self.configure_button.clicked.connect(self.configure)
        header.addWidget(self.configure_button)
        self.clear_button = QPushButton('✕')
        self.clear_button.setToolTip('Zelle leeren')
        self.clear_button.setFixedWidth(30)
        self.clear_button.clicked.connect(self.clear)
        header.addWidget(self.clear_button)
        root.addLayout(header)

        self.stack = QStackedWidget()
        self.placeholder = QPushButton('+ Diagramm konfigurieren')
        self.placeholder.clicked.connect(self.configure)
        self.stack.addWidget(self.placeholder)
        root.addWidget(self.stack, 1)

        self.note = QLabel()
        self.note.setObjectName('muted')
        self.note.setWordWrap(True)
        self.note.setVisible(False)
        root.addWidget(self.note)

        self._update_header()
        if self.config is not None:
            self.render()
        else:
            self._show_placeholder()

    # -- Aufbau ---------------------------------------------------------
    def _ensure_canvas(self):
        if self._canvas is None:
            self._figure = create_figure()
            self._canvas = SafeFigureCanvas(self._figure)
            self._canvas.setMinimumHeight(150)
            self.stack.addWidget(self._canvas)
        return self._canvas

    def _show_placeholder(self):
        self.stack.setCurrentWidget(self.placeholder)
        if self._canvas is not None:
            self._canvas.setVisible(False)

    def _update_header(self):
        if self.config is None:
            self.title.setText('')
            self.clear_button.setVisible(False)
        else:
            self.title.setText(self.config.title or self.config.id)
            self.clear_button.setVisible(True)

    # -- Aktionen -------------------------------------------------------
    def configure(self):
        from .chart_config_dialog import ChartConfigDialog
        base = self.config
        if base is None:
            base = ChartConfig(id=f'grid_{self.index}', title='',
                               chart_type='barh', data_source='positions')
        dialog = ChartConfigDialog(base, self, repo=self.repo, scope_getter=self.scope_getter)
        if dialog.exec():
            config = dialog.config()
            if config is not None:
                self.set_config(config)

    def clear(self):
        self.set_config(None)

    def set_config(self, config: ChartConfig | None):
        self.config = config
        self._update_header()
        if config is None:
            self.note.setVisible(False)
            self._show_placeholder()
        else:
            self.render()
        self.changed.emit()

    def render(self):
        if self.config is None:
            self._show_placeholder()
            return
        if getattr(self.repo, 'defer_initial_views', False):
            return
        canvas = self._ensure_canvas()
        self.stack.setCurrentWidget(canvas)
        canvas.setVisible(True)
        account, as_of = self.scope_getter()
        try:
            data = prepare_chart_for_config(self.repo, self.config.data_source, as_of,
                                            account, self.config.options)
        except Exception as error:  # Bedienbarkeit erhalten
            self.note.setText(f'Daten konnten nicht geladen werden: {error}')
            self.note.setVisible(True)
            return
        self._figure.clear()
        self._figure.set_size_inches(4.6, 3.0)
        style_figure(self._figure)
        self._figure.set_layout_engine('constrained')
        note = render_chart(self._figure, data, self.config,
                            {'as_of': as_of, 'account': account, 'carry_prices': False})
        self.note.setText((note or '').strip())
        self.note.setVisible(bool((note or '').strip()))
        self._canvas.draw_idle()


class ChartGridWidget(QWidget):
    """Seite mit einem frei belegbaren Raster aus Diagramm-Kacheln."""

    def __init__(self, repo, scope_getter, settings=None, save=None, parent=None):
        super().__init__(parent)
        self.repo = repo
        self.scope_getter = scope_getter
        self.settings = settings if settings is not None else {}
        self.save = save
        self.store = ChartGridStore(default_grid_path(repo))
        state = self.store.load()
        self.rows = max(1, min(MAX_GRID, int(state.get('rows', 2) or 2)))
        self.cols = max(1, min(MAX_GRID, int(state.get('cols', 2) or 2)))
        self.cells: dict[str, ChartConfig] = {}
        for key, payload in (state.get('cells') or {}).items():
            try:
                self.cells[key] = ChartConfig.from_dict(payload)
            except Exception:
                continue
        self.tile_map: dict[str, ChartTile] = {}
        self.tiles: list[ChartTile] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)

        controls = QHBoxLayout()
        controls.setContentsMargins(6, 4, 6, 0)
        controls.addWidget(QLabel('Raster'))
        controls.addWidget(QLabel('Spalten:'))
        self.spin_cols = QSpinBox()
        self.spin_cols.setRange(1, MAX_GRID)
        self.spin_cols.setValue(self.cols)
        self.spin_cols.valueChanged.connect(self._apply_size)
        controls.addWidget(self.spin_cols)
        controls.addWidget(QLabel('Reihen:'))
        self.spin_rows = QSpinBox()
        self.spin_rows.setRange(1, MAX_GRID)
        self.spin_rows.setValue(self.rows)
        self.spin_rows.valueChanged.connect(self._apply_size)
        controls.addWidget(self.spin_rows)
        refresh = QPushButton('Aktualisieren')
        refresh.clicked.connect(self.refresh)
        controls.addWidget(refresh)
        clear_all = QPushButton('Alle Zellen leeren')
        clear_all.clicked.connect(self.clear_all)
        controls.addWidget(clear_all)
        controls.addStretch()
        self.hint = QLabel('Jede Zelle über ⚙ frei konfigurieren – Depot oder einzelne Positionen wählbar.')
        self.hint.setObjectName('muted')
        self.hint.setWordWrap(True)
        controls.addWidget(self.hint)
        root.addLayout(controls)

        self.grid_host = QWidget()
        self.grid = QGridLayout(self.grid_host)
        self.grid.setContentsMargins(6, 0, 6, 6)
        self.grid.setSpacing(6)
        root.addWidget(self.grid_host, 1)

        self.rebuild_grid()

    # -- Raster ---------------------------------------------------------
    def rebuild_grid(self):
        while self.grid.count():
            item = self.grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self.tile_map = {}
        self.tiles = []
        for row in range(self.rows):
            for col in range(self.cols):
                key = f'{row},{col}'
                tile = ChartTile(row * self.cols + col, self.repo, self.scope_getter,
                                 self.cells.get(key), self)
                tile.changed.connect(lambda key=key: self._on_tile_changed(key))
                self.grid.addWidget(tile, row, col)
                self.tile_map[key] = tile
                self.tiles.append(tile)
        for col in range(self.cols):
            self.grid.setColumnStretch(col, 1)
        for row in range(self.rows):
            self.grid.setRowStretch(row, 1)

    def _apply_size(self, *_args):
        self.rows = self.spin_rows.value()
        self.cols = self.spin_cols.value()
        self.rebuild_grid()
        self._persist()

    def _on_tile_changed(self, key):
        tile = self.tile_map.get(key)
        if tile is None:
            return
        if tile.config is None:
            self.cells.pop(key, None)
        else:
            self.cells[key] = tile.config
        self._persist()

    def _persist(self):
        try:
            self.store.save(self.rows, self.cols, self.cells)
        except OSError:
            pass

    # -- Öffentliche API ------------------------------------------------
    def clear_all(self):
        self.cells = {}
        for tile in self.tiles:
            tile.blockSignals(True)
            tile.set_config(None)
            tile.blockSignals(False)
        self._persist()

    def set_cell(self, key: str, config: ChartConfig | None):
        """Belegt eine Zelle programmatisch (z. B. aus Vorlagen)."""
        tile = self.tile_map.get(key)
        if tile is None:
            return
        tile.set_config(config)

    def refresh(self):
        if getattr(self.repo, 'defer_initial_views', False):
            return
        if hasattr(self.repo, 'db') and self.repo.db.in_transaction:
            return
        for tile in self.tiles:
            if tile.config is not None:
                tile.render()
