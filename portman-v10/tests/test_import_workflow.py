from io import BytesIO
from pathlib import Path
from threading import Event
from tempfile import TemporaryDirectory
from datetime import date
import unittest

from pypdf import PdfWriter

from portman_v10.application.contracts import (
    AccountIdentifier, AccountInput, ApplicationError, CommitImport, Conflict, ConflictDecision, OpeningBalanceInput,
    DocumentUpload, ErrorCode, ExecuteRollback, ImportDocumentResult, ImportJob, ImportStart, RollbackSelection,
    InstrumentInput,
)
from portman_v10.infrastructure.import_workflow import ImportWorkflow
from portman_v10.infrastructure.sqlite_store import SQLiteStore
from portman_v10.domain.values import ExactValue
from synthetic_pdf import make_text_pdf


COMDIRECT_BUY = """comdirect
Wertpapierkauf
Depotnummer: 123456
Stk. 0,125 Fonds DE0008474511
Provision EUR 1,50
Zu Ihren Lasten EUR 126,50
Valuta 01.07.2026
DE00 0000 0000 0000 0000 01"""


class ImportWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = SQLiteStore(self.root / "v10.sqlite")
        self.store.migrate()
        self.cash = self.store.save_account(AccountInput(
            "comdirect Giro", "cash", "checking", "comdirect", "EUR",
            identifiers=(AccountIdentifier("iban", "comdirect", "DE00000000000000000001"),),
        ), None)
        self.depot = self.store.save_account(AccountInput(
            "comdirect Depot", "position", "depot", "comdirect",
            identifiers=(AccountIdentifier("depot_number", "comdirect", "123456"),),
        ), None)
        self.instrument = self.store.save_instrument(InstrumentInput("Indexfonds", "fund", isin="DE0008474511"), None)
        self.workflow = ImportWorkflow(self.store, self.root)
        self.addCleanup(lambda: self.workflow.close())

    def _upload(self, text=COMDIRECT_BUY, name="comdirect.pdf"):
        return self.workflow.upload_document(DocumentUpload(name, make_text_pdf(text)))

    def _ready_preview(self, text=COMDIRECT_BUY, name="comdirect.pdf"):
        uploaded = self._upload(text, name)
        job = self.workflow.wait(self.workflow.start_import(ImportStart((uploaded.document.document_id,))).job_id, 10)
        preview = self.workflow.get_import_preview(job.import_id)
        self.assertEqual(len(preview.items), 1)
        item = preview.items[0]
        from dataclasses import replace
        candidate = replace(item, review_status="complete_candidate", missing_fields=(), disposition="unclassified",
                            movements=tuple(replace(value, account_assignment="exact_identifier") for value in item.movements))
        from portman_v10.infrastructure.preview_codec import encode_preview
        self.store.replace_import_preview_items(job.import_id, preview.revision, encode_preview(replace(preview, items=(candidate,))))
        preview = self.workflow.get_import_preview(job.import_id)
        decision = ConflictDecision(candidate.candidate_id, "accept", candidate_revision=candidate.revision)
        updated = self.workflow.resolve_import_item(job.import_id, decision, preview.revision)
        item = updated.items[0]
        return uploaded, job, updated

    def test_atomic_import_commit_replay_revision_and_reopen_index(self):
        uploaded, job, preview = self._ready_preview()
        command = CommitImport(job.import_id, preview.revision, "commit-once")
        report = self.workflow.commit_import(command)
        self.assertEqual(len(report.created_event_ids), 1)
        replay = self.workflow.commit_import(command)
        self.assertTrue(replay.replayed)
        self.assertEqual(report.event_ids, replay.event_ids)
        with self.assertRaises(ApplicationError) as reused:
            self.workflow.commit_import(CommitImport(job.import_id, preview.revision + 1, "commit-once"))
        self.assertEqual(reused.exception.code, ErrorCode.REQUEST_ID_REUSED)
        self.workflow.close()
        self.workflow = ImportWorkflow(SQLiteStore(self.root / "v10.sqlite"), self.root)
        reopened = self.store.load_event(report.event_ids[0])
        self.assertEqual(reopened.document_ids, (uploaded.document.document_id,))
        self.assertTrue(reopened.contributions)
        connection = self.store.connect()
        try:
            revision = connection.execute("SELECT data_revision FROM app_state").fetchone()[0]
            self.assertEqual(connection.execute("SELECT count(*) FROM events").fetchone()[0], 1)
            self.assertEqual(connection.execute("SELECT count(*) FROM positions").fetchone()[0], 2)
            self.assertTrue(all(row[0] == revision for row in connection.execute("SELECT data_revision FROM balance_index")))
            self.assertEqual(connection.execute("SELECT count(*) FROM balance_index").fetchone()[0], 2)
        finally:
            connection.close()
        overview = self.workflow.get_overview(date(2026, 7, 1))
        self.assertEqual(overview.data_revision, report.data_revision)
        self.assertEqual(len(overview.lines), 2)
        self.assertTrue(all(line.value is None and line.completeness == "unknown" for line in overview.lines))

    def test_list_imports_summary_sorting_and_revisioned_cursor(self):
        uploaded_a, job_a, preview_a = self._ready_preview(name="first-source.pdf")
        uploaded_b, job_b, _ = self._ready_preview(name="second-source.pdf")
        self.workflow.commit_import(CommitImport(job_a.import_id, preview_a.revision, "list-imports-commit"))

        first_page = self.workflow.list_imports(limit=1)
        self.assertEqual(first_page.items[0].import_id, job_b.import_id)
        self.assertEqual(first_page.items[0].job_id, job_b.job_id)
        self.assertEqual(first_page.items[0].filenames, (uploaded_b.document.name,))
        self.assertEqual(first_page.items[0].candidate_count, 1)
        self.assertEqual(first_page.items[0].import_status, "preview")
        self.assertFalse(first_page.items[0].committed)
        self.assertIsNotNone(first_page.next_cursor)

        second_page = self.workflow.list_imports(first_page.next_cursor, limit=1)
        self.assertEqual(second_page.items[0].import_id, job_a.import_id)
        self.assertEqual(second_page.items[0].filenames, (uploaded_a.document.name,))
        self.assertTrue(second_page.items[0].committed)
        self.assertEqual(second_page.items[0].import_status, "committed")
        self.assertEqual(second_page.items[0].job_status, "completed")

        stale_page = self.workflow.list_imports(limit=1)
        self.store.save_instrument(InstrumentInput("Indexfonds angepasst", "fund", isin="DE0008474511", instrument_id=self.instrument.instrument_id), self.instrument.revision)
        with self.assertRaises(ApplicationError) as stale:
            self.workflow.list_imports(stale_page.next_cursor, limit=1)
        self.assertEqual(stale.exception.code, ErrorCode.STALE_REVISION)

    def test_discard_preview_is_revision_checked_and_keeps_original_for_reimport(self):
        uploaded, job, preview = self._ready_preview()
        discarded = self.workflow.discard_import(job.import_id, preview.revision)
        self.assertEqual(discarded.state, "cancelled")
        self.assertEqual(self.workflow.get_job(job.job_id).state, "cancelled")
        with self.assertRaises(ApplicationError) as missing_preview:
            self.workflow.get_import_preview(job.import_id)
        self.assertEqual(missing_preview.exception.code, ErrorCode.NOT_FOUND)
        self.assertEqual(self.workflow.get_document(uploaded.document.document_id).metadata.document_id, uploaded.document.document_id)
        listed = next(item for item in self.workflow.list_imports().items if item.import_id == job.import_id)
        self.assertEqual(listed.import_status, "cancelled")
        self.assertEqual(listed.candidate_count, 0)

        with self.assertRaises(ApplicationError) as repeated:
            self.workflow.discard_import(job.import_id, preview.revision)
        self.assertEqual(repeated.exception.code, ErrorCode.VALIDATION_ERROR)

        # Der ursprüngliche Beleg kann ohne erneuten Upload wieder eingereicht werden.
        reimport = self.workflow.start_import(ImportStart((uploaded.document.document_id,)))
        self.workflow.wait(reimport.job_id, 10)
        self.assertEqual(self.workflow.get_import_preview(reimport.import_id).items[0].document_id, uploaded.document.document_id)

    def test_discard_preview_rejects_stale_revision_and_committed_import(self):
        _, job, preview = self._ready_preview()
        with self.assertRaises(ApplicationError) as stale:
            self.workflow.discard_import(job.import_id, preview.revision - 1)
        self.assertEqual(stale.exception.code, ErrorCode.STALE_REVISION)
        current = self.workflow.get_import_preview(job.import_id)
        self.workflow.commit_import(CommitImport(job.import_id, current.revision, "discard-guard-commit"))
        with self.assertRaises(ApplicationError) as committed:
            self.workflow.discard_import(job.import_id, current.revision)
        self.assertEqual(committed.exception.code, ErrorCode.VALIDATION_ERROR)

    def test_identical_real_purchases_without_safe_reference_remain_separate(self):
        first, job_a, preview_a = self._ready_preview(name="first.pdf")
        second, job_b, preview_b = self._ready_preview(name="second.pdf")
        self.workflow.commit_import(CommitImport(job_a.import_id, preview_a.revision, "buy-a"))
        # Zwei zuvor angezeigte Vorschauen werden vor zweiter Übernahme neu berechnet;
        # unterschiedliche, ungeprüfte Imports bekommen aktuelle Datenrevisionen.
        for job, preview in ((job_b, preview_b),):
            current_revision = self.workflow._data_revision()
            raw = self.store.load_import_preview_json(job.import_id)
            from portman_v10.infrastructure.preview_codec import decode_preview, encode_preview
            decoded = decode_preview(raw, revision=preview.revision, data_revision=current_revision)
            self.store.replace_import_preview_items(job.import_id, preview.revision, encode_preview(decoded))
            with self.store.transaction() as write:
                write.execute("UPDATE import_previews SET data_revision=? WHERE import_id=?", (current_revision, job.import_id))
        preview_b = self.workflow.get_import_preview(job_b.import_id)
        self.workflow.commit_import(CommitImport(job_b.import_id, preview_b.revision, "buy-b"))
        connection = self.store.connect()
        try:
            self.assertEqual(connection.execute("SELECT count(*) FROM events").fetchone()[0], 2)
            self.assertEqual(connection.execute("SELECT count(*) FROM positions").fetchone()[0], 4)
        finally:
            connection.close()

    def test_second_evidence_links_existing_event_without_duplicate_positions(self):
        first_upload, first_job, first_preview = self._ready_preview(name="primary.pdf")
        first_report = self.workflow.commit_import(CommitImport(first_job.import_id, first_preview.revision, "primary-commit"))
        second_upload, second_job, second_preview = self._ready_preview(name="confirmation.pdf")
        item = second_preview.items[0]
        from dataclasses import replace
        from portman_v10.infrastructure.preview_codec import encode_preview
        linked_candidate = replace(item, disposition="complement", conflicts=(Conflict(ErrorCode.POSSIBLE_DUPLICATE, "safe match", item.candidate_id, first_report.event_ids[0]),))
        self.store.replace_import_preview_items(second_job.import_id, second_preview.revision, encode_preview(replace(second_preview, items=(linked_candidate,))))
        second_preview = self.workflow.get_import_preview(second_job.import_id)
        self.workflow.resolve_import_item(second_job.import_id, ConflictDecision(item.candidate_id, "link", target_id=first_report.event_ids[0], candidate_revision=item.revision), second_preview.revision)
        second_preview = self.workflow.get_import_preview(second_job.import_id)
        report = self.workflow.commit_import(CommitImport(second_job.import_id, second_preview.revision, "confirmation-commit"))
        self.assertEqual(report.event_ids, first_report.event_ids)
        stored = self.store.load_event(report.event_ids[0])
        self.assertEqual(set(stored.document_ids), {first_upload.document.document_id, second_upload.document.document_id})
        self.assertEqual(len(stored.positions), 2)
        self.assertEqual(len([row for row in stored.components if row.component_type == "fee"]), 1)

    def test_complement_adds_missing_position_with_provenance_and_rollback_removes_it(self):
        from dataclasses import replace
        from portman_v10.infrastructure.preview_codec import encode_preview

        uploaded_a, job_a, preview_a = self._ready_preview(name="partial-primary.pdf")
        item_a = preview_a.items[0]
        cash = next(value for value in item_a.movements if value.movement_type == "cash")
        partial_item = replace(item_a, movements=(cash,))
        self.store.replace_import_preview_items(job_a.import_id, preview_a.revision,
                                                encode_preview(replace(preview_a, items=(partial_item,))))
        preview_a = self.workflow.get_import_preview(job_a.import_id)
        report_a = self.workflow.commit_import(CommitImport(job_a.import_id, preview_a.revision, "partial-primary-commit"))
        event_id = report_a.created_event_ids[0]
        self.assertEqual(len(self.store.load_event(event_id).positions), 1)

        writer = PdfWriter(clone_from=BytesIO(make_text_pdf(COMDIRECT_BUY)))
        writer.add_metadata({"/Title": "Teilbeleg mit Stückposition"})
        complement_pdf = BytesIO()
        writer.write(complement_pdf)
        uploaded_b = self.workflow.upload_document(DocumentUpload("quantity-complement.pdf", complement_pdf.getvalue()))
        job_b = self.workflow.wait(self.workflow.start_import(ImportStart((uploaded_b.document.document_id,))).job_id, 10)
        preview_b = self.workflow.get_import_preview(job_b.import_id)
        candidate_b = preview_b.items[0]
        from dataclasses import replace
        ready_b = replace(candidate_b, review_status="complete_candidate", missing_fields=(), disposition="unclassified",
                          movements=tuple(replace(value, account_assignment="exact_identifier") for value in candidate_b.movements))
        self.store.replace_import_preview_items(job_b.import_id, preview_b.revision,
                                                encode_preview(replace(preview_b, items=(ready_b,))))
        preview_b = self.workflow.get_import_preview(job_b.import_id)
        self.workflow.resolve_import_item(job_b.import_id,
                                          ConflictDecision(ready_b.candidate_id, "accept", candidate_revision=ready_b.revision),
                                          preview_b.revision)
        preview_b = self.workflow.get_import_preview(job_b.import_id)
        item_b = preview_b.items[0]
        linked_item = replace(item_b, disposition="complement",
                              conflicts=(Conflict(ErrorCode.POSSIBLE_DUPLICATE, "gleicher Vorgang", item_b.candidate_id, event_id),))
        self.store.replace_import_preview_items(job_b.import_id, preview_b.revision,
                                                encode_preview(replace(preview_b, items=(linked_item,))))
        preview_b = self.workflow.get_import_preview(job_b.import_id)
        self.workflow.resolve_import_item(job_b.import_id,
                                          ConflictDecision(item_b.candidate_id, "link", target_id=event_id, candidate_revision=item_b.revision),
                                          preview_b.revision)
        preview_b = self.workflow.get_import_preview(job_b.import_id)
        report_b = self.workflow.commit_import(CommitImport(job_b.import_id, preview_b.revision, "quantity-complement-commit"))
        self.assertEqual(report_b.linked_event_ids, (event_id,))
        stored = self.store.load_event(event_id)
        self.assertEqual(len(stored.positions), 2)
        self.assertEqual(len([value for value in stored.contributions if value.import_id == job_b.import_id and value.field_name.startswith("position:") and value.action == "create"]), 1)
        self.assertEqual(len(stored.document_ids), 2)

        rollback = self.workflow.preview_rollback(RollbackSelection((job_b.import_id,)))
        result = self.workflow.execute_rollback(ExecuteRollback(rollback.plan_id, rollback.revision, "quantity-complement-rollback"))
        self.assertEqual(result.retained_event_ids, (event_id,))
        self.assertEqual(len(self.store.load_event(event_id).positions), 1)
        self.assertEqual(set(self.store.load_event(event_id).document_ids), {uploaded_a.document.document_id})
        self.assertNotIn(uploaded_b.document.document_id, self.store.load_event(event_id).document_ids)

    def test_complement_position_conflict_is_reported_and_atomic(self):
        from dataclasses import replace
        from portman_v10.infrastructure.preview_codec import encode_preview

        _, job_a, preview_a = self._ready_preview(name="conflict-primary.pdf")
        item_a = preview_a.items[0]
        cash = next(value for value in item_a.movements if value.movement_type == "cash")
        partial_item = replace(item_a, movements=(cash,))
        self.store.replace_import_preview_items(job_a.import_id, preview_a.revision,
                                                encode_preview(replace(preview_a, items=(partial_item,))))
        preview_a = self.workflow.get_import_preview(job_a.import_id)
        report_a = self.workflow.commit_import(CommitImport(job_a.import_id, preview_a.revision, "conflict-primary-commit"))
        event_id = report_a.created_event_ids[0]
        before = self.store.load_event(event_id)

        _, job_b, preview_b = self._ready_preview(name="conflicting-complement.pdf")
        item_b = preview_b.items[0]
        cash_b = next(value for value in item_b.movements if value.movement_type == "cash")
        wrong_cash = replace(cash_b, amount=ExactValue("999"))
        mismatched = replace(item_b, movements=tuple(wrong_cash if value == cash_b else value for value in item_b.movements),
                             disposition="complement",
                             conflicts=(Conflict(ErrorCode.POSSIBLE_DUPLICATE, "gleicher Vorgang", item_b.candidate_id, event_id),))
        self.store.replace_import_preview_items(job_b.import_id, preview_b.revision,
                                                encode_preview(replace(preview_b, items=(mismatched,))))
        preview_b = self.workflow.get_import_preview(job_b.import_id)
        self.workflow.resolve_import_item(job_b.import_id,
                                          ConflictDecision(item_b.candidate_id, "link", target_id=event_id, candidate_revision=item_b.revision),
                                          preview_b.revision)
        preview_b = self.workflow.get_import_preview(job_b.import_id)
        with self.assertRaises(ApplicationError) as conflict:
            self.workflow.commit_import(CommitImport(job_b.import_id, preview_b.revision, "conflicting-complement-commit"))
        self.assertEqual(conflict.exception.code, ErrorCode.SOURCE_CONFLICT)
        self.assertEqual(self.store.load_event(event_id).positions, before.positions)
        self.assertEqual(self.store.load_event(event_id).document_ids, before.document_ids)
        connection = self.store.connect()
        try:
            self.assertEqual(connection.execute("SELECT status FROM imports WHERE import_id=?", (job_b.import_id,)).fetchone()[0], "preview")
        finally:
            connection.close()

    def test_identical_file_reimport_requires_link_and_does_not_duplicate_booking(self):
        first_upload, first_job, first_preview = self._ready_preview(name="original.pdf")
        first_report = self.workflow.commit_import(CommitImport(first_job.import_id, first_preview.revision, "original-commit"))

        repeated_upload = self._upload(name="renamed-copy.pdf")
        self.assertTrue(repeated_upload.identical_content_already_stored)
        self.assertEqual(repeated_upload.document.document_id, first_upload.document.document_id)
        repeated_job = self.workflow.wait(
            self.workflow.start_import(ImportStart((repeated_upload.document.document_id,))).job_id, 10
        )
        repeated_preview = self.workflow.get_import_preview(repeated_job.import_id)
        self.assertEqual(len(repeated_preview.items), 1)
        candidate = repeated_preview.items[0]
        self.assertEqual(candidate.disposition, "conflict")
        self.assertEqual(candidate.conflicts[0].related_event_id, first_report.event_ids[0])

        decision = ConflictDecision(candidate.candidate_id, "link", target_id=first_report.event_ids[0], candidate_revision=candidate.revision)
        repeated_preview = self.workflow.resolve_import_item(repeated_job.import_id, decision, repeated_preview.revision)
        report = self.workflow.commit_import(CommitImport(repeated_job.import_id, repeated_preview.revision, "repeat-commit"))

        self.assertEqual(report.created_event_ids, ())
        self.assertEqual(report.linked_event_ids, first_report.event_ids)
        stored = self.store.load_event(first_report.event_ids[0])
        self.assertEqual(stored.document_ids, (first_upload.document.document_id,))
        self.assertEqual(len(stored.positions), 2)
        connection = self.store.connect()
        try:
            self.assertEqual(connection.execute("SELECT count(*) FROM events").fetchone()[0], 1)
            self.assertEqual(connection.execute("SELECT count(*) FROM positions").fetchone()[0], 2)
            self.assertEqual(connection.execute("SELECT count(*) FROM import_contributions WHERE import_id=? AND event_id=? AND field_name LIKE 'position:%' AND action='link'",
                                                 (repeated_job.import_id, first_report.event_ids[0])).fetchone()[0], 2)
        finally:
            connection.close()

    def test_preview_candidate_order_is_canonical_and_reference_conflicts_are_held(self):
        uploaded = self._upload(name="multi.pdf")
        job = self.workflow.wait(self.workflow.start_import(ImportStart((uploaded.document.document_id,))).job_id, 10)
        preview = self.workflow.get_import_preview(job.import_id)
        self.assertEqual(len(preview.items), 1)
        item = preview.items[0]
        from dataclasses import replace
        duplicate = replace(item, candidate_id="zz-second", references=tuple((key, "VALID-REF-0001" if key == "bank_reference" else "RECOGNIZED" if key == "bank_reference_status" else value) for key, value in item.references))
        first = replace(item, references=tuple((key, "VALID-REF-0001" if key == "bank_reference" else "RECOGNIZED" if key == "bank_reference_status" else value) for key, value in item.references))
        forward = self.workflow._classify_candidates((duplicate, first))
        reverse = self.workflow._classify_candidates((first, duplicate))
        self.assertEqual(tuple(value.candidate_id for value in forward), tuple(value.candidate_id for value in reverse))
        self.assertEqual(sum(value.disposition == "conflict" for value in forward), 0)
        mismatch = replace(duplicate, movements=tuple(replace(value, amount=type(value.amount)("-127") if value.movement_type == "cash" else value.amount) for value in duplicate.movements))
        conflict_preview = self.workflow._classify_candidates((first, mismatch))
        self.assertTrue(any(value.conflicts for value in conflict_preview))

    def test_stale_preview_rejected_after_another_import_commit(self):
        _, first, first_preview = self._ready_preview(name="one.pdf")
        _, second, second_preview = self._ready_preview(name="two.pdf")
        self.workflow.commit_import(CommitImport(first.import_id, first_preview.revision, "stale-first"))
        with self.assertRaises(ApplicationError) as stale:
            self.workflow.commit_import(CommitImport(second.import_id, second_preview.revision, "stale-second"))
        self.assertEqual(stale.exception.code, ErrorCode.STALE_REVISION)
        connection = self.store.connect()
        try:
            self.assertEqual(connection.execute("SELECT count(*) FROM events").fetchone()[0], 1)
        finally:
            connection.close()

    def test_concurrent_commit_requests_with_same_request_id_commit_once(self):
        uploaded, job, preview = self._ready_preview()
        command = CommitImport(job.import_id, preview.revision, "concurrent-request")
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = tuple(executor.map(self.workflow.commit_import, (command, command)))
        self.assertEqual(sum(not value.replayed for value in results), 1)
        connection = self.store.connect()
        try:
            self.assertEqual(connection.execute("SELECT count(*) FROM events").fetchone()[0], 1)
            self.assertEqual(connection.execute("SELECT count(*) FROM operations WHERE request_id='concurrent-request'").fetchone()[0], 1)
        finally:
            connection.close()

    def test_commit_fault_rolls_back_every_write(self):
        uploaded, job, preview = self._ready_preview()
        original = self.store._insert_import_event
        def fail_after_insert(*args, **kwargs):
            original(*args, **kwargs)
            raise RuntimeError("synthetic fault after event insert")
        self.store._insert_import_event = fail_after_insert
        with self.assertRaises(ApplicationError):
            self.workflow.commit_import(CommitImport(job.import_id, preview.revision, "faulted"))
        connection = self.store.connect()
        try:
            for table in ("events", "positions", "event_components", "event_documents", "import_contributions", "operations", "balance_index"):
                self.assertEqual(connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0], 0, table)
            self.assertEqual(connection.execute("SELECT status FROM imports WHERE import_id=?", (job.import_id,)).fetchone()[0], "preview")
        finally:
            connection.close()
        self.store._insert_import_event = original
        _, repeat_job, repeat_preview = self._ready_preview(name="same-source-after-rollback.pdf")
        reimported = self.workflow.commit_import(CommitImport(repeat_job.import_id, repeat_preview.revision, "rollback-source-reimport"))
        self.assertEqual(len(reimported.created_event_ids), 1)
        self.assertEqual(self.workflow.get_document(uploaded.document.document_id).content, make_text_pdf(COMDIRECT_BUY))

    def test_rollback_preview_execution_replay_staleness_and_reopen(self):
        from datetime import date

        self.store.record_opening(OpeningBalanceInput("rollback-cash-opening", self.cash.account_id, date(2026, 1, 1), currency="EUR", amount=ExactValue("1000")))
        self.store.record_opening(OpeningBalanceInput("rollback-position-opening", self.depot.account_id, date(2026, 1, 1), instrument_id=self.instrument.instrument_id, quantity=ExactValue("5")))
        with self.store.transaction() as connection:
            revision = connection.execute("SELECT data_revision FROM app_state WHERE singleton=1").fetchone()[0]
            self.store._rebuild_balance_index(connection, revision)
        _, job, preview = self._ready_preview()
        committed = self.workflow.commit_import(CommitImport(job.import_id, preview.revision, "rollback-source-commit"))
        connection = self.store.connect()
        try:
            components = connection.execute("SELECT component_id FROM event_components WHERE event_id=?", (committed.created_event_ids[0],)).fetchall()
            self.assertEqual(len(components), 1)
            self.assertTrue(connection.execute("SELECT 1 FROM import_contributions WHERE event_id=? AND field_name LIKE 'component:%'", (committed.created_event_ids[0],)).fetchone())
            after_import_index = tuple(tuple(row) for row in connection.execute("SELECT account_id,asset_key,as_of,value_decimal,data_revision FROM balance_index ORDER BY account_id,asset_key,as_of"))
            self.assertIn((self.cash.account_id, "CURRENCY:EUR", "2026-07-01", "873.5", committed.data_revision), after_import_index)
            self.assertIn((self.depot.account_id, f"INSTRUMENT:{self.instrument.instrument_id}", "2026-07-01", "5.125", committed.data_revision), after_import_index)
        finally:
            connection.close()
        plan = self.workflow.preview_rollback(RollbackSelection((job.import_id,)))
        self.assertEqual(plan.affected_event_ids, committed.created_event_ids)
        self.assertTrue(plan.affected_contribution_ids)
        self.assertTrue(any(self.cash.account_id in item and "CURRENCY:EUR" in item for item in plan.balance_impacts))
        connection = self.store.connect()
        try:
            self.assertEqual(tuple(tuple(row) for row in connection.execute("SELECT account_id,asset_key,as_of,value_decimal,data_revision FROM balance_index ORDER BY account_id,asset_key,as_of")), after_import_index)
        finally:
            connection.close()
        command = ExecuteRollback(plan.plan_id, plan.revision, "rollback-source-once")
        report = self.workflow.execute_rollback(command)
        self.assertEqual(report.removed_import_ids, (job.import_id,))
        self.assertEqual(report.removed_event_ids, committed.created_event_ids)
        connection = self.store.connect()
        try:
            self.assertEqual(connection.execute("SELECT count(*) FROM event_components WHERE event_id=?", (committed.created_event_ids[0],)).fetchone()[0], 0)
            final_balances = {(row["account_id"], row["asset_key"], row["value_decimal"]) for row in connection.execute("SELECT account_id,asset_key,value_decimal FROM balance_index")}
            self.assertEqual(final_balances, {(self.cash.account_id, "CURRENCY:EUR", "1000"),
                                               (self.depot.account_id, f"INSTRUMENT:{self.instrument.instrument_id}", "5")})
        finally:
            connection.close()
        self.assertTrue(self.workflow.execute_rollback(command).replayed)
        with self.assertRaises(ApplicationError) as reused:
            self.workflow.execute_rollback(ExecuteRollback("different-plan", plan.revision, "rollback-source-once"))
        self.assertEqual(reused.exception.code, ErrorCode.REQUEST_ID_REUSED)
        with self.assertRaises(ApplicationError) as stale:
            self.workflow.execute_rollback(ExecuteRollback(plan.plan_id, plan.revision, "rollback-source-again"))
        self.assertEqual(stale.exception.code, ErrorCode.STALE_REVISION)
        self.workflow.close()
        reopened_store = SQLiteStore(self.root / "v10.sqlite")
        self.workflow = ImportWorkflow(reopened_store, self.root)
        self.assertTrue(self.workflow.execute_rollback(command).replayed)
        summary = self.workflow.list_imports().items[0]
        self.assertEqual(summary.import_status, "rolled_back")
        self.assertEqual(summary.job_status, "completed")
        self.assertTrue(summary.committed)  # Historische erfolgreiche Übernahme; aktueller Zustand steht in import_status.
        connection = reopened_store.connect()
        try:
            self.assertEqual(connection.execute("SELECT status FROM imports WHERE import_id=?", (job.import_id,)).fetchone()[0], "rolled_back")
            self.assertEqual(connection.execute("SELECT count(*) FROM events").fetchone()[0], 2)
            self.assertEqual(connection.execute("SELECT count(*) FROM balance_index").fetchone()[0], 2)
            self.assertEqual(connection.execute("SELECT count(*) FROM operations WHERE request_id='rollback-source-once'").fetchone()[0], 1)
        finally:
            connection.close()

    def test_rollback_shared_evidence_orders_and_auto_instrument_lifecycle(self):
        source = """comdirect\nWertpapierkauf\nDepotnummer: 123456\nWKN: A2H57N\nISIN: LU1681041973\nStk. 0,25 AIS-AM.E.H.D.F.EOC, WKN / ISIN: A2H57N / LU1681041973\nIBAN DE00000000000000000001\nValuta 02.05.2025\nZu Ihren Lasten EUR 49,92\nReferenz: A2HROLLBACK01"""

        def ready(text, name):
            uploaded = self._upload(text, name)
            job = self.workflow.wait(self.workflow.start_import(ImportStart((uploaded.document.document_id,))).job_id, 10)
            preview = self.workflow.get_import_preview(job.import_id)
            item = preview.items[0]
            self.workflow.resolve_import_item(job.import_id, ConflictDecision(item.candidate_id, "accept", candidate_revision=item.revision), preview.revision)
            return job, self.workflow.get_import_preview(job.import_id)

        job_a, preview_a = ready(source, "rollback-a.pdf")
        report_a = self.workflow.commit_import(CommitImport(job_a.import_id, preview_a.revision, "rollback-a-commit"))
        instrument_id = report_a.created_instrument_ids[0]
        writer = PdfWriter(clone_from=BytesIO(make_text_pdf(source)))
        writer.add_metadata({"/Title": "zweiter Beleg"})
        second_pdf = BytesIO()
        writer.write(second_pdf)
        uploaded_b = self.workflow.upload_document(DocumentUpload("rollback-b.pdf", second_pdf.getvalue()))
        job_b = self.workflow.wait(self.workflow.start_import(ImportStart((uploaded_b.document.document_id,))).job_id, 10)
        preview_b = self.workflow.get_import_preview(job_b.import_id)
        item_b = preview_b.items[0]
        from dataclasses import replace
        linked = replace(item_b, review_status="complete_candidate", missing_fields=(), disposition="complement",
                         movements=tuple(replace(value, account_assignment="exact_identifier") for value in item_b.movements),
                         original_text=self.store.load_event(report_a.event_ids[0]).event.original_text,
                         conflicts=(Conflict(ErrorCode.POSSIBLE_DUPLICATE, "same purchase", item_b.candidate_id, report_a.event_ids[0]),))
        from portman_v10.infrastructure.preview_codec import encode_preview
        self.store.replace_import_preview_items(job_b.import_id, preview_b.revision, encode_preview(replace(preview_b, items=(linked,))))
        preview_b = self.workflow.get_import_preview(job_b.import_id)
        self.workflow.resolve_import_item(job_b.import_id, ConflictDecision(item_b.candidate_id, "link", target_id=report_a.event_ids[0], candidate_revision=item_b.revision), preview_b.revision)
        preview_b = self.workflow.get_import_preview(job_b.import_id)
        self.workflow.commit_import(CommitImport(job_b.import_id, preview_b.revision, "rollback-b-commit"))
        with self.store.transaction() as connection:
            connection.execute("INSERT INTO import_contributions(contribution_id,import_id,event_id,document_id,source_kind,target_type,field_name,action,previous_value_text,value_text,created_at) VALUES('later-field',?,?,?,'import','event','original_text','set',NULL,'Belegergänzung','2026-11-07T00:00:00+01:00')",
                               (job_b.import_id, report_a.event_ids[0], uploaded_b.document.document_id))
            connection.execute("UPDATE events SET original_text='Manuelle spätere Notiz',revision=revision+1 WHERE event_id=?", (report_a.event_ids[0],))
            connection.execute("INSERT INTO import_contributions(contribution_id,event_id,source_kind,target_type,field_name,action,value_text,created_at) VALUES('manual-later-field',?,'manual','event','original_text','set','Manuelle spätere Notiz','2026-11-07T00:00:00+01:00')", (report_a.event_ids[0],))

        # A zurücknehmen: der von B belegte Kauf und das Instrument bleiben erhalten.
        plan_a = self.workflow.preview_rollback(RollbackSelection((job_a.import_id,)))
        self.assertNotIn(instrument_id, plan_a.removable_instrument_ids)
        rollback_a = self.workflow.execute_rollback(ExecuteRollback(plan_a.plan_id, plan_a.revision, "rollback-a"))
        self.assertEqual(rollback_a.retained_event_ids, report_a.event_ids)
        self.assertEqual(self.store.match_instrument_identifier("ISIN", "standard", "LU1681041973"), (instrument_id,))

        # Nach B verschwindet das letzte aktive Ereignis; die instrumenteigene Importherkunft erlaubt Bereinigung.
        plan_b = self.workflow.preview_rollback(RollbackSelection((job_b.import_id,)))
        self.assertIn(instrument_id, plan_b.removable_instrument_ids)
        rollback_b = self.workflow.execute_rollback(ExecuteRollback(plan_b.plan_id, plan_b.revision, "rollback-b"))
        self.assertEqual(rollback_b.retained_event_ids, report_a.event_ids)
        retained_event = self.store.load_event(report_a.event_ids[0])
        self.assertEqual(retained_event.event.original_text, "Manuelle spätere Notiz")
        self.assertEqual(retained_event.positions, ())
        self.assertEqual(self.store.match_instrument_identifier("ISIN", "standard", "LU1681041973"), ())

    def test_rollback_retains_manually_edited_import_instrument(self):
        source = """comdirect\nWertpapierkauf\nDepotnummer: 123456\nWKN: A2H57N\nISIN: LU1681041973\nStk. 0,25 AIS-AM.E.H.D.F.EOC, WKN / ISIN: A2H57N / LU1681041973\nIBAN DE00000000000000000001\nValuta 02.05.2025\nZu Ihren Lasten EUR 49,92\nReferenz: A2HMANUAL01"""
        _, job, preview = self._ready_preview(source, "rollback-manual-instrument.pdf")
        report = self.workflow.commit_import(CommitImport(job.import_id, preview.revision, "rollback-manual-commit"))
        instrument_id = report.created_instrument_ids[0]
        instrument = self.store.get_instrument(instrument_id)
        self.store.save_instrument(InstrumentInput("Manuell bearbeitet", instrument.asset_type, instrument_id=instrument_id), instrument.revision)
        plan = self.workflow.preview_rollback(RollbackSelection((job.import_id,)))
        self.assertNotIn(instrument_id, plan.removable_instrument_ids)
        result = self.workflow.execute_rollback(ExecuteRollback(plan.plan_id, plan.revision, "rollback-manual"))
        self.assertEqual(result.removed_instrument_ids, ())
        self.assertEqual(self.store.get_instrument(instrument_id).name, "Manuell bearbeitet")

    def test_rollback_creator_keeps_auto_instrument_used_by_another_import(self):
        source_a = """comdirect
Wertpapierkauf
Depotnummer: 123456
WKN: A2H57N
ISIN: LU1681041973
Stk. 0,25 AIS-AM.E.H.D.F.EOC, WKN / ISIN: A2H57N / LU1681041973
IBAN DE00000000000000000001
Valuta 02.05.2025
Zu Ihren Lasten EUR 49,92
Referenz: A2HSEPARATE01"""
        _, job_a, preview_a = self._ready_preview(source_a, "separate-a.pdf")
        report_a = self.workflow.commit_import(CommitImport(job_a.import_id, preview_a.revision, "separate-a-commit"))
        instrument_id = report_a.created_instrument_ids[0]
        source_b = source_a.replace("02.05.2025", "03.05.2025").replace("A2HSEPARATE01", "A2HSEPARATE02")
        _, job_b, preview_b = self._ready_preview(source_b, "separate-b.pdf")
        self.assertEqual(preview_b.items[0].instrument_resolution, "existing")
        report_b = self.workflow.commit_import(CommitImport(job_b.import_id, preview_b.revision, "separate-b-commit"))
        plan_a = self.workflow.preview_rollback(RollbackSelection((job_a.import_id,)))
        self.assertNotIn(instrument_id, plan_a.removable_instrument_ids)
        rolled_a = self.workflow.execute_rollback(ExecuteRollback(plan_a.plan_id, plan_a.revision, "separate-a-rollback"))
        self.assertEqual(rolled_a.removed_event_ids, report_a.created_event_ids)
        self.assertIsNotNone(self.store.load_event(report_b.created_event_ids[0]))
        self.assertEqual(self.store.match_instrument_identifier("ISIN", "standard", "LU1681041973"), (instrument_id,))

    def test_rollback_shared_event_second_source_first_then_creator(self):
        from dataclasses import replace
        from portman_v10.infrastructure.preview_codec import encode_preview

        source = COMDIRECT_BUY + "\nVermerk A"
        uploaded_a, job_a, preview_a = self._ready_preview(source, "order-a.pdf")
        report_a = self.workflow.commit_import(CommitImport(job_a.import_id, preview_a.revision, "order-a-commit"))
        uploaded_b = self._upload(source.replace("Vermerk A", "Vermerk B"), "order-b.pdf")
        job_b = self.workflow.wait(self.workflow.start_import(ImportStart((uploaded_b.document.document_id,))).job_id, 10)
        preview_b = self.workflow.get_import_preview(job_b.import_id)
        item_b = preview_b.items[0]
        linked = replace(item_b, review_status="complete_candidate", missing_fields=(), disposition="complement",
                          movements=tuple(replace(value, account_assignment="exact_identifier") for value in item_b.movements),
                          original_text=self.store.load_event(report_a.event_ids[0]).event.original_text,
                          conflicts=(Conflict(ErrorCode.POSSIBLE_DUPLICATE, "gleiche Referenz", item_b.candidate_id, report_a.event_ids[0]),))
        self.store.replace_import_preview_items(job_b.import_id, preview_b.revision, encode_preview(replace(preview_b, items=(linked,))))
        preview_b = self.workflow.get_import_preview(job_b.import_id)
        self.workflow.resolve_import_item(job_b.import_id, ConflictDecision(item_b.candidate_id, "link", target_id=report_a.event_ids[0], candidate_revision=item_b.revision), preview_b.revision)
        preview_b = self.workflow.get_import_preview(job_b.import_id)
        self.workflow.commit_import(CommitImport(job_b.import_id, preview_b.revision, "order-b-commit"))

        plan_b = self.workflow.preview_rollback(RollbackSelection((job_b.import_id,)))
        report_b = self.workflow.execute_rollback(ExecuteRollback(plan_b.plan_id, plan_b.revision, "order-b-rollback"))
        self.assertEqual(report_b.retained_event_ids, report_a.event_ids)
        self.assertEqual(len(self.store.load_event(report_a.event_ids[0]).positions), 2)
        plan_a = self.workflow.preview_rollback(RollbackSelection((job_a.import_id,)))
        report_a_rollback = self.workflow.execute_rollback(ExecuteRollback(plan_a.plan_id, plan_a.revision, "order-a-rollback"))
        self.assertEqual(report_a_rollback.removed_event_ids, report_a.event_ids)
        self.assertIsNone(self.store.load_event(report_a.event_ids[0]))
        # Interne Originale bleiben über Import-/Jobhistorie referenziert und externe Quelldateien werden nie gelöscht.
        self.assertEqual(self.workflow.get_document(uploaded_a.document.document_id).metadata.document_id, uploaded_a.document.document_id)
        self.assertEqual(self.workflow.get_document(uploaded_b.document.document_id).metadata.document_id, uploaded_b.document.document_id)

    def test_rollback_all_retains_manual_opening_and_fault_is_atomic(self):
        from datetime import date

        opening = self.store.record_opening(OpeningBalanceInput(
            "manual-cash-opening", self.cash.account_id, date(2026, 1, 1), currency="EUR", amount=ExactValue("500")))
        source = """comdirect
Wertpapierkauf
Depotnummer: 123456
WKN: A2H57N
ISIN: LU1681041973
Stk. 0,25 AIS-AM.E.H.D.F.EOC, WKN / ISIN: A2H57N / LU1681041973
IBAN DE00000000000000000001
Valuta 02.05.2025
Zu Ihren Lasten EUR 49,92
Referenz: A2HALL0001"""
        _, job, preview = self._ready_preview(source, "all-import.pdf")
        committed = self.workflow.commit_import(CommitImport(job.import_id, preview.revision, "all-import-commit"))
        created_instrument = committed.created_instrument_ids[0]
        _, job_b, preview_b = self._ready_preview(name="all-selection-second-import.pdf")
        committed_b = self.workflow.commit_import(CommitImport(job_b.import_id, preview_b.revision, "all-selection-second-commit"))
        selected_plan = self.workflow.preview_rollback(RollbackSelection((job.import_id, job_b.import_id)))
        self.assertEqual(set(selected_plan.import_ids), {job.import_id, job_b.import_id})
        plan = self.workflow.preview_rollback(RollbackSelection(all_imports=True))
        self.assertEqual(plan.import_ids, tuple(sorted((job.import_id, job_b.import_id))))
        self.assertTrue(plan.balance_impacts)
        original_rebuild = self.store._rebuild_balance_index

        def fail_during_index(connection, revision):
            original_rebuild(connection, revision)
            raise RuntimeError("synthetic rollback failure after index write")

        self.store._rebuild_balance_index = fail_during_index
        with self.assertRaises(ApplicationError) as failed:
            self.workflow.execute_rollback(ExecuteRollback(plan.plan_id, plan.revision, "all-rollback-fault"))
        self.assertEqual(failed.exception.code, ErrorCode.STORAGE_ERROR)
        self.store._rebuild_balance_index = original_rebuild
        connection = self.store.connect()
        try:
            self.assertEqual(connection.execute("SELECT status FROM imports WHERE import_id=?", (job.import_id,)).fetchone()[0], "committed")
            self.assertEqual(connection.execute("SELECT count(*) FROM events").fetchone()[0], 3)
            self.assertEqual(connection.execute("SELECT count(*) FROM operations WHERE request_id='all-rollback-fault'").fetchone()[0], 0)
            self.assertEqual(connection.execute("SELECT count(*) FROM instruments WHERE instrument_id=?", (created_instrument,)).fetchone()[0], 1)
        finally:
            connection.close()
        report = self.workflow.execute_rollback(ExecuteRollback(plan.plan_id, plan.revision, "all-rollback-retry"))
        self.assertEqual(set(report.removed_event_ids), set((*committed.created_event_ids, *committed_b.created_event_ids)))
        self.assertIsNotNone(self.store.load_event(opening.event_id))
        self.assertEqual(self.store.get_opening(opening.opening_id).source_kind, "manual")
        self.assertIsNotNone(self.store.get_account(self.cash.account_id))
        self.assertIsNotNone(self.store.get_instrument(self.instrument.instrument_id))
        self.assertEqual(self.store.match_instrument_identifier("ISIN", "standard", "LU1681041973"), ())

    def test_rollback_preview_reports_and_blocks_later_correction_dependency(self):
        _, job, preview = self._ready_preview(name="dependency-import.pdf")
        committed = self.workflow.commit_import(CommitImport(job.import_id, preview.revision, "dependency-commit"))
        with self.store.transaction() as connection:
            connection.execute("INSERT INTO events(event_id,kind,booking_date,completeness,correction_of_event_id,revision) VALUES('manual-correction','correction','2026-07-03','complete',?,1)", (committed.created_event_ids[0],))
        plan = self.workflow.preview_rollback(RollbackSelection((job.import_id,)))
        self.assertTrue(any("späterer Korrektur" in dependency for dependency in plan.unresolved_dependencies))
        with self.assertRaises(ApplicationError) as blocked:
            self.workflow.execute_rollback(ExecuteRollback(plan.plan_id, plan.revision, "dependency-rollback"))
        self.assertEqual(blocked.exception.code, ErrorCode.DEPENDENCY_CONFLICT)
        self.assertIsNotNone(self.store.load_event(committed.created_event_ids[0]))

    def test_rollback_keeps_manually_changed_field_but_removes_import_positions(self):
        source = """comdirect
Wertpapierkauf
Depotnummer: 123456
WKN: A2H57N
ISIN: LU1681041973
Stk. 0,25 AIS-AM.E.H.D.F.EOC, WKN / ISIN: A2H57N / LU1681041973
IBAN DE00000000000000000001
Valuta 02.05.2025
Zu Ihren Lasten EUR 49,92
Referenz: A2HMANUALFIELD"""
        _, job, preview = self._ready_preview(source, "manual-field.pdf")
        committed = self.workflow.commit_import(CommitImport(job.import_id, preview.revision, "manual-field-commit"))
        event_id = committed.created_event_ids[0]
        with self.store.transaction() as connection:
            # Historischer Datensatz vor 0006: nur der Eventbeitrag, keine Positionsbeiträge.
            connection.execute("DELETE FROM import_contributions WHERE event_id=? AND field_name LIKE 'position:%'", (event_id,))
            connection.execute("UPDATE events SET original_text='Manuelle spätere Notiz',revision=revision+1 WHERE event_id=?", (event_id,))
            connection.execute("INSERT INTO import_contributions(contribution_id,event_id,source_kind,target_type,field_name,action,value_text,created_at) VALUES('manual-field',?,'manual','event','original_text','set','Manuelle spätere Notiz','2026-11-07T00:00:00+01:00')", (event_id,))
        plan = self.workflow.preview_rollback(RollbackSelection((job.import_id,)))
        self.assertTrue(plan.balance_impacts)
        report = self.workflow.execute_rollback(ExecuteRollback(plan.plan_id, plan.revision, "manual-field-rollback"))
        self.assertEqual(report.retained_event_ids, (event_id,))
        self.assertEqual(len(report.removed_position_ids), 2)
        retained = self.store.load_event(event_id)
        self.assertEqual(retained.event.original_text, "Manuelle spätere Notiz")
        self.assertEqual(retained.positions, ())
        self.assertEqual(self.store.match_instrument_identifier("ISIN", "standard", "LU1681041973"), ())

    def test_real_pinned_comdirect_handler_upload_preview_and_reopen(self):
        other_context = self.store.save_account(AccountInput(
            "Unrelated identifier context", "cash", "checking", "another bank", "EUR",
            identifiers=(AccountIdentifier("iban", "another-bank", "DE00000000000000000001"),),
        ), None)
        source = make_text_pdf(COMDIRECT_BUY)
        uploaded = self.workflow.upload_document(DocumentUpload("../purchase.pdf", source))
        job = self.workflow.start_import(ImportStart((uploaded.document.document_id,)))
        done = self.workflow.wait(job.job_id, 10)
        self.assertEqual(done.state, "needs_review")
        self.assertEqual(done.completed_documents, 1)
        preview = self.workflow.get_import_preview(job.import_id)
        self.assertEqual(preview.documents[0].handler_id, "wertpapierkauf")
        self.assertEqual(preview.documents[0].parser_package_version, "0.7.0")
        self.assertEqual(preview.documents[0].parser_api_version, "0.6")
        self.assertTrue(preview.documents[0].extraction_preparation_version)
        item = preview.items[0]
        self.assertEqual(item.document_name, "purchase.pdf")
        self.assertEqual(item.plugin_version, "2.0")
        self.assertEqual(item.parser_schema_version, "1.6.0")
        self.assertEqual(item.parser_package_version, "0.7.0")
        self.assertEqual(item.parser_api_version, "0.6")
        self.assertEqual(set(item.account_ids), {self.cash.account_id, self.depot.account_id})
        self.assertNotIn(other_context.account_id, item.account_ids)
        self.assertEqual(item.instrument_ids, (self.instrument.instrument_id,))
        self.assertEqual([(m.movement_type, m.amount.text) for m in item.movements], [("cash", "-126.5"), ("quantity", "0.125")])
        self.assertEqual([m.account_assignment for m in item.movements], ["exact_identifier", "exact_identifier"])
        self.assertEqual([(c.kind, c.amount.text, c.counts_as_movement) for c in item.components if c.amount is not None], [("provision", "1.5", False), ("settlement_amount", "126.5", False)])
        self.assertTrue(any(component.kind == "price" and component.amount is None for component in item.components))
        self.assertEqual(next(value for value in item.dates if value.meaning == "trade_date").unknown_reason, "not_found")
        self.assertTrue(item.original_text and "Wertpapierkauf" in item.original_text)
        self.assertTrue(item.source_evidence)
        self.assertEqual(item.review_status, "needs_review")

        second_upload = self.workflow.upload_document(DocumentUpload("another-name.pdf", source))
        self.assertTrue(second_upload.identical_content_already_stored)
        self.assertEqual(second_upload.document.document_id, uploaded.document.document_id)
        self.assertEqual(len(tuple((self.root / "documents").rglob("*.pdf"))), 1)
        self.assertEqual(self.workflow.get_document(uploaded.document.document_id).content, source)

        self.workflow.close()
        self.workflow = ImportWorkflow(SQLiteStore(self.root / "v10.sqlite"), self.root)
        reopened = self.workflow.get_import_preview(job.import_id)
        self.assertEqual(reopened.items, preview.items)
        self.assertEqual(self.workflow.get_document(uploaded.document.document_id).content, source)
        connection = self.store.connect()
        try:
            self.assertEqual(connection.execute("SELECT count(*) FROM events").fetchone()[0], 0)
            self.assertEqual(connection.execute("SELECT count(*) FROM positions").fetchone()[0], 0)
        finally:
            connection.close()

    def test_comdirect_purchase_uses_event_isin_for_instrument_match(self):
        from portman_v10.infrastructure.parser_adapter import _resolve_instrument

        matched = self.store.save_instrument(InstrumentInput(
            "Lang & Schwarz", "equity", isin="DE000LS9AVX3", wkn="LS9AVX",
        ))
        # Der Parser liefert die Sicherheitskennung zusätzlich direkt am Event.
        self.assertEqual(_resolve_instrument(self.store, "DE000LS9AVX3", "LS9AVX", None), (matched.instrument_id, None))

        source = """comdirect
Wertpapierkauf
Depotnummer: 123456
WKN: LS9AVX
ISIN: DE000LS9AVX3
Nennwert Zum Kurs von
St. 0,007 EUR 3.471,31
Kurswert : EUR 24,30
Valuta 01.07.2026
Zu Ihren Lasten EUR 24,30
Steuerliche Behandlung: Wertpapierkauf Nr. 91182283 vom 01.07.2026
Stk. 0,007 LANG+SCHWARZ O.E. INDEX , WKN / ISIN: LS9AVX / DE000LS9AVX3
IBAN DE00000000000000000001"""
        uploaded = self._upload(source, "structured-purchase.pdf")
        job = self.workflow.wait(self.workflow.start_import(ImportStart((uploaded.document.document_id,))).job_id, 10)
        item = self.workflow.get_import_preview(job.import_id).items[0]
        self.assertEqual(dict(item.references)["security_isin"], "DE000LS9AVX3")
        self.assertEqual(dict(item.references)["security_wkn"], "LS9AVX")
        self.assertEqual(item.instrument_ids, (matched.instrument_id,))
        self.assertFalse(any("V10-Instrument" in value for value in item.missing_fields))

    def test_instrument_resolution_wkn_fallback_conflicts_and_multiple_hits(self):
        from portman_v10.infrastructure.parser_adapter import _resolve_instrument

        wkn_only = self.store.save_instrument(InstrumentInput("WKN only", "fund", wkn="ABC123"))
        self.assertEqual(_resolve_instrument(self.store, None, "ABC123", None), (wkn_only.instrument_id, None))
        self.assertIn("Kein V10-Instrument", _resolve_instrument(self.store, None, "NOHIT1", None)[1])

        self.store.save_instrument(InstrumentInput("Conflict A", "equity", isin="DE0001111111", wkn="AAA111"))
        self.store.save_instrument(InstrumentInput("Conflict B", "equity", isin="DE0002222222", wkn="BBB222"))
        conflict_id, conflict_reason = _resolve_instrument(self.store, "DE0001111111", "BBB222", "DE0001111111")
        self.assertIsNone(conflict_id)
        self.assertIn("Widersprüchliche ISIN/WKN", conflict_reason)

        duplicate_isin = "DE0003333333"
        self.store.save_instrument(InstrumentInput("Duplicate A", "equity", isin=duplicate_isin))
        self.store.save_instrument(InstrumentInput("Duplicate B", "equity", isin=duplicate_isin))
        duplicate_id, duplicate_reason = _resolve_instrument(self.store, duplicate_isin, None, duplicate_isin)
        self.assertIsNone(duplicate_id)
        self.assertIn("Mehrere V10-Instrumente", duplicate_reason)

    def test_real_pinned_comdirect_sale_and_income_handlers_require_safe_account_reference(self):
        samples = (
            ("wertpapierverkauf", "comdirect\nWertpapierverkauf\nStk. 1,000 Fonds DE0008474511\nZu Ihren Gunsten EUR 100,00\nDepotnummer: 123456\nIBAN DE00000000000000000001\nValuta 01.07.2026", ["-1", "100"]),
            ("dividendengutschrift", "comdirect\nAbrechnung Dividendengutschrift\nBruttoertrag EUR 5,00\nZu Ihren Gunsten EUR 3,68\nStk. 1,000 Fonds DE0008474511\nDepotnummer: 123456\nIBAN DE00000000000000000001\nValuta 01.07.2026", ["3.68"]),
            ("einloesung", "comdirect\nAbrechnung Einlösung\nStk. 1,000 Fonds DE0008474511\nZu Ihren Gunsten EUR 100,00\nDepotnummer: 123456\nIBAN DE00000000000000000001\nValuta 01.07.2026", ["100", "-1"]),
        )
        for handler, source, _expected in samples:
            with self.subTest(handler=handler):
                uploaded = self._upload(source, f"{handler}.pdf")
                job = self.workflow.wait(self.workflow.start_import(ImportStart((uploaded.document.document_id,))).job_id, 10)
                preview = self.workflow.get_import_preview(job.import_id)
                self.assertEqual(preview.documents[0].handler_id, handler)
                self.assertTrue(preview.items)
                self.assertEqual(preview.items[0].review_status, "needs_review")
                self.assertTrue(any("Bankreferenz" in value for value in preview.items[0].missing_fields))

    def test_commit_rejects_pp_handler_even_if_preview_is_incorrectly_marked_complete(self):
        from dataclasses import replace
        from portman_v10.infrastructure.preview_codec import encode_preview

        source = "comdirect\nWertpapierverkauf\nStk. 1,000 Fonds DE0008474511\nZu Ihren Gunsten EUR 100,00\nDepotnummer: 123456\nIBAN DE00000000000000000001\nValuta 01.07.2026"
        uploaded = self._upload(source, "held-sale.pdf")
        job = self.workflow.wait(self.workflow.start_import(ImportStart((uploaded.document.document_id,))).job_id, 10)
        preview = self.workflow.get_import_preview(job.import_id)
        candidate = replace(preview.items[0], plugin_id="portfolio-performance.comdirect", review_status="complete_candidate", missing_fields=(), warnings=())
        preview = replace(preview, items=(candidate,))
        self.store.replace_import_preview_items(job.import_id, preview.revision, encode_preview(preview))
        self.workflow.resolve_import_item(job.import_id, ConflictDecision(candidate.candidate_id, "accept"), preview.revision)
        with self.assertRaises(ApplicationError) as rejected:
            self.workflow.commit_import(CommitImport(job.import_id, preview.revision + 1, "blocked-sale"))
        self.assertEqual(rejected.exception.code, ErrorCode.UNSUPPORTED_DOCUMENT)

    def test_real_parser_comdirect_sale_creates_signed_cash_and_quantity_once(self):
        source = """comdirect
Wertpapierverkauf
Depotnummer: 123456
Stk. 1,000 Fonds, WKN / ISIN: ABC123 / DE0008474511
IBAN DE00000000000000000001
Zu Ihren Gunsten EUR 100,00
Valuta 01.07.2026
Referenz: SELLREF0001"""
        uploaded = self._upload(source, "sale-with-reference.pdf")
        job = self.workflow.wait(self.workflow.start_import(ImportStart((uploaded.document.document_id,))).job_id, 10)
        preview = self.workflow.get_import_preview(job.import_id)
        item = preview.items[0]
        self.assertEqual((preview.documents[0].handler_id, item.kind, item.review_status), ("wertpapierverkauf", "SELL", "complete_candidate"))
        self.assertEqual([(value.movement_type, value.amount.text) for value in item.movements], [("cash", "100"), ("quantity", "-1")])
        self.workflow.resolve_import_item(job.import_id, ConflictDecision(item.candidate_id, "accept", candidate_revision=item.revision), preview.revision)
        current = self.workflow.get_import_preview(job.import_id)
        report = self.workflow.commit_import(CommitImport(job.import_id, current.revision, "real-parser-sale"))
        self.assertEqual(len(report.created_event_ids), 1)
        connection = self.store.connect()
        try:
            rows = connection.execute("SELECT currency,amount_decimal,instrument_id,quantity_decimal FROM positions").fetchall()
            self.assertCountEqual([(row[0], row[1], row[2], row[3]) for row in rows], [("EUR", "100", None, None), (None, None, self.instrument.instrument_id, "-1")])
        finally:
            connection.close()

    def test_real_parser_dividend_uses_cash_credit_without_depot_quantity(self):
        source = """comdirect
Abrechnung Dividendengutschrift
Zu Ihren Gunsten EUR 3,68
Stk. 1,000 Fonds, WKN / ISIN: ABC123 / DE0008474511
IBAN DE00000000000000000001
Valuta 01.07.2026
Referenz: DIVREF0001"""
        uploaded = self._upload(source, "dividend-with-reference.pdf")
        job = self.workflow.wait(self.workflow.start_import(ImportStart((uploaded.document.document_id,))).job_id, 10)
        preview = self.workflow.get_import_preview(job.import_id)
        item = preview.items[0]
        self.assertEqual((preview.documents[0].handler_id, item.kind, item.review_status), ("dividendengutschrift", "DIVIDEND", "complete_candidate"))
        self.assertEqual([(value.movement_type, value.amount.text) for value in item.movements], [("cash", "3.68")])
        self.workflow.resolve_import_item(job.import_id, ConflictDecision(item.candidate_id, "accept", candidate_revision=item.revision), preview.revision)
        current = self.workflow.get_import_preview(job.import_id)
        self.workflow.commit_import(CommitImport(job.import_id, current.revision, "real-parser-dividend"))
        connection = self.store.connect()
        try:
            rows = connection.execute("SELECT currency,amount_decimal,instrument_id,quantity_decimal FROM positions").fetchall()
            self.assertEqual([(row[0], row[1], row[2], row[3]) for row in rows], [("EUR", "3.68", None, None)])
        finally:
            connection.close()

    def test_real_parser_redemption_and_income_interest_handlers_have_distinct_effects(self):
        samples = (
            ("einloesung", "Abrechnung Einlösung\nStk. 1,000 Fonds, WKN / ISIN: ABC123 / DE0008474511\nDepotnummer: 123456\nIBAN DE00000000000000000001\nZu Ihren Gunsten EUR 100,00\nValuta 01.07.2026\nReferenz: REDEMPTION0001", [("cash", "100"), ("quantity", "-1")]),
            ("ertragsgutschrift", "Abrechnung Ertragsgutschrift\nZinsgutschrift EUR 5,00\nZu Ihren Gunsten EUR 5,00\nIBAN DE00000000000000000001\nValuta 01.07.2026\nReferenz: INCOME00001", [("cash", "5")]),
        )
        for handler, source, expected_movements in samples:
            with self.subTest(handler=handler):
                uploaded = self._upload("comdirect\n" + source, f"{handler}-with-reference.pdf")
                job = self.workflow.wait(self.workflow.start_import(ImportStart((uploaded.document.document_id,))).job_id, 10)
                preview = self.workflow.get_import_preview(job.import_id)
                item = preview.items[0]
                self.assertEqual(preview.documents[0].handler_id, handler)
                self.assertEqual(item.review_status, "complete_candidate")
                self.assertEqual([(value.movement_type, value.amount.text) for value in item.movements], expected_movements)
                self.workflow.resolve_import_item(job.import_id, ConflictDecision(item.candidate_id, "accept", candidate_revision=item.revision), preview.revision)
                current = self.workflow.get_import_preview(job.import_id)
                report = self.workflow.commit_import(CommitImport(job.import_id, current.revision, f"real-parser-{handler}"))
                self.assertEqual(len(report.created_event_ids), 1)

    def test_a2h57n_purchase_parser_preserves_quarter_share_and_identifier(self):
        source = """comdirect
Wertpapierkauf
Depotnummer: 123456
WKN: A2H57N
ISIN: LU1681041973
Nennwert Zum Kurs von
St. 0,25 EUR 199,68
Kurswert : EUR 49,92
Valuta 02.05.2025
Zu Ihren Lasten EUR 49,92
Steuerliche Behandlung: Wertpapierkauf Nr. 266D25000000001 vom 02.05.2025
Stk. 0,25 AIS-AM.E.H.D.F.EOC, WKN / ISIN: A2H57N / LU1681041973
IBAN DE00000000000000000001"""
        uploaded = self._upload(source, "synthetic-a2h57n-buy.pdf")
        job = self.workflow.wait(self.workflow.start_import(ImportStart((uploaded.document.document_id,))).job_id, 10)
        preview = self.workflow.get_import_preview(job.import_id)
        item = preview.items[0]
        self.assertEqual(preview.documents[0].handler_id, "wertpapierkauf")
        self.assertEqual(dict(item.references)["security_wkn"], "A2H57N")
        self.assertEqual(dict(item.references)["security_isin"], "LU1681041973")
        self.assertEqual([(movement.movement_type, movement.amount.text) for movement in item.movements], [("cash", "-49.92"), ("quantity", "0.25")])
        self.assertTrue(item.source_evidence)

    def test_a2h57n_confirmed_import_creates_instrument_once_and_reuses_it(self):
        from portman_v10.application.contracts import CommitImport

        source = """comdirect
Wertpapierkauf
Depotnummer: 123456
WKN: A2H57N
ISIN: LU1681041973
Nennwert Zum Kurs von
St. 0,25 EUR 199,68
Kurswert : EUR 49,92
Valuta 02.05.2025
Zu Ihren Lasten EUR 49,92
Steuerliche Behandlung: Wertpapierkauf Nr. 266D25000000001 vom 02.05.2025
Stk. 0,25 AIS-AM.E.H.D.F.EOC, WKN / ISIN: A2H57N / LU1681041973
IBAN DE00000000000000000001
Referenz: A2HBUY000001"""

        def preview_for(document_text, document_name):
            uploaded = self._upload(document_text, document_name)
            job = self.workflow.wait(self.workflow.start_import(ImportStart((uploaded.document.document_id,))).job_id, 10)
            return uploaded, job, self.workflow.get_import_preview(job.import_id)

        uploaded, job, preview = preview_for(source, "a2h57n-original.pdf")
        item = preview.items[0]
        self.assertEqual(item.instrument_resolution, "will_create")
        self.assertEqual(item.instrument_message, "Neues Instrument wird angelegt: AIS-AM.E.H.D.F.EOC (LU1681041973)")
        self.assertEqual(item.review_status, "complete_candidate")
        self.assertEqual(self.store.match_instrument_identifier("ISIN", "standard", "LU1681041973"), ())
        self.workflow.resolve_import_item(job.import_id, ConflictDecision(item.candidate_id, "accept", candidate_revision=item.revision), preview.revision)
        preview = self.workflow.get_import_preview(job.import_id)
        committed = self.workflow.commit_import(CommitImport(job.import_id, preview.revision, "a2h57n-create"))
        self.assertEqual(len(committed.created_event_ids), 1)
        self.assertEqual(len(committed.created_instrument_ids), 1)
        instrument_id = committed.created_instrument_ids[0]
        replay = self.workflow.commit_import(CommitImport(job.import_id, preview.revision, "a2h57n-create"))
        self.assertTrue(replay.replayed)
        self.assertEqual(replay.created_instrument_ids, (instrument_id,))
        self.assertEqual(self.store.match_instrument_identifier("ISIN", "standard", "LU1681041973"), (instrument_id,))
        self.assertEqual(self.store.get_instrument(instrument_id).asset_type, "security")
        event = self.store.load_event(committed.created_event_ids[0])
        self.assertEqual([(position.instrument_id, position.quantity.text) for position in event.positions if position.instrument_id], [(instrument_id, "0.25")])

        repeated_upload, repeated_job, repeated_preview = preview_for(source, "a2h57n-repeat.pdf")
        repeated = repeated_preview.items[0]
        self.assertEqual(repeated.disposition, "conflict")
        self.workflow.resolve_import_item(repeated_job.import_id, ConflictDecision(
            repeated.candidate_id, "link", target_id=committed.created_event_ids[0], candidate_revision=repeated.revision
        ), repeated_preview.revision)
        repeated_preview = self.workflow.get_import_preview(repeated_job.import_id)
        repeated_report = self.workflow.commit_import(CommitImport(repeated_job.import_id, repeated_preview.revision, "a2h57n-repeat"))
        self.assertEqual(repeated_report.created_event_ids, ())
        self.assertEqual(repeated_report.created_instrument_ids, ())
        self.assertEqual(repeated_report.linked_event_ids, committed.created_event_ids)

        second_source = source.replace("02.05.2025", "03.05.2025").replace("A2HBUY000001", "A2HBUY000002")
        _, second_job, second_preview = preview_for(second_source, "a2h57n-second.pdf")
        second_item = second_preview.items[0]
        self.assertEqual(second_item.instrument_resolution, "existing")
        self.assertEqual(second_item.instrument_ids, (instrument_id,))
        self.workflow.resolve_import_item(second_job.import_id, ConflictDecision(
            second_item.candidate_id, "accept", candidate_revision=second_item.revision
        ), second_preview.revision)
        second_preview = self.workflow.get_import_preview(second_job.import_id)
        second_report = self.workflow.commit_import(CommitImport(second_job.import_id, second_preview.revision, "a2h57n-second"))
        self.assertEqual(len(second_report.created_event_ids), 1)
        self.assertEqual(second_report.created_instrument_ids, ())
        self.assertEqual(self.store.match_instrument_identifier("ISIN", "standard", "LU1681041973"), (instrument_id,))
        self.assertEqual(uploaded.document.document_id, repeated_upload.document.document_id)

    def test_failed_a2h57n_commit_rolls_back_new_instrument_with_event(self):
        from portman_v10.application.contracts import CommitImport

        source = """comdirect
Wertpapierkauf
Depotnummer: 123456
WKN: A2H57N
ISIN: LU1681041973
Stk. 0,25 AIS-AM.E.H.D.F.EOC, WKN / ISIN: A2H57N / LU1681041973
IBAN DE00000000000000000001
Valuta 02.05.2025
Zu Ihren Lasten EUR 49,92
Referenz: A2HFAULT0001"""
        _, job, preview = self._ready_preview(source, "a2h57n-fault.pdf")
        item = preview.items[0]
        self.assertEqual(item.instrument_resolution, "will_create")
        connection = self.store.connect()
        try:
            baseline_instruments = connection.execute("SELECT count(*) FROM instruments").fetchone()[0]
        finally:
            connection.close()
        original = self.store._insert_import_event

        def fail_after_event_insert(*args, **kwargs):
            original(*args, **kwargs)
            raise RuntimeError("synthetic failure after event insert")

        self.store._insert_import_event = fail_after_event_insert
        with self.assertRaises(ApplicationError):
            self.workflow.commit_import(CommitImport(job.import_id, preview.revision, "a2h57n-fault"))
        connection = self.store.connect()
        try:
            self.assertEqual(connection.execute("SELECT count(*) FROM instruments").fetchone()[0], baseline_instruments)
            self.assertEqual(connection.execute("SELECT count(*) FROM instrument_identifiers WHERE value='LU1681041973'").fetchone()[0], 0)
            self.assertEqual(connection.execute("SELECT count(*) FROM events").fetchone()[0], 0)
            self.assertEqual(connection.execute("SELECT count(*) FROM import_contributions WHERE target_type='instrument'").fetchone()[0], 0)
        finally:
            connection.close()

    def test_parallel_imports_for_same_new_isin_do_not_create_duplicate_instruments(self):
        from concurrent.futures import ThreadPoolExecutor
        from portman_v10.application.contracts import CommitImport

        base = """comdirect
Wertpapierkauf
Depotnummer: 123456
WKN: A2H57N
ISIN: LU1681041973
Stk. 0,25 AIS-AM.E.H.D.F.EOC, WKN / ISIN: A2H57N / LU1681041973
IBAN DE00000000000000000001
Valuta 02.05.2025
Zu Ihren Lasten EUR 49,92"""
        previews = []
        for index in range(2):
            source = f"{base}\nReferenz: PARALLEL{index:06d}"
            uploaded = self._upload(source, f"parallel-{index}.pdf")
            job = self.workflow.wait(self.workflow.start_import(ImportStart((uploaded.document.document_id,))).job_id, 10)
            preview = self.workflow.get_import_preview(job.import_id)
            item = preview.items[0]
            self.assertEqual(item.instrument_resolution, "will_create")
            self.workflow.resolve_import_item(job.import_id, ConflictDecision(
                item.candidate_id, "accept", candidate_revision=item.revision
            ), preview.revision)
            previews.append((job, self.workflow.get_import_preview(job.import_id)))
        commands = tuple(CommitImport(job.import_id, preview.revision, f"parallel-commit-{index}")
                         for index, (job, preview) in enumerate(previews))
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = tuple(executor.submit(self.workflow.commit_import, command) for command in commands)
            outcomes = []
            for future in futures:
                try:
                    outcomes.append(future.result())
                except ApplicationError as error:
                    outcomes.append(error)
        self.assertEqual(sum(not isinstance(value, ApplicationError) for value in outcomes), 1)
        self.assertEqual(sum(isinstance(value, ApplicationError) and value.code == ErrorCode.STALE_REVISION for value in outcomes), 1)
        connection = self.store.connect()
        try:
            self.assertEqual(connection.execute(
                "SELECT count(DISTINCT instrument_id) FROM instrument_identifiers WHERE identifier_type='ISIN' AND value='LU1681041973'"
            ).fetchone()[0], 1)
            self.assertEqual(connection.execute("SELECT count(*) FROM events WHERE kind='BUY'").fetchone()[0], 1)
        finally:
            connection.close()

    def test_real_pinned_comdirect_tax_information_has_no_booking_candidate(self):
        source = "comdirect\nSteuerliche Behandlung: Vorabpauschale\nVorabpauschale EUR 5,00\nSteuerbemessungsgrundlage EUR 4,00\nKapitalertragsteuer EUR 1,00\nFreistellungsauftrag EUR 2,00\nIBAN DE00000000000000000001\nDepotnummer: 123456"
        uploaded = self._upload(source, "vorabpauschale.pdf")
        job = self.workflow.wait(self.workflow.start_import(ImportStart((uploaded.document.document_id,))).job_id, 10)
        preview = self.workflow.get_import_preview(job.import_id)
        self.assertEqual(preview.documents[0].handler_id, "vorabpauschale")
        self.assertEqual(preview.items[0].review_status, "information")
        self.assertFalse(preview.items[0].movements)
        self.assertTrue(any(item.category == "tax_detail" and item.kind == "taxable_amount" for item in preview.items[0].components))

    def test_tax_statement_parser_quantity_without_cash_is_held_as_parser_gap(self):
        source = """comdirect
Steuerliche Behandlung: Fiktiver Verkauf Investmentfonds w. Investmentsteuerref.
Stk. -21,826 ISH.S.EUROP.MID 200 U.ETF, WKN / ISIN: 593399 / DE0005933998
Zu Ihren Gunsten vor Steuern:
Kapitalertragsteuer EUR 0,00
Solidaritätszuschlag EUR 0,00
Kirchensteuer EUR 0,00
abgeführte Steuern EUR 0,00
Zu Ihren Gunsten nach Steuern:
Freistellungsauftrag EUR 0,00"""
        uploaded = self._upload(source, "synthetic-fiktiver-verkauf-steuer.pdf")
        job = self.workflow.wait(self.workflow.start_import(ImportStart((uploaded.document.document_id,))).job_id, 10)
        preview = self.workflow.get_import_preview(job.import_id)
        item = preview.items[0]
        self.assertEqual(preview.documents[0].handler_id, "wertpapierverkauf")
        self.assertEqual(item.kind, "parserluecke_steuerereignis")
        self.assertEqual(item.movements, ())
        self.assertIn("kein Bestandszugang oder -abgang", item.missing_fields[0])
        self.assertIn("-21.826", dict(item.references)["unbooked_security_movements"])
        connection = self.store.connect()
        try:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM events").fetchone()[0], 0)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM positions").fetchone()[0], 0)
        finally:
            connection.close()

    def test_real_pinned_comdirect_tax_notice_handlers_keep_bases_out_of_cash_movements(self):
        samples = (
            ("investment_ausschuettung", "comdirect\nSteuerliche Behandlung: Investment-Ausschüttung\nBruttoertrag EUR 5,00\nKapitalertragsteuer EUR 1,00\nSteuerbemessungsgrundlage EUR 4,00\nFreistellungsauftrag EUR 2,00\nIBAN DE00000000000000000001\nDepotnummer: 123456", {"taxable_amount": "4", "exemption_order_used": "2"}),
            ("dividende_steuer_inland", "comdirect\nSteuerliche Behandlung: Dividende\nBruttoertrag EUR 5,00\nKapitalertragsteuer EUR 1,00\nKirchensteuer EUR 0,10\nSteuerbemessungsgrundlage EUR 4,00\nIBAN DE00000000000000000001\nDepotnummer: 123456", {"taxable_amount": "4", "actually_withheld_tax": "1.1"}),
        )
        for handler, source, expected_details in samples:
            with self.subTest(handler=handler):
                uploaded = self._upload(source, f"{handler}.pdf")
                job = self.workflow.wait(self.workflow.start_import(ImportStart((uploaded.document.document_id,))).job_id, 10)
                preview = self.workflow.get_import_preview(job.import_id)
                self.assertEqual(preview.documents[0].handler_id, handler)
                self.assertEqual(len(preview.items), 1)
                item = preview.items[0]
                self.assertEqual(item.review_status, "information")
                self.assertFalse(item.movements)
                self.assertFalse(item.missing_fields)
                self.assertFalse(item.warnings)
                details = {component.kind: component.amount.text for component in item.components if component.amount}
                for key, value in expected_details.items():
                    self.assertEqual(details[key], value)
                self.assertTrue(item.source_evidence)

    def test_investment_distribution_tax_notice_preserves_identity_without_position(self):
        """Wertpapieridentität bleibt auch bei einer bewegungsneutralen Steuermitteilung sichtbar."""
        source = """comdirect
Steuerliche Behandlung: Investment-Ausschüttung
Wertpapier-Bezeichnung                 WKN/ISIN
iShares MSCI World                     A0H074
Inhaber-Anteile                        DE000A0H0744
STK 16,471
Bruttoertrag EUR 5,00
Kapitalertragsteuer EUR 1,00
Steuerbemessungsgrundlage EUR 4,00
IBAN DE00000000000000000001
Depotnummer: 123456"""
        uploaded = self._upload(source, "investment-distribution-tax-notice.pdf")
        job = self.workflow.wait(self.workflow.start_import(ImportStart((uploaded.document.document_id,))).job_id, 10)
        preview = self.workflow.get_import_preview(job.import_id)
        item = preview.items[0]
        self.assertEqual(preview.documents[0].handler_id, "investment_ausschuettung")
        self.assertEqual(item.review_status, "information")
        self.assertEqual(item.movements, ())
        self.assertFalse(item.missing_fields)
        self.assertFalse(item.warnings)
        references = dict(item.references)
        self.assertEqual(references["security_isin"], "DE000A0H0744")
        self.assertEqual(references["security_wkn"], "A0H074")

    def test_real_pinned_comdirect_mifid_information_is_non_bookable(self):
        source = "comdirect\nKosteninformation zum Wertpapiergeschäft\nProduktkosten 1,00 EUR\nDienstleistungskosten 0,50 EUR"
        uploaded = self._upload(source, "mifid-costs.pdf")
        job = self.workflow.wait(self.workflow.start_import(ImportStart((uploaded.document.document_id,))).job_id, 10)
        preview = self.workflow.get_import_preview(job.import_id)
        self.assertEqual(preview.items[0].review_status, "information")
        self.assertFalse(preview.items[0].movements)
        self.assertTrue(all(not item.counts_as_movement for item in preview.items[0].components))

    def test_real_pinned_comdirect_finanzreport_snapshot_stays_information(self):
        source = "comdirect\nFinanzreport Nr. 123 per 01.07.2026\nGirokonto DE00000000000000000001\nAlter Saldo 01.06.2026 100,00\nNeuer Saldo 01.07.2026 110,00"
        uploaded = self._upload(source, "finanzreport.pdf")
        job = self.workflow.wait(self.workflow.start_import(ImportStart((uploaded.document.document_id,))).job_id, 10)
        preview = self.workflow.get_import_preview(job.import_id)
        self.assertEqual(preview.documents[0].handler_id, "finanzreport")
        self.assertEqual(preview.items[0].review_status, "information")
        self.assertFalse(preview.items[0].movements)

    def test_real_pinned_comdirect_finanzreport_keeps_each_booking_row_separate(self):
        source = "comdirect\nFinanzreport Nr. 124 per 01.07.2026\nGirokonto DE00000000000000000001\nAlter Saldo 01.06.2026 100,00\n01.07.2026 01.07.2026 Habenzinsen +10,00\n01.07.2026 01.07.2026 Kartenzahlung -2,50\nNeuer Saldo 01.07.2026 107,50"
        uploaded = self._upload(source, "finanzreport-lines.pdf")
        job = self.workflow.wait(self.workflow.start_import(ImportStart((uploaded.document.document_id,))).job_id, 10)
        preview = self.workflow.get_import_preview(job.import_id)
        self.assertEqual(preview.documents[0].handler_id, "finanzreport")
        self.assertEqual(len(preview.items), 2)
        by_source = {item.source_evidence[0].excerpt: item for item in preview.items}
        self.assertEqual(set(by_source), {"01.07.2026 01.07.2026 Habenzinsen +10,00", "01.07.2026 01.07.2026 Kartenzahlung -2,50"})
        self.assertEqual(by_source["01.07.2026 01.07.2026 Habenzinsen +10,00"].movements[0].amount.text, "10")
        self.assertEqual(by_source["01.07.2026 01.07.2026 Kartenzahlung -2,50"].movements[0].amount.text, "-2.5")
        self.assertEqual({item.movements[0].account_id for item in preview.items}, {self.cash.account_id})
        self.assertEqual([item.review_status for item in preview.items], ["needs_review", "needs_review"])
        self.assertTrue(all(item.source_evidence and item.source_evidence[0].excerpt for item in preview.items))
        self.assertTrue(all(item.missing_fields == (
            "Bankreferenz fehlt oder ist nicht eindeutig; Dubletten können nicht sicher automatisch zugeordnet werden",
        ) for item in preview.items))

    def test_finanzreport_cash_rows_need_explicit_unmatched_acceptance_and_reimport_links_each_row(self):
        source = "comdirect\nFinanzreport Nr. 124 per 01.07.2026\nGirokonto DE00000000000000000001\nAlter Saldo 01.06.2026 100,00\n01.07.2026 01.07.2026 Habenzinsen +10,00\n01.07.2026 01.07.2026 Kartenzahlung -2,50\nNeuer Saldo 01.07.2026 107,50"
        self.store.record_opening(OpeningBalanceInput("finanzreport-opening", self.cash.account_id, date(2026, 6, 30), currency="EUR", amount=ExactValue("100")))
        uploaded = self._upload(source, "finanzreport-explicit-acceptance.pdf")
        first_job = self.workflow.wait(self.workflow.start_import(ImportStart((uploaded.document.document_id,))).job_id, 10)
        preview = self.workflow.get_import_preview(first_job.import_id)
        self.assertEqual(len(preview.items), 2)
        self.assertTrue(all(item.review_status == "needs_review" for item in preview.items))
        self.assertTrue(all(item.missing_fields == (
            "Bankreferenz fehlt oder ist nicht eindeutig; Dubletten können nicht sicher automatisch zugeordnet werden",
        ) for item in preview.items))

        for item in preview.items:
            preview = self.workflow.resolve_import_item(
                first_job.import_id,
                ConflictDecision(item.candidate_id, "accept_unmatched", candidate_revision=item.revision),
                preview.revision,
            )
        first_report = self.workflow.commit_import(CommitImport(first_job.import_id, preview.revision, "finanzreport-first"))
        self.assertEqual(len(first_report.created_event_ids), 2)
        overview = self.store.get_overview(date(2026, 7, 1), (self.cash.account_id,))
        self.assertEqual(overview.lines[0].value.text, "107.5")

        overlapping_source = "comdirect\nFinanzreport Nr. 125 per 01.07.2026\nGirokonto DE00000000000000000001\n01.07.2026 01.07.2026 Habenzinsen +10,00"
        overlapping_upload = self._upload(overlapping_source, "finanzreport-overlap.pdf")
        overlapping_job = self.workflow.wait(self.workflow.start_import(ImportStart((overlapping_upload.document.document_id,))).job_id, 10)
        overlapping_preview = self.workflow.get_import_preview(overlapping_job.import_id)
        overlapping_item = overlapping_preview.items[0]
        self.assertEqual(overlapping_item.disposition, "conflict")
        duplicate_event_id = overlapping_item.conflicts[0].related_event_id
        self.assertIn(duplicate_event_id, first_report.created_event_ids)
        overlapping_preview = self.workflow.resolve_import_item(
            overlapping_job.import_id,
            ConflictDecision(overlapping_item.candidate_id, "accept_unmatched", candidate_revision=overlapping_item.revision),
            overlapping_preview.revision,
        )
        with self.assertRaises(ApplicationError):
            self.workflow.commit_import(CommitImport(overlapping_job.import_id, overlapping_preview.revision, "finanzreport-overlap-reject-new"))
        overlapping_item = overlapping_preview.items[0]
        overlapping_preview = self.workflow.resolve_import_item(
            overlapping_job.import_id,
            ConflictDecision(overlapping_item.candidate_id, "link", target_id=duplicate_event_id, candidate_revision=overlapping_item.revision),
            overlapping_preview.revision,
        )
        linked_report = self.workflow.commit_import(CommitImport(overlapping_job.import_id, overlapping_preview.revision, "finanzreport-overlap-link"))
        self.assertEqual(linked_report.created_event_ids, ())
        self.assertEqual(linked_report.linked_event_ids, (duplicate_event_id,))
        self.assertEqual(self.store.get_overview(date(2026, 7, 1), (self.cash.account_id,)).lines[0].value.text, "107.5")

        source_bytes = self.workflow.get_document(uploaded.document.document_id).content
        repeated_upload = self.workflow.upload_document(DocumentUpload(uploaded.document.name, source_bytes))
        self.assertTrue(repeated_upload.identical_content_already_stored)
        second_job = self.workflow.wait(self.workflow.start_import(ImportStart((repeated_upload.document.document_id,))).job_id, 10)
        repeated_preview = self.workflow.get_import_preview(second_job.import_id)
        self.assertEqual(len(repeated_preview.items), 2)
        for item in repeated_preview.items:
            target = next(value.related_event_id for value in item.conflicts if value.related_event_id)
            repeated_preview = self.workflow.resolve_import_item(
                second_job.import_id,
                ConflictDecision(item.candidate_id, "link", target_id=target, candidate_revision=item.revision),
                repeated_preview.revision,
            )
        repeated_report = self.workflow.commit_import(CommitImport(second_job.import_id, repeated_preview.revision, "finanzreport-replay"))
        self.assertEqual(len(repeated_report.created_event_ids), 0)
        self.assertEqual(len(repeated_report.linked_event_ids), 2)
        connection = self.store.connect()
        try:
            self.assertEqual(connection.execute("SELECT count(*) FROM events WHERE kind='CASH_BOOKING'").fetchone()[0], 2)
            self.assertEqual(connection.execute(
                "SELECT count(*) FROM positions p JOIN events e ON e.event_id=p.event_id WHERE p.account_id=? AND e.kind='CASH_BOOKING'",
                (self.cash.account_id,),
            ).fetchone()[0], 2)
        finally:
            connection.close()

    def test_executable_comdirect_handler_registry_is_fully_listed(self):
        from portman_parsers.registry import default_registry

        handlers = {(plugin.plugin_id, item.handler_id) for plugin in default_registry().metadata()
                    if plugin.plugin_id in {"user.comdirect-ertraege", "comdirect.finanzreport", "portfolio-performance.comdirect"}
                    for item in plugin.handlers if default_registry().handler_status(plugin.plugin_id, item.handler_id) == "IMPLEMENTED"}
        self.assertEqual(len(handlers), 19)

    def test_pp_derived_comdirect_plugins_are_parsed_when_selected_by_registry(self):
        from portman_parsers.registry import default_registry
        from portman_parsers.extraction import extract_pdf

        source = "comdirect\nWertpapierverkauf\nStk. 1,000 Fonds, WKN / ISIN: ABC123 / DE0008474511\nDepotnummer: 123456\nIBAN DE00000000000000000001\nZu Ihren Gunsten EUR 10,00\nValuta 01.07.2026"
        path = self.root / "pp-derived-sale.pdf"
        path.write_bytes(make_text_pdf(source))
        detection = default_registry().select(extract_pdf(str(path)))
        self.assertIsNotNone(detection)
        uploaded = self.workflow.upload_document(DocumentUpload("pp-derived-sale.pdf", path.read_bytes()))
        job = self.workflow.wait(self.workflow.start_import(ImportStart((uploaded.document.document_id,))).job_id, 10)
        preview = self.workflow.get_import_preview(job.import_id)
        self.assertEqual(preview.documents[0].handler_id, detection.handler_id)
        self.assertEqual(preview.items[0].review_status, "needs_review")

    def test_all_pp_comdirect_handlers_parse_synthetic_pdf_through_registered_plugin(self):
        from portman_parsers.extraction import extract_pdf
        from portman_parsers.registry import default_registry
        from portman_parsers.validation import validate_parsed_document

        samples = {
            "wertpapierkauf": ("Wertpapierkauf\nStk. 1,000 Fonds, WKN / ISIN: ABC123 / DE0008474511\nDepotnummer: 123456\nIBAN DE00000000000000000001\nZu Ihren Lasten EUR 10,00\nValuta 01.07.2026", "BUY", "-10", "1"),
            "wertpapierverkauf": ("Wertpapierverkauf\nStk. 1,000 Fonds, WKN / ISIN: ABC123 / DE0008474511\nDepotnummer: 123456\nIBAN DE00000000000000000001\nZu Ihren Gunsten EUR 10,00\nValuta 01.07.2026", "SELL", "10", "-1"),
            "einloesung": ("Abrechnung Einlösung\nStk. 1,000 Fonds, WKN / ISIN: ABC123 / DE0008474511\nDepotnummer: 123456\nIBAN DE00000000000000000001\nZu Ihren Gunsten EUR 10,00\nValuta 01.07.2026", "REDEMPTION", "10", "-1"),
            "dividendengutschrift": ("Abrechnung Dividendengutschrift\nZu Ihren Gunsten EUR 5,00\nDepotnummer: 123456\nIBAN DE00000000000000000001\nValuta 01.07.2026", "DIVIDEND", "5", None),
            "ertragsgutschrift": ("Abrechnung Ertragsgutschrift\nZinsgutschrift EUR 5,00\nZu Ihren Gunsten EUR 5,00\nIBAN DE00000000000000000001\nValuta 01.07.2026", "DIVIDEND", "5", None),
            "investment_ausschuettung": ("Steuerliche Behandlung: Investment-Ausschüttung\nKapitalertragsteuer EUR 1,00\nSteuerbemessungsgrundlage EUR 4,00", "TAX_NOTICE", None, None),
            "dividende_steuer_inland": ("Steuerliche Behandlung: Dividende\nKapitalertragsteuer EUR 1,00\nSteuerbemessungsgrundlage EUR 4,00", "TAX_NOTICE", None, None),
            "vorabpauschale": ("Steuerliche Behandlung: Vorabpauschale\nVorabpauschale EUR 5,00\nKapitalertragsteuer EUR 1,00", "ADVANCE_TAX", None, None),
            "finanzreport": ("Finanzreport Nr. 123 per 01.07.2026\nGirokonto DE00000000000000000001\nAlter Saldo 01.06.2026 100,00\nNeuer Saldo 01.07.2026 110,00", None, None, None),
        }
        registry = default_registry()
        plugin_id = "portfolio-performance.comdirect"
        plugin = registry.plugin(plugin_id)
        with TemporaryDirectory() as directory:
            for handler, (body, expected_kind, cash_amount, quantity_amount) in samples.items():
                with self.subTest(handler=handler):
                    path = Path(directory) / f"pp-{handler}.pdf"
                    path.write_bytes(make_text_pdf(f"comdirect\n{body}"))
                    document = extract_pdf(str(path))
                    detections = plugin.detect(document)
                    self.assertEqual(len(detections), 1)
                    detection = detections[0]
                    self.assertEqual(detection.handler_id, handler)
                    result = registry.parse(document, detection)
                    self.assertEqual((result.plugin_id, result.handler_id), (plugin_id, handler))
                    self.assertTrue(result.evidence)
                    self.assertEqual(validate_parsed_document(result), ())
                    if expected_kind:
                        self.assertEqual(len(result.events), 1)
                        event = result.events[0]
                        self.assertEqual(event.kind, expected_kind)
                        self.assertEqual([format(m.amount.normalize(), "f") for m in event.cash_movements], [cash_amount] if cash_amount is not None else [])
                        self.assertEqual([format(m.quantity.normalize(), "f") for m in event.security_movements], [quantity_amount] if quantity_amount is not None else [])
                    else:
                        self.assertFalse(result.events)

    def test_default_registry_prefers_comdirect_specific_plugins_over_pp_aliases(self):
        from portman_parsers.extraction import extract_pdf
        from portman_parsers.registry import default_registry

        samples = {
            "wertpapierkauf": "Wertpapierkauf",
            "wertpapierverkauf": "Wertpapierverkauf",
            "einloesung": "Abrechnung Einlösung",
            "dividendengutschrift": "Abrechnung Dividendengutschrift",
            "ertragsgutschrift": "Abrechnung Ertragsgutschrift",
            "investment_ausschuettung": "Steuerliche Behandlung: Investment-Ausschüttung",
            "dividende_steuer_inland": "Steuerliche Behandlung: Dividende",
            "vorabpauschale": "Steuerliche Behandlung: Vorabpauschale",
        }
        registry = default_registry()
        with TemporaryDirectory() as directory:
            for handler, title in samples.items():
                with self.subTest(handler=handler):
                    path = Path(directory) / f"registry-{handler}.pdf"
                    path.write_bytes(make_text_pdf(f"comdirect\n{title}"))
                    document = extract_pdf(str(path))
                    candidates = registry.detect(document)
                    selected = registry.select(document)
                    self.assertIn(("portfolio-performance.comdirect", handler), {(item.plugin_id, item.handler_id) for item in candidates})
                    self.assertEqual((selected.plugin_id, selected.handler_id), ("user.comdirect-ertraege", handler))

            report_path = Path(directory) / "registry-finanzreport.pdf"
            report_path.write_bytes(make_text_pdf("comdirect\nFinanzreport Nr. 125 per 01.07.2026"))
            report = registry.select(extract_pdf(str(report_path)))
            self.assertEqual((report.plugin_id, report.handler_id), ("comdirect.finanzreport", "finanzreport"))

    def test_conflicting_account_hint_is_visible_and_does_not_override_source(self):
        other = self.store.save_account(AccountInput("Other Giro", "cash", "checking", "comdirect", "EUR"), None)
        uploaded = self._upload()
        job = self.workflow.start_import(ImportStart((uploaded.document.document_id,), account_hint=other.account_id))
        self.workflow.wait(job.job_id, 10)
        item = self.workflow.get_import_preview(job.import_id).items[0]
        cash = next(movement for movement in item.movements if movement.movement_type == "cash")
        self.assertEqual(cash.account_id, self.cash.account_id)
        self.assertEqual(cash.account_assignment, "conflict")
        self.assertTrue(item.conflicts)
        self.assertNotIn(other.account_id, item.account_ids)

    def test_preview_decisions_are_revisioned_and_do_not_change_parser_facts(self):
        uploaded = self._upload()
        job = self.workflow.wait(self.workflow.start_import(ImportStart((uploaded.document.document_id,))).job_id, 10)
        preview = self.workflow.get_import_preview(job.import_id)
        item_before = preview.items[0]
        decision = ConflictDecision(item_before.candidate_id, "ignore")
        updated = self.workflow.resolve_import_item(job.import_id, decision, preview.revision)
        self.assertEqual(updated.revision, preview.revision + 1)
        self.assertEqual(updated.items[0], item_before)
        self.assertEqual(updated.decisions[0].decision, decision)
        self.assertEqual(updated.decisions[0].candidate_revision, item_before.revision)
        self.assertEqual(updated.decisions[0].preview_revision, preview.revision)
        with self.assertRaises(ApplicationError) as stale:
            self.workflow.resolve_import_item(job.import_id, decision, preview.revision)
        self.assertEqual(stale.exception.code, ErrorCode.STALE_REVISION)

    def test_mixed_valid_and_invalid_documents_keep_each_result(self):
        good = self._upload()
        bad = self.workflow.upload_document(DocumentUpload("broken.pdf", b"not a PDF"))
        start = self.workflow.start_import(ImportStart((good.document.document_id, bad.document.document_id)))
        result = self.workflow.wait(start.job_id, 10)
        self.assertEqual(result.state, "needs_review")
        by_name = {item.name: item for item in self.workflow.get_import_document_results(start.job_id)}
        self.assertEqual(by_name["comdirect.pdf"].status, "needs_review")
        self.assertEqual(by_name["broken.pdf"].status, "failed")
        self.assertEqual(by_name["broken.pdf"].error_code, ErrorCode.INVALID_DOCUMENT)
        self.assertEqual(len(self.workflow.get_import_preview(start.import_id).items), 1)

    def test_incomplete_purchase_keeps_missing_amounts_unknown(self):
        uploaded = self._upload("comdirect\nWertpapierkauf", "incomplete.pdf")
        job = self.workflow.start_import(ImportStart((uploaded.document.document_id,)))
        self.assertEqual(self.workflow.wait(job.job_id, 10).state, "needs_review")
        document_result = self.workflow.get_import_document_results(job.job_id)[0]
        self.assertEqual(document_result.status, "needs_review")
        item = self.workflow.get_import_preview(job.import_id).items[0]
        self.assertEqual(item.suggested_kind, "BUY")
        self.assertEqual(item.review_status, "needs_review")
        self.assertEqual(item.movements, ())
        self.assertEqual(item.amounts, ())
        self.assertTrue(item.missing_fields)

    def test_empty_text_pdf_and_encrypted_pdf_have_distinct_errors(self):
        empty = self.workflow.upload_document(DocumentUpload("empty.pdf", make_text_pdf(" ")))
        encrypted = BytesIO()
        writer = PdfWriter()
        writer.add_blank_page(width=200, height=200)
        writer.encrypt("test-password")
        writer.write(encrypted)
        locked = self.workflow.upload_document(DocumentUpload("locked.pdf", encrypted.getvalue()))
        job = self.workflow.start_import(ImportStart((empty.document.document_id, locked.document.document_id)))
        self.workflow.wait(job.job_id, 10)
        results = {item.name: item for item in self.workflow.get_import_document_results(job.job_id)}
        self.assertEqual(results["empty.pdf"].error_code, ErrorCode.INCOMPLETE_RESULT)
        self.assertIn("PDFium", results["empty.pdf"].warning_messages[0])
        self.assertEqual(results["locked.pdf"].error_code, ErrorCode.ENCRYPTED_DOCUMENT)

    def test_cleanup_removes_only_owned_temporary_upload_files(self):
        owned = self.root / "documents" / ".incoming" / ("a" * 32 + ".tmp")
        unrelated = self.root / "documents" / "unrelated.tmp"
        owned.write_bytes(b"partial")
        unrelated.write_bytes(b"preserve")
        self.assertEqual(self.workflow.cleanup_temporary_files(), 1)
        self.assertFalse(owned.exists())
        self.assertTrue(unrelated.exists())

    def test_unsupported_document_does_not_create_candidate_or_booking(self):
        uploaded = self._upload("unbekannte Beispielbank\nMitteilung", "unknown.pdf")
        job = self.workflow.start_import(ImportStart((uploaded.document.document_id,)))
        self.assertEqual(self.workflow.wait(job.job_id, 10).state, "needs_review")
        result = self.workflow.get_import_document_results(job.job_id)[0]
        self.assertEqual(result.status, "unsupported")
        self.assertEqual(self.workflow.get_import_preview(job.import_id).items, ())

        unapproved = self._upload("comdirect\nWertpapierverkauf\nStk. 1,000 DE0008474511\nZu Ihren Gunsten EUR 10,00", "sale.pdf")
        sale_job = self.workflow.start_import(ImportStart((unapproved.document.document_id,)))
        self.workflow.wait(sale_job.job_id, 10)
        sale_result = self.workflow.get_import_document_results(sale_job.job_id)[0]
        self.assertEqual(sale_result.status, "needs_review")
        self.assertEqual(sale_result.handler_id, "wertpapierverkauf")
        sale_preview = self.workflow.get_import_preview(sale_job.import_id)
        self.assertEqual(sale_preview.items[0].review_status, "needs_review")
        self.assertTrue(sale_preview.items[0].movements)

    def test_information_only_comdirect_document_is_not_a_booking_candidate(self):
        source = "comdirect\nKosteninformation zum Wertpapiergeschäft 10,00 EUR"
        uploaded = self._upload(source, "mifid.pdf")
        job = self.workflow.start_import(ImportStart((uploaded.document.document_id,)))
        self.assertEqual(self.workflow.wait(job.job_id, 10).state, "needs_review")
        result = self.workflow.get_import_document_results(job.job_id)[0]
        self.assertEqual(result.status, "information")
        preview = self.workflow.get_import_preview(job.import_id)
        self.assertEqual(len(preview.items), 1)
        self.assertEqual(preview.items[0].review_status, "information")
        self.assertFalse(preview.items[0].movements)
        self.assertTrue(all(not component.counts_as_movement for component in preview.items[0].components))

    def test_queued_and_in_parser_cancellation_are_cooperative(self):
        entered, release = Event(), Event()

        class GateParser:
            package_version = "0.7.0"
            api_version = "0.6"
            schema_version = "1.6.0"

            def parse_path(self, document_id, path, name, account_hint=None):
                entered.set()
                release.wait(5)
                result = ImportDocumentResult(document_id, name, "parsed", "synthetic", "test", "1", "handler", "1.6.0")
                return result, (), ()

        self.workflow.parser = GateParser()
        first = self._upload(name="first.pdf")
        second = self.workflow.upload_document(DocumentUpload("second.pdf", make_text_pdf("comdirect\nunknown")))
        running = self.workflow.start_import(ImportStart((first.document.document_id,)))
        self.assertTrue(entered.wait(5))
        queued = self.workflow.start_import(ImportStart((second.document.document_id,)))
        cancelled_queued = self.workflow.cancel_job(queued.job_id, queued.revision)
        self.assertEqual(cancelled_queued.state, "cancelled")
        self.assertEqual(self.workflow.get_import_document_results(queued.job_id)[0].status, "cancelled")
        running_now = self.workflow.get_job(running.job_id)
        requested = self.workflow.cancel_job(running.job_id, running_now.revision)
        self.assertTrue(requested.cancel_requested)
        release.set()
        self.assertEqual(self.workflow.wait(running.job_id, 10).state, "cancelled")
        self.assertEqual(self.workflow.get_import_document_results(running.job_id)[0].status, "cancelled")

    def test_unfinished_jobs_are_marked_failed_after_restart_without_retry(self):
        upload = self._upload()
        abandoned = ImportJob("abandoned-job", "abandoned-import", "queued", 0, 1, document_count=1)
        self.store.create_import_job(abandoned, (upload.document.document_id,), None, "0.7.0", "0.6", "1.6.0")
        self.workflow.close()
        self.workflow = ImportWorkflow(SQLiteStore(self.root / "v10.sqlite"), self.root)
        recovered = self.workflow.get_job(abandoned.job_id)
        self.assertEqual(recovered.state, "failed")
        self.assertEqual(recovered.error_code, ErrorCode.JOB_INTERRUPTED)
        self.assertEqual(self.workflow.get_import_document_results(abandoned.job_id)[0].error_code, ErrorCode.JOB_INTERRUPTED)


if __name__ == "__main__":
    unittest.main()
