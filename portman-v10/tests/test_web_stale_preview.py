from dataclasses import replace
from io import BytesIO
from pathlib import Path
import re
from tempfile import TemporaryDirectory
import unittest

from portman_v10.application.contracts import AccountIdentifier, AccountInput, InstrumentInput
from portman_v10.infrastructure.import_workflow import ImportWorkflow
from portman_v10.infrastructure.preview_codec import encode_preview
from portman_v10.infrastructure.sqlite_store import SQLiteStore
from portman_v10.web.server import create_app
from synthetic_pdf import make_text_pdf

BASE_URL = "http://127.0.0.1:8765"
PURCHASE_TEXT = """comdirect
Wertpapierkauf
Depotnummer: 123456
Stk. 0,125 Fonds DE0008474511
Provision EUR 1,50
Zu Ihren Lasten EUR 126,50
Valuta 01.07.2026
DE00 0000 0000 0000 0000 01"""


class StalePreviewTests(unittest.TestCase):
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
        page = self.client.get("/", base_url=BASE_URL).get_data(as_text=True)
        self.token = re.search(r'name="_csrf_token" value="([^"]+)"', page).group(1)
        self.headers = {"Origin": BASE_URL, "Referer": f"{BASE_URL}/jobs/x"}
        response = self.client.post("/imports", data={"_csrf_token": self.token, "pdf": (BytesIO(make_text_pdf(PURCHASE_TEXT)), "kauf.pdf")},
                                    content_type="multipart/form-data", base_url=BASE_URL, headers={"Origin": BASE_URL})
        self.job_url = response.headers["Location"]
        self.import_id = self.workflow.wait(self.job_url.rsplit("/", 1)[-1], timeout=15).import_id
        self._make_committable(self.import_id)

    def _make_committable(self, import_id):
        preview = self.workflow.get_import_preview(import_id)
        item = replace(preview.items[0], review_status="complete_candidate", missing_fields=(), warnings=(), conflicts=())
        self.store.replace_import_preview_items(import_id, preview.revision, encode_preview(replace(preview, items=(item,))))
        candidate = self.workflow.get_import_preview(import_id).items[0]
        self.client.post(f"/imports/{import_id}/review", base_url=BASE_URL, headers=self.headers, data={
            "_csrf_token": self.token, "candidate_id": candidate.candidate_id, "candidate_revision": candidate.revision, "decision": "accept"})

    def _change_data(self):
        self.store.save_account(AccountInput("Tagesgeld", "cash", "savings", "Andere Bank", "EUR"), None)

    def _events(self):
        connection = self.store.connect()
        try:
            return connection.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        finally:
            connection.close()

    def _commit(self, import_id):
        revision = self.workflow.get_import_preview(import_id).revision
        return self.client.post(f"/imports/{import_id}/commit", base_url=BASE_URL, headers=self.headers,
                                data={"_csrf_token": self.token, "preview_revision": revision, "request_id": f"web-{import_id}-{revision}"})

    def _refresh(self, import_id, token=None):
        return self.client.post(f"/imports/{import_id}/refresh", base_url=BASE_URL, headers=self.headers,
                                data={"_csrf_token": self.token if token is None else token})

    def test_current_preview_shows_no_warning(self):
        html = self.client.get(self.job_url, base_url=BASE_URL).get_data(as_text=True)
        self.assertNotIn('id="stale-preview"', html)
        self.assertIn('<button type="submit" >Übernehmen</button>', html)

    def test_changed_data_marks_preview_stale_and_locks_commit_button(self):
        self._change_data()
        html = self.client.get(self.job_url, base_url=BASE_URL).get_data(as_text=True)
        self.assertIn('id="stale-preview"', html)
        self.assertIn("Vorschau mit aktuellem Datenstand neu erstellen", html)
        self.assertIn("disabled>Übernehmen</button>", html)

    def test_stale_commit_is_explained_on_the_import_page_and_books_nothing(self):
        self._change_data()
        response = self._commit(self.import_id)
        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 409)
        self.assertIn('id="action-error"', html)
        self.assertIn("Seit dieser Vorschau wurde der Datenbestand geändert", html)
        self.assertIn(f'action="/imports/{self.import_id}/refresh"', html)
        self.assertEqual(self._events(), 0)

    def test_refresh_reads_the_same_documents_into_a_new_current_preview(self):
        old_preview = self.workflow.get_import_preview(self.import_id)
        old_job = self.workflow.get_job(self.job_url.rsplit("/", 1)[-1])
        old_document_ids = {item.document_id for item in self.workflow.get_import_document_results(old_job.job_id)}
        self._change_data()

        response = self._refresh(self.import_id)
        self.assertEqual(response.status_code, 303, response.get_data(as_text=True))
        new_job = self.workflow.wait(response.headers["Location"].rsplit("/", 1)[-1], timeout=15)
        self.assertNotEqual(new_job.import_id, self.import_id)
        self.assertEqual({item.document_id for item in self.workflow.get_import_document_results(new_job.job_id)}, old_document_ids)
        new_preview = self.workflow.get_import_preview(new_job.import_id)
        self.assertGreater(new_preview.data_revision, old_preview.data_revision)
        self.assertNotIn("duplicate_file", {item.review_status for item in new_preview.items})
        page = self.client.get(response.headers["Location"], base_url=BASE_URL).get_data(as_text=True)
        self.assertNotIn('id="stale-preview"', page)
        self.assertEqual(self.workflow.get_import_preview(self.import_id).revision, old_preview.revision)

        self._make_committable(new_job.import_id)
        self.assertEqual(self._commit(new_job.import_id).status_code, 303)
        self.assertEqual(self._events(), 1)

    def test_refresh_requires_session_token_and_an_open_import(self):
        self.assertEqual(self._refresh(self.import_id, token="falsch").status_code, 403)
        self.assertEqual(self._commit(self.import_id).status_code, 303)
        response = self._refresh(self.import_id)
        self.assertEqual(response.status_code, 409)
        self.assertIn("Dieser Import ist nicht mehr offen", response.get_data(as_text=True))
        self.assertEqual(self._refresh("unbekannt").status_code, 404)


if __name__ == "__main__":
    unittest.main()
