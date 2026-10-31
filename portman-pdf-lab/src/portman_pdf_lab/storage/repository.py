"""Transactional, versioned SQLite repository for parser evidence and reviews."""

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Iterator

from portman_pdf_lab.reviews.models import ReviewStatus

SCHEMA_VERSION = 3


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
                version = 1
            if version == 1:
                db.executescript("""
                CREATE TABLE annotations(
                    annotation_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    document_id TEXT NOT NULL, parser_id TEXT NOT NULL, handler_id TEXT NOT NULL,
                    page_number INTEGER NOT NULL, original_text TEXT NOT NULL, field_path TEXT NOT NULL,
                    reference_json TEXT, annotation_kind TEXT NOT NULL, decision TEXT NOT NULL,
                    review_status TEXT NOT NULL, coordinates_json TEXT, created_at TEXT NOT NULL,
                    created_by TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1,
                    FOREIGN KEY(document_id) REFERENCES documents(document_id)
                );
                CREATE TABLE annotation_history(
                    history_id INTEGER PRIMARY KEY AUTOINCREMENT, annotation_id INTEGER NOT NULL,
                    snapshot_json TEXT NOT NULL, changed_at TEXT NOT NULL, changed_by TEXT NOT NULL,
                    reason TEXT NOT NULL, FOREIGN KEY(annotation_id) REFERENCES annotations(annotation_id)
                );
                CREATE TABLE golden_tests(
                    golden_id INTEGER PRIMARY KEY AUTOINCREMENT, document_id TEXT NOT NULL,
                    bank TEXT NOT NULL, handler_id TEXT NOT NULL, layout_variant TEXT NOT NULL,
                    parser_version TEXT NOT NULL, expectations_json TEXT NOT NULL,
                    status TEXT NOT NULL, version INTEGER NOT NULL, created_at TEXT NOT NULL,
                    created_by TEXT NOT NULL, supersedes_id INTEGER,
                    FOREIGN KEY(document_id) REFERENCES documents(document_id),
                    FOREIGN KEY(supersedes_id) REFERENCES golden_tests(golden_id)
                );
                CREATE TABLE golden_history(
                    history_id INTEGER PRIMARY KEY AUTOINCREMENT, golden_id INTEGER NOT NULL,
                    snapshot_json TEXT NOT NULL, changed_at TEXT NOT NULL, changed_by TEXT NOT NULL,
                    reason TEXT NOT NULL, FOREIGN KEY(golden_id) REFERENCES golden_tests(golden_id)
                );
                CREATE TABLE rule_candidates(
                    candidate_id INTEGER PRIMARY KEY AUTOINCREMENT, document_id TEXT NOT NULL,
                    parser_id TEXT NOT NULL, handler_id TEXT NOT NULL, rule_json TEXT NOT NULL,
                    annotation_ids_json TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL,
                    created_by TEXT NOT NULL, FOREIGN KEY(document_id) REFERENCES documents(document_id)
                );
                CREATE TABLE rule_tests(
                    test_id INTEGER PRIMARY KEY AUTOINCREMENT, candidate_id INTEGER NOT NULL,
                    result_json TEXT NOT NULL, tested_at TEXT NOT NULL, tested_by TEXT NOT NULL,
                    FOREIGN KEY(candidate_id) REFERENCES rule_candidates(candidate_id)
                );
                CREATE TABLE rule_versions(
                    version_id INTEGER PRIMARY KEY AUTOINCREMENT, parser_id TEXT NOT NULL,
                    handler_id TEXT NOT NULL, profile_version INTEGER NOT NULL, rules_json TEXT NOT NULL,
                    status TEXT NOT NULL, created_at TEXT NOT NULL, created_by TEXT NOT NULL,
                    candidate_id INTEGER, predecessor_id INTEGER,
                    FOREIGN KEY(candidate_id) REFERENCES rule_candidates(candidate_id),
                    FOREIGN KEY(predecessor_id) REFERENCES rule_versions(version_id),
                    UNIQUE(parser_id, handler_id, profile_version)
                );
                CREATE TABLE release_decisions(
                    decision_id INTEGER PRIMARY KEY AUTOINCREMENT, candidate_id INTEGER NOT NULL,
                    version_id INTEGER, status TEXT NOT NULL, decided_at TEXT NOT NULL,
                    decided_by TEXT NOT NULL, reason TEXT NOT NULL,
                    FOREIGN KEY(candidate_id) REFERENCES rule_candidates(candidate_id),
                    FOREIGN KEY(version_id) REFERENCES rule_versions(version_id)
                );
                CREATE TABLE training_history(
                    history_id INTEGER PRIMARY KEY AUTOINCREMENT, document_id TEXT,
                    action TEXT NOT NULL, detail_json TEXT NOT NULL, created_at TEXT NOT NULL,
                    created_by TEXT NOT NULL, FOREIGN KEY(document_id) REFERENCES documents(document_id)
                );
                CREATE INDEX idx_annotations_document ON annotations(document_id, field_path, active);
                CREATE INDEX idx_golden_document ON golden_tests(document_id, status, version);
                CREATE INDEX idx_candidates_parser ON rule_candidates(parser_id, handler_id, status);
                CREATE INDEX idx_rule_tests_candidate ON rule_tests(candidate_id, test_id);
                PRAGMA user_version=2;
                """)
                version = 2
            if version == 2:
                db.executescript("""
                CREATE TABLE profile_activations(
                    activation_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    parser_id TEXT NOT NULL, handler_id TEXT NOT NULL, document_type TEXT NOT NULL,
                    layout_variant TEXT NOT NULL, version_id INTEGER, profile_id TEXT NOT NULL,
                    profile_version INTEGER NOT NULL, profile_hash TEXT NOT NULL, active INTEGER NOT NULL,
                    decided_at TEXT NOT NULL, decided_by TEXT NOT NULL,
                    FOREIGN KEY(version_id) REFERENCES rule_versions(version_id)
                );
                CREATE TABLE comparison_results(
                    comparison_id INTEGER PRIMARY KEY AUTOINCREMENT, document_id TEXT,
                    left_variant TEXT NOT NULL, right_variant TEXT NOT NULL, result_json TEXT NOT NULL,
                    created_at TEXT NOT NULL, created_by TEXT NOT NULL,
                    FOREIGN KEY(document_id) REFERENCES documents(document_id)
                );
                CREATE INDEX idx_profile_activation ON profile_activations(parser_id,handler_id,document_type,layout_variant,active);
                CREATE INDEX idx_comparison_document ON comparison_results(document_id,comparison_id);
                PRAGMA user_version=3;
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

    def document(self, document_id: str) -> dict:
        with self._connect() as db: row = db.execute("SELECT * FROM documents WHERE document_id=?", (document_id,)).fetchone()
        if not row: raise KeyError(document_id)
        return dict(row)

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
                       for table in ("documents", "parser_runs", "reference_values", "reference_history", "reviews",
                                     "annotations", "annotation_history", "golden_tests", "golden_history",
                                     "rule_candidates", "rule_tests", "rule_versions", "release_decisions",
                                     "training_history", "profile_activations", "comparison_results")}
        target = Path(path); target.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")
        return target

    @staticmethod
    def _now():
        return datetime.now(timezone.utc).isoformat()

    def create_annotation(self, document_id: str, parser_id: str, handler_id: str,
                          page_number: int, original_text: str, field_path: str, reference_value,
                          annotation_kind: str, decision: str, review_status: str,
                          created_by: str, coordinates=None) -> int:
        if page_number < 1 or not field_path or not original_text and annotation_kind not in {"MISSING", "NOT_APPLICABLE"}:
            raise ValueError("annotation requires page, field and source text unless explicitly missing")
        now = self._now(); reference = json.dumps(reference_value, ensure_ascii=False, sort_keys=True)
        coords = json.dumps(coordinates, ensure_ascii=False, sort_keys=True) if coordinates is not None else None
        with self.transaction() as db:
            cursor = db.execute("""INSERT INTO annotations(document_id,parser_id,handler_id,page_number,original_text,
                field_path,reference_json,annotation_kind,decision,review_status,coordinates_json,created_at,created_by)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (document_id, parser_id, handler_id, page_number, original_text, field_path, reference,
                 annotation_kind, decision, review_status, coords, now, created_by))
            annotation_id = int(cursor.lastrowid)
            row = dict(db.execute("SELECT * FROM annotations WHERE annotation_id=?", (annotation_id,)).fetchone())
            db.execute("INSERT INTO annotation_history(annotation_id,snapshot_json,changed_at,changed_by,reason) VALUES(?,?,?,?,?)",
                       (annotation_id, json.dumps(row, ensure_ascii=False, sort_keys=True), now, created_by, "created"))
        return annotation_id

    def annotation(self, annotation_id: int) -> dict:
        with self._connect() as db:
            row = db.execute("SELECT * FROM annotations WHERE annotation_id=?", (annotation_id,)).fetchone()
        if not row: raise KeyError(annotation_id)
        value = dict(row); value["reference_value"] = json.loads(value.pop("reference_json"))
        value["coordinates"] = json.loads(value.pop("coordinates_json")) if value["coordinates_json"] else None
        return value

    def update_annotation(self, annotation_id: int, reference_value, decision: str,
                          review_status: str, changed_by: str, reason: str) -> None:
        now = self._now()
        with self.transaction() as db:
            before = db.execute("SELECT * FROM annotations WHERE annotation_id=?", (annotation_id,)).fetchone()
            if not before: raise KeyError(annotation_id)
            db.execute("UPDATE annotations SET reference_json=?,decision=?,review_status=? WHERE annotation_id=?",
                       (json.dumps(reference_value, ensure_ascii=False, sort_keys=True), decision, review_status, annotation_id))
            after = dict(db.execute("SELECT * FROM annotations WHERE annotation_id=?", (annotation_id,)).fetchone())
            db.execute("INSERT INTO annotation_history(annotation_id,snapshot_json,changed_at,changed_by,reason) VALUES(?,?,?,?,?)",
                       (annotation_id, json.dumps(after, ensure_ascii=False, sort_keys=True), now, changed_by, reason))

    def deactivate_annotation(self, annotation_id: int, changed_by: str, reason: str) -> None:
        now = self._now()
        with self.transaction() as db:
            before = db.execute("SELECT * FROM annotations WHERE annotation_id=?", (annotation_id,)).fetchone()
            if not before: raise KeyError(annotation_id)
            db.execute("UPDATE annotations SET active=0 WHERE annotation_id=?", (annotation_id,))
            after = dict(db.execute("SELECT * FROM annotations WHERE annotation_id=?", (annotation_id,)).fetchone())
            db.execute("INSERT INTO annotation_history(annotation_id,snapshot_json,changed_at,changed_by,reason) VALUES(?,?,?,?,?)",
                       (annotation_id, json.dumps(after, ensure_ascii=False, sort_keys=True), now, changed_by, reason))

    def annotations_for_document(self, document_id: str) -> tuple[dict, ...]:
        with self._connect() as db:
            ids = [row[0] for row in db.execute("SELECT annotation_id FROM annotations WHERE document_id=? AND active=1 ORDER BY annotation_id", (document_id,))]
        return tuple(self.annotation(item) for item in ids)

    def create_golden(self, document_id: str, bank: str, handler_id: str, layout_variant: str,
                      parser_version: str, expectations: dict, created_by: str, status="DRAFT",
                      supersedes_id=None) -> int:
        now = self._now()
        with self.transaction() as db:
            version = db.execute("SELECT COALESCE(MAX(version),0)+1 FROM golden_tests WHERE document_id=? AND handler_id=?",
                                 (document_id, handler_id)).fetchone()[0]
            cursor = db.execute("INSERT INTO golden_tests(document_id,bank,handler_id,layout_variant,parser_version,expectations_json,status,version,created_at,created_by,supersedes_id) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                                (document_id, bank, handler_id, layout_variant, parser_version,
                                 json.dumps(expectations, ensure_ascii=False, sort_keys=True), status, version, now, created_by, supersedes_id))
            golden_id = int(cursor.lastrowid)
            snapshot = dict(db.execute("SELECT * FROM golden_tests WHERE golden_id=?", (golden_id,)).fetchone())
            db.execute("INSERT INTO golden_history(golden_id,snapshot_json,changed_at,changed_by,reason) VALUES(?,?,?,?,?)",
                       (golden_id, json.dumps(snapshot, ensure_ascii=False, sort_keys=True), now, created_by, "created"))
        return golden_id

    def golden(self, golden_id: int) -> dict:
        with self._connect() as db: row = db.execute("SELECT * FROM golden_tests WHERE golden_id=?", (golden_id,)).fetchone()
        if not row: raise KeyError(golden_id)
        value = dict(row); value["expectations"] = json.loads(value.pop("expectations_json")); return value

    def decide_golden(self, golden_id: int, status: str, user: str, reason: str) -> None:
        if status not in {"DRAFT", "APPROVED", "REJECTED", "SUPERSEDED"}: raise ValueError(status)
        now = self._now()
        with self.transaction() as db:
            db.execute("UPDATE golden_tests SET status=? WHERE golden_id=?", (status, golden_id))
            row = db.execute("SELECT * FROM golden_tests WHERE golden_id=?", (golden_id,)).fetchone()
            if not row: raise KeyError(golden_id)
            db.execute("INSERT INTO golden_history(golden_id,snapshot_json,changed_at,changed_by,reason) VALUES(?,?,?,?,?)",
                       (golden_id, json.dumps(dict(row), ensure_ascii=False, sort_keys=True), now, user, reason))

    def create_rule_candidate(self, document_id: str, parser_id: str, handler_id: str, rule: dict,
                              annotation_ids, created_by: str) -> int:
        with self.transaction() as db:
            cursor = db.execute("INSERT INTO rule_candidates(document_id,parser_id,handler_id,rule_json,annotation_ids_json,status,created_at,created_by) VALUES(?,?,?,?,?,?,?,?)",
                                (document_id, parser_id, handler_id, json.dumps(rule, ensure_ascii=False, sort_keys=True),
                                 json.dumps(list(annotation_ids)), "DRAFT", self._now(), created_by))
            return int(cursor.lastrowid)

    def rule_candidate(self, candidate_id: int) -> dict:
        with self._connect() as db: row = db.execute("SELECT * FROM rule_candidates WHERE candidate_id=?", (candidate_id,)).fetchone()
        if not row: raise KeyError(candidate_id)
        value = dict(row); value["rule"] = json.loads(value.pop("rule_json")); value["annotation_ids"] = json.loads(value.pop("annotation_ids_json")); return value

    def save_rule_test(self, candidate_id: int, result: dict, tested_by: str) -> int:
        with self.transaction() as db:
            cursor = db.execute("INSERT INTO rule_tests(candidate_id,result_json,tested_at,tested_by) VALUES(?,?,?,?)",
                                (candidate_id, json.dumps(result, ensure_ascii=False, sort_keys=True), self._now(), tested_by))
            db.execute("UPDATE rule_candidates SET status='TESTED' WHERE candidate_id=?", (candidate_id,))
            return int(cursor.lastrowid)

    def latest_rule_test(self, candidate_id: int) -> dict | None:
        with self._connect() as db: row = db.execute("SELECT * FROM rule_tests WHERE candidate_id=? ORDER BY test_id DESC LIMIT 1", (candidate_id,)).fetchone()
        if not row: return None
        value = dict(row); value["result"] = json.loads(value.pop("result_json")); return value

    def decide_rule_candidate(self, candidate_id: int, status, user: str, reason: str, version_id=None) -> None:
        status_value = getattr(status, "value", status)
        if status_value not in {"DRAFT", "TESTED", "APPROVED", "REJECTED", "SUPERSEDED"}: raise ValueError(status_value)
        with self.transaction() as db:
            db.execute("UPDATE rule_candidates SET status=? WHERE candidate_id=?", (status_value, candidate_id))
            db.execute("INSERT INTO release_decisions(candidate_id,version_id,status,decided_at,decided_by,reason) VALUES(?,?,?,?,?,?)",
                       (candidate_id, version_id, status_value, self._now(), user, reason))

    def approve_rule_candidate(self, candidate_id: int, user: str, reason: str) -> int:
        candidate = self.rule_candidate(candidate_id)
        with self.transaction() as db:
            predecessor = db.execute("SELECT version_id,rules_json FROM rule_versions WHERE parser_id=? AND handler_id=? AND status='APPROVED' ORDER BY profile_version DESC LIMIT 1",
                                     (candidate["parser_id"], candidate["handler_id"])).fetchone()
            rules = json.loads(predecessor["rules_json"]) if predecessor else []
            rules.append(candidate["rule"])
            profile = db.execute("SELECT COALESCE(MAX(profile_version),0)+1 FROM rule_versions WHERE parser_id=? AND handler_id=?",
                                 (candidate["parser_id"], candidate["handler_id"])).fetchone()[0]
            if predecessor: db.execute("UPDATE rule_versions SET status='SUPERSEDED' WHERE version_id=?", (predecessor["version_id"],))
            cursor = db.execute("INSERT INTO rule_versions(parser_id,handler_id,profile_version,rules_json,status,created_at,created_by,candidate_id,predecessor_id) VALUES(?,?,?,?,?,?,?,?,?)",
                                (candidate["parser_id"], candidate["handler_id"], profile, json.dumps(rules, ensure_ascii=False, sort_keys=True), "APPROVED", self._now(), user, candidate_id, predecessor["version_id"] if predecessor else None))
            version_id = int(cursor.lastrowid)
            db.execute("UPDATE rule_candidates SET status='APPROVED' WHERE candidate_id=?", (candidate_id,))
            db.execute("INSERT INTO release_decisions(candidate_id,version_id,status,decided_at,decided_by,reason) VALUES(?,?,?,?,?,?)",
                       (candidate_id, version_id, "APPROVED", self._now(), user, reason))
        return version_id

    def rollback_rule_version(self, version_id: int, user: str, reason: str) -> int:
        with self.transaction() as db:
            current = db.execute("SELECT * FROM rule_versions WHERE version_id=?", (version_id,)).fetchone()
            if not current or not current["predecessor_id"]: raise ValueError("no predecessor to restore")
            previous = db.execute("SELECT * FROM rule_versions WHERE version_id=?", (current["predecessor_id"],)).fetchone()
            profile = db.execute("SELECT MAX(profile_version)+1 FROM rule_versions WHERE parser_id=? AND handler_id=?", (current["parser_id"], current["handler_id"])).fetchone()[0]
            db.execute("UPDATE rule_versions SET status='SUPERSEDED' WHERE parser_id=? AND handler_id=? AND status='APPROVED'", (current["parser_id"], current["handler_id"]))
            cursor = db.execute("INSERT INTO rule_versions(parser_id,handler_id,profile_version,rules_json,status,created_at,created_by,predecessor_id) VALUES(?,?,?,?,?,?,?,?)",
                                (current["parser_id"], current["handler_id"], profile, previous["rules_json"], "APPROVED", self._now(), user, version_id))
            restored = int(cursor.lastrowid)
            db.execute("INSERT INTO training_history(document_id,action,detail_json,created_at,created_by) VALUES(NULL,?,?,?,?)",
                       ("RULE_ROLLBACK", json.dumps({"from": version_id, "restored_as": restored, "reason": reason}), self._now(), user))
        return restored

    def rule_version(self, version_id: int) -> dict:
        with self._connect() as db: row = db.execute("SELECT * FROM rule_versions WHERE version_id=?", (version_id,)).fetchone()
        if not row: raise KeyError(version_id)
        value = dict(row); value["rules"] = json.loads(value.pop("rules_json")); return value

    def add_training_history(self, document_id, action: str, user: str, detail: dict) -> int:
        with self.transaction() as db:
            cursor = db.execute("INSERT INTO training_history(document_id,action,detail_json,created_at,created_by) VALUES(?,?,?,?,?)",
                                (document_id, action, json.dumps(detail, ensure_ascii=False, sort_keys=True), self._now(), user))
            return int(cursor.lastrowid)

    def training_metrics(self, parser_id: str) -> dict:
        """Metrics use approved human references only; unknown rates remain None."""
        with self._connect() as db:
            documents = db.execute("SELECT count(DISTINCT document_id) FROM annotations WHERE parser_id=?", (parser_id,)).fetchone()[0]
            confirmed = db.execute("SELECT count(*) FROM annotations WHERE parser_id=? AND review_status='APPROVED'", (parser_id,)).fetchone()[0]
            goldens = db.execute("SELECT count(*) FROM golden_tests WHERE status='APPROVED' AND document_id IN (SELECT document_id FROM annotations WHERE parser_id=?)", (parser_id,)).fetchone()[0]
            missing_evidence = db.execute("SELECT count(*) FROM annotations WHERE parser_id=? AND review_status='APPROVED' AND original_text=''", (parser_id,)).fetchone()[0]
            candidate_ids = [row[0] for row in db.execute("SELECT candidate_id FROM rule_candidates WHERE parser_id=?", (parser_id,))]
            results = []
            for candidate_id in candidate_ids:
                row = db.execute("SELECT result_json FROM rule_tests WHERE candidate_id=? ORDER BY test_id DESC LIMIT 1", (candidate_id,)).fetchone()
                if row: results.append(json.loads(row[0]))
        regressions = sum(item.get("regressions", 0) for item in results)
        cash_errors = sum(bool(item.get("critical_cashflow_regression")) for item in results)
        matched = sum(item.get("improved", 0) for item in results)
        tested = matched + regressions
        return {"documents_checked": documents, "confirmed_references": confirmed,
                "approved_goldens": goldens, "document_detection_rate": None,
                "required_field_accuracy": (matched / tested) if tested else None,
                "optional_field_accuracy": None, "cashflow_errors": cash_errors,
                "tax_errors": None, "fee_errors": None, "security_id_errors": None,
                "missing_evidence": missing_evidence, "regressions": regressions,
                "runtime_per_document_ns": None, "unsupported_layouts": None}

    def record_profile_activation(self, parser_id: str, handler_id: str, document_type: str,
                                  layout_variant: str, version_id: int | None, profile_id: str,
                                  profile_version: int, profile_hash: str, active: bool, user: str) -> int:
        with self.transaction() as db:
            if active:
                db.execute("UPDATE profile_activations SET active=0 WHERE parser_id=? AND handler_id=? AND document_type=? AND layout_variant=? AND active=1",
                           (parser_id, handler_id, document_type, layout_variant))
            cursor = db.execute("INSERT INTO profile_activations(parser_id,handler_id,document_type,layout_variant,version_id,profile_id,profile_version,profile_hash,active,decided_at,decided_by) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                                (parser_id, handler_id, document_type, layout_variant, version_id, profile_id,
                                 profile_version, profile_hash, int(active), self._now(), user))
            return int(cursor.lastrowid)

    def save_comparison_result(self, document_id, left_variant: str, right_variant: str,
                               result: dict, user: str) -> int:
        with self.transaction() as db:
            cursor = db.execute("INSERT INTO comparison_results(document_id,left_variant,right_variant,result_json,created_at,created_by) VALUES(?,?,?,?,?,?)",
                                (document_id, left_variant, right_variant, json.dumps(result, ensure_ascii=False, sort_keys=True), self._now(), user))
            return int(cursor.lastrowid)
