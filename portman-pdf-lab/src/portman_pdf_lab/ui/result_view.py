"""Lossless, read-only presentation adapters for structured parser results."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace
from decimal import Decimal
from enum import Enum
from typing import Any, Iterable

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction, QColor, QKeySequence
from PySide6.QtWidgets import (
    QApplication, QAbstractItemView, QComboBox, QHBoxLayout, QHeaderView, QLabel,
    QMenu, QStackedWidget, QTableWidget, QTableWidgetItem, QTextEdit, QToolButton,
    QVBoxLayout, QWidget,
)


class RecognitionStatus(str, Enum):
    RECOGNIZED = "ERKANNT"
    MISSING = "NICHT ERKANNT"
    REVIEW = "PRÜFEN"
    NOT_APPLICABLE = "NICHT ANWENDBAR"


@dataclass(frozen=True)
class DisplayRow:
    path: str
    name: str
    value: Any
    unit: str = ""
    status: RecognitionStatus = RecognitionStatus.REVIEW
    source: str = ""
    page: str = ""
    evidence: Any = None
    data_type: str = ""
    requirement: str = ""


def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str) and (not value.strip() or value.strip().upper() in {"NOT_FOUND", "UNKNOWN"}):
        return True
    if isinstance(value, dict):
        marker = str(value.get("status", value.get("kind", ""))).upper()
        return marker in {"MISSING", "MISSINGVALUE", "NOT_FOUND", "NOT_RECOGNIZED"}
    return value.__class__.__name__ == "MissingValue"


def _status(value: Any, evidence: bool, conflict: bool = False) -> RecognitionStatus:
    if isinstance(value, str) and value.strip().upper().replace(" ", "_") in {"N/A", "NA", "NOT_APPLICABLE"}:
        return RecognitionStatus.NOT_APPLICABLE
    if isinstance(value, dict):
        marker = str(value.get("status", "")).upper().replace(" ", "_")
        if marker in {"N/A", "NA", "NOT_APPLICABLE"}:
            return RecognitionStatus.NOT_APPLICABLE
        if marker in {"EXPECTED", "PROPOSED", "UNCONFIRMED", "AMBIGUOUS"}:
            return RecognitionStatus.REVIEW
        conflict = conflict or bool(value.get("conflict") or value.get("ambiguous"))
    if _is_missing(value):
        return RecognitionStatus.MISSING
    if conflict or not evidence:
        return RecognitionStatus.REVIEW
    return RecognitionStatus.RECOGNIZED


def scalar_text(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (Decimal, int, float)):
        return str(value)
    return str(value)


# Backwards-compatible private alias used by the original presentation adapter.
_scalar_text = scalar_text


def flatten_result(value: Any, evidence_by_id: dict[str, dict] | None = None,
                   prefix: str = "", inherited_evidence: Iterable[str] = ()) -> list[DisplayRow]:
    """Flatten dicts/lists without mutating or numerically converting the input."""
    evidence_by_id = evidence_by_id or {}
    rows: list[DisplayRow] = []

    def walk(current: Any, path: str, inherited: tuple[str, ...], inherited_conflict=False,
             inherited_unit="") -> None:
        own = tuple(str(item) for item in current.get("evidence_ids", ())) if isinstance(current, dict) else ()
        ids = own or inherited
        conflict = inherited_conflict or (isinstance(current, dict) and
                                           (current.get("conflict") is True or current.get("ambiguous") is True))
        marker = str(current.get("status", "")).upper().replace(" ", "_") if isinstance(current, dict) else ""
        if marker in {"EXPECTED", "PROPOSED", "UNCONFIRMED", "AMBIGUOUS"}:
            conflict = True
        if marker in {"N/A", "NA", "NOT_APPLICABLE"}:
            rows.append(DisplayRow(path or "$", path.rsplit(".", 1)[-1] if path else "$", current,
                                   status=RecognitionStatus.NOT_APPLICABLE))
            return
        if isinstance(current, dict) and current and not _is_missing(current):
            local_unit = str(current.get("currency", current.get("unit", inherited_unit)))
            for key, child in current.items():
                if key == "evidence_ids" or (key in {"conflict", "ambiguous"} and child is True):
                    continue
                walk(child, f"{path}.{key}" if path else str(key), ids, conflict,
                     "" if key in {"currency", "unit"} else local_unit)
            return
        if isinstance(current, list):
            if not current:
                rows.append(DisplayRow(path, path.rsplit(".", 1)[-1], "[]", status=_status(current, bool(ids))))
            for index, child in enumerate(current):
                walk(child, f"{path}[{index}]", ids, conflict, inherited_unit)
            return
        evidence = next((evidence_by_id[item] for item in ids if item in evidence_by_id), None)
        unit = inherited_unit
        if isinstance(current, dict):
            unit = str(current.get("currency", current.get("unit", "")))
        rows.append(DisplayRow(
            path or "$", (path.rsplit(".", 1)[-1] if path else "$"), current, unit,
            _status(current, evidence is not None, conflict),
            "PDF" if evidence else "ohne Evidence",
            str(evidence.get("page_number", "")) if evidence else "",
            evidence,
        ))

    walk(value, prefix, tuple(str(item) for item in inherited_evidence))
    return rows


class ResultTable(QTableWidget):
    fieldActivated = Signal(object)
    HEADERS = ("Feld", "Wert", "Typ", "Pflichtstatus", "Erkennungsstatus", "Quelle", "PDF-Seite")
    COLORS = {
        RecognitionStatus.RECOGNIZED: QColor("#2e7d32"),
        RecognitionStatus.MISSING: QColor("#c62828"),
        RecognitionStatus.REVIEW: QColor("#b26a00"),
        RecognitionStatus.NOT_APPLICABLE: QColor("#707070"),
    }

    def emit_activated(self, row: int):
        item = self.item(row, 0)
        if item is not None:
            self.fieldActivated.emit(item.data(Qt.UserRole))

    def __init__(self, parent=None):
        super().__init__(0, len(self.HEADERS), parent)
        self.setHorizontalHeaderLabels(self.HEADERS)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setSelectionBehavior(QAbstractItemView.SelectItems)
        self.setSortingEnabled(True)
        self.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)
        self.cellClicked.connect(lambda row, _column: self.emit_activated(row))
        header = self.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)
        header.setStretchLastSection(False)
        header.resizeSection(0, 260); header.resizeSection(1, 240); header.resizeSection(2, 110)

    def set_rows(self, rows: list[DisplayRow], evidence_by_id: dict[str, dict] | None = None):
        self.setSortingEnabled(False); self.setRowCount(len(rows))
        for row, data in enumerate(rows):
            value = _scalar_text(data.value) + (f" {data.unit}" if data.unit else "")
            values = (data.path, value, data.data_type, data.requirement,
                      data.status.value, data.source, data.page)
            for column, value in enumerate(values):
                item = QTableWidgetItem(value); item.setToolTip(value)
                background = QColor(self.COLORS[data.status]); background.setAlpha(42); item.setBackground(background)
                if column == 4:
                    item.setForeground(self.COLORS[data.status]); item.setData(Qt.UserRole + 1, data.status.value)
                if column == 0:
                    item.setData(Qt.UserRole, data)
                elif data.evidence is not None:
                    item.setData(Qt.UserRole, data.evidence)
                self.setItem(row, column, item)
        self.setSortingEnabled(True)

    def copy_selection(self, select_all=False):
        if select_all:
            self.selectAll()
        indexes = sorted(self.selectedIndexes(), key=lambda index: (index.row(), index.column()))
        if not indexes:
            return
        row_numbers = sorted({index.row() for index in indexes})
        columns = sorted({index.column() for index in indexes})
        text = "\n".join("\t".join(self.item(row, column).text() if self.item(row, column) else ""
                                     for column in columns) for row in row_numbers)
        QApplication.clipboard().setText(text)

    def keyPressEvent(self, event):
        if event.matches(QKeySequence.SelectAll):
            self.selectAll(); return
        if event.matches(QKeySequence.Copy):
            self.copy_selection(); return
        super().keyPressEvent(event)

    def _menu(self, position):
        menu = QMenu(self); copy = QAction("Kopieren", self); copy.triggered.connect(self.copy_selection)
        all_action = QAction("Alles kopieren", self); all_action.triggered.connect(lambda: self.copy_selection(True))
        menu.addAction(copy); menu.addAction(all_action); menu.exec(self.viewport().mapToGlobal(position))


def enrich_rows(rows: list[DisplayRow], catalog, value: Any = None) -> list[DisplayRow]:
    """Apply catalog labels, requirements and status rules without mutating values."""
    if not catalog:
        return rows
    present = {row.path for row in rows}
    values = {row.path: row.value for row in rows}

    def valid(path):
        candidate = values.get(path)
        if _is_missing(candidate):
            return False
        definition = catalog.field(path)
        return not definition or not definition.validation or bool(re.fullmatch(definition.validation, str(candidate)))

    def condition_required(definition):
        condition = definition.condition or {}
        operation = condition.get("op")
        if operation == "REQUIRED_UNLESS_VALID":
            return not any(valid(path) for path in condition.get("paths", ()))
        if operation == "PRESENT":
            return condition.get("path") in present and not _is_missing(values.get(condition.get("path")))
        if operation == "EQUALS":
            return values.get(condition.get("path")) == condition.get("value")
        if operation == "ALL":
            return all(condition_required(replace(definition, condition=item)) for item in condition.get("conditions", ()))
        if operation == "ANY":
            return any(condition_required(replace(definition, condition=item)) for item in condition.get("conditions", ()))
        return False

    enriched = []
    for row in rows:
        definition = catalog.field(row.path)
        if definition:
            status = row.status
            if not valid(row.path):
                if definition.requirement == "REQUIRED" or condition_required(definition):
                    status = RecognitionStatus.MISSING
                elif _is_missing(row.value):
                    # An absent optional value is simply not applicable: grey
                    # in the table and never an artificial PDF marker.
                    status = RecognitionStatus.NOT_APPLICABLE
                else:
                    status = RecognitionStatus.REVIEW
            enriched.append(replace(row, name=definition.label, data_type=definition.data_type,
                                    requirement=definition.requirement, status=status))
        else:
            enriched.append(row)
    for definition in catalog.visible_fields():
        if definition.path not in present:
            required = definition.requirement == "REQUIRED" or (definition.requirement == "CONDITIONAL" and condition_required(definition))
            status = RecognitionStatus.MISSING if required else RecognitionStatus.NOT_APPLICABLE
            enriched.append(DisplayRow(definition.path, definition.label, None, definition.unit, status,
                                       "Feldkatalog", "", None, definition.data_type, definition.requirement))
    return enriched


class StructuredResultView(QWidget):
    FILTERS = ("Alle Felder", "Nur erkannte", "Nur fehlende", "Nur zu prüfende")

    def __init__(self, parent=None):
        super().__init__(parent); self.rows: list[DisplayRow] = []; self.raw: Any = None
        layout = QVBoxLayout(self); bar = QHBoxLayout()
        self.mode = QComboBox(); self.mode.addItems(("Tabelle", "JSON"))
        self.filter = QComboBox(); self.filter.addItems(self.FILTERS)
        self.stats = QLabel("Erkannt 0 · Fehlend 0 · Prüfen 0 · N/A 0")
        bar.addWidget(self.mode); bar.addWidget(self.filter); bar.addWidget(self.stats); bar.addStretch()
        self.stack = QStackedWidget(); self.table = ResultTable(); self.json = QTextEdit(); self.json.setReadOnly(True)
        self.json.setLineWrapMode(QTextEdit.NoWrap)
        self.stack.addWidget(self.table); self.stack.addWidget(self.json)
        layout.addLayout(bar); layout.addWidget(self.stack)
        self.mode.currentIndexChanged.connect(self.stack.setCurrentIndex)
        self.filter.currentTextChanged.connect(self._apply_filter)

    def set_data(self, value: Any, evidence_by_id: dict[str, dict] | None = None, catalog=None):
        self.raw = value; rows = flatten_result(value, evidence_by_id)
        if catalog:
            rows = enrich_rows(rows, catalog, value)
        self.rows = rows
        self.table.set_rows(self.rows, evidence_by_id)
        self.json.setPlainText(json.dumps(value, ensure_ascii=False, indent=2, default=str))
        counts = {status: sum(row.status == status for row in self.rows) for status in RecognitionStatus}
        self.stats.setText(f"Erkannt {counts[RecognitionStatus.RECOGNIZED]} · Fehlend {counts[RecognitionStatus.MISSING]} · "
                           f"Prüfen {counts[RecognitionStatus.REVIEW]} · N/A {counts[RecognitionStatus.NOT_APPLICABLE]}")
        self._apply_filter()

    def _apply_filter(self):
        selected = self.filter.currentText()
        wanted = {"Nur erkannte": RecognitionStatus.RECOGNIZED, "Nur fehlende": RecognitionStatus.MISSING,
                  "Nur zu prüfende": RecognitionStatus.REVIEW}.get(selected)
        # Sorting may have reordered rows since set_data(), therefore read the
        # status from the row itself instead of zipping self.rows by index.
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 4)
            status = item.data(Qt.UserRole + 1) if item else None
            self.table.setRowHidden(row, wanted is not None and status != wanted.value)
