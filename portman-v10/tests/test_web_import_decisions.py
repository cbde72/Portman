from dataclasses import replace
from io import BytesIO
from pathlib import Path
import re
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from portman_v10.application.contracts import AccountIdentifier, AccountInput, ApplicationError, ErrorCode, InstrumentInput
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
HINT = "ohne Entscheidung"


class ImportDecisionFeedbackTests(unittest.TestCase):
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
        token_page = self.client.get("/", base_url=BASE_URL).get_data(as_text=True)
        self.token = re.search(r'name="_csrf_token" value="([^"]+)"', token_page).group(1)

        response = self.client.post("/imports", data={"_csrf_token": self.token, "pdf": (BytesIO(make_text_pdf(PURCHASE_TEXT)), "kauf.pdf")},
                                    content_type="multipart/form-data", base_url=BASE_URL, headers={"Origin": BASE_URL})
        self.job_url = response.headers["Location"]
        job = self.workflow.wait(self.job_url.rsplit("/", 1)[-1], timeout=15)
        self.import_id = job.import_id
        # Prüfbarer, vollständiger Kandidat wie in test_web_preview: Entscheidung ist der einzige offene Punkt.
        preview = self.workflow.get_import_preview(self.import_id)
        self.item = replace(preview.items[0], review_status="complete_candidate", missing_fields=(), warnings=(), conflicts=())
        self.preview = replace(preview, items=(self.item,))
        self.store.replace_import_preview_items(self.import_id, preview.revision, encode_preview(self.preview))
        self.headers = {"Origin": BASE_URL, "Referer": f"{BASE_URL}/jobs/x"}

    def _events(self):
        connection = self.store.connect()
        try:
            return connection.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        finally:
            connection.close()

    def _commit(self, request_id):
        revision = self.workflow.get_import_preview(self.import_id).revision
        return self.client.post(f"/imports/{self.import_id}/commit", base_url=BASE_URL, headers=self.headers,
                                data={"_csrf_token": self.token, "preview_revision": revision, "request_id": request_id})

    def test_undecided_candidate_is_marked_and_blocks_commit_button(self):
        html = self.client.get(self.job_url, base_url=BASE_URL).get_data(as_text=True)
        self.assertIn("Prüfen: Entscheidung fehlt", html)
        self.assertIn('id="undecided-hint"', html)
        self.assertIn("Noch 1 Kandidat ohne Entscheidung", html)
        self.assertIn("disabled>Übernehmen</button>", html)

    def test_needs_review_candidate_without_decision_buttons_gets_no_decision_hint(self):
        current = self.workflow.get_import_preview(self.import_id)
        item = replace(current.items[0], review_status="needs_review")
        self.store.replace_import_preview_items(self.import_id, current.revision, encode_preview(replace(current, items=(item,))))
        html = self.client.get(self.job_url, base_url=BASE_URL).get_data(as_text=True)
        self.assertIn("noch nicht zur Übernahme freigegeben", html)
        self.assertNotIn("Entscheidung fehlt", html)
        self.assertNotIn(HINT, html)
        self.assertIn("disabled>Übernehmen</button>", html)

    def test_commit_without_decision_reports_on_same_import_page_and_books_nothing(self):
        response = self._commit("web-no-decision")
        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 400)
        self.assertNotIn("Bad Request", html)
        self.assertIn('id="action-error"', html)
        self.assertIn("Übernahme nicht ausgeführt: Jeder Buchungskandidat muss ausdrücklich angenommen oder ignoriert werden", html)
        self.assertIn("Noch 1 Kandidat ohne Entscheidung – unten rot markiert.", html)
        self.assertIn("Importprüfung", html)
        self.assertIn("Kandidat prüfen / annehmen", html)
        self.assertEqual(self._events(), 0)

    def test_accepted_candidate_clears_hint_and_enables_commit(self):
        accepted = self.client.post(f"/imports/{self.import_id}/review", base_url=BASE_URL, headers=self.headers, data={
            "_csrf_token": self.token, "candidate_id": self.item.candidate_id, "candidate_revision": self.item.revision, "decision": "accept",
        })
        self.assertEqual(accepted.status_code, 303)
        html = self.client.get(self.job_url, base_url=BASE_URL).get_data(as_text=True)
        self.assertNotIn(HINT, html)
        self.assertNotIn("Entscheidung fehlt", html)
        self.assertIn("<button type=\"submit\" >Übernehmen</button>", html)

    def test_rejected_review_decision_is_reported_on_import_page(self):
        # Veraltete Vorschau entsteht nur bei gleichzeitiger Änderung; hier gezielt aus der Anwendungsschicht ausgelöst.
        stale = ApplicationError(ErrorCode.STALE_REVISION, "Vorschau-Revision ist veraltet")
        with patch.object(self.workflow, "resolve_import_item", side_effect=stale):
            response = self.client.post(f"/imports/{self.import_id}/review", base_url=BASE_URL, headers=self.headers, data={
                "_csrf_token": self.token, "candidate_id": self.item.candidate_id, "candidate_revision": self.item.revision, "decision": "accept",
            })
        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 409)
        self.assertIn('id="action-error"', html)
        self.assertIn("Prüfentscheidung nicht gespeichert: Vorschau-Revision ist veraltet", html)
        self.assertIn("Prüfen: Entscheidung fehlt", html)
        self.assertEqual(self.workflow.get_import_preview(self.import_id).decisions, ())


if __name__ == "__main__":
    unittest.main()
