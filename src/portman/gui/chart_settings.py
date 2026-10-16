"""Configurable chart appearance dialog (settings key ``chart_v10``)."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QFormLayout, QVBoxLayout, QHBoxLayout, QDoubleSpinBox,
                               QSpinBox, QCheckBox, QDialogButtonBox, QLabel, QGroupBox,
                               QPushButton, QFrame, QListWidget, QListWidgetItem, QLineEdit,
                               QAbstractItemView)
from portman.chart_style import CHART_STYLE, apply_chart_style

KNOWN_EXPORT_FORMATS = ['png', 'svg', 'pdf', 'jpg', 'jpeg', 'webp', 'tif']


def parse_export_formats(checked, extras_text):
    """Combines checked formats with comma/semicolon-separated extras."""
    extra = [part.strip().lstrip('.').lower() for part in
             extras_text.replace(';', ',').split(',') if part.strip()]
    return checked + [fmt for fmt in extra if fmt not in checked]


class ChartSettingsMixin:
    """Shared "Diagramme …" entry point for widgets that live in a main window."""

    def open_chart_settings(self):
        window = self.window()
        if window is None or not hasattr(window, 'refresh_charts_after_style'):
            return
        open_chart_settings_dialog(window)


def open_chart_settings_dialog(window):
    dialog = QDialog(window)
    dialog.setWindowTitle('Diagramm-Einstellungen')
    layout = QVBoxLayout(dialog)
    controls = {}
    form = QFormLayout()

    width = QDoubleSpinBox(); width.setRange(4.0, 24.0); width.setSingleStep(0.5)
    width.setValue(float(CHART_STYLE['figure_width']))
    height = QDoubleSpinBox(); height.setRange(2.0, 12.0); height.setSingleStep(0.1)
    height.setValue(float(CHART_STYLE['figure_height']))
    row = QHBoxLayout(); row.addWidget(width); row.addWidget(QLabel('×')); row.addWidget(height)
    form.addRow('Figurengröße (Breite × Höhe)', row)
    controls['figure_width'] = lambda: width.value()
    controls['figure_height'] = lambda: height.value()

    for key, label, minimum, maximum, callback_type in (
        ('dpi', 'Bildschirm-DPI', 72, 300, int),
        ('export_dpi', 'Export-DPI (Raster)', 72, 600, int),
        ('base_fontsize', 'Tickschriftgröße', 6, 14, int),
        ('title_fontsize', 'Titelgröße', 8, 20, int),
        ('legend_fontsize', 'Legendengröße', 6, 16, int),
        ('top_n', 'Top-N Positionen', 3, 30, int),
        ('max_months', 'Monate (Vermögensänderung)', 6, 60, int),
    ):
        spin = QSpinBox(); spin.setRange(minimum, maximum)
        spin.setValue(int(CHART_STYLE[key]))
        form.addRow(label, spin)
        controls[key] = lambda spin=spin, t=callback_type: t(spin.value())

    grid = QCheckBox('Horizontales Raster anzeigen')
    grid.setChecked(bool(CHART_STYLE['grid_alpha']))
    layout.addLayout(form)
    group = QGroupBox('Raster')
    g_layout = QVBoxLayout(group); g_layout.addWidget(grid)
    layout.addWidget(group)

    note = QLabel('Betrifft die Haupt-Diagramme (Vermögen, Konten, Positionen, Kursvergleich).')
    note.setWordWrap(True)
    layout.addWidget(note)

    export_group = QGroupBox('Export-Dateiformate')
    export_layout = QVBoxLayout(export_group)
    export_hint = QLabel('Wählen Sie die Formate, die „Alle Diagramme speichern“ erzeugt. Die DPI-Einstellung gilt für Rasterformate.')
    export_hint.setWordWrap(True)
    export_layout.addWidget(export_hint)
    formats = set(CHART_STYLE.get('export_formats') or [])
    format_list = QListWidget()
    format_list.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
    format_list.setMaximumHeight(150)
    for fmt in KNOWN_EXPORT_FORMATS:
        item = QListWidgetItem(fmt)
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(Qt.CheckState.Checked if fmt in formats else Qt.CheckState.Unchecked)
        format_list.addItem(item)
    export_layout.addWidget(format_list)
    export_layout.addWidget(QLabel('Weitere Formate (kommagetrennt):'))
    extra_formats = QLineEdit(', '.join(sorted(formats - set(KNOWN_EXPORT_FORMATS))))
    export_layout.addWidget(extra_formats)
    layout.addWidget(export_group)

    def read_export_formats():
        checked = [format_list.item(i).text() for i in range(format_list.count())
                   if format_list.item(i).checkState() == Qt.CheckState.Checked]
        return parse_export_formats(checked, extra_formats.text())

    controls['export_formats'] = read_export_formats

    # Benutzerdefinierte Diagramme
    layout.addWidget(QFrame())
    custom_group = QGroupBox('Benutzerdefinierte Diagramme')
    custom_layout = QVBoxLayout(custom_group)
    custom_note = QLabel('Erstellen und verwalten Sie eigene Diagramme mit beliebigen Typen, Datenquellen und Styling.')
    custom_note.setWordWrap(True)
    custom_layout.addWidget(custom_note)
    custom_btn = QPushButton('Eigene Diagramme verwalten …')
    custom_btn.clicked.connect(lambda: _open_custom_charts(window))
    custom_layout.addWidget(custom_btn)
    layout.addWidget(custom_group)

    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return
    config = {key: reader() for key, reader in controls.items()}
    config['grid_alpha'] = CHART_STYLE['grid_alpha'] if grid.isChecked() else 0.0
    window.settings['chart_v10'] = config
    apply_chart_style(config)
    window.refresh_charts_after_style()
    window.save_settings()


def _open_custom_charts(window):
    """Öffnet den Dialog zur Verwaltung benutzerdefinierter Diagramme."""
    from portman.chart_config import default_manager
    from portman.chart_config_dialog import CustomChartsDialog
    repo = getattr(window, 'repository', None)
    scope_getter = getattr(window, 'dashboard_scope', None)
    manager = default_manager(repo)
    dialog = CustomChartsDialog(manager, window, repo=repo, scope_getter=scope_getter)
    if dialog.exec():
        # Diagramme neu laden und alle Charts aktualisieren
        board = getattr(window, 'visualizations_board', None)
        if board is not None and hasattr(board, 'reload_custom_charts'):
            board.reload_custom_charts()
        if hasattr(window, 'refresh_charts_after_style'):
            window.refresh_charts_after_style()
        if hasattr(window, 'save_settings'):
            window.save_settings()
