"""Kleine SQLite-Migrations- und Persistenzbasis; kein vollständiger Importservice."""
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
from datetime import datetime
from importlib.resources import files
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
from typing import Iterator
from uuid import uuid4

from portman_v10.domain.rational import RationalAmount
from portman_v10.domain.values import ExactValue, canonical_decimal, sum_decimal_text
from portman_v10.infrastructure.sqlite_decimal import register_decimal_collation, register_rational_collation
from portman_v10.application.contracts import (
    Account, AccountIdentifier, AccountInput, AccountPage, ApplicationError,
    ErrorCode, Instrument, InstrumentIdentifier, InstrumentInput, InstrumentPage,
    OpeningBalance, OpeningBalanceInput, Document, ImportJob, ImportDocumentResult,
)


@dataclass(frozen=True, slots=True)
class EventInput:
    event_id: str
    kind: str
    booking_date: date
    completeness: str = "complete"
    original_text: str | None = None
    trade_date: date | None = None
    value_date: date | None = None
    correction_of_event_id: str | None = None
    revision: int = 1


@dataclass(frozen=True, slots=True)
class PositionInput:
    position_id: str
    account_id: str
    effective_date: date
    currency: str | None = None
    amount: ExactValue | None = None
    instrument_id: str | None = None
    quantity: ExactValue | None = None


@dataclass(frozen=True, slots=True)
class ComponentInput:
    component_id: str
    component_type: str
    amount: ExactValue | None
    currency: str | None


@dataclass(frozen=True, slots=True)
class DocumentInput:
    document_id: str
    sha256: str
    original_name: str
    relative_path: str
    media_type: str | None
    imported_at: str


@dataclass(frozen=True, slots=True)
class EventDocumentInput:
    document_id: str
    source_role: str
    page_or_entry: str | None = None


@dataclass(frozen=True, slots=True)
class ContributionInput:
    contribution_id: str
    source_kind: str
    target_type: str
    target_id: str
    field_name: str
    action: str
    created_at: str
    import_id: str | None = None
    document_id: str | None = None
    previous_value_text: str | None = None
    value_text: str | None = None


@dataclass(frozen=True, slots=True)
class AcquisitionLotInput:
    lot_id: str
    account_id: str
    instrument_id: str
    quantity: ExactValue
    acquired_on: date | None
    original_cost: ExactValue | None
    cost_currency: str | None


@dataclass(frozen=True, slots=True)
class LotAllocationInput:
    position_id: str
    lot_id: str
    source_account_id: str
    destination_account_id: str | None
    quantity: ExactValue
    cost: RationalAmount | None


@dataclass(frozen=True, slots=True)
class PersistedEventInput:
    event: EventInput
    positions: tuple[PositionInput, ...]
    components: tuple[ComponentInput, ...] = ()
    documents: tuple[DocumentInput, ...] = ()
    event_documents: tuple[EventDocumentInput, ...] = ()
    contributions: tuple[ContributionInput, ...] = ()
    lots: tuple[AcquisitionLotInput, ...] = ()
    lot_allocations: tuple[LotAllocationInput, ...] = ()


@dataclass(frozen=True, slots=True)
class StoredPosition:
    position_id: str
    account_id: str
    currency: str | None
    amount: ExactValue | None
    instrument_id: str | None
    quantity: ExactValue | None
    effective_date: date


@dataclass(frozen=True, slots=True)
class StoredComponent:
    component_id: str
    component_type: str
    amount: ExactValue | None
    currency: str | None


@dataclass(frozen=True, slots=True)
class StoredContribution:
    contribution_id: str
    import_id: str | None
    document_id: str | None
    source_kind: str
    target_type: str
    field_name: str
    action: str
    previous_value_text: str | None
    value_text: str | None


@dataclass(frozen=True, slots=True)
class StoredLot:
    lot_id: str
    account_id: str
    instrument_id: str
    quantity: ExactValue
    acquired_on: date | None
    original_cost: ExactValue | None
    cost_currency: str | None


@dataclass(frozen=True, slots=True)
class StoredLotAllocation:
    position_id: str
    lot_id: str
    source_account_id: str
    destination_account_id: str | None
    quantity: ExactValue
    cost: RationalAmount | None


@dataclass(frozen=True, slots=True)
class StoredEvent:
    event: EventInput
    positions: tuple[StoredPosition, ...]
    components: tuple[StoredComponent, ...]
    document_ids: tuple[str, ...]
    contributions: tuple[StoredContribution, ...]
    lots: tuple[StoredLot, ...]
    lot_allocations: tuple[StoredLotAllocation, ...]


