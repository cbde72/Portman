"""Guided, non-modal quick-training panel backed by the existing workflow."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QScrollArea, QVBoxLayout, QWidget,
)

from .field_mapping import EditorFactory
from portman_pdf_lab.field_descriptions import resolve_description


STEPS = ("Feld auswählen", "PDF markieren", "Bestätigen", "Regel prüfen", "Freigeben", "Aktivieren")


class QuickTrainingPanel(QScrollArea):
    confirmRequested = Signal(object, str)
    missingRequested = Signal()
    cancelRequested = Signal()
    testRequested = Signal()
    approveRequested = Signal()
    activateRequested = Signal()
    recheckRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent); self.setWidgetResizable(True); self.setMinimumWidth(300)
        self.context = None; self.definition = None; self.selection = None; self.step = 0; self.active = False
        body = QWidget(); self.setWidget(body); layout = QVBoxLayout(body)
        self.progress = QLabel(); self.progress.setWordWrap(True); layout.addWidget(self.progress)
        group = QGroupBox("Schnelltraining"); form = QFormLayout(group)
        self.field = QLabel("—"); self.description = QLabel("—"); self.description.setWordWrap(True)
        self.old_value = QLabel("—"); self.pdf_text = QLabel("Noch nichts markiert")
        self.pdf_text.setWordWrap(True); self.reference_host = QWidget(); self.reference_layout = QHBoxLayout(self.reference_host)
        self.reference_layout.setContentsMargins(0, 0, 0, 0); self.editor = QLineEdit()
        self.reference_layout.addWidget(self.editor)
        self.current_step = QLabel("Feld auswählen"); self.next_action = QLabel("Feld in der Analyse auswählen")
        self.next_action.setWordWrap(True)
        for label, widget in (("Ausgewähltes Feld", self.field), ("Beschreibung", self.description),
                              ("Bisheriger Parserwert", self.old_value),
                              ("Markierter PDF-Text", self.pdf_text), ("Neuer Referenzwert", self.reference_host),
                              ("Aktueller Schritt", self.current_step), ("Nächste Aktion", self.next_action)):
            form.addRow(label, widget)
        layout.addWidget(group)
        confirm_row = QHBoxLayout(); self.confirm = QPushButton("Bestätigen"); self.missing = QPushButton("Im PDF nicht vorhanden")
        self.cancel = QPushButton("Abbrechen")
        for button in (self.confirm, self.missing, self.cancel): confirm_row.addWidget(button)
        layout.addLayout(confirm_row)
        rule_row = QHBoxLayout(); self.test = QPushButton("Regel prüfen"); self.approve = QPushButton("Regel freigeben")
        self.activate = QPushButton("Profil aktivieren"); self.recheck = QPushButton("Erneut prüfen")
        for button in (self.test, self.approve, self.activate, self.recheck): rule_row.addWidget(button)
        layout.addLayout(rule_row); self.result = QLabel(); self.result.setWordWrap(True); layout.addWidget(self.result); layout.addStretch()
        self.confirm.clicked.connect(self._confirm); self.missing.clicked.connect(self.missingRequested)
        self.cancel.clicked.connect(self.cancelRequested); self.test.clicked.connect(self.testRequested)
        self.approve.clicked.connect(self.approveRequested); self.activate.clicked.connect(self.activateRequested)
        self.recheck.clicked.connect(self.recheckRequested); self.reset()

    def _set_editor(self, definition, value=""):
        while self.reference_layout.count():
            item = self.reference_layout.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        self.editor = EditorFactory.create(definition, value); self.reference_layout.addWidget(self.editor)

    def begin(self, context, definition, existing=None, catalog=None):
        self.context, self.definition, self.selection, self.active = context, definition, None, True
        self.field.setText(context.field_name); self.old_value.setText(str(context.current_value if context.current_value is not None else "—"))
        self.description.setText(resolve_description(context.field_path, catalog).description)
        initial = (existing or {}).get("reference_value") if existing else context.reference_value
        self._set_editor(definition, "" if initial is None else str(initial))
        self.pdf_text.setText("Noch nichts markiert"); self.result.setText("")
        self.set_step(1, "Passenden Wert mit der linken Maustaste direkt im PDF markieren.")

    def set_selection(self, selection):
        self.selection = selection; self.pdf_text.setText(selection.text)
        self._set_editor(self.definition, selection.text)
        self.set_step(2, "Referenzwert kontrollieren und bestätigen oder bearbeiten.")

    def _confirm(self):
        if self.selection is not None:
            self.confirmRequested.emit(self.selection, EditorFactory.text(self.editor))

    def set_step(self, step, next_action):
        self.step = step; self.current_step.setText(STEPS[min(step, len(STEPS) - 1)]); self.next_action.setText(next_action)
        self.progress.setText(" → ".join((f"● {name}" if index == step else f"○ {name}") for index, name in enumerate(STEPS)))
        self.confirm.setEnabled(step == 2); self.missing.setEnabled(step in {1, 2})
        self.test.setEnabled(step >= 3); self.approve.setEnabled(step >= 4); self.activate.setEnabled(step >= 5)
        self.recheck.setEnabled(step >= 5)

    def candidate_created(self, candidate_id):
        if candidate_id:
            self.result.setText("Regelkandidat gespeichert. Weitere Beispiele können für eine sichere Generalisierung erforderlich sein.")
            self.set_step(3, "Regel gegen Golden- und Regressionstests prüfen.")
        else:
            self.result.setText("Kein sicherer Regelvorschlag möglich. Bitte weitere Textauswahl oder ein weiteres Beispieldokument hinzufügen.")

    def tested(self, message, passed):
        self.result.setText(message); self.set_step(4 if passed else 3, "Regel ausdrücklich freigeben." if passed else "Konflikte beheben oder weiteres Beispiel hinzufügen.")

    def approved(self):
        self.result.setText("Regel freigegeben, aber noch nicht aktiviert."); self.set_step(5, "Freigegebenes Profil separat aktivieren.")

    def activated(self):
        self.result.setText("Profil aktiviert. EXTENDED kann nun erneut ausgeführt werden."); self.set_step(5, "Mit „Erneut prüfen“ die EXTENDED-Auswertung aktualisieren.")
        self.recheck.setEnabled(True)

    def rechecked(self, standard, extended, reference, status):
        self.result.setText(f"Ursprünglich: {standard}\nEXTENDED: {extended}\nReferenz: {reference}\nStatus: {status}")

    def reset(self):
        self.context = self.definition = self.selection = None; self.active = False
        self.field.setText("—"); self.description.setText("—"); self.old_value.setText("—"); self.pdf_text.setText("Noch nichts markiert")
        self.result.setText(""); self.set_step(0, "Feld in der Analyse auswählen")
