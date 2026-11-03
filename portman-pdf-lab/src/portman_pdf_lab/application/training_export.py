"""Read-only enrichment of PDF batch CSV rows with stored training data.

This module intentionally does not use :class:`ReferenceRepository`: its
constructor performs migrations and therefore is unsuitable for an export
which must never write to the training database.
"""

from __future__ import annotations

from collections import defaultdict
import json
from pathlib import Path
import sqlite3
from typing import Any, Mapping


TRAINING_FIELDS = (
    "field_path",
    "reference_value",
    "corrected_value",
    "status",
    "source",
)


def _json(value: Any) -> Any:
    if value is None:
        return None
    try:
        return json.loads(value) if isinstance(value, str) else value
    except (TypeError, ValueError):
        return value


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return str(value)


def _parser_matches(row: Mapping[str, Any], plugin_id: str, handler_id: str) -> bool:
    row_plugin = str(row.get("plugin_id") or row.get("parser_id") or "")
    row_handler = str(row.get("handler_id") or "")
    return row_plugin == plugin_id and row_handler == handler_id


def _read_only_connection(path: Path) -> sqlite3.Connection:
    # URI mode=ro is important: sqlite3.connect(path) can create a missing DB.
    connection = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    return connection


def _empty() -> dict[str, list[dict[str, str]]]:
    return defaultdict(list)


