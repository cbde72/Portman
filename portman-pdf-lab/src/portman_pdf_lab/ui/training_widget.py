"""Compact four-area local parser-training UI."""

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
from portman_pdf_lab.training import AnnotationKind, Decision, TrainingService
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

    def __init__(self, repository_path, parent=None):
        super().__init__(parent)
        self.repository_path = repository_path
        self.report = None
        self.document_path = None
        self.annotation_id = None
        self.candidate_id = None
        self.version_id = None
        self.settings = None
        self._binding = False
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
        self.fields = CopyableTable(0, 9)
        self.fields.setHorizontalHeaderLabels(("Feldpfad", "STANDARD", "EXTENDED", "Referenzwert", "Einheit/Währung", "Quelle", "Fundstelle", "Status", "Regel-ID"))
        self.fields.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed | QAbstractItemView.SelectedClicked)
        self.fields.itemSelectionChanged.connect(self._select_field)
        self.fields.itemChanged.connect(self._field_item_changed)
        fields_layout.addLayout(field_bar); fields_layout.addWidget(self.fields)

        controls = QGroupBox("D. Trainingssteuerung")
        form = QFormLayout(controls)
        self.field_path = QLineEdit(); self.reference_value = QLineEdit()
        self.parser = QComboBox(); self.parser.addItems(("user.comdirect-ertraege", "portfolio-performance.comdirect"))
        self.mode = QComboBox(); self.mode.addItems(("STANDARD", "EXTENDED", "COMPARE"))
        self.kind = QComboBox(); self.kind.addItems([item.value for item in AnnotationKind])
        self.result = QTextEdit(); self.result.setReadOnly(True); self.result.setMaximumHeight(150)
        form.addRow("Parser", self.parser); form.addRow("Regelmodus", self.mode)
        form.addRow("Feldpfad", self.field_path); form.addRow("Referenzwert", self.reference_value); form.addRow("Annotation", self.kind)
        actions = QGridLayout()
        for index, (label, method) in enumerate((("Feld bestätigen", self.confirm_field), ("Feld korrigieren", self.correct_field),
                              ("Als unbekannt", self.unknown_field), ("PDF-Text zuordnen", self.map_text),
                              ("Referenzfall speichern", self.save_golden), ("Regelvorschlag", self.suggest_rule),
                              ("Vorschlag testen", self.test_rule), ("Vorschlag freigeben", self.approve_rule),
                              ("Vorschlag verwerfen", self.reject_rule), ("Vorherige Version", self.rollback),
                              ("Profil aktivieren", self.activate_profile), ("Profil deaktivieren", self.deactivate_profile),
                              ("Profil exportieren", self.export_profile), ("Profil importieren", self.import_profile),
                              ("Qualität", self.show_quality))):
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
                cells = (display.path, standard, extended, "", display.unit, display.source, display.page,
                         status.value, rule_id)
                for column, cell in enumerate(cells):
                    item = QTableWidgetItem(str(cell)); item.setToolTip(str(cell))
                    background = QColor(colors[status]); background.setAlpha(42); item.setBackground(background)
                    if column == 7:
                        item.setForeground(colors[status]); item.setData(Qt.UserRole + 1, status.value)
                    if column == 0:
                        item.setData(Qt.UserRole, display)
                    if column != 3:
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

    def _apply_field_filter(self):
        wanted = {"Nur erkannte": RecognitionStatus.RECOGNIZED.value, "Nur fehlende": RecognitionStatus.MISSING.value,
                  "Nur zu prüfende": RecognitionStatus.REVIEW.value}.get(self.field_filter.currentText())
        for row in range(self.fields.rowCount()):
            item = self.fields.item(row, 7)
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
        standard = self._cell_text(self.fields, row, 1)
        reference = self._cell_text(self.fields, row, 3)
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
        if display is not None:
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

    def _store(self, decision):
        if not self.report or not self.report.get("run_id"): raise ValueError("first analyze and store a PDF")
        run = self.repository().run(self.report["run_id"])
        value = self.reference_value.text()
        try: value = json.loads(value)
        except json.JSONDecodeError: pass
        self.annotation_id = self.repository().create_annotation(run["document_id"], run["plugin_id"], run["handler_id"],
            1, self._selection(), self.field_path.text(), value, self.kind.currentText(), decision.value,
            "APPROVED" if decision in {Decision.CONFIRMED, Decision.CORRECTED} else "IN_REVIEW", "GUI user")
        self.result.setPlainText(f"Annotation {self.annotation_id} gespeichert")

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
        self._guard(action)

    def suggest_rule(self):
        def action():
            if not self.annotation_id: raise ValueError("save an annotation first")
            self.candidate_id = TrainingService(self.repository()).suggest_rule(self.annotation_id, "GUI user")
            self.result.setPlainText(f"Regelkandidat: {self.candidate_id}" if self.candidate_id else "Kein sicherer Vorschlag möglich")
        self._guard(action)

    def test_rule(self):
        self._guard(lambda: self.result.setPlainText(json.dumps(TrainingService(self.repository()).test_candidate(self.candidate_id, "GUI user"), ensure_ascii=False, indent=2)))

    def approve_rule(self):
        def action():
            self.version_id = TrainingService(self.repository()).approve(self.candidate_id, "GUI user", "Explicit approval")
            self.result.setPlainText(f"Regelprofil-Version {self.version_id} freigegeben")
        self._guard(action)

    def reject_rule(self):
        self._guard(lambda: TrainingService(self.repository()).reject(self.candidate_id, "GUI user", "Rejected in GUI"))

    def rollback(self):
        self._guard(lambda: self.result.setPlainText(f"Wiederhergestellt als Version {self.repository().rollback_rule_version(self.version_id, 'GUI user', 'GUI rollback')}"))

    def show_quality(self):
        parser_id = self.report.get("result", {}).get("plugin_id", "") if self.report else ""
        self.result.setPlainText(json.dumps(self.repository().training_metrics(parser_id), ensure_ascii=False, indent=2))

    def activate_profile(self):
        self._guard(lambda: self.result.setPlainText(f"Aktiv: {TrainingService(self.repository()).activate(self.version_id).profile_id}"))

    def deactivate_profile(self):
        self._guard(lambda: TrainingService(self.repository()).deactivate(self.version_id))

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
