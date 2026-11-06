from io import BytesIO
from pathlib import Path
from threading import Event
from tempfile import TemporaryDirectory
import unittest

from pypdf import PdfWriter

from portman_v10.application.contracts import (
    AccountIdentifier, AccountInput, ApplicationError, ConflictDecision,
    DocumentUpload, ErrorCode, ImportDocumentResult, ImportJob, ImportStart,
    InstrumentInput,
)
from portman_v10.infrastructure.import_workflow import ImportWorkflow
from portman_v10.infrastructure.sqlite_store import SQLiteStore
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
        self.assertEqual(sale_result.status, "unsupported")
        self.assertEqual(sale_result.handler_id, "wertpapierverkauf")
        self.assertEqual(self.workflow.get_import_preview(sale_job.import_id).items, ())

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
