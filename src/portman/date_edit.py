"""Date text input with German presentation and ISO persistence."""
from datetime import datetime
from PySide6.QtWidgets import QLineEdit
from .date_display import display_dates


class DateLineEdit(QLineEdit):
    def __init__(self, value='', parent=None):
        super().__init__(display_dates(value), parent)
        self.setPlaceholderText('TT.MM.JJJJ')

    def setText(self, value):
        super().setText(display_dates(value))

    def text(self):
        value = super().text().strip()
        try:
            return datetime.strptime(value, '%d.%m.%Y').date().isoformat()
        except ValueError:
            return value
