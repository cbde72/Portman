"""Responsive multi-chart workspace using the shared chart data cache."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QPushButton, QSplitter

from .visualizations import VisualizationsWidget
from .chart_config import default_manager


class VisualizationBoard(QWidget):
    MODES = [('Ein Diagramm', 1), ('Zwei nebeneinander', 2), ('Vier als 2 × 2', 4)]

    def __init__(self, repo, scope_getter, settings=None, save=None, parent=None):
        super().__init__(parent)
        self.settings, self.save = settings if settings is not None else {}, None
        self.repo = repo
        self.scope_getter = scope_getter
        # Benutzerdefinierte Diagramme laden
        self.config_manager = default_manager(repo)
        self._load_custom_charts()
        root = QVBoxLayout(self); root.setContentsMargins(0, 0, 0, 0); root.setSpacing(6)
        controls = QHBoxLayout(); controls.setContentsMargins(6, 4, 6, 0)
        controls.addWidget(QLabel('Diagramm-Layout'))
        self.mode = QComboBox()
        for label, count in self.MODES: self.mode.addItem(label, count)
        controls.addWidget(self.mode)
        custom_btn = QPushButton('Eigene Diagramme …')
        custom_btn.clicked.connect(self.open_custom_charts)
        controls.addWidget(custom_btn)
        controls.addStretch()
        settings_button = QPushButton('Diagramme …'); settings_button.clicked.connect(self.open_chart_settings)
        controls.addWidget(settings_button)
        root.addLayout(controls)
        self.vertical = QSplitter(Qt.Orientation.Vertical)
        self.rows = [QSplitter(Qt.Orientation.Horizontal), QSplitter(Qt.Orientation.Horizontal)]
        for row in self.rows: self.vertical.addWidget(row)
        root.addWidget(self.vertical, 1)
        defaults = (0, 3, 4, 5)
        self.charts = [VisualizationsWidget(repo, scope_getter, self, compact=True, initial_view=view,
                                            custom_charts=self.custom_charts)
                       for view in defaults]
        self.rows[0].addWidget(self.charts[0]); self.rows[0].addWidget(self.charts[1])
        self.rows[1].addWidget(self.charts[2]); self.rows[1].addWidget(self.charts[3])
        self.primary = self.charts[0]
        requested = int(self.settings.get('visualization_count', 4))
        index = self.mode.findData(requested)
        self.mode.setCurrentIndex(index if index >= 0 else 2)
        self.mode.currentIndexChanged.connect(self.apply_mode)
        self.apply_mode()
        self.save = save

    def _load_custom_charts(self):
        """Lädt benutzerdefinierte Diagramme aus der JSON-Datei."""
        loaded = self.config_manager.load()
        # Falls keine Konfigurationen vorhanden, Defaults anbieten
        if not loaded:
            from .chart_config import default_configs
            loaded = {c.id: c for c in default_configs()}
            self.config_manager.save(loaded)
        self.custom_charts = list(loaded.values())

    def _save_custom_charts(self):
        """Speichert benutzerdefinierte Diagramme in der JSON-Datei."""
        self.config_manager.save({c.id: c for c in self.custom_charts})

    def apply_mode(self, *_args):
        count = self.mode.currentData()
        for index, chart in enumerate(self.charts): chart.setVisible(index < count)
        self.rows[1].setVisible(count == 4)
        self.rows[0].setSizes([1, 1] if count > 1 else [1, 0])
        self.vertical.setSizes([1, 1] if count == 4 else [1, 0])
        self.settings['visualization_count'] = count
        if self.save: self.save()
        self.refresh()

    def refresh(self):
        for chart in self.charts:
            if chart.isVisible(): chart.refresh()

    def open_chart_settings(self):
        window = self.window()
        if window is None or not hasattr(window, 'refresh_charts_after_style'):
            return
        from .gui.chart_settings import open_chart_settings_dialog
        open_chart_settings_dialog(window)

    def open_custom_charts(self):
        """Öffnet den Dialog zur Verwaltung benutzerdefinierter Diagramme."""
        from .chart_config_dialog import CustomChartsDialog
        dialog = CustomChartsDialog(self.config_manager, self, repo=self.repo,
                                    scope_getter=self.scope_getter)
        dialog.exec()
        self.reload_custom_charts()

    def reload_custom_charts(self):
        """Lädt die benutzerdefinierten Diagramme neu und aktualisiert alle Ansichten."""
        self.config_manager.load()
        self.custom_charts = list(self.config_manager.all())
        self._save_custom_charts()
        for chart in self.charts:
            chart.custom_charts = list(self.custom_charts)
            chart._update_custom_charts()
        self.refresh()
