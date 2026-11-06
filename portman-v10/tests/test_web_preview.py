from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from portman_v10.application.contracts import AccountIdentifier, AccountInput, InstrumentInput
from portman_v10.infrastructure.import_workflow import ImportWorkflow
from portman_v10.infrastructure.sqlite_store import SQLiteStore
from portman_v10.web.server import create_app
from synthetic_pdf import make_text_pdf


PURCHASE_TEXT = """comdirect
Wertpapierkauf
Depotnummer: 123456
Stk. 0,125 Fonds DE0008474511
Provision EUR 1,50
Zu Ihren Lasten EUR 126,50
Valuta 01.07.2026
DE00 0000 0000 0000 0000 01"""


class ImportWebPreviewTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.data_dir = Path(self.temporary.name)
        self.store = SQLiteStore(self.data_dir / "v10.sqlite")
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
        self.workflow = ImportWorkflow(self.store, self.data_dir)
        self.addCleanup(self.workflow.close)
        self.app = create_app(self.workflow, branch="codex/portman-v10-foundation", commit="abc1234", profile="test-web")
        self.client = self.app.test_client()

    def _submit(self, content=None, filename="purchase.pdf"):
        content = content if content is not None else make_text_pdf(PURCHASE_TEXT)
        response = self.client.post(
            "/imports",
            data={"pdf": (BytesIO(content), filename)},
            content_type="multipart/form-data",
            headers={"Origin": "http://127.0.0.1:8765", "Referer": "http://127.0.0.1:8765/", "Host": "127.0.0.1:8765"},
        )
        self.assertEqual(response.status_code, 303, response.get_data(as_text=True))
        job_url = response.headers["Location"]
        job_id = job_url.rsplit("/", 1)[-1]
        job = self.workflow.wait(job_id, timeout=15)
        return job, job_url

    def test_upload_job_preview_original_and_no_booking(self):
        source = make_text_pdf(PURCHASE_TEXT + "\n<script>alert(1)</script>")
        job, job_url = self._submit(source, "<img src=x onerror=alert(1)>.pdf")
        self.assertEqual(job.state, "needs_review")
        page = self.client.get(job_url)
        html = page.get_data(as_text=True)
        self.assertEqual(page.status_code, 200)
        self.assertIn("Importvorschau – noch nicht gebucht", html)
        self.assertIn("codex/portman-v10-foundation", html)
        self.assertIn("abc1234", html)
        self.assertIn("Indexfonds — DE0008474511", html)
        self.assertIn("comdirect Giro", html)
        self.assertIn("-126.5 EUR", html)
        self.assertIn("0.125", html)
        self.assertIn("1.5 EUR", html)
        self.assertIn("Exakte Kennung", html)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html)
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertNotIn("<img src=x onerror=alert(1)>", html)
        self.assertIn('disabled>Übernehmen</button>', html)
        self.assertIn("Vorschau bereit – Angaben müssen geprüft werden.", html)

        document = self.workflow.get_import_document_results(job.job_id)[0]
        original = self.client.get(f"/documents/{document.document_id}")
        self.assertEqual(original.status_code, 200)
        self.assertEqual(original.mimetype, "application/pdf")
        self.assertEqual(original.data, source)
        self.assertEqual(original.headers["X-Content-Type-Options"], "nosniff")

        connection = self.store.connect()
        try:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM events").fetchone()[0], 0)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM positions").fetchone()[0], 0)
        finally:
            connection.close()

    def test_home_page_shows_profile_and_persistent_notice(self):
        response = self.client.get("/")
        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("Importvorschau – noch nicht gebucht", html)
        self.assertIn("test-web", html)
        self.assertIn("multipart/form-data", html)
        self.assertIn("bereit zum Hochladen", html)
        self.assertIn("wird hochgeladen", html)
        self.assertIn("hochgeladen. Importvorschau wird erstellt", html)
        self.assertIn("xhr.status", html)

    def test_unsupported_document_is_explained_and_has_no_candidate(self):
        job, job_url = self._submit(make_text_pdf("comdirect\nWertpapierverkauf"), "sale.pdf")
        self.assertEqual(job.state, "needs_review")
        html = self.client.get(job_url).get_data(as_text=True)
        self.assertIn("Nicht unterstützt", html)
        self.assertIn("nicht freigegeben", html)
        self.assertIn("keine Buchungskandidaten", html)

    def test_parser_failure_shows_concrete_error_and_retry_link(self):
        job, job_url = self._submit(b"kein gueltiges PDF", "broken.pdf")
        self.assertEqual(job.state, "failed")
        html = self.client.get(job_url).get_data(as_text=True)
        self.assertIn("Import fehlgeschlagen", html)
        self.assertIn("Bitte erneut versuchen", html)
        self.assertIn("broken.pdf", html)
        self.assertIn("retry-upload", html)

    def test_unmatched_depot_is_clearly_shown_as_open(self):
        text = PURCHASE_TEXT.replace("Depotnummer: 123456", "Depotnummer: 999999")
        job, job_url = self._submit(make_text_pdf(text), "unmatched.pdf")
        self.assertEqual(job.state, "needs_review")
        html = self.client.get(job_url).get_data(as_text=True)
        self.assertIn("Zuordnung offen", html)
        self.assertIn("999999", html)

    def test_upload_validation_size_and_unknown_document_errors(self):
        local_headers = {"Host": "127.0.0.1:8765", "Origin": "http://127.0.0.1:8765", "Referer": "http://127.0.0.1:8765/"}
        no_file = self.client.post("/imports", data={}, content_type="multipart/form-data", headers=local_headers)
        self.assertEqual(no_file.status_code, 400)
        self.assertIn("Bitte eine PDF-Datei auswählen", no_file.get_data(as_text=True))

        wrong_extension = self.client.post(
            "/imports", data={"pdf": (BytesIO(b"not pdf"), "statement.txt")}, content_type="multipart/form-data", headers=local_headers,
        )
        self.assertEqual(wrong_extension.status_code, 400)
        self.assertIn("Endung .pdf", wrong_extension.get_data(as_text=True))

        empty = self.client.post(
            "/imports", data={"pdf": (BytesIO(b""), "empty.pdf")}, content_type="multipart/form-data", headers=local_headers,
        )
        self.assertEqual(empty.status_code, 400)
        self.assertIn("Datei ist leer", empty.get_data(as_text=True))

        self.app.config["MAX_CONTENT_LENGTH"] = 512
        oversized = self.client.post(
            "/imports", data={"pdf": (BytesIO(b"x" * 2048), "large.pdf")}, content_type="multipart/form-data", headers=local_headers,
        )
        self.assertEqual(oversized.status_code, 413)
        self.assertIn("50 MiB", oversized.get_data(as_text=True))

        unknown_job = self.client.get("/jobs/not-a-job")
        self.assertEqual(unknown_job.status_code, 404)
        unknown_document = self.client.get("/documents/C:%5CWindows%5Cwin.ini")
        self.assertEqual(unknown_document.status_code, 404)

    def test_rejects_untrusted_host(self):
        response = self.client.get("/", headers={"Host": "external.example"})
        self.assertEqual(response.status_code, 400)

    def test_rejects_cross_origin_upload(self):
        response = self.client.post("/imports", headers={"Origin": "http://external.example", "Host": "127.0.0.1:8765"})
        self.assertEqual(response.status_code, 403)
        self.assertIn("nur von der geöffneten lokalen V10-Seite", response.get_data(as_text=True))

    def test_http_403_is_not_reported_as_success_and_same_file_can_be_retried(self):
        file_bytes = make_text_pdf(PURCHASE_TEXT)
        rejected = self.client.post("/imports", data={"pdf": (BytesIO(file_bytes), "retry.pdf")}, content_type="multipart/form-data",
                                    headers={"Host": "127.0.0.1:8765", "Origin": "http://evil.example"})
        self.assertEqual(rejected.status_code, 403)
        self.assertIn("Upload nur von der geöffneten lokalen V10-Seite erlaubt", rejected.get_data(as_text=True))
        accepted = self.client.post("/imports", data={"pdf": (BytesIO(file_bytes), "retry.pdf")}, content_type="multipart/form-data",
                                    headers={"Host": "127.0.0.1:8765", "Origin": "http://127.0.0.1:8765", "Referer": "http://127.0.0.1:8765/"})
        self.assertEqual(accepted.status_code, 303)
        job_id = accepted.headers["Location"].rsplit("/", 1)[-1]
        self.workflow.wait(job_id, timeout=15)
        feedback = self.client.get(accepted.headers["Location"]).get_data(as_text=True)
        self.assertIn("Importvorschau – noch nicht gebucht", feedback)
        self.assertIn("Vorschau bereit – Angaben müssen geprüft werden", feedback)

    def test_accepts_same_origin_browser_form_headers_with_matching_scheme_host_and_port(self):
        response = self.client.post("/imports", data={"pdf": (BytesIO(make_text_pdf(PURCHASE_TEXT)), "browser.pdf")},
                                    content_type="multipart/form-data", headers={"Host": "127.0.0.1:8765", "Origin": "http://127.0.0.1:8765", "Referer": "http://127.0.0.1:8765/"})
        self.assertEqual(response.status_code, 303, response.get_data(as_text=True))

    def test_referer_fallback_is_allowed_but_missing_or_invalid_origin_headers_are_denied(self):
        fallback = self.client.post("/imports", data={"pdf": (BytesIO(make_text_pdf(PURCHASE_TEXT)), "referer.pdf")},
                                    content_type="multipart/form-data", headers={"Host": "127.0.0.1:8765", "Referer": "http://127.0.0.1:8765/source/page?tab=import"})
        self.assertEqual(fallback.status_code, 303, fallback.get_data(as_text=True))
        missing = self.client.post("/imports", data={"pdf": (BytesIO(make_text_pdf(PURCHASE_TEXT)), "no-origin.pdf")}, content_type="multipart/form-data", headers={"Host": "127.0.0.1:8765", "Origin": "", "Referer": ""})
        self.assertEqual(missing.status_code, 403)
        mismatch = self.client.post("/imports", data={"pdf": (BytesIO(make_text_pdf(PURCHASE_TEXT)), "wrong-port.pdf")},
                                    content_type="multipart/form-data", headers={"Host": "127.0.0.1:8765", "Origin": "http://127.0.0.1:8766"})
        self.assertEqual(mismatch.status_code, 403)
        malformed = self.client.post("/imports", data={"pdf": (BytesIO(make_text_pdf(PURCHASE_TEXT)), "bad-origin.pdf")},
                                     content_type="multipart/form-data", headers={"Host": "127.0.0.1:8765", "Origin": "null"})
        self.assertEqual(malformed.status_code, 403)

    def test_same_origin_value_with_path_is_not_valid_origin_but_is_valid_referer(self):
        valid_referer = self.client.post("/imports", data={"pdf": (BytesIO(make_text_pdf(PURCHASE_TEXT)), "referer-path.pdf")},
                                         content_type="multipart/form-data", headers={"Host": "127.0.0.1:8765", "Referer": "http://127.0.0.1:8765/a/page?return=1"})
        self.assertEqual(valid_referer.status_code, 303, valid_referer.get_data(as_text=True))
        invalid_origin = self.client.post("/imports", data={"pdf": (BytesIO(make_text_pdf(PURCHASE_TEXT)), "origin-path.pdf")},
                                          content_type="multipart/form-data", headers={"Host": "127.0.0.1:8765", "Origin": "http://127.0.0.1:8765/a/page"})
        self.assertEqual(invalid_origin.status_code, 403)


if __name__ == "__main__":
    unittest.main()