class SQLiteStore:
    """Versionierte SQLite-Datei mit schmalen Schreib-/Lesebelegen."""

    def __init__(self, path: str | Path, migrations_dir: str | Path | None = None):
        self.path = Path(path)
        self.migrations_dir = Path(migrations_dir) if migrations_dir else Path(str(files("portman_v10.infrastructure.migrations")))

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.create_function("portman_is_decimal", 1, self._is_canonical_decimal, deterministic=True)
        connection.create_function("portman_is_decimal_positive", 1, self._is_positive_decimal, deterministic=True)
        connection.create_function("portman_is_rational", 1, self._is_canonical_rational, deterministic=True)
        register_decimal_collation(connection)
        register_rational_collation(connection)
        connection.execute("PRAGMA foreign_keys = ON")
        if connection.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
            connection.close()
            raise RuntimeError("SQLite-Fremdschlüssel konnten nicht aktiviert werden")
        return connection

    def _stored_document_path(self, relative_path: str) -> Path:
        relative = Path(relative_path)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("Dokumentpfad muss relativ und innerhalb der V10-Dokumentablage liegen")
        documents_root = (self.path.parent / "documents").resolve()
        candidate = (self.path.parent / relative).resolve()
        try:
            candidate.relative_to(documents_root)
        except ValueError as error:
            raise ValueError("Dokumentpfad verlässt die V10-Dokumentablage") from error
        return candidate

    def register_document(self, *, document_id: str, digest: str, name: str, relative_path: str, media_type: str | None, imported_at: str) -> tuple[Document, bool]:
        """Registriert Metadaten. Rückgabe-Bool besagt, ob die Datei schon bekannt war."""
        with self.transaction() as connection:
            existing = connection.execute("SELECT * FROM documents WHERE sha256 = ?", (digest,)).fetchone()
            if existing is not None:
                size = self._stored_document_path(existing["relative_path"]).stat().st_size
                return Document(existing["document_id"], existing["original_name"], existing["media_type"] or "application/pdf", size, digest), True
            file_path = self._stored_document_path(relative_path)
            if not file_path.is_file():
                raise ValueError("Dokument muss vor den Metadaten atomar abgelegt sein")
            connection.execute("INSERT INTO documents(document_id, sha256, original_name, relative_path, media_type, imported_at) VALUES (?, ?, ?, ?, ?, ?)",
                               (document_id, digest, name, relative_path, media_type, imported_at))
            self._bump_metadata_revision(connection, refresh_index_revision=False)
            return Document(document_id, name, media_type or "application/pdf", file_path.stat().st_size, digest), False

    def find_document_by_hash(self, digest: str) -> Document | None:
        connection = self.connect()
        try:
            row = connection.execute("SELECT * FROM documents WHERE sha256=?", (digest,)).fetchone()
            if row is None:
                return None
            size = self._stored_document_path(row["relative_path"]).stat().st_size
            return Document(row["document_id"], row["original_name"], row["media_type"] or "application/pdf", size, digest)
        finally:
            connection.close()

    def match_account_identifier(self, identifier_type: str, context: str | None, value: str) -> tuple[str, ...]:
        connection = self.connect()
        try:
            return tuple(row[0] for row in connection.execute(
                "SELECT DISTINCT account_id FROM account_identifiers WHERE lower(identifier_type)=lower(?) AND (? IS NULL OR lower(context)=lower(?)) AND value=? ORDER BY account_id",
                (identifier_type, context, context, value)))
        finally:
            connection.close()

    def match_instrument_identifier(self, identifier_type: str, context: str, value: str) -> tuple[str, ...]:
        connection = self.connect()
        try:
            return tuple(row[0] for row in connection.execute(
                "SELECT DISTINCT instrument_id FROM instrument_identifiers WHERE lower(identifier_type)=lower(?) AND lower(context)=lower(?) AND value=? ORDER BY instrument_id",
                (identifier_type, context, value)))
        finally:
            connection.close()

    def account_exists(self, account_id: str) -> bool:
        connection = self.connect()
        try:
            return connection.execute("SELECT 1 FROM accounts WHERE account_id=?", (account_id,)).fetchone() is not None
        finally:
            connection.close()

    def account_kind(self, account_id: str) -> str | None:
        connection = self.connect()
        try:
            row = connection.execute("SELECT kind FROM accounts WHERE account_id=?", (account_id,)).fetchone()
            return row[0] if row else None
        finally:
            connection.close()

    def document_record(self, document_id: str) -> tuple[Document, str] | None:
        connection = self.connect()
        try:
            row = connection.execute("SELECT * FROM documents WHERE document_id = ?", (document_id,)).fetchone()
            if row is None:
                return None
            size = self._stored_document_path(row["relative_path"]).stat().st_size
            return Document(row["document_id"], row["original_name"], row["media_type"] or "application/pdf", size, row["sha256"]), row["relative_path"]
        finally:
            connection.close()

    def create_import_job(self, job: ImportJob, document_ids: tuple[str, ...], account_hint: str | None, parser_version: str, api_version: str, schema_version: str) -> None:
        with self.transaction() as connection:
            connection.execute("INSERT INTO imports(import_id, started_at, status, preview_revision, parser_version, schema_version, parser_api_version) VALUES (?, ?, 'started', 1, ?, ?, ?)",
                               (job.import_id, datetime.now().astimezone().isoformat(), parser_version, schema_version, api_version))
            connection.execute("INSERT INTO import_jobs(job_id, import_id, state, progress, revision, document_count, completed_documents, account_hint, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                               (job.job_id, job.import_id, job.state, job.progress, job.revision, len(document_ids), 0, account_hint, datetime.now().astimezone().isoformat()))
            connection.executemany("INSERT INTO import_documents(import_id, document_id) VALUES (?, ?)", ((job.import_id, item) for item in document_ids))
            connection.executemany("INSERT INTO import_job_documents(job_id, document_id, ordinal, status) VALUES (?, ?, ?, 'queued')", ((job.job_id, item, index) for index, item in enumerate(document_ids)))

    def mark_interrupted_import_jobs(self) -> int:
        with self.transaction() as connection:
            rows = connection.execute("SELECT import_id FROM import_jobs WHERE state IN ('queued', 'running')").fetchall()
            connection.execute("UPDATE import_jobs SET state='failed', error_code='JOB_INTERRUPTED', revision=revision+1, updated_at=? WHERE state IN ('queued', 'running')", (datetime.now().astimezone().isoformat(),))
            connection.execute("UPDATE import_job_documents SET status='failed', error_code='JOB_INTERRUPTED' WHERE status='queued' AND job_id IN (SELECT job_id FROM import_jobs WHERE error_code='JOB_INTERRUPTED' AND state='failed')")
            connection.execute("UPDATE import_job_documents SET status='failed', error_code='JOB_INTERRUPTED' WHERE status='queued' AND job_id IN (SELECT job_id FROM import_jobs WHERE error_code='JOB_INTERRUPTED' AND state='failed')")
            connection.execute("UPDATE imports SET status='failed' WHERE status='started' AND import_id IN (SELECT import_id FROM import_jobs WHERE state='failed' AND error_code='JOB_INTERRUPTED')")
            return len(rows)

    def save_import_progress(self, job: ImportJob, documents: tuple[ImportDocumentResult, ...], preview_json: str | None, data_revision: int) -> None:
        with self.transaction() as connection:
            current = connection.execute("SELECT revision FROM import_jobs WHERE job_id=?", (job.job_id,)).fetchone()
            if current is None:
                raise ApplicationError(ErrorCode.NOT_FOUND, "Importjob nicht gefunden")
            if current[0] != job.revision - 1:
                raise ApplicationError(ErrorCode.STALE_REVISION, "Importjob wurde parallel geändert")
            connection.execute("UPDATE import_jobs SET state=?, progress=?, revision=?, completed_documents=?, cancel_requested=?, error_code=?, updated_at=? WHERE job_id=?",
                               (job.state, job.progress, job.revision, job.completed_documents, int(job.cancel_requested), job.error_code.value if job.error_code else None, datetime.now().astimezone().isoformat(), job.job_id))
            for index, document in enumerate(documents):
                connection.execute("UPDATE import_job_documents SET status=?, document_type=?, plugin_id=?, plugin_version=?, parser_package_version=?, parser_api_version=?, handler_id=?, parser_schema_version=?, extraction_preparation_version=?, warning_messages_json=?, error_code=? WHERE job_id=? AND document_id=?",
                                   (document.status, document.document_type, document.plugin_id, document.plugin_version, document.parser_package_version, document.parser_api_version, document.handler_id, document.parser_schema_version, document.extraction_preparation_version, json.dumps(document.warning_messages, ensure_ascii=False), document.error_code.value if document.error_code else None, job.job_id, document.document_id))
            if job.state == "cancelled":
                connection.execute("UPDATE import_job_documents SET status='cancelled', error_code='CANCELLED' WHERE job_id=? AND status='queued'", (job.job_id,))
            import_status = "preview" if job.state == "needs_review" else job.state if job.state in {"failed", "cancelled", "completed"} else "started"
            connection.execute("UPDATE imports SET status=?, preview_revision=? WHERE import_id=?",
                               (import_status, 1, job.import_id))
            if preview_json is not None:
                connection.execute("INSERT INTO import_previews(import_id, revision, data_revision, normalized_preview_json, updated_at) VALUES (?, 1, ?, ?, ?) ON CONFLICT(import_id) DO UPDATE SET revision=excluded.revision, data_revision=excluded.data_revision, normalized_preview_json=excluded.normalized_preview_json, updated_at=excluded.updated_at",
                                   (job.import_id, data_revision, preview_json, datetime.now().astimezone().isoformat()))

    def load_import_job(self, job_id: str) -> tuple[ImportJob, tuple[ImportDocumentResult, ...]] | None:
        connection = self.connect()
        try:
            row = connection.execute("SELECT * FROM import_jobs WHERE job_id=?", (job_id,)).fetchone()
            if row is None:
                return None
            from portman_v10.application.contracts import ErrorCode
            job = ImportJob(row["job_id"], row["import_id"], row["state"], row["progress"], row["revision"], ErrorCode(row["error_code"]) if row["error_code"] else None, row["document_count"], row["completed_documents"], bool(row["cancel_requested"]))
            rows = connection.execute("SELECT d.document_id, f.original_name, d.status, d.document_type, d.plugin_id, d.plugin_version, d.parser_package_version, d.parser_api_version, d.handler_id, d.parser_schema_version, d.extraction_preparation_version, d.warning_messages_json, d.error_code FROM import_job_documents d JOIN documents f ON f.document_id=d.document_id WHERE d.job_id=? ORDER BY d.ordinal", (job_id,)).fetchall()
            results = tuple(ImportDocumentResult(r["document_id"], r["original_name"], r["status"], r["document_type"], r["plugin_id"], r["plugin_version"], r["handler_id"], r["parser_schema_version"], tuple(json.loads(r["warning_messages_json"])), ErrorCode(r["error_code"]) if r["error_code"] else None, r["parser_package_version"], r["parser_api_version"], r["extraction_preparation_version"]) for r in rows)
            return job, results
        finally:
            connection.close()

    def load_import_preview_json(self, import_id: str) -> str | None:
        connection = self.connect()
        try:
            row = connection.execute("SELECT normalized_preview_json FROM import_previews WHERE import_id=?", (import_id,)).fetchone()
            return row[0] if row else None
        finally:
            connection.close()

    def find_job_by_import(self, import_id: str) -> str | None:
        connection = self.connect()
        try:
            row = connection.execute("SELECT job_id FROM import_jobs WHERE import_id=?", (import_id,)).fetchone()
            return row[0] if row else None
        finally:
            connection.close()

    def load_import_commit_report(self, import_id: str):
        connection = self.connect()
        try:
            row = connection.execute("SELECT result_text FROM operations WHERE command_type='commit_import' ORDER BY completed_at DESC").fetchall()
            for value in row:
                report = json.loads(value[0])
                if report.get("import_id") == import_id:
                    return report
            return None
        finally:
            connection.close()

    def load_import_preview_revision(self, import_id: str) -> tuple[int, int] | None:
        connection = self.connect()
        try:
            row = connection.execute("SELECT revision, data_revision FROM import_previews WHERE import_id=?", (import_id,)).fetchone()
            return (row[0], row[1]) if row else None
        finally:
            connection.close()

    def load_review_decisions(self, import_id: str) -> tuple[tuple[str, int, int, str], ...]:
        connection = self.connect()
        try:
            return tuple((row["candidate_id"], row["candidate_revision"], row["preview_revision"], row["decision_json"]) for row in connection.execute(
                "SELECT candidate_id, candidate_revision, preview_revision, decision_json FROM import_review_decisions WHERE import_id=? ORDER BY candidate_id, preview_revision DESC", (import_id,)))
        finally:
            connection.close()

    def load_import_preview_bundle(self, import_id: str):
        """Liest Vorschau, Revision und manuelle Entscheidungen aus einem Snapshot."""
        connection = self.connect()
        try:
            connection.execute("BEGIN")
            row = connection.execute("SELECT normalized_preview_json, revision, data_revision FROM import_previews WHERE import_id=?", (import_id,)).fetchone()
            if row is None:
                return None
            decisions = tuple((item["candidate_id"], item["candidate_revision"], item["preview_revision"], item["decision_json"]) for item in connection.execute(
                "SELECT candidate_id, candidate_revision, preview_revision, decision_json FROM import_review_decisions WHERE import_id=? ORDER BY candidate_id, preview_revision DESC", (import_id,)))
            connection.commit()
            return row["normalized_preview_json"], row["revision"], row["data_revision"], decisions
        finally:
            connection.close()

    def save_review_decision(self, import_id: str, candidate_id: str, preview_revision: int, candidate_revision: int, decision_json: str, *, preview_json: str | None = None) -> None:
        with self.transaction() as connection:
            current = connection.execute("SELECT revision FROM import_previews WHERE import_id=?", (import_id,)).fetchone()
            if current is None:
                raise KeyError(import_id)
            if current[0] != preview_revision:
                raise ValueError("stale preview revision")
            connection.execute("INSERT INTO import_review_decisions(import_id, candidate_id, candidate_revision, preview_revision, decision_json, created_at) VALUES (?, ?, ?, ?, ?, ?)", (import_id, candidate_id, candidate_revision, preview_revision, decision_json, datetime.now().astimezone().isoformat()))
            connection.execute("UPDATE import_previews SET revision=revision+1, normalized_preview_json=COALESCE(?, normalized_preview_json) WHERE import_id=?", (preview_json, import_id))
            connection.execute("UPDATE imports SET preview_revision=preview_revision+1 WHERE import_id=?", (import_id,))

    def replace_import_preview_items(self, import_id: str, expected_revision: int, preview_json: str) -> None:
        with self.transaction() as connection:
            row = connection.execute("SELECT revision FROM import_previews WHERE import_id=?", (import_id,)).fetchone()
            if row is None or row[0] != expected_revision:
                raise ValueError("stale preview revision")
            connection.execute("UPDATE import_previews SET normalized_preview_json=? WHERE import_id=?", (preview_json, import_id))

    def commit_import(self, command, preview, decisions):
        """Revalidiert und übernimmt eine Vorschau atomar; BEGIN IMMEDIATE serialisiert Writer."""
        from portman_v10.application.contracts import ApplicationError, CommitReport, ErrorCode

        command_text = json.dumps({"import_id": command.import_id, "preview_revision": command.preview_revision}, sort_keys=True, separators=(",", ":"))
        input_hash = sha256(command_text.encode()).hexdigest()
        with self.transaction() as connection:
            operation = connection.execute("SELECT command_type, input_hash, result_text FROM operations WHERE request_id=?", (command.request_id,)).fetchone()
            if operation:
                if operation["command_type"] != "commit_import" or operation["input_hash"] != input_hash:
                    raise ApplicationError(ErrorCode.REQUEST_ID_REUSED, "request_id wurde bereits für eine andere Eingabe verwendet")
                raw = json.loads(operation["result_text"])
                return CommitReport(raw["import_id"], tuple(raw["event_ids"]), raw["data_revision"], True,
                                    tuple(raw.get("created_event_ids", ())), tuple(raw.get("linked_event_ids", ())))

            stored = connection.execute("SELECT revision, data_revision FROM import_previews WHERE import_id=?", (command.import_id,)).fetchone()
            current_revision = connection.execute("SELECT data_revision FROM app_state WHERE singleton=1").fetchone()[0]
            if stored is None or stored["revision"] != command.preview_revision or stored["data_revision"] != current_revision:
                raise ApplicationError(ErrorCode.STALE_REVISION, "Vorschau oder Datenbestand hat sich geändert; bitte neu prüfen")
            if preview.revision != stored["revision"] or preview.data_revision != stored["data_revision"]:
                raise ApplicationError(ErrorCode.STALE_REVISION, "Übergebene Vorschau ist nicht mehr aktuell")
            import_row = connection.execute("SELECT status, parser_version, schema_version FROM imports WHERE import_id=?", (command.import_id,)).fetchone()
            if import_row is None or import_row["status"] != "preview":
                raise ApplicationError(ErrorCode.VALIDATION_ERROR, "Dieser Import ist nicht übernahmebereit")
            decision_rows = connection.execute("SELECT candidate_id, candidate_revision, preview_revision, decision_json FROM import_review_decisions WHERE import_id=? ORDER BY candidate_id, preview_revision DESC", (command.import_id,)).fetchall()
            latest_decisions = {}
            for row in decision_rows:
                if row["candidate_id"] in latest_decisions:
                    continue
                latest_decisions[row["candidate_id"]] = (row["candidate_revision"], row["preview_revision"], json.loads(row["decision_json"]))
            preview_items = {item.candidate_id: item for item in preview.items}
            candidates = []
            for candidate_id, item in sorted(preview_items.items()):
                if item.review_status in {"information", "error", "duplicate_file"}:
                    continue
                decision_record = latest_decisions.get(candidate_id)
                if not decision_record:
                    raise ApplicationError(ErrorCode.VALIDATION_ERROR, "Jeder Buchungskandidat muss ausdrücklich angenommen oder ignoriert werden")
                candidate_revision, decision_revision, decision = decision_record
                if candidate_revision != item.revision or decision_revision > stored["revision"]:
                    raise ApplicationError(ErrorCode.STALE_REVISION, "Kandidatenentscheidung ist nicht zur aktuellen Vorschau passend")
                action = decision["decision"]
                if action == "ignore":
                    continue
                repeated_document_link = action == "link" and any(value.code == ErrorCode.POSSIBLE_DUPLICATE and value.related_event_id for value in item.conflicts) and connection.execute("SELECT 1 FROM event_documents WHERE event_id=? AND document_id=?", (decision.get("target_id"), item.document_id)).fetchone() is not None
                if repeated_document_link:
                    if not decision.get("target_id"):
                        raise ApplicationError(ErrorCode.VALIDATION_ERROR, "Wiederimport benötigt das bereits verknüpfte Zielereignis")
                    candidates.append((item, action, decision.get("target_id")))
                    continue
                if item.conflicts and not (action == "link" and all(value.code in {ErrorCode.POSSIBLE_DUPLICATE, ErrorCode.SOURCE_CONFLICT} for value in item.conflicts)):
                    raise ApplicationError(ErrorCode.VALIDATION_ERROR, "Widersprüchliche Kandidaten können nicht übernommen werden")
                if item.missing_fields or item.review_status != "complete_candidate":
                    raise ApplicationError(ErrorCode.VALIDATION_ERROR, "Unvollständige Kandidaten können nicht übernommen werden")
                booking_kinds = {
                    ("user.comdirect-ertraege", "wertpapierkauf"): {"BUY"},
                    ("user.comdirect-ertraege", "wertpapierverkauf"): {"SELL"},
                    ("user.comdirect-ertraege", "einloesung"): {"REDEMPTION"},
                    ("user.comdirect-ertraege", "dividendengutschrift"): {"DIVIDEND"},
                    ("user.comdirect-ertraege", "ertragsgutschrift"): {"DIVIDEND"},
                }
                if item.plugin_id is not None and item.kind not in booking_kinds.get((item.plugin_id, item.handler_id), set()):
                    raise ApplicationError(ErrorCode.UNSUPPORTED_DOCUMENT, "Für diesen Parserhandler und Vorgangstyp ist noch kein sicherer V10-Übernahmepfad implementiert")
                if action not in {"accept", "link"}:
                    raise ApplicationError(ErrorCode.VALIDATION_ERROR, "Kandidat hat keine gültige Übernahmeentscheidung")
                candidates.append((item, action, decision.get("target_id")))

            by_reference = {}
            for item, action, target_id in candidates:
                reference = dict(item.references).get("bank_reference")
                reference_status = dict(item.references).get("bank_reference_status")
                account_ids = {movement.account_id for movement in item.movements if movement.movement_type == "cash" and movement.account_id}
                if reference and reference_status == "RECOGNIZED" and account_ids:
                    key = ("|".join(sorted(account_ids)), reference.strip())
                    if key in by_reference:
                        # Dieselbe Belegreferenz zweimal in einer Auswahl kann nicht zwei Events erzeugen.
                        raise ApplicationError(ErrorCode.POSSIBLE_DUPLICATE, "Mehrere ausgewählte Belege teilen dieselbe sichere Bankreferenz")
                    by_reference[key] = item.candidate_id
                if action == "link" and not target_id:
                    raise ApplicationError(ErrorCode.VALIDATION_ERROR, "Verknüpfungsentscheidung benötigt ein Zielereignis")

            created, linked = [], []
            now = datetime.now().astimezone().isoformat()
            for item, action, target_id in candidates:
                reference = dict(item.references).get("bank_reference")
                reference_status = dict(item.references).get("bank_reference_status")
                cash_accounts = {movement.account_id for movement in item.movements if movement.movement_type == "cash" and movement.account_id}
                context = "|".join(sorted(cash_accounts)) if reference and reference_status == "RECOGNIZED" and cash_accounts else None
                existing = None
                if reference and context:
                    rows = connection.execute("SELECT event_id FROM events WHERE reference_context=? AND bank_reference=? ORDER BY event_id", (context, reference.strip())).fetchall()
                    if len(rows) > 1:
                        raise ApplicationError(ErrorCode.SOURCE_CONFLICT, "Bankreferenz ist im Kontokontext nicht eindeutig")
                    existing = rows[0][0] if rows else None
                if action == "link":
                    if existing and existing != target_id:
                        raise ApplicationError(ErrorCode.SOURCE_CONFLICT, "Sichere Referenz zeigt auf ein anderes Ereignis als die Entscheidung")
                    event_id = target_id
                    stored_event = connection.execute("SELECT kind FROM events WHERE event_id=?", (event_id,)).fetchone()
                    if stored_event is None or stored_event["kind"] != item.kind:
                        raise ApplicationError(ErrorCode.SOURCE_CONFLICT, "Verknüpfungsziel fehlt oder hat einen anderen Vorgangstyp")
                    self._link_complement(connection, item, event_id, command.import_id, now)
                    linked.append(event_id)
                elif item.disposition in {"conflict", "complement", "existing"}:
                    related = next((value.related_event_id for value in item.conflicts if value.related_event_id), None)
                    if not related:
                        raise ApplicationError(ErrorCode.POSSIBLE_DUPLICATE, "Vorschau enthält einen ungeklärten Dublettenhinweis")
                    event_id = related
                    self._link_complement(connection, item, event_id, command.import_id, now)
                    linked.append(event_id)
                elif existing:
                    self._link_complement(connection, item, existing, command.import_id, now)
                    linked.append(existing)
                else:
                    event_id = uuid4().hex
                    self._insert_import_event(connection, item, event_id, command.import_id, now, reference, context, import_row)
                    created.append(event_id)

            revision = self._bump_metadata_revision(connection, refresh_index_revision=False)
            self._refresh_touched_balance_index(connection, candidates, created, revision)
            report = CommitReport(command.import_id, tuple(dict.fromkeys((*created, *linked))), revision, False, tuple(created), tuple(linked))
            result = json.dumps({"import_id": report.import_id, "event_ids": report.event_ids, "data_revision": report.data_revision,
                                 "created_event_ids": report.created_event_ids, "linked_event_ids": report.linked_event_ids}, sort_keys=True)
            connection.execute("INSERT INTO operations(request_id, command_type, input_hash, result_text, completed_at) VALUES (?, 'commit_import', ?, ?, ?)", (command.request_id, input_hash, result, now))
            connection.execute("UPDATE imports SET status='committed' WHERE import_id=?", (command.import_id,))
            return report

    def _insert_import_event(self, connection, item, event_id, import_id, now, reference, context, import_row):
        dates = {date.meaning: date.value for date in item.dates}
        dates.update({"event_date": next((movement.date for movement in item.movements if movement.date), None)})
        booking_date = dates.get("event_date") or next((value for value in dates.values() if value), None)
        if booking_date is None:
            raise ValueError("Übernommener Vorgang benötigt ein belegtes Buchungsdatum")
        completeness = "complete" if not item.missing_fields else "incomplete"
        connection.execute("INSERT INTO events(event_id, kind, booking_date, trade_date, value_date, original_text, completeness, revision, bank_reference, reference_context) VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?)",
                           (event_id, item.kind, booking_date.isoformat(), self._date(dates.get("trade_date")), self._date(dates.get("value_date")), item.original_text, completeness, reference.strip() if reference else None, context))
        for movement in item.movements:
            if movement.account_id is None or movement.date is None or movement.amount is None:
                raise ValueError("Unvollständige Bewegung trotz Übernahmefreigabe")
            position_id = uuid4().hex
            connection.execute("INSERT INTO positions(position_id,event_id,account_id,currency,amount_decimal,instrument_id,quantity_decimal,effective_date) VALUES (?,?,?,?,?,?,?,?)",
                               (position_id, event_id, movement.account_id, movement.currency if movement.movement_type == "cash" else None,
                                self._decimal(movement.amount) if movement.movement_type == "cash" else None,
                                movement.instrument_id if movement.movement_type == "quantity" else None,
                                self._decimal(movement.amount) if movement.movement_type == "quantity" else None, movement.date.isoformat()))
        for component in item.components:
            if component.category not in {"fee", "tax"}:
                continue
            component_type = "fee" if component.category == "fee" else "tax"
            connection.execute("INSERT INTO event_components(component_id,event_id,component_type,amount_decimal,currency) VALUES (?,?,?,?,?)",
                               (uuid4().hex, event_id, component_type, self._decimal(component.amount), component.currency))
        document = connection.execute("SELECT * FROM documents WHERE document_id=?", (item.document_id,)).fetchone()
        if document is None:
            raise ValueError("Quellbeleg fehlt")
        connection.execute("INSERT OR IGNORE INTO event_documents(event_id,document_id,source_role) VALUES (?,?,?)", (event_id, item.document_id, "primary"))
        connection.execute("INSERT INTO import_contributions(contribution_id,import_id,event_id,document_id,source_kind,target_type,field_name,action,value_text,created_at) VALUES (?,?,?,?,'import','event','event','create',?,?)",
                           (uuid4().hex, import_id, event_id, item.document_id, json.dumps({"candidate_id": item.candidate_id}), now))

    def _link_complement(self, connection, item, event_id, import_id, now):
        event = connection.execute("SELECT kind, bank_reference, reference_context FROM events WHERE event_id=?", (event_id,)).fetchone()
        if event is None or event["kind"] != item.kind:
            raise ValueError("Ergänzungsbeleg passt nicht zum vorhandenen Vorgang")
        existing_positions = connection.execute("SELECT account_id,currency,amount_decimal,instrument_id,quantity_decimal,effective_date FROM positions WHERE event_id=? ORDER BY account_id,currency,instrument_id,effective_date", (event_id,)).fetchall()
        existing_signature = {(row["account_id"], row["currency"], row["amount_decimal"], row["instrument_id"], row["quantity_decimal"], row["effective_date"]) for row in existing_positions}
        incoming_signature = set()
        for movement in item.movements:
            account_id = movement.account_id
            if not account_id or movement.amount is None or movement.date is None:
                raise ValueError("Ergänzungsbeleg enthält keine vollständige Bewegung")
            signature = (account_id, movement.currency if movement.movement_type == "cash" else None,
                         self._decimal(movement.amount) if movement.movement_type == "cash" else None,
                         movement.instrument_id if movement.movement_type == "quantity" else None,
                         self._decimal(movement.amount) if movement.movement_type == "quantity" else None, movement.date.isoformat())
            incoming_signature.add(signature)
        if existing_signature and incoming_signature != existing_signature:
            raise ValueError("Ergänzungsbeleg widerspricht den vorhandenen Geld-/Mengenpositionen")
        if existing_signature:
            existing_documents = {row[0] for row in connection.execute("SELECT document_id FROM event_documents WHERE event_id=?", (event_id,))}
            if item.document_id in existing_documents:
                connection.execute("INSERT INTO import_contributions(contribution_id,import_id,event_id,document_id,source_kind,target_type,field_name,action,value_text,created_at) VALUES (?,?,?,?,'import','event','evidence','link',?,?)",
                                   (uuid4().hex, import_id, event_id, item.document_id, json.dumps({"candidate_id": item.candidate_id, "duplicate_file": True}), now))
                return
        stored_components = {(row["component_type"], row["amount_decimal"], row["currency"]) for row in connection.execute("SELECT component_type,amount_decimal,currency FROM event_components WHERE event_id=?", (event_id,))}
        for component in item.components:
            if component.category not in {"fee", "tax"} or component.amount is None:
                continue
            key = (component.category, self._decimal(component.amount), component.currency)
            if key in stored_components:
                continue
            same_kind = {value for value in stored_components if value[0] == component.category and value[2] == component.currency}
            if same_kind:
                raise ValueError("Gebühren- oder Steuerbeleg widerspricht einem bereits gespeicherten Wert")
            connection.execute("INSERT INTO event_components(component_id,event_id,component_type,amount_decimal,currency) VALUES (?,?,?,?,?)", (uuid4().hex, event_id, component.category, key[1], key[2]))
            stored_components.add(key)
        connection.execute("INSERT OR IGNORE INTO event_documents(event_id,document_id,source_role) VALUES (?,?,?)", (event_id, item.document_id, "complement"))
        if item.original_text:
            current = connection.execute("SELECT original_text FROM events WHERE event_id=?", (event_id,)).fetchone()[0]
            if current and current != item.original_text:
                raise ValueError("Ergänzungsbeleg hat abweichenden Originaltext; keine automatische Überschreibung")
            if not current:
                connection.execute("UPDATE events SET original_text=?, completeness='complete', revision=revision+1 WHERE event_id=?", (item.original_text, event_id))
        if reference := dict(item.references).get("bank_reference"):
            context = event["reference_context"]
            if event["bank_reference"] and event["bank_reference"] != reference:
                raise ValueError("Ergänzungsbeleg enthält eine abweichende Bankreferenz")
            if not event["bank_reference"]:
                cash_accounts = sorted({movement.account_id for movement in item.movements if movement.movement_type == "cash" and movement.account_id})
                context = "|".join(cash_accounts) if cash_accounts else None
                if context:
                    connection.execute("UPDATE events SET bank_reference=?, reference_context=?, revision=revision+1 WHERE event_id=?", (reference, context, event_id))
        connection.execute("INSERT INTO import_contributions(contribution_id,import_id,event_id,document_id,source_kind,target_type,field_name,action,value_text,created_at) VALUES (?,?,?,?,'import','event','evidence','link',?,?)",
                           (uuid4().hex, import_id, event_id, item.document_id, json.dumps({"candidate_id": item.candidate_id}), now))

    def _refresh_touched_balance_index(self, connection, candidates, created_event_ids, revision):
        touched = set()
        for item, _action, _target_id in candidates:
            for movement in item.movements:
                if not movement.account_id:
                    continue
                asset_key = f"CURRENCY:{movement.currency}" if movement.movement_type == "cash" else f"INSTRUMENT:{movement.instrument_id}"
                touched.add((movement.account_id, asset_key, movement.currency if movement.movement_type == "cash" else None, movement.instrument_id if movement.movement_type == "quantity" else None))
        for account_id, asset_key, currency, instrument_id in touched:
            opening_rows = connection.execute("SELECT o.effective_date,o.cost_basis_status,p.amount_decimal,p.quantity_decimal FROM opening_entries o JOIN positions p ON p.position_id=o.position_id WHERE p.account_id=? AND ((? IS NOT NULL AND p.currency=?) OR (? IS NOT NULL AND p.instrument_id=?)) ORDER BY o.effective_date", (account_id, currency, currency, instrument_id, instrument_id)).fetchall()
            rows = connection.execute("SELECT p.effective_date,p.amount_decimal,p.quantity_decimal,e.completeness FROM positions p JOIN events e ON e.event_id=p.event_id LEFT JOIN opening_entries o ON o.event_id=e.event_id WHERE p.account_id=? AND o.event_id IS NULL AND ((? IS NOT NULL AND p.currency=?) OR (? IS NOT NULL AND p.instrument_id=?)) ORDER BY p.effective_date,p.position_id", (account_id, currency, currency, instrument_id, instrument_id)).fetchall()
            completeness = {}
            dates = sorted({row["effective_date"] for row in (*opening_rows, *rows)})
            by_date = {}
            for row in opening_rows:
                by_date.setdefault(row["effective_date"], []).append({"amount_decimal": row["amount_decimal"], "quantity_decimal": row["quantity_decimal"], "completeness": "complete", "is_opening": True})
            for row in rows:
                by_date.setdefault(row["effective_date"], []).append(row)
            for day in dates:
                day_complete = True
                for row in by_date[day]:
                    value = row["amount_decimal"] if currency else row["quantity_decimal"]
                    if value is None:
                        day_complete = False
                    day_complete &= row["completeness"] == "complete"
                completeness[day] = "complete" if day_complete else "incomplete"
            connection.execute("DELETE FROM balance_index WHERE account_id=? AND asset_key=?", (account_id, asset_key))
            running = "0"
            known = False
            for day in dates:
                if any("is_opening" in row.keys() and row["is_opening"] for row in by_date[day]):
                    known = True
                day_values = [row["amount_decimal"] if currency else row["quantity_decimal"] for row in by_date[day] if (row["amount_decimal"] if currency else row["quantity_decimal"]) is not None]
                if day_values:
                    running = sum_decimal_text([running, *day_values])
                value = running if known else None
                status = "complete" if all(completeness[prior] == "complete" for prior in dates[:dates.index(day) + 1]) else "incomplete"
                connection.execute("INSERT INTO balance_index(account_id,asset_key,currency,instrument_id,as_of,value_decimal,value_rational,completeness,data_revision) VALUES (?,?,?,?,?,?,NULL,?,?)", (account_id, asset_key, currency, instrument_id, day, value, status, revision))

    @staticmethod
    def _is_canonical_decimal(value: object) -> int:
        if not isinstance(value, str):
            return 0
        try:
            return int(canonical_decimal(value) == value)
        except ValueError:
            return 0

    @staticmethod
    def _is_canonical_rational(value: object) -> int:
        if not isinstance(value, str):
            return 0
        try:
            RationalAmount.from_storage_text(value)
            return 1
        except (ValueError, ZeroDivisionError):
            return 0

    @classmethod
    def _is_positive_decimal(cls, value: object) -> int:
        if not cls._is_canonical_decimal(value):
            return 0
        from portman_v10.domain.values import compare_decimal_text
        return int(compare_decimal_text(value, "0") > 0)

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def migrate(self) -> tuple[str, ...]:
        if sqlite3.sqlite_version_info < (3, 37, 0):
            raise RuntimeError("V10-Schema benötigt SQLite 3.37.0 oder neuer (STRICT-Tabellen)")
        migrations = sorted(self.migrations_dir.glob("[0-9][0-9][0-9][0-9]_*.sql"))
        if not migrations:
            raise RuntimeError("Keine SQLite-Migrationen gefunden")
        applied_now: list[str] = []
        with self.transaction() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, checksum TEXT NOT NULL, applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP) STRICT"
            )
            applied = {row["version"]: (row["name"], row["checksum"]) for row in connection.execute("SELECT version, name, checksum FROM schema_migrations")}
            for expected, path in enumerate(migrations, start=1):
                version = int(path.name[:4])
                if version != expected:
                    raise RuntimeError(f"Migrationslücke vor {path.name}")
                raw_sql = path.read_bytes()
                checksum = sha256(raw_sql).hexdigest()
                if version in applied:
                    if applied[version] != (path.name, checksum):
                        raise RuntimeError(f"Versionsnummer {version} ist bereits anders belegt")
                    continue
                sql = raw_sql.decode("utf-8")
                statement = ""
                for line in sql.splitlines(keepends=True):
                    statement += line
                    if sqlite3.complete_statement(statement):
                        if statement.strip():
                            connection.execute(statement)
                        statement = ""
                if statement.strip():
                    raise RuntimeError(f"Unvollständiges SQL-Statement in {path.name}")
                connection.execute("INSERT INTO schema_migrations(version, name, checksum) VALUES (?, ?, ?)", (version, path.name, checksum))
                applied_now.append(path.name)
        return tuple(applied_now)

    @staticmethod
    def _decimal(value: ExactValue | None) -> str | None:
        if value is None:
            return None
        canonical = canonical_decimal(value.text)
        if canonical != value.text:
            raise ValueError("Zahlen müssen gemäß V10-05 kanonisch als Dezimaltext vorliegen")
        return canonical

    @staticmethod
    def _date(value: date | None) -> str | None:
        return value.isoformat() if value is not None else None

    @staticmethod
    def _bump_metadata_revision(connection: sqlite3.Connection, *, refresh_index_revision: bool = True) -> int:
        connection.execute("UPDATE app_state SET data_revision = data_revision + 1 WHERE singleton = 1")
        revision = connection.execute("SELECT data_revision FROM app_state WHERE singleton = 1").fetchone()[0]
        if refresh_index_revision:
            connection.execute("UPDATE balance_index SET data_revision = ?", (revision,))
        return revision

    @staticmethod
    def _account_identifiers(connection: sqlite3.Connection, account_id: str) -> tuple[AccountIdentifier, ...]:
        return tuple(AccountIdentifier(row["identifier_type"], row["context"], row["value"]) for row in connection.execute(
            "SELECT identifier_type, context, value FROM account_identifiers WHERE account_id = ? ORDER BY identifier_type, context, value", (account_id,)
        ))

    @classmethod
    def _account_from_row(cls, connection: sqlite3.Connection, row: sqlite3.Row) -> Account:
        return Account(row["account_id"], row["name"], row["kind"], row["subtype"], row["institution"], row["currency"], row["reference_account_id"], bool(row["active"]), row["revision"], cls._account_identifiers(connection, row["account_id"]))

    @staticmethod
    def _instrument_identifiers(connection: sqlite3.Connection, instrument_id: str) -> tuple[InstrumentIdentifier, ...]:
        return tuple(InstrumentIdentifier(row["provider"], row["identifier_type"], row["context"], row["value"]) for row in connection.execute(
            "SELECT provider, identifier_type, context, value FROM instrument_identifiers WHERE instrument_id = ? ORDER BY provider, identifier_type, context, value", (instrument_id,)
        ) if not (row["provider"] == "instrument" and row["identifier_type"] in ("ISIN", "WKN")))

    @classmethod
    def _instrument_from_row(cls, connection: sqlite3.Connection, row: sqlite3.Row) -> Instrument:
        identifiers = tuple(InstrumentIdentifier(item["provider"], item["identifier_type"], item["context"], item["value"]) for item in connection.execute(
            "SELECT provider, identifier_type, context, value FROM instrument_identifiers WHERE instrument_id = ? ORDER BY provider, identifier_type, context, value", (row["instrument_id"],)
        ))
        standard = {(item.identifier_type): item.value for item in identifiers if item.provider == "instrument"}
        return Instrument(row["instrument_id"], row["name"], row["asset_type"], standard.get("ISIN"), standard.get("WKN"), row["revision"], tuple(item for item in identifiers if item.provider != "instrument"))

    def list_accounts(self, cursor: str | None = None, limit: int = 100) -> AccountPage:
        if not 1 <= limit <= 500:
            raise ApplicationError(ErrorCode.VALIDATION_ERROR, "limit muss zwischen 1 und 500 liegen")
        connection = self.connect()
        try:
            revision = connection.execute("SELECT data_revision FROM app_state WHERE singleton = 1").fetchone()[0]
            offset = 0
            if cursor:
                try:
                    cursor_revision, cursor_offset = cursor.split(":", 1)
                    if int(cursor_revision) != revision:
                        raise ApplicationError(ErrorCode.STALE_REVISION, "Kontenliste wurde geändert; Liste neu laden")
                    offset = int(cursor_offset)
                    if offset < 0:
                        raise ValueError("negativer Cursor")
                except ValueError as error:
                    raise ApplicationError(ErrorCode.VALIDATION_ERROR, "Kontencursor ungültig") from error
            rows = connection.execute("SELECT * FROM accounts ORDER BY account_id LIMIT ? OFFSET ?", (limit + 1, offset)).fetchall()
            has_more = len(rows) > limit
            items = tuple(self._account_from_row(connection, row) for row in rows[:limit])
            next_cursor = f"{revision}:{offset + limit}" if has_more else None
            return AccountPage(items, next_cursor, revision)
        finally:
            connection.close()

    def get_account(self, account_id: str) -> Account:
        connection = self.connect()
        try:
            row = connection.execute("SELECT * FROM accounts WHERE account_id = ?", (account_id,)).fetchone()
            if row is None:
                raise ApplicationError(ErrorCode.NOT_FOUND, "Konto nicht gefunden")
            return self._account_from_row(connection, row)
        finally:
            connection.close()

    def save_account(self, value: AccountInput, expected_revision: int | None = None) -> Account:
        if not value.name.strip():
            raise ApplicationError(ErrorCode.VALIDATION_ERROR, "Kontoname ist erforderlich")
        if value.reference_account_id == value.account_id and value.account_id is not None:
            raise ApplicationError(ErrorCode.VALIDATION_ERROR, "Ein Konto darf nicht sich selbst als Referenzkonto haben")
        account_id = value.account_id or uuid4().hex
        with self.transaction() as connection:
            existing = connection.execute("SELECT * FROM accounts WHERE account_id = ?", (account_id,)).fetchone()
            if existing is None and expected_revision is not None:
                raise ApplicationError(ErrorCode.STALE_REVISION, "Neues Konto darf keine erwartete Revision haben")
            if existing is not None and expected_revision != existing["revision"]:
                raise ApplicationError(ErrorCode.STALE_REVISION, "Konto-Revision ist veraltet")
            if existing is not None and connection.execute("SELECT 1 FROM positions WHERE account_id = ? LIMIT 1", (account_id,)).fetchone():
                if (existing["kind"], existing["subtype"], existing["currency"]) != (value.kind, value.subtype, value.currency):
                    raise ApplicationError(ErrorCode.VALIDATION_ERROR, "Kontotyp, Unterart und Währung historischer Konten sind unveränderlich")
            if existing is not None and value.kind != "cash" and connection.execute("SELECT 1 FROM accounts WHERE reference_account_id = ? LIMIT 1", (account_id,)).fetchone():
                raise ApplicationError(ErrorCode.VALIDATION_ERROR, "Ein als Referenz verwendetes Konto muss ein Geldkonto bleiben")
            if value.reference_account_id:
                reference = connection.execute("SELECT kind FROM accounts WHERE account_id = ?", (value.reference_account_id,)).fetchone()
                if reference is None:
                    raise ApplicationError(ErrorCode.NOT_FOUND, "Referenzkonto nicht gefunden")
                if reference["kind"] != "cash":
                    raise ApplicationError(ErrorCode.VALIDATION_ERROR, "Referenzkonto muss ein Geldkonto sein")
            revision = existing["revision"] + 1 if existing else 1
            if existing is None:
                connection.execute("INSERT INTO accounts(account_id, name, kind, subtype, institution, currency, reference_account_id, active, revision) VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)", (account_id, value.name, value.kind, value.subtype, value.institution, value.currency, value.reference_account_id, revision))
            else:
                connection.execute("UPDATE accounts SET name=?, kind=?, subtype=?, institution=?, currency=?, reference_account_id=?, revision=? WHERE account_id=?", (value.name, value.kind, value.subtype, value.institution, value.currency, value.reference_account_id, revision, account_id))
            connection.execute("DELETE FROM account_identifiers WHERE account_id = ?", (account_id,))
            connection.executemany("INSERT INTO account_identifiers(identifier_id, account_id, identifier_type, context, value) VALUES (?, ?, ?, ?, ?)", ((uuid4().hex, account_id, item.identifier_type, item.context, item.value) for item in value.identifiers))
            self._bump_metadata_revision(connection)
            row = connection.execute("SELECT * FROM accounts WHERE account_id = ?", (account_id,)).fetchone()
            return self._account_from_row(connection, row)

    def deactivate_account(self, account_id: str, expected_revision: int) -> Account:
        with self.transaction() as connection:
            row = connection.execute("SELECT * FROM accounts WHERE account_id = ?", (account_id,)).fetchone()
            if row is None:
                raise ApplicationError(ErrorCode.NOT_FOUND, "Konto nicht gefunden")
            if expected_revision != row["revision"]:
                raise ApplicationError(ErrorCode.STALE_REVISION, "Konto-Revision ist veraltet")
            if row["active"]:
                connection.execute("UPDATE accounts SET active = 0, revision = revision + 1 WHERE account_id = ?", (account_id,))
                self._bump_metadata_revision(connection)
            updated = connection.execute("SELECT * FROM accounts WHERE account_id = ?", (account_id,)).fetchone()
            return self._account_from_row(connection, updated)

    def get_instrument(self, instrument_id: str) -> Instrument:
        connection = self.connect()
        try:
            row = connection.execute("SELECT * FROM instruments WHERE instrument_id = ?", (instrument_id,)).fetchone()
            if row is None:
                raise ApplicationError(ErrorCode.NOT_FOUND, "Instrument nicht gefunden")
            return self._instrument_from_row(connection, row)
        finally:
            connection.close()

    def list_instruments(self, cursor: str | None = None, limit: int = 100) -> InstrumentPage:
        if not 1 <= limit <= 500:
            raise ApplicationError(ErrorCode.VALIDATION_ERROR, "limit muss zwischen 1 und 500 liegen")
        connection = self.connect()
        try:
            revision = connection.execute("SELECT data_revision FROM app_state WHERE singleton = 1").fetchone()[0]
            offset = 0
            if cursor:
                try:
                    cursor_revision, cursor_offset = cursor.split(":", 1)
                    if int(cursor_revision) != revision:
                        raise ApplicationError(ErrorCode.STALE_REVISION, "Instrumentliste wurde geändert; Liste neu laden")
                    offset = int(cursor_offset)
                    if offset < 0:
                        raise ValueError("negativer Cursor")
                except ValueError as error:
                    raise ApplicationError(ErrorCode.VALIDATION_ERROR, "Instrumentcursor ungültig") from error
            rows = connection.execute("SELECT * FROM instruments ORDER BY instrument_id LIMIT ? OFFSET ?", (limit + 1, offset)).fetchall()
            items = tuple(self._instrument_from_row(connection, row) for row in rows[:limit])
            next_cursor = f"{revision}:{offset + limit}" if len(rows) > limit else None
            return InstrumentPage(items, next_cursor, revision)
        finally:
            connection.close()

    def save_instrument(self, value: InstrumentInput, expected_revision: int | None = None) -> Instrument:
        instrument_id = value.instrument_id or uuid4().hex
        with self.transaction() as connection:
            existing = connection.execute("SELECT * FROM instruments WHERE instrument_id = ?", (instrument_id,)).fetchone()
            if value.instrument_id is not None and existing is None:
                raise ApplicationError(ErrorCode.NOT_FOUND, "Instrument nicht gefunden")
            if value.instrument_id is None and expected_revision is not None:
                raise ApplicationError(ErrorCode.STALE_REVISION, "Neues Instrument darf keine erwartete Revision haben")
            if existing is None and expected_revision is not None:
                raise ApplicationError(ErrorCode.STALE_REVISION, "Neues Instrument darf keine erwartete Revision haben")
            if existing is not None and expected_revision != existing["revision"]:
                raise ApplicationError(ErrorCode.STALE_REVISION, "Instrument-Revision ist veraltet")
            revision = existing["revision"] + 1 if existing else 1
            if existing is None:
                connection.execute("INSERT INTO instruments(instrument_id, name, asset_type, revision) VALUES (?, ?, ?, ?)", (instrument_id, value.name, value.asset_type, revision))
            else:
                connection.execute("UPDATE instruments SET name=?, asset_type=?, revision=? WHERE instrument_id=?", (value.name, value.asset_type, revision, instrument_id))
            connection.execute("DELETE FROM instrument_identifiers WHERE instrument_id = ?", (instrument_id,))
            identifiers = list(value.identifiers)
            if value.isin:
                identifiers.append(InstrumentIdentifier("instrument", "ISIN", "standard", value.isin))
            if value.wkn:
                identifiers.append(InstrumentIdentifier("instrument", "WKN", "standard", value.wkn))
            connection.executemany("INSERT INTO instrument_identifiers(identifier_id, instrument_id, provider, identifier_type, context, value) VALUES (?, ?, ?, ?, ?, ?)", ((uuid4().hex, instrument_id, item.provider, item.identifier_type, item.context, item.value) for item in identifiers))
            self._bump_metadata_revision(connection)
            row = connection.execute("SELECT * FROM instruments WHERE instrument_id = ?", (instrument_id,)).fetchone()
            return self._instrument_from_row(connection, row)

    def record_opening(self, value: OpeningBalanceInput) -> OpeningBalance:
        event_id = f"opening-event-{value.opening_id}"
        position_id = f"opening-position-{value.opening_id}"
        lot_id = f"opening-lot-{value.opening_id}" if value.instrument_id is not None else None
        money = value.currency is not None
        with self.transaction() as connection:
            account = connection.execute("SELECT kind, currency FROM accounts WHERE account_id = ?", (value.account_id,)).fetchone()
            if account is None:
                raise ApplicationError(ErrorCode.NOT_FOUND, "Eröffnungskonto nicht gefunden")
            if money and (account["kind"] != "cash" or account["currency"] != value.currency):
                raise ApplicationError(ErrorCode.VALIDATION_ERROR, "Geld-Eröffnung muss zur Kontowährung passen")
            if not money and account["kind"] != "position":
                raise ApplicationError(ErrorCode.VALIDATION_ERROR, "Mengen-Eröffnung benötigt ein Bestandskonto")
            if not money and connection.execute("SELECT 1 FROM instruments WHERE instrument_id = ?", (value.instrument_id,)).fetchone() is None:
                raise ApplicationError(ErrorCode.NOT_FOUND, "Eröffnungsinstrument nicht gefunden")
            event = EventInput(event_id, "opening_balance", value.effective_date, "complete", value.note)
            position = PositionInput(position_id, value.account_id, value.effective_date, currency=value.currency, amount=value.amount, instrument_id=value.instrument_id, quantity=value.quantity)
            connection.execute("INSERT INTO events(event_id, kind, booking_date, original_text, completeness, revision) VALUES (?, ?, ?, ?, ?, 1)", (event.event_id, event.kind, event.booking_date.isoformat(), event.original_text, event.completeness))
            connection.execute("INSERT INTO positions(position_id, event_id, account_id, currency, amount_decimal, instrument_id, quantity_decimal, effective_date) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (position.position_id, event.event_id, position.account_id, position.currency, self._decimal(position.amount), position.instrument_id, self._decimal(position.quantity), position.effective_date.isoformat()))
            if not money:
                connection.execute("INSERT INTO acquisition_lots(lot_id, instrument_id, account_id, original_quantity_decimal, acquired_on, original_cost_decimal, cost_currency) VALUES (?, ?, ?, ?, ?, ?, ?)", (lot_id, value.instrument_id, value.account_id, self._decimal(value.quantity), self._date(value.acquired_on), self._decimal(value.acquisition_cost), value.cost_currency))
            basis = "not_applicable" if money else "known" if value.acquisition_cost is not None else "unknown"
            connection.execute("INSERT INTO opening_entries(opening_id, event_id, position_id, opening_kind, effective_date, cost_basis_status, lot_id, note, source_kind, history_scope) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'manual', 'starting_balance')", (value.opening_id, event_id, position_id, "money" if money else "quantity", value.effective_date.isoformat(), basis, lot_id, value.note))
            self._bump_metadata_revision(connection, refresh_index_revision=False)
            return OpeningBalance(value.opening_id, event_id, position_id, lot_id, value.account_id, value.effective_date, value.amount, value.quantity, value.currency, value.instrument_id, basis, value.acquired_on, value.acquisition_cost, value.cost_currency, value.note, "manual", "starting_balance")

    def get_opening(self, opening_id: str) -> OpeningBalance:
        connection = self.connect()
        try:
            row = connection.execute("SELECT o.*, p.account_id, p.currency, p.amount_decimal, p.instrument_id, p.quantity_decimal, l.acquired_on, l.original_cost_decimal, l.cost_currency FROM opening_entries o JOIN positions p ON p.position_id=o.position_id LEFT JOIN acquisition_lots l ON l.lot_id=o.lot_id WHERE o.opening_id=?", (opening_id,)).fetchone()
            if row is None:
                raise ApplicationError(ErrorCode.NOT_FOUND, "Eröffnungsbestand nicht gefunden")
            return OpeningBalance(row["opening_id"], row["event_id"], row["position_id"], row["lot_id"], row["account_id"], date.fromisoformat(row["effective_date"]), ExactValue(row["amount_decimal"]) if row["amount_decimal"] is not None else None, ExactValue(row["quantity_decimal"]) if row["quantity_decimal"] is not None else None, row["currency"], row["instrument_id"], row["cost_basis_status"], date.fromisoformat(row["acquired_on"]) if row["acquired_on"] else None, ExactValue(row["original_cost_decimal"]) if row["original_cost_decimal"] is not None else None, row["cost_currency"], row["note"], row["source_kind"], row["history_scope"])
        finally:
            connection.close()

    def save_event(self, record: PersistedEventInput) -> None:
        event = record.event
        with self.transaction() as connection:
            connection.execute(
                "INSERT INTO events(event_id, kind, booking_date, trade_date, value_date, original_text, completeness, correction_of_event_id, revision) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (event.event_id, event.kind, event.booking_date.isoformat(), self._date(event.trade_date), self._date(event.value_date), event.original_text, event.completeness, event.correction_of_event_id, event.revision),
            )
            for position in record.positions:
                connection.execute(
                    "INSERT INTO positions(position_id, event_id, account_id, currency, amount_decimal, instrument_id, quantity_decimal, effective_date) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (position.position_id, event.event_id, position.account_id, position.currency, self._decimal(position.amount), position.instrument_id, self._decimal(position.quantity), position.effective_date.isoformat()),
                )
            for lot in record.lots:
                connection.execute(
                    "INSERT INTO acquisition_lots(lot_id, instrument_id, account_id, original_quantity_decimal, acquired_on, original_cost_decimal, cost_currency) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (lot.lot_id, lot.instrument_id, lot.account_id, self._decimal(lot.quantity), self._date(lot.acquired_on), self._decimal(lot.original_cost), lot.cost_currency),
                )
            for allocation in record.lot_allocations:
                connection.execute(
                    "INSERT INTO lot_allocations(event_id, position_id, lot_id, source_account_id, destination_account_id, quantity_decimal, cost_rational) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (event.event_id, allocation.position_id, allocation.lot_id, allocation.source_account_id, allocation.destination_account_id, self._decimal(allocation.quantity), allocation.cost.to_storage_text() if allocation.cost is not None else None),
                )
            for component in record.components:
                connection.execute(
                    "INSERT INTO event_components(component_id, event_id, component_type, amount_decimal, currency) VALUES (?, ?, ?, ?, ?)",
                    (component.component_id, event.event_id, component.component_type, self._decimal(component.amount), component.currency),
                )
            for document in record.documents:
                connection.execute(
                    "INSERT INTO documents(document_id, sha256, original_name, relative_path, media_type, imported_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (document.document_id, document.sha256, document.original_name, document.relative_path, document.media_type, document.imported_at),
                )
            for link in record.event_documents:
                connection.execute(
                    "INSERT INTO event_documents(event_id, document_id, page_or_entry, source_role) VALUES (?, ?, ?, ?)",
                    (event.event_id, link.document_id, link.page_or_entry, link.source_role),
                )
            for contribution in record.contributions:
                event_target = event.event_id if contribution.target_type == "event" else None
                account_target = contribution.target_id if contribution.target_type == "account" else None
                instrument_target = contribution.target_id if contribution.target_type == "instrument" else None
                connection.execute(
                    "INSERT INTO import_contributions(contribution_id, import_id, event_id, account_id, instrument_id, document_id, source_kind, target_type, field_name, action, previous_value_text, value_text, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (contribution.contribution_id, contribution.import_id, event_target, account_target, instrument_target, contribution.document_id, contribution.source_kind, contribution.target_type, contribution.field_name, contribution.action, contribution.previous_value_text, contribution.value_text, contribution.created_at),
                )
            self._bump_metadata_revision(connection, refresh_index_revision=False)

    def load_event(self, event_id: str) -> StoredEvent | None:
        connection = self.connect()
        try:
            row = connection.execute("SELECT * FROM events WHERE event_id = ?", (event_id,)).fetchone()
            if row is None:
                return None
            event = EventInput(row["event_id"], row["kind"], date.fromisoformat(row["booking_date"]), row["completeness"], row["original_text"], date.fromisoformat(row["trade_date"]) if row["trade_date"] else None, date.fromisoformat(row["value_date"]) if row["value_date"] else None, row["correction_of_event_id"], row["revision"])
            positions = tuple(StoredPosition(item["position_id"], item["account_id"], item["currency"], ExactValue(item["amount_decimal"]) if item["amount_decimal"] is not None else None, item["instrument_id"], ExactValue(item["quantity_decimal"]) if item["quantity_decimal"] is not None else None, date.fromisoformat(item["effective_date"])) for item in connection.execute("SELECT * FROM positions WHERE event_id = ? ORDER BY position_id", (event_id,)))
            components = tuple(StoredComponent(item["component_id"], item["component_type"], ExactValue(item["amount_decimal"]) if item["amount_decimal"] is not None else None, item["currency"]) for item in connection.execute("SELECT * FROM event_components WHERE event_id = ? ORDER BY component_id", (event_id,)))
            documents = tuple(item[0] for item in connection.execute("SELECT document_id FROM event_documents WHERE event_id = ? ORDER BY document_id", (event_id,)))
            contributions = tuple(StoredContribution(item["contribution_id"], item["import_id"], item["document_id"], item["source_kind"], item["target_type"], item["field_name"], item["action"], item["previous_value_text"], item["value_text"]) for item in connection.execute("SELECT * FROM import_contributions WHERE event_id = ? ORDER BY contribution_id", (event_id,)))
            lots = tuple(StoredLot(item["lot_id"], item["account_id"], item["instrument_id"], ExactValue(item["original_quantity_decimal"]), date.fromisoformat(item["acquired_on"]) if item["acquired_on"] else None, ExactValue(item["original_cost_decimal"]) if item["original_cost_decimal"] is not None else None, item["cost_currency"]) for item in connection.execute("SELECT l.* FROM acquisition_lots l JOIN lot_allocations a ON a.lot_id = l.lot_id WHERE a.event_id = ? GROUP BY l.lot_id ORDER BY l.lot_id", (event_id,)))
            lot_allocations = tuple(StoredLotAllocation(item["position_id"], item["lot_id"], item["source_account_id"], item["destination_account_id"], ExactValue(item["quantity_decimal"]), RationalAmount.from_storage_text(item["cost_rational"]) if item["cost_rational"] else None) for item in connection.execute("SELECT * FROM lot_allocations WHERE event_id = ? ORDER BY lot_id, position_id", (event_id,)))
            return StoredEvent(event, positions, components, documents, contributions, lots, lot_allocations)
        finally:
            connection.close()

    def put_balance_index(self, *, account_id: str, currency: str | None, instrument_id: str | None, as_of: date, value: ExactValue | None, rational_value: RationalAmount | None, completeness: str, data_revision: int) -> None:
        if (currency is None) == (instrument_id is None):
            raise ValueError("Genau Währung oder Instrument muss gesetzt sein")
        if value is not None and rational_value is not None:
            raise ValueError("Indexwert darf nur eine Zahlenrepräsentation enthalten")
        decimal_text = self._decimal(value)
        rational_text = rational_value.to_storage_text() if rational_value is not None else None
        if rational_text is not None and RationalAmount.from_storage_text(rational_text) != rational_value:
            raise ValueError("Rationalwert ist nicht kanonisch")
        asset_key = f"CURRENCY:{currency}" if currency is not None else f"INSTRUMENT:{instrument_id}"
        with self.transaction() as connection:
            current_revision = connection.execute("SELECT data_revision FROM app_state WHERE singleton = 1").fetchone()[0]
            if data_revision != current_revision:
                raise ValueError("Bestandsindex muss der aktuell veröffentlichten gemeinsamen Datenrevision entsprechen")
            connection.execute(
                "INSERT INTO balance_index(account_id, asset_key, currency, instrument_id, as_of, value_decimal, value_rational, completeness, data_revision) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(account_id, asset_key, as_of) DO UPDATE SET value_decimal=excluded.value_decimal, value_rational=excluded.value_rational, completeness=excluded.completeness, data_revision=excluded.data_revision",
                (account_id, asset_key, currency, instrument_id, as_of.isoformat(), decimal_text, rational_text, completeness, data_revision),
            )
