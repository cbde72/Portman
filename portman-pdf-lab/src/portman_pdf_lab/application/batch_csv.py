"""Read-only CSV export of PDF-detected parser values for batch runs.

The export never writes to SQLite, reference values, parser history, training
data or field-catalog files.  Training information is read through a separate
read-only connection (see :mod:`training_export`).  Every PDF produces exactly
one CSV row; detected field columns are the dynamic union of all evidence-backed
paths, and training columns are always appended at the far right.
"""

from __future__ import annotations

import csv
import os
import tempfile
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from portman_pdf_lab.field_descriptions import resolve_description

from .training_export import TrainingExportReader, training_columns, training_values


BASE_FIELDS = (
    "source", "source_hash", "plugin_id", "handler_id",
    "document_type", "status", "runtime_ns",
)

# Top-level result keys that are transport/proof metadata rather than detected
# document fields.  They are never exported as PDF values.
_SKIP_ROOTS = frozenset({"evidence", "issues"})

# Generated internal identifiers and pure transport/provenance metadata.  A leaf
# whose final segment matches is never exported as a "detected PDF value", even
# when it inherits the evidence ids of its parent container.  Real detected
# identifiers (iban, bic, account_number, security_isin, security_wkn, ...) do
# not end in ``_id`` and stay exported.  The same applies to ``FieldValue``
# wrappers such as ``security_id`` (the printed WKN of a depot position): their
# content comes from the PDF, so the generic ``_id`` suffix does not filter them.
_TECHNICAL_LEAVES = frozenset({
    "schema_version", "plugin_version", "evidence_ids", "review_status",
    "page_number", "source_ref", "confidence", "bank_reference_status",
    "security_identity_evidence_ids", "bank_reference_evidence_ids",
})

_MISSING_DESCRIPTION = "Beschreibung fehlt"


def _is_missing(value: Any) -> bool:
    """True for placeholders that must not be exported as a detected value."""
    if value is None:
        return True
    if isinstance(value, str):
        marker = value.strip().upper()
        if not value.strip() or marker in {"NOT_FOUND", "UNKNOWN", "MISSING"}:
            return True
    if isinstance(value, Mapping):
        marker = str(value.get("status", value.get("kind", ""))).upper()
        if marker in {"MISSING", "MISSINGVALUE", "NOT_FOUND", "NOT_RECOGNIZED"}:
            return True
    return value.__class__.__name__ == "MissingValue"


def _leaf_name(path: str) -> str:
    return path.rsplit(".", 1)[-1].rsplit("[", 1)[0]


def _is_technical_leaf(path: str, detected: bool = False) -> bool:
    name = _leaf_name(path)
    if name in _TECHNICAL_LEAVES:
        return True
    # ``detected`` markiert FieldValue-Blätter: ihr Inhalt stammt aus dem PDF,
    # das generische ``_id``-Suffix (interne Verknüpfungs-IDs) trifft sie nicht.
    return not detected and name.endswith("_id")


