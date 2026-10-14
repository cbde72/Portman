"""Chart settings dialog: export format selection and persistence (chart_v10)."""
import os

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtWidgets import QApplication, QDialog, QWidget

from portman.chart_style import CHART_STYLE
from portman.gui.chart_settings import open_chart_settings_dialog, parse_export_formats


class FakeWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.settings = {}

    def refresh_charts_after_style(self):
        pass

    def save_settings(self):
        pass


def test_parse_export_formats_merges_checked_and_extras():
    assert parse_export_formats(['png', 'svg'], '') == ['png', 'svg']
    assert parse_export_formats(['png'], 'eps, .ps; pgf') == ['png', 'eps', 'ps', 'pgf']
    assert parse_export_formats(['png'], 'PNG,  tif  ,png') == ['png', 'tif']
    assert parse_export_formats([], '') == []
    assert parse_export_formats(['webp'], ', ,') == ['webp']


def test_chart_settings_dialog_persists_export_formats(monkeypatch):
    QApplication.instance() or QApplication([])
    window = FakeWindow()
    monkeypatch.setattr(QDialog, 'exec', lambda self: QDialog.DialogCode.Accepted)
    open_chart_settings_dialog(window)
    config = window.settings['chart_v10']
    assert config['export_formats'] == list(CHART_STYLE.get('export_formats', ['png']))
    assert config['export_dpi'] == CHART_STYLE['export_dpi']
    assert config['figure_width'] == float(CHART_STYLE['figure_width'])


def test_chart_settings_dialog_cancel_applies_nothing(monkeypatch):
    QApplication.instance() or QApplication([])
    window = FakeWindow()
    monkeypatch.setattr(QDialog, 'exec', lambda self: QDialog.DialogCode.Rejected)
    open_chart_settings_dialog(window)
    assert 'chart_v10' not in window.settings


def test_export_appends_configured_format_and_uses_dpi(tmp_path, monkeypatch):
    QApplication.instance() or QApplication([])
    from portman import visualizations
    from portman.repository_v09 import RepositoryV09

    repo = RepositoryV09(tmp_path / 'export.sqlite', backups=False)
    try:
        monkeypatch.setitem(CHART_STYLE, 'export_formats', ['svg', 'png'])
        monkeypatch.setitem(CHART_STYLE, 'export_dpi', 210)
        saved = []
        monkeypatch.setattr(visualizations, 'save_figure',
                            lambda fig, path, dpi: saved.append((path, dpi)))

        class FakeFileDialog:
            @staticmethod
            def getSaveFileName(*args, **kwargs):
                return str(tmp_path / 'chart'), ''

        monkeypatch.setattr(visualizations, 'QFileDialog', FakeFileDialog)
        widget = visualizations.VisualizationsWidget(repo, lambda: (None, '2026-12-31'))
        widget.export()
        assert saved == [(str(tmp_path / 'chart.svg'), 210)]
    finally:
        repo.close()


def test_export_keeps_suffix_when_format_configured(tmp_path, monkeypatch):
    QApplication.instance() or QApplication([])
    from portman import visualizations
    from portman.repository_v09 import RepositoryV09

    repo = RepositoryV09(tmp_path / 'export2.sqlite', backups=False)
    try:
        monkeypatch.setitem(CHART_STYLE, 'export_formats', ['svg', 'png'])
        saved = []
        monkeypatch.setattr(visualizations, 'save_figure', lambda fig, path, dpi: saved.append(path))
        class FakeFileDialog:
            @staticmethod
            def getSaveFileName(*args, **kwargs):
                return str(tmp_path / 'chart.png'), ''

        monkeypatch.setattr(visualizations, 'QFileDialog', FakeFileDialog)
        widget = visualizations.VisualizationsWidget(repo, lambda: (None, '2026-12-31'))
        widget.export()
        assert saved == [str(tmp_path / 'chart.png')]
    finally:
        repo.close()