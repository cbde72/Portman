"""Parser field analysis: catalog coverage, evidence status and training entry.

The widget deliberately reuses the presentation adapters from ``result_view``
and the existing annotation/rule tables.  It never creates a parser result by
itself: a confirmed reference or a rule candidate changes the training state,
but only a real parser run (and for extra rules an activated profile) can turn
a row green.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import html
import json
from collections.abc import Iterable, Mapping
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction, QColor, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QHBoxLayout, QHeaderView, QLabel, QMenu, QPushButton, QStackedWidget, QTableWidget,
    QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget,
)

from portman_pdf_lab.field_catalog import FieldCatalog, FieldDefinition
from portman_pdf_lab.storage import ReferenceRepository
from portman_pdf_lab.training import TrainingContext
from portman_pdf_lab.ui.result_view import (
    DisplayRow, RecognitionStatus, _is_missing, enrich_rows, flatten_result,
    scalar_text,
)


HEADERS = (
    "Feldgruppe", "Feldname", "Feldpfad", "Pflichtstatus", "Gefundener Wert",
    "Erkennungsstatus", "PDF-Seite", "Evidence", "Parserregel",
    "Trainingsstatus", "Aktion",
)

STATUS_COLORS = {
    RecognitionStatus.RECOGNIZED: "#2e7d32",
    RecognitionStatus.MISSING: "#c62828",
    RecognitionStatus.REVIEW: "#b26a00",
    RecognitionStatus.NOT_APPLICABLE: "#707070",
}

GROUP_ORDER = ("Identifikation", "Handelsdaten", "Kontodaten", "Depot", "Steuern",
               "Kosten", "Technisch", "Allgemein")


def _group_for(definition: FieldDefinition | None, path: str) -> str:
    identifier = (definition.field_id if definition else path).casefold()
    if identifier.startswith(("technical.", "plugin", "evidence")) or "linked_security" in identifier:
        return "Technisch"
    if identifier.startswith(("security.", "trade.")):
        return "Identifikation" if identifier.startswith("security.") else "Handelsdaten"
    if identifier.startswith(("account.", "booking.")):
        return "Kontodaten"
    if identifier.startswith(("depot.", "snapshot.", "position.")):
        return "Depot"
    if identifier.startswith("tax."):
        return "Steuern"
    if identifier.startswith("mifid."):
        return "Kosten"
    if identifier.startswith(("payment.", "event.")):
        return "Handelsdaten"
    return "Allgemein"


def _value_text(value: Any) -> str:
    return "—" if _is_missing(value) else scalar_text(value)


def _as_int(value: Any, default: int = 0) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return number if number > 0 else default


def _evidence_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


@dataclass(frozen=True)
class FieldAnalysisRow:
    """Stable row payload independent of table sorting and filtering."""

    field_id: str
    group: str
    name: str
    path: str
    requirement: str
    value: Any
    status: RecognitionStatus
    status_text: str
    page: str = ""
    evidence: Any = None
    parser_rule: str = ""
    training_status: str = "Untrainiert"
    absence_confirmed: bool = False
    extracted: bool = False
    conflict: bool = False
    annotation_id: int | None = None
    reference_value: Any = None
    candidate_id: int | None = None
    candidate_status: str = ""
    note: str = ""
    definition: FieldDefinition | None = None

    @property
    def row_id(self) -> str:
        return self.path or self.field_id

    @property
    def training_available(self) -> bool:
        return bool(self.path)

    def display(self) -> tuple[str, ...]:
        evidence = _evidence_mapping(self.evidence)
        return (
            self.group, self.name, self.path, self.requirement, _value_text(self.value),
            self.status_text, self.page or "—", str(evidence.get("excerpt") or "—"),
            self.parser_rule or "—", self.training_status, "Feld trainieren",
        )


def _latest_annotations(annotations: Iterable[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    latest: dict[str, Mapping[str, Any]] = {}
    for annotation in annotations:
        if annotation.get("active", 1) in (0, False):
            continue
        path = str(annotation.get("field_path") or "")
        if not path:
            continue
        previous = latest.get(path)
        if previous is None or int(annotation.get("annotation_id") or 0) >= int(previous.get("annotation_id") or 0):
            latest[path] = annotation
    return latest


def _candidate_fields(candidates: Iterable[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    rank = {"DRAFT": 1, "TESTED": 2, "APPROVED": 3, "REJECTED": 0, "SUPERSEDED": 0}
    latest: dict[str, Mapping[str, Any]] = {}
    for candidate in candidates:
        rule = candidate.get("rule") if isinstance(candidate.get("rule"), Mapping) else {}
        path = str(rule.get("field_path") or candidate.get("field_path") or "")
        if not path:
            continue
        current = latest.get(path)
        if current is None or rank.get(str(candidate.get("status")), 0) >= rank.get(str(current.get("status")), 0):
            latest[path] = candidate
    return latest


def _training_status(annotation: Mapping[str, Any] | None, candidate: Mapping[str, Any] | None,
                     activation: Mapping[str, Any] | None) -> tuple[str, str, bool]:
    decision = str((annotation or {}).get("decision") or "").upper()
    kind = str((annotation or {}).get("annotation_kind") or "").upper()
    absence = decision in {"MISSING", "NOT_APPLICABLE"} or kind in {"MISSING", "NOT_APPLICABLE"}
    status = str((candidate or {}).get("status") or "")
    if candidate:
        label = {"DRAFT": "Kandidat", "TESTED": "Kandidat getestet",
                 "APPROVED": "Freigegeben", "REJECTED": "Kandidat verworfen",
                 "SUPERSEDED": "Kandidat ersetzt"}.get(status, "Kandidat")
        if status == "APPROVED" and activation and activation.get("active"):
            label += " · Profil aktiv"
        return label, status, absence
    if annotation:
        return ("Abwesenheit bestätigt" if absence else "Annotation"), status, absence
    return "Untrainiert", status, absence


def _status_text(row: DisplayRow, requirement: str, absence: bool, conflict: bool) -> str:
    if conflict:
        return "Prüfen (STANDARD/EXTENDED-Konflikt)"
    if row.status == RecognitionStatus.RECOGNIZED:
        return "Erkannt"
    if row.status == RecognitionStatus.MISSING:
        if absence:
            return "Nachweislich nicht im PDF vorhanden"
        return "Fehlt / nicht extrahiert" if requirement in {"REQUIRED", "CONDITIONAL"} else "Nicht extrahiert"
    if row.status == RecognitionStatus.REVIEW:
        return "Prüfen"
    if absence:
        return "Nachweislich nicht im PDF vorhanden"
    if requirement == "OPTIONAL":
        return "Nicht extrahiert (optional)"
    return "Nicht anwendbar"


def build_field_analysis_rows(
    report: Mapping[str, Any] | None,
    catalog: FieldCatalog | None = None,
    annotations: Iterable[Mapping[str, Any]] = (),
    candidates: Iterable[Mapping[str, Any]] = (),
    activations: Iterable[Mapping[str, Any]] = (),
) -> list[FieldAnalysisRow]:
    """Build one stable row per catalog field (or per result field as fallback)."""
    report = report or {}
    result = report.get("result") if isinstance(report.get("result"), Mapping) else {}
    evidence = {str(item.get("evidence_id")): item for item in (result.get("evidence") or [])
                if isinstance(item, Mapping)}
    rows = flatten_result(result, evidence)
    if catalog:
        rows = enrich_rows(rows, catalog, result)

    by_path: dict[str, DisplayRow] = {}
    for row in rows:
        by_path.setdefault(row.path, row)

    latest_annotations = _latest_annotations(annotations)
    latest_candidates = _candidate_fields(candidates)
    active_activation = next((item for item in activations if item.get("active")), None)

    decisions = {str(item.get("field_path")): item for item in (report.get("rule_decisions") or [])
                 if isinstance(item, Mapping) and item.get("field_path")}
    comparisons = {str(item.get("field")): item for item in (report.get("rule_comparison") or [])
                   if isinstance(item, Mapping) and item.get("field")}

    definitions = list(catalog.visible_fields()) if catalog else []
    if not definitions:
        # A report without a catalog is still inspectable.  Technical plumbing
        # is kept out where possible, but nothing raises on unusual structures.
        fallback = [row for row in rows if row.path not in {"", "$"} and
                    not row.path.endswith("evidence_ids") and row.status != RecognitionStatus.NOT_APPLICABLE]
        definitions = []

    analysis_rows: list[FieldAnalysisRow] = []
    seen: set[str] = set()

    def append_row(definition: FieldDefinition | None, match: DisplayRow | None, path: str,
                   fallback_name: str = "") -> None:
        if path in seen:
            return
        seen.add(path)
        requirement = (definition.requirement if definition else
                       (match.requirement if match else "OPTIONAL")) or "OPTIONAL"
        name = definition.label if definition else (match.name if match else fallback_name or path)
        if match is None:
            required = requirement in {"REQUIRED"} or (requirement == "CONDITIONAL")
            match = DisplayRow(path, name, None, definition.unit if definition else "",
                               RecognitionStatus.MISSING if required else RecognitionStatus.NOT_APPLICABLE,
                               "Feldkatalog", "", None, definition.data_type if definition else "",
                               requirement)
        annotation = latest_annotations.get(path)
        candidate = latest_candidates.get(path)
        status_label, candidate_status, absence = _training_status(annotation, candidate, active_activation)
        decision = decisions.get(path) or {}
        comparison = comparisons.get(path) or {}
        conflict = bool(decision.get("conflict") or comparison.get("conflict"))
        effective = decision.get("effective_value")
        reference = (annotation or {}).get("reference_value")
        if (str(report.get("rule_mode_effective") or "").upper() == "EXTENDED" and
                effective is not None and not conflict and annotation and str(effective) == str(reference)):
            # Only a real EXTENDED run with an active approved profile may turn
            # a trained field into a successful parser recognition. A manual
            # reference or draft candidate alone never reaches this branch.
            match = replace(match, value=effective, status=RecognitionStatus.RECOGNIZED,
                            source=str(decision.get("provenance") or "EXTENDED rule profile"))
        status = RecognitionStatus.REVIEW if conflict else match.status
        status_text = _status_text(match, requirement, absence, conflict)
        annotation_evidence = _evidence_mapping((annotation or {}).get("evidence"))
        evidence_value = match.evidence or (annotation_evidence or None)
        evidence_mapping = _evidence_mapping(evidence_value)
        page = str(match.page or evidence_mapping.get("page_number") or
                   ((annotation or {}).get("page_number") or ""))
        candidate_rule = (candidate or {}).get("rule")
        candidate_rule = candidate_rule if isinstance(candidate_rule, Mapping) else {}
        rule_id = str(candidate_rule.get("rule_id") or "")
        if not rule_id:
            rule_id = str(decision.get("rule_id") or comparison.get("rule_id") or "")
        extracted = (match.value is not None and not _is_missing(match.value)
                     and match.status != RecognitionStatus.NOT_APPLICABLE)
        note = ""
        if conflict:
            note = "STANDARD und EXTENDED liefern unterschiedliche Werte."
        if absence:
            note = " ".join(filter(None, (note, "Abwesenheit wurde durch eine Annotation bestätigt.")))
        analysis_rows.append(FieldAnalysisRow(
            field_id=definition.field_id if definition else path,
            group=_group_for(definition, path),
            name=name,
            path=path,
            requirement=requirement,
            value=match.value,
            status=status,
            status_text=status_text,
            page=page,
            evidence=evidence_value,
            parser_rule=rule_id,
            training_status=status_label,
            absence_confirmed=absence,
            extracted=extracted,
            conflict=conflict,
            annotation_id=(annotation or {}).get("annotation_id"),
            reference_value=(annotation or {}).get("reference_value"),
            candidate_id=(candidate or {}).get("candidate_id"),
            candidate_status=candidate_status,
            note=note,
            definition=definition,
        ))

    for definition in definitions:
        match = by_path.get(definition.path)
        if match is None:
            descendants = [row for row in rows
                           if row.path.startswith(definition.path + ".") or
                           row.path.startswith(definition.path + "[")]
            match = descendants[0] if descendants else None
        append_row(definition, match, definition.path)

    if not definitions:
        for row in fallback:
            append_row(None, row, row.path)

    group_index = {name: index for index, name in enumerate(GROUP_ORDER)}
    analysis_rows.sort(key=lambda item: (group_index.get(item.group, 99),
                                         item.definition.order if item.definition else 900,
                                         item.path))
    return analysis_rows


def training_context_for_row(
    row: FieldAnalysisRow,
    report: Mapping[str, Any] | None,
    document_hash: str = "",
    catalog_version: int = 0,
    rule_profile_version: int = 0,
) -> TrainingContext:
    """Collect every piece of context the training tab otherwise asks for."""
    report = report or {}
    detection = report.get("detection") if isinstance(report.get("detection"), Mapping) else {}
    result = report.get("result") if isinstance(report.get("result"), Mapping) else {}
    evidence = _evidence_mapping(row.evidence)
    parser_id = str(result.get("plugin_id") or detection.get("plugin_id") or "")
    handler = str(result.get("handler_id") or detection.get("handler_id") or "")
    bank = ("comdirect" if "comdirect" in parser_id.casefold()
            else parser_id.split(".")[0]) or "generic"
    page = _as_int(row.page or evidence.get("page_number"), 0)
    original = str(evidence.get("excerpt") or "")
    reference = row.reference_value
    if _is_missing(reference):
        reference = None if _is_missing(row.value) else row.value
    return TrainingContext(
        document_id=str(report.get("document_id") or result.get("document_id") or ""),
        document_hash=str(document_hash or report.get("source_hash") or evidence.get("document_hash") or ""),
        bank=bank,
        parser_id=parser_id,
        handler_id=handler,
        document_type=str(detection.get("document_type") or ""),
        rule_mode=str(report.get("rule_mode_effective") or report.get("rule_mode_requested") or "STANDARD"),
        field_path=row.path,
        field_id=row.field_id,
        field_name=row.name,
        requirement=row.requirement,
        data_type=str(row.definition.data_type if row.definition else ""),
        current_value=row.value,
        reference_value=reference,
        evidence=row.evidence,
        page_number=page,
        original_text=original,
        catalog_version=int(catalog_version or 0),
        rule_profile_version=int(rule_profile_version or 0),
        annotation_id=row.annotation_id,
        candidate_id=row.candidate_id,
        candidate_status=row.candidate_status,
        training_status=row.training_status,
        report=dict(report),
    )


def field_help_html(row: FieldAnalysisRow) -> str:
    definition = row.definition
    description = definition.description if definition else row.name
    data_type = definition.data_type if definition else "TEXT"
    expected = (definition.pdf_source if definition and definition.pdf_source else
                "Gedruckte Angabe im PDF; ohne Evidence oder Bestätigung gilt ein Wert nicht als nachweislich vorhanden.")
    validation = (definition.validation if definition and definition.validation else "keine besondere Validierung")
    rules = ", ".join(definition.available_rules) if definition else "STANDARD, EXTENDED"
    missing_behavior = (definition.missing_behavior if definition else
                        "Fehlende Werte werden als nicht extrahiert dargestellt.")
    return (
        f"<h1>{html.escape(row.name)}</h1>"
        f"<p><code>{html.escape(row.path)}</code></p>"
        f"<h2>Feldbeschreibung</h2><p>{html.escape(description)}</p>"
        f"<h2>Datentyp</h2><p>{html.escape(data_type)}</p>"
        f"<h2>Pflichtbedingung</h2><p>{html.escape(row.requirement)}</p>"
        f"<h2>Erwartete PDF-Information</h2><p>{html.escape(expected)}</p>"
        f"<h2>Validierungsregeln</h2><p>{html.escape(validation)}</p>"
        f"<h2>Verfügbare Erkennungsregeln</h2><p>{html.escape(rules)}</p>"
        f"<h2>Aktueller Trainingsstatus</h2><p>{html.escape(row.training_status)}</p>"
        f"<h2>Aktueller Parserwert</h2><p>{html.escape(_value_text(row.value))}</p>"
        f"<h2>Status</h2><p>{html.escape(row.status_text)}</p>"
        f"<h2>Fehlendes Feld</h2><p>{html.escape(missing_behavior)}</p>"
    )


class FieldHelpDialog(QDialog):
    def __init__(self, row: FieldAnalysisRow, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Feldhilfe – {row.name}")
        self.resize(760, 620)
        layout = QVBoxLayout(self)
        text = QTextEdit(); text.setReadOnly(True); text.setHtml(field_help_html(row))
        layout.addWidget(text)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject); layout.addWidget(buttons)


class FieldAnalysisTable(QTableWidget):
    fieldActivated = Signal(object)
    trainingRequested = Signal(object)
    helpRequested = Signal(object)

    def __init__(self, parent=None):
        super().__init__(0, len(HEADERS), parent)
        self.setHorizontalHeaderLabels(HEADERS)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setSelectionBehavior(QAbstractItemView.SelectItems)
        self.setSortingEnabled(True)
        self.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.setWordWrap(False)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)
        header = self.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)
        header.setStretchLastSection(False)
        for column, width in enumerate((120, 180, 310, 110, 190, 190, 80, 260, 150, 170, 130)):
            header.resizeSection(column, width)
        self.cellClicked.connect(self._clicked)
        self.cellDoubleClicked.connect(lambda row, _column: self._train(row))

    def row_at(self, row: int) -> FieldAnalysisRow | None:
        for column in (0, 1, 2, len(HEADERS) - 1):
            item = self.item(row, column)
            value = item.data(Qt.UserRole) if item is not None else None
            if isinstance(value, FieldAnalysisRow):
                return value
        return None

    def selected_row(self) -> FieldAnalysisRow | None:
        row = self.currentRow()
        return self.row_at(row) if row >= 0 else None

    def set_rows(self, rows: list[FieldAnalysisRow]) -> None:
        self.setSortingEnabled(False)
        try:
            self.clearContents()
            self.setRowCount(len(rows))
            for index, data in enumerate(rows):
                for column, text in enumerate(data.display()):
                    item = QTableWidgetItem(str(text)); item.setToolTip(str(text))
                    item.setData(Qt.UserRole, data)
                    item.setData(Qt.UserRole + 1, data.status.value)
                    color = QColor(STATUS_COLORS.get(data.status, "#707070"))
                    background = QColor(color); background.setAlpha(42)
                    item.setBackground(background)
                    if column == 5:
                        item.setForeground(color)
                    if column == 10:
                        item.setToolTip("Öffnet das vorhandene Parsertraining mit vorbelegtem Feld")
                    self.setItem(index, column, item)
        finally:
            self.setSortingEnabled(True)

    def _clicked(self, row: int, column: int) -> None:
        data = self.row_at(row)
        if data is None:
            return
        if column == 10:
            self.trainingRequested.emit(data)
        else:
            self.fieldActivated.emit(data)

    def _train(self, row: int) -> None:
        data = self.row_at(row)
        if data is not None and data.training_available:
            self.trainingRequested.emit(data)

    def copy_selection(self, select_all: bool = False) -> None:
        if select_all:
            self.selectAll()
        indexes = sorted(self.selectedIndexes(), key=lambda item: (item.row(), item.column()))
        if not indexes:
            return
        row_numbers = sorted({item.row() for item in indexes})
        columns = sorted({item.column() for item in indexes})
        text = "\n".join("\t".join(self.item(row, column).text() if self.item(row, column) else ""
                                   for column in columns) for row in row_numbers)
        QApplication.clipboard().setText(text)

    def keyPressEvent(self, event):
        if event.matches(QKeySequence.HelpContents):
            data = self.selected_row()
            if data is not None:
                self.helpRequested.emit(data); return
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            data = self.selected_row()
            if data is not None and data.training_available:
                self.trainingRequested.emit(data); return
        if event.matches(QKeySequence.SelectAll):
            self.selectAll(); return
        if event.matches(QKeySequence.Copy):
            self.copy_selection(); return
        super().keyPressEvent(event)

    def _menu(self, position):
        data = self.row_at(self.rowAt(position.y()))
        menu = QMenu(self)
        copy = QAction("Kopieren", self); copy.triggered.connect(self.copy_selection)
        all_action = QAction("Alles kopieren", self); all_action.triggered.connect(lambda: self.copy_selection(True))
        menu.addAction(copy); menu.addAction(all_action)
        if data is not None:
            menu.addSeparator()
            train = QAction("Feld trainieren", self); train.setEnabled(data.training_available)
            train.triggered.connect(lambda: self.trainingRequested.emit(data)); menu.addAction(train)
            evidence = QAction("Fundstelle anzeigen", self)
            evidence.triggered.connect(lambda: self.fieldActivated.emit(data)); menu.addAction(evidence)
            help_action = QAction("Feldhilfe (F1)", self)
            help_action.triggered.connect(lambda: self.helpRequested.emit(data)); menu.addAction(help_action)
        menu.exec(self.viewport().mapToGlobal(position))


class FieldAnalysisWidget(QWidget):
    trainingRequested = Signal(object)
    fieldActivated = Signal(object)
    helpRequested = Signal(object)
    testRuleRequested = Signal()
    approveRuleRequested = Signal()
    activateRuleRequested = Signal()

    FILTERS = ("Alle Felder", "Nur erkannte", "Nur fehlende", "Nur zu prüfende",
               "Nur optionale fehlend")

    def __init__(self, repository_path=None, parent=None):
        super().__init__(parent)
        self.repository_path = repository_path
        self.report: Mapping[str, Any] | None = None
        self.catalog: FieldCatalog | None = None
        self.document_hash = ""
        self.document_id = ""
        self.rule_profile_version = 0
        self._rows: list[FieldAnalysisRow] = []
        self.quick_mode = False
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        bar = QHBoxLayout()
        self.mode = QComboBox(); self.mode.addItems(("Tabelle", "JSON"))
        self.filter = QComboBox(); self.filter.addItems(self.FILTERS)
        self.stats = QLabel("Erkannt 0 · Fehlend 0 · Prüfen 0 · N/A 0")
        self.quality_hint = QLabel("Textqualität: —")
        self.quality_hint.setToolTip("Qualität der gemeinsamen PDF-Textaufbereitung")
        self.show_all = QCheckBox("Alle Felder anzeigen"); self.show_all.setVisible(False)
        self.test_rule = QPushButton("Regel prüfen"); self.test_rule.setVisible(False)
        self.approve_rule = QPushButton("Regel freigeben"); self.approve_rule.setVisible(False)
        self.activate_rule = QPushButton("Profil aktivieren"); self.activate_rule.setVisible(False)
        bar.addWidget(self.mode); bar.addWidget(self.filter); bar.addWidget(self.stats)
        bar.addStretch(); bar.addWidget(self.quality_hint)
        for widget in (self.show_all, self.test_rule, self.approve_rule, self.activate_rule): bar.addWidget(widget)
        self.stack = QStackedWidget()
        self.table = FieldAnalysisTable()
        self.table.fieldActivated.connect(self.fieldActivated)
        self.table.trainingRequested.connect(self.trainingRequested)
        self.table.helpRequested.connect(self.helpRequested)
        self.json = QTextEdit(); self.json.setReadOnly(True); self.json.setLineWrapMode(QTextEdit.NoWrap)
        self.stack.addWidget(self.table); self.stack.addWidget(self.json)
        layout.addLayout(bar); layout.addWidget(self.stack)
        self.mode.currentIndexChanged.connect(self.stack.setCurrentIndex)
        self.filter.currentTextChanged.connect(self._apply_filter)
        self.show_all.toggled.connect(self._apply_filter)
        self.test_rule.clicked.connect(self.testRuleRequested); self.approve_rule.clicked.connect(self.approveRuleRequested)
        self.activate_rule.clicked.connect(self.activateRuleRequested)

    def set_quick_mode(self, enabled: bool):
        self.quick_mode = enabled; self.mode.setVisible(not enabled); self.filter.setVisible(not enabled)
        for widget in (self.show_all, self.test_rule, self.approve_rule, self.activate_rule): widget.setVisible(enabled)
        for column in (2, 7, 8): self.table.setColumnHidden(column, enabled)
        self._apply_filter()

    @property
    def rows(self) -> list[FieldAnalysisRow]:
        return list(self._rows)

    def repository(self):
        return ReferenceRepository(self.repository_path) if self.repository_path else None

    def bind_report(self, report: Mapping[str, Any] | None, catalog: FieldCatalog | None = None,
                    document_hash: str = "", annotations=None, candidates=None,
                    activations=None) -> None:
        self.report = report or {}
        self.catalog = catalog
        preparation = self.report.get("text_preparation") if isinstance(self.report, Mapping) else {}
        preparation = preparation if isinstance(preparation, Mapping) else {}
        quality = str(preparation.get("quality") or "")
        self.quality_hint.setText({
            "ok": "Textqualität: OK",
            "suspicious": "Textqualität: prüfen",
            "unreliable": "Textqualität: nicht zuverlässig",
        }.get(quality.casefold(), "Textqualität: —"))
        self.document_hash = str(document_hash or (self.report or {}).get("source_hash") or "")
        self.document_id = ""
        repository = self.repository()
        run_id = (self.report or {}).get("run_id")
        if repository is not None and run_id:
            try:
                run = repository.run(int(run_id))
                self.document_id = str(run.get("document_id") or "")
                self.document_hash = self.document_hash or str(repository.document(self.document_id).get("sha256") or "")
                if annotations is None:
                    annotations = repository.annotations_for_document(self.document_id)
                if candidates is None:
                    candidates = repository.rule_candidates_for_document(self.document_id)
                if activations is None:
                    activations = repository.profile_activations_for(
                        str(run.get("plugin_id") or ""), str(run.get("handler_id") or ""))
            except (KeyError, ValueError, TypeError):
                annotations = annotations or ()
                candidates = candidates or ()
                activations = activations or ()
        activations = tuple(activations or ())
        active = next((item for item in activations if item.get("active")), None)
        self.rule_profile_version = int((active or {}).get("profile_version") or 0)
        self.set_rows(build_field_analysis_rows(
            self.report, catalog, annotations or (), candidates or (), activations))

    def refresh_from_repository(self) -> None:
        self.bind_report(self.report, self.catalog, self.document_hash)

    def refresh(self) -> None:
        self.refresh_from_repository()

    def set_rows(self, rows: list[FieldAnalysisRow]) -> None:
        self._rows = list(rows)
        self.table.set_rows(self._rows)
        self.json.setPlainText(json.dumps([{
            "field_group": row.group, "name": row.name, "path": row.path,
            "requirement": row.requirement, "value": _value_text(row.value),
            "status": row.status_text, "page": row.page,
            "evidence": (_evidence_mapping(row.evidence).get("excerpt") or ""),
            "parser_rule": row.parser_rule, "training_status": row.training_status,
            "action": "Feld trainieren", "absence_confirmed": row.absence_confirmed,
            "extracted": row.extracted, "conflict": row.conflict,
        } for row in self._rows], ensure_ascii=False, indent=2))
        counts = {status: sum(row.status == status for row in self._rows) for status in RecognitionStatus}
        self.stats.setText(
            f"Erkannt {counts[RecognitionStatus.RECOGNIZED]} · Fehlend {counts[RecognitionStatus.MISSING]} · "
            f"Prüfen {counts[RecognitionStatus.REVIEW]} · N/A {counts[RecognitionStatus.NOT_APPLICABLE]}")
        self._apply_filter()

    def _apply_filter(self):
        selected = self.filter.currentText()
        wanted = {"Nur erkannte": RecognitionStatus.RECOGNIZED,
                  "Nur fehlende": RecognitionStatus.MISSING,
                  "Nur zu prüfende": RecognitionStatus.REVIEW}.get(selected)
        for row in range(self.table.rowCount()):
            data = self.table.row_at(row)
            if data is None:
                self.table.setRowHidden(row, True); continue
            if selected == "Nur optionale fehlend":
                hidden = not (data.requirement == "OPTIONAL" and data.status == RecognitionStatus.NOT_APPLICABLE)
            else:
                hidden = wanted is not None and data.status != wanted
            if self.quick_mode and not self.show_all.isChecked():
                hidden = hidden or (data.requirement == "OPTIONAL" and data.status == RecognitionStatus.NOT_APPLICABLE) or data.requirement == "TECHNICAL"
            self.table.setRowHidden(row, hidden)

    def row_for_path(self, path: str) -> FieldAnalysisRow | None:
        return next((row for row in self._rows if row.path == path or row.path.endswith(path)), None)

    def select_field_path(self, path: str) -> bool:
        if not path:
            return False
        for row in range(self.table.rowCount()):
            data = self.table.row_at(row)
            if data is not None and (data.path == path or data.path.endswith(path)):
                self.table.selectRow(row)
                item = self.table.item(row, 0)
                if item is not None:
                    self.table.scrollToItem(item)
                return True
        return False

    def select_row(self, row: FieldAnalysisRow) -> bool:
        return self.select_field_path(row.path)

    def selected_row(self) -> FieldAnalysisRow | None:
        return self.table.selected_row()

    def training_context(self, row: FieldAnalysisRow | None = None,
                         rule_profile_version: int | None = None) -> TrainingContext | None:
        selected = row or self.selected_row()
        if selected is None:
            return None
        version = self.rule_profile_version if rule_profile_version is None else rule_profile_version
        return training_context_for_row(selected, self.report or {}, self.document_hash,
                                        self.catalog.version if self.catalog else 0,
                                        version)

    def help_html(self, row: FieldAnalysisRow | None = None) -> str:
        selected = row or self.selected_row()
        return field_help_html(selected) if selected is not None else ""

    def save_settings(self, settings):
        settings.setValue("headers/field-analysis", self.table.horizontalHeader().saveState())

    def restore_settings(self, settings):
        state = settings.value("headers/field-analysis")
        if state:
            self.table.horizontalHeader().restoreState(state)
