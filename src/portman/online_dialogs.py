import os
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QFormLayout, QLineEdit, QComboBox,
    QLabel, QDialogButtonBox, QMessageBox, QCheckBox, QTabWidget, QWidget)
from .online_providers import PROVIDERS, DIVVY


class OnlineCredentialsDialog(QDialog):
    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store
        self.setWindowTitle('Online-Zugänge'); self.resize(650, 480)
        root = QVBoxLayout(self)
        note = QLabel('API-Schlüssel eintragen. Leere Felder behalten bestehende Schlüssel. Yahoo Finance und Kraken benötigen keinen Schlüssel.')
        note.setWordWrap(True); root.addWidget(note)
        tabs = QTabWidget(); root.addWidget(tabs)
        self.fields, self.removals = {}, {}
        for provider, info in {**{k: v for k, v in PROVIDERS.items() if v['key']}, 'divvydiary': DIVVY}.items():
            page = QWidget(); form = QFormLayout(page); form.setSpacing(18)
            hint = QLabel(info['hint']); hint.setWordWrap(True); form.addRow(hint)
            link = QLabel(f'<a href="{info["url"]}">Beim Anbieter einrichten / Tarif prüfen ↗</a>')
            link.setOpenExternalLinks(True); form.addRow(link)
            if info.get('daily'):
                used = store.daily_usage().get(provider, 0)
                form.addRow(QLabel(f'Heute in PortMan verwendet: {used} / {info["daily"]} Abrufe (UTC)'))
            field = QLineEdit(); field.setEchoMode(QLineEdit.EchoMode.Password)
            field.setPlaceholderText('Schlüssel hinterlegt – leer lassen zum Beibehalten' if store.credentials.has(provider) else 'Noch kein Schlüssel hinterlegt')
            field.setMaxLength(4096)
            remove = QCheckBox('Gespeicherten Schlüssel entfernen')
            form.addRow('API-Schlüssel', field); form.addRow(remove)
            self.fields[provider], self.removals[provider] = field, remove
            tabs.addTab(page, info['name'])
        self.persist = QCheckBox('Neue Schlüssel verschlüsselt für diesen Windows-Benutzer speichern')
        self.persist.setChecked(os.name == 'nt'); self.persist.setEnabled(os.name == 'nt'); root.addWidget(self.persist)
        note = QLabel('Ohne Speicherung gelten neue Schlüssel nur für diese Sitzung. Es wird kein Abonnement abgeschlossen. Lokale Abrufbudgets orientieren sich an kostenlosen Kontingenten; die Freigabe des Anbieters gilt zusätzlich.')
        note.setWordWrap(True); root.addWidget(note)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText('Speichern')
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('Abbrechen')
        buttons.accepted.connect(self.save); buttons.rejected.connect(self.reject); root.addWidget(buttons)

    def save(self):
        remove = [p for p, checkbox in self.removals.items() if checkbox.isChecked()]
        values = {p: field.text() for p, field in self.fields.items() if p not in remove}
        try: self.store.credentials.update(values, remove, self.persist.isChecked())
        except ValueError as exc:
            QMessageBox.warning(self, 'Online-Zugänge', str(exc)); return
        self.accept()


class FeedDialog(QDialog):
    def __init__(self, store, position, parent=None):
        super().__init__(parent)
        self.store, self.position = store, position
        self.original = store.mappings().get(position['key'], {})
        self.setWindowTitle('Kursquelle · ' + position['name']); self.resize(650, 450)
        root = QVBoxLayout(self); form = QFormLayout(); form.setSpacing(14); root.addLayout(form)
        self.provider = QComboBox()
        for key, info in PROVIDERS.items():
            self.provider.addItem(info['name'] + (' · API-Schlüssel' if info['key'] else ' · ohne Schlüssel'), key)
        self.symbol = QLineEdit(self.original.get('symbol', ''))
        self.currency = QLineEdit(self.original.get('currency', '')); self.currency.setPlaceholderText('EUR, USD, GBP oder GBX (Pence)')
        self.exchange = QLineEdit(self.original.get('exchange', ''))
        form.addRow('Anbieter', self.provider); form.addRow('Anbietersymbol', self.symbol)
        form.addRow('Kurswährung', self.currency); form.addRow('Handelsplatz / MIC', self.exchange)
        self.hint = QLabel(); self.hint.setWordWrap(True); root.addWidget(self.hint)
        self.provider.setCurrentIndex(max(0, self.provider.findData(self.original.get('provider', 'yahoo'))))
        self.provider.currentIndexChanged.connect(self.provider_changed)
        self.update_hint()
        note = QLabel('Wähle den tatsächlichen Handelsplatz und dessen Kurswährung. Symbole unterscheiden sich zwischen Anbietern. Bei Yahoo darf das Symbol für eine ISIN-Suche leer bleiben. Nach einem Quellenwechsel ist ein neuer Abruf nötig.')
        note.setWordWrap(True); root.addWidget(note)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText('Speichern')
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('Abbrechen')
        buttons.accepted.connect(self.save); buttons.rejected.connect(self.reject); root.addWidget(buttons)

    def update_hint(self):
        info = PROVIDERS[self.provider.currentData()]
        self.hint.setText(info['hint']); self.symbol.setPlaceholderText(info['example'])
        self.exchange.setPlaceholderText('MIC, z. B. XNAS / XETR (optional)' if self.provider.currentData() == 'twelvedata' else 'Bezeichnung (optional)')

    def provider_changed(self):
        if self.provider.currentData() == self.original.get('provider', 'yahoo'):
            self.symbol.setText(self.original.get('symbol', ''))
            self.exchange.setText(self.original.get('exchange', ''))
        else:
            self.symbol.clear(); self.exchange.clear()
        self.update_hint()

    def save(self):
        try:
            self.store.set_feed(self.position['key'], self.provider.currentData(), self.symbol.text(), self.currency.text(), self.exchange.text())
        except ValueError as exc:
            QMessageBox.warning(self, 'Kursquelle prüfen', str(exc)); return
        self.accept()
