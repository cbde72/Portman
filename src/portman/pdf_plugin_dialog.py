from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QHBoxLayout, QLabel,
                               QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout)

from portfolio_v5.pdf_plugins import discover_plugins


class PdfPluginDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('PDF-Import-Plugins')
        self.resize(900, 520)
        root = QVBoxLayout(self)
        note = QLabel('Eine Bank kann mehrere Dokumenttypen bereitstellen. TOML-Profile liegen im Ordner pdf_plugins; '
                      'Python-Erweiterungen werden über den Entry-Point „portman.pdf_importers“ installiert.')
        note.setWordWrap(True); root.addWidget(note)
        self.table = QTableWidget(); self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(['Bank', 'Plugin-ID', 'Version', 'Dokumenttypen', 'Quelle'])
        self.table.horizontalHeader().setStretchLastSection(True); root.addWidget(self.table)
        self.errors = QLabel(); self.errors.setWordWrap(True); root.addWidget(self.errors)
        bar = QHBoxLayout()
        folder = QPushButton('Profilordner öffnen')
        folder.clicked.connect(self.open_folder); bar.addWidget(folder)
        reload_button = QPushButton('Neu laden'); reload_button.clicked.connect(self.refresh); bar.addWidget(reload_button)
        bar.addStretch(); root.addLayout(bar)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.accept); root.addWidget(buttons)
        self.refresh()

    @staticmethod
    def profile_folder():
        from portman.gui.window_compat import project_root
        folder = project_root() / 'pdf_plugins'; folder.mkdir(exist_ok=True)
        return folder

    def open_folder(self):
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.profile_folder().resolve())))

    def refresh(self):
        plugins, errors = discover_plugins([self.profile_folder()])
        self.table.setRowCount(len(plugins))
        for row, plugin in enumerate(plugins):
            documents = getattr(plugin, 'documents', None)
            if documents:
                types = ', '.join(item['type'] for item in documents)
                source = str(getattr(plugin, 'path', 'TOML-Profil'))
            else:
                types = getattr(plugin, 'document_types', 'Vom Python-Plugin bereitgestellt')
                source = str(getattr(plugin, 'source_path', 'Python Entry-Point'))
            for column, value in enumerate((plugin.bank_name, plugin.plugin_id, plugin.version, types, source)):
                self.table.setItem(row, column, QTableWidgetItem(str(value)))
        self.table.resizeColumnsToContents()
        self.errors.setText('' if not errors else 'Nicht geladene Plugins:\n' + '\n'.join(errors))
