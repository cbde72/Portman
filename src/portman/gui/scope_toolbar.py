"""Latest-available-date scope controls shared by the version windows."""
from PySide6.QtCore import QDate
from PySide6.QtWidgets import QLabel, QPushButton


class LatestScopeMixin:
    def selected_date(self):
        if hasattr(self, 'combo_snapshot') and self.combo_snapshot.currentData() == '9999-12-31':
            return '9999-12-31'
        return super().selected_date()

    def install_latest_scope(self):
        self.combo_snapshot.setItemText(0, 'Letzte verfügbare Daten')
        latest = QPushButton('Letzte Daten')
        latest.setFixedWidth(110)
        latest.setCheckable(True)
        latest.setToolTip('Je Konto der letzte gespeicherte Stand; Daten können unterschiedlich alt sein.')
        latest.clicked.connect(lambda: self.combo_snapshot.setCurrentIndex(0))
        self.scope_toolbar.addWidget(latest)
        self.scope_note = QLabel('Bestände: Stichtag · Analysen: eigener Zeitraum')
        self.scope_note.setMinimumWidth(220)
        self.scope_toolbar.addWidget(self.scope_note)

        def update_scope_note():
            is_latest = self.combo_snapshot.currentData() == '9999-12-31'
            latest.setChecked(is_latest); self.date_selector.setEnabled(not is_latest)
            self.scope_note.setText('Letzter Stand je Konto' if is_latest else 'Bestände: Stichtag · Performance/Analyse: eigener Zeitraum')

        self.combo_snapshot.currentIndexChanged.connect(update_scope_note)
        for button in self.scope_toolbar.findChildren(QPushButton):
            if button.text() == 'Heute': button.clicked.connect(lambda: self.select_calendar_date(QDate.currentDate()))
        update_scope_note()
