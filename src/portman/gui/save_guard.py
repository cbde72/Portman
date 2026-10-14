"""Error guards around settings, theme and layout persistence."""
from PySide6.QtWidgets import QMessageBox


class SaveGuardMixin:
    def save_settings(self):
        if hasattr(self, 'preferences'): self.preferences.save()
        return super().save_settings()

    def save_named_layout(self):
        try:
            super().save_named_layout()
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, 'Layout nicht gespeichert', str(error))

    def on_etf_fetch_done(self, new_etf_data, failures):
        try:
            super().on_etf_fetch_done(new_etf_data, failures)
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, 'ETF-Daten nicht gespeichert', str(error))

    def save_layout_settings(self):
        try:
            if hasattr(self, 'preferences'): self.preferences.save()
            super().save_layout_settings()
        except (OSError, ValueError) as error:
            self.statusBar().showMessage(f'Einstellungen nicht gespeichert: {error}. Mit Strg+S erneut versuchen.')

    def closeEvent(self, event):
        try:
            super().closeEvent(event)
        except Exception as error:
            event.ignore()
            QMessageBox.warning(self, 'Speichern fehlgeschlagen',
                                f'{error}\nDas Fenster bleibt geöffnet. Bitte erneut speichern.')
