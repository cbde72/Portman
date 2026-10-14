"""Selectable and explicitly copyable banking status messages."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QPushButton


def add_copy_button(layout, status, *, text_provider=None):
    status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse
                                   | Qt.TextInteractionFlag.TextSelectableByKeyboard)
    button = QPushButton('Meldung kopieren')
    button.setToolTip('Den vollständigen Meldungstext in die Zwischenablage kopieren')
    button.setAutoDefault(False)
    provider = text_provider or status.text
    button.clicked.connect(lambda: QApplication.clipboard().setText(provider()))
    layout.addWidget(button)
    return button
