"""Transactional, versioned SQLite repository for parser evidence and reviews."""

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Iterator

from portman_pdf_lab.reviews.models import ReviewStatus

SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class RunComparison:
    left_run_id: int
    right_run_id: int
    added: tuple[str, ...]
    removed: tuple[str, ...]
    changed: tuple[str, ...]
    critical_cashflow_changes: tuple[str, ...]
    runtime_delta_ns: int


def _flatten(value, prefix=""):
    if isinstance(value, dict):
        for key in sorted(value):
            yield from _flatten(value[key], f"{prefix}.{key}" if prefix else str(key))
    elif isinstance(value, list):
        # Stable economic lists are compared by stable IDs when present.
        identities = ("event_id", "movement_id", "fee_id", "tax_event_id", "snapshot_id", "position_id")
        if all(isinstance(item, dict) for item in value):
            identity = next((name for name in identities if all(name in item for item in value)), None)
            if identity:
                for item in sorted(value, key=lambda row: str(row[identity])):
                    yield from _flatten(item, f"{prefix}[{item[identity]}]")
                return
        for index, item in enumerate(value):
            yield from _flatten(item, f"{prefix}[{index}]")
    else:
        yield prefix, value


class ReferenceRepository:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._migrate()

    def _connect(self):
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _migrate(self):
        with self.transaction() as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version > SCHEMA_VERSION:
                raise RuntimeError("repository schema is newer than this application")
            if version == 0:
                db.executescript("""
                CREATE TABLE documents(
                    document_id TEXT PRIMARY KEY, sha256 TEXT NOT NULL UNIQUE, file_ref TEXT,
                    bank TEXT, document_type TEXT, created_at TEXT NOT NULL
                );
                CREATE TABLE parser_runs(
                    run_id INTEGER PRIMARY KEY AUTOINCREMENT, document_id TEXT NOT NULL,
                    plugin_id TEXT NOT NULL, handler_id TEXT NOT NULL, parser_version TEXT NOT NULL,
                    result_version TEXT NOT NULL, result_json TEXT NOT NULL, issues_json TEXT NOT NULL,
                    runtime_ns INTEGER NOT NULL, created_at TEXT NOT NULL,
                    FOREIGN KEY(document_id) REFERENCES documents(document_id)
                );
                CREATE TABLE reference_values(
                    document_id TEXT NOT NULL, field_path TEXT NOT NULL, expected_json TEXT NOT NULL,
                    severity TEXT NOT NULL, updated_at TEXT NOT NULL, updated_by TEXT NOT NULL,
                    PRIMARY KEY(document_id, field_path),
                    FOREIGN KEY(document_id) REFERENCES documents(document_id)
                );
                CREATE TABLE reference_history(
                    history_id INTEGER PRIMARY KEY AUTOINCREMENT, document_id TEXT NOT NULL,
                    field_path TEXT NOT NULL, old_json TEXT, new_json TEXT NOT NULL,
                    changed_at TEXT NOT NULL, changed_by TEXT NOT NULL, reason TEXT NOT NULL
                );
                CREATE TABLE reviews(
                    review_id INTEGER PRIMARY KEY AUTOINCREMENT, run_id INTEGER NOT NULL,
                    category TEXT NOT NULL, status TEXT NOT NULL, reviewer TEXT NOT NULL,
                    reason TEXT NOT NULL, decided_at TEXT NOT NULL,
                    FOREIGN KEY(run_id) REFERENCES parser_runs(run_id)
                );
                CREATE INDEX idx_runs_document ON parser_runs(document_id, run_id);
                CREATE INDEX idx_reviews_run ON reviews(run_id, review_id);
                PRAGMA user_version=1;
                """)

    def register_document(self, document_id: str, sha256: str, file_ref: str | None,
                          bank: str, document_type: str) -> str:
        now = datetime.now(timezone.utc).isoformat()
        with self.transaction() as db:
            existing = db.execute("SELECT document_id FROM documents WHERE sha256=?", (sha256,)).fetchone()
            if existing:
                return existing[0]
            db.execute("INSERT INTO documents VALUES(?,?,?,?,?,?)",
                       (document_id, sha256, file_ref, bank, document_type, now))
        return document_id

    def save_run(self, document_id: str, plugin_id: str, handler_id: str,
                 parser_version: str, result_version: str, result: dict,
                 issues: list | tuple, runtime_ns: int) -> int:
        now = datetime.now(timezone.utc).isoformat()
        with self.transaction() as db:
            cursor = db.execute(
                "INSERT INTO parser_runs(document_id,plugin_id,handler_id,parser_version,result_version,result_json,issues_json,runtime_ns,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                (document_id, plugin_id, handler_id, parser_version, result_version,
                 json.dumps(result, ensure_ascii=False, sort_keys=True),
                 json.dumps(issues, ensure_ascii=False, sort_keys=True), runtime_ns, now))
            return int(cursor.lastrowid)

    def run(self, run_id: int) -> dict:
        with self._connect() as db:
            row = db.execute("SELECT * FROM parser_runs WHERE run_id=?", (run_id,)).fetchone()
        if not row:
            raise KeyError(run_id)
        value = dict(row); value["result"] = json.loads(value.pop("result_json")); value["issues"] = json.loads(value.pop("issues_json"))
        return value

    def runs_for_document(self, document_id: str) -> tuple[dict, ...]:
        with self._connect() as db:
            ids = [row[0] for row in db.execute("SELECT run_id FROM parser_runs WHERE document_id=? ORDER BY run_id", (document_id,))]
        return tuple(self.run(item) for item in ids)

    def set_reference(self, document_id: str, field_path: str, expected, reviewer: str,
                      reason: str, severity: str = "ERROR"):
        now = datetime.now(timezone.utc).isoformat(); encoded = json.dumps(expected, ensure_ascii=False, sort_keys=True)
        with self.transaction() as db:
            previous = db.execute("SELECT expected_json FROM reference_values WHERE document_id=? AND field_path=?",
                                  (document_id, field_path)).fetchone()
            db.execute("INSERT INTO reference_history(document_id,field_path,old_json,new_json,changed_at,changed_by,reason) VALUES(?,?,?,?,?,?,?)",
                       (document_id, field_path, previous[0] if previous else None, encoded, now, reviewer, reason))
            db.execute("INSERT INTO reference_values VALUES(?,?,?,?,?,?) ON CONFLICT(document_id,field_path) DO UPDATE SET expected_json=excluded.expected_json,severity=excluded.severity,updated_at=excluded.updated_at,updated_by=excluded.updated_by",
                       (document_id, field_path, encoded, severity, now, reviewer))

    def reference_history(self, document_id: str, field_path: str) -> tuple[dict, ...]:
        with self._connect() as db:
            rows = db.execute("SELECT * FROM reference_history WHERE document_id=? AND field_path=? ORDER BY history_id",
                              (document_id, field_path)).fetchall()
        return tuple(dict(row) for row in rows)

    def review(self, run_id: int, category: str, status: ReviewStatus, reviewer: str, reason: str):
        with self.transaction() as db:
            db.execute("INSERT INTO reviews(run_id,category,status,reviewer,reason,decided_at) VALUES(?,?,?,?,?,?)",
                       (run_id, category, status.value, reviewer, reason, datetime.now(timezone.utc).isoformat()))

    def compare_runs(self, left_run_id: int, right_run_id: int) -> RunComparison:
        left, right = self.run(left_run_id), self.run(right_run_id)
        a, b = dict(_flatten(left["result"])), dict(_flatten(right["result"]))
        added = tuple(sorted(b.keys() - a.keys())); removed = tuple(sorted(a.keys() - b.keys()))
        changed = tuple(sorted(key for key in a.keys() & b.keys() if a[key] != b[key]))
        critical = tuple(key for key in changed + added + removed
                         if any(token in key.lower() for token in ("cash_movements", "amount", "currency")))
        return RunComparison(left_run_id, right_run_id, added, removed, changed, critical,
                             right["runtime_ns"] - left["runtime_ns"])

    def reference_comparison(self, run_id: int) -> tuple[dict, ...]:
        run = self.run(run_id); actual = dict(_flatten(run["result"]))
        with self._connect() as db:
            rows = db.execute("SELECT * FROM reference_values WHERE document_id=? ORDER BY field_path",
                              (run["document_id"],)).fetchall()
        return tuple({"field": row["field_path"], "expected": json.loads(row["expected_json"]),
                      "actual": actual.get(row["field_path"]), "severity": row["severity"],
                      "matches": actual.get(row["field_path"]) == json.loads(row["expected_json"])} for row in rows)

    def export(self, path: str | Path):
        with self._connect() as db:
            payload = {table: [dict(row) for row in db.execute(f"SELECT * FROM {table}")]
                       for table in ("documents", "parser_runs", "reference_values", "reference_history", "reviews")}
        target = Path(path); target.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")
        return target
