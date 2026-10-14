"""Shared desktop theme, including floating docks and dialogs."""
from PySide6.QtGui import QFont, QColor, QPalette
from PySide6.QtWidgets import QApplication
from .chart_style import COLORS


STYLES = {'light': 'Hell', 'dark': 'Dunkel', 'nord': 'Nord', 'contrast': 'Hoher Kontrast'}

# Configurable per table-type fonts (settings key ``table_fonts_v10``).
# Empty values keep the global application font.
TABLE_FONT_TYPES = ('positions', 'dashboard', 'history', 'market', 'performance', 'quality')
DEFAULT_TABLE_FONT = {'family': 'Segoe UI', 'size': 9}
TABLE_FONTS = {}


def row_height_for(size, compact=False):
    default = int(DEFAULT_TABLE_FONT['size'])
    return max(18, int(round(size or default)) + 21 - (6 if compact else 0))


def table_font_rules(fonts=None):
    rules = []
    for table_type in TABLE_FONT_TYPES:
        config = (fonts or {}).get(table_type) or {}
        family = str(config.get('family') or '').strip()
        size = int(config.get('size') or 0)
        declarations = []
        if family: declarations.append(f'font-family: "{family}";')
        if size: declarations.append(f'font-size: {size}pt;')
        if not declarations: continue
        body = ' '.join(declarations)
        rules.append(f'QTableView[table_type="{table_type}"] {{ {body} }}')
        rules.append(f'QTableView[table_type="{table_type}"] QHeaderView::section {{ {body} }}')
    return '\n        '.join(rules)


