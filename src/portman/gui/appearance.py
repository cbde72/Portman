"""Persisted application styles, shared by dialogs and detached views."""
from PySide6.QtGui import QActionGroup, QAction, QFont
from PySide6.QtWidgets import (QDialog, QFormLayout, QVBoxLayout, QHBoxLayout,
                              QFontComboBox, QSpinBox, QDialogButtonBox, QLabel, QWidget,
                              QLineEdit)
from portman.theme import STYLES, TABLE_FONT_TYPES, TABLE_FONTS, DEFAULT_TABLE_FONT, apply_theme
from portman.gui.chart_settings import open_chart_settings_dialog

TABLE_FONT_LABELS = {
    'positions': 'Depotpositionen',
    'dashboard': 'Übersicht',
    'history': 'Historie',
    'market': 'Marktdaten',
    'performance': 'Performance',
    'quality': 'Datenqualität',
}


def install_appearance_menu(window):
    """Zentrales ⚙️-Einstellungen-Menü der Anwendung.

    Bündelt Darstellung, Tabellenschriften, Diagramme und die Online-Anbindung,
    die zuvor über die linke Navigationsleiste und das Ansicht-Menü verstreut
    waren.
    """
    menu = window.menuBar().addMenu('⚙️ Einstellungen')
    window.settings_menu = menu

    group = QActionGroup(window)
    group.setExclusive(True)
    window.gui_style_actions = {}
    current = window.settings.get('gui_style', 'dark' if window.settings.get('dark_theme') else 'light')
    for key, title in STYLES.items():
        action = menu.addAction(title)
        action.setCheckable(True)
        group.addAction(action)
        action.setChecked(key == current)
        action.triggered.connect(lambda checked=False, name=key: window.select_gui_style(name))
        window.gui_style_actions[key] = action
    menu.addSeparator()
    fonts_action = QAction('Tabellenschriften …', window)
    fonts_action.triggered.connect(lambda: open_table_font_dialog(window))
    menu.addAction(fonts_action)
    chart_action = QAction('Diagramme …', window)
    chart_action.triggered.connect(lambda: open_chart_settings_dialog(window))
    menu.addAction(chart_action)
    parser_action = QAction('Import-Erkennung …', window)
    parser_action.triggered.connect(lambda: open_import_tags_dialog(window))
    menu.addAction(parser_action)
    menu.addSeparator()
    connection_action = QAction('Online-Anbindung …', window)
    connection_action.triggered.connect(window.open_connection_proposal)
    menu.addAction(connection_action)


def open_import_tags_dialog(window):
    """Edit the words used to recognize generic PDF document types."""
    from pdf_plugins._statement_classification import DOCUMENT_TAGS, normalized_document_tags

    dialog = QDialog(window)
    dialog.setWindowTitle('Import-Erkennung')
    layout = QVBoxLayout(dialog)
    note = QLabel('Tags werden beim Einlesen von PDF-Dateien ohne spezielles Bank-Plugin im Dokumenttext gesucht. Mehrere Tags mit Semikolon trennen.')
    note.setWordWrap(True)
    layout.addWidget(note)
    form = QFormLayout()
    controls = {}
    current = normalized_document_tags(window.settings.get('import_document_tags'))
    for document_type in DOCUMENT_TAGS:
        editor = QLineEdit('; '.join(current[document_type]))
        editor.setClearButtonEnabled(True)
        form.addRow(document_type, editor)
        controls[document_type] = editor
    layout.addLayout(form)
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save |
                               QDialogButtonBox.StandardButton.Cancel |
                               QDialogButtonBox.StandardButton.RestoreDefaults)

    def restore_defaults():
        for document_type, editor in controls.items():
            editor.setText('; '.join(DOCUMENT_TAGS[document_type]))

    buttons.button(QDialogButtonBox.StandardButton.RestoreDefaults).clicked.connect(restore_defaults)
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return
    configured = {}
    for document_type, editor in controls.items():
        values = list(dict.fromkeys(tag.strip() for tag in editor.text().split(';') if tag.strip()))
        configured[document_type] = values or list(DOCUMENT_TAGS[document_type])
    window.settings['import_document_tags'] = configured
    window.save_settings()
    window.statusBar().showMessage('Tags für die Import-Erkennung gespeichert.', 5000)


def open_table_font_dialog(window):
    dialog = QDialog(window)
    dialog.setWindowTitle('Tabellenschriften')
    layout = QVBoxLayout(dialog)
    form = QFormLayout()
    font = TABLE_FONTS or {t: dict(DEFAULT_TABLE_FONT) for t in TABLE_FONT_TYPES}
    controls = {}
    for table_type in TABLE_FONT_TYPES:
        config = font.get(table_type) or dict(DEFAULT_TABLE_FONT)
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        combo = QFontComboBox(); combo.setCurrentFont(QFont(config.get('family') or '', int(config.get('size') or 9)))
        size = QSpinBox(); size.setRange(6, 20); size.setValue(int(config.get('size') or 9))
        row_layout.addWidget(combo, 1); row_layout.addWidget(size)
        controls[table_type] = (combo, size)
        form.addRow(TABLE_FONT_LABELS.get(table_type, table_type), row)
    layout.addLayout(form)
    note = QLabel('Gilt für die jeweiligen Haupttabellen. Dialoge und übrige Tabellen behalten den App-Font.')
    note.setWordWrap(True)
    layout.addWidget(note)
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return
    fonts = {table_type: {'family': combo.currentFont().family(), 'size': spin.value()}
             for table_type, (combo, spin) in controls.items()}
    window.settings['table_fonts_v10'] = fonts
    apply_theme(window.settings.get('gui_style', window.settings.get('dark_theme', False)), fonts)
    window.apply_table_fonts()
    window.save_settings()
