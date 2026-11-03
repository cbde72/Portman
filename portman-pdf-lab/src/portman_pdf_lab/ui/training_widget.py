"""Compact four-area local parser-training UI."""

from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction, QColor, QKeySequence
from PySide6.QtWidgets import (
    QApplication, QAbstractItemView, QComboBox, QFileDialog, QFormLayout, QGridLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QMenu, QMessageBox, QPushButton, QSplitter, QTableWidget, QTableWidgetItem,
    QTextEdit, QVBoxLayout, QWidget,
)

from portman_pdf_lab.storage import ReferenceRepository
from portman_pdf_lab.field_descriptions import resolve_description
from portman_pdf_lab.training import AnnotationKind, Decision, TrainingContext, TrainingService
from portman_pdf_lab.ui.result_view import (
    DisplayRow, RecognitionStatus, _is_missing, enrich_rows, flatten_result, scalar_text,
)


def _flatten(value, prefix=""):
    if isinstance(value, dict):
        for key in sorted(value):
            yield from _flatten(value[key], f"{prefix}.{key}" if prefix else key)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _flatten(item, f"{prefix}[{index}]")
    else:
        yield prefix, value


def _selection_value(text: str) -> str:
    """Normalize a direct PDF selection into a candidate field value.

    Users often select the whole printed line (``Handelsplatz: XETRA``).  The
    value after a short label is the actual field content; line breaks and the
    label itself are kept in the annotation's original PDF text, not in the
    normalized reference value.
    """
    clean = str(text or "").replace("\u2029", "\n").replace("\r\n", "\n").strip()
    if clean and "\n" not in clean and ":" in clean:
        label, _, value = clean.partition(":")
        if 0 < len(label.strip()) <= 48 and value.strip():
            return value.strip()
    return clean


def _annotation_kind(data_type: str, fallback="TEXT") -> str:
    return {"DECIMAL": "AMOUNT", "AMOUNT": "AMOUNT", "DATE": "DATE",
            "ISIN": "SECURITY_ID", "WKN": "SECURITY_ID", "QUANTITY": "QUANTITY",
            "PRICE": "PRICE", "MARKET_VALUE": "MARKET_VALUE", "MULTILINE": "MULTILINE"}.get(
                str(data_type or "").upper(), fallback)


class CopyableTable(QTableWidget):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setSelectionBehavior(QAbstractItemView.SelectItems)
        self.setSortingEnabled(True)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)

    def copy_selection(self):
        indexes = sorted(self.selectedIndexes(), key=lambda item: (item.row(), item.column()))
        if indexes:
            rows = {}
            for index in indexes: rows.setdefault(index.row(), {})[index.column()] = index.data() if index.data() is not None else ""
            columns = sorted({column for values in rows.values() for column in values})
            QApplication.clipboard().setText("\n".join("\t".join(str(values.get(column, "")) for column in columns) for values in rows.values()))

    def keyPressEvent(self, event):
        if event.matches(QKeySequence.SelectAll):
            self.selectAll(); return
        if event.matches(QKeySequence.Copy):
            self.copy_selection(); return
        super().keyPressEvent(event)

    def _menu(self, position):
        menu = QMenu(self); action = QAction("Kopieren", self); action.triggered.connect(self.copy_selection)
        menu.addAction(action); menu.exec(self.viewport().mapToGlobal(position))