def apply_theme(dark=False, table_fonts=None):
    app = QApplication.instance()
    app.setStyle('Fusion')
    app.setFont(QFont('Segoe UI', 9))
    style = dark if isinstance(dark, str) else ('dark' if dark else 'light')
    TABLE_FONTS.clear(); TABLE_FONTS.update(table_fonts or {})
    dark = style in ('dark', 'nord', 'contrast')
    if style == 'light':
        bg, panel, text, muted, border, alternate = '#f5f5f5', '#ffffff', '#1f2937', '#6b7280', '#d0d0d0', '#f8f9fa'
    elif style == 'nord':
        bg, panel, text, muted, border, alternate = '#2e3440', '#3b4252', '#eceff4', '#aebacf', '#4c566a', '#434c5e'
    elif style == 'contrast':
        bg, panel, text, muted, border, alternate = '#000000', '#111111', '#ffffff', '#cccccc', '#ffffff', '#181818'
    else:  # dark
        bg, panel, text, muted, border, alternate = '#1a1a1a', '#242424', '#f5f5f5', '#9ca3af', '#3f3f3f', '#2a2a2a'
    COLORS.update(text=text, grid=border, background=bg, panel=panel, muted=muted)
    palette = QPalette()
    for role, value in [(QPalette.ColorRole.Window, bg), (QPalette.ColorRole.WindowText, text),
                        (QPalette.ColorRole.Base, panel), (QPalette.ColorRole.AlternateBase, alternate),
                        (QPalette.ColorRole.Text, text), (QPalette.ColorRole.Button, panel),
                        (QPalette.ColorRole.ButtonText, text), (QPalette.ColorRole.Highlight, '#2563eb'),
                        (QPalette.ColorRole.HighlightedText, '#ffffff'),
                        (QPalette.ColorRole.ToolTipBase, panel), (QPalette.ColorRole.ToolTipText, text)]:
        palette.setColor(role, QColor(value))
    app.setPalette(palette)
    app.setStyleSheet(f'''
        QMainWindow, QDialog, QWidget {{ color: {text}; background: transparent; }}
        QMainWindow, QDialog {{ background: {bg}; }}
        QToolBar {{ background: {panel}; border: none; spacing: 6px; padding: 6px 8px; border-bottom: 1px solid {border}; border-radius: 6px; }}
        QToolBar#navigation {{ background: {alternate}; border: none; border-right: 1px solid {border}; padding: 0; border-radius: 0; }}
        QWidget#navigationPanel, QScrollArea#navigationScroll {{ background: {alternate}; }}
        QLabel#brand {{ color: {text}; font-size: 18px; font-weight: 700; padding: 6px 10px; }}
        QLabel#navCaption {{ color: {muted}; font-size: 9px; font-weight: 600; padding: 12px 10px 6px; text-transform: uppercase; letter-spacing: 0.06em; }}
        QPushButton#navButton {{ color: {text}; background: transparent; text-align: left;
            border: 1px solid transparent; border-radius: 6px; padding: 8px 10px; font-weight: 500; }}
        QPushButton#navButton:hover {{ background: {border}; }}
        QPushButton#navButton:checked {{ background: {panel}; color: #3b82f6;
            border: 1px solid {border}; border-left: 3px solid #3b82f6; font-weight: 600; }}
        QPushButton#navButton:focus {{ border: 1px solid #3b82f6; outline: none; }}
        QLabel#pageTitle {{ font-size: 18px; font-weight: 700; }}
        QLabel#muted {{ color: {muted}; }}
        QLabel#metricValue {{ font-size: 22px; font-weight: 700; }}
        QGroupBox {{ background: {panel}; border: 1px solid {border}; border-radius: 8px;
            margin-top: 12px; padding: 14px 12px 12px; font-weight: 600; }}
        QGroupBox::title {{ subcontrol-origin: margin; left: 14px; padding: 0 6px; color: {muted}; }}
        QPushButton {{ border: 1px solid {border}; background: {panel}; color: {text}; padding: 6px 12px;
            border-radius: 6px; font-weight: 500; }}
        QPushButton:hover {{ background: {alternate}; }}
        QPushButton:pressed {{ background: {border}; }}
        QPushButton:focus, QPushButton:checked {{ border: 1px solid #3b82f6; outline: none; }}
        QPushButton:default {{ background: #2563eb; color: #ffffff; border: 1px solid #2563eb; font-weight: 600; }}
        QPushButton:default:hover {{ background: #1d4ed8; }}
        QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox, QDateEdit, QComboBox {{ background: {panel}; color: {text}; border: 1px solid {border}; border-radius: 6px; padding: 6px 8px; }}
        QComboBox QAbstractItemView {{ background-color: {panel}; color: {text};
            selection-background-color: #2563eb; selection-color: #ffffff;
            border: 1px solid {border}; outline: none; padding: 4px; }}
        QComboBox QAbstractItemView::item {{ min-height: 24px; padding: 4px 8px; }}
        QLineEdit:focus, QTextEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QDateEdit:focus, QComboBox:focus {{ border: 1px solid #3b82f6; outline: none; }}
        QTableWidget, QTableView, QTreeWidget, QTreeView {{ background: {panel}; alternate-background-color: {alternate}; color: {text}; gridline-color: {border}; border: 1px solid {border}; border-radius: 6px; }}
        QHeaderView::section {{ background: {alternate}; color: {muted}; padding: 8px; border: none; border-right: 1px solid {border}; font-weight: 600; }}
        QStatusBar {{ background: {panel}; border-top: 1px solid {border}; color: {muted}; padding: 4px 10px; }}
        QStatusBar::item {{ border: none; }}
        QMenuBar {{ background: {panel}; color: {text}; border-bottom: 1px solid {border}; padding: 3px 6px; }}
        QMenuBar::item {{ background: transparent; color: {text}; padding: 6px 10px; border-radius: 4px; }}
        QMenuBar::item:selected {{ background: {alternate}; }}
        QMenu {{ background: {panel}; color: {text}; border: 1px solid {border}; border-radius: 6px; padding: 4px; }}
        QMenu::item {{ padding: 8px 14px; border-radius: 4px; }}
        QMenu::item:selected {{ background: {alternate}; }}
        QDockWidget {{ titlebar-close-icon: none; titlebar-normal-icon: none; }}
        QDockWidget::title {{ background: {alternate}; color: {text}; padding: 8px 10px; border: 1px solid {border}; border-bottom: none; border-top-left-radius: 6px; border-top-right-radius: 6px; font-weight: 600; }}
        QDockWidget::close-button, QDockWidget::float-button {{ margin: 2px; }}
        QTabWidget::pane {{ background: {panel}; border: 1px solid {border}; border-radius: 6px; top: -1px; }}
        QTabBar::tab {{ background: {alternate}; color: {text}; border: 1px solid {border}; padding: 8px 12px; margin-right: 4px; border-top-left-radius: 6px; border-top-right-radius: 6px; }}
        QTabBar::tab:selected {{ background: {panel}; border-bottom: 1px solid {panel}; font-weight: 600; }}
        QScrollBar:vertical {{ width: 10px; background: transparent; }}
        QScrollBar::handle:vertical {{ background: {border}; border-radius: 5px; min-height: 30px; }}
        QScrollBar::handle:vertical:hover {{ background: {muted}; }}
        QToolTip {{ background: {panel}; color: {text}; border: 1px solid {border}; border-radius: 6px; padding: 6px 10px; }}
        {table_font_rules(TABLE_FONTS)}
        QGroupBox#wealthHero {{ background: {panel}; border: 1px solid {border}; border-left: 3px solid #3b82f6; }}
        QGroupBox#wealthHero QLabel {{ color: {text}; }}
        QGroupBox#wealthHero::title {{ color: {muted}; }}
        QPushButton {{ background: {panel}; border: 1px solid {border}; border-radius: 6px; padding: 6px 10px; }}
        QPushButton:hover {{ border-color: #3b82f6; background: {alternate}; }}
        QPushButton:focus {{ border: 1px solid #3b82f6; outline: none; }}
        QPushButton:pressed {{ background: {border}; }}
        QPushButton:disabled {{ color: {muted}; }}
        QPushButton#primary {{ background: #2563eb; color: white; border: 1px solid #2563eb; font-weight: 600; border-radius: 6px; }}
        QPushButton#primary:hover {{ background: #1d4ed8; }}
        QPushButton#primary:focus {{ border: 1px solid #93c5fd; }}
        QTableView, QTreeView, QTextEdit {{ background: {panel}; alternate-background-color: {alternate};
            border: 1px solid {border}; border-radius: 8px; gridline-color: {border};
            selection-background-color: #2563eb; selection-color: white; }}
        QTableView::item, QTreeView::item {{ padding: 4px; }}
        QHeaderView::section {{ background: {alternate}; color: {muted}; border: none;
            border-bottom: 1px solid {border}; padding: 6px 7px; font-weight: 700; }}
        QDockWidget::title {{ background: {bg}; padding: 8px 10px; font-size: 11px; font-weight: 600; border-radius: 6px; }}
        QDockWidget {{ border: 1px solid {border}; border-radius: 8px; }}
        QTabWidget::pane {{ border: none; }}
        QTabBar::tab {{ background: {bg}; color: {muted}; padding: 7px 12px; border-bottom: 2px solid transparent; }}
        QTabBar::tab:selected {{ color: #3b82f6; border-bottom: 2px solid #3b82f6; font-weight: 600; }}
        QMenuBar, QMenu {{ background: {panel}; }}
        QMenuBar::item, QMenu::item {{ padding: 6px 14px; }}
        QMenuBar::item:selected, QMenu::item:selected {{ background: #2563eb; color: white; }}
        QMenu::item {{ padding: 6px 16px; }}
        QProgressBar {{ border: 1px solid {border}; border-radius: 5px; text-align: center; }}
        QProgressBar::chunk {{ background: #2563eb; border-radius: 4px; }}
        QScrollBar:vertical {{ width: 10px; background: {bg}; }}
        QScrollBar::handle:vertical {{ background: {border}; border-radius: 5px; min-height: 30px; }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
        QToolTip {{ background: {panel}; color: {text}; border: 1px solid {border}; padding: 6px; }}
        {table_font_rules(TABLE_FONTS)}
    ''')
