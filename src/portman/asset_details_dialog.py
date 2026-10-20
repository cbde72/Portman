"""Sourced asset, listing, depot and transaction details with dated edits."""
from decimal import Decimal
from PySide6.QtCore import Qt, QDate
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QLineEdit,
    QPushButton, QComboBox, QDateEdit, QTabWidget, QTableWidget, QTableWidgetItem, QScrollArea,
    QWidget, QDialogButtonBox, QMessageBox)
from .asset_fields import FIELDS


def table(headers, rows):
    result = QTableWidget(len(rows), len(headers))
    result.setHorizontalHeaderLabels(headers)
    result.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    result.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    result.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
    for i, row in enumerate(rows):
        for j, value in enumerate(row):
            item = QTableWidgetItem('–' if value is None or value == '' else str(value))
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            result.setItem(i, j, item)
    result.resizeColumnsToContents()
    return result


class FactEditor(QWidget):
    def __init__(self, registry, key, scope, contexts, parent=None):
        super().__init__(parent)
        self.registry, self.key, self.scope = registry, key, scope
        layout = QVBoxLayout(self)
        self.context = QComboBox()
        for label, identifier in contexts: self.context.addItem(label, identifier)
        layout.addWidget(self.context)
        note = QLabel('Leere Felder bedeuten unbekannt. Angaben werden mit Gültigkeitsdatum und Quelle gespeichert. '
                      'Importierte Beträge bleiben erhalten; diese Ergänzungen ändern keine Buchungen oder Steuerberechnungen.')
        note.setWordWrap(True); layout.addWidget(note)
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        body = QWidget(); form = QFormLayout(body)
        self.inputs = {}
        for field, (caption, kind) in FIELDS[scope].items():
            edit = QLineEdit()
            if kind == 'date': edit.setPlaceholderText('JJJJ-MM-TT')
            if kind == 'timestamp': edit.setPlaceholderText('2026-01-01T12:00:00+01:00')
            self.inputs[field] = edit; form.addRow(caption, edit)
        self.day = QDateEdit(QDate.currentDate()); self.day.setCalendarPopup(True); self.day.setDisplayFormat('dd.MM.yyyy')
        form.addRow('Gültig ab / Belegstichtag', self.day)
        self.source = QLineEdit(); form.addRow('Quelle / Begründung', self.source)
        scroll.setWidget(body); layout.addWidget(scroll)
        self.message = QLabel(); self.message.setWordWrap(True); layout.addWidget(self.message)
        save = QPushButton('Diese Angaben speichern'); save.clicked.connect(self.save); layout.addWidget(save)
        save.setEnabled(bool(contexts))
        self.context.currentIndexChanged.connect(self.load)
        self.load()

    def load(self):
        if self.context.currentIndex() < 0: return
        data = self.registry.facts(self.key, self.scope, self.context.currentData())
        for field, edit in self.inputs.items(): edit.setText(data['values'].get(field, ''))
        self.source.setText(data['source'])
        self.day.setDate(QDate.fromString(data['valid_from'], 'yyyy-MM-dd') if data['valid_from'] else QDate.currentDate())
        self.message.clear()

    def save(self):
        try:
            self.registry.save_facts(self.key, self.scope, self.context.currentData(), self.day.date().toString('yyyy-MM-dd'),
                {field: edit.text() for field, edit in self.inputs.items()}, self.source.text())
        except ValueError as error:
            self.message.setText(str(error)); return
        self.message.setText('Dauerhaft gespeichert. Vorherige Angaben bleiben im Änderungsprotokoll nachvollziehbar.')


