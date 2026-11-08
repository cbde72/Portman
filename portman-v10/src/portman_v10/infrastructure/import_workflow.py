"""Persistenter, begrenzter Importjob ohne produktive Buchungsübernahme."""
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import replace
import json
from pathlib import Path
import sqlite3
from threading import Event, RLock
from uuid import uuid4

from portman_v10.application.contracts import (
    ApplicationError, CommitImport, Conflict, ConflictDecision, DocumentUpload, DocumentUploadResult,
    ErrorCode, ImportDocumentResult, ImportJob, ImportPage, ImportPreview, ImportStart,
    RecordedDecision,
)
from portman_v10.infrastructure.document_storage import DocumentStorage
from portman_v10.infrastructure.parser_adapter import PortmanParserAdapter
from portman_v10.infrastructure.preview_codec import decode_preview, encode_preview
from portman_v10.infrastructure.sqlite_store import SQLiteStore


class ImportWorkflow:
    """Lokaler Adapter: Bytes ablegen, Hintergrundjob verarbeiten, Vorschau lesen."""

    def __init__(self, store: SQLiteStore, data_dir: str | Path, *, max_workers: int = 1):
        if not 1 <= max_workers <= 2:
            raise ValueError("Importworkflow erlaubt ein oder zwei Worker")
        Path(data_dir).resolve().mkdir(parents=True, exist_ok=True)
        store.path.parent.mkdir(parents=True, exist_ok=True)
        self.store = store
        self.store.migrate()
        self.storage = DocumentStorage(data_dir, store)
        self.parser = PortmanParserAdapter(store)
        self.executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="portman-v10-import")
        self._lock = RLock()
        self._cancel: dict[str, Event] = {}
        self._futures: dict[str, Future] = {}
        self.store.mark_interrupted_import_jobs()

    def upload_document(self, upload: DocumentUpload) -> DocumentUploadResult:
        document, duplicate = self.storage.add(upload)
        return DocumentUploadResult(document, duplicate)

    def get_document(self, document_id: str):
        return self.storage.open(document_id)

    def cleanup_temporary_files(self) -> int:
        return self.storage.cleanup_temporary()

    def start_import(self, value: ImportStart) -> ImportJob:
        document_ids = tuple(dict.fromkeys(value.document_ids))
        if value.account_hint and not self.store.account_exists(value.account_hint):
            raise ApplicationError(ErrorCode.UNRESOLVED_ACCOUNT, "Kontovorgabe ist unbekannt")
        for document_id in document_ids:
            try:
                record = self.store.document_record(document_id)
            except (sqlite3.Error, OSError, ValueError) as error:
                raise ApplicationError(ErrorCode.STORAGE_ERROR, "Dokumentmetadaten oder Originaldatei sind nicht lesbar") from error
            if record is None:
                raise ApplicationError(ErrorCode.NOT_FOUND, f"Dokument nicht gefunden: {document_id}")
        job_id, import_id = uuid4().hex, uuid4().hex
        job = ImportJob(job_id, import_id, "queued", 0, 1, None, len(document_ids), 0, False)
        try:
            self.store.create_import_job(job, document_ids, value.account_hint, self.parser.package_version, self.parser.api_version, self.parser.schema_version)
        except sqlite3.Error as error:
            raise ApplicationError(ErrorCode.STORAGE_ERROR, "Importjob konnte nicht dauerhaft angelegt werden") from error
        cancel = Event()
        with self._lock:
            self._cancel[job_id] = cancel
            self._futures[job_id] = self.executor.submit(self._run, job, document_ids, value.account_hint, cancel)
        return job

    def get_job(self, job_id: str) -> ImportJob:
        try:
            stored = self.store.load_import_job(job_id)
        except sqlite3.Error as error:
            raise ApplicationError(ErrorCode.STORAGE_ERROR, "Importjob konnte nicht gelesen werden") from error
        if stored is None:
            raise ApplicationError(ErrorCode.NOT_FOUND, "Importjob nicht gefunden")
        job, _ = stored
        if job.state == "failed" and job.error_code == ErrorCode.JOB_INTERRUPTED:
            return replace(job, error_code=ErrorCode.JOB_INTERRUPTED)
        return job

    def get_import_document_results(self, job_id: str) -> tuple[ImportDocumentResult, ...]:
        try:
            stored = self.store.load_import_job(job_id)
        except sqlite3.Error as error:
            raise ApplicationError(ErrorCode.STORAGE_ERROR, "Dokumentstatus konnte nicht gelesen werden") from error
        if stored is None:
            raise ApplicationError(ErrorCode.NOT_FOUND, "Importjob nicht gefunden")
        return stored[1]

    def cancel_job(self, job_id: str, expected_revision: int) -> ImportJob:
        with self._lock:
            stored = self.store.load_import_job(job_id)
            if stored is None:
                raise ApplicationError(ErrorCode.NOT_FOUND, "Importjob nicht gefunden")
            job, results = stored
            if job.revision != expected_revision:
                raise ApplicationError(ErrorCode.STALE_REVISION, "Job-Revision ist veraltet")
            if job.state not in {"queued", "running"}:
                return job
            cancel = self._cancel.get(job_id)
            if cancel:
                cancel.set()
            future = self._futures.get(job_id)
            if future is not None and future.cancel():
                updated = replace(job, state="cancelled", progress=100, revision=job.revision + 1)
            else:
                updated = replace(job, cancel_requested=True, revision=job.revision + 1)
            try:
                self.store.save_import_progress(updated, results, None, self._data_revision())
            except sqlite3.Error as error:
                raise ApplicationError(ErrorCode.STORAGE_ERROR, "Abbruchstatus konnte nicht gespeichert werden") from error
            return updated

    def get_import_preview(self, import_id: str) -> ImportPreview:
        try:
            bundle = self.store.load_import_preview_bundle(import_id)
        except sqlite3.Error as error:
            raise ApplicationError(ErrorCode.STORAGE_ERROR, "Importvorschau konnte nicht gelesen werden") from error
        if bundle is None:
            raise ApplicationError(ErrorCode.NOT_FOUND, "Importvorschau nicht gefunden")
        payload, revision, data_revision, stored_decisions = bundle
        preview = decode_preview(payload, revision=revision, data_revision=data_revision)
        decisions = []
        for candidate_id, candidate_revision, preview_revision, decision_json in stored_decisions:
            raw = json.loads(decision_json)
            decisions.append(RecordedDecision(candidate_id, candidate_revision, preview_revision, ConflictDecision(**raw)))
        return replace(preview, decisions=tuple(decisions))

    def resolve_import_item(self, import_id: str, decision: ConflictDecision, expected_revision: int) -> ImportPreview:
        preview = self.get_import_preview(import_id)
        if preview.revision != expected_revision:
            raise ApplicationError(ErrorCode.STALE_REVISION, "Vorschau-Revision ist veraltet")
        candidate = next((item for item in preview.items if item.candidate_id == decision.candidate_id), None)
        if candidate is None:
            raise ApplicationError(ErrorCode.NOT_FOUND, "Vorschaukandidat nicht gefunden")
        if candidate.revision != decision.candidate_revision:
            raise ApplicationError(ErrorCode.STALE_REVISION, "Kandidatenrevision ist veraltet")
        if decision.decision == "assign_account":
            if not decision.account_id or not self.store.account_exists(decision.account_id):
                raise ApplicationError(ErrorCode.UNRESOLVED_ACCOUNT, "Zielkonto unbekannt")
            assigned = replace(candidate, movements=tuple(replace(value, account_id=decision.account_id, account_assignment="user_hint") if value.account_id is None else value for value in candidate.movements),
                               missing_fields=tuple(value for value in candidate.missing_fields if "Kontozuordnung" not in value and "Konto" not in value))
            preview = replace(preview, items=tuple(assigned if item.candidate_id == candidate.candidate_id else item for item in preview.items))
            from portman_v10.infrastructure.preview_codec import encode_preview
            try:
                raw_preview = self.store.load_import_preview_json(import_id)
                from portman_v10.infrastructure.preview_codec import decode_preview
                decoded = decode_preview(raw_preview, revision=preview.revision, data_revision=preview.data_revision)
                normalized = replace(decoded, items=tuple(assigned if item.candidate_id == candidate.candidate_id else item for item in decoded.items))
                self.store.save_review_decision(import_id, decision.candidate_id, expected_revision, decision.candidate_revision,
                                                json.dumps({"candidate_id": decision.candidate_id, "decision": decision.decision,
                                                            "target_id": decision.target_id, "account_id": decision.account_id,
                                                            "candidate_revision": decision.candidate_revision}, sort_keys=True),
                                                preview_json=encode_preview(normalized))
            except (TypeError, sqlite3.Error, ValueError) as error:
                raise ApplicationError(ErrorCode.STORAGE_ERROR, "Kontozuordnung konnte nicht gespeichert werden") from error
            return self.get_import_preview(import_id)
        try:
            self.store.save_review_decision(import_id, decision.candidate_id, expected_revision, decision.candidate_revision,
                                            json.dumps({"candidate_id": decision.candidate_id, "decision": decision.decision,
                                                        "target_id": decision.target_id, "account_id": decision.account_id,
                                                        "candidate_revision": decision.candidate_revision}, sort_keys=True))
        except ValueError as error:
            raise ApplicationError(ErrorCode.STALE_REVISION, "Vorschau-Revision ist veraltet") from error
        except sqlite3.Error as error:
            raise ApplicationError(ErrorCode.STORAGE_ERROR, "Prüfentscheidung konnte nicht gespeichert werden") from error
        return self.get_import_preview(import_id)

    def commit_import(self, command: CommitImport):
        try:
            preview = self.get_import_preview(command.import_id)
            if preview.revision != command.preview_revision:
                # Replay wird im Store vor der Revisionsprüfung aufgelöst.
                return self.store.commit_import(command, preview, ())
            return self.store.commit_import(command, preview, preview.decisions)
        except ApplicationError:
            raise
        except Exception as error:
            raise ApplicationError(ErrorCode.STORAGE_ERROR, "Import konnte nicht atomar übernommen werden") from error

    def list_imports(self, cursor: str | None = None, limit: int = 100) -> ImportPage:
        """Listet Importläufe über den Anwendungsadapter mit stabiler Seitennavigation."""
        return self.store.list_imports(cursor, limit)

    def discard_import(self, import_id: str, expected_revision: int) -> ImportJob:
        """Verwirft eine offene Vorschau über den Anwendungskern."""
        return self.store.discard_import(import_id, expected_revision)

    def preview_rollback(self, selection):
        """Anwendungsschnittstelle für einzelne, ausgewählte oder ausdrücklich alle Importe."""
        return self.store.preview_rollback(selection)

    def execute_rollback(self, command):
        """Anwendungsschnittstelle; SQL bleibt im SQLiteStore gekapselt."""
        return self.store.execute_rollback(command)

    def get_overview(self, as_of, account_ids=()):
        """Liefert Bestände über den Anwendungsadapter aus dem persistenten Index."""
        return self.store.get_overview(as_of, account_ids)

    def _data_revision(self) -> int:
        connection = self.store.connect()
        try:
            return int(connection.execute("SELECT data_revision FROM app_state WHERE singleton=1").fetchone()[0])
        finally:
            connection.close()

    def _cancel_requested(self, job_id: str, event: Event) -> bool:
        if event.is_set():
            return True
        stored = self.store.load_import_job(job_id)
        return stored is None or stored[0].cancel_requested or stored[0].state == "cancelled"

    def _run(self, initial: ImportJob, document_ids: tuple[str, ...], account_hint: str | None, cancel: Event) -> None:
        try:
            self._execute(initial, document_ids, account_hint, cancel)
        except ApplicationError as error:
            if error.code != ErrorCode.STALE_REVISION:
                self._mark_job_failed(initial.job_id, error.code)
        except (sqlite3.Error, OSError):
            self._mark_job_failed(initial.job_id, ErrorCode.STORAGE_ERROR)
        except Exception:
            self._mark_job_failed(initial.job_id, ErrorCode.PARSER_ERROR)

    def _mark_job_failed(self, job_id: str, code: ErrorCode) -> None:
        try:
            with self._lock:
                stored = self.store.load_import_job(job_id)
                if stored is None or stored[0].state not in {"queued", "running"}:
                    return
                current, documents = stored
                failed = replace(current, state="failed", progress=100, revision=current.revision + 1, error_code=code)
                self.store.save_import_progress(failed, documents, self.store.load_import_preview_json(current.import_id), self._data_revision())
        except Exception:
            # Wenn SQLite selbst nicht verfügbar ist, verhindert der Neustart
            # einen dauerhaft sichtbaren running-Status über die Reaper-Regel.
            return

    def _execute(self, initial: ImportJob, document_ids: tuple[str, ...], account_hint: str | None, cancel: Event) -> None:
        initial_record = self.store.load_import_job(initial.job_id)
        document_names = {item.document_id: item.name for item in initial_record[1]} if initial_record else {}
        with self._lock:
            job = replace(initial, state="running", revision=initial.revision + 1)
            self.store.save_import_progress(job, (), None, self._data_revision())
        results: list[ImportDocumentResult] = []
        items = []
        warnings = []
        for index, document_id in enumerate(document_ids):
            if self._cancel_requested(job.job_id, cancel):
                for remaining in document_ids[index:]:
                    results.append(ImportDocumentResult(remaining, document_names.get(remaining, remaining), "cancelled", None, None, None, None, None, (), ErrorCode.CANCELLED))
                break
            try:
                metadata, internal_path = self.storage.internal_path(document_id)
                result, parsed_items, parsed_warnings = self.parser.parse_path(document_id, str(internal_path), metadata.name, account_hint)
                if self._cancel_requested(job.job_id, cancel):
                    result = replace(result, status="cancelled", error_code=ErrorCode.CANCELLED)
                results.append(result)
                if not self._cancel_requested(job.job_id, cancel):
                    items.extend(parsed_items)
                    warnings.extend(parsed_warnings)
            except ApplicationError as error:
                results.append(ImportDocumentResult(document_id, document_names.get(document_id, document_id), "failed", None, None, None, None, None, (error.message,), error.code))
            except Exception as error:
                results.append(ImportDocumentResult(document_id, document_names.get(document_id, document_id), "failed", None, None, None, None, None, (f"Unerwarteter Fehler ({type(error).__name__}) bei der Dokumentverarbeitung",), ErrorCode.PARSER_ERROR))
            with self._lock:
                latest = self.store.load_import_job(job.job_id)
                if latest is not None:
                    job = latest[0]
                job = replace(job, progress=min(99, int((index + 1) * 100 / len(document_ids))), revision=job.revision + 1,
                              completed_documents=index + 1, cancel_requested=self._cancel_requested(job.job_id, cancel))
                partial = ImportPreview(job.import_id, 1, self._data_revision(), tuple(self._classify_candidates(items)), tuple(results))
                self.store.save_import_progress(job, tuple(results), encode_preview(partial), partial.data_revision)
        was_cancelled = self._cancel_requested(job.job_id, cancel)
        state = "cancelled" if was_cancelled else "needs_review" if any(r.status in {"parsed", "needs_review", "information", "unsupported", "duplicate_file"} for r in results) else "failed"
        error_code = ErrorCode.CANCELLED if was_cancelled else None if state == "needs_review" else next((item.error_code for item in results if item.error_code), ErrorCode.PARSER_ERROR)
        with self._lock:
            latest = self.store.load_import_job(job.job_id)
            if latest is not None:
                job = latest[0]
            final = replace(job, state=state, progress=100, revision=job.revision + 1,
                            completed_documents=len(results), cancel_requested=was_cancelled, error_code=error_code)
            preview = ImportPreview(final.import_id, 1, self._data_revision(), tuple(self._classify_candidates(items)), tuple(results))
            self.store.save_import_progress(final, tuple(results), encode_preview(preview), preview.data_revision)

    def _classify_candidates(self, items):
        """Sichere Referenzen und exakte Finanzreport-Bewegungstreffer klassifizieren."""
        by_key = {}
        result = []
        for item in sorted(items, key=lambda value: (value.document_id, value.candidate_id)):
            connection = self.store.connect()
            try:
                linked_events = connection.execute("SELECT event_id,page_or_entry FROM event_documents WHERE document_id=? ORDER BY event_id", (item.document_id,)).fetchall()
            finally:
                connection.close()
            if linked_events:
                matching = tuple(value[0] for value in linked_events if value[1] == item.candidate_id)
                if len(matching) == 1:
                    result.append(replace(item, disposition="conflict", conflicts=(*item.conflicts, Conflict(
                        ErrorCode.POSSIBLE_DUPLICATE, "Diese Belegzeile ist bereits einem Vorgang zugeordnet", item.candidate_id, matching[0]))))
                    continue
                event_ids = tuple(value[0] for value in linked_events)
                if len(event_ids) == 1:
                    result.append(replace(item, disposition="conflict", conflicts=(*item.conflicts, Conflict(ErrorCode.POSSIBLE_DUPLICATE, "Dieser Dateiinhalt ist bereits einem Vorgang zugeordnet", item.candidate_id, event_ids[0]))))
                else:
                    result.append(replace(item, disposition="conflict", conflicts=(*item.conflicts, Conflict(ErrorCode.POSSIBLE_DUPLICATE, "Dieser Beleg ist mehreren Vorgängen zugeordnet; Zielentscheidung erforderlich", item.candidate_id))))
                continue
            reference = dict(item.references).get("bank_reference")
            reference_status = dict(item.references).get("bank_reference_status")
            cash_accounts = sorted({movement.account_id for movement in item.movements if movement.movement_type == "cash" and movement.account_id})
            key = (cash_accounts[0], reference.strip()) if reference and reference_status == "RECOGNIZED" and len(cash_accounts) == 1 else None
            if key is not None:
                connection = self.store.connect()
                try:
                    rows = connection.execute("SELECT event_id,kind FROM events WHERE reference_context=? AND bank_reference=?", (key[0], key[1])).fetchall()
                    if rows:
                        same = len(rows) == 1 and rows[0]["kind"] == item.kind
                        disposition = "complement" if same else "conflict"
                        code = ErrorCode.POSSIBLE_DUPLICATE if same else ErrorCode.SOURCE_CONFLICT
                        message = "Sichere Bankreferenz gehört zu einem vorhandenen Vorgang" if same else "Sichere Bankreferenz widerspricht einem vorhandenen Vorgang"
                        result.append(replace(item, disposition=disposition, conflicts=(*item.conflicts, Conflict(code, message, item.candidate_id, rows[0]["event_id"]))))
                        continue
                finally:
                    connection.close()
            if (item.plugin_id, item.handler_id, item.kind) == ("comdirect.finanzreport", "finanzreport", "CASH_BOOKING") and len(item.movements) == 1:
                movement = item.movements[0]
                if (movement.movement_type == "cash" and movement.account_id and movement.currency and movement.amount
                        and movement.date and movement.status == "ACTUAL"):
                    connection = self.store.connect()
                    try:
                        rows = connection.execute(
                            "SELECT DISTINCT e.event_id,e.kind FROM positions p JOIN events e ON e.event_id=p.event_id "
                            "WHERE p.account_id=? AND p.currency=? AND p.amount_decimal=? COLLATE PORTMAN_DECIMAL "
                            "AND p.effective_date=? ORDER BY e.event_id",
                            (movement.account_id, movement.currency, movement.amount.text, movement.date.isoformat()),
                        ).fetchall()
                    finally:
                        connection.close()
                    if rows:
                        related = rows[0]["event_id"] if len(rows) == 1 and rows[0]["kind"] == item.kind else None
                        message = ("Gleiche Konto-/Währungs-/Betrags-/Datumsposition gefunden; Vorgang prüfen und gezielt verknüpfen"
                                   if related else "Mögliche Dublette anhand gleicher Konto-/Währungs-/Betrags-/Datumsposition; Treffer sind mehrdeutig oder haben einen anderen Vorgangstyp")
                        result.append(replace(item, disposition="conflict", conflicts=(*item.conflicts, Conflict(
                            ErrorCode.POSSIBLE_DUPLICATE, message, item.candidate_id, related))))
                        continue
            reference = dict(item.references).get("bank_reference")
            reference_status = dict(item.references).get("bank_reference_status")
            cash_accounts = sorted({movement.account_id for movement in item.movements if movement.movement_type == "cash" and movement.account_id})
            key = (cash_accounts[0], reference.strip()) if reference and reference_status == "RECOGNIZED" and len(cash_accounts) == 1 else None
            if key is None:
                result.append(item)
                continue
            previous = by_key.get(key)
            if previous is None:
                by_key[key] = item
                result.append(item)
                continue
            if self._business_signature(previous) != self._business_signature(item):
                result.append(replace(item, disposition="conflict", conflicts=(*item.conflicts, Conflict(ErrorCode.SOURCE_CONFLICT, "Gleiche sichere Bankreferenz mit abweichenden Fachwerten", item.candidate_id, previous.candidate_id))))
            else:
                # Gleiche Referenz+gleiche Transaktion: mehrere Belege gehören zu einem Kandidaten.
                merged = replace(previous, document_id="|".join(sorted({previous.document_id, item.document_id})),
                                    document_name="; ".join(sorted({previous.document_name, item.document_name})),
                                    source_evidence=tuple(sorted(set((*previous.source_evidence, *item.source_evidence)), key=lambda value: (value.evidence_id, value.field or ""))),
                                    warnings=tuple(sorted(set((*previous.warnings, *item.warnings)), key=lambda value: (value.code, value.message))),
                                    components=tuple(sorted(set((*previous.components, *item.components)), key=lambda value: (value.category, value.kind, value.amount.text if value.amount else "", value.currency or ""))))
                result[result.index(previous)] = merged
                by_key[key] = merged
        ambiguous_rows = {}
        for index, item in enumerate(result):
            if (item.plugin_id, item.handler_id, item.kind) != ("comdirect.finanzreport", "finanzreport", "CASH_BOOKING"):
                continue
            if dict(item.references).get("bank_reference_status") == "RECOGNIZED" or len(item.movements) != 1:
                continue
            movement = item.movements[0]
            if movement.movement_type == "cash" and movement.account_id and movement.amount and movement.currency and movement.date:
                key = movement.account_id, movement.currency, movement.amount.text, movement.date.isoformat()
                ambiguous_rows.setdefault(key, []).append(index)
        for indices in ambiguous_rows.values():
            if len(indices) < 2:
                continue
            for index in indices:
                item = result[index]
                result[index] = replace(item, disposition="conflict", conflicts=(*item.conflicts, Conflict(
                    ErrorCode.POSSIBLE_DUPLICATE,
                    "Mehrere Finanzreportzeilen haben dasselbe Konto, dieselbe Währung, denselben Betrag und dasselbe Datum; einzeln fachlich prüfen",
                    item.candidate_id,
                )))
        return tuple(sorted(result, key=lambda value: (value.document_id, value.candidate_id)))

    @staticmethod
    def _business_signature(item):
        movements = tuple(sorted((value.movement_type, value.account_id, value.currency, value.instrument_id, value.amount.text if value.amount else None, value.date.isoformat() if value.date else None, value.direction) for value in item.movements))
        return item.kind, movements

    def wait(self, job_id: str, timeout: float | None = None) -> ImportJob:
        future = self._futures.get(job_id)
        if future is not None:
            future.result(timeout=timeout)
        return self.get_job(job_id)

    def close(self, *, wait: bool = True) -> None:
        self.executor.shutdown(wait=wait, cancel_futures=False)
