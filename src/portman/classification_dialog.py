from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QFormLayout,
                               QLabel, QMessageBox, QPushButton, QVBoxLayout)
from .security_classification import CLASSIFICATION_CHOICES


class ClassificationDialog(QDialog):
    def __init__(self, repository, security_key, parent=None):
        super().__init__(parent)
        self.repo, self.key = repository, security_key
        state = repository.security_classification(security_key)
        self.setWindowTitle('Wertpapier bearbeiten')
        self.resize(540, 350)
        root = QVBoxLayout(self)
        title = QLabel(state['name']); title.setObjectName('pageTitle')
        title.setTextFormat(Qt.TextFormat.PlainText); title.setWordWrap(True); root.addWidget(title)
        identity = QLabel(security_key); identity.setTextFormat(Qt.TextFormat.PlainText); root.addWidget(identity)
        note = QLabel('Die Zuordnung gilt für dieses Wertpapier in allen Depots und bleibt dauerhaft gespeichert.')
        note.setWordWrap(True); root.addWidget(note)
        form = QFormLayout(); form.setSpacing(14); root.addLayout(form)
        self.fields = {}
        labels = {'asset_type': 'Anlageklasse / Typ', 'region': 'Region', 'cap_size': 'Größenklasse (Cap)'}
        for field, choices in CLASSIFICATION_CHOICES.items():
            combo = QComboBox()
            combo.addItem('Ursprünglich · ' + state['base'][field], None)
            for value in choices: combo.addItem(value, value)
            value = state['overrides'].get(field)
            if value is not None and combo.findData(value) < 0: combo.addItem(value, value)
            combo.setCurrentIndex(max(0, combo.findData(value)))
            self.fields[field] = combo; form.addRow(labels[field], combo)
        reset = QPushButton('Alle Zuordnungen zurücksetzen')
        reset.clicked.connect(self.reset_fields); root.addWidget(reset)
        hint = QLabel('„Ursprünglich“ verwendet wieder die Import-/Metadaten. Zurücksetzen wird erst mit Speichern übernommen.')
        hint.setWordWrap(True); root.addWidget(hint)
        details = QPushButton('Stammdaten, Depots, Kauftranchen und Steuerangaben …')
        details.clicked.connect(self.open_details); root.addWidget(details)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText('Speichern')
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('Abbrechen')
        buttons.accepted.connect(self.save); buttons.rejected.connect(self.reject); root.addWidget(buttons)

    def reset_fields(self):
        for combo in self.fields.values(): combo.setCurrentIndex(0)

    def open_details(self):
        from .asset_details_dialog import AssetDetailsDialog
        AssetDetailsDialog(self.repo, self.key, self).exec()

    def save(self):
        try:
            self.repo.update_position(self.key, classification={field: combo.currentData() for field, combo in self.fields.items()})
        except ValueError as exc:
            QMessageBox.warning(self, 'Zuordnung prüfen', str(exc)); return
        self.accept()


class WertpapierEditDialog(ClassificationDialog):
    """Central editor opened from the ISIN cell."""
