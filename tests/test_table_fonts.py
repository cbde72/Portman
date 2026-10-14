import os
import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from portman import theme
from portman.preferences_v09 import table_font_type


def test_table_font_rules_typed_selectors():
    fonts = {'positions': {'family': 'Noto Sans', 'size': 11}, 'market': {'family': '', 'size': 0}}
    qss = theme.table_font_rules(fonts)
    assert 'QTableView[table_type="positions"]' in qss
    assert 'font-family: "Noto Sans";' in qss
    assert 'font-size: 11pt;' in qss
    assert 'QTableView[table_type="positions"] QHeaderView::section' in qss
    assert 'market' not in qss


def test_table_font_rules_empty():
    assert theme.table_font_rules({}) == ''


@pytest.mark.parametrize('size,compact,expected', [(9, False, 30), (9, True, 24), (20, False, 41), (6, False, 27)])
def test_row_height_for(size, compact, expected):
    assert theme.row_height_for(size, compact) == expected


def test_table_font_type_mapping():
    assert table_font_type('positions.Alle') == 'positions'
    assert table_font_type('dashboard.top') == 'dashboard'
    assert table_font_type('history_widget.wealth_table') == 'history'
    assert table_font_type('market_widget.table') == 'market'
    assert table_font_type('performance_widget.comparison') == 'performance'
    assert table_font_type('quality_widget.table') == 'quality'
    assert table_font_type('unbekannt.x') is None


def test_positions_bold_font_uses_configuration():
    from portman.positions_model import _bold_font
    theme.TABLE_FONTS.clear()
    theme.TABLE_FONTS['positions'] = {'family': 'Consolas', 'size': 10}
    try:
        font = _bold_font()
        assert font.bold()
        assert font.family() == 'Consolas'
        assert font.pointSize() == 10
    finally:
        theme.TABLE_FONTS.clear()


def test_apply_theme_adds_rules():
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    fonts = {'positions': {'family': 'Consolas', 'size': 10}}
    theme.apply_theme('nord', fonts)
    assert theme.TABLE_FONTS == fonts
    assert 'QTableView[table_type="positions"] {' in app.styleSheet()