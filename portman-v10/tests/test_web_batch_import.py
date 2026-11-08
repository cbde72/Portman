from io import BytesIO
from pathlib import Path
import re
from tempfile import TemporaryDirectory
import unittest

from portman_v10.application.contracts import AccountIdentifier, AccountInput, InstrumentInput
from portman_v10.infrastructure.import_workflow import ImportWorkflow
from portman_v10.infrastructure.sqlite_store import SQLiteStore
from portman_v10.web.server import MAX_BATCH_FILES, create_app
from synthetic_pdf import make_text_pdf

BASE_URL = "http://127.0.0.1:8765"
HEADERS = {"Origin": BASE_URL}
PURCHASE = """comdirect
Wertpapierkauf
Depotnummer: 123456
Stk. 0,125 Fonds DE0008474511
Provision EUR 1,50
Zu Ihren Lasten EUR 126,50
Valuta {date}
DE00 0000 0000 0000 0000 01"""


def purchase_pdf(date):
    return make_text_pdf(PURCHASE.format(date=date))


class WebBatchImportTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        data_dir = Path(temporary.name)
        self.store = SQLiteStore(data_dir / "v10.sqlite")
        self.store.migrate()
        cash = self.store.save_account(AccountInput("comdirect Giro", "cash", "checking", "comdirect", "EUR",
                                                    identifiers=(AccountIdentifier("iban", "comdirect", "DE00000000000000000001"),)), None)
        self.store.save_account(AccountInput("comdirect Depot", "position", "depot", "comdirect", reference_account_id=cash.account_id,
                                             identifiers=(AccountIdentifier("depot_number", "comdirect", "123456"),)), None)
        self.store.save_instrument(InstrumentInput("Indexfonds", "fund", isin="DE0008474511"), None)
        self.workflow = ImportWorkflow(self.store, data_dir)
        self.addCleanup(self.workflow.close)
        self.client = create_app(self.workflow, profile="test-web").test_client()
        self.home = self.client.get("/", base_url=BASE_URL).get_data(as_text=True)
        self.token = re.search(r'name="_csrf_token" value="([^"]+)"', self.home).group(1)

    def _imports(self):
        return self.workflow.list_imports(None, 50).items

    def _finished_job(self, response):
        self.assertEqual(response.status_code, 303, response.get_data(as_text=True))
        job_id = response.headers["Location"].rsplit("/", 1)[-1]
        return self.workflow.wait(job_id, timeout=30)

    def _stage(self, name, content, token=None):
        return self.client.post("/documents", base_url=BASE_URL, headers=HEADERS, content_type="multipart/form-data",
                                data={"_csrf_token": self.token if token is None else token, "pdf": (BytesIO(content), name)})

    def _start(self, document_ids, token=None):
        return self.client.post("/imports/batch", base_url=BASE_URL, headers=HEADERS,
                                data={"_csrf_token": self.token if token is None else token, "document_id": list(document_ids)})

    def test_home_page_offers_multiple_selection_and_batch_endpoints(self):
        self.assertIn('type="file" accept="application/pdf,.pdf" multiple required', self.home)
        self.assertIn('data-documents-url="/documents"', self.home)
        self.assertIn('data-batch-url="/imports/batch"', self.home)
        self.assertIn('id="pdf-folder" type="file" webkitdirectory', self.home)

    def test_several_pdfs_in_one_request_become_one_import(self):
        response = self.client.post("/imports", base_url=BASE_URL, headers=HEADERS, content_type="multipart/form-data", data={
            "_csrf_token": self.token,
            "pdf": [(BytesIO(purchase_pdf("01.07.2026")), "kauf-1.pdf"), (BytesIO(purchase_pdf("02.07.2026")), "kauf-2.pdf")],
        })
        job = self._finished_job(response)
        self.assertEqual(job.document_count, 2)
        self.assertEqual([item.name for item in self.workflow.get_import_document_results(job.job_id)], ["kauf-1.pdf", "kauf-2.pdf"])
        self.assertEqual(len(self._imports()), 1)
        self.assertEqual(len(self.workflow.get_import_preview(job.import_id).items), 2)

    def test_one_invalid_file_in_a_request_imports_nothing(self):
        response = self.client.post("/imports", base_url=BASE_URL, headers=HEADERS, content_type="multipart/form-data", data={
            "_csrf_token": self.token,
            "pdf": [(BytesIO(purchase_pdf("01.07.2026")), "kauf.pdf"), (BytesIO(b"text"), "notiz.txt")],
        })
        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 400)
        self.assertIn("notiz.txt: Bitte eine Datei mit der Endung .pdf auswählen. Es wurde nichts importiert.", html)
        self.assertIn(f'value="{self.token}"', html, "Fehlerseite muss erneut absendbar sein")
        self.assertEqual(self._imports(), ())

    def test_staged_documents_start_one_common_import(self):
        first = self._stage("kauf-1.pdf", purchase_pdf("01.07.2026"))
        second = self._stage("kauf-2.pdf", purchase_pdf("02.07.2026"))
        again = self._stage("kauf-1-kopie.pdf", purchase_pdf("01.07.2026"))
        self.assertEqual((first.status_code, second.status_code, again.status_code), (201, 201, 201))
        self.assertFalse(first.get_json()["already_stored"])
        self.assertTrue(again.get_json()["already_stored"])
        self.assertEqual(again.get_json()["document_id"], first.get_json()["document_id"])
        self.assertEqual(self._imports(), (), "Ablegen allein startet keinen Import")

        ids = [first.get_json()["document_id"], second.get_json()["document_id"], again.get_json()["document_id"]]
        job = self._finished_job(self._start(ids))
        self.assertEqual(job.document_count, 2, "identische Datei zählt nur einmal")
        self.assertEqual(len(self._imports()), 1)

    def test_pdfs_larger_than_64_kib_are_accepted_on_both_upload_paths(self):
        # Regression: MAX_FORM_MEMORY_SIZE = 64 KiB ließ Werkzeug 3.1 jede PDF über ~64 KB mit 413 ablehnen.
        filler = "\n".join(f"Umsatzzeile {index:05d} 01.07.2026 Kartenzahlung -2,50 Verwendungszweck mit etwas Text" for index in range(4000))
        large = make_text_pdf(PURCHASE.format(date="01.07.2026") + "\n" + filler)
        self.assertGreater(len(large), 200 * 1024)
        staged = self._stage("finanzreport-gross.pdf", large)
        self.assertEqual(staged.status_code, 201, staged.get_data(as_text=True)[:300])
        direct = self.client.post("/imports", base_url=BASE_URL, headers=HEADERS, content_type="multipart/form-data",
                                  data={"_csrf_token": self.token, "pdf": (BytesIO(large), "finanzreport-gross.pdf")})
        self.assertEqual(direct.status_code, 303, direct.get_data(as_text=True)[:300])

    def test_too_many_parts_is_not_reported_as_50_mib(self):
        response = self.client.post("/imports", base_url=BASE_URL, headers=HEADERS, content_type="multipart/form-data", data={
            "_csrf_token": self.token, "pdf": [(BytesIO(b"%PDF-1.4"), f"klein-{index}.pdf") for index in range(MAX_BATCH_FILES + 10)]})
        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 413)
        self.assertIn(f"zu viele Dateien auf einmal (höchstens {MAX_BATCH_FILES})", html)
        self.assertNotIn("50 MiB", html.split('role="alert">', 1)[1].split("<", 1)[0])
        self.assertIn(f'data-max-files="{MAX_BATCH_FILES}"', self.home)

    def test_staging_rejects_invalid_files_with_a_json_message(self):
        for name, content, message in (("notiz.txt", b"text", "Endung .pdf"), ("leer.pdf", b"", "Datei ist leer")):
            with self.subTest(name=name):
                response = self._stage(name, content)
                self.assertEqual(response.status_code, 400)
                self.assertIn(message, response.get_json()["error"])

    def test_batch_start_validates_ids_and_limit(self):
        unknown = self._start(["fehlt"])
        self.assertEqual(unknown.status_code, 404)
        self.assertIn("Import nicht gestartet", unknown.get_data(as_text=True))
        self.assertEqual(self._start([]).status_code, 400)
        too_many = self._start([f"id-{index}" for index in range(MAX_BATCH_FILES + 1)])
        self.assertEqual(too_many.status_code, 400)
        self.assertIn(f"Höchstens {MAX_BATCH_FILES} PDF-Dateien", too_many.get_data(as_text=True))
        self.assertEqual(self._imports(), ())

    def test_batch_endpoints_require_session_token(self):
        self.assertEqual(self._stage("kauf.pdf", purchase_pdf("01.07.2026"), token="falsch").status_code, 403)
        staged = self._stage("kauf.pdf", purchase_pdf("01.07.2026")).get_json()["document_id"]
        self.assertEqual(self._start([staged], token="falsch").status_code, 403)
        self.assertEqual(self._imports(), ())


if __name__ == "__main__":
    unittest.main()