class TrainingExportReader:
    """Read existing references, annotations and golden data without writes."""

    def __init__(self, database: str | Path | None):
        self.path = Path(database) if database else None
        self.warning = ""
        self._db: sqlite3.Connection | None = None
        self._by_document_parser: dict[tuple[str, str, str], list[dict[str, str]]] = {}
        if self.path is None:
            self.warning = "Keine Trainingsdatenbank angegeben; Trainingsspalten bleiben leer."
            return
        if not self.path.exists():
            self.warning = f"Trainingsdatenbank nicht gefunden: {self.path}"
            return
        try:
            self._db = _read_only_connection(self.path)
            self._load()
        except (OSError, sqlite3.Error) as exc:
            self.warning = f"Trainingsdatenbank nicht lesbar: {exc}"
            if self._db is not None:
                self._db.close()
                self._db = None

    @property
    def available(self) -> bool:
        return self._db is not None

    def close(self) -> None:
        if self._db is not None:
            self._db.close()
            self._db = None

    def __enter__(self) -> "TrainingExportReader":
        return self

    def __exit__(self, *_args) -> None:
        self.close()

    def _load(self) -> None:
        assert self._db is not None
        documents = {
            str(row["document_id"]): str(row["sha256"])
            for row in self._db.execute("SELECT document_id, sha256 FROM documents")
        }
        parsers = {
            str(row["document_id"]): (str(row["plugin_id"]), str(row["handler_id"]))
            for row in self._db.execute(
                """SELECT p.document_id, p.plugin_id, p.handler_id
                   FROM parser_runs p
                   JOIN (SELECT document_id, MAX(run_id) AS run_id
                         FROM parser_runs GROUP BY document_id) latest
                     ON latest.run_id = p.run_id"""
            )
        }
        references = self._query_optional(
            """SELECT document_id, field_path, expected_json, severity
               FROM reference_values ORDER BY document_id, field_path"""
        )
        annotations = self._query_optional(
            """SELECT document_id, parser_id, handler_id, field_path,
                      reference_json, annotation_kind, decision, review_status,
                      annotation_id
               FROM annotations
               WHERE active=1
               ORDER BY document_id, field_path, annotation_id"""
        )
        golden = self._query_optional(
            """SELECT document_id, handler_id, parser_version,
                      expectations_json, status, golden_id
               FROM golden_tests
               ORDER BY document_id, golden_id"""
        )

        grouped: dict[tuple[str, str, str], list[dict[str, str]]] = defaultdict(list)
        for row in references:
            self._append_reference(grouped, row, documents, parsers)
        for row in annotations:
            self._append_annotation(grouped, row, documents, parsers)
        for row in golden:
            self._append_golden(grouped, row, documents, parsers)
        self._by_document_parser = dict(grouped)

    def _query_optional(self, query: str) -> list[sqlite3.Row]:
        assert self._db is not None
        try:
            return list(self._db.execute(query))
        except sqlite3.Error:
            # Older/partial databases may not have every artifact table. This
            # is a read-only export and should still produce the PDF CSV.
            return []

    @staticmethod
    def _key(document_id: str, plugin_id: str, handler_id: str) -> tuple[str, str, str]:
        return document_id, plugin_id, handler_id

    def _append_reference(self, grouped, row, documents, parsers) -> None:
        document_id = str(row["document_id"])
        plugin_id, handler_id = parsers.get(document_id, ("", ""))
        if not documents.get(document_id) or not plugin_id or not handler_id:
            return
        grouped[self._key(document_id, plugin_id, handler_id)].append({
            "field_path": str(row["field_path"]),
            "reference_value": _text(_json(row["expected_json"])),
            "corrected_value": "",
            "status": "REFERENCE",
            "source": "reference_values",
        })

    def _append_annotation(self, grouped, row, documents, parsers) -> None:
        document_id = str(row["document_id"])
        plugin_id, handler_id = str(row["parser_id"]), str(row["handler_id"])
        if not documents.get(document_id) or not plugin_id or not handler_id:
            return
        if parsers.get(document_id) != (plugin_id, handler_id):
            return
        reference = _text(_json(row["reference_json"]))
        decision = str(row["decision"] or row["review_status"] or row["annotation_kind"] or "ANNOTATION")
        grouped[self._key(document_id, plugin_id, handler_id)].append({
            "field_path": str(row["field_path"]),
            "reference_value": reference,
            "corrected_value": reference if decision.upper() in {"CORRECTED", "CONFIRMED"} else "",
            "status": decision,
            "source": "annotations",
        })

    def _append_golden(self, grouped, row, documents, parsers) -> None:
        document_id = str(row["document_id"])
        plugin_id, current_handler = parsers.get(document_id, ("", ""))
        handler_id = str(row["handler_id"])
        if not documents.get(document_id) or not plugin_id or current_handler != handler_id:
            return
        expectations = _json(row["expectations_json"])
        if not isinstance(expectations, Mapping):
            return
        for field_path in sorted(expectations):
            grouped[self._key(document_id, plugin_id, handler_id)].append({
                "field_path": str(field_path),
                "reference_value": _text(expectations[field_path]),
                "corrected_value": "",
                "status": str(row["status"] or "GOLDEN"),
                "source": "golden_tests",
            })

    def for_report(self, report: Mapping[str, Any]) -> list[dict[str, str]]:
        document_id = str(report.get("document_id") or "")
        detection = report.get("detection") if isinstance(report.get("detection"), Mapping) else {}
        plugin_id = str(detection.get("plugin_id") or "")
        handler_id = str(detection.get("handler_id") or "")
        if not document_id or not plugin_id or not handler_id:
            return []
        # document_id is the primary key. source_hash is deliberately checked
        # when a stored document is available, preventing path-only matches.
        if self._db is not None:
            row = self._db.execute(
                "SELECT sha256 FROM documents WHERE document_id=?", (document_id,)
            ).fetchone()
            if row is None or (report.get("source_hash") and str(row[0]) != str(report["source_hash"])):
                return []
        return list(self._by_document_parser.get(self._key(document_id, plugin_id, handler_id), ()))


def training_columns(items: list[Mapping[str, Any]]) -> list[str]:
    return [f"training[{index}].{field}" for index in range(len(items)) for field in TRAINING_FIELDS]


def training_values(items: list[Mapping[str, Any]]) -> dict[str, str]:
    result: dict[str, str] = {}
    for index, item in enumerate(items):
        for field in TRAINING_FIELDS:
            result[f"training[{index}].{field}"] = _text(item.get(field))
    return result