def _scalar_text(value: Any) -> str:
    """Canonical text for a detected leaf.  Zero and ``0.00`` stay visible."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _is_field_value(node: Any) -> bool:
    """A FieldValue transport wrapper carries ``value`` plus provenance keys."""
    return (isinstance(node, Mapping) and "value" in node
            and any(key in node for key in ("source", "evidence_ids", "review_status", "page_number")))


def flatten_evidence_values(result: Mapping[str, Any]) -> dict[str, str]:
    """Return ``{field_path: text}`` for leaves backed by PDF evidence.

    FieldValue wrappers are exported under their unwrapped path (``...amount``,
    not ``...amount.value``) using the inner value.  A leaf is exported only when
    an own or inherited evidence id resolves against the result's evidence list
    and the value is not a missing placeholder.  Generated identifiers,
    provenance sub-fields and synthetic values without evidence are excluded.
    Zero and ``0.00`` are valid and kept.  Indexes in the path are stable, so
    multiple events/components map to distinct columns.
    """
    evidence_ids = {
        str(item.get("evidence_id"))
        for item in (result.get("evidence") or ())
        if isinstance(item, Mapping) and item.get("evidence_id")
    }
    values: dict[str, str] = {}

    def backed(ids: tuple[str, ...]) -> bool:
        return bool(ids) and any(item in evidence_ids for item in ids)

    def walk(current: Any, path: str, inherited: tuple[str, ...]) -> None:
        own = tuple(str(x) for x in current.get("evidence_ids", ())) if isinstance(current, Mapping) else ()
        ids = own or inherited
        if _is_field_value(current):
            inner = current.get("value")
            if backed(ids) and not _is_missing(inner) and not _is_technical_leaf(path, detected=True):
                values[path or "$"] = _scalar_text(inner)
            return
        if isinstance(current, Mapping) and current and not _is_missing(current):
            for key in current:
                if key == "evidence_ids":
                    continue
                if not path and key in _SKIP_ROOTS:
                    continue
                child = current[key]
                if key in {"conflict", "ambiguous"} and child is True:
                    continue
                walk(child, f"{path}.{key}" if path else str(key), ids)
            return
        if isinstance(current, list):
            for index, child in enumerate(current):
                walk(child, f"{path}[{index}]", ids)
            return
        if backed(ids) and not _is_missing(current) and not _is_technical_leaf(path):
            values[path or "$"] = _scalar_text(current)

    walk(result, "", ())
    return values


def _atomic_write_csv(target: Path, fieldnames: list[str], rows: Iterable[Mapping[str, Any]]) -> None:
    """Write a CSV atomically (temp file in the target dir, then replace)."""
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=".batch-", suffix=".tmp", dir=str(target.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8-sig", newline="") as handle:
            # Semikolon + UTF-8-BOM: entspricht den Audit-CSVs und öffnet
            # direkt korrekt in deutschem Excel.
            writer = csv.DictWriter(handle, fieldnames=fieldnames, restval="", delimiter=";")
            writer.writeheader()
            for row in rows:
                writer.writerow(row)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, target)
    finally:
        if os.path.exists(tmp_name):
            try:
                os.unlink(tmp_name)
            except OSError:
                pass


def _description_for(path: str, catalog: Any) -> tuple[str, str]:
    entry = resolve_description(path, catalog)
    description = entry.description
    if "keine weitergehende fachliche Bedeutung definiert" in description:
        return _MISSING_DESCRIPTION, entry.source
    return description, entry.source


def write_fields_description(field_paths: Iterable[str], path: str | Path, catalog: Any = None) -> Path:
    """Write ``fields_description.csv`` next to the batch CSV (no SQLite)."""
    target = Path(path)
    rows = []
    for field_path in field_paths:
        description, source = _description_for(field_path, catalog)
        rows.append({"field_path": field_path, "description": description, "source": source})
    _atomic_write_csv(target, ["field_path", "description", "source"], rows)
    return target


def export_batch_csv(report: Mapping[str, Any], path: str | Path,
                     training_database: str | Path | None = None,
                     catalog: Any = None) -> Path:
    """Export one CSV row per PDF with detected values and optional training.

    Column order: technical metadata, then the deterministic union of detected
    PDF field paths, then training columns at the far right.  Documents without
    training data leave those cells empty.  A missing/unreadable training
    database only adds a warning; the PDF CSV is still written.
    """
    target = Path(path)
    files = list(report.get("files", []))

    pdf_values: list[dict[str, str]] = []
    all_paths: set[str] = set()
    for item in files:
        result = item.get("result") if isinstance(item.get("result"), Mapping) else {}
        values = flatten_evidence_values(result) if result else {}
        pdf_values.append(values)
        all_paths.update(values.keys())
    pdf_fields = sorted(all_paths)

    with TrainingExportReader(training_database) as reader:
        training_by_index = [reader.for_report(item) for item in files]
        warning = reader.warning
    max_training = max((len(items) for items in training_by_index), default=0)
    training_fields = training_columns([{} for _ in range(max_training)])

    fieldnames = [*BASE_FIELDS, *pdf_fields, *training_fields]
    rows: list[dict[str, Any]] = []
    for item, values, training in zip(files, pdf_values, training_by_index):
        detection = item.get("detection") if isinstance(item.get("detection"), Mapping) else {}
        status = "DUPLICATE" if item.get("duplicate_of") else "ERROR" if item.get("error") else "OK"
        timings = item.get("timings") if isinstance(item.get("timings"), Mapping) else {}
        row: dict[str, Any] = {
            "source": item.get("source", ""),
            "source_hash": item.get("source_hash", ""),
            "plugin_id": detection.get("plugin_id", ""),
            "handler_id": detection.get("handler_id", ""),
            "document_type": detection.get("document_type", ""),
            "status": status,
            "runtime_ns": timings.get("total_ns", ""),
        }
        row.update(values)
        row.update(training_values(training))
        rows.append(row)

    _atomic_write_csv(target, fieldnames, rows)
    write_fields_description(pdf_fields, target.parent / "fields_description.csv", catalog)

    if warning:
        report.setdefault("warnings", []).append(warning)
    return target
