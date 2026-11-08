from io import BytesIO
from pathlib import Path
import re
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from portman_v10.application.contracts import AccountIdentifier, AccountInput, ApplicationError, ErrorCode
from portman_v10.infrastructure.import_workflow import ImportWorkflow
from portman_v10.infrastructure.sqlite_store import SQLiteStore
from portman_v10.web.server import create_app
from synthetic_pdf import make_text_pdf

BASE_URL = "http://127.0.0.1:8765"
REPORT = ("comdirect\nFinanzreport Nr. 124 per 01.07.2026\nGirokonto DE00000000000000000001\n"
          "01.07.2026 01.07.2026 Habenzinsen +10,00")
HAS_CORE_DISCARD = hasattr(ImportWorkflow, "discard_import")


class WebDiscardPreviewTests(unittest.TestCase):
    """Vorbereitet für den vorgeschlagenen Kernvertrag workflow.discard_import(import_id, expected_revision)."""

    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        data_dir = Path(temporary.name)
        self.store = SQLiteStore(data_dir / "v10.sqlite")
        self.store.migrate()
        self.store.save_account(AccountInput("Giro", "cash", "checking", "comdirect", "EUR",
                                             identifiers=(AccountIdentifier("iban", "comdirect", "DE00000000000000000001"),)), None)
        self.workflow = ImportWorkflow(self.store, data_dir)
        self.addCleanup(self.workflow.close)
        self.client = create_app(self.workflow, profile="test-web").test_client()
        home = self.client.get("/", base_url=BASE_URL).get_data(as_text=True)
        self.token = re.search(r'name="_csrf_token" value="([^"]+)"', home).group(1)
        self.headers = {"Origin": BASE_URL, "Referer": f"{BASE_URL}/imports"}
        self.job_url, self.import_id = self._upload("report-1.pdf", "Nr. 124")
        self.calls = []

    def _upload(self, name, number):
        response = self.client.post("/imports", data={"_csrf_token": self.token, "pdf": (BytesIO(make_text_pdf(REPORT.replace("Nr. 124", number))), name)},
                                    content_type="multipart/form-data", base_url=BASE_URL, headers={"Origin": BASE_URL})
        job_url = response.headers["Location"]
        return job_url, self.workflow.wait(job_url.rsplit("/", 1)[-1], timeout=15).import_id

    def _fake_discard(self, import_id, expected_revision):
        current = self.workflow.get_import_preview(import_id).revision
        if expected_revision != current:
            raise ApplicationError(ErrorCode.STALE_REVISION, "Vorschau-Revision ist veraltet")
        self.calls.append((import_id, expected_revision))

    def _with_core(self):
        return patch.object(ImportWorkflow, "discard_import", lambda workflow, import_id, revision: self._fake_discard(import_id, revision), create=True)

    def _post(self, data):
        return self.client.post("/imports/discard", base_url=BASE_URL, headers=self.headers, data={"_csrf_token": self.token, **data})

    @unittest.skipIf(HAS_CORE_DISCARD, "Datenkern bietet discard_import bereits an")
    def test_without_core_function_only_a_notice_is_shown(self):
        page = self.client.get(self.job_url, base_url=BASE_URL).get_data(as_text=True)
        self.assertIn("Vorschau verwerfen: noch nicht verfügbar", page)
        self.assertNotIn('name="discard_id"', page)
        self.assertNotIn('name="discard_id"', self.client.get("/imports", base_url=BASE_URL).get_data(as_text=True))
        response = self._post({"discard_id": self.import_id})
        self.assertEqual(response.status_code, 501)
        self.assertIn("discard_import noch nicht an", response.get_data(as_text=True))

    def test_job_page_discards_with_the_displayed_preview_revision(self):
        with self._with_core():
            page = self.client.get(self.job_url, base_url=BASE_URL).get_data(as_text=True)
            self.assertIn(">Vorschau verwerfen</button>", page)
            revision = re.search(r'name="expected_revision" value="(\d+)"', page[page.index('id="discard-area"'):]).group(1)
            response = self._post({"discard_id": self.import_id, "expected_revision": revision})
        self.assertEqual(response.status_code, 303, response.get_data(as_text=True))
        self.assertEqual(self.calls, [(self.import_id, int(revision))])
        notice = self.client.get(response.headers["Location"], base_url=BASE_URL).get_data(as_text=True)
        self.assertIn("1 Vorschau verworfen. Gebucht wurde nichts.", notice)

    def test_outdated_job_page_is_refused_on_the_import_page(self):
        with self._with_core():
            response = self._post({"discard_id": self.import_id, "expected_revision": "999"})
        self.assertEqual(response.status_code, 409)
        html = response.get_data(as_text=True)
        self.assertIn('id="action-error"', html)
        self.assertIn("Vorschau hat sich seit dem Laden der Seite geändert", html)
        self.assertEqual(self.calls, [])

    def test_list_selects_only_open_previews_separately_from_rollback(self):
        _, second = self._upload("report-2.pdf", "Nr. 125")
        with self._with_core():
            html = self.client.get("/imports", base_url=BASE_URL).get_data(as_text=True)
            self.assertEqual(html.count('name="discard_id"'), 2)
            self.assertNotIn('name="import_id" value="', html.split('id="import-list"', 1)[1].split("</table>", 1)[0],
                             "offene Vorschauen sind keine Rücknahmeauswahl")
            self.assertIn('formaction="/imports/discard"', html)
            response = self._post({"discard_id": [self.import_id, second]})
        self.assertEqual(response.status_code, 303)
        self.assertEqual({value[0] for value in self.calls}, {self.import_id, second})
        self.assertIn("2 Vorschauen verworfen", self.client.get(response.headers["Location"], base_url=BASE_URL).get_data(as_text=True))

    @unittest.skipUnless(HAS_CORE_DISCARD, "Datenkern bietet discard_import noch nicht an")
    def test_real_core_discard_marks_the_preview_and_keeps_documents(self):
        page = self.client.get(self.job_url, base_url=BASE_URL).get_data(as_text=True)
        revision = re.search(r'name="expected_revision" value="(\d+)"', page[page.index('id="discard-area"'):]).group(1)
        job_id = self.job_url.rsplit("/", 1)[-1]
        documents = {item.document_id for item in self.workflow.get_import_document_results(job_id)}

        stale = self._post({"discard_id": self.import_id, "expected_revision": str(int(revision) + 1)})
        self.assertEqual(stale.status_code, 409)
        response = self._post({"discard_id": self.import_id, "expected_revision": revision})
        self.assertEqual(response.status_code, 303, response.get_data(as_text=True))

        self.assertEqual(self.workflow.get_job(job_id).state, "cancelled")
        self.assertEqual({item.document_id for item in self.workflow.get_import_document_results(job_id)}, documents)
        listing = self.client.get("/imports", base_url=BASE_URL).get_data(as_text=True)
        self.assertIn("Abgebrochen/verworfen", listing)
        self.assertNotIn(f'name="discard_id" value="{self.import_id}"', listing)
        job_page = self.client.get(self.job_url, base_url=BASE_URL).get_data(as_text=True)
        self.assertIn("Vorschau verworfen – es wurde nichts gebucht", job_page)
        self.assertNotIn('id="discard-area"', job_page)
        again = self._post({"discard_id": self.import_id, "expected_revision": revision})
        self.assertEqual(again.status_code, 400)

    def test_list_offers_select_all_buttons_only_with_javascript(self):
        with self._with_core():
            html = self.client.get("/imports", base_url=BASE_URL).get_data(as_text=True)
        tools = html[html.index('id="selection-tools"') - 10:html.index("</p>", html.index('id="selection-tools"'))]
        self.assertIn("hidden", tools, "ohne JavaScript bleibt die Einzelauswahl")
        self.assertIn('type="button" data-select="discard_id"', tools)
        self.assertIn('type="button" data-select="import_id"', tools)
        nonce = re.search(r"script-src 'self' 'nonce-([^']+)'", self.client.get("/imports", base_url=BASE_URL).headers["Content-Security-Policy"])
        self.assertIsNotNone(nonce)
        self.assertEqual(len(re.findall(r'<script nonce="[^"]+">', html)), 2, "Seiten- und Basisskript tragen die Nonce")

    def test_discard_requires_selection_and_session_token(self):
        with self._with_core():
            self.assertEqual(self._post({}).status_code, 400)
            denied = self.client.post("/imports/discard", base_url=BASE_URL, headers=self.headers,
                                      data={"_csrf_token": "falsch", "discard_id": self.import_id})
        self.assertEqual(denied.status_code, 403)
        self.assertIn("Verwerfen abgelehnt", denied.get_data(as_text=True))
        self.assertEqual(self.calls, [])


if __name__ == "__main__":
    unittest.main()