class TrainingWidget(QWidget):
    fieldActivated = Signal(object)
    trainingChanged = Signal(object)
    selectionCaptured = Signal(object)
    returnRequested = Signal()

    def __init__(self, repository_path, parent=None):
        super().__init__(parent)
        self.repository_path = repository_path
        self.report = None
        self.document_path = None
        self.annotation_id = None
        self.candidate_id = None
        self.version_id = None
        self.settings = None
        self.context: TrainingContext | None = None
        self.pending_selection = None
        self._binding = False
        self._applying_context = False
        self._display_rows: list[DisplayRow] = []
        self._build()

    def repository(self):
        return ReferenceRepository(self.repository_path)

    def _build(self):
        layout = QVBoxLayout(self)
        split = self.main_splitter = QSplitter(Qt.Vertical); split.setObjectName("training-main-splitter")
        upper = self.upper_splitter = QSplitter(Qt.Horizontal); upper.setObjectName("training-upper-splitter")
        lower = self.lower_splitter = QSplitter(Qt.Horizontal); lower.setObjectName("training-lower-splitter")

        documents = QGroupBox("A. Dokumentliste und Filter")
        documents_layout = QVBoxLayout(documents)
        filters = QHBoxLayout()
        self.bank_filter = QLineEdit(); self.bank_filter.setPlaceholderText("Bank")
        self.type_filter = QLineEdit(); self.type_filter.setPlaceholderText("Dokumenttyp")
        self.from_filter = QLineEdit(); self.from_filter.setPlaceholderText("Zeitraum von")
        self.to_filter = QLineEdit(); self.to_filter.setPlaceholderText("Zeitraum bis")
        self.status_filter = QComboBox(); self.status_filter.addItems(("Alle", "NOT_REVIEWED", "APPROVED", "NEEDS_CORRECTION"))
        filters.addWidget(self.bank_filter); filters.addWidget(self.type_filter); filters.addWidget(self.status_filter); filters.addWidget(self.from_filter); filters.addWidget(self.to_filter)
        self.documents = CopyableTable(0, 9)
        self.documents.setHorizontalHeaderLabels(("Bank", "Datei", "Dokumenttyp", "Parser", "Handler", "Layout", "Review", "Training", "Fehler"))
        documents_layout.addLayout(filters); documents_layout.addWidget(self.documents)

        source = QGroupBox("B. Original-PDF / Textannotation")
        source_layout = QVBoxLayout(source)
        self.page_label = QLabel("Seite 1 – Textauszug, solange keine Bounding Boxes vorliegen")
        self.source_text = QTextEdit(); self.source_text.setPlaceholderText("PDF-Text oder Evidence-Auszug markieren")
        source_layout.addWidget(self.page_label); source_layout.addWidget(self.source_text)

        fields = QGroupBox("C. Extrahierte Felder und Referenzwerte")
        fields_layout = QVBoxLayout(fields)
        field_bar = QHBoxLayout(); self.field_filter = QComboBox()
        self.field_filter.addItems(("Alle Felder", "Nur erkannte", "Nur fehlende", "Nur zu prüfende"))
        self.field_stats = QLabel("Erkannt 0 · Fehlend 0 · Prüfen 0 · N/A 0")
        field_bar.addWidget(self.field_filter); field_bar.addWidget(self.field_stats); field_bar.addStretch()
        self.fields = CopyableTable(0, 10)
        self.fields.setHorizontalHeaderLabels(("Feldpfad", "Beschreibung", "STANDARD", "EXTENDED", "Referenzwert", "Einheit/Währung", "Quelle", "Fundstelle", "Status", "Regel-ID"))
        self.fields.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed | QAbstractItemView.SelectedClicked)
        self.fields.itemSelectionChanged.connect(self._select_field)
        self.fields.itemChanged.connect(self._field_item_changed)
        fields_layout.addLayout(field_bar); fields_layout.addWidget(self.fields)

        controls = QGroupBox("D. Trainingssteuerung")
        form = QFormLayout(controls)
        self.context_label = QLabel("Kein Feld aus der Feldanalyse ausgewählt")
        self.context_label.setWordWrap(True)
        self.field_path = QLineEdit(); self.reference_value = QLineEdit()
        self.parser = QComboBox(); self.parser.addItems(("user.comdirect-ertraege", "portfolio-performance.comdirect"))
        self.mode = QComboBox(); self.mode.addItems(("STANDARD", "EXTENDED", "COMPARE"))
        self.kind = QComboBox(); self.kind.addItems([item.value for item in AnnotationKind])
        self.result = QTextEdit(); self.result.setReadOnly(True); self.result.setMaximumHeight(150)
        form.addRow("Kontext", self.context_label)
        form.addRow("Parser", self.parser); form.addRow("Regelmodus", self.mode)
        form.addRow("Feldpfad", self.field_path); form.addRow("Referenzwert", self.reference_value); form.addRow("Annotation", self.kind)
        actions = QGridLayout()
        for index, (label, method) in enumerate((
                ("Feld bestätigen", self.confirm_field), ("Feld korrigieren", self.correct_field),
                ("Fehlendes Feld ergänzen", self.add_missing), ("Als unbekannt", self.unknown_field),
                ("PDF-Text zuordnen", self.map_text),
                ("Auswahl übernehmen", self.assign_selection), ("Fehlen bestätigen", self.confirm_absence),
                ("Nicht anwendbar", self.not_applicable), ("Annotation bearbeiten", self.edit_annotation),
                ("Annotation löschen", self.delete_annotation), ("Referenzfall speichern", self.save_golden),
                ("Regelvorschlag", self.suggest_rule), ("Vorschlag testen", self.test_rule),
                ("Vorschlag freigeben", self.approve_rule), ("Vorschlag verwerfen", self.reject_rule),
                ("Vorherige Version", self.rollback), ("Profil aktivieren", self.activate_profile),
                ("Profil deaktivieren", self.deactivate_profile), ("Profil exportieren", self.export_profile),
                ("Profil importieren", self.import_profile), ("Qualität", self.show_quality),
                ("Zur Feldanalyse", self.return_to_analysis))):
            button = QPushButton(label); button.clicked.connect(method); actions.addWidget(button, index // 3, index % 3)
        form.addRow(actions); form.addRow("Test/Vergleich", self.result)

        upper.addWidget(documents); upper.addWidget(source); lower.addWidget(fields); lower.addWidget(controls)
        upper.setChildrenCollapsible(False); lower.setChildrenCollapsible(False); split.setChildrenCollapsible(False)
        upper.setStretchFactor(0, 1); upper.setStretchFactor(1, 1); lower.setStretchFactor(0, 2); lower.setStretchFactor(1, 1)
        split.addWidget(upper); split.addWidget(lower); layout.addWidget(split)
        self.bank_filter.textChanged.connect(self._apply_filters); self.type_filter.textChanged.connect(self._apply_filters)
        self.status_filter.currentTextChanged.connect(self._apply_filters)
        self.field_filter.currentTextChanged.connect(self._apply_field_filter)

    def save_settings(self, settings):
        settings.setValue("splitters/training-main", self.main_splitter.saveState())
        settings.setValue("splitters/training-upper", self.upper_splitter.saveState())
        settings.setValue("splitters/training-lower", self.lower_splitter.saveState())
        settings.setValue("headers/training-documents", self.documents.horizontalHeader().saveState())
        settings.setValue("headers/training-fields", self.fields.horizontalHeader().saveState())

    def restore_settings(self, settings):
        self.settings = settings
        for key, splitter in (("training-main", self.main_splitter), ("training-upper", self.upper_splitter), ("training-lower", self.lower_splitter)):
            state = settings.value(f"splitters/{key}")
            if state: splitter.restoreState(state)
        for key, table in (("training-documents", self.documents), ("training-fields", self.fields)):
            state = settings.value(f"headers/{key}")
            if state: table.horizontalHeader().restoreState(state)

    @staticmethod
    def _cell_text(table, row, column):
        item = table.item(row, column) if table is not None else None
        return item.text() if item is not None else ""

    def bind_report(self, report, document_path=None, catalog=None):
        self._binding = True
        try:
            if not self._applying_context:
                # A new document invalidates any handoff from the previous one.
                self.context = None
                self.pending_selection = None
            self.fields.setSortingEnabled(False)
            previous_path = self.field_path.text()
            self.report = report; self.document_path = document_path
            result = report.get("result", {}); detection = report.get("detection", {})
            self.documents.setRowCount(1)
            values = (detection.get("plugin_id", "").split(".")[0], str(document_path or report.get("source", "")),
                      detection.get("document_type", ""), result.get("plugin_id", ""), result.get("handler_id", ""),
                      result.get("attributes", {}).get("layout_path", "unknown"), "NOT_REVIEWED", "OPEN", len(report.get("issues", [])))
            for column, value in enumerate(values): self.documents.setItem(0, column, QTableWidgetItem(str(value)))
            evidence = {item.get("evidence_id"): item for item in result.get("evidence", [])}
            rows = flatten_result(result, evidence)
            if catalog:
                rows = enrich_rows(rows, catalog, result)

            comparison = {}
            for item in report.get("rule_comparison", []) or []:
                path = item.get("field") or item.get("field_path")
                if path: comparison[path] = item
            for item in report.get("rule_decisions", []) or []:
                path = item.get("field_path")
                if path:
                    comparison.setdefault(path, {"field": path, "standard": item.get("standard_value"),
                                                 "extended": item.get("effective_value"),
                                                 "conflict": item.get("conflict"), "rule_id": item.get("rule_id")})

            colors = {RecognitionStatus.RECOGNIZED: QColor("#2e7d32"), RecognitionStatus.MISSING: QColor("#c62828"),
                      RecognitionStatus.REVIEW: QColor("#b26a00"), RecognitionStatus.NOT_APPLICABLE: QColor("#707070")}
            self._display_rows = []
            self.fields.clearContents()
            self.fields.setRowCount(len(rows))
            for row, display in enumerate(rows):
                decision = comparison.get(display.path) or {}
                standard = "null" if display.value is None else scalar_text(display.value)
                extended = standard
                if "extended" in decision and not _is_missing(decision.get("extended")):
                    extended = scalar_text(decision.get("extended"))
                elif "standard" in decision and not _is_missing(decision.get("standard")):
                    extended = scalar_text(decision.get("standard"))
                rule_id = str(decision.get("rule_id") or "")
                status = RecognitionStatus.REVIEW if decision.get("conflict") else display.status
                display = DisplayRow(display.path, display.name, display.value, display.unit, status,
                                     display.source, display.page, display.evidence, display.data_type,
                                     display.requirement)
                self._display_rows.append(display)
                cells = (display.path, resolve_description(display.path, catalog).description,
                         standard, extended, "", display.unit, display.source, display.page,
                         status.value, rule_id)
                for column, cell in enumerate(cells):
                    item = QTableWidgetItem(str(cell)); item.setToolTip(str(cell))
                    background = QColor(colors[status]); background.setAlpha(42); item.setBackground(background)
                    if column == 8:
                        item.setForeground(colors[status]); item.setData(Qt.UserRole + 1, status.value)
                    if column == 0:
                        item.setData(Qt.UserRole, display)
                    if column != 4:
                        item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                    self.fields.setItem(row, column, item)

            counts = {status: sum(item.status == status for item in self._display_rows) for status in RecognitionStatus}
            self.field_stats.setText(f"Erkannt {counts[RecognitionStatus.RECOGNIZED]} · Fehlend {counts[RecognitionStatus.MISSING]} · "
                                     f"Prüfen {counts[RecognitionStatus.REVIEW]} · N/A {counts[RecognitionStatus.NOT_APPLICABLE]}")
            self.source_text.setPlainText("\n\n".join(item.get("excerpt", "") for item in evidence.values()))
        finally:
            self.fields.setSortingEnabled(True)
            self._binding = False
        self._apply_filters(); self._apply_field_filter()
        if previous_path:
            self.select_field_path(previous_path)

    def apply_training_context(self, context: TrainingContext | None, catalog=None, document_path=None):
        """Select a field analysis row inside the existing training workflow.

        Bank, parser, handler, document type, field path, current value,
        evidence and the annotation/candidate state all arrive in one immutable
        context.  No second training database or parallel rule engine is used.
        """
        if context is None:
            return
        self._applying_context = True
        try:
            self.context = context
            report = getattr(context, "report", None) or self.report
            if report:
                self.bind_report(report, document_path or self.document_path or context.document_id, catalog)
            if context.parser_id:
                index = self.parser.findText(context.parser_id)
                if index < 0:
                    self.parser.addItem(context.parser_id)
                    index = self.parser.count() - 1
                self.parser.setCurrentIndex(index)
            if context.rule_mode in {self.mode.itemText(i) for i in range(self.mode.count())}:
                self.mode.setCurrentText(context.rule_mode)
            self.field_path.setText(context.field_path)
            self.kind.setCurrentText(_annotation_kind(context.data_type, self.kind.currentText()))
            evidence = context.evidence if isinstance(context.evidence, dict) else {}
            original = context.original_text or str(evidence.get("excerpt") or "")
            self.source_text.setPlainText(original)
            page = int(context.page_number or 0)
            self.page_label.setText(
                f"Seite {page} – Trainingskontext aus Feldanalyse" if page
                else "Seite 1 – Trainingskontext aus Feldanalyse")
            self.annotation_id = context.annotation_id
            self.candidate_id = context.candidate_id
            self.context_label.setText(
                f"{context.field_name or context.field_path} · "
                f"{context.requirement or 'Pflichtstatus unbekannt'} · {context.training_status}")
            # Select first because _select_field() derives its own default from
            # the training table; the explicit reference/annotation from the
            # field analysis must win afterwards.
            self.select_field_path(context.field_path)
            self.field_path.setText(context.field_path)
            value = context.reference_value
            if _is_missing(value):
                value = context.current_value
            self.reference_value.setText("" if _is_missing(value) else scalar_text(value))
            self.result.setPlainText(
                f"Feldanalyse-Kontext: {context.field_path} "
                f"(Parser {context.parser_id or '—'}, Seite {page or '—'})")
        finally:
            self._applying_context = False

    def apply_pdf_selection(self, selection):
        """Keep a direct PDF selection ready for the preselected field."""
        if selection is None:
            return
        self.pending_selection = selection
        text = str(getattr(selection, "text", "") or "")
        page = int(getattr(selection, "page_number", 0) or 0)
        self.source_text.setPlainText(text)
        if page:
            self.page_label.setText(f"Seite {page} – PDF-Auswahl für {self.field_path.text() or 'Feld'}")
        if self.context is not None:
            self.context = self.context.with_selection(selection)
        # A direct selection is the strongest source for the reference value:
        # the user confirms it with one click, so a stale parser value must not
        # silently survive in the editable field.
        if text:
            self.reference_value.setText(_selection_value(text))
        self.result.setPlainText(
            f"PDF-Auswahl übernommen: Seite {page or '—'}, {len(text)} Zeichen. "
            "Mit „Auswahl übernehmen“ direkt dem Feld zuordnen.")
        self.selectionCaptured.emit(selection)

    def _announce(self, kind: str):
        payload = {"kind": kind, "field_path": self.field_path.text(),
                   "annotation_id": self.annotation_id, "candidate_id": self.candidate_id,
                   "version_id": self.version_id, "context": self.context}
        self.trainingChanged.emit(payload)

    def _current_values(self):
        run = self.repository().run(self.report["run_id"])
        context = self.context
        parser_id = context.parser_id if context and context.parser_id else run["plugin_id"]
        handler_id = context.handler_id if context and context.handler_id else run["handler_id"]
        return run, parser_id, handler_id

    def _reference_input(self):
        raw = self.reference_value.text()
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return raw

    def _store(self, decision: Decision):
        if not self.report or not self.report.get("run_id"):
            raise ValueError("first analyze and store a PDF")
        run, parser_id, handler_id = self._current_values()
        context = self.context
        reference_value = self._reference_input()
        kind = _annotation_kind(context.data_type if context else "", self.kind.currentText())
        page = int(context.page_number or 0) if context else 0
        original_text = (context.original_text if context and context.original_text else self._selection())
        coordinates = context.coordinates if context else None
        if decision in {Decision.MISSING, Decision.NOT_APPLICABLE}:
            kind = "MISSING" if decision == Decision.MISSING else "NOT_APPLICABLE"
            reference_value = None
            original_text = original_text if decision == Decision.MISSING else ""
        review = "APPROVED" if decision in {Decision.CONFIRMED, Decision.CORRECTED} else "IN_REVIEW"
        if self.annotation_id:
            self.repository().update_annotation(self.annotation_id, reference_value, decision.value,
                                                review, "GUI user", "GUI training update")
            message = f"Annotation {self.annotation_id} aktualisiert"
        else:
            self.annotation_id = self.repository().create_annotation(
                run["document_id"], parser_id, handler_id, max(1, page), original_text,
                self.field_path.text(), reference_value, kind, decision.value, review,
                "GUI user", coordinates)
            message = f"Annotation {self.annotation_id} gespeichert"
        self.result.setPlainText(message)
        self._announce("annotation")

    def assign_selection(self):
        def action():
            if self.pending_selection is None:
                raise ValueError("Bitte zuerst Text im PDF markieren")
            if not self.field_path.text().strip():
                raise ValueError("Bitte zuerst ein Zielfeld auswählen")
            self._store(Decision.CONFIRMED)
        self._guard(action)

    def confirm_absence(self):
        self._guard(lambda: self._store(Decision.MISSING))

    def not_applicable(self):
        self._guard(lambda: self._store(Decision.NOT_APPLICABLE))

    def edit_annotation(self):
        def action():
            if not self.annotation_id:
                raise ValueError("Keine Annotation ausgewählt")
            self.repository().update_annotation(self.annotation_id, self._reference_input(),
                                                Decision.CORRECTED.value, "APPROVED", "GUI user",
                                                "Edited in training")
            self.result.setPlainText(f"Annotation {self.annotation_id} bearbeitet")
            self._announce("annotation")
        self._guard(action)

    def delete_annotation(self):
        def action():
            if not self.annotation_id:
                raise ValueError("Keine Annotation ausgewählt")
            self.repository().deactivate_annotation(self.annotation_id, "GUI user", "Deleted in training")
            annotation_id = self.annotation_id
            self.annotation_id = None
            self.result.setPlainText(f"Annotation {annotation_id} gelöscht")
            self._announce("annotation")
        self._guard(action)

    def return_to_analysis(self):
        self.returnRequested.emit()

    def _apply_field_filter(self):
        wanted = {"Nur erkannte": RecognitionStatus.RECOGNIZED.value, "Nur fehlende": RecognitionStatus.MISSING.value,
                  "Nur zu prüfende": RecognitionStatus.REVIEW.value}.get(self.field_filter.currentText())
        for row in range(self.fields.rowCount()):
            item = self.fields.item(row, 8)
            status = item.text() if item is not None else ""
            self.fields.setRowHidden(row, wanted is not None and status != wanted)

    def _apply_filters(self):
        bank = self.bank_filter.text().casefold(); document_type = self.type_filter.text().casefold(); status = self.status_filter.currentText()
        for row in range(self.documents.rowCount()):
            matches = (bank in self._cell_text(self.documents, row, 0).casefold() and
                       document_type in self._cell_text(self.documents, row, 2).casefold() and
                       (status == "Alle" or status == self._cell_text(self.documents, row, 6)))
            self.documents.setRowHidden(row, not matches)

    def _display_at(self, row):
        item = self.fields.item(row, 0)
        value = item.data(Qt.UserRole) if item is not None else None
        return value if isinstance(value, DisplayRow) else None

    def _select_field(self):
        if self._binding:
            return
        row = self.fields.currentRow()
        if row < 0:
            return
        display = self._display_at(row)
        path = display.path if display is not None else self._cell_text(self.fields, row, 0)
        standard = self._cell_text(self.fields, row, 2)
        reference = self._cell_text(self.fields, row, 4)
        self.field_path.setText(path)
        selected = reference
        if selected in {"", "null"}:
            if display is not None and _is_missing(display.value):
                selected = ""
            elif standard == "null":
                selected = ""
            else:
                selected = standard
        self.reference_value.setText(selected)
        if not self._applying_context:
            self.annotation_id = None
            self.candidate_id = None
            if self.context is not None and display is not None:
                evidence = display.evidence if isinstance(display.evidence, dict) else {}
                try:
                    page = int(display.page or evidence.get("page_number") or 0)
                except (TypeError, ValueError, OverflowError):
                    page = 0
                # The document/parser part of the handoff stays valid, but all
                # field-specific data must follow the newly selected row.
                self.context = replace(
                    self.context,
                    field_path=display.path,
                    field_id=display.path,
                    field_name=display.name,
                    requirement=display.requirement or self.context.requirement,
                    data_type=display.data_type,
                    current_value=display.value,
                    reference_value=None,
                    evidence=display.evidence,
                    page_number=page,
                    original_text=str(evidence.get("excerpt") or ""),
                    selected_text="",
                    coordinates=None,
                    annotation_id=None,
                    candidate_id=None,
                    candidate_status="",
                    training_status="Untrainiert",
                )
        if display is not None and not self._applying_context:
            self.fieldActivated.emit(display)

    def _field_item_changed(self, item):
        if self._binding or item is None or item.column() != 3:
            return
        row = item.row()
        display = self._display_at(row)
        if display is not None:
            self.field_path.setText(display.path)
        self.reference_value.setText(item.text())

    def select_field_path(self, path):
        for row in range(self.fields.rowCount()):
            display = self._display_at(row)
            text = display.path if display is not None else self._cell_text(self.fields, row, 0)
            if text == path or text.endswith(path):
                self.fields.selectRow(row)
                item = self.fields.item(row, 0)
                if item is not None:
                    self.fields.scrollToItem(item)
                return True
        return False

    def select_field_row(self, path):
        return self.select_field_path(path)

    def _selection(self):
        cursor = self.source_text.textCursor(); selected = cursor.selectedText().replace("\u2029", "\n")
        return selected or self.source_text.toPlainText()

    def add_missing(self):
        """Store a value supplied for a previously missing field."""
        def action():
            if not self.field_path.text().strip():
                raise ValueError("Bitte zuerst ein Zielfeld auswählen")
            if not self.reference_value.text().strip() and self.pending_selection is None:
                raise ValueError("Bitte den fehlenden Wert eintragen oder im PDF markieren")
            self._store(Decision.CORRECTED)
        self._guard(action)

    def confirm_field(self): self._guard(lambda: self._store(Decision.CONFIRMED))
    def correct_field(self): self._guard(lambda: self._store(Decision.CORRECTED))
    def unknown_field(self): self._guard(lambda: self._store(Decision.UNKNOWN))
    def map_text(self): self._guard(lambda: self._store(Decision.CORRECTED))

    def save_golden(self):
        def action():
            if not self.annotation_id: raise ValueError("save an annotation first")
            annotation = self.repository().annotation(self.annotation_id)
            golden = self.repository().create_golden(annotation["document_id"], "comdirect", annotation["handler_id"],
                "annotated", self.report["result"]["plugin_version"], {annotation["field_path"]: annotation["reference_value"]}, "GUI user")
            self.repository().decide_golden(golden, "APPROVED", "GUI user", "Explicit GUI confirmation")
            self.result.setPlainText(f"Golden {golden} fachlich freigegeben")
            self._announce("golden")
        self._guard(action)

    def suggest_rule(self):
        def action():
            if not self.annotation_id: raise ValueError("save an annotation first")
            self.candidate_id = TrainingService(self.repository()).suggest_rule(self.annotation_id, "GUI user")
            self.result.setPlainText(f"Regelkandidat: {self.candidate_id}" if self.candidate_id else "Kein sicherer Vorschlag möglich")
            self._announce("candidate")
        self._guard(action)

    def test_rule(self):
        def action():
            result = TrainingService(self.repository()).test_candidate(self.candidate_id, "GUI user")
            self.result.setPlainText(json.dumps(result, ensure_ascii=False, indent=2))
            self._announce("rule_test")
        self._guard(action)

    def approve_rule(self):
        def action():
            self.version_id = TrainingService(self.repository()).approve(self.candidate_id, "GUI user", "Explicit approval")
            self.result.setPlainText(f"Regelprofil-Version {self.version_id} freigegeben")
            self._announce("approved")
        self._guard(action)

    def reject_rule(self):
        def action():
            TrainingService(self.repository()).reject(self.candidate_id, "GUI user", "Rejected in GUI")
            self.result.setPlainText(f"Regelkandidat {self.candidate_id} verworfen")
            self._announce("rejected")
        self._guard(action)

    def rollback(self):
        def action():
            self.result.setPlainText(f"Wiederhergestellt als Version {self.repository().rollback_rule_version(self.version_id, 'GUI user', 'GUI rollback')}")
            self._announce("rollback")
        self._guard(action)

    def show_quality(self):
        parser_id = self.report.get("result", {}).get("plugin_id", "") if self.report else ""
        self.result.setPlainText(json.dumps(self.repository().training_metrics(parser_id), ensure_ascii=False, indent=2))

    def activate_profile(self):
        def action():
            profile_id = TrainingService(self.repository()).activate(self.version_id).profile_id
            self.result.setPlainText(f"Aktiv: {profile_id}")
            self._announce("activated")
        self._guard(action)

    def deactivate_profile(self):
        def action():
            TrainingService(self.repository()).deactivate(self.version_id)
            self.result.setPlainText(f"Profil für Version {self.version_id} deaktiviert")
            self._announce("deactivated")
        self._guard(action)

    def export_profile(self):
        def action():
            service = TrainingService(self.repository()); profile = service.activate(self.version_id)
            directory = self.settings.value("dialogs/last-directory", "", type=str) if self.settings else ""
            suggested = str(Path(directory) / f"{profile.profile_id}.yaml") if directory else f"{profile.profile_id}.yaml"
            path, _ = QFileDialog.getSaveFileName(self, "Regelprofil exportieren", suggested, "YAML (*.yaml)")
            if path:
                if self.settings: self.settings.setValue("dialogs/last-directory", str(Path(path).parent))
                service.profile_store.export_profile(profile, path); self.result.setPlainText(f"Exportiert: {path}")
        self._guard(action)

    def import_profile(self):
        def action():
            directory = self.settings.value("dialogs/last-directory", "", type=str) if self.settings else ""
            path, _ = QFileDialog.getOpenFileName(self, "Regelprofil importieren", directory, "YAML (*.yaml *.yml)")
            if path:
                if self.settings: self.settings.setValue("dialogs/last-directory", str(Path(path).parent))
                profile = TrainingService(self.repository()).profile_store.import_profile(path)
                self.result.setPlainText(f"Importiert, nicht automatisch aktiviert: {profile.profile_id} v{profile.profile_version}")
        self._guard(action)

    def _guard(self, action):
        try: action()
        except Exception as exc: QMessageBox.warning(self, "Parsertraining", str(exc))
