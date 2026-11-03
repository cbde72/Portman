"""Read-only presentation of values actually returned by STANDARD."""

from __future__ import annotations

from dataclasses import dataclass
import csv
import json
from collections.abc import Mapping
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QApplication, QAbstractItemView, QCheckBox, QDialog, QFileDialog, QHBoxLayout, QLabel,
    QLineEdit, QMenu, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from portman_pdf_lab.field_catalog import FieldCatalog, FieldDefinition, normalize_field_path
from portman_pdf_lab.field_descriptions import resolve_description
from portman_pdf_lab.ui.result_view import (
    DisplayRow, RecognitionStatus, _is_missing, flatten_result, scalar_text,
)


HEADERS = ("Variable", "Wert", "Beschreibung", "Feldname", "Einheit / Währung",
           "Datentyp", "Parser-ID", "Regel-ID", "PDF-Seite", "Evidence", "Status")
FINANCIAL_ROOTS = frozenset({
    "accounts", "depots", "depot_snapshots", "account_balances",
    "depot_account_links", "events", "snapshots", "tax_calculations",
    "tax_carryforwards",
})
# Parser bookkeeping and transport metadata are not financial result values.
NON_VALUE_SEGMENTS = frozenset({
    "attributes", "evidence", "evidence_ids", "issues", "review_status",
    "page_number", "source_ref", "confidence", "plugin_id",
    "plugin_version", "handler_id", "document_id", "result_id",
    "schema_version", "event_id", "movement_id", "trade_id",
    "tax_event_id", "fee_id", "cost_event_id", "snapshot_id",
    "position_id", "link_id", "balance_id",
})


def is_financial_value_path(path: str) -> bool:
    normalized = normalize_field_path(path)
    parts = normalized.replace("[]", "").split(".")
    return bool(parts and parts[0] in FINANCIAL_ROOTS and
                not any(part in NON_VALUE_SEGMENTS for part in parts))


def normalize_description_path(path: str) -> str:
    """Backward-compatible name for the central catalog normalizer."""
    return normalize_field_path(path)


def _catalog_definition(catalog: FieldCatalog | None, path: str) -> FieldDefinition | None:
    if catalog is None:
        return None
    return catalog.field_for_description(path)


def _actual_value(value: Any) -> bool:
    """Return whether a value is genuinely present in STANDARD output."""
    if _is_missing(value):
        return False
    if isinstance(value, (str, bytes)):
        return bool(value.strip())
    if isinstance(value, (list, tuple, set, frozenset, dict)):
        return bool(value)
    # False and numeric zero are valid parser values.
    return True


@dataclass(frozen=True)
class StandardValueRow:
    path: str
    name: str
    value: Any
    description: str
    unit: str = ""
    data_type: str = ""
    parser_id: str = ""
    rule_id: str = ""
    page: str = ""
    evidence: Any = None
    status: str = "Erkannt"
    display_row: DisplayRow | None = None
    definition: FieldDefinition | None = None

    def display(self, details: bool = True) -> tuple[str, ...]:
        evidence = self.evidence if isinstance(self.evidence, Mapping) else {}
        # The first three columns are the compact/main view. The remaining
        # columns are technical details and are hidden until requested.
        return (
            self.path,
            scalar_text(self.value),
            self.description,
            self.name,
            self.unit or "—",
            self.data_type or "—",
            self.parser_id or "—",
            self.rule_id or "—",
            self.page or "—",
            str(evidence.get("excerpt") or "Evidence fehlt"),
            self.status,
        )


def build_standard_value_rows(report: Mapping[str, Any] | None,
                              catalog: FieldCatalog | None = None,
                              financial_only: bool = False) -> list[StandardValueRow]:
    """Build rows exclusively from the original report's STANDARD result."""
    report = report or {}
    result = report.get("result") if isinstance(report.get("result"), Mapping) else {}
    evidence_by_id = {
        str(item.get("evidence_id")): item
        for item in (result.get("evidence") or ())
        if isinstance(item, Mapping) and item.get("evidence_id")
    }
    rows: list[StandardValueRow] = []
    for display in flatten_result(result, evidence_by_id):
        if financial_only and not is_financial_value_path(display.path):
            continue
        if (display.status == RecognitionStatus.NOT_APPLICABLE or
                display.value == "[]" or not _actual_value(display.value)):
            continue
        definition = _catalog_definition(catalog, display.path)
        evidence = display.evidence if isinstance(display.evidence, Mapping) else None
        name = definition.label if definition else display.name
        description = resolve_description(display.path, catalog).description
        unit = (definition.unit if definition and definition.unit else display.unit)
        status = "Erkannt" if evidence is not None else "Evidence fehlt / Prüfen"
        rows.append(StandardValueRow(
            path=display.path, name=name, value=display.value, description=description,
            unit=unit, data_type=definition.data_type if definition else display.data_type,
            parser_id=str(result.get("plugin_id") or ""),
            rule_id="", page=display.page, evidence=evidence, status=status,
            display_row=display, definition=definition,
        ))
    return sorted(rows, key=lambda row: (
        row.definition.order if row.definition else 900, row.name.casefold(), row.path))


def audit_standard_descriptions(report: Mapping[str, Any] | None,
                                catalog: FieldCatalog | None = None) -> list[dict[str, str]]:
    """Return a reproducible audit of every displayed variable and its source."""
    result = []
    for row in build_standard_value_rows(report, catalog):
        exact = catalog.field(row.path) if catalog else None
        result.append({
            "variable": row.path,
            "description": row.description,
            "source": "field_catalog" if exact else "field_catalog_normalized" if row.definition else "unknown",
        })
    return result