class AssetDetailsDialog(QDialog):
    def __init__(self, repo, key, parent=None):
        super().__init__(parent)
        self.repo, self.key, self.registry = repo, key, repo.assets
        self.registry.sync()
        self.setWindowTitle('Wertpapierdaten · Stammdaten, Depots und Belege')
        self.resize(1050, 780)
        layout = QVBoxLayout(self)
        meta = repo.metadata().get(key, {})
        title = QLabel(meta.get('canonical_name', key)); title.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(title)
        uid = QLabel('Wertpapier-UUID: ' + self.registry.identity(key)); uid.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(uid)
        self.tabs = QTabWidget(); layout.addWidget(self.tabs)
        from .asset_summary import summary_rows
        self.tabs.addTab(table(['Angabe / Berechnungsgrundlage', 'Wert'], summary_rows(repo, key)), 'Übersicht')
        self.tabs.addTab(FactEditor(self.registry, key, 'security', [('Wertpapier · alle Depots', '')]), 'Stammdaten')
        positions = [(r['depot_name'] + ' · ' + r['uuid'], r['uuid']) for r in self.registry.positions(key)]
        self.tabs.addTab(FactEditor(self.registry, key, 'position', positions), 'Depotkontext')
        self.listing_page = QWidget(); self.listing_layout = QVBoxLayout(self.listing_page)
        buttons = QHBoxLayout()
        for text, handler in [('Notierung hinzufügen', self.add_listing), ('Als Kursquelle verwenden', self.activate_listing),
                              ('FIGI / Gültigkeit bearbeiten', self.edit_listing)]:
            button = QPushButton(text); button.clicked.connect(handler); buttons.addWidget(button)
        self.listing_layout.addLayout(buttons)
        self.listing_table = None; self.refresh_listings()
        self.tabs.addTab(self.listing_page, 'Notierungen')
        self.trades = self.registry.transactions(key)
        self.trade_table = table(['Datum', 'Depot', 'Art', 'Stücke', 'Kurswert', 'Gebühren', 'Steuern',
            'Abrechnungsbetrag', 'Währung', 'Anschaffungskosten inkl. enthaltener Kosten',
            'Kosten je Stück inkl. Kosten', 'Kauftranche-UUID', 'Import-ID', 'Quelldokument-Hash', 'Quelle'],
            [[t['date'], t['depot'], t['kind'], t.get('quantity'), t.get('gross_amount'),
              t.get('fees'), t.get('taxes'), abs(Decimal(t['amount'])), t['currency'],
              t.get('acquisition_cost'), t.get('unit_cost_including_fees'),
              t['lot_uuid'], t['import_id'], t['document_hash'], t.get('source')] for t in self.trades])
        from .widgets_v09 import table_tools
        table_tools(self.trade_table)
        self.trade_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectItems)
        self.trade_table.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
        self.tabs.addTab(self.trade_table, 'Kauftranchen / Buchungen')
        contexts = [(f"{t['date']} · {t['depot']} · {t['kind']} · {t['external_id']}", t['reference']) for t in self.trades]
        self.tabs.addTab(FactEditor(self.registry, key, 'trade', contexts), 'Belegdetails / Erträge')
        tax_contexts = positions + [(label, ref) for label, ref in contexts]
        self.tabs.addTab(FactEditor(self.registry, key, 'tax', tax_contexts), 'Steuerangaben')
        self.audit_table = None
        self.audit_page = QWidget(); self.audit_layout = QVBoxLayout(self.audit_page)
        self.tabs.addTab(self.audit_page, 'Änderungsprotokoll')
        self.tabs.currentChanged.connect(self.refresh_audit)
        self.refresh_audit()
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.button(QDialogButtonBox.StandardButton.Close).setText('Schließen')
        buttons.rejected.connect(self.accept); layout.addWidget(buttons)

    def refresh_listings(self):
        self.listings = self.registry.listings(self.key)
        if self.listing_table is not None:
            self.listing_layout.removeWidget(self.listing_table); self.listing_table.deleteLater()
        self.listing_table = table(['Anbieter', 'Symbol', 'Handelsplatz', 'Kurswährung', 'FIGI', 'Quelle'],
            [[r['provider'], r['symbol'], r['exchange'], r['currency'],
              self.registry.facts(self.key, 'listing', r['uuid'])['values'].get('figi'), r['source']] for r in self.listings])
        self.listing_layout.addWidget(self.listing_table)

    def add_listing(self):
        from .online_providers import PROVIDERS
        dialog = QDialog(self); dialog.setWindowTitle('Zusätzliche Notierung')
        form = QFormLayout(dialog)
        provider = QComboBox()
        for key, info in PROVIDERS.items(): provider.addItem(info['name'], key)
        form.addRow('Anbieter', provider)
        edits = {}
        for key, label in [('symbol', 'Anbietersymbol'), ('exchange', 'Handelsplatz / MIC'), ('currency', 'Kurswährung'), ('source', 'Quelle')]:
            edits[key] = QLineEdit(); form.addRow(label, edits[key])
        message = QLabel(); form.addRow(message)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        def save():
            try:
                self.registry.add_listing(self.key, provider.currentData(), **{k: v.text() for k, v in edits.items()})
            except ValueError as error: message.setText(str(error)); return
            dialog.accept()
        buttons.accepted.connect(save); buttons.rejected.connect(dialog.reject); form.addRow(buttons)
        if dialog.exec(): self.refresh_listings()

    def activate_listing(self):
        row = self.listing_table.currentRow()
        if row < 0: return
        listing = self.listings[row]
        try:
            self.repo.market.set_feed(self.key, listing['provider'], listing['symbol'], listing['currency'], listing['exchange'])
        except ValueError as error: QMessageBox.warning(self, 'Kursquelle prüfen', str(error))

    def edit_listing(self):
        row = self.listing_table.currentRow()
        if row < 0: return
        listing = self.listings[row]
        dialog = QDialog(self); dialog.setWindowTitle('Notierung ergänzen'); dialog.resize(650, 500)
        layout = QVBoxLayout(dialog)
        layout.addWidget(FactEditor(self.registry, self.key, 'listing', [(listing['symbol'], listing['uuid'])]))
        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close); close.rejected.connect(dialog.accept); layout.addWidget(close)
        close.button(QDialogButtonBox.StandardButton.Close).setText('Schließen')
        dialog.exec(); self.refresh_listings()

    def refresh_audit(self, *args):
        if self.audit_table is not None:
            self.audit_layout.removeWidget(self.audit_table); self.audit_table.deleteLater()
        self.audit_table = table(['Zeitpunkt', 'Bereich', 'Kontext', 'Gültig ab', 'Vorher', 'Nachher', 'Quelle / Begründung'],
            [[r['changed_at'], r['scope'], r['context'], r['valid_from'], r['old_payload'], r['new_payload'], r['source']]
            for r in self.registry.audit(self.key)])
        self.audit_layout.addWidget(self.audit_table)
