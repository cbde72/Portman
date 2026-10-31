"""Catalog-driven field editors, help and PDF selection mapping dialog."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import re

from PySide6.QtCore import Qt, QRegularExpression
from PySide6.QtGui import QKeySequence, QRegularExpressionValidator, QShortcut
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout,
    QLabel, QLineEdit, QMessageBox, QPushButton, QTextEdit, QVBoxLayout, QWidget,
)

from portman_pdf_lab.field_catalog import CatalogStore, FieldCatalog, FieldDefinition


class EditorFactory:
    PATTERNS = {
        "ISIN": r"[A-Za-z]{2}[A-Za-z0-9]{9}[0-9]",
        "WKN": r"[A-Za-z0-9]{6}",
        "IBAN": r"[A-Za-z]{2}[0-9A-Za-z ]{13,34}",
        "DECIMAL": r"[+-]?(?:[0-9]{1,3}(?:[. ][0-9]{3})*|[0-9]+)(?:[,\.][0-9]+)?",
        "AMOUNT": r"[+-]?(?:[0-9]{1,3}(?:[. ][0-9]{3})*|[0-9]+)(?:[,\.][0-9]+)?",
        "DATE": r"(?:[0-3]?[0-9][.\-/][01]?[0-9][.\-/][0-9]{2,4}|[0-9]{4}-[01][0-9]-[0-3][0-9])",
    }

    @classmethod
    def create(cls, definition: FieldDefinition, value=""):
        if definition.editor == "MULTILINE":
            widget = QTextEdit(); widget.setPlainText(str(value)); return widget
        if definition.editor == "VENUE":
            widget = QComboBox(); widget.setEditable(True); widget.addItems(("", "XETRA", "Tradegate", "Frankfurt", "gettex")); widget.setCurrentText(str(value)); return widget
        if definition.editor == "STATUS":
            widget = QComboBox(); widget.addItems(("UNREVIEWED", "CONFIRMED", "MISSING", "NOT_APPLICABLE")); widget.setCurrentText(str(value)); return widget
        widget = QLineEdit(str(value))
        pattern = cls.PATTERNS.get(definition.editor) or definition.validation
        if pattern:
            widget.setValidator(QRegularExpressionValidator(QRegularExpression(pattern), widget))
        return widget

    @staticmethod
    def text(widget):
        if isinstance(widget, QTextEdit): return widget.toPlainText()
        if isinstance(widget, QComboBox): return widget.currentText()
        return widget.text()

    @staticmethod
    def normalize(value: str, definition: FieldDefinition, normalizer: str):
        original = value
        if normalizer in {"DECIMAL_DE", "DECIMAL_EN"}:
            candidate = value.strip().replace(" ", "")
            if normalizer == "DECIMAL_DE": candidate = candidate.replace(".", "").replace(",", ".")
            try: return original, format(Decimal(candidate), "f")
            except InvalidOperation: raise ValueError("Ungültiger Dezimalwert")
        if normalizer == "UPPER" or definition.data_type in {"ISIN", "WKN", "IBAN"}:
            return original, value.replace(" ", "").upper()
        return original, value


def catalog_help_html(catalog: FieldCatalog) -> str:
    groups = (("REQUIRED", "Unbedingt erforderliche Werte"), ("CONDITIONAL", "Bedingt erforderliche Werte"),
              ("OPTIONAL", "Optionale Werte"), ("TECHNICAL", "Technische und Qualitätswerte"))
    parts = [f"<h1>Feldhilfe – {catalog.document_type}</h1>"]
    for requirement, title in groups:
        parts.append(f"<h2>{title}</h2>")
        for field in catalog.visible_fields():
            if field.requirement == requirement:
                source = "PDF-Evidence erforderlich" if field.evidence_required else "technisch erzeugt"
                parts.append(f"<h3>{field.label}</h3><p><code>{field.path}</code><br>{field.description}<br>"
                             f"Typ: {field.data_type}; Validierung: {field.validation or 'keine'}; Quelle: {source}; "
                             f"Fehlend: {field.missing_behavior}</p>")
    return "".join(parts)


class CatalogHelpDialog(QDialog):
    def __init__(self, catalog, parent=None):
        super().__init__(parent); self.setWindowTitle("Feldhilfe"); self.resize(760, 620)
        layout = QVBoxLayout(self); text = QTextEdit(); text.setReadOnly(True); text.setHtml(catalog_help_html(catalog)); layout.addWidget(text)
        close = QDialogButtonBox(QDialogButtonBox.Close); close.rejected.connect(self.reject); layout.addWidget(close)


@dataclass(frozen=True)
class MappingResult:
    field: FieldDefinition
    selected_text: str
    original_value: str
    normalized_value: str
    normalizer: str
    page_number: int
    coordinates: object = None


class FieldMappingDialog(QDialog):
    def __init__(self, catalog: FieldCatalog, catalog_store: CatalogStore, context: dict,
                 selected_text: str, page_number: int, coordinates=None, define_new=False, parent=None):
        super().__init__(parent); self.catalog = catalog; self.catalog_store = catalog_store; self.context = context
        self.selected_text, self.page_number, self.coordinates = selected_text, page_number, coordinates
        self.mapping_result = None; self.setWindowTitle("PDF-Text einem Feld zuordnen"); self.resize(720, 620)
        layout = QVBoxLayout(self); form = QFormLayout()
        for label, value in (("Bank", context.get("bank", "")), ("Parser-ID", context.get("parser_id", "")),
                             ("Dokumenttyp", context.get("document_type", "")), ("PDF-Seite", page_number),
                             ("Originaltext", context.get("original_text", "")), ("Ausgewählter Text", selected_text),
                             ("Regelmodus", context.get("rule_mode", "STANDARD"))):
            field = QLineEdit(str(value)); field.setReadOnly(True); form.addRow(label, field)
        self.field_choice = QComboBox()
        for field in catalog.visible_fields(): self.field_choice.addItem(f"{field.label} — {field.path}", field.field_id)
        self.field_choice.currentIndexChanged.connect(self._field_changed); form.addRow("Zielfeld", self.field_choice)
        self.new_field = QCheckBox("Neues optionales Erweiterungsfeld")
        self.new_field.setChecked(define_new); self.new_field.toggled.connect(self._new_toggled); form.addRow(self.new_field)
        self.new_id = QLineEdit(); self.new_id.setPlaceholderText("z. B. trade.venue_detail"); form.addRow("Neue Feld-ID", self.new_id)
        self.new_label = QLineEdit(); form.addRow("Anzeigename", self.new_label)
        self.type_label = QLabel(); self.requirement_label = QLabel(); form.addRow("Datentyp", self.type_label); form.addRow("Pflichtstatus", self.requirement_label)
        self.editor_host = QWidget(); self.editor_layout = QHBoxLayout(self.editor_host); self.editor_layout.setContentsMargins(0, 0, 0, 0); form.addRow("Wert", self.editor_host)
        self.normalizer = QComboBox(); form.addRow("Normalisierung", self.normalizer)
        self.evidence = QLineEdit(f"Seite {page_number}: {selected_text}"); self.evidence.setReadOnly(True); form.addRow("Evidence", self.evidence)
        help_button = QPushButton("Feldhilfe (F1)"); help_button.clicked.connect(self.show_help); form.addRow(help_button)
        layout.addLayout(form); buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._accept); buttons.rejected.connect(self.reject); layout.addWidget(buttons)
        self.help_shortcut = QShortcut(QKeySequence.HelpContents, self); self.help_shortcut.activated.connect(self.show_help)
        self._new_toggled(define_new); self._field_changed()

    def current_definition(self):
        return self.catalog.field(self.field_choice.currentData())

    def _clear_editor(self):
        while self.editor_layout.count():
            item = self.editor_layout.takeAt(0)
            if item.widget(): item.widget().deleteLater()

    def _field_changed(self):
        definition = self.current_definition()
        if not definition: return
        self.type_label.setText(definition.data_type); self.requirement_label.setText(definition.requirement)
        self.normalizer.clear(); self.normalizer.addItems(definition.normalizers)
        self._clear_editor(); self.value_editor = EditorFactory.create(definition, self.selected_text); self.editor_layout.addWidget(self.value_editor)

    def _new_toggled(self, enabled):
        self.field_choice.setEnabled(not enabled); self.new_id.setEnabled(enabled); self.new_label.setEnabled(enabled)
        if enabled:
            self.type_label.setText("TEXT"); self.requirement_label.setText("OPTIONAL")
            self.normalizer.clear(); self.normalizer.addItem("TEXT")
            self._clear_editor(); self.value_editor = QLineEdit(self.selected_text); self.editor_layout.addWidget(self.value_editor)
        else:
            self._field_changed()

    def _accept(self):
        try:
            definition = self.current_definition()
            if self.new_field.isChecked():
                self.catalog, definition = self.catalog_store.add_optional_field(self.catalog, self.new_id.text(), self.new_label.text())
            if not definition: raise ValueError("Zielfeld fehlt")
            value = EditorFactory.text(self.value_editor)
            original, normalized = EditorFactory.normalize(value, definition, self.normalizer.currentText())
            if definition.validation and not re.fullmatch(definition.validation, normalized): raise ValueError("Wert entspricht nicht der Feldvalidierung")
            self.mapping_result = MappingResult(definition, self.selected_text, original, normalized,
                                                self.normalizer.currentText(), self.page_number, self.coordinates)
            self.accept()
        except ValueError as exc:
            QMessageBox.warning(self, "Feldzuordnung", str(exc))

    def show_help(self):
        CatalogHelpDialog(self.catalog, self).exec()