class StandardValuesTable(QTableWidget):
    fieldActivated = Signal(object)

    def __init__(self, parent=None):
        super().__init__(0, len(HEADERS), parent)
        self.setHorizontalHeaderLabels(HEADERS)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setSelectionBehavior(QAbstractItemView.SelectItems)
        self.setSortingEnabled(True)
        self.setWordWrap(False)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)
        self.cellClicked.connect(self._clicked)
        self.cellDoubleClicked.connect(self._clicked)
        self.horizontalHeader().setStretchLastSection(False)
        self.setColumnWidth(0, 320); self.setColumnWidth(1, 220)
        self.setColumnWidth(2, 420); self.setColumnWidth(3, 180)

    def set_rows(self, rows: list[StandardValueRow], details: bool = True):
        self.setSortingEnabled(False)
        self.clearContents(); self.setRowCount(len(rows))
        for row_index, data in enumerate(rows):
            for column, text in enumerate(data.display(details)):
                item = QTableWidgetItem(str(text)); item.setToolTip(str(text))
                item.setData(Qt.UserRole, data)
                self.setItem(row_index, column, item)
        self.setSortingEnabled(True)

    def _clicked(self, row: int, _column: int):
        item = self.item(row, 0)
        data = item.data(Qt.UserRole) if item else None
        if isinstance(data, StandardValueRow):
            self.fieldActivated.emit(data)

    def selected_value(self) -> StandardValueRow | None:
        item = self.item(self.currentRow(), 0)
        data = item.data(Qt.UserRole) if item else None
        return data if isinstance(data, StandardValueRow) else None

    def copy_selection(self, select_all: bool = False):
        if select_all:
            self.selectAll()
        indexes = sorted(self.selectedIndexes(), key=lambda index: (index.row(), index.column()))
        if not indexes:
            return
        rows = sorted({index.row() for index in indexes})
        columns = sorted({index.column() for index in indexes})
        QApplication.clipboard().setText("\n".join(
            "\t".join(self.item(row, column).text() if self.item(row, column) else "" for column in columns)
            for row in rows))

    def keyPressEvent(self, event):
        if event.matches(QKeySequence.SelectAll): self.selectAll(); return
        if event.matches(QKeySequence.Copy): self.copy_selection(); return
        super().keyPressEvent(event)

    def _menu(self, position):
        menu = QMenu(self)
        copy = QAction("Kopieren", self); copy.triggered.connect(self.copy_selection)
        all_action = QAction("Alles kopieren", self); all_action.triggered.connect(lambda: self.copy_selection(True))
        menu.addAction(copy); menu.addAction(all_action); menu.exec(self.viewport().mapToGlobal(position))


class StandardValuesDialog(QDialog):
    fieldActivated = Signal(object)

    def __init__(self, rows: list[StandardValueRow], report: Mapping[str, Any] | None = None, parent=None):
        super().__init__(parent)
        self.rows = list(rows); self.report = report or {}
        self.setWindowTitle("Alle gefundenen Werte – STANDARD")
        self.resize(1250, 720)
        layout = QVBoxLayout(self)
        bar = QHBoxLayout()
        self.search = QLineEdit(); self.search.setPlaceholderText("Feld, Wert oder Beschreibung suchen …")
        self.details = QCheckBox("Details anzeigen"); self.details.setChecked(False)
        self.count = QLabel()
        self.export_json = QPushButton("JSON exportieren"); self.export_csv = QPushButton("CSV exportieren")
        bar.addWidget(self.search); bar.addWidget(self.details); bar.addWidget(self.count)
        bar.addStretch(); bar.addWidget(self.export_json); bar.addWidget(self.export_csv)
        layout.addLayout(bar)
        self.table = StandardValuesTable(); layout.addWidget(self.table)
        self.search.textChanged.connect(self._filter)
        self.details.toggled.connect(self._details_changed)
        self.export_json.clicked.connect(self._save_json); self.export_csv.clicked.connect(self._save_csv)
        self.table.fieldActivated.connect(self.fieldActivated)
        self._details_changed(False)

    def _details_changed(self, checked: bool):
        hidden = not checked
        for column in range(3, len(HEADERS)):
            self.table.setColumnHidden(column, hidden)
        self.table.set_rows(self.rows, checked)
        self._filter(self.search.text())

    def _filter(self, text: str):
        needle = str(text or "").casefold()
        visible = 0
        for row in range(self.table.rowCount()):
            haystack = " ".join(self.table.item(row, column).text() for column in range(self.table.columnCount())
                                if self.table.item(row, column)).casefold()
            hidden = needle not in haystack
            self.table.setRowHidden(row, hidden)
            visible += not hidden
        self.count.setText(f"{visible} von {len(self.rows)} gefunden")

    def _save_json(self):
        path, _ = QFileDialog.getSaveFileName(self, "STANDARD-Werte exportieren", "standard-values.json", "JSON (*.json)")
        if not path: return
        data = [{"name": row.name, "path": row.path, "value": scalar_text(row.value),
                 "description": row.description, "unit": row.unit, "page": row.page,
                 "evidence": row.evidence, "status": row.status} for row in self.rows]
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2, default=str)

    def _save_csv(self):
        path, _ = QFileDialog.getSaveFileName(self, "STANDARD-Werte exportieren", "standard-values.csv", "CSV (*.csv)")
        if not path: return
        with open(path, "w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle); writer.writerow(HEADERS)
            writer.writerows(row.display(True) for row in self.rows)
